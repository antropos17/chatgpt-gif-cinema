"""Lossless local PNG atlas drawings, with authored frame rectangles and timing."""
import copy
import io
import json
from pathlib import Path
import re

from . import layer_gifs, motion, pose_tracks

MAX_ATLAS_PIXELS = 16 * 1024 * 1024
MAX_ATLAS_SIDE = 16384
MAX_CROP_PIXEL_FRAMES = 32 * 1024 * 1024


def normalize_frames(value):
    if not isinstance(value, list) or not 1 <= len(value) <= layer_gifs.MAX_FRAMES:
        raise ValueError('Sprite layer frames must contain 1..256 frame records')
    result, size, duration = [], None, 0
    for record in value:
        if not isinstance(record, dict) or set(record) != {'rect', 'duration_ms'}:
            raise ValueError('Sprite frame requires only rect and duration_ms')
        rect = record['rect']
        if not isinstance(rect, list) or len(rect) != 4:
            raise ValueError('Sprite rect must be [x, y, width, height]')
        for index, component in enumerate(rect):
            motion.number(component, 'sprite rect', 0 if index < 2 else 1, 16384, True)
        if rect[2] * rect[3] > 4 * 1024 * 1024:
            raise ValueError('Sprite drawing exceeds 4 megapixel limit')
        if size is not None and rect[2:] != size:
            raise ValueError('Sprite layer drawings must share one size and pose coordinate system')
        size = rect[2:]
        delay = motion.number(record['duration_ms'], 'sprite duration_ms', 20, 60000, True)
        if delay % 10:
            raise ValueError('Sprite durations must use 10 ms units')
        duration += delay
        if duration > layer_gifs.MAX_DURATION_MS:
            raise ValueError('Sprite layer duration exceeds 120 seconds')
        result.append(copy.deepcopy(record))
    return result


def budgets(scene, assets, gif_cache_pixels):
    crop_pixels, cache_pixels = 0, 0
    for layer in scene['layers']:
        if layer['type'] != 'sprites':
            continue
        source = assets[layer['source']]['rgba']
        for record in layer['frames']:
            x, y, width, height = record['rect']
            if x + width > source.width or y + height > source.height:
                raise ValueError('Sprite frame rectangle exceeds the PNG atlas')
            crop_pixels += width * height
        cache_pixels += len(layer['frames']) * layer['size'][0] * layer['size'][1]
    if crop_pixels > MAX_CROP_PIXEL_FRAMES:
        raise ValueError('Sprite layers exceed decoded crop pixel-frame budget')
    if cache_pixels + gif_cache_pixels > layer_gifs.MAX_CACHED_PIXELS:
        raise ValueError('Animated layers exceed combined cached raster pixel budget')
    return {'crop_pixel_frames': crop_pixels, 'cached_pixels_upper_bound': cache_pixels}


def sequence(layer):
    delays = [record['duration_ms'] for record in layer['frames']]
    ends, elapsed = [], 0
    for delay in delays:
        elapsed += delay
        ends.append(elapsed)
    # The shared sampler only needs the number of records, not decoded images.
    return {'frames': layer['frames'], 'delays_ms': delays, 'ends_ms': ends,
            'duration_ms': elapsed, 'native_loop': None}


def timing_report(scene):
    result = {}
    period = 1000 // scene['fps']
    for layer in scene['layers']:
        if layer['type'] != 'sprites':
            continue
        info = sequence(layer)
        result[layer['id']] = {'source_drawings': len(layer['frames']),
            'source_duration_ms': info['duration_ms'], 'source_delays_ms': info['delays_ms'],
            'playback': layer['playback'], 'sampling': layer['sampling'],
            **(pose_tracks.selection_report(layer, period) if 'pose_keys' in layer
               else layer_gifs.selection_report(info, layer, period)),
            'rectangles': [record['rect'] for record in layer['frames']]}
    return result


def import_project(manifest_path, out, *, width=512, height=512, fps=50, repeat=False, dry_run=False):
    """Import a verified sprites pack/slice atlas into one portable scene.

    Only the atlas and its crop hashes are consumed. Preview GIFs and individual
    frame files are not imported, decoded, or treated as pixel authorities.
    """
    from PIL import Image
    from . import layers
    manifest_path = Path(manifest_path).resolve()
    raw = layers.read_regular(manifest_path, 1024 * 1024)
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f'Duplicate sprite manifest field: {key}')
            value[key] = item
        return value
    try:
        manifest = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Sprite manifest must be bounded UTF-8 JSON') from exc
    if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('Require a schema-1 sprites pack/slice manifest')
    atlas_name = layers.source_name(manifest.get('atlas'))
    atlas_path = (manifest_path.parent / atlas_name).resolve()
    if not atlas_path.is_relative_to(manifest_path.parent):
        raise ValueError('Sprite atlas escapes manifest directory')
    layout = manifest.get('frame_layout')
    if not isinstance(layout, list) or not 1 <= len(layout) <= layer_gifs.MAX_FRAMES:
        raise ValueError('Sprite manifest requires 1..256 frame_layout records')
    if type(manifest.get('frame_count')) is not int or manifest['frame_count'] != len(layout):
        raise ValueError('Sprite manifest frame_count does not match layout')
    records, expected_crops = [], []
    for index, record in enumerate(layout):
        if not isinstance(record, dict) or type(record.get('index')) is not int or record['index'] != index:
            raise ValueError('Sprite layout indices must be consecutive and ordered')
        expected = record.get('rgba_sha256')
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Sprite layout requires valid RGBA drawing hashes')
        records.append({'rect': record.get('rect'), 'duration_ms': record.get('duration_ms')})
        expected_crops.append(expected)
    records = normalize_frames(records)
    duration = sum(record['duration_ms'] for record in records)
    if type(manifest.get('duration_ms')) is not int or manifest['duration_ms'] != duration:
        raise ValueError('Sprite manifest duration does not match drawing delays')
    hashes = manifest.get('files_sha256')
    expected_atlas = hashes.get(atlas_name) if isinstance(hashes, dict) else None
    if not isinstance(expected_atlas, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_atlas):
        raise ValueError('Sprite manifest requires the atlas file SHA-256')
    atlas_size = manifest.get('atlas_size')
    if not isinstance(atlas_size, list) or len(atlas_size) != 2:
        raise ValueError('Sprite manifest atlas_size must be a positive integer pair')
    for component in atlas_size:
        motion.number(component, 'atlas_size', 1, MAX_ATLAS_SIDE, True)
    # Validate scene parameters and duration before decoding/allocating pixels.
    if type(fps) is not int or fps not in (25, 50):
        raise ValueError('FPS must be 25 or 50')
    if type(repeat) is not bool or type(dry_run) is not bool:
        raise ValueError('repeat and dry_run must be boolean')
    period = 1000 // fps
    if repeat and duration % period:
        raise ValueError('Exact repeat requires source duration to align with the output frame period')
    # A render requires at least two output frames. Once adds a stated final
    # hold; repeat adds only complete native cycles, never an implicit seam pause.
    cycles = max(1, (2 * period + duration - 1) // duration) if repeat else 1
    output_duration = duration * cycles if repeat else max(2 * period, ((duration + period - 1) // period) * period)
    scene = layers.normalize_scene({'format': layers.FORMAT, 'schema_version': 1,
        'title': 'Imported sprite animation', 'width': width, 'height': height,
        'duration_ms': output_duration, 'fps': fps, 'loop': repeat,
        'layers': [{'id': 'actor', 'type': 'sprites', 'source': atlas_name, 'sha256': expected_atlas,
                    'size': [width, height], 'frames': records, 'sampling': 'pixel',
                    'playback': 'loop' if repeat else 'once'}]})
    atlas_raw = layers.read_regular(atlas_path, layers.MAX_ASSET_BYTES)
    if layers.digest(atlas_raw) != expected_atlas:
        raise ValueError('Sprite atlas file hash differs from manifest')
    with Image.open(io.BytesIO(atlas_raw)) as image:
        if image.format != 'PNG' or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Sprite atlas must be a still PNG')
        if max(image.size) > MAX_ATLAS_SIDE or image.width * image.height > min(MAX_ATLAS_PIXELS, layers.MAX_TOTAL_ASSET_PIXELS):
            raise ValueError('Sprite atlas exceeds decoded pixel budget')
        if manifest.get('atlas_size') != list(image.size):
            raise ValueError('Sprite atlas_size does not match PNG dimensions')
        # PNG getexif() may call load(), so even metadata inspection must follow
        # allocation preflight. Budgets/rectangles only need header dimensions.
        bounds = budgets(scene, {atlas_name: {'rgba': image}}, 0)
        if image.getexif().get(274, 1) != 1:
            raise ValueError('Sprite atlas cannot carry EXIF orientation')
        rgba = image.convert('RGBA')
    for record, expected in zip(records, expected_crops):
        x, y, w, h = record['rect']
        if layers.digest(rgba.crop((x, y, x + w, y + h)).tobytes()) != expected:
            raise ValueError('Sprite drawing RGBA hash differs from manifest')
    plan = {'format': 'gif-cinema-sprite-import', 'schema_version': 1,
        'status': 'planned' if dry_run else 'saved', 'api_calls': 0,
        'manifest_sha256': layers.digest(raw), 'atlas_sha256': expected_atlas,
        'drawings': len(records), 'source_duration_ms': duration, 'duration_ms': output_duration,
        'final_hold_ms': 0 if repeat else output_duration - duration,
        'source_cycles': cycles, 'fps': fps, 'loop': repeat,
        'sprite_budget': bounds, 'verification': 'atlas bytes and every selected drawing RGBA hash matched',
        'drawing_rgba_sha256': expected_crops,
        'note': 'Imports authored drawings, not their lossy GIF preview; visual acceptance remains pending.'}
    if dry_run:
        return plan
    if layers.digest(layers.read_regular(manifest_path, 1024 * 1024)) != plan['manifest_sha256']:
        raise ValueError('Sprite manifest changed during import')
    if layers.digest(layers.read_regular(atlas_path, layers.MAX_ASSET_BYTES)) != expected_atlas:
        raise ValueError('Sprite atlas changed during import')
    saved = layers.save_bundle({'scene': scene, 'assets': {atlas_name: {
        'raw': atlas_raw, 'sha256': expected_atlas}}}, out)
    plan['scene'] = str(saved)
    with (saved.parent / 'import-receipt.json').open('x', encoding='utf-8') as handle:
        json.dump({**plan, 'scene': 'scene.json'}, handle, indent=2, allow_nan=False)
        handle.write('\n')
    return plan
