"""Authored point attachments for the offline layer renderer.

These constraints position a layer anchor. They do not track depicted hands,
solve a skeleton, inherit transforms, or certify physical/visual contact.
"""
import bisect
import math

from . import motion

MAX_SEGMENTS = 32


def normalize(scene):
    """Validate a complete, frame-aligned attachment schedule and an acyclic graph."""
    by_id = {layer['id']: layer for layer in scene['layers']}
    graph = {key: set() for key in by_id}
    period = 1000 // scene['fps']
    for layer in scene['layers']:
        if 'attachments' not in layer:
            continue
        segments = layer['attachments']
        if not isinstance(segments, list) or not 1 <= len(segments) <= MAX_SEGMENTS:
            raise ValueError('attachments must contain 1..32 segments')
        # Neutral normalized x/y values survive save/reopen. Non-neutral values
        # would otherwise be silently ignored, including inherited keyframes.
        if any(key['x'] != .5 or key['y'] != .5 for key in layer['keyframes']):
            raise ValueError('Attached layers cannot animate x/y; animate their parent instead')
        cursor = layer['in_ms']
        for segment in segments:
            if not isinstance(segment, dict) or set(segment) != {'start_ms', 'end_ms', 'parent', 'point'}:
                raise ValueError('Attachment needs only start_ms, end_ms, parent and point')
            start, end = segment['start_ms'], segment['end_ms']
            motion.number(start, 'attachment.start_ms', 0, scene['duration_ms'] - 1, True)
            motion.number(end, 'attachment.end_ms', 1, scene['duration_ms'], True)
            if start != cursor or end <= start or start % period or end % period:
                raise ValueError('Attachments must be ordered, contiguous and aligned to the frame grid')
            cursor = end
            parent = segment['parent']
            if not isinstance(parent, str) or parent not in by_id or parent == layer['id']:
                raise ValueError('Attachment parent must name another existing layer exactly')
            target = by_id[parent]
            if start < target['in_ms'] or end > target['out_ms']:
                raise ValueError('Attachment parent must be active throughout its segment')
            point = segment['point']
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError('Attachment point must be a normalized pair')
            for number in point:
                motion.number(number, 'attachment.point', 0, 1)
            graph[layer['id']].add(parent)
        if cursor != layer['out_ms']:
            raise ValueError('Attachments must cover the complete child active interval')
    visiting, visited = set(), set()

    def visit(key):
        if key in visiting:
            raise ValueError('Attachment parent graph must be acyclic, including across time')
        if key in visited:
            return
        visiting.add(key)
        for parent in graph[key]:
            visit(parent)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)


def segment_at(layer, time_ms, *, before=False):
    segments = layer.get('attachments', [])
    for segment in segments:
        if ((segment['start_ms'] < time_ms <= segment['end_ms']) if before
                else (segment['start_ms'] <= time_ms < segment['end_ms'])):
            return segment
    # The conceptual closing endpoint is used for diagnosis, never exported.
    if segments and time_ms == layer['out_ms']:
        return segments[-1]
    return None


def world_point(scene, layer, raster, state, point):
    """Map a normalized actual-raster point through the renderer's affine transform."""
    dx = (point[0] - layer['anchor'][0]) * raster.width * state['zoom']
    dy = (point[1] - layer['anchor'][1]) * raster.height * state['zoom']
    angle = math.radians(state['rotation'])
    return (state['x'] * scene['width'] + math.cos(angle) * dx - math.sin(angle) * dy,
            state['y'] * scene['height'] + math.sin(angle) * dx + math.cos(angle) * dy)


def resolve(prepared, time_ms, *, before=False):
    """Resolve positions independently of paint order. Rotation/scale remain local."""
    from . import layers
    scene = prepared['scene']
    motion.number(time_ms, 'time_ms', 0, scene['duration_ms'])
    by_id = {layer['id']: layer for layer in scene['layers']}
    states = {}

    def state_for(key):
        if key in states:
            return states[key]
        layer = by_id[key]
        if before and layer['in_ms'] < time_ms <= layer['out_ms']:
            progress = (time_ms - layer['in_ms']) / (layer['out_ms'] - layer['in_ms'])
            keys = layer['keyframes']
            state = layers.evaluate(keys, progress)
            index = bisect.bisect_left([key['at'] for key in keys], progress)
            if index > 0 and index < len(keys) and keys[index]['at'] == progress and keys[index - 1]['easing'] == 'step':
                # A step keeps the outgoing pose right up to the boundary.
                # Evaluating the new key here would hide its transfer jump.
                state = {name: keys[index - 1][name] for name in state}
        elif before:
            state = None
        else:
            state = layers.layer_transform(scene, layer, time_ms)
        if state is not None and layer.get('attachments'):
            segment = segment_at(layer, time_ms, before=before)
            if segment is None:
                raise ValueError('Active attached layer has no attachment segment')
            parent = by_id[segment['parent']]
            parent_state = state_for(parent['id'])
            if parent_state is None:
                raise ValueError('Active attachment has an inactive parent')
            x, y = world_point(scene, parent, prepared['rasters'][parent['id']], parent_state, segment['point'])
            state['x'], state['y'] = x / scene['width'], y / scene['height']
            state['attachment'] = {'parent': parent['id'], 'point': list(segment['point'])}
        states[key] = state
        return state

    for key in by_id:
        state_for(key)
    return states


def review(prepared):
    """Report authored switch gaps, not measured image contact or visual acceptance."""
    scene = prepared['scene']
    attached = [layer for layer in scene['layers'] if layer.get('attachments')]
    if not attached:
        return None
    # All schedule boundaries matter, including an ancestor switching parent.
    boundaries = sorted({segment['start_ms'] for layer in attached
                         for segment in layer['attachments'][1:]})
    switches = []
    for timestamp in boundaries:
        before, after = resolve(prepared, timestamp, before=True), resolve(prepared, timestamp)
        for layer in attached:
            key = layer['id']
            left, right = before[key], after[key]
            if left is None or right is None:
                continue
            dx = (right['x'] - left['x']) * scene['width']
            dy = (right['y'] - left['y']) * scene['height']
            own_switch = left['attachment'] != right['attachment']
            gap = math.hypot(dx, dy)
            if own_switch or gap > 1e-9:
                switches.append({'layer': key, 'time_ms': timestamp,
                    'from_parent': left['attachment']['parent'], 'to_parent': right['attachment']['parent'],
                    'own_schedule_switch': own_switch,
                    'before_anchor_px': [left['x'] * scene['width'], left['y'] * scene['height']],
                    'after_anchor_px': [right['x'] * scene['width'], right['y'] * scene['height']],
                    'anchor_gap_px': gap})
    return {'status': 'human-review-required', 'attached_layers': [layer['id'] for layer in attached],
        'switches': switches, 'max_switch_gap_px': max((row['anchor_gap_px'] for row in switches), default=0),
        'scope': 'Authored anchor positions at schedule boundaries, not image tracking, grip/contact validation, '
                 'collision detection or visual acceptance. Zero gap does not prove natural motion. '
                 'Parent opacity, rotation and zoom are not inherited; the attachment point follows parent transforms.'}
