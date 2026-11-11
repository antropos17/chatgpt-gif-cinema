"""Explicit stepped selection of existing authored atlas drawings, never synthesis."""
import bisect
import copy

from . import motion

# Only floating-point arithmetic noise is accepted, not sub-frame timing.
GRID_TOLERANCE_MS = 1e-7


def normalize(value, drawing_count, duration_ms, period_ms):
    """Validate keys on the active layer's output grid, preserving authored data."""
    if not isinstance(value, list) or not 2 <= len(value) <= 256:
        raise ValueError('pose_keys must contain 2..256 records')
    result, previous_time = [], -1
    for key in value:
        if not isinstance(key, dict) or set(key) != {'at', 'frame'}:
            raise ValueError('Each pose key requires only at and frame')
        at = motion.number(key['at'], 'pose key at', 0, 1)
        motion.number(key['frame'], 'pose key frame', 0, drawing_count - 1, True)
        if result and at <= result[-1]['at']:
            raise ValueError('Pose key times must strictly increase')
        time = at * duration_ms
        grid_time = round(time / period_ms) * period_ms
        if abs(time - grid_time) > GRID_TOLERANCE_MS:
            raise ValueError('Pose key times must align with the output frame grid')
        if grid_time <= previous_time:
            raise ValueError('Pose keys must occupy distinct output frame times')
        previous_time = grid_time
        result.append(copy.deepcopy(key))
    if result[0]['at'] != 0 or result[-1]['at'] != 1:
        raise ValueError('Pose keys must include 0 and 1 endpoints')
    return result


def index_at(layer, elapsed_ms):
    """Select a drawing at layer-relative time; at=1 is diagnostic, not exported.

    Validated grid times are integral milliseconds. Rounding their floating-point
    representation avoids delaying an authored event by a frame at exact boundaries.
    """
    duration = layer['out_ms'] - layer['in_ms']
    keys = layer['pose_keys']
    times = [round(key['at'] * duration) for key in keys]
    index = max(0, bisect.bisect_right(times, elapsed_ms) - 1)
    return keys[index]['frame']


def selection_report(layer, period_ms):
    """Report actual exported holds separately from the conceptual endpoint."""
    duration = layer['out_ms'] - layer['in_ms']
    indices = [index_at(layer, time) for time in range(0, duration, period_ms)]
    holds = []
    for sample, index in enumerate(indices):
        time = layer['in_ms'] + sample * period_ms
        if holds and holds[-1]['source_index'] == index:
            holds[-1]['out_ms'] = time + period_ms
            holds[-1]['duration_ms'] += period_ms
            holds[-1]['output_frames'] += 1
        else:
            holds.append({'source_index': index, 'in_ms': time,
                          'out_ms': time + period_ms, 'duration_ms': period_ms,
                          'output_frames': 1})
    return {'selection': 'authored-poses', 'source_delays_used': False,
            'pose_keys': copy.deepcopy(layer['pose_keys']),
            'playback_duration_ms': duration,
            'selected_source_indices': [key['frame'] for key in layer['pose_keys'][:-1]],
            'sampled_source_indices': sorted(set(indices)),
            'omitted_source_drawings': sorted(set(range(len(layer['frames']))) - set(indices)),
            'exported_source_indices': indices, 'holds': holds,
            'transitions': [{'time_ms': after['in_ms'],
                             'from_source_index': before['source_index'],
                             'to_source_index': after['source_index']}
                            for before, after in zip(holds, holds[1:])],
            'conceptual_endpoint': {'time_ms': layer['out_ms'],
                                    'source_index': index_at(layer, duration), 'exported': False},
            'note': 'Authored drawing selection only; source delays are unused. No pose interpolation, synthesis or visual acceptance is implied.'}
