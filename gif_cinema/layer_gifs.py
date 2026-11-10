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


def normalize_range(value):
    """Validate an authored half-open source interval before reading any asset."""
    from . import motion
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('source_range_ms must be [start, end]')
    for component in value:
        motion.number(component, 'source_range_ms', 0, MAX_DURATION_MS, True)
        if component % 10:
            raise ValueError('Source range boundaries must use 10 ms units')
    if value[1] - value[0] < 20:
        raise ValueError('Source range must select at least 20 ms, with start before end')
    return list(value)


def playback_range(asset, layer):
    start, end = layer.get('source_range_ms', [0, asset['duration_ms']])
    if end > asset['duration_ms']:
        raise ValueError(f'Source range for {layer["id"]} exceeds the native animation duration')
    return start, end


def frame_index(asset, time_ms, playback, source_range_ms=None):
    """Sample original intervals inside a half-open trim, retaining source indices."""
    start, end = source_range_ms if source_range_ms is not None else (0, asset['duration_ms'])
    duration = end - start
    elapsed = time_ms % duration if playback == 'loop' else max(0, time_ms)
    if playback != 'loop' and elapsed >= duration:
        # end is exclusive: an exact source boundary must hold the preceding
        # drawing, not leak the first excluded drawing into the final hold.
        return min(len(asset['frames']) - 1, bisect.bisect_left(asset['ends_ms'], end))
    return min(len(asset['frames']) - 1, bisect.bisect_right(asset['ends_ms'], start + elapsed))


def selection_report(asset, layer, period):
    start, end = playback_range(asset, layer)
    starts = [0, *asset['ends_ms'][:-1]]
    selected = [index for index, (a, b) in enumerate(zip(starts, asset['ends_ms']))
                if a < end and b > start]
    used = {frame_index(asset, time - layer['in_ms'], layer['playback'], (start, end))
            for time in range(layer['in_ms'], layer['out_ms'], period)}
    all_indices = set(range(len(asset['frames'])))
    return {'source_range_ms': [start, end], 'playback_duration_ms': end - start,
            'selected_source_indices': selected,
            'selected_delays_ms': [min(end, asset['ends_ms'][index]) - max(start, starts[index]) for index in selected],
            'trimmed_source_drawings': sorted(all_indices - set(selected)),
            'unsampled_selected_drawings': sorted(set(selected) - used),
            'sampled_source_indices': sorted(used),
            'omitted_source_drawings': sorted(all_indices - used)}


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
        result[layer['id']] = {
            'source_drawings': len(asset['frames']), 'source_duration_ms': asset['duration_ms'],
            'source_delays_ms': asset['delays_ms'], 'source_loop_metadata': asset['native_loop'],
            'playback': layer['playback'], **selection_report(asset, layer, period),
            'sampling': 'native source delay intervals at output frame times; once holds the final drawing; loop wraps explicitly'}
    return result
