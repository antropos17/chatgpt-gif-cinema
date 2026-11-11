"""Exact palette normalization of existing GIFs, with safe pixel-grid upscaling."""
import argparse
import io
import json
from pathlib import Path
import re
import tempfile

from PIL import Image

from . import cli, factory, layers, pixel_palette as codec

FORMAT = 'gif-cinema-pixel-export'
PALETTE_FORMAT = 'gif-cinema-palette'
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_PALETTE_BYTES = 16 * 1024
SCOPE = ('Exact canonical visible RGBA playback and integer nearest-neighbor scaling. '
         'RGB under zero alpha is normalized to zero. No quantization, recoloring, '
         'new drawings, motion repair or artistic approval. File bytes and ancillary '
         'GIF metadata are not preserved in the viewing copy; original source bytes are retained. '
         'Receipt consistency is not authentication, and viewer timing/color management may differ.')


def local_path(path):
    value = str(path)
    if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', value) and not re.match(r'^[A-Za-z]:[/\\]', value):
        raise ValueError('Pixel workflow requires local paths, not URLs')
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('Pixel workflow paths must not use symlinks')
    return path


def read_palette(raw):
    value = factory.parse_json(raw)
    layers.require_fields(value, ['format', 'schema_version', 'colors'],
                          ['format', 'schema_version', 'colors'], 'Palette')
    if value['format'] != PALETTE_FORMAT or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Require a schema-1 gif-cinema-palette')
    colors = value['colors']
    if not isinstance(colors, list) or len(colors) > 256:
        raise ValueError('Palette colors must be a list of 0..256 distinct #RRGGBB colors')
    result = []
    for color in colors:
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('Palette colors must be #RRGGBB strings')
        result.append(tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)))
    if len(set(result)) != len(result):
        raise ValueError('Palette colors must be distinct')
    return result


def palette_document(plan):
    return {'format': PALETTE_FORMAT, 'schema_version': 1,
            'colors': ['#%02x%02x%02x' % tuple(color) for color in plan['colors']]}


def load(path, scale, palette_path):
    source = local_path(path)
    raw = layers.read_regular(source, codec.MAX_BYTES)
    decoded = codec.decode(raw, scale=scale)
    requested_path = local_path(palette_path) if palette_path is not None else None
    requested_raw = layers.read_regular(requested_path, MAX_PALETTE_BYTES) if requested_path is not None else None
    colors = read_palette(requested_raw) if requested_raw is not None else None
    return source, raw, decoded, requested_path, requested_raw, colors


def inspect(path, scale=1, palette_path=None):
    _, raw, source, _, _, colors = load(path, scale, palette_path)
    return analyze(raw, source, scale, colors)


def analyze(raw, source, scale, colors):
    found = codec.audit(source['frames'])
    report = {'format': 'gif-cinema-pixel-analysis', 'schema_version': 1, 'provider_calls': 0,
        'source_sha256': layers.digest(raw), 'source_size': list(source['size']),
        'output_size': [side * scale for side in source['size']], 'scale': scale,
        'frames': len(source['frames']), 'delays_ms': source['delays_ms'],
        'duration_ms': sum(source['delays_ms']), 'loop': source['loop'],
        'source_local_color_tables': codec.inspect_tables(raw)['local_count'],
        'visible_color_count_lower_bound': found['color_count_lower_bound'],
        'color_count_is_exact': found['color_count_lower_bound'] < 257,
        'has_transparency': found['transparency'], 'visual_acceptance': 'not-established', 'scope': SCOPE}
    try:
        plan = codec.choose_palette(source['frames'], colors)
    except ValueError as exc:
        report.update(can_process_exactly=False, reason=str(exc))
    else:
        report.update(can_process_exactly=True, palette=palette_document(plan),
                      transparent_index=plan['transparent_index'])
    return report


def dump(path, value):
    raw = factory.json_bytes(value)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError('Pixel receipt exceeds the JSON byte budget')
    path.write_bytes(raw)


def file_inventory(root):
    files, total = {}, 0
    for index, path in enumerate(root.rglob('*'), 1):
        if index > 280:
            raise ValueError('Pixel bundle exceeds directory-entry budget')
        if path.is_symlink():
            raise ValueError('Pixel bundle must not contain symlinks')
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        if name == 'receipt.json':
            continue
        raw = layers.read_regular(path, codec.MAX_BYTES)
        total += len(raw)
        if total > MAX_OUTPUT_BYTES:
            raise ValueError('Pixel bundle exceeds aggregate output budget')
        files[name] = {'bytes': len(raw), 'sha256': layers.digest(raw)}
    return files


def scaled_frames(source, scale):
    return [frame.resize((frame.width * scale, frame.height * scale), Image.Resampling.NEAREST)
            for frame in source['frames']]


def review_images(frames, plan):
    first, last = frames[0], frames[-1]
    seam = Image.new('RGBA', (first.width * 2, first.height))
    seam.paste(last, (0, 0)); seam.paste(first, (first.width, 0))
    rows = max(1, (len(plan['colors']) + 15) // 16)
    swatches = Image.new('RGB', (256, rows * 16), '#202020')
    for index, color in enumerate(plan['colors']):
        x, y = index % 16 * 16, index // 16 * 16
        swatches.paste(tuple(color), (x, y, x + 16, y + 16))
    return {'loop-seam.png': seam, 'palette.png': swatches}


def receipt_for(raw, source, frames, plan, encoded_raw, scale, requested_raw):
    encoded = codec.decode(encoded_raw)
    tables = codec.inspect_tables(encoded_raw)
    expected_timeline = codec.timeline(frames, source['delays_ms'])
    if (encoded['size'] != frames[0].size or encoded['loop'] != source['loop']
            or codec.timeline(encoded['frames'], encoded['delays_ms']) != expected_timeline):
        raise ValueError('Encoded GIF differs from the exact visible source timeline or loop')
    if tables['local_count'] or tables['global_palette'] != bytes(plan['palette']):
        raise ValueError('Encoded GIF differs from the fixed global palette')
    samples, elapsed = [], 0
    for index, (frame, delay) in enumerate(zip(frames, source['delays_ms'])):
        samples.append({'file': f'frames/{index:04}.png', 'time_ms': elapsed,
                        'duration_ms': delay, 'rgba_sha256': layers.digest(frame.tobytes())})
        elapsed += delay
    return {'format': FORMAT, 'schema_version': 1, 'status': 'human-review-required',
        'provider_calls': 0, 'scale': scale,
        'source': {'sha256': layers.digest(raw), 'bytes': len(raw), 'size': list(source['size']),
            'frames': len(source['frames']), 'delays_ms': source['delays_ms'],
            'duration_ms': elapsed, 'loop': source['loop'],
            'local_color_tables': codec.inspect_tables(raw)['local_count']},
        'palette': {**palette_document(plan), 'transparent_index': plan['transparent_index'],
            'mode': 'authored-fixed-palette' if requested_raw is not None else 'exact-source-color-union',
            'requested_sha256': layers.digest(requested_raw) if requested_raw is not None else None},
        'output': {'size': list(encoded['size']), 'frames': len(encoded['frames']),
            'delays_ms': encoded['delays_ms'], 'duration_ms': sum(encoded['delays_ms']),
            'loop': encoded['loop'], 'timeline': expected_timeline, 'local_color_tables': 0,
            'global_palette_sha256': layers.digest(tables['global_palette'])},
        'frames': samples, 'visual_acceptance': 'not-established', 'scope': SCOPE}


def check_png(path, expected):
    raw = layers.read_regular(path, codec.MAX_BYTES)
    with Image.open(io.BytesIO(raw)) as image:
        if (image.format != 'PNG' or image.size != expected.size or image.mode != expected.mode
                or getattr(image, 'n_frames', 1) != 1):
            raise ValueError('Saved PNG format, dimensions or mode differs from expected pixels')
        if image.tobytes() != expected.tobytes():
            raise ValueError('Saved PNG pixels differ from the source-derived pixel render')


def verify(directory):
    root = local_path(directory)
    receipt = factory.parse_json(layers.read_regular(root / 'receipt.json', MAX_RECEIPT_BYTES))
    if (not isinstance(receipt, dict) or receipt.get('format') != FORMAT
            or type(receipt.get('schema_version')) is not int or receipt['schema_version'] != 1):
        raise ValueError('Invalid pixel receipt')
    scale = receipt.get('scale')
    inventory = file_inventory(root)
    if factory.json_bytes(receipt.get('files')) != factory.json_bytes(inventory):
        raise ValueError('Pixel bundle inventory or hashes changed')
    raw = layers.read_regular(root / 'source.gif', codec.MAX_BYTES)
    source = codec.decode(raw, scale=scale)
    requested_raw = (layers.read_regular(root / 'requested-palette.json', MAX_PALETTE_BYTES)
                     if 'requested-palette.json' in inventory else None)
    requested = read_palette(requested_raw) if requested_raw is not None else None
    plan = codec.choose_palette(source['frames'], requested)
    actual_palette = factory.parse_json(layers.read_regular(root / 'palette.json', MAX_PALETTE_BYTES))
    if factory.json_bytes(actual_palette) != factory.json_bytes(palette_document(plan)):
        raise ValueError('Palette document differs from source or authored palette')
    frames = scaled_frames(source, scale)
    expected = receipt_for(raw, source, frames, plan,
        layers.read_regular(root / 'preview.gif', codec.MAX_BYTES), scale, requested_raw)
    required = {'source.gif', 'palette.json', 'preview.gif', 'loop-seam.png', 'palette.png'}
    required.update(sample['file'] for sample in expected['frames'])
    if requested_raw is not None:
        required.add('requested-palette.json')
    if set(inventory) != required or set(receipt) != set(expected) | {'files'}:
        raise ValueError('Pixel bundle inventory is incomplete or unexpected')
    for key, value in expected.items():
        if factory.json_bytes(receipt.get(key)) != factory.json_bytes(value):
            raise ValueError(f'Pixel receipt {key} differs from recompiled source evidence')
    for sample, frame in zip(expected['frames'], frames):
        check_png(root / sample['file'], frame)
    for name, image in review_images(frames, plan).items():
        check_png(root / name, image)
    return {'status': 'verified', 'provider_calls': 0, 'frames_reopened_and_matched': len(frames),
        'source_frames': len(source['frames']), 'output_frames': expected['output']['frames'],
        'duration_ms': expected['output']['duration_ms'], 'loop': source['loop'], 'scale': scale,
        'visible_timeline_exact': True, 'local_color_tables': 0, 'files_verified': len(inventory),
        'visual_acceptance': 'not-established', 'scope': SCOPE}


def publish(stage, out):
    # No-clobber file links and a completion receipt published last. Never
    # delete public paths after failure: another writer could have replaced or
    # edited them. An interrupted publication leaves an inspectable partial
    # directory; it is not a successful build and must not be reused blindly.
    out.mkdir(exist_ok=False)
    (out / 'frames').mkdir()
    files = sorted((p for p in stage.rglob('*') if p.is_file()),
                   key=lambda p: (p.name == 'receipt.json', p.as_posix()))
    for path in files:
        cli.publish_file(path, out / path.relative_to(stage))


def build(path, out, scale=1, palette_path=None, dry_run=False):
    if type(dry_run) is not bool:
        raise ValueError('dry_run must be boolean')
    out = local_path(out)
    if out.exists():
        raise ValueError('Pixel output must be a new directory')
    source_path, raw, source, requested_path, requested_raw, colors = load(path, scale, palette_path)
    plan = codec.choose_palette(source['frames'], colors)
    if dry_run:
        return {**analyze(raw, source, scale, colors), 'status': 'planned'}
    out.parent.mkdir(parents=True, exist_ok=True)
    with cli.output_lock(out), tempfile.TemporaryDirectory(prefix='.pixel-stage-', dir=out.parent) as temporary:
        stage = Path(temporary) / 'bundle'; stage.mkdir(); (stage / 'frames').mkdir()
        (stage / 'source.gif').write_bytes(raw)
        if requested_raw is not None:
            (stage / 'requested-palette.json').write_bytes(requested_raw)
        dump(stage / 'palette.json', palette_document(plan))
        codec.encode(source['frames'], source['delays_ms'], source['loop'], plan, stage / 'preview.gif', scale)
        frames = scaled_frames(source, scale)
        for index, frame in enumerate(frames):
            frame.save(stage / 'frames' / f'{index:04}.png')
        for name, image in review_images(frames, plan).items():
            image.save(stage / name)
        receipt = receipt_for(raw, source, frames, plan,
                              layers.read_regular(stage / 'preview.gif', codec.MAX_BYTES), scale, requested_raw)
        receipt['files'] = file_inventory(stage)
        dump(stage / 'receipt.json', receipt)
        result = verify(stage)
        # A changed original cannot be published under its earlier identity.
        if layers.read_regular(source_path, codec.MAX_BYTES) != raw:
            raise ValueError('Source GIF changed during build')
        if requested_path is not None and layers.read_regular(requested_path, MAX_PALETTE_BYTES) != requested_raw:
            raise ValueError('Requested palette changed during build')
        publish(stage, out)
    return {**result, 'output': str(out), 'gif': str(out / 'preview.gif')}


def run(args):
    if args.pixel_command == 'verify':
        result = verify(args.directory)
    elif args.pixel_command == 'inspect':
        result = inspect(args.source, args.scale, args.palette)
    else:
        result = build(args.source, args.out, args.scale, args.palette, args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def add_parser(sub):
    parser = sub.add_parser('pixel', help='Inspect or normalize exact GIF palettes and pixel scaling')
    commands = parser.add_subparsers(dest='pixel_command', required=True)
    for name in ('inspect', 'build'):
        command = commands.add_parser(name)
        command.add_argument('source', type=Path)
        command.add_argument('--scale', type=int, default=1)
        command.add_argument('--palette', type=Path)
        if name == 'build':
            command.add_argument('--out', required=True, type=Path)
            command.add_argument('--dry-run', action='store_true')
        command.set_defaults(func=run)
    command = commands.add_parser('verify')
    command.add_argument('directory', type=Path)
    command.set_defaults(func=run)
