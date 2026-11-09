"""Bounded, offline sprite-sheet slicing and GIF-to-runtime-atlas export.

All poses share one crop and scale. This packages drawings; it never invents
character action, removes backgrounds, or asserts visual continuity.
"""
import hashlib
import io
import json
import math
from pathlib import Path
import stat
import tempfile

from PIL import Image, ImageSequence

MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_SHEET_PIXELS = 16 * 1024 * 1024
MAX_FRAME_PIXELS = 4 * 1024 * 1024
MAX_PIXEL_FRAMES = 32 * 1024 * 1024
MAX_FRAMES = 256
MAX_DURATION_MS = 120000
MAX_SPEC_BYTES = 1024 * 1024


def integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer in {low}..{high}")
    return value


def pair(value, label, low, high):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must be a two-integer list")
    return [integer(v, label, low, high) for v in value]


def read_bytes(path, limit):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"Input exceeds the {limit} byte limit")
    return raw


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def directory_identity(path):
    """Refuse renamed/replaced output directories between publication steps."""
    try:
        status = path.lstat()
    except OSError as exc:
        raise ValueError('Output directory changed during publication') from exc
    if not stat.S_ISDIR(status.st_mode):
        raise ValueError('Output directory changed during publication')
    return status.st_dev, status.st_ino


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def check_budget(size, count):
    width, height = size
    if width * height > MAX_FRAME_PIXELS:
        raise ValueError('Sprite frame exceeds the 4 megapixel limit')
    if count > MAX_FRAMES or width * height * count > MAX_PIXEL_FRAMES:
        raise ValueError('Sprite animation exceeds the frame or decoded pixel budget')


def validate_timing(delays, loop):
    for delay in delays:
        integer(delay, 'duration_ms', 20, 60000)
        if delay % 10:
            raise ValueError('duration_ms must be a multiple of 10 for exact GIF timing')
    if sum(delays) > MAX_DURATION_MS:
        raise ValueError('Sprite animation exceeds the 120 second duration limit')
    if loop is not None:
        integer(loop, 'loop', 0, 65535)


def load_sheet(spec_path):
    spec_path = Path(spec_path)
    spec = json.loads(read_bytes(spec_path, MAX_SPEC_BYTES).decode('utf-8'),
                      object_pairs_hook=reject_duplicate_keys)
    allowed = {'schema_version', 'atlas', 'grid', 'cells', 'duration_ms', 'loop',
               'crop', 'trim', 'scale', 'sampling', 'columns', 'padding', 'require_margin'}
    if not isinstance(spec, dict) or set(spec) - allowed:
        raise ValueError('Sprite spec must be an object with only documented fields')
    if type(spec.get('schema_version')) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    name = spec.get('atlas')
    if not isinstance(name, str) or not name.strip() or '://' in name:
        raise ValueError('atlas must be a local PNG path relative to the spec')
    columns, rows = pair(spec.get('grid'), 'grid', 1, MAX_FRAMES)
    if columns * rows > MAX_FRAMES:
        raise ValueError('Grid exceeds the 256 cell limit')
    source = spec_path.parent / name
    raw = read_bytes(source, MAX_INPUT_BYTES)
    with Image.open(io.BytesIO(raw)) as sheet:
        if sheet.format != 'PNG' or getattr(sheet, 'n_frames', 1) != 1:
            raise ValueError('atlas must be a still PNG, not an animation')
        if sheet.width * sheet.height > MAX_SHEET_PIXELS:
            raise ValueError('Atlas exceeds the 16 megapixel limit')
        if sheet.width % columns or sheet.height % rows:
            raise ValueError('Atlas dimensions must divide exactly by the declared grid')
        width, height = sheet.width // columns, sheet.height // rows
        cells = spec.get('cells', [[x, y] for y in range(rows) for x in range(columns)])
        if not isinstance(cells, list) or not 1 <= len(cells) <= MAX_FRAMES:
            raise ValueError('cells must contain 1..256 [column, row] pairs')
        rects = []
        for cell in cells:
            x, y = pair(cell, 'cell', 0, MAX_FRAMES - 1)
            if x >= columns or y >= rows:
                raise ValueError('Cell lies outside the declared grid')
            rects.append([x * width, y * height, width, height])
        check_budget((width, height), len(cells))
        delay = spec.get('duration_ms', 120)
        delays = delay if isinstance(delay, list) else [delay] * len(cells)
        if len(delays) != len(cells):
            raise ValueError('duration_ms list must match the selected cells')
        loop = spec.get('loop')
        validate_timing(delays, loop)
        sheet.load()
        rgba = sheet.convert('RGBA')
        frames = [rgba.crop((x, y, x + w, y + h)) for x, y, w, h in rects]
    metadata = {'kind': 'png-grid', 'file': source.name, 'sha256': digest(raw),
                'grid': [columns, rows], 'rectangles': rects}
    return frames, delays, loop, metadata, spec


def load_gif(path):
    from .cli import check_gif_limits
    raw = read_bytes(path, MAX_INPUT_BYTES)
    check_gif_limits(raw, max_frames=MAX_FRAMES, max_pixel_frames=MAX_PIXEL_FRAMES,
                     fixed_canvas=True)
    # GIF opening itself can allocate a disposal canvas. The shared preflight
    # establishes a fixed canvas; impose our tighter cap before Pillow opens it.
    check_budget((int.from_bytes(raw[6:8], 'little'), int.from_bytes(raw[8:10], 'little')), 1)
    frames, delays = [], []
    with Image.open(io.BytesIO(raw)) as gif:
        check_budget(gif.size, 1)
        check_budget(gif.size, gif.n_frames)
        loop = gif.info.get('loop')
        for frame in ImageSequence.Iterator(gif):
            frames.append(frame.convert('RGBA').copy())
            delays.append(frame.info.get('duration', 0))
    validate_timing(delays, loop)
    metadata = {'kind': 'gif', 'file': Path(path).name, 'sha256': digest(raw)}
    return frames, delays, loop, metadata


def transform(frames, options):
    """Use shared coordinates, never center/resize each pose independently."""
    scale = integer(options.get('scale', 1), 'scale', 1, 4)
    sampling = options.get('sampling', 'pixel')
    if sampling not in ('pixel', 'smooth'):
        raise ValueError('sampling must be pixel or smooth')
    trim = options.get('trim', False)
    if type(trim) is not bool:
        raise ValueError('trim must be a boolean')
    margin = integer(options.get('require_margin', 0), 'require_margin', 0, 256)
    width, height = frames[0].size
    bounds = [frame.getchannel('A').getbbox() for frame in frames]
    warnings = []
    if any(box is None for box in bounds):
        warnings.append('One or more selected poses are completely transparent.')
    if margin and any(box and (box[0] < margin or box[1] < margin or
                              box[2] > width - margin or box[3] > height - margin)
                      for box in bounds):
        raise ValueError('A selected pose violates require_margin; review sheet boundaries')
    crop = options.get('crop', [0, 0, width, height])
    if not isinstance(crop, list) or len(crop) != 4:
        raise ValueError('crop must be [x, y, width, height] in every cell')
    x, y, w, h = [integer(v, 'crop', 0, MAX_SHEET_PIXELS) for v in crop]
    if not w or not h or x + w > width or y + h > height:
        raise ValueError('crop lies outside the sprite cell')
    if trim and 'crop' in options:
        raise ValueError('Choose shared automatic trim or an explicit crop, not both')
    visible = [box for box in bounds if box]
    if trim and visible:
        x, y = min(b[0] for b in visible), min(b[1] for b in visible)
        w = max(b[2] for b in visible) - x
        h = max(b[3] for b in visible) - y
    if any(box and (box[0] < x or box[1] < y or box[2] > x + w or box[3] > y + h)
           for box in bounds):
        warnings.append('The explicit crop removes visible pixels. Inspect every output pose.')
    if any(frame.getchannel('A').getextrema()[0] != 0 for frame in frames):
        warnings.append('Some poses have no fully transparent background; no background removal was applied.')
    check_budget((w * scale, h * scale), len(frames))
    resampling = Image.Resampling.NEAREST if sampling == 'pixel' else Image.Resampling.LANCZOS
    result = []
    for frame in frames:
        cut = frame.crop((x, y, x + w, y + h))
        if scale != 1:
            cut = cut.resize((w * scale, h * scale), resampling)
        result.append(cut)
    return result, {'crop': [x, y, w, h], 'scale': scale, 'sampling': sampling,
                    'source_size': [width, height]}, warnings


def layout(frames, columns, padding):
    columns = integer(columns, 'columns', 1, MAX_FRAMES)
    padding = integer(padding, 'padding', 0, 64)
    columns = min(columns, len(frames))
    rows = math.ceil(len(frames) / columns)
    width, height = frames[0].size
    size = (columns * (width + 2 * padding), rows * (height + 2 * padding))
    if size[0] * size[1] > MAX_SHEET_PIXELS or max(size) > 16384:
        raise ValueError('Packed atlas exceeds the 16 megapixel or 16384 dimension limit')
    rects = [[(i % columns) * (width + 2 * padding) + padding,
              (i // columns) * (height + 2 * padding) + padding, width, height]
             for i in range(len(frames))]
    return size, rects


def write_preview(frames, delays, loop, path):
    """Shared palette, explicit binary alpha; PNGs remain the lossless source."""
    # Bounded palette training samples every pose, not just the first one.
    samples = Image.new('RGB', (64 * len(frames), 64))
    for i, frame in enumerate(frames):
        samples.paste(frame.convert('RGB').resize((64, 64), Image.Resampling.NEAREST), (i * 64, 0))
    palette = samples.quantize(colors=255)
    colors = palette.getpalette()[:765]
    palette.putpalette(colors + [0, 0, 0])
    encoded = []
    for frame in frames:
        indexed = frame.convert('RGB').quantize(palette=palette, dither=Image.Dither.NONE)
        # Palette entry 255 is reserved for transparent pixels. Re-map any
        # opaque black pixel that quantize chose from that unused entry.
        if indexed.getextrema()[1] == 255:
            fallback = min(range(255), key=lambda i: sum(c * c for c in colors[i*3:i*3+3]))
            indexed = indexed.point([*range(255), fallback])
        indexed.paste(255, mask=frame.getchannel('A').point(lambda a: 255 if a < 128 else 0))
        indexed.info['transparency'] = 255
        encoded.append(indexed)
    kwargs = {'loop': loop} if loop is not None else {}
    encoded[0].save(path, format='GIF', save_all=True, append_images=encoded[1:],
                    duration=delays, disposal=2, transparency=255, optimize=False, **kwargs)
    with Image.open(path) as decoded:
        actual = [int(frame.info.get('duration', 0)) for frame in ImageSequence.Iterator(decoded)]
        if sum(actual) != sum(delays) or decoded.info.get('loop') != loop:
            raise ValueError('Encoded GIF failed timing or loop verification')
    return {'file': 'animation.gif', 'decoded_frames': len(actual), 'durations_ms': actual,
            'duration_ms': sum(actual), 'loop': loop, 'alpha_threshold': 128,
            'note': 'Shared 255-color GIF palette with binary alpha; consecutive equal drawings may merge.'}


def export(frames, delays, loop, source, options, out, *, dry_run=False):
    frames, transform_info, warnings = transform(frames, options)
    size, rects = layout(frames, options.get('columns', 8), options.get('padding', 1))
    warnings += ['Character identity, alignment, clipped edges and loop continuity require human review.',
                 'GIF preview has binary alpha and limited color; PNG frames and atlas preserve RGBA.']
    hashes = [digest(frame.tobytes()) for frame in frames]
    duplicates = [i for i in range(1, len(hashes)) if hashes[i] == hashes[i - 1]]
    if duplicates:
        warnings.append('Consecutive duplicate drawings are held poses, not new motion.')
    report = {'schema_version': 1, 'api_calls': 0, 'source': source,
              'transform': transform_info, 'frame_count': len(frames),
              'duration_ms': sum(delays), 'loop': loop, 'atlas': 'atlas.png',
              'atlas_size': list(size), 'padding': options.get('padding', 1),
              'consecutive_duplicate_indices': duplicates,
              'review_status': 'human-review-required', 'warnings': warnings,
              'frame_layout': [{'index': i, 'file': f'frames/{i:04d}.png',
                                'rect': rect, 'duration_ms': delays[i], 'rgba_sha256': hashes[i]}
                               for i, rect in enumerate(rects)]}
    if dry_run:
        return report
    target = Path(out).absolute()
    if target.exists() or target.is_symlink():
        raise ValueError('Output directory must be new; accepted assets are never overwritten')
    target.parent.mkdir(parents=True, exist_ok=True)
    from .cli import output_lock, publish_file
    with output_lock(target), tempfile.TemporaryDirectory(prefix='.sprites-', dir=target.parent) as tmp:
        stage = Path(tmp)
        (stage / 'frames').mkdir()
        atlas = Image.new('RGBA', size)
        for i, (frame, rect) in enumerate(zip(frames, rects)):
            frame.save(stage / f'frames/{i:04d}.png')
            atlas.paste(frame, tuple(rect[:2]))
        atlas.save(stage / 'atlas.png')
        report['preview'] = write_preview(frames, delays, loop, stage / 'animation.gif')
        report['files_sha256'] = {p.relative_to(stage).as_posix(): digest(p.read_bytes())
                                  for p in sorted(stage.rglob('*')) if p.is_file()}
        (stage / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        # Reserve the directory atomically, then publish no-clobber files.
        # The manifest is the completion marker and is always published last.
        # Once published, files are never removed on failure: another process
        # may already have replaced or started using them. A partial directory
        # without a manifest is explicitly incomplete, not an accepted export.
        target.mkdir()
        target_identity = directory_identity(target)
        (target / 'frames').mkdir()
        frames_identity = directory_identity(target / 'frames')
        files = sorted(p for p in stage.rglob('*') if p.is_file() and p.name != 'manifest.json')
        for path in files + [stage / 'manifest.json']:
            if (directory_identity(target) != target_identity or
                    directory_identity(target / 'frames') != frames_identity):
                raise ValueError('Output directory changed during publication')
            publish_file(path, target / path.relative_to(stage))
    return report


def run_slice(args):
    frames, delays, loop, source, options = load_sheet(args.spec)
    print(json.dumps(export(frames, delays, loop, source, options, args.out,
                            dry_run=args.dry_run), indent=2))


def run_pack(args):
    frames, delays, loop, source = load_gif(args.gif)
    options = {name: getattr(args, name) for name in ('columns', 'padding', 'trim', 'scale', 'sampling')}
    print(json.dumps(export(frames, delays, loop, source, options, args.out,
                            dry_run=args.dry_run), indent=2))


def add_parser(subparsers):
    root = subparsers.add_parser('sprites', help='Offline PNG sheet slicing and GIF-to-atlas export')
    commands = root.add_subparsers(dest='sprite_command', required=True)
    slicing = commands.add_parser('slice', help='Render selected PNG grid cells from a JSON spec')
    slicing.add_argument('spec', type=Path)
    slicing.set_defaults(func=run_slice)
    packing = commands.add_parser('pack', help='Pack existing GIF drawings into a lossless RGBA atlas')
    packing.add_argument('gif', type=Path)
    packing.add_argument('--columns', type=int, default=8)
    packing.add_argument('--padding', type=int, default=1)
    packing.add_argument('--trim', action='store_true', help='Trim one shared alpha bound, never each pose separately')
    packing.add_argument('--scale', type=int, default=1)
    packing.add_argument('--sampling', choices=('pixel', 'smooth'), default='pixel')
    packing.set_defaults(func=run_pack)
    for parser in (slicing, packing):
        parser.add_argument('--out', type=Path, required=True)
        parser.add_argument('--dry-run', action='store_true', help='Validate and print coordinates; no writes or network')
