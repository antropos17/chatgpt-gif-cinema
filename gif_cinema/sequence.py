"""Carry one authored stage through sequential local actions, with zero provider calls.

The compiler preserves layer identity and transfers transforms/attachments. It
cannot invent poses, track hands in images or certify narrative/visual acceptance.
"""
import argparse
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from . import attachments, cli, factory, layer_sprites, layers, motion, pose_tracks, render

FORMAT = 'gif-cinema-layer-sequence'
MAX_PROJECT_BYTES = 512 * 1024
MAX_SHOTS = 64
MAX_DURATION_MS = 300000
MAX_FRAMES = 7500
MAX_PIXEL_FRAMES = 320 * 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_FILES = 10000
POSE_TOLERANCE = 1e-7
PROPERTIES = tuple(layers.DEFAULTS)
NOTICE = ('Authored transforms and attachment states only. No pose generation, hand tracking, '
          'physics, semantic continuity inference or automatic visual acceptance.')


def load_project(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Sequence inputs must not use symlinks')
    raw = layers.read_regular(path, MAX_PROJECT_BYTES)
    value = factory.parse_json(raw)
    layers.require_fields(value, ['format', 'schema_version', 'title', 'stage', 'shots'],
                          ['format', 'schema_version', 'title', 'stage', 'shots'], 'Sequence')
    if value['format'] != FORMAT or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Expected a schema-1 GIF Cinema layer sequence')
    layers.text_value(value['title'], 'sequence.title', 120)
    stage_path = factory.safe_input(path.parent, value['stage'])
    prepared = layers.prepare_scene(stage_path)
    scene = prepared['scene']
    for layer in scene['layers']:
        if layer['type'] == 'gif' or (layer['type'] == 'sprites' and 'pose_keys' not in layer):
            raise ValueError('Sequence stages use still assets or explicit sprite pose_keys; native animated GIF/sprite clocks cannot implicitly reset between shots')
        if layer['type'] == 'sprites' and any(key['frame'] != layer['pose_keys'][0]['frame'] for key in layer['pose_keys']):
            raise ValueError('The stage must have a static starting sprite pose; author drawing changes in shot tracks')
        if layer['in_ms'] != 0 or layer['out_ms'] != scene['duration_ms']:
            raise ValueError('Every stage layer must be active throughout the seed scene')
        keys = layer['keyframes']
        properties = (*PROPERTIES, 'reveal') if layer['type'] == 'stroke' else PROPERTIES
        if any(any(key[name] != keys[0][name] for name in properties) for key in keys[1:]):
            raise ValueError('The stage must be a static seed pose; author actions in shot tracks')
        if layer.get('attachments') and len(layer['attachments']) != 1:
            raise ValueError('Stage attachments must describe a single starting holder')
    shots = value['shots']
    if not isinstance(shots, list) or not 1 <= len(shots) <= MAX_SHOTS:
        raise ValueError('Sequence shots must contain 1..64 actions')
    seen, total_ms, total_frames = set(), 0, 0
    for shot in shots:
        layers.require_fields(shot, ['id', 'action', 'duration_ms', 'tracks'], ['id', 'action', 'duration_ms'], 'Shot')
        sid = shot['id']
        if (not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}', sid)
                or sid.lower() in seen or sid.lower() in factory.RESERVED_IDS):
            raise ValueError('Shot IDs must be unique portable ASCII identifiers')
        seen.add(sid.lower())
        layers.text_value(shot['action'], 'shot.action', 1000)
        duration = motion.number(shot['duration_ms'], 'shot.duration_ms', 40, 30000, True)
        if duration % (1000 // scene['fps']):
            raise ValueError('Shot duration must align with the stage frame grid')
        total_ms += duration
        total_frames += duration * scene['fps'] // 1000
    if (total_ms > MAX_DURATION_MS or total_frames > MAX_FRAMES
            or total_frames * scene['width'] * scene['height'] > MAX_PIXEL_FRAMES):
        raise ValueError('Sequence exceeds aggregate duration/frame/pixel budget')
    divisor = math.gcd(scene['width'], scene['height'])
    ratio = [scene['width'] // divisor, scene['height'] // divisor]
    if max(ratio) > 99:
        raise ValueError('Reduced stage aspect ratio must fit the ordinary film contract (1..99 per side)')
    return path, raw, value, prepared, ':'.join(map(str, ratio))


def pose_fields(layer, state, attached):
    properties = (*PROPERTIES, 'reveal') if layer['type'] == 'stroke' else PROPERTIES
    pose = {name: state[name] for name in properties}
    if attached:
        pose['x'], pose['y'] = .5, .5
    return pose


def scene_state(prepared, time_ms):
    """Include the authored drawing identity alongside transform/holder state."""
    result = attachments.resolve(prepared, time_ms)
    for layer in prepared['scene']['layers']:
        if layer['type'] == 'sprites':
            result[layer['id']]['source_index'] = pose_tracks.index_at(layer, time_ms - layer['in_ms'])
    return result


def compile_sequence(path):
    path, raw, project, seed, ratio = load_project(path)
    stage = seed['scene']
    previous_scene = stage
    carried = scene_state(seed, 0)
    compiled, timeline, elapsed = [], [], 0
    for shot in project['shots']:
        duration, sid = shot['duration_ms'], shot['id']
        tracks = shot.get('tracks', {})
        ids = {layer['id'] for layer in stage['layers']}
        if not isinstance(tracks, dict) or set(tracks) - ids:
            raise ValueError(f'{sid}: tracks must name existing layer IDs exactly')
        scene = copy.deepcopy(stage)
        scene.update(title=f'{sid}: {shot["action"]}'[:120], duration_ms=duration, loop=False)
        prior_layers = {layer['id']: layer for layer in previous_scene['layers']}
        for layer in scene['layers']:
            name = layer['id']
            track = tracks.get(name, {})
            layers.require_fields(track, ['keyframes', 'attachments', 'pose_keys'], [], f'{sid}.{name} track')
            layer['in_ms'], layer['out_ms'] = 0, duration
            if 'pose_keys' in track and layer['type'] != 'sprites':
                raise ValueError('Only sprite layers accept authored pose_keys')
            if layer['type'] == 'sprites':
                poses = copy.deepcopy(track.get('pose_keys', [{'at': 0}, {'at': 1, 'frame': carried[name]['source_index']}]))
                if not isinstance(poses, list) or not poses or not isinstance(poses[0], dict):
                    raise ValueError(f'{sid}.{name}: invalid pose_keys')
                poses[0] = {'frame': carried[name]['source_index'], **poses[0]}
                layer['pose_keys'] = poses
            binding = None
            if 'attachments' in track:
                binding = copy.deepcopy(track['attachments'])
                if binding is not None and not isinstance(binding, list):
                    raise ValueError('Track attachments must be a schedule or null for an explicit detach')
            elif prior_layers[name].get('attachments'):
                last = prior_layers[name]['attachments'][-1]
                binding = [{**copy.deepcopy(last), 'start_ms': 0, 'end_ms': duration}]
            layer.pop('attachments', None)
            if binding is not None:
                layer['attachments'] = binding
            initial = pose_fields(layer, carried[name], binding is not None)
            keys = copy.deepcopy(track.get('keyframes', [{'at': 0}, {'at': 1}]))
            if not isinstance(keys, list) or not keys or not isinstance(keys[0], dict):
                raise ValueError(f'{sid}.{name}: invalid keyframes')
            keys[0] = {**initial, **keys[0]}
            layer['keyframes'] = keys
        scene = layers.normalize_scene(scene)
        prepared = {**seed, 'scene': scene}
        beginning = scene_state(prepared, 0)
        for layer in scene['layers']:
            name = layer['id']
            for property_name, expected in carried[name].items():
                if property_name == 'attachment':
                    continue  # An explicit holder change is allowed at coincident world anchors.
                actual = beginning[name][property_name]
                if abs(actual - expected) > POSE_TOLERANCE:
                    raise ValueError(f'{sid}.{name}.{property_name}: first pose differs from carried state '
                                     f'({actual!r} instead of {expected!r}); no implicit scene reset is allowed')
        ending = scene_state(prepared, duration)
        frames = duration * scene['fps'] // 1000
        timeline.append({'id': sid, 'action': shot['action'], 'start_ms': elapsed,
            'duration_ms': duration, 'frames': frames, 'start_state': beginning, 'end_state': ending,
            'attachment_review': attachments.review(prepared)})
        compiled.append(prepared)
        carried, previous_scene = ending, scene
        elapsed += duration
    report = {'format': FORMAT, 'schema_version': 1, 'status': 'planned', 'provider_calls': 0,
        'title': project['title'], 'project_sha256': layers.digest(raw),
        'stage_sha256': seed['source_sha256'],
        'asset_sha256': {name: item['sha256'] for name, item in seed['assets'].items()},
        'width': stage['width'], 'height': stage['height'], 'fps': stage['fps'], 'ratio': ratio,
        'duration_ms': elapsed, 'frames': sum(row['frames'] for row in timeline),
        'timeline': timeline, 'visual_acceptance': 'not-established', 'scope': NOTICE,
        'sampling': 'Each scene exports samples at 0..duration-frame_period. The next scene begins at the previous conceptual duration endpoint, not its last stored frame.'}
    if any(layer['type'] == 'sprites' for layer in stage['layers']):
        report['scope'] = NOTICE.replace('Authored transforms and attachment states only.',
            'Author-selected existing atlas drawings, with carried transforms and attachment states.')
    return {'path': path, 'raw': raw, 'project': project, 'seed': seed, 'compiled': compiled, 'report': report}


def file_inventory(root):
    files, total = {}, 0
    for entry_count, path in enumerate(root.rglob('*'), 1):
        if entry_count > MAX_FILES + 512:
            raise ValueError('Sequence exceeds the directory-entry budget')
        if path.is_symlink():
            raise ValueError('Sequence bundle must not contain symlinks')
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        if name == 'sequence-receipt.json':
            continue
        raw = layers.read_regular(path, MAX_FILE_BYTES)
        total += len(raw)
        if len(files) >= MAX_FILES or total > MAX_OUTPUT_BYTES:
            raise ValueError('Sequence exceeds the aggregate file/512 MiB output budget')
        files[name] = {'bytes': len(raw), 'sha256': layers.digest(raw)}
    return files


def dump(path, value):
    raw = factory.json_bytes(value)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError('Sequence receipt exceeds its JSON byte budget')
    path.write_bytes(raw)


def film_script(compilation):
    report = compilation['report']
    return {'schema_version': 1, 'title': report['title'], 'ratio': report['ratio'],
        'width': report['width'], 'height': report['height'], 'fps': report['fps'],
        'style_bible': 'One fixed authored stage with carried layer poses and explicit prop holders. ' + NOTICE,
        'shots': [{'id': row['id'], 'source': f'shots/{row["id"]}/preview.gif',
            'first_frame_target': 'Carried authored stage state; see sequence receipt. Not a semantic observation.',
            'last_frame_target': 'Authored action result: ' + row['action'],
            'caption': row['action'], 'transition': 'cut'} for row in report['timeline']]}


def render_join(previous, following, output=None, verify=None):
    from PIL import Image, ImageDraw
    before = previous['scene']
    step = 1000 // before['fps']
    last, _ = layers.render_at(previous, before['duration_ms'] - step)
    endpoint, _ = layers.render_at(previous, before['duration_ms'])
    first, _ = layers.render_at(following, 0)
    sheet = Image.new('RGB', (3 * before['width'], before['height'] + 28), before['matte'])
    for column, (label, frame) in enumerate([('LAST STORED', last), ('CARRIED ENDPOINT', endpoint), ('NEXT FIRST', first)]):
        sheet.paste(motion.flatten(frame, before['matte']), (column * before['width'], 28))
        ImageDraw.Draw(sheet).text((column * before['width'] + 8, 7), label, fill='white')
    if output is not None:
        sheet.save(output)
    if verify is not None:
        raw = layers.read_regular(verify, 16 * 1024 * 1024)
        with Image.open(io.BytesIO(raw)) as saved:
            if saved.mode != 'RGB' or saved.size != sheet.size or saved.tobytes() != sheet.tobytes():
                raise ValueError('Join sheet differs from the compiled sequence')
    return {'previous_last_rgba_sha256': layers.digest(last.tobytes()),
        'previous_endpoint_rgba_sha256': layers.digest(endpoint.tobytes()),
        'next_first_rgba_sha256': layers.digest(first.tobytes()),
        'endpoint_pixels_equal': endpoint.tobytes() == first.tobytes(),
        'last_stored_pixels_equal': last.tobytes() == first.tobytes(),
        'status': 'human-review-required'}


def verify_sequence(directory):
    """Recompile the portable project, rerender every PNG, and decode the film."""
    from PIL import Image
    root = Path(directory).absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError('Sequence bundle must not use symlinks')
    receipt = factory.parse_json(layers.read_regular(root / 'sequence-receipt.json', MAX_RECEIPT_BYTES))
    if (receipt.get('format') != FORMAT or type(receipt.get('schema_version')) is not int
            or receipt['schema_version'] != 1 or receipt.get('status') != 'human-review-required'):
        raise ValueError('Invalid sequence receipt')
    compilation = compile_sequence(root / 'sequence.json')
    report = compilation['report']
    expected = {key: value for key, value in report.items() if key != 'status'}
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError('Sequence receipt differs from the portable project')
    if type(receipt.get('provider_calls')) is not int or receipt['provider_calls'] != 0 or receipt.get('visual_acceptance') != 'not-established':
        raise ValueError('Sequence receipt must preserve zero-call and unestablished visual status')
    for key in ('original_project_sha256', 'original_stage_sha256'):
        if not isinstance(receipt.get(key), str) or not re.fullmatch(r'[a-f0-9]{64}', receipt[key]):
            raise ValueError('Invalid original-input provenance hash')
    inventory = file_inventory(root)
    if receipt.get('files') != inventory:
        raise ValueError('Sequence bundle file inventory or hashes changed')
    if factory.parse_json(layers.read_regular(root / 'film.json', MAX_PROJECT_BYTES)) != film_script(compilation):
        raise ValueError('Film script differs from compiled scene order or actions')
    count = 0
    joins = []
    for index, (prepared, row) in enumerate(zip(compilation['compiled'], report['timeline'])):
        shot_root = root / 'shots' / row['id']
        saved = layers.prepare_scene(shot_root / 'editable/scene.json')
        if layers.serialize_scene(saved['scene']) != layers.serialize_scene(prepared['scene']):
            raise ValueError(f'{row["id"]}: saved scene differs from the compiled action')
        child = factory.parse_json(layers.read_regular(shot_root / 'receipt.json', layers.MAX_RECEIPT_BYTES))
        if (child.get('frames') != row['frames'] or not isinstance(child.get('samples'), list)
                or len(child['samples']) != row['frames']):
            raise ValueError('Scene receipt timeline does not cover every frame')
        required = {'editable/scene.json', 'preview.gif', 'preview.mp4', 'contact-sheet.png', 'first.png',
                    'last.png', 'closing-endpoint.png', 'loop-seam.png', 'encoded-loop-seam.png'}
        required.update(f'frames/{i:04}.png' for i in range(row['frames']))
        required.update(f'layers/{layer["id"]}.png' for layer in prepared['scene']['layers'])
        required.update(f'editable/{layer["source"]}' for layer in prepared['scene']['layers'] if layer['type'] in ('image', 'sprites'))
        if not isinstance(child.get('outputs'), dict) or set(child['outputs']) != required:
            raise ValueError('Scene export inventory is incomplete or unexpected')
        for name, expected_hash in child['outputs'].items():
            record = inventory.get(f'shots/{row["id"]}/{name}')
            if record is None or record['sha256'] != expected_hash:
                raise ValueError('Scene export hash differs from its receipt')
        if child.get('attachment_review') != row['attachment_review']:
            raise ValueError('Scene attachment review differs from the compiled action')
        if child.get('sprite_timing') != layer_sprites.timing_report(prepared['scene']):
            raise ValueError('Scene sprite timing differs from the compiled action')
        for frame_index, sample in enumerate(child['samples']):
            timestamp = frame_index * (1000 // report['fps'])
            frame, states = layers.render_at(prepared, timestamp)
            if (sample.get('frame') != frame_index or sample.get('time_ms') != timestamp
                    or sample.get('layers') != states or sample.get('rgba_sha256') != layers.digest(frame.tobytes())):
                raise ValueError('Saved scene frame receipt differs from the compiled action')
            raw = layers.read_regular(shot_root / 'frames' / f'{frame_index:04}.png', 16 * 1024 * 1024)
            with Image.open(io.BytesIO(raw)) as png:
                if png.mode != 'RGBA' or png.size != frame.size or png.tobytes() != frame.tobytes():
                    raise ValueError('Saved scene PNG differs from the compiled action')
            count += 1
        if index:
            joins.append({'previous': report['timeline'][index - 1]['id'], 'next': row['id'],
                          **render_join(compilation['compiled'][index - 1], prepared, verify=root / 'joins' / f'{index:02}.png')})
    if receipt.get('joins') != joins:
        raise ValueError('Join evidence differs from the compiled sequence')
    manifest = factory.parse_json(layers.read_regular(root / 'film/render-manifest.json', MAX_RECEIPT_BYTES))
    script = render.load_script(root / 'film.json', argparse.Namespace(width=None, height=None, fps=None),
                                source_only=True, max_import_bytes=MAX_OUTPUT_BYTES)
    for shot in script['shots']:
        record = manifest.get('shots', {}).get(shot['id'])
        if (not isinstance(record, dict) or record.get('sha256') != shot['source_sha256']
                or not render.cached(root / 'film', record, shot)):
            raise ValueError('Film source cache differs from its scene export')
    if manifest.get('film', {}).get('sha256') != inventory.get('film/film.mp4', {}).get('sha256'):
        raise ValueError('Assembled film hash differs from its manifest')
    render.probe(root / 'film/film.mp4', report['width'], report['height'], report['duration_ms'] / 1000,
                 report['fps'], len(report['timeline']))
    return {'status': 'verified', 'provider_calls': 0, 'frames_reopened_and_matched': count,
        'scene_count': len(report['timeline']), 'duration_ms': report['duration_ms'],
        'files_verified': len(inventory), 'joins': joins, 'visual_acceptance': 'not-established',
        'verification_scope': {'source_pngs_and_joins': 'rerendered-and-pixel-matched',
            'film_source_cache': 'byte-identical-to-scene-gif-exports',
            'encoded_film': 'inventory-hash-and-codec-size-duration-decode-only',
            'encoded_pixels_match_source': 'not-established',
            'receipt_authenticity': 'not-established'}, 'scope': report['scope']}


def publish(stage, out):
    # Do not roll back already-published paths after a failure: another writer
    # may have replaced or edited them. Retain partial output for inspection;
    # publication never overwrites, and the completion receipt is written last.
    out.mkdir(exist_ok=False)
    for path in sorted((p for p in stage.rglob('*') if p.is_dir()), key=lambda p: len(p.parts)):
        (out / path.relative_to(stage)).mkdir(exist_ok=False)
    files = sorted((p for p in stage.rglob('*') if p.is_file()),
                   key=lambda p: (p.name == 'sequence-receipt.json', p.as_posix()))
    for path in files:
        cli.publish_file(path, out / path.relative_to(stage))


def build_sequence(path, out, dry_run=False):
    out = Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Sequence output must be a new directory without symlinks')
    compiled = compile_sequence(path)
    if dry_run:
        return compiled['report']
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('FFmpeg and ffprobe are required for building a sequence')
    out.parent.mkdir(parents=True, exist_ok=True)
    with cli.output_lock(out), tempfile.TemporaryDirectory(prefix='.sequence-stage-', dir=out.parent) as temporary:
        stage, work = Path(temporary) / 'sequence', Path(temporary) / 'work'
        stage.mkdir(); work.mkdir(); (stage / 'shots').mkdir(); (stage / 'joins').mkdir()
        layers.save_bundle(compiled['seed'], stage / 'stage')
        portable = {**compiled['project'], 'stage': 'stage/scene.json'}
        dump(stage / 'sequence.json', portable)
        # Recompile the actual portable snapshot, so verification never depends on
        # the author's original paths or a recipe hidden in a temporary directory.
        snapshot = compile_sequence(stage / 'sequence.json')
        receipt = {**snapshot['report'], 'status': 'human-review-required',
            'original_project_sha256': compiled['report']['project_sha256'],
            'original_stage_sha256': compiled['report']['stage_sha256'], 'joins': []}
        for index, (prepared, row) in enumerate(zip(snapshot['compiled'], receipt['timeline'])):
            source = layers.save_bundle(prepared, work / row['id'])
            layers.render_scene(source, stage / 'shots' / row['id'])
            if index:
                receipt['joins'].append({'previous': receipt['timeline'][index - 1]['id'], 'next': row['id'],
                    **render_join(snapshot['compiled'][index - 1], prepared, stage / 'joins' / f'{index:02}.png')})
            file_inventory(stage)  # Bound cumulative media/PNG output after each action.
        dump(stage / 'film.json', film_script(snapshot))
        arguments = argparse.Namespace(script=str(stage / 'film.json'), out=str(stage / 'film'), execute=True,
            max_api_calls=0, retries=0, force=False, force_shot=[], width=None, height=None, fps=None)
        with contextlib.redirect_stdout(io.StringIO()):
            film_receipt = render.run(arguments)
        if film_receipt['api_calls'] != 0:
            raise ValueError('Sequence assembly unexpectedly made a provider call')
        film_receipt['film'] = 'film.mp4'
        dump(stage / 'film/receipt.json', film_receipt)
        # Inputs may have been edited while rendering. Preserve the old workspace
        # and refuse to publish a completed build under changed source identities.
        refreshed = compile_sequence(compiled['path'])
        for key in ('project_sha256', 'stage_sha256', 'asset_sha256'):
            if refreshed['report'][key] != compiled['report'][key]:
                raise ValueError('Sequence inputs changed during build')
        receipt['files'] = file_inventory(stage)
        dump(stage / 'sequence-receipt.json', receipt)
        result = verify_sequence(stage)
        publish(stage, out)
    return {**result, 'output': str(out), 'film': str(out / 'film/film.mp4')}


def run(args):
    if args.sequence_command == 'master':
        from .sequence_master import build
        result = build(args.directory, args.out)
    else:
        result = (verify_sequence(args.directory) if args.sequence_command == 'verify'
                  else build_sequence(args.project, args.out, args.dry_run))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def add_parser(sub):
    parser = sub.add_parser('sequence', help='Carry one authored stage through multiple local actions')
    commands = parser.add_subparsers(dest='sequence_command', required=True)
    build = commands.add_parser('build', help='Plan or render a new zero-call scene sequence')
    build.add_argument('project', type=Path)
    build.add_argument('--out', required=True, type=Path)
    build.add_argument('--dry-run', action='store_true')
    build.set_defaults(func=run)
    verify = commands.add_parser('verify', help='Recompile the portable project and verify every output frame')
    verify.add_argument('directory', type=Path)
    verify.set_defaults(func=run)
    master = commands.add_parser('master', help='Lossless RGBA film from verified original sequence PNGs')
    master.add_argument('directory', type=Path)
    master.add_argument('--out', required=True, type=Path)
    master.set_defaults(func=run)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='entry', required=True)
    # Keep the standalone module concise: python -m gif_cinema.sequence build ...
    add_parser(sub)
    args = parser.parse_args(['sequence', *(argv if argv is not None else __import__('sys').argv[1:])])
    try:
        run(args)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Sequence error: {exc}\n')
    except (RuntimeError, subprocess.SubprocessError):
        parser.exit(2, 'Sequence error: local encoder/verification failed; no completed output was published.\n')


if __name__ == '__main__':
    main()
