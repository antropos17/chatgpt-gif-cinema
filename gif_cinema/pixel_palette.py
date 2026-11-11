"""Bounded, lossless GIF palette normalization. No color quantization occurs here."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import GifImagePlugin, Image, ImageSequence

from . import cli

MAX_BYTES = 128 * 1024 * 1024
MAX_FRAMES = 256
MAX_PIXELS = 4_000_000
MAX_PIXEL_FRAMES = 16_000_000
MAX_DIMENSION = 8192
MAX_DURATION_MS = 120_000


def _scale(scale):
    if type(scale) is not int or not 1 <= scale <= 8:
        raise ValueError("scale must be an integer from 1 to 8")
    return scale


def _budget(width, height, count, scale=1):
    _scale(scale)
    if not count or count > MAX_FRAMES:
        raise ValueError("GIF must contain 1..256 frames")
    if min(width, height) < 1 or max(width * scale, height * scale) > MAX_DIMENSION:
        raise ValueError("GIF source/output dimensions must be 1..8192")
    pixels = width * height * scale * scale
    if pixels > MAX_PIXELS:
        raise ValueError("GIF source/output frame exceeds the 4 million pixel budget")
    if pixels * count > MAX_PIXEL_FRAMES:
        raise ValueError("GIF source/output exceeds the 16 million aggregate pixel budget")


def _frames(frames, scale=1):
    if not isinstance(frames, (list, tuple)) or not frames:
        raise ValueError("frames must be a nonempty list or tuple")
    size = frames[0].size
    _budget(*size, len(frames), scale)
    for frame in frames:
        if frame.mode != "RGBA" or frame.size != size:
            raise ValueError("frames must be equal-sized RGBA images")
        if any(frame.getchannel("A").histogram()[1:255]):
            raise ValueError("GIF requires binary alpha (0 or 255); partial alpha is not supported")
    return size


def canonical_rgba(frame):
    """Canonical visible pixels: fully transparent RGB is zero; no alpha threshold."""
    if frame.mode != "RGBA":
        frame = frame.convert("RGBA")
    alpha = frame.getchannel("A")
    if any(alpha.histogram()[1:255]):
        raise ValueError("GIF requires binary alpha (0 or 255); partial alpha is not supported")
    result = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    result.paste(frame, mask=alpha)
    return result


def _timing(delays_ms, count, loop):
    if not isinstance(delays_ms, (list, tuple)) or len(delays_ms) != count:
        raise ValueError("one delay is required per frame")
    if any(type(d) is not int or not 20 <= d <= MAX_DURATION_MS or d % 10
           for d in delays_ms):
        raise ValueError("GIF delays must be integer multiples of 10 ms in 20..120000 ms")
    if sum(delays_ms) > MAX_DURATION_MS:
        raise ValueError("GIF total duration exceeds 120000 ms")
    if loop is not None and (type(loop) is not int or not 0 <= loop <= 65535):
        raise ValueError("GIF loop must be None or an integer in 0..65535")


def decode(raw, scale=1):
    """Decode canonical composited source frames; scale only preflights future output.

    Pillow performs GIF local-table lookup and disposal 2/3 compositing. All
    structural/scaled budgets are checked before opening the decoder.
    """
    _scale(scale)
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("GIF must be bytes within the 128 MiB input limit")
    stats = cli.check_gif_limits(raw, max_frames=MAX_FRAMES,
                                 max_pixel_frames=MAX_PIXEL_FRAMES, fixed_canvas=True)
    _budget(stats['width'], stats['height'], stats['frames'], scale)
    inspect_tables(raw)  # Reject display semantics that Pillow cannot preserve.
    try:
        with Image.open(io.BytesIO(raw)) as source:
            loop = source.info.get('loop')
            frames, delays = [], []
            for frame in ImageSequence.Iterator(source):
                if len(frames) >= stats['frames'] or frame.size != (stats['width'], stats['height']):
                    raise ValueError("GIF decoder disagrees with structural preflight")
                delays.append(frame.info.get('duration', 0))
                frames.append(canonical_rgba(frame))
            _timing(delays, len(frames), loop)
            if len(frames) != stats['frames']:
                raise ValueError("GIF decoder frame count disagrees with structural preflight")
    except (OSError, EOFError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Invalid GIF: {exc}") from exc
    return {'frames': frames, 'delays_ms': delays, 'loop': loop,
            'size': (stats['width'], stats['height']), 'stats': stats}


def _pixels(frame):
    # Byte iteration works on the declared Pillow minimum and avoids getdata
    # deprecation in Pillow 12 without allocating millions of Python tuples.
    values = iter(frame.tobytes())
    return zip(values, values, values, values)


def audit(frames):
    """Bound the exact visible RGB union; 257 is a sufficient failure lower bound."""
    _frames(frames)
    colors = set()
    transparency = False
    for frame in frames:
        transparency |= frame.getchannel('A').getextrema()[0] == 0
        counted = frame.getcolors(maxcolors=257)
        pixels = (pixel for _, pixel in counted) if counted is not None else _pixels(frame)
        for r, g, b, a in pixels:
            if a and len(colors) < 257:
                colors.add((r, g, b))
            if len(colors) == 257:
                break
    return {'colors': sorted(colors), 'color_count_lower_bound': len(colors),
            'transparency': transparency}


def _requested(colors):
    if not isinstance(colors, (list, tuple)) or not 0 <= len(colors) <= 256:
        raise ValueError("requested palette must contain 0..256 distinct RGB colors")
    result = []
    for color in colors:
        if (not isinstance(color, (tuple, list)) or len(color) != 3
                or any(type(c) is not int or not 0 <= c <= 255 for c in color)):
            raise ValueError("palette colors must be RGB triples of integers in 0..255")
        result.append(tuple(color))
    if len(set(result)) != len(result):
        raise ValueError("requested palette contains duplicate colors")
    return result


def choose_palette(frames, requested_colors=None):
    """Preserve every visible color exactly; optionally reuse an authored palette."""
    found = audit(frames)
    colors = found['colors'] if requested_colors is None else _requested(requested_colors)
    capacity = 255 if found['transparency'] else 256
    if len(found['colors']) > capacity:
        raise ValueError(f"source needs at least {len(found['colors'])} visible colors; "
                         f"GIF allows {capacity} with this transparency (no quantization)")
    if len(colors) > capacity:
        raise ValueError("palette has no free index for transparency")
    missing = set(found['colors']) - set(colors)
    if missing:
        raise ValueError(f"requested palette is missing {len(missing)} visible source colors")
    transparent_index = len(colors) if found['transparency'] else None
    palette = [channel for color in colors for channel in color]
    palette.extend([0] * (768 - len(palette)))
    return {'colors': list(colors), 'transparent_index': transparent_index, 'palette': palette}


def timeline(frames, delays_ms):
    """Hash canonical display states and combine adjacent identical holds."""
    size = _frames(frames)
    _timing(delays_ms, len(frames), None)
    result = []
    for frame, delay in zip(frames, delays_ms):
        digest = hashlib.sha256(f'{size[0]}x{size[1]}:'.encode() +
                                canonical_rgba(frame).tobytes()).hexdigest()
        if result and result[-1]['sha256'] == digest:
            result[-1]['duration_ms'] += delay
        else:
            result.append({'sha256': digest, 'duration_ms': delay})
    return result


def inspect_tables(raw):
    """Inspect GIF structure, not byte-pattern matches inside compressed pixels."""
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("GIF must be bytes within the 128 MiB input limit")
    cli.check_gif_limits(raw, max_frames=MAX_FRAMES,
                         max_pixel_frames=MAX_PIXEL_FRAMES, fixed_canvas=True)
    if raw[12] != 0:
        raise ValueError("GIF pixel-aspect metadata is unsupported for exact normalization")
    length = (3 << ((raw[10] & 7) + 1)) if raw[10] & 128 else 0
    global_palette = raw[13:13 + length]
    offset, local_count = 13 + length, 0

    def skip(position):
        while True:
            n = raw[position]
            position += 1
            if not n:
                return position
            position += n

    while raw[offset] != 0x3B:
        marker = raw[offset]
        offset += 1
        if marker == 0x21:
            label = raw[offset]
            if label == 0x01:
                raise ValueError("GIF plain-text graphics cannot be preserved exactly")
            if label == 0xF9:
                flags = raw[offset + 2]
                if flags & 2:
                    raise ValueError("GIF user-input behavior cannot be preserved exactly")
                if ((flags >> 2) & 7) > 3:
                    raise ValueError("GIF reserved disposal modes 4..7 are unsupported")
            offset = skip(offset + 1)
        else:
            flags = raw[offset + 8]
            offset += 9
            if flags & 128:
                local_count += 1
                offset += 3 << ((flags & 7) + 1)
            offset = skip(offset + 1)
    return {'global_palette': global_palette, 'local_count': local_count}


def encode(frames, delays_ms, loop, palette_plan, path, scale=1):
    """Write exact full-frame palette indices, one GCT, then verify visible playback.

    Uses Pillow's GIF block writer to avoid its palette remapping and delta-frame
    heuristics. Full frames with disposal 2 preserve disappearing transparency.
    The caller owns no-clobber publication and completion marking.
    """
    _frames(frames, scale)
    _timing(delays_ms, len(frames), loop)
    if not isinstance(palette_plan, dict):
        raise ValueError("invalid palette plan")
    expected_plan = choose_palette(frames, palette_plan.get('colors'))
    if palette_plan != expected_plan:
        raise ValueError("invalid or inconsistent palette plan")
    color_indices = {color: i for i, color in enumerate(palette_plan['colors'])}
    transparent = palette_plan['transparent_index']
    rendered = [canonical_rgba(frame).resize((frame.width * scale, frame.height * scale),
                                            Image.Resampling.NEAREST)
                if scale != 1 else canonical_rgba(frame) for frame in frames]
    stream = io.BytesIO()
    for index, (frame, delay) in enumerate(zip(rendered, delays_ms)):
        indices = bytes(color_indices[(r, g, b)] if a else transparent
                        for r, g, b, a in _pixels(frame))
        indexed = Image.frombytes('P', frame.size, indices)
        indexed.putpalette(palette_plan['palette'])
        info = {'optimize': False, 'duration': delay, 'disposal': 2,
                'include_color_table': False, 'background': transparent or 0}
        if transparent is not None:
            info['transparency'] = transparent
        if loop is not None:
            info['loop'] = loop
        if index == 0:
            header, _ = GifImagePlugin.getheader(indexed, info=info)
            for block in header:
                stream.write(block)
        for block in GifImagePlugin.getdata(indexed, **info):
            stream.write(block)
        if stream.tell() > MAX_BYTES:
            raise ValueError("encoded GIF exceeds the 128 MiB limit")
    stream.write(b';')
    raw = stream.getvalue()
    tables = inspect_tables(raw)
    if tables['local_count'] or tables['global_palette'] != bytes(palette_plan['palette']):
        raise ValueError("encoded GIF does not have exactly the requested global palette")
    actual = decode(raw)
    expected = timeline(rendered, delays_ms)
    if actual['loop'] != loop or timeline(actual['frames'], actual['delays_ms']) != expected:
        raise ValueError("encoded GIF failed exact visible timeline/loop verification")
    Path(path).write_bytes(raw)
    return {'size': actual['size'], 'frames': len(actual['frames']),
            'duration_ms': sum(delays_ms), 'loop': loop, 'timeline': expected,
            'local_count': 0, 'bytes': len(raw)}
