"""Bounded existing GIF drawings for the offline layer compositor."""
import bisect
import io

MAX_FRAMES = 256
MAX_DURATION_MS = 120000
MAX_CACHED_PIXELS = 32 * 1024 * 1024


def decode(raw, frame_pixel_limit, remaining_pixels):
    from PIL import Image, ImageSequence
    from .cli import check_gif_limits
    if remaining_pixels <= 0:
        raise ValueError('Assets exceed decoded pixel budget')
    stats = check_gif_limits(raw, max_frames=MAX_FRAMES,
                             max_pixel_frames=remaining_pixels, fixed_canvas=True)
    if stats['width'] * stats['height'] > frame_pixel_limit:
        raise ValueError('GIF asset exceeds per-frame decoded pixel budget')
    frames, delays, elapsed = [], [], 0
    with Image.open(io.BytesIO(raw)) as source:
        native_loop = source.info.get('loop')
        for frame in ImageSequence.Iterator(source):
            delay = frame.info.get('duration', 0)
            if type(delay) is not int or not 20 <= delay <= 60000:
                raise ValueError('GIF layer frame delays must be 20..60000 milliseconds')
            elapsed += delay
            if elapsed > MAX_DURATION_MS:
                raise ValueError('GIF layer source duration exceeds 120 seconds')
            image = frame.convert('RGBA').copy()
            image.info.clear()
            frames.append(image)
            delays.append(delay)
    if not frames:
        raise ValueError('GIF layer source has no drawings')
    ends, elapsed = [], 0
    for delay in delays:
        elapsed += delay
        ends.append(elapsed)
    return {'frames': frames, 'rgba': frames[0], 'delays_ms': delays,
            'ends_ms': ends, 'duration_ms': elapsed, 'native_loop': native_loop}


def frame_index(asset, time_ms, playback):
    """Sample native delay intervals; only explicit loop playback wraps."""
    elapsed = time_ms % asset['duration_ms'] if playback == 'loop' else time_ms
    return min(len(asset['frames']) - 1, bisect.bisect_right(asset['ends_ms'], elapsed))


def cache_budget(scene, assets):
    """Bound all resized GIF rasters before allocating their cached variants."""
    pixels = sum(layer['size'][0] * layer['size'][1] * len(assets[layer['source']]['frames'])
                 for layer in scene['layers'] if layer['type'] == 'gif')
    if pixels > MAX_CACHED_PIXELS:
        raise ValueError('GIF layers exceed cached raster pixel budget')
    return pixels


def timing_report(scene, assets):
    period = 1000 // scene['fps']
    result = {}
    for layer in scene['layers']:
        if layer['type'] != 'gif':
            continue
        asset = assets[layer['source']]
        used = {frame_index(asset, time - layer['in_ms'], layer['playback'])
                for time in range(layer['in_ms'], layer['out_ms'], period)}
        result[layer['id']] = {
            'source_drawings': len(asset['frames']), 'source_duration_ms': asset['duration_ms'],
            'source_delays_ms': asset['delays_ms'], 'source_loop_metadata': asset['native_loop'],
            'playback': layer['playback'], 'sampled_source_indices': sorted(used),
            'omitted_source_drawings': sorted(set(range(len(asset['frames']))) - used),
            'sampling': 'native source delay intervals at output frame times; once holds the final drawing; loop wraps explicitly'}
    return result
