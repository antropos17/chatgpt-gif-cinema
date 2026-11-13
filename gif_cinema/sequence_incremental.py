"""Immutable sequence revisions with bounded, durable scene checkpoints."""
import argparse
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import uuid

from . import sequence as seq, layers, factory, cli, render, durability


def digest(value):
    return layers.digest(factory.json_bytes(value))


def engine():
    from PIL import __version__
    return digest({'python_sources': {p.name: layers.digest(p.read_bytes())
                   for p in sorted(Path(__file__).parent.glob('*.py'))}, 'pillow': __version__})


def scene_key(prepared):
    scene = copy.deepcopy(prepared['scene'])
    for layer in scene['layers']:
        if layer['type'] in ('image', 'sprites', 'gif'):
            sha = prepared['assets'][layer['source']]['sha256']
            layer.update(source=f'assets/{sha}.image', sha256=sha)
    return digest({'scene': canonical_numbers(scene), 'engine': engine()})


def canonical_numbers(value):
    # Normalized scene coordinates can spell the same value as 0 or 0.0.
    # Keep exact numeric equality, without rounding away a genuine pose change.
    if type(value) in (int, float):
        return 0.0 if value == 0 else float(value)
    if isinstance(value, dict):
        return {k: canonical_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical_numbers(v) for v in value]
    return value


def identity(compiled):
    r = compiled['report']
    return {k: r[k] for k in ('project_sha256', 'stage_sha256', 'asset_sha256')}


def review_plan(current, previous=None):
    old = {} if previous is None else {r['id']: (p, r, shot) for p, r, shot in
        zip(previous['compiled'], previous['report']['timeline'], previous['project']['shots'])}
    scenes = []
    for prepared, row, shot in zip(current['compiled'], current['report']['timeline'], current['project']['shots']):
        prior = old.get(row['id'])
        same = prior is not None and scene_key(prior[0]) == scene_key(prepared)
        timing = prior is not None and prior[1]['start_ms'] != row['start_ms']
        reason = ('new' if prior is None else 'unchanged' if same else
                  'authored-change' if shot != prior[2] else 'carried-state-or-stage-change')
        scenes.append({'id': row['id'], 'key': scene_key(prepared),
                       'encoding': 'reuse' if same else 'render', 'reason': reason,
                       'timing_changed': timing, 'review_required': not same or timing})
    changed = {r['id'] for r in scenes if r['review_required']}
    old_pairs = [] if previous is None else list(zip(
        [r['id'] for r in previous['report']['timeline']],
        [r['id'] for r in previous['report']['timeline']][1:]))
    ids = [r['id'] for r in scenes]
    pairs = list(zip(ids, ids[1:]))
    joins = [{'previous': a, 'next': b, 'reason': 'new-join' if (a, b) not in old_pairs else 'affected-neighbor',
              'review_required': True} for a, b in pairs if (a, b) not in old_pairs or a in changed or b in changed]
    return {'scenes': scenes, 'joins_for_review': joins,
            'removed_scenes': sorted(set(old) - set(ids)),
            'removed_joins': [{'previous': a, 'next': b} for a, b in old_pairs if (a, b) not in pairs],
            'visual_acceptance': 'not-established', 'provider_calls': 0}


def read_state(work):
    state = factory.parse_json(layers.read_regular(work / 'checkpoint.json', seq.MAX_RECEIPT_BYTES))
    if state.get('format') != 'gif-cinema-sequence-checkpoint' or state.get('schema_version') != 1:
        raise ValueError('Invalid sequence checkpoint; preserve the workspace')
    if not isinstance(state.get('completed'), dict):
        raise ValueError('Invalid completed-scene checkpoint')
    return state


def save_state(work, state):
    raw = factory.json_bytes(state)
    if len(raw) > seq.MAX_RECEIPT_BYTES:
        raise ValueError('Checkpoint exceeds byte budget')
    durability.durable_write(work / 'checkpoint.json', raw)


def cached_scene(work, entry, key):
    if not isinstance(entry, dict) or entry.get('key') != key:
        raise ValueError('Checkpoint scene identity changed; preserve workspace')
    name = entry.get('directory', '')
    if not isinstance(name, str) or len(name) != 32 or any(c not in '0123456789abcdef' for c in name):
        raise ValueError('Unsafe checkpoint directory')
    path = work / 'cache' / name
    if seq.file_inventory(path) != entry.get('files') or not (path / 'receipt.json').is_file():
        raise ValueError('Checkpoint scene files changed; preserve workspace')
    return path


def build(path, out, *, dry_run=False, resume=False, reuse_from=None):
    out = Path(out).absolute()
    work = out.with_name(out.name + '.sequence-work')
    for target in (out, work):
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('Sequence output/workspace must not use symlinks')
    compiled = seq.compile_sequence(path)
    old = None
    if reuse_from is not None:
        reuse_from = Path(reuse_from).absolute()
        if reuse_from == out:
            raise ValueError('Use a new output version; previous results are immutable')
        # Full existing verifier checks decoded frames, inventory and film before reuse.
        if not dry_run:
            seq.verify_sequence(reuse_from)
        old = seq.compile_sequence(reuse_from / 'sequence.json')
    plan = review_plan(compiled, old)
    if dry_run:
        return {**compiled['report'], 'incremental': plan, 'workspace': str(work),
                'reuse_validation': 'pending execution verification' if reuse_from is not None else 'not-requested'}
    if out.exists() and (out / 'sequence-receipt.json').exists():
        if not resume or not work.is_dir():
            raise ValueError('Output must be new; --resume requires its original checkpoint')
        state = read_state(work)
        if state.get('input') != identity(compiled) or state.get('engine') != engine() or state.get('output') != str(out):
            raise ValueError('Resume input or engine changed; choose a new output version')
        result = seq.verify_sequence(out)
        return {**result, 'output': str(out), 'film': str(out / 'film/film.mp4'), 'incremental': state['review']}
    if out.exists() and (not resume or not work.is_dir()):
        raise ValueError('Partial output needs its original workspace and --resume')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('FFmpeg and ffprobe are required')
    out.parent.mkdir(parents=True, exist_ok=True)
    with cli.output_lock(out):
        if work.exists():
            if not resume:
                raise ValueError('Workspace exists; use --resume with unchanged inputs')
            state = read_state(work)
            if state.get('input') != identity(compiled) or state.get('engine') != engine() or state.get('output') != str(out):
                raise ValueError('Resume input or engine changed; choose a new output version')
            plan = state['review']
        else:
            work.mkdir(); (work / 'cache').mkdir()
            state = {'format': 'gif-cinema-sequence-checkpoint', 'schema_version': 1,
                     'input': identity(compiled), 'engine': engine(), 'output': str(out),
                     'review': plan, 'completed': {}}
            save_state(work, state)
        seq.file_inventory(work)  # Refuse an oversized retained workspace before another render.
        if state.get('ready') is not None:
            name = state['ready']
            if not isinstance(name, str) or not name.startswith('ready-') or len(name) != 38 or any(c not in '0123456789abcdef' for c in name[6:]):
                raise ValueError('Invalid ready-publication checkpoint')
            ready = work / name
            result = seq.verify_sequence(ready)
            publish_revision(ready, out)
            return {**result, 'output': str(out), 'film': str(out / 'film/film.mp4'),
                    'incremental': plan, 'scene_exports': {'rendered': 0, 'reused': 0, 'resumed': len(state['completed'])},
                    'workspace': str(work)}
        # Fresh staging each time; completed immutable scene exports survive outside it.
        with tempfile.TemporaryDirectory(prefix='.sequence-revision-', dir=out.parent) as temp:
            stage = Path(temp) / 'result'; stage.mkdir()
            (stage / 'shots').mkdir(); (stage / 'joins').mkdir()
            layers.save_bundle(compiled['seed'], stage / 'stage')
            seq.dump(stage / 'sequence.json', {**compiled['project'], 'stage': 'stage/scene.json'})
            snapshot = seq.compile_sequence(stage / 'sequence.json')
            receipt = {**snapshot['report'], 'status': 'human-review-required',
                       'original_project_sha256': compiled['report']['project_sha256'],
                       'original_stage_sha256': compiled['report']['stage_sha256'], 'joins': []}
            counts = {'rendered': 0, 'reused': 0, 'resumed': 0}
            for index, (prepared, row, decision) in enumerate(zip(snapshot['compiled'], receipt['timeline'], plan['scenes'])):
                sid, key = row['id'], scene_key(prepared)
                if key != decision['key']:
                    raise ValueError('Portable snapshot changed scene identity')
                if sid in state['completed']:
                    candidate = cached_scene(work, state['completed'][sid], key)
                    counts['resumed'] += 1
                else:
                    name = uuid.uuid4().hex; candidate = work / 'cache' / name
                    if decision['encoding'] == 'reuse':
                        if reuse_from is None:
                            raise ValueError('Supply the original --reuse-from to finish this revision')
                        shutil.copytree(reuse_from / 'shots' / sid, candidate)
                        counts['reused'] += 1
                    else:
                        with tempfile.TemporaryDirectory(prefix='.scene-input-', dir=work) as source_dir:
                            source = layers.save_bundle(prepared, Path(source_dir) / 'input')
                            layers.render_scene(source, candidate)
                        counts['rendered'] += 1
                    files = seq.file_inventory(candidate)
                    if not (candidate / 'receipt.json').is_file():
                        raise ValueError('Scene export did not complete')
                    seq.file_inventory(work)  # Bound retained checkpoints including interrupted orphans.
                    state['completed'][sid] = {'key': key, 'directory': name, 'files': files}
                    save_state(work, state)
                shutil.copytree(candidate, stage / 'shots' / sid)
                if index:
                    receipt['joins'].append({'previous': receipt['timeline'][index - 1]['id'], 'next': sid,
                        **seq.render_join(snapshot['compiled'][index - 1], prepared, stage / 'joins' / f'{index:02}.png')})
                seq.file_inventory(stage)
            seq.dump(stage / 'film.json', seq.film_script(snapshot))
            args = argparse.Namespace(script=str(stage / 'film.json'), out=str(stage / 'film'), execute=True,
                max_api_calls=0, retries=0, force=False, force_shot=[], width=None, height=None, fps=None)
            with contextlib.redirect_stdout(io.StringIO()):
                film = render.run(args)
            if film['api_calls'] != 0:
                raise ValueError('Sequence assembly made an unexpected provider call')
            film['film'] = 'film.mp4'; seq.dump(stage / 'film/receipt.json', film)
            if identity(seq.compile_sequence(path)) != identity(compiled):
                raise ValueError('Inputs changed during build; checkpoints retained, choose a new output')
            seq.dump(stage / 'review-required.json', plan)
            receipt['files'] = seq.file_inventory(stage)
            seq.dump(stage / 'sequence-receipt.json', receipt)
            result = seq.verify_sequence(stage)
            ready = work / ('ready-' + uuid.uuid4().hex)
            shutil.copytree(stage, ready)
            seq.file_inventory(work)
            state['ready'] = ready.name
            save_state(work, state)
            publish_revision(ready, out)
        return {**result, 'output': str(out), 'film': str(out / 'film/film.mp4'),
                'incremental': plan, 'scene_exports': counts, 'workspace': str(work)}


def publish_revision(stage, out):
    """Resume interrupted publication by accepting only byte-identical existing files."""
    expected = seq.file_inventory(stage)
    if out.exists():
        existing = seq.file_inventory(out)
        if any(expected.get(name) != record for name, record in existing.items()):
            raise ValueError('Partial publication changed; preserve it and choose a new output')
    else:
        out.mkdir()
    for folder in sorted((p for p in stage.rglob('*') if p.is_dir()), key=lambda p: len(p.parts)):
        (out / folder.relative_to(stage)).mkdir(exist_ok=True)
    for source in sorted((p for p in stage.rglob('*') if p.is_file()),
                         key=lambda p: (p.name == 'sequence-receipt.json', p.as_posix())):
        target = out / source.relative_to(stage)
        if target.exists():
            if target.is_symlink() or layers.read_regular(target, seq.MAX_FILE_BYTES) != source.read_bytes():
                raise ValueError('Partial publication changed; no existing file was replaced')
        else:
            # publish_file uses a hard link: link a disposable COPY so later user
            # edits to the delivered file cannot mutate the retained ready snapshot.
            with tempfile.TemporaryDirectory(prefix='.sequence-publish-', dir=out.parent) as temp:
                staged = Path(temp) / 'file'
                shutil.copyfile(source, staged)
                cli.publish_file(staged, target)
