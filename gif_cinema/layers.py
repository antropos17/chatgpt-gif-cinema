"""Experimental, deterministic offline layer compositor. Not a Lottie player.

The scene is data, never executable code. No URL loaders, expressions, plugins,
font downloads, paid generation or implicit source replacement exist here.
"""
import argparse
import bisect
import copy
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile

from . import layer_gifs, motion, strokes, text_fonts
from .motion import run_command

FORMAT = 'gif-cinema-layered-scene'
MAX_SCENE_BYTES = 512 * 1024
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_ASSET_BYTES = 16 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 32 * 1024 * 1024
MAX_ASSET_PIXELS = 4 * 1024 * 1024
MAX_TOTAL_ASSET_PIXELS = 16 * 1024 * 1024
MAX_PIXEL_FRAMES = 160 * 1024 * 1024
MAX_LAYER_PIXEL_FRAMES = 1200 * 1024 * 1024
MAX_LAYER_RASTER_PIXELS = 1024 * 1024
MAX_TOTAL_RASTER_PIXELS = 4 * 1024 * 1024
MAX_RASTER_PIXEL_FRAMES = 256 * 1024 * 1024
MAX_SUPERSAMPLED_RASTER_PIXELS = 9 * 1024 * 1024
SUPERSAMPLE = 3
DEFAULTS = {'x': .5, 'y': .5, 'zoom': 1, 'rotation': 0, 'opacity': 1}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path, limit):
    """Bound local input without blocking on FIFOs, sockets or device files.

    The first stat provides a clear error. NONBLOCK and the second fstat cover
    replacement by a FIFO between that check and opening on POSIX systems.
    """
    if not stat.S_ISREG(os.stat(path).st_mode):
        raise ValueError('Input must be a regular local file')
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    flags |= getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('Input must be a regular local file')
        with os.fdopen(descriptor, 'rb', closefd=False) as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ValueError(f'Input exceeds {limit} byte limit')
        return raw
    finally:
        os.close(descriptor)


def require_fields(value, allowed, required, label):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        raise ValueError(f'{label} must have required fields and known fields only')


def color(value, label):
    if not isinstance(value, str) or re.fullmatch(r'#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?', value) is None:
        raise ValueError(f'{label} must be #RRGGBB or #RRGGBBAA')
    return value.lower()


def text_value(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f'{label} must be 1..{limit} printable characters, on one line')
    return value


def source_name(value):
    if not isinstance(value, str) or len(value) > 240 or not value:
        raise ValueError('Source must be a bounded relative asset path')
    if ('\\' in value or ':' in value or any(ord(c) < 32 for c in value)
            or PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError('Source must be a relative asset path without URLs or traversal')
    return value


def output_name(path, directory):
    """Serialize generated receipt paths portably without relaxing input guards."""
    return source_name(path.relative_to(directory).as_posix())


def easing_value(value):
    if isinstance(value, str) and value in motion.EASINGS:
        return value
    if isinstance(value, list) and len(value) == 4:
        # Temporal easing only; these four numbers are not spatial path points.
        for component in value:
            motion.number(component, 'cubic-bezier control point', 0, 1)
        return list(value)
    raise ValueError('Easing must be a supported name or four cubic-bezier values in 0..1')


def normalize_keyframes(keys, *, stroke=False):
    if not isinstance(keys, list) or not 2 <= len(keys) <= 32:
        raise ValueError('Each layer needs 2..32 keyframes')
    defaults = {**DEFAULTS, **({'reveal': 1} if stroke else {})}
    result, previous = [], dict(defaults)
    for key in keys:
        require_fields(key, [*defaults, 'at', 'easing'], ['at'], 'Keyframe')
        motion.number(key['at'], 'keyframe.at', 0, 1)
        if result and key['at'] <= result[-1]['at']:
            raise ValueError('Keyframe times must strictly increase')
        row = {**previous, **copy.deepcopy(key), 'easing': easing_value(key.get('easing', 'linear'))}
        for name, lo, hi in (('x', -2, 3), ('y', -2, 3), ('zoom', .05, 8),
                             ('rotation', -3600, 3600), ('opacity', 0, 1)):
            motion.number(row[name], f'keyframe.{name}', lo, hi)
        if stroke:
            motion.number(row['reveal'], 'keyframe.reveal', 0, 1)
        result.append(row)
        previous = {name: row[name] for name in defaults}
    if result[0]['at'] != 0 or result[-1]['at'] != 1:
        raise ValueError('Keyframes must include 0 and 1 endpoints')
    return result


def normalize_scene(value):
    require_fields(value, ['format', 'schema_version', 'title', 'width', 'height', 'fps',
                           'duration_ms', 'loop', 'matte', 'layers', 'text_renderer'],
                   ['format', 'schema_version', 'width', 'height', 'duration_ms', 'layers'], 'Scene')
    scene = {'title': 'Untitled scene', 'fps': 50, 'loop': True, 'matte': '#101018', **copy.deepcopy(value)}
    if scene['format'] != FORMAT:
        raise ValueError('This is a GIF Cinema scene, not a Lottie document')
    motion.number(scene['schema_version'], 'schema_version', 1, 1, True)
    text_value(scene['title'], 'title', 120)
    for name in ('width', 'height'):
        motion.number(scene[name], name, 2, 1024, True)
        if scene[name] % 2:
            raise ValueError('Dimensions must be even')
    motion.number(scene['fps'], 'fps', 25, 50, True)
    if scene['fps'] not in (25, 50):
        raise ValueError('FPS must be 25 or 50 for exact GIF frame timing')
    motion.number(scene['duration_ms'], 'duration_ms', 40, 30000, True)
    if scene['duration_ms'] % (1000 // scene['fps']):
        raise ValueError('Duration must be a whole number of output frame periods')
    if type(scene['loop']) is not bool:
        raise ValueError('loop must be true or false')
    if len(color(scene['matte'], 'matte')) != 7:
        raise ValueError('matte must be opaque #RRGGBB')
    layers = scene['layers']
    if not isinstance(layers, list) or not 1 <= len(layers) <= 16:
        raise ValueError('Require 1..16 layers')
    count = scene['duration_ms'] * scene['fps'] // 1000
    if count < 2 or count > 1500 or count * scene['width'] * scene['height'] > MAX_PIXEL_FRAMES:
        raise ValueError('Scene exceeds bounded frame/pixel budget')
    if count * scene['width'] * scene['height'] * len(layers) > MAX_LAYER_PIXEL_FRAMES:
        raise ValueError('Scene exceeds bounded layer compositing budget')
    names, normalized = set(), []
    common = ['id', 'type', 'name', 'keyframes', 'in_ms', 'out_ms', 'anchor']
    special = {'rect': ['size', 'fill', 'stroke', 'stroke_width', 'radius'],
               'ellipse': ['size', 'fill', 'stroke', 'stroke_width'],
               'stroke': ['size', 'points', 'stroke', 'stroke_width'],
               'text': ['text', 'font_size', 'fill', 'font_id', 'font_sha256'],
               'image': ['source', 'size', 'sha256'], 'gif': ['source', 'size', 'sha256', 'playback']}
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get('type'), str) or layer['type'] not in special:
            raise ValueError('Layer type must be rect, ellipse, stroke, text, image or gif')
        kind = layer['type']
        require_fields(layer, common + special[kind], ['id', 'type'], 'Layer')
        name = layer['id']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', name) or name.lower() in names:
            raise ValueError('Layer IDs must be unique ASCII identifiers')
        names.add(name.lower())
        row = {'name': name, 'in_ms': 0, 'out_ms': scene['duration_ms'], 'anchor': [.5, .5],
               'keyframes': [{'at': 0}, {'at': 1}], **copy.deepcopy(layer)}
        text_value(row['name'], 'layer.name', 120)
        motion.number(row['in_ms'], 'in_ms', 0, scene['duration_ms'] - 1, True)
        motion.number(row['out_ms'], 'out_ms', 1, scene['duration_ms'], True)
        if row['in_ms'] >= row['out_ms']:
            raise ValueError('Layer in_ms must be before out_ms')
        for timing in ('in_ms', 'out_ms'):
            if row[timing] % (1000 // scene['fps']):
                raise ValueError('Layer timing must align with the output frame grid')
        if not isinstance(row['anchor'], list) or len(row['anchor']) != 2:
            raise ValueError('Layer anchor must be a normalized pair')
        for component in row['anchor']:
            motion.number(component, 'anchor', 0, 1)
        row['keyframes'] = normalize_keyframes(row['keyframes'], stroke=kind == 'stroke')
        if kind != 'text':
            if not isinstance(row.get('size'), list) or len(row['size']) != 2:
                raise ValueError('Layer size must be a width/height pixel pair')
            for component in row['size']:
                motion.number(component, 'layer size', 1, 2048, True)
        if kind == 'text':
            text_value(row.get('text'), 'layer.text', 160)
            row.setdefault('font_size', 32)
            motion.number(row['font_size'], 'font_size', 8, 160, True)
            row['fill'] = color(row.get('fill', '#ffffff'), 'text fill')
            from .text_fonts import normalize_text_layer
            row.update(normalize_text_layer(row))
        elif kind in ('rect', 'ellipse'):
            row['fill'] = color(row.get('fill', '#ffffff'), 'fill')
            row['stroke'] = color(row.get('stroke', '#00000000'), 'stroke')
            row.setdefault('stroke_width', 0)
            motion.number(row['stroke_width'], 'stroke_width', 0, min(row['size']) // 2, True)
            if kind == 'rect':
                row.setdefault('radius', 0)
                motion.number(row['radius'], 'radius', 0, min(row['size']) / 2)
        elif kind == 'stroke':
            strokes.validate_points(row.get('points'), row['size'])
            row['stroke'] = color(row.get('stroke', '#ffffff'), 'stroke')
            row.setdefault('stroke_width', 3)
            motion.number(row['stroke_width'], 'stroke_width', 1, 128, True)
        else:
            row['source'] = source_name(row.get('source'))
            if kind == 'gif':
                row.setdefault('playback', 'once')
                if row['playback'] not in ('once', 'loop'):
                    raise ValueError('GIF layer playback must be once or loop')
            if 'sha256' in row and (not isinstance(row['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])):
                raise ValueError('Asset sha256 must be a lowercase SHA-256 digest')
        normalized.append(row)
    scene['layers'] = normalized
    from .text_fonts import bind_renderer
    bind_renderer(scene)
    raster_budget(scene)
    return scene


def text_layout(layer):
    from .text_fonts import load_font
    font = load_font(layer['font_id'], layer['font_size'] * SUPERSAMPLE)
    bounds = font.getbbox(layer['text'])
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    if width > 4096 * SUPERSAMPLE or height > 512 * SUPERSAMPLE:
        raise ValueError('Rendered text exceeds bounded size; shorten text or reduce font size')
    high_size = (max(1, width + 4 * SUPERSAMPLE), max(1, height + 4 * SUPERSAMPLE))
    size = tuple(max(1, math.ceil(value / SUPERSAMPLE)) for value in high_size)
    return font, bounds, high_size, size


def raster_budget(scene):
    """Preflight source-raster work independently of the final canvas area.

    Image boxes are conservative upper bounds. Text metrics are measured without
    allocating a pixel surface. All limits precede asset decoding/rasterization.
    """
    total, pixel_frames, peak_supersampled = 0, 0, 0
    stroke_pixels, stroke_segments = 0, 0
    period = 1000 // scene['fps']
    for layer in scene['layers']:
        if layer['type'] == 'text':
            _, _, high_size, size = text_layout(layer)
            supersampled = high_size[0] * high_size[1]
        else:
            size = layer['size']
            supersampled = size[0] * size[1] * SUPERSAMPLE ** 2 if layer['type'] not in ('image', 'gif') else 0
        area = size[0] * size[1]
        if area > MAX_LAYER_RASTER_PIXELS or supersampled > MAX_SUPERSAMPLED_RASTER_PIXELS:
            raise ValueError(f'Layer {layer["id"]} exceeds raster/supersampling pixel budget')
        total += area
        pixel_frames += area * ((layer['out_ms'] - layer['in_ms']) // period)
        peak_supersampled = max(peak_supersampled, supersampled)
        if layer['type'] == 'stroke':
            active_frames = (layer['out_ms'] - layer['in_ms']) // period
            stroke_pixels += supersampled * active_frames
            stroke_segments += (len(layer['points']) - 1) * active_frames
            if stroke_pixels > strokes.MAX_RASTER_PIXEL_FRAMES:
                raise ValueError('Scene exceeds dynamic stroke raster pixel-frame budget')
            if stroke_segments > strokes.MAX_SEGMENT_FRAMES:
                raise ValueError('Scene exceeds dynamic stroke segment-frame budget')
        if total > MAX_TOTAL_RASTER_PIXELS:
            raise ValueError('Scene exceeds total layer raster pixel budget')
        if pixel_frames > MAX_RASTER_PIXEL_FRAMES:
            raise ValueError('Scene exceeds layer raster pixel-frame budget')
    return {'total_raster_pixels_upper_bound': total, 'raster_pixel_frames_upper_bound': pixel_frames,
            'peak_supersampled_pixels': peak_supersampled,
            'stroke_supersampled_pixel_frames': stroke_pixels, 'stroke_segment_frames': stroke_segments}


def parse_scene(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate scene field: {key}')
            result[key] = value
        return result
    try:
        if len(raw) > MAX_SCENE_BYTES:
            raise ValueError('Scene exceeds JSON size budget')
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Scene must be bounded UTF-8 JSON') from exc
    return normalize_scene(value)


def load_scene(path):
    return parse_scene(read_regular(path, MAX_SCENE_BYTES))


def serialize_scene(scene):
    raw = (json.dumps(normalize_scene(scene), ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if len(raw) > MAX_SCENE_BYTES:
        raise ValueError('Normalized scene exceeds JSON size budget')
    return raw


def ease(value, easing):
    if isinstance(easing, list):
        x1, y1, x2, y2 = easing
        def bezier(t, p1, p2):
            return 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3
        if value in (0, 1):
            return value
        lo, hi = 0., 1.
        for _ in range(32):
            middle = (lo + hi) / 2
            if bezier(middle, x1, x2) < value:
                lo = middle
            else:
                hi = middle
        return bezier((lo + hi) / 2, y1, y2)
    if easing == 'ease-in':
        return value * value
    if easing == 'ease-out':
        return 1 - (1 - value) ** 2
    if easing == 'ease-in-out':
        return value * value * (3 - 2 * value)
    if easing == 'smootherstep':
        return value ** 3 * (value * (value * 6 - 15) + 10)
    if easing == 'step':
        return 0.
    return value


def evaluate(keyframes, progress):
    motion.number(progress, 'progress', 0, 1)
    index = max(0, bisect.bisect_right([k['at'] for k in keyframes], progress) - 1)
    left = keyframes[index]
    properties = (*DEFAULTS, 'reveal') if 'reveal' in left else DEFAULTS
    if index == len(keyframes) - 1:
        return {name: left[name] for name in properties}
    right = keyframes[index + 1]
    t = ease((progress - left['at']) / (right['at'] - left['at']), left['easing'])
    return {name: left[name] + t * (right[name] - left[name]) for name in properties}


def read_assets(scene, base):
    from PIL import Image, ImageOps
    base = Path(base).resolve()
    assets, pixels, total_bytes = {}, 0, 0
    for layer in scene['layers']:
        if layer['type'] not in ('image', 'gif'):
            continue
        name = layer['source']
        if name in assets and assets[name]['kind'] != layer['type']:
            raise ValueError('The same source cannot be both image and GIF layer')
        if name not in assets:
            path = (base / name).resolve()
            if not path.is_relative_to(base):
                raise ValueError('Asset path escapes scene directory, possibly through a symlink')
            raw = read_regular(path, MAX_ASSET_BYTES)
            total_bytes += len(raw)
            if total_bytes > MAX_TOTAL_ASSET_BYTES:
                raise ValueError('Total asset bytes exceed budget')
            if layer['type'] == 'gif':
                decoded = layer_gifs.decode(raw, MAX_ASSET_PIXELS, MAX_TOTAL_ASSET_PIXELS - pixels)
                pixels += sum(frame.width * frame.height for frame in decoded['frames'])
            else:
                with Image.open(io.BytesIO(raw)) as source:
                    if source.format not in ('PNG', 'JPEG', 'WEBP') or getattr(source, 'n_frames', 1) != 1:
                        raise ValueError('Image layers support still PNG/JPEG/WebP only; use a gif layer for animation')
                    area = source.width * source.height
                    pixels += area
                    if area > MAX_ASSET_PIXELS or pixels > MAX_TOTAL_ASSET_PIXELS:
                        raise ValueError('Assets exceed decoded pixel budget')
                    image = ImageOps.exif_transpose(source).convert('RGBA')
                    image.info.clear()
                decoded = {'rgba': image}
            assets[name] = {'raw': raw, **decoded, 'sha256': digest(raw), 'kind': layer['type']}
        if layer.get('sha256', assets[name]['sha256']) != assets[name]['sha256']:
            raise ValueError(f'Asset changed: {name}')
    return assets


def fit_image(source, size):
    from PIL import Image
    source = source.copy()
    source.thumbnail(tuple(size), Image.Resampling.LANCZOS)
    scale = min(size[0] / source.width, size[1] / source.height)
    return source.resize((max(1, round(source.width * scale)), max(1, round(source.height * scale))), Image.Resampling.LANCZOS)


def rasterize(layer, assets):
    from PIL import Image, ImageDraw
    kind = layer['type']
    if kind == 'stroke':
        return strokes.rasterize(layer, strokes.prepare_path(layer['points']), 1, SUPERSAMPLE)
    if kind in ('image', 'gif'):
        return fit_image(assets[layer['source']]['rgba'], layer['size'])
    scale = SUPERSAMPLE
    if kind == 'text':
        font, bounds, high_size, size = text_layout(layer)
        image = Image.new('RGBA', high_size)
        ImageDraw.Draw(image).text((2 * scale - bounds[0], 2 * scale - bounds[1]), layer['text'], font=font, fill=layer['fill'])
        return image.resize(size, Image.Resampling.LANCZOS)
    width, height = layer['size']
    image = Image.new('RGBA', (width * scale, height * scale))
    draw = ImageDraw.Draw(image)
    box = (0, 0, width * scale - 1, height * scale - 1)
    style = {'fill': layer['fill'], 'outline': layer['stroke'] if layer['stroke_width'] else None,
             'width': layer['stroke_width'] * scale}
    if kind == 'rect':
        draw.rounded_rectangle(box, radius=layer['radius'] * scale, **style)
    else:
        draw.ellipse(box, **style)
    return image.resize((width, height), Image.Resampling.LANCZOS)


def prepare_scene(path):
    path = Path(path).absolute()
    raw = read_regular(path, MAX_SCENE_BYTES)
    scene = parse_scene(raw)
    assets = read_assets(scene, path.parent)
    cached_gif_pixels = layer_gifs.cache_budget(scene, assets)
    # Cache premultiplication once, not a conversion of the full source on each frame.
    rasters, gif_rasters = {}, {}
    for layer in scene['layers']:
        if layer['type'] == 'gif':
            variants = [fit_image(frame, layer['size']).convert('RGBa')
                        for frame in assets[layer['source']]['frames']]
            gif_rasters[layer['id']] = variants
            rasters[layer['id']] = variants[0]
        else:
            rasters[layer['id']] = rasterize(layer, assets).convert('RGBa')
    paths = {layer['id']: strokes.prepare_path(layer['points'])
             for layer in scene['layers'] if layer['type'] == 'stroke'}
    return {'scene': scene, 'assets': assets, 'rasters': rasters,
            'stroke_paths': paths,
            'gif_rasters': gif_rasters, 'cached_gif_pixels_upper_bound': cached_gif_pixels,
            'source_path': path, 'source_sha256': digest(raw)}


def layer_transform(scene, layer, time_ms):
    motion.number(time_ms, 'time_ms', 0, scene['duration_ms'])
    # The conceptual closing endpoint is diagnostic; it is never duplicated in export.
    closing = time_ms == scene['duration_ms'] == layer['out_ms']
    if time_ms < layer['in_ms'] or (time_ms >= layer['out_ms'] and not closing):
        return None
    progress = (time_ms - layer['in_ms']) / (layer['out_ms'] - layer['in_ms'])
    return evaluate(layer['keyframes'], progress)


def render_at(prepared, time_ms, only_layer=None, _layer_previews=None):
    from PIL import Image
    scene = prepared['scene']
    canvas = Image.new('RGBA', (scene['width'], scene['height']))
    if only_layer is not None and only_layer not in prepared['rasters']:
        raise ValueError('Unknown layer ID')
    states = {}
    for layer in scene['layers']:
        if only_layer is not None and layer['id'] != only_layer:
            continue
        state = layer_transform(scene, layer, time_ms)
        if state is not None and layer['type'] == 'gif':
            state['source_index'] = layer_gifs.frame_index(prepared['assets'][layer['source']],
                time_ms - layer['in_ms'], layer['playback'])
        states[layer['id']] = state
        if state is None or state['opacity'] <= 0:
            continue
        raster = prepared['rasters'][layer['id']]
        if layer['type'] == 'gif':
            raster = prepared['gif_rasters'][layer['id']][state['source_index']]
        if layer['type'] == 'stroke' and state['reveal'] != 1:
            if state['reveal'] == 0:
                continue
            raster = strokes.rasterize(layer, prepared['stroke_paths'][layer['id']],
                                       state['reveal'], SUPERSAMPLE).convert('RGBa')
        angle = math.radians(state['rotation'])
        a, b = math.cos(angle) / state['zoom'], math.sin(angle) / state['zoom']
        d, e = -b, a
        cx, cy = state['x'] * scene['width'], state['y'] * scene['height']
        ax, ay = layer['anchor'][0] * raster.width, layer['anchor'][1] * raster.height
        matrix = (a, b, ax - a * cx - b * cy, d, e, ay - d * cx - e * cy)
        transformed = raster.transform(canvas.size, Image.Transform.AFFINE,
                        matrix, resample=Image.Resampling.BICUBIC).convert('RGBA')
        if state['opacity'] != 1:
            transformed.putalpha(transformed.getchannel('A').point(lambda alpha: round(alpha * state['opacity'])))
        if _layer_previews is not None:
            _collect_layer_preview(_layer_previews, scene, layer, time_ms, transformed)
        canvas.alpha_composite(transformed)
    canvas.info.clear()
    return canvas, states


def _collect_layer_preview(candidates, scene, layer, time_ms, frame):
    """Retain an existing transformed frame, with no second render or pixel copy."""
    step = 1000 // scene['fps']
    if (type(time_ms) is not int or time_ms % step or time_ms >= scene['duration_ms']
            or not layer['in_ms'] <= time_ms < layer['out_ms']):
        return
    distance = abs(2 * time_ms - layer['in_ms'] - layer['out_ms'])
    previous = candidates.get(layer['id'])
    if previous is not None and (distance, time_ms) >= (previous['distance'], previous['time_ms']):
        return
    bbox = frame.getchannel('A').getbbox()
    if bbox is not None:
        # alpha_composite reads this source; it does not modify the retained image.
        candidates[layer['id']] = {'image': frame, 'distance': distance,
            'frame': time_ms // step, 'time_ms': time_ms, 'alpha_bbox': list(bbox)}


def _write_layer_previews(candidates, scene, destination):
    """Keep legacy PNG paths, and release retained images before GIF encoding."""
    from PIL import Image
    metadata = {}
    for layer in scene['layers']:
        chosen = candidates.pop(layer['id'], None)
        if chosen is None:
            frame = Image.new('RGBA', (scene['width'], scene['height']))
            record = {'status': 'no-visible-export-frame', 'frame': None,
                      'time_ms': None, 'alpha_bbox': None}
        else:
            source = chosen.pop('image')
            # Match render_at(..., only_layer=...) even for RGB values hidden
            # under zero alpha after opacity rounding. Normalize once per PNG.
            frame = Image.new('RGBA', source.size)
            frame.alpha_composite(source)
            del source
            record = {'status': 'visible', 'frame': chosen['frame'],
                      'time_ms': chosen['time_ms'], 'alpha_bbox': chosen['alpha_bbox']}
        filename = f"{layer['id']}.png"
        frame.save(destination / filename)
        metadata[layer['id']] = {'filename': f'layers/{filename}',
            'in_ms': layer['in_ms'], 'out_ms': layer['out_ms'], **record}
    return metadata


def save_bundle(prepared, destination):
    """Write a new self-contained editable scene; never modify originals."""
    destination = Path(destination).absolute()
    if destination.exists() or any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError('Bundle destination must be a new directory without symlinks')
    normalized = copy.deepcopy(prepared['scene'])
    snapshots = {}
    for layer in normalized['layers']:
        if layer['type'] not in ('image', 'gif'):
            continue
        asset = prepared['assets'][layer['source']]
        layer['source'] = f'assets/{asset["sha256"]}.image'
        layer['sha256'] = asset['sha256']
        snapshots[layer['source']] = asset['raw']
    # Validate/serialize before claiming any output directory.
    serialized = serialize_scene(normalized)
    destination.mkdir(parents=True, exist_ok=False)
    for name, raw in snapshots.items():
        path = destination / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
    (destination / 'scene.json').write_bytes(serialized)
    return destination / 'scene.json'


def mean_rgb_difference(left, right):
    from PIL import ImageChops, ImageStat
    return sum(ImageStat.Stat(ImageChops.difference(left.convert('RGB'), right.convert('RGB'))).mean) / 3


def render_scene(path, out, dry_run=False):
    import PIL
    from PIL import Image, ImageDraw, ImageSequence
    prepared = prepare_scene(path)
    scene = prepared['scene']
    count, step = scene['duration_ms'] * scene['fps'] // 1000, 1000 // scene['fps']
    plan = {'format': FORMAT, 'schema_version': 1, 'status': 'planned', 'api_calls': 0,
            'title': scene['title'], 'frames': count, 'fps': scene['fps'], 'duration_ms': scene['duration_ms'],
            'width': scene['width'], 'height': scene['height'], 'layer_count': len(scene['layers']),
            'loop': scene['loop'], 'scene_sha256': prepared['source_sha256'],
            'raster_budget': raster_budget(scene),
            'cached_gif_pixels_upper_bound': prepared['cached_gif_pixels_upper_bound'],
            'gif_timing': layer_gifs.timing_report(scene, prepared['assets']),
            'text_renderer': scene.get('text_renderer'),
            'font_assets': text_fonts.font_receipt(scene),
            'asset_sha256': {name: asset['sha256'] for name, asset in prepared['assets'].items()},
            'sampling': 'frame i at i/fps; endpoint at duration is diagnostic and is not exported twice'}
    if dry_run:
        return plan
    out = Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Output must be a new directory without symlinks; originals are immutable')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('Installed FFmpeg and ffprobe are required; dry-run requires neither')
    out.parent.mkdir(parents=True, exist_ok=True)
    commands = []
    # Stage beside the destination. Reserve a fresh directory only after verification,
    # and move the receipt last as a completion marker; never replace a raced target.
    with tempfile.TemporaryDirectory(prefix=f'.{out.name}-stage-', dir=out.parent) as temporary:
        stage = Path(temporary) / 'candidate'
        stage.mkdir()
        frame_dir = stage / 'frames'; frame_dir.mkdir()
        preview_dir = Path(temporary) / 'preview'; preview_dir.mkdir()
        reopened = prepare_scene(save_bundle(prepared, stage / 'editable'))
        palettes = Image.new('RGB', (256, count))
        selected = sorted(set([0, count // 4, count // 2, 3 * count // 4, count - 1]))
        sheet = Image.new('RGB', (224 * len(selected), 252), scene['matte'])
        samples, first, previous, last, adjacent = [], None, None, None, []
        reopen_verified = []
        preview_candidates = {}
        for index in range(count):
            frame, states = render_at(prepared, index * step, _layer_previews=preview_candidates)
            rgba_hash = digest(frame.tobytes())
            frame.save(frame_dir / f'{index:04}.png')
            preview = motion.flatten(frame, scene['matte'])
            preview.save(preview_dir / f'{index:04}.png')
            palettes.paste(motion.palette_row(preview), (0, index))
            if previous is not None:
                adjacent.append(mean_rgb_difference(previous, preview))
            if first is None:
                first = preview.copy()
            previous = preview
            last = preview
            if index in selected:
                reopened_frame, _ = render_at(reopened, index * step)
                if reopened_frame.tobytes() != frame.tobytes():
                    raise ValueError('Saved scene failed deterministic reopen verification')
                reopen_verified.append(index)
                thumb = preview.copy(); thumb.thumbnail((224, 224))
                column = selected.index(index)
                sheet.paste(thumb, (column * 224 + (224 - thumb.width) // 2, (224 - thumb.height) // 2))
                ImageDraw.Draw(sheet).text((column * 224 + 8, 234), f'{index * step} ms', fill='white')
            samples.append({'frame': index, 'time_ms': index * step, 'rgba_sha256': rgba_hash, 'layers': states})
        sheet.save(stage / 'contact-sheet.png')
        closing_rgba, closing_states = render_at(prepared, scene['duration_ms'])
        closing = motion.flatten(closing_rgba, scene['matte'])
        first.save(stage / 'first.png'); last.save(stage / 'last.png'); closing.save(stage / 'closing-endpoint.png')
        seam = Image.new('RGB', (scene['width'] * 3, scene['height'] + 32), scene['matte'])
        for column, (label, frame) in enumerate([('LAST EXPORTED', last), ('FIRST / WRAP', first), ('CLOSING ENDPOINT', closing)]):
            seam.paste(frame, (column * scene['width'], 32))
            ImageDraw.Draw(seam).text((column * scene['width'] + 8, 10), label, fill='white')
        seam.save(stage / 'loop-seam.png')
        # Each isolated preview comes from a real visible export sample, not a
        # global midpoint that may lie outside the layer's active interval.
        isolation = stage / 'layers'; isolation.mkdir()
        layer_previews = _write_layer_previews(preview_candidates, scene, isolation)
        palette = palettes.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        gif_frames = []
        for index in range(count):
            with Image.open(preview_dir / f'{index:04}.png') as frame:
                gif_frames.append(motion.quantize_shared(frame.convert('RGB'), palette))
        gif = stage / 'preview.gif'
        options = {'loop': 0} if scene['loop'] else {}
        gif_frames[0].save(gif, save_all=True, append_images=gif_frames[1:], duration=step,
                           optimize=False, disposal=1, **options)
        del gif_frames
        with Image.open(gif) as encoded:
            gif_first = encoded.convert('RGB').copy()
            delays = [frame.info.get('duration', 0) for frame in ImageSequence.Iterator(encoded)]
            gif_last = encoded.convert('RGB').copy()
            repeat = encoded.info.get('loop')
        if sum(delays) != scene['duration_ms'] or repeat != (0 if scene['loop'] else None):
            raise ValueError('GIF timing or loop metadata verification failed')
        movie = stage / 'preview.mp4'
        run_command(['ffmpeg', '-v', 'error', '-nostdin', '-framerate', str(scene['fps']),
                     '-i', str(preview_dir / '%04d.png'), '-frames:v', str(count), '-c:v', 'libx264',
                     '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(movie)], commands)
        probe = json.loads(run_command(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                                       '-of', 'json', str(movie)], commands))
        stream = probe['streams'][0]
        if (stream.get('codec_name') != 'h264' or int(stream.get('nb_read_frames', -1)) != count
                or int(stream.get('width', -1)) != scene['width'] or int(stream.get('height', -1)) != scene['height']
                or Fraction(stream.get('avg_frame_rate', '0')) != scene['fps']
                or abs(float(stream.get('duration', -1)) - scene['duration_ms'] / 1000) > .001):
            raise ValueError('MP4 dimensions, duration, frame count or codec verification failed')
        for media, options in ((movie, []), (gif, ['-ignore_loop', '1'])):
            run_command(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', *options,
                         '-i', str(media), '-f', 'null', '-'], commands)
        endpoint_bytes = run_command(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(movie),
            '-vf', f'select=eq(n\\,0)+eq(n\\,{count - 1})', '-fps_mode', 'passthrough',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], commands)
        frame_bytes = scene['width'] * scene['height'] * 3
        if len(endpoint_bytes) != frame_bytes * 2:
            raise ValueError('MP4 endpoint decode did not produce exactly two frames')
        mp4_first = Image.frombytes('RGB', first.size, endpoint_bytes[:frame_bytes])
        mp4_last = Image.frombytes('RGB', first.size, endpoint_bytes[frame_bytes:])
        encoded_seam = Image.new('RGB', (scene['width'] * 2, scene['height'] * 2 + 64), scene['matte'])
        for row, (label, a, b) in enumerate([('GIF: LAST / FIRST', gif_last, gif_first),
                                            ('MP4: LAST / FIRST', mp4_last, mp4_first)]):
            top = row * (scene['height'] + 32)
            ImageDraw.Draw(encoded_seam).text((8, top + 10), label, fill='white')
            encoded_seam.paste(a, (0, top + 32)); encoded_seam.paste(b, (scene['width'], top + 32))
        encoded_seam.save(stage / 'encoded-loop-seam.png')
        if digest(read_regular(prepared['source_path'], MAX_SCENE_BYTES)) != prepared['source_sha256']:
            raise ValueError('Source scene changed during export')
        current = read_assets(scene, prepared['source_path'].parent)
        if {k: v['sha256'] for k, v in current.items()} != plan['asset_sha256']:
            raise ValueError('Source assets changed during export')
        first_rgba, _ = render_at(prepared, 0)
        loop_review = {'status': 'human-review-required',
            'closing_endpoint_rgba_equal': first_rgba.tobytes() == closing_rgba.tobytes(),
            'closing_endpoint_rgb_mae': mean_rgb_difference(first, closing),
            'exported_seam_rgb_mae': mean_rgb_difference(last, first),
            'decoded_gif_seam_rgb_mae': mean_rgb_difference(gif_last, gif_first),
            'decoded_mp4_seam_rgb_mae': mean_rgb_difference(mp4_last, mp4_first),
            'adjacent_rgb_mae_max': max(adjacent), 'adjacent_rgb_mae_mean': sum(adjacent) / len(adjacent),
            'last_frame_time_ms': (count - 1) * step, 'endpoint_time_ms': scene['duration_ms'],
            'layer_endpoint_states': closing_states,
            'note': 'Equal endpoints and low pixel differences do not prove perceptual or velocity continuity.'}
        outputs = {output_name(p, stage): digest(p.read_bytes()) for p in sorted(stage.rglob('*')) if p.is_file()}
        receipt = {**plan, 'status': 'human-review-required', 'source_unchanged': True,
            'gif_drawings': len(delays), 'gif_delays_ms': delays, 'loop_review': loop_review,
            'layer_previews': layer_previews,
            'layer_preview_sampling': 'nearest visible export frame to each active interval midpoint; ties select the earlier frame; visible means nonzero isolated alpha on canvas',
            'reopen_verified_frames': reopen_verified, 'reopen_scope': 'five sampled frames, all sources snapshotted',
            'pillow': PIL.__version__, 'probe': probe, 'commands': commands, 'samples': samples, 'outputs': outputs,
            'limitations': ['Experimental GIF Cinema format, not Lottie-compatible.',
                'Still images, existing GIF drawings, text, shapes and authored polyline strokes; no new character poses.',
                'GIF layers retain native source cadence on the output frame grid; high FPS does not create new drawings.',
                'GIF source loop metadata is ignored; each GIF layer explicitly plays once with final hold or loops.',
                'Stroke reveal follows authored point order and arc length; no handwriting generation, tracing or SVG import.',
                'No expressions, scripts, URLs, font paths/downloads, parenting, masks, blend modes or Lottie import/export.',
                'Layer order is back to front; opacity uses source-over alpha compositing.',
                'GIF and MP4 are flattened against matte; PNG frames and isolated layers retain alpha.',
                'Text font bytes are hash-pinned; saved text scenes require their recorded Pillow and FreeType versions.',
                'MP4 has no inherent loop playback flag; enable repeat in the player.',
                'Technical verification does not establish visual acceptance.']}
        receipt_raw = (json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
        if len(receipt_raw) > MAX_RECEIPT_BYTES:
            raise ValueError('Export receipt exceeds the shared writer/verifier byte budget')
        (stage / 'receipt.json').write_bytes(receipt_raw)
        out.mkdir(exist_ok=False)
        for item in sorted(stage.iterdir(), key=lambda p: (p.name == 'receipt.json', p.name)):
            os.rename(item, out / item.name)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    render = sub.add_parser('render', help='Render a local scene into a new verified output directory')
    render.add_argument('scene', type=Path)
    render.add_argument('--out', required=True, type=Path)
    render.add_argument('--dry-run', action='store_true')
    save = sub.add_parser('save', help='Save a new portable editable scene and snapshot its assets')
    save.add_argument('scene', type=Path)
    save.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'save':
            result = {'scene': str(save_bundle(prepare_scene(args.scene), args.out)), 'api_calls': 0}
        else:
            result = render_scene(args.scene, args.out, dry_run=args.dry_run)
            if not args.dry_run:
                result = {k: result[k] for k in ('title', 'status', 'frames', 'fps', 'duration_ms', 'layer_count', 'api_calls')}
                result['out'] = str(args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Layer scene error: {exc}\n')
    except (RuntimeError, subprocess.SubprocessError):
        parser.exit(2, 'Layer scene error: media encoder/probe failed or timed out; no completed output was published.\n')


if __name__ == '__main__':
    main()
