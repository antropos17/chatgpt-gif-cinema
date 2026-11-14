"""Bounded JSON contract for native sprite, camera, light and sound projects."""
import hashlib
import json
import math
import os
from pathlib import Path
import re

from PIL import Image
from . import layers

FORMAT = 'gif-cinema-shot-project'
FIELDS = set('format schema_version title width height fps background files clips actors shadows shadow_blur occlusion_threshold occlusion_blur glow_blur camera_push effects overlays audio scenes'.split())
EFFECTS = {
    'ambient': 'particles drift speed color strength flicker',
    'path-light': 'start end fade_in fade_out trail_start trail_end trail_step trail_samples radius pulse color satellites orbit_speed orbit_radius orbit_wobble orbit_aspect satellite_radius path',
    'burst': 'start xy color duration radius speed aspect width count angle scatter particle_radius',
    'ribbons': 'start bands samples travel origin spread rise waves speed phase amplitude spacing fade_in fade_out fade_duration color glow_width width',
    'swarm': 'start particles targets delay travel origin control spread wobble speed fade_in colors color_every radius strength flicker star_every star_after star_strength star_radius',
    'arrival': 'start xy travel path flight_radius flight_color radius color fade_in strength ring_duration ring_radius ring_speed ring_strength ring_width',
}


def fields(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError(f'{label}: expected fields {sorted(names)}')


def number(value, lo, hi, label, integer=False):
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{label}: expected {lo}..{hi}')


def vector(value, length, label, lo=-10000, hi=10000):
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f'{label}: expected a {length}-element list')
    for n in value:
        number(n, lo, hi, label)


def bounded(value, depth=0):
    if depth > 12:
        raise ValueError('Project nesting exceeds budget')
    if isinstance(value, dict):
        for key, v in value.items():
            if key == 'bytes':
                number(v, 0, 32*1024*1024, 'asset bytes', True)
            else:
                bounded(v, depth+1)
    elif isinstance(value, list):
        if len(value) > 600:
            raise ValueError('Project array exceeds budget')
        for v in value:
            bounded(v, depth+1)
    elif type(value) in (int, float):
        number(value, -1000000, 1000000, 'Project number')
    elif not isinstance(value, (str, bool)) and value is not None:
        raise ValueError('Unsupported JSON value')


def validate_effect(e):
    kind = e.get('type') if isinstance(e, dict) else None
    if kind not in EFFECTS:
        raise ValueError('Unknown light effect type')
    fields(e, ['type', 'plane', *EFFECTS[kind].split()], f'{kind} effect')
    if e['plane'] not in ('front', 'behind'):
        raise ValueError('Effect plane must be front or behind')
    vectors = {'ambient': {'speed', 'strength'}, 'swarm': {'radius', 'strength'},
               'path-light': set(), 'burst': set(), 'ribbons': set(), 'arrival': set()}
    structured = {'type', 'plane', 'particles', 'targets', 'colors', 'path', 'color', 'flight_color',
                  'xy', 'origin', 'control', 'wobble', 'scatter'} | vectors[kind]
    for key in set(e)-structured:
        number(e[key], -10000, 10000, f'{kind}.{key}')
    for key in ('fade_in', 'duration', 'travel', 'fade_duration', 'ring_duration', 'trail_step'):
        if key in e:
            number(e[key], .00001, 300, key)
    for key in ('count', 'bands', 'samples', 'trail_samples', 'satellites', 'color_every', 'star_every', 'width', 'glow_width', 'ring_width'):
        if key in e:
            number(e[key], 2 if key == 'samples' else 1, 600 if key.endswith('samples') else 256, key, True)
    for key in ('color', 'flight_color'):
        if key in e:
            vector(e[key], 3, key, 0, 255)
    for key in ('xy', 'origin', 'control', 'wobble', 'scatter'):
        if key in e:
            vector(e[key], 2, key)
    if 'particles' in e:
        for particle in e['particles']:
            vector(particle, 4, 'particle')
    if kind == 'swarm':
        if len(e['targets']) != len(e['particles']):
            raise ValueError('Swarm targets and particles differ')
        for target in e['targets']:
            vector(target, 2, 'target')
        if len(e['colors']) != 2:
            raise ValueError('Swarm requires two colors')
        for color in e['colors']:
            vector(color, 3, 'color', 0, 255)
        vector(e['radius'], 2, 'radius', 0, 128)
        vector(e['strength'], 2, 'strength', 0, 1)
    elif kind == 'ambient':
        vector(e['speed'], 2, 'speed')
        vector(e['strength'], 2, 'strength', 0, 1)
    elif kind == 'path-light':
        if e['end'] <= e['fade_out'] or e['end'] <= e['start'] or not e['path']:
            raise ValueError('Invalid path-light interval')
        previous = None
        for segment in e['path']:
            kind = segment.get('kind')
            if kind not in ('linear', 'bezier', 'orbit'):
                raise ValueError('Unknown light path kind')
            allowed = {'kind', 'start', 'end', 'points'} | ({'radius'} if kind == 'orbit' else set())
            if set(segment) - (allowed | {'ease', 'duration'}) or not allowed <= set(segment):
                raise ValueError('Invalid light path fields')
            if 'duration' in segment:
                number(segment['duration'], .00001, 300, 'path duration')
                if not math.isclose(segment['duration'], segment['end']-segment['start'], abs_tol=1e-9):
                    raise ValueError('Explicit path duration must match its interval')
            if segment['end'] <= segment['start'] or (previous is not None and segment['start'] != previous):
                raise ValueError('Path segments must be ordered and contiguous')
            if len(segment['points']) != {'linear': 2, 'bezier': 3, 'orbit': 1}[kind]:
                raise ValueError('Invalid light path points')
            for point in segment['points']:
                vector(point, 2, 'path point')
            if kind == 'orbit':
                vector(segment['radius'], 2, 'orbit radius', 0, 10000)
            previous = segment['end']
    elif kind == 'arrival':
        if len(e['path']) != 3:
            raise ValueError('Arrival requires a quadratic path')
        for point in e['path']:
            vector(point, 2, 'path point')


def load_project(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Project must not use symlinks')
    raw = layers.read_regular(path, 1024*1024)
    value = json.loads(raw)
    bounded(value)
    fields(value, FIELDS, 'Shot project')
    if value['format'] != FORMAT or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Expected schema-1 native shot project')
    if not isinstance(value['title'], str) or not 1 <= len(value['title']) <= 120:
        raise ValueError('Invalid title')
    for dim in ('width', 'height'):
        number(value[dim], 2, 1920, dim, True)
        if value[dim] % 2:
            raise ValueError('Output dimensions must be even')
    number(value['fps'], 1, 60, 'fps', True)
    if not isinstance(value['scenes'], list) or not 1 <= len(value['scenes']) <= 32:
        raise ValueError('Expected 1..32 scenes')
    previous, seen = None, set()
    for scene in value['scenes']:
        fields(scene, ['id', 'start_frame', 'end_frame', 'camera', 'effects'], 'Scene')
        sid = scene['id']
        if not isinstance(sid, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,39}', sid) or sid.lower() in seen:
            raise ValueError('Scene IDs must be portable and unique')
        seen.add(sid.lower())
        for key in ('start_frame', 'end_frame'):
            number(scene[key], 0, 18000, key, True)
        if scene['end_frame'] <= scene['start_frame'] or previous is not None and scene['start_frame'] != previous:
            raise ValueError('Scenes must partition a contiguous source clock')
        previous = scene['end_frame']
        vector(scene['camera'], 4, 'camera', 0, max(value['width'], value['height']))
        x0, y0, x1, y1 = scene['camera']
        if not (x0 < x1 <= value['width'] and y0 < y1 <= value['height']):
            raise ValueError('Camera crop must be inside the stage')
        fields(scene['effects'], ['gain'], 'Scene effects')
        number(scene['effects']['gain'], 0, 2, 'gain')
    frames = previous-value['scenes'][0]['start_frame']
    if frames > 7500 or frames*value['width']*value['height'] > 320*1024*1024:
        raise ValueError('Shot project exceeds frame/pixel budget')
    paths, total = {}, 0
    if not isinstance(value['files'], dict) or not 1 <= len(value['files']) <= 32:
        raise ValueError('Expected 1..32 file records')
    for name, fact in value['files'].items():
        fields(fact, ['path', 'sha256', 'bytes'], 'Asset')
        if not isinstance(fact['path'], str) or Path(fact['path']).is_absolute() or ':' in fact['path'] or '\\' in fact['path']:
            raise ValueError('Assets must use relative local POSIX paths')
        candidate = path.parent / fact['path']
        if any(p.is_symlink() for p in (candidate, *candidate.parents)):
            raise ValueError('Assets must not use symlinks')
        data = layers.read_regular(candidate, 32*1024*1024)
        total += len(data)
        if total > 96*1024*1024 or len(data) != fact['bytes'] or hashlib.sha256(data).hexdigest() != fact['sha256']:
            raise ValueError('Asset hash/byte budget differs')
        paths[name] = Path(os.path.abspath(candidate))
    if value['background'] not in paths:
        raise ValueError('Missing background asset')
    with Image.open(paths[value['background']]) as image:
        if image.size != (value['width'], value['height']):
            raise ValueError('Background geometry differs')
    if not isinstance(value['clips'], dict) or len(value['clips']) > 32:
        raise ValueError('Invalid clips')
    pixels = 0
    for clip in value['clips'].values():
        fields(clip, 'source frames columns tile_size xy mask threshold blur'.split(), 'Clip')
        if clip['source'] not in paths or clip['mask'] not in ('alpha', 'background-difference'):
            raise ValueError('Invalid clip source/mask')
        number(clip['frames'], 1, 600, 'clip frames', True)
        number(clip['columns'], 1, 32, 'clip columns', True)
        vector(clip['tile_size'], 2, 'tile size', 1, 1024)
        vector(clip['xy'], 2, 'xy', 0, 1920)
        if any(type(n) is not int for n in clip['tile_size']+clip['xy']):
            raise ValueError('Tile geometry must use integers')
        number(clip['threshold'], 0, 255, 'mask threshold')
        number(clip['blur'], 0, 10, 'mask blur')
        w, h = clip['tile_size']; cols = clip['columns']
        pixels += clip['frames']*w*h
        if clip['xy'][0]+w > value['width'] or clip['xy'][1]+h > value['height']:
            raise ValueError('Clip must fit its stage')
        with Image.open(paths[clip['source']]) as image:
            if image.width != cols*w or image.height < math.ceil(clip['frames']/cols)*h or image.height > 16384:
                raise ValueError('Atlas geometry differs')
    if pixels > 96*1024*1024:
        raise ValueError('Decoded clip pixels exceed budget')
    for actor in value['actors']:
        fields(actor, ['id', 'tracks'], 'Actor')
        end = -1
        for track in actor['tracks']:
            fields(track, 'clip start end origin duration loop first last'.split(), 'Performance track')
            for key in ('start', 'end', 'origin'):
                number(track[key], -300, 300, f'performance {key}')
            if track['clip'] not in value['clips'] or type(track['loop']) is not bool:
                raise ValueError('Invalid performance clip/loop')
            if track['start'] < end or track['end'] <= track['start']:
                raise ValueError('Performance tracks overlap or have no duration')
            end = track['end']
            number(track['duration'], .00001, 300, 'performance duration')
            for key in ('first', 'last'):
                number(track[key], 0, value['clips'][track['clip']]['frames']-1, key, True)
    for effect in value['effects']:
        validate_effect(effect)
    for shadow in value['shadows']:
        fields(shadow, ['xy', 'radius', 'color'], 'Shadow')
        vector(shadow['xy'], 2, 'shadow xy'); vector(shadow['radius'], 2, 'shadow radius', 0, 1920)
        vector(shadow['color'], 4, 'shadow color', 0, 255)
    for name in ('shadow_blur', 'occlusion_blur', 'glow_blur'):
        number(value[name], 0, 64, name)
    number(value['occlusion_threshold'], 0, 255, 'occlusion threshold')
    fields(value['camera_push'], ['amplitude', 'speed'], 'Camera push')
    number(value['camera_push']['amplitude'], 0, .25, 'camera push amplitude')
    number(value['camera_push']['speed'], 0, 100, 'camera push speed')
    for overlay in value['overlays']:
        fields(overlay, 'type particles wrap offset speed amplitude radius aspect color'.split(), 'Overlay')
        if overlay['type'] != 'petals':
            raise ValueError('Unknown overlay type')
        number(overlay['wrap'], 1, 10000, 'overlay wrap')
        vector(overlay['radius'], 2, 'overlay radius', .01, 1000)
        vector(overlay['color'], 4, 'overlay color', 0, 255)
        for particle in overlay['particles']:
            vector(particle, 4, 'overlay particle')
    audio = value['audio']
    fields(audio, 'rate duration fade_in fade_out tones noise'.split(), 'Audio')
    number(audio['rate'], 8000, 48000, 'audio rate', True)
    number(audio['duration'], previous/value['fps'], 300, 'audio duration')
    if audio['rate']*audio['duration'] > 2*1024*1024:
        raise ValueError('Source audio exceeds 2 Mi-sample synthesis budget')
    for key in ('fade_in', 'fade_out'):
        number(audio[key], .00001, 300, key)
    if len(audio['tones']) > 128 or len(audio['noise']) > 32:
        raise ValueError('Audio event budget exceeded')
    for start, length, frequency, gain, pan in audio['tones']:
        number(start, 0, audio['duration'], 'tone start'); number(length, .00001, 30, 'tone length')
        number(frequency, 1, audio['rate']/2, 'tone frequency'); number(gain, 0, 1, 'gain'); number(pan, -1, 1, 'pan')
    for start, end, seed, gain in audio['noise']:
        number(start, 0, audio['duration'], 'noise start'); number(end, start+.00001, audio['duration'], 'noise end')
        number(seed, 0, 1000000, 'noise seed', True); number(gain, 0, 1, 'noise gain')
    return value, paths


def dependencies(value, scene):
    lo, hi = scene['start_frame']/value['fps'], scene['end_frame']/value['fps']
    return [{'id': actor['id'], 'tracks': [t for t in actor['tracks'] if t['start'] < hi and t['end'] > lo]}
            for actor in value['actors']]


def review(value, keys, old):
    decisions = [{'id': s['id'], 'key': keys[s['id']],
                  'encoding': 'reuse' if old and old['keys'].get(s['id']) == keys[s['id']] else 'render'} for s in value['scenes']]
    changed = {d['id'] for d in decisions if d['encoding'] == 'render'}
    neighbors, cuts = set(), []
    origin = value['scenes'][0]['start_frame']
    for a, b in zip(value['scenes'], value['scenes'][1:]):
        if a['id'] in changed or b['id'] in changed:
            cuts.append({'previous': a['id'], 'next': b['id'],
                         'at_ms': (b['start_frame']-origin)*1000/value['fps'],
                         'source_at_ms': b['start_frame']*1000/value['fps']})
            neighbors.update([a['id'], b['id']])
    return {'scenes': decisions, 'changed_scenes': sorted(changed),
            'neighbor_scenes_for_review': sorted(neighbors-changed), 'cuts_for_review': cuts,
            'note': 'Independent shots share an absolute performance clock. Neighbors require playback review, not automatic re-encoding.'}
