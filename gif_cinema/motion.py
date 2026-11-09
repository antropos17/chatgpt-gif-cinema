"""Deterministic, offline motion recipes. Sources and accepted takes are immutable."""
import bisect
import copy
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run_command(command, commands):
    from .cli import run_media
    commands.append(command)
    return run_media(command).stdout


def mae(left, right):
    from PIL import ImageChops, ImageStat
    return sum(ImageStat.Stat(ImageChops.difference(left, right)).mean) / 3


MAX_BYTES = 32 * 1024 * 1024
MAX_RECIPE_BYTES = 64 * 1024
MAX_SOURCE_PIXELS = 4 * 1024 * 1024
MAX_SOURCE_PIXEL_FRAMES = 64 * 1024 * 1024
MAX_FRAMES = 1500
MAX_PIXEL_FRAMES = 160 * 1024 * 1024
MAX_ATLAS_PIXELS = 16 * 1024 * 1024
EASINGS = ('linear', 'ease-in', 'ease-out', 'ease-in-out', 'smootherstep', 'step')
TRANSFORM_DEFAULTS = {'x': .5, 'y': .5, 'zoom': 1, 'rotation': 0, 'opacity': 1}
PRESETS = {
    'identity': [{ 'at': 0 }, { 'at': 1 }],
    'push-in': [{'at': 0, 'easing': 'ease-in-out'}, {'at': 1, 'zoom': 1.15}],
    'pan-left': [{'at': 0, 'zoom': 1.2, 'x': .6, 'easing': 'ease-in-out'},
                 {'at': 1, 'x': .4}],
    'pop-in': [{'at': 0, 'zoom': .75, 'opacity': 0, 'easing': 'ease-out'},
               {'at': .3, 'zoom': 1.06, 'opacity': 1, 'easing': 'ease-in-out'},
               {'at': .5, 'zoom': 1}, {'at': 1}],
}


def number(value, label, low, high, integer=False):
    if (type(value) not in (int, float) or not low <= value <= high or
            not math.isfinite(value) or (integer and type(value) is not int)):
        raise ValueError(f'{label} must be {"an integer" if integer else "a finite number"} in {low}..{high}')
    return value


def read_bounded(path, limit):
    """Read a bounded regular-file snapshot without blocking on special files."""
    if not stat.S_ISREG(os.stat(path).st_mode):
        raise ValueError('Input must be a regular local file')
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    flags |= getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('Input must be a regular local file')
        with os.fdopen(descriptor, 'rb', closefd=False) as handle:
            data = handle.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f'Input exceeds {limit} byte limit')
        return data
    finally:
        os.close(descriptor)


def load_recipe(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate recipe field: {key}')
            result[key] = value
        return result
    try:
        value = json.loads(read_bounded(path, MAX_RECIPE_BYTES).decode('utf-8-sig'),
                           object_pairs_hook=unique)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Recipe must be bounded UTF-8 JSON') from exc
    return value


def normalize_recipe(value, source_size):
    defaults = {'schema_version': 1, 'fps': 25, 'width': source_size[0] + source_size[0] % 2,
                'height': source_size[1] + source_size[1] % 2, 'fit': 'contain',
                'background': '#101018', 'trim_start_ms': 0, 'trim_end_ms': None,
                'speed': 1, 'playback': 'forward', 'repeats': 1, 'hold_start_ms': 0,
                'hold_end_ms': 0, 'still_duration_ms': 2000, 'spritesheet': False,
                'keyframes': PRESETS['identity']}
    if not isinstance(value, dict) or set(value) - set(defaults):
        raise ValueError('Recipe must be an object with known fields only')
    config = copy.deepcopy(defaults)
    config.update(copy.deepcopy(value))
    number(config['schema_version'], 'schema_version', 1, 1, True)
    number(config['fps'], 'fps', 25, 50, True)
    if config['fps'] not in (25, 50):
        raise ValueError('fps must be 25 or 50 for exact GIF timing')
    for name in ('width', 'height'):
        number(config[name], name, 2, 2048, True)
        if config[name] % 2:
            raise ValueError('Canvas dimensions must be even')
    for name, choices in (('fit', ('contain', 'cover')),
                          ('playback', ('forward', 'reverse', 'ping-pong'))):
        if config[name] not in choices:
            raise ValueError(f'{name} must be one of {choices}')
    if not isinstance(config['background'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', config['background']):
        raise ValueError('background must be #RRGGBB; PNG frames retain transparency')
    number(config['speed'], 'speed', .1, 8)
    number(config['repeats'], 'repeats', 1, 16, True)
    number(config['still_duration_ms'], 'still_duration_ms', 40, 30000, True)
    for name in ('trim_start_ms', 'hold_start_ms', 'hold_end_ms'):
        number(config[name], name, 0, 300000 if name == 'trim_start_ms' else 10000, True)
    if config['trim_end_ms'] is not None:
        number(config['trim_end_ms'], 'trim_end_ms', 1, 300000, True)
    if type(config['spritesheet']) is not bool:
        raise ValueError('spritesheet must be true or false')
    keys = config['keyframes']
    if not isinstance(keys, list) or not 2 <= len(keys) <= 32:
        raise ValueError('Require 2..32 keyframes')
    previous = dict(TRANSFORM_DEFAULTS)
    normalized = []
    for key in keys:
        if not isinstance(key, dict) or 'at' not in key or set(key) - set(TRANSFORM_DEFAULTS) - {'at', 'easing'}:
            raise ValueError('Keyframe requires at and only known transform fields')
        number(key['at'], 'keyframe.at', 0, 1)
        if normalized and key['at'] <= normalized[-1]['at']:
            raise ValueError('Keyframe times must be strictly increasing')
        result = {**previous, **key, 'easing': key.get('easing', 'linear')}
        for name, low, high in (('x', -2, 3), ('y', -2, 3), ('zoom', .1, 8),
                                ('rotation', -3600, 3600), ('opacity', 0, 1)):
            number(result[name], f'keyframe.{name}', low, high)
        if result['easing'] not in EASINGS:
            raise ValueError(f'Unknown easing; choose from {EASINGS}')
        normalized.append(result)
        previous = {name: result[name] for name in TRANSFORM_DEFAULTS}
    if normalized[0]['at'] != 0 or normalized[-1]['at'] != 1:
        raise ValueError('Keyframes must include endpoints at 0 and 1')
    config['keyframes'] = normalized
    return config


def build_timeline(delays, recipe):
    if not delays or any(type(delay) is not int or delay < 20 for delay in delays):
        raise ValueError('Source delays must be integer milliseconds of at least 20 ms')
    start = recipe['trim_start_ms']
    end = sum(delays) if recipe['trim_end_ms'] is None else recipe['trim_end_ms']
    if not 0 <= start < end <= sum(delays):
        raise ValueError('Trim must select a nonempty interval within source duration')
    elapsed = 0
    segments = []
    for index, delay in enumerate(delays):
        overlap = min(end, elapsed + delay) - max(start, elapsed)
        if overlap > 0:
            segments.append({'source_index': index, 'duration_ms': Fraction(overlap) / Fraction(str(recipe['speed']))})
        elapsed += delay
    if recipe['playback'] == 'reverse':
        segments.reverse()
    elif recipe['playback'] == 'ping-pong':
        # The terminal and initial holds occur only once per cycle, including repeated cycles.
        segments += list(reversed(segments[1:-1]))
    segments *= recipe['repeats']
    segments = copy.deepcopy(segments)
    if recipe['hold_start_ms']:
        segments.insert(0, {'source_index': segments[0]['source_index'], 'duration_ms': Fraction(recipe['hold_start_ms'])})
    if recipe['hold_end_ms']:
        segments.append({'source_index': segments[-1]['source_index'], 'duration_ms': Fraction(recipe['hold_end_ms'])})
    duration = sum(segment['duration_ms'] for segment in segments)
    count = round(duration * recipe['fps'] / 1000)
    if count < 2:
        raise ValueError('Timeline needs at least two output frames; lower speed or use 50 FPS')
    if count > MAX_FRAMES or count * recipe['width'] * recipe['height'] > MAX_PIXEL_FRAMES:
        raise ValueError('Timeline exceeds bounded frame/pixel budget')
    # Keep rational boundaries for sampling. Float receipt values alone can put
    # a frame-center that is exactly on a boundary into the preceding drawing.
    ticks_per_ms = math.lcm(*(segment['duration_ms'].denominator for segment in segments))
    elapsed_ticks, end_ticks = 0, []
    for segment in segments:
        exact = segment['duration_ms']
        elapsed_ticks += exact.numerator * (ticks_per_ms // exact.denominator)
        end_ticks.append(elapsed_ticks)
    for segment in segments:
        segment['duration_ms'] = float(segment['duration_ms'])
    atlas = None
    if recipe['spritesheet']:
        width, height = recipe['width'], recipe['height']
        grids = [(columns, math.ceil(count / columns))
                 for columns in range(1, min(count, 8192 // width) + 1)]
        grids = [(columns, rows) for columns, rows in grids
                 if rows * height <= 8192 and rows * height * columns * width <= MAX_ATLAS_PIXELS]
        if not grids:
            raise ValueError('Spritesheet exceeds 8192px/16-megapixel limit; reduce dimensions/duration or disable spritesheet')
        # Minimize empty cells, then prefer a compact shape. A near-square guess
        # alone can exceed the pixel budget while another integer grid fits.
        columns, rows = min(grids, key=lambda grid: (grid[0] * grid[1], abs(grid[0] * width - grid[1] * height), grid[0]))
        atlas = {'columns': columns, 'rows': rows, 'width': columns * width, 'height': rows * height}
    actual = count * 1000 // recipe['fps']
    return {'segments': segments, 'duration_ms': float(duration), 'playback_frames': count,
            'output_duration_ms': actual, 'duration_quantization_ms': float(actual - duration),
            'exact_timing': {'ticks_per_ms': ticks_per_ms, 'segment_end_ticks': end_ticks},
            'spritesheet': atlas}


def sample_timeline(timeline, frame_number):
    count = timeline['playback_frames']
    if type(frame_number) is not int or not 0 <= frame_number < count:
        raise ValueError('Output frame index is outside the timeline')
    segments = timeline['segments']
    if frame_number == 0:
        return segments[0]['source_index']
    if frame_number == count - 1:
        return segments[-1]['source_index']
    if 'exact_timing' in timeline:
        ends = timeline['exact_timing']['segment_end_ticks']
        sample = Fraction((2 * frame_number + 1) * ends[-1], 2 * count)
        index = min(len(segments) - 1, bisect.bisect_right(ends, sample))
        return segments[index]['source_index']
    # Compatibility for callers passing a legacy, float-only timeline.
    sample = (frame_number + .5) * timeline['duration_ms'] / count
    elapsed = 0
    for segment in segments:
        elapsed += segment['duration_ms']
        if sample < elapsed:
            return segment['source_index']
    return segments[-1]['source_index']


def evaluate_keyframes(keyframes, progress):
    number(progress, 'progress', 0, 1)
    index = max(0, bisect.bisect_right([key['at'] for key in keyframes], progress) - 1)
    left = keyframes[index]
    if index == len(keyframes) - 1:
        return {name: left[name] for name in TRANSFORM_DEFAULTS}
    right = keyframes[index + 1]
    value = (progress - left['at']) / (right['at'] - left['at'])
    easing = left['easing']
    if easing == 'ease-in':
        value *= value
    elif easing == 'ease-out':
        value = 1 - (1 - value) ** 2
    elif easing == 'ease-in-out':
        value = value * value * (3 - 2 * value)
    elif easing == 'smootherstep':
        # Quintic easing has zero first and second derivative at both ends.
        value = value ** 3 * (value * (value * 6 - 15) + 10)
    elif easing == 'step':
        value = 0
    return {name: left[name] + (right[name] - left[name]) * value for name in TRANSFORM_DEFAULTS}


def render_frame(source_rgba, recipe, transform):
    from PIL import Image
    width, height = recipe['width'], recipe['height']
    source_width, source_height = source_rgba.size
    fit = min if recipe['fit'] == 'contain' else max
    scale = fit(width / source_width, height / source_height) * transform['zoom']
    angle = math.radians(transform['rotation'])
    a, b = math.cos(angle) / scale, math.sin(angle) / scale
    d, e = -b, a
    cx, cy = transform['x'] * width, transform['y'] * height
    matrix = (a, b, source_width / 2 - a * cx - b * cy,
              d, e, source_height / 2 - d * cx - e * cy)
    # Premultiplied alpha prevents dark RGB fringes during subpixel transforms.
    result = source_rgba.convert('RGBa').transform((width, height), Image.Transform.AFFINE,
                  matrix, resample=Image.Resampling.BICUBIC).convert('RGBA')
    if transform['opacity'] != 1:
        result.putalpha(result.getchannel('A').point(lambda alpha: round(alpha * transform['opacity'])))
    result.info.clear()
    return result


def decode_source(raw, still_duration):
    from PIL import Image, ImageOps, ImageSequence
    if len(raw) > MAX_BYTES:
        raise ValueError('Source exceeds 32 MiB byte limit')
    if raw[:6] in (b'GIF87a', b'GIF89a'):
        from .cli import check_gif_limits
        stats = check_gif_limits(raw)
        if stats['width'] * stats['height'] > MAX_SOURCE_PIXELS:
            raise ValueError('Source exceeds 4 megapixel frame limit')
        if stats['frames'] > 512 or stats['pixel_frames'] > MAX_SOURCE_PIXEL_FRAMES:
            raise ValueError('Source exceeds decoded drawing/pixel budget')
        if stats['canvas_expanded']:
            raise ValueError('GIF frame descriptors must stay within a fixed logical canvas')
    frames, delays = [], []
    with Image.open(io.BytesIO(raw)) as source:
        if source.format not in ('GIF', 'PNG', 'JPEG', 'WEBP') or source.width * source.height > MAX_SOURCE_PIXELS:
            raise ValueError('Source must be GIF or still PNG/JPEG/WebP, at most 4 megapixels')
        if source.format != 'GIF' and getattr(source, 'n_frames', 1) != 1:
            raise ValueError('Animated PNG/WebP unsupported; use GIF or a still image')
        source_format = source.format
        source_size = source.size
        pixels = 0
        for frame in ImageSequence.Iterator(source):
            frame_pixels = frame.width * frame.height
            if frame_pixels > MAX_SOURCE_PIXELS:
                raise ValueError('Source exceeds 4 megapixel frame limit')
            if source_format == 'GIF' and frame.size != source_size:
                raise ValueError('GIF frames must keep a fixed logical canvas')
            if len(frames) >= 512 or pixels + frame_pixels > MAX_SOURCE_PIXEL_FRAMES:
                raise ValueError('Source exceeds decoded drawing/pixel budget')
            if source_format != 'GIF':
                # Normalize the display orientation before recipe defaults and
                # transforms. Transpose preserves pixels/alpha, not metadata.
                frame = ImageOps.exif_transpose(frame)
            frames.append(frame.convert('RGBA').copy())
            delays.append(int(frame.info.get('duration', 0)))
            pixels += frame_pixels
    if len(frames) == 1:
        delays = [still_duration]
    elif any(delay < 20 for delay in delays):
        raise ValueError('Source frame delays must be at least 20 ms')
    for frame in frames:
        frame.info.clear()
    return frames, delays, source_format


def flatten(frame, background):
    from PIL import Image
    canvas = Image.new('RGBA', frame.size, background)
    canvas.alpha_composite(frame)
    return canvas.convert('RGB')


def palette_row(frame):
    """Collect bounded full-resolution colors without averaging away fine marks.

    Reserve one sample for every color when there are at most 256; otherwise use
    the frame's full-resolution median-cut representatives. Remaining samples
    follow pixel frequency. A clip with <=256 distinct RGB colors retains them
    all in its shared palette, including isolated one-pixel accents.
    """
    from PIL import Image
    colors = frame.getcolors(256)
    if colors is None:
        reduced = frame.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        palette = reduced.getpalette()
        colors = [(amount, tuple(palette[index * 3:index * 3 + 3]))
                  for amount, index in reduced.getcolors()]
    colors = sorted(colors, key=lambda item: item[1])
    remaining = 256 - len(colors)
    total = frame.width * frame.height
    amounts = [1 + remaining * amount // total for amount, _ in colors]
    left = 256 - sum(amounts)
    order = sorted(range(len(colors)), key=lambda i: (-(remaining * colors[i][0] % total), colors[i][1]))
    for index in order[:left]:
        amounts[index] += 1
    row = Image.new('RGB', (256, 1))
    row.putdata([color for count, (_, color) in zip(amounts, colors) for _ in range(count)])
    return row


def quantize_shared(frame, palette):
    """Use exact index remapping when all actual frame colors fit the palette.

    Pillow's fixed-palette RGB lookup uses a coarse color cache, which can merge
    nearby colors even when both are present. Indexed remapping avoids that loss.
    """
    from PIL import Image
    colors = frame.getcolors(256)
    values = palette.getpalette()
    lookup = {tuple(values[i:i + 3]): i // 3 for i in range(0, len(values), 3)}
    if colors is not None and all(color in lookup for _, color in colors):
        indexed = frame.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        local_palette = indexed.getpalette()
        mapping = [0] * 256
        for _, index in indexed.getcolors():
            mapping[index] = lookup[tuple(local_palette[index * 3:index * 3 + 3])]
        result = indexed.point(mapping)
        result.putpalette(values)
        return result
    return frame.quantize(palette=palette, dither=Image.Dither.NONE)


def motion(source, out, recipe=None, preset=None, dry_run=False):
    import PIL
    from PIL import Image, ImageDraw, ImageSequence
    if preset is not None and preset not in PRESETS:
        raise ValueError('Unknown motion preset')
    if recipe is not None and preset is not None:
        raise ValueError('Choose a recipe or preset, not both')
    value = copy.deepcopy(recipe) if recipe is not None else {}
    if preset is not None:
        value['keyframes'] = PRESETS[preset]
    if not isinstance(value, dict):
        raise ValueError('Recipe must be an object')
    still_duration = value.get('still_duration_ms', 2000)
    number(still_duration, 'still_duration_ms', 40, 30000, True)
    source = Path(source).resolve()
    raw = read_bounded(source, MAX_BYTES)
    frames, delays, source_format = decode_source(raw, still_duration)
    config = normalize_recipe(value, frames[0].size)
    timeline = build_timeline(delays, config)
    count, step = timeline['playback_frames'], 1000 // config['fps']
    samples = [{'frame': i, 'time_ms': i * step, 'source_index': sample_timeline(timeline, i),
                'transform': evaluate_keyframes(config['keyframes'], i / (count - 1))} for i in range(count)]
    used = {row['source_index'] for row in samples}
    selected = {segment['source_index'] for segment in timeline['segments']}
    plan = {'schema_version': 1, 'status': 'planned', 'api_calls': 0,
            'source_sha256': sha(raw), 'source_format': source_format, 'source_drawings': len(frames),
            'source_duration_ms': sum(delays), 'recipe': config, 'timeline': timeline,
            'omitted_source_drawings': sorted(selected - used),
            'sampling': 'center of uniformly retimed bins; first/last source poses retained',
            'keyframe_timing': 'normalized across the whole output, including repeats and holds'}
    if dry_run:
        return plan
    out = Path(out).absolute()
    if any(path.is_symlink() for path in (out, *out.parents)) or out.exists():
        raise ValueError('Output must be a new directory without symlinks; no overwrite or resume')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('Installed FFmpeg and ffprobe are required; use --dry-run to plan without them')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(exist_ok=False)
    commands = []
    with tempfile.TemporaryDirectory(prefix='.stage-', dir=out) as temporary:
        stage = Path(temporary)
        rgba_dir, preview_dir = stage / 'frames', stage / 'preview'
        rgba_dir.mkdir(); preview_dir.mkdir()
        # One shared palette across the clip avoids per-frame palette instability.
        palette_samples = Image.new('RGB', (256, count))
        sheet = Image.new('RGB', (5 * 192, 220), config['background'])
        selected_frames = [round(i * (count - 1) / 4) for i in range(5)]
        atlas = Image.new('RGBA', (timeline['spritesheet']['width'], timeline['spritesheet']['height'])) if timeline['spritesheet'] else None
        atlas_rows = []
        for row in samples:
            index = row['frame']
            frame = render_frame(frames[row['source_index']], config, row['transform'])
            frame_path = rgba_dir / f'{index:04}.png'
            frame.save(frame_path)
            row['rgba_sha256'] = sha(frame.tobytes())
            row['png_sha256'] = sha(frame_path.read_bytes())
            preview = flatten(frame, config['background'])
            preview.save(preview_dir / f'{index:04}.png')
            palette_samples.paste(palette_row(preview), (0, index))
            if index in selected_frames:
                thumb = preview.copy(); thumb.thumbnail((192, 192))
                for column, selected_index in enumerate(selected_frames):
                    if selected_index == index:
                        sheet.paste(thumb, (column * 192 + (192 - thumb.width) // 2, (192 - thumb.height) // 2))
                        ImageDraw.Draw(sheet).text((column * 192 + 5, 198), f'{index * step} ms / source {row["source_index"]}', fill='white')
            if atlas is not None:
                x = (index % timeline['spritesheet']['columns']) * config['width']
                y = (index // timeline['spritesheet']['columns']) * config['height']
                atlas.paste(frame, (x, y))
                atlas_rows.append({'filename': f'frames/{index:04}.png', 'frame': {'x': x, 'y': y, 'w': config['width'], 'h': config['height']},
                                   'duration_ms': step, 'source_index': row['source_index'], 'rotated': False, 'trimmed': False})
        sheet.save(stage / 'contact-sheet.png')
        shutil.copyfile(rgba_dir / '0000.png', stage / 'first.png')
        shutil.copyfile(rgba_dir / f'{count - 1:04}.png', stage / 'last.png')
        # Make the wraparound visible without claiming an automatic aesthetic pass.
        with Image.open(preview_dir / '0000.png') as first, Image.open(preview_dir / f'{count - 1:04}.png') as last:
            seam = Image.new('RGB', (config['width'] * 2, config['height'] + 28), config['background'])
            seam.paste(last, (0, 28)); seam.paste(first, (config['width'], 28))
            ImageDraw.Draw(seam).text((8, 8), 'LAST -> FIRST | human review required', fill='white')
            seam.save(stage / 'loop-seam.png')
            seam_mae = mae(first, last)
        palette = palette_samples.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        gif_frames = []
        for index in range(count):
            with Image.open(preview_dir / f'{index:04}.png') as frame:
                gif_frames.append(quantize_shared(frame.convert('RGB'), palette))
        candidate = stage / 'take.gif'
        gif_frames[0].save(candidate, save_all=True, append_images=gif_frames[1:], duration=step,
                           loop=0, optimize=False, disposal=1)
        del gif_frames
        with Image.open(candidate) as image:
            actual_delays = [frame.info.get('duration', 0) for frame in ImageSequence.Iterator(image)]
        if sum(actual_delays) != timeline['output_duration_ms']:
            raise ValueError('Encoded GIF timing mismatch')
        movie = stage / 'review.mp4'
        run_command(['ffmpeg', '-v', 'error', '-nostdin', '-framerate', str(config['fps']),
                     '-i', str(preview_dir / '%04d.png'), '-frames:v', str(count), '-c:v', 'libx264',
                     '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(movie)], commands)
        probe = json.loads(run_command(['ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-of', 'json', str(movie)], commands))
        stream = probe['streams'][0]
        if (stream['codec_name'] != 'h264' or int(stream['nb_read_frames']) != count or
                int(stream['width']) != config['width'] or int(stream['height']) != config['height'] or
                Fraction(stream['avg_frame_rate']) != config['fps'] or
                abs(float(stream['duration']) - timeline['output_duration_ms'] / 1000) > .001):
            raise ValueError('MP4 verification failed')
        for path, options in ((movie, []), (candidate, ['-ignore_loop', '1'])):
            run_command(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', *options, '-i', str(path), '-f', 'null', '-'], commands)
        if atlas is not None:
            atlas.save(stage / 'spritesheet.png')
            (stage / 'spritesheet.json').write_text(json.dumps({'schema_version': 1, 'image': 'spritesheet.png',
                 'size': {'w': atlas.width, 'h': atlas.height}, 'fps': config['fps'], 'frames': atlas_rows}, indent=2), encoding='utf-8')
        (stage / 'recipe.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
        if sha(read_bounded(source, MAX_BYTES)) != sha(raw):
            raise ValueError('Source changed during rendering; no candidate published')
        outputs = ['take.gif', 'review.mp4', 'first.png', 'last.png', 'contact-sheet.png', 'loop-seam.png', 'recipe.json']
        if atlas is not None:
            outputs += ['spritesheet.png', 'spritesheet.json']
        receipt = {**plan, 'status': 'human-review-required', 'source_unchanged': True,
                   'gif_palette': 'shared median-cut from up to 256 full-resolution representative colors per output frame; no dithering',
                   'still_orientation': 'EXIF display orientation normalized before recipe sizing and transforms',
                   'candidate_drawings': len(actual_delays), 'candidate_delays_ms': actual_delays,
                   'loop_review': {'status': 'human-review-required', 'endpoint_rgb_mae': seam_mae,
                                   'note': 'Pixel difference is diagnostic only, not seamlessness or continuity acceptance.'},
                   'samples': samples, 'outputs': {name: sha((stage / name).read_bytes()) for name in outputs},
                   'pillow': PIL.__version__, 'probe': probe,
                   'ffmpeg': run_command(['ffmpeg', '-version'], commands).decode().splitlines()[0],
                   'commands': commands, 'limitations': [
                       'Transforms animate the whole source, not separate objects, letters or poses.',
                       'No new in-between drawings: retiming may repeat or omit source drawings.',
                       'PNG sequence and spritesheet retain alpha; GIF and MP4 use the explicit background.',
                       'MP4 uses full-color PNGs, not the palette-quantized GIF; inspect both deliverables.',
                       'Ping-pong avoids repeated endpoint holds but does not prove a seamless loop.',
                       'Keyframes run across the entire output, including source holds and repeats.',
                       'Technical verification is not visual acceptance; inspect subjects and both cuts.']}
        (stage / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        # Reserve frames without adopting an existing destination. Receipt is the completion marker.
        (out / 'frames').mkdir(exist_ok=False)
        for path in sorted(rgba_dir.iterdir()):
            os.link(path, out / 'frames' / path.name)
        for filename in outputs + ['receipt.json']:
            os.link(stage / filename, out / filename)
        return receipt


def run(args):
    recipe = load_recipe(args.recipe) if args.recipe else None
    result = motion(args.source, args.out, recipe, args.preset, args.dry_run)
    print(json.dumps(result if args.dry_run else {
        'out': str(args.out), 'status': result['status'], 'api_calls': 0,
        'playback_frames': result['timeline']['playback_frames'],
        'duration_ms': result['timeline']['output_duration_ms'],
        'omitted_source_drawings': result['omitted_source_drawings']}, indent=2))


def add_parser(sub):
    parser = sub.add_parser('motion', help='Animate a still or retime/reframe a GIF locally, with editable keyframes')
    parser.add_argument('source', help='Local GIF or still PNG/JPEG/WebP')
    parser.add_argument('--out', required=True, help='New output directory; originals never change')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--recipe', help='Strict motion recipe JSON')
    group.add_argument('--preset', choices=tuple(PRESETS))
    parser.add_argument('--dry-run', action='store_true', help='Validate and print zero-call plan without writing or FFmpeg')
    parser.set_defaults(func=run)
