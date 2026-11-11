"""Author-controlled script cuts on original decoded GIF drawings and timing."""
import argparse
import json
from pathlib import Path
import re

from . import cli, factory, master, render

FORMAT = 'gif-cinema-exact-edit'
MAX_EDITS_BYTES = 1024 * 1024


def caption(value):
    if value is None: return None
    value = value.replace('\r\n', '\n').replace('\r', '\n').strip()
    if ('-->' in value or any(not line.strip() for line in value.split('\n')) or
            re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', value)):
        raise ValueError('Caption contains an ambiguous SRT cue delimiter, blank line or control character')
    return value


def load(path):
    path = Path(path).resolve()
    script = render.load_script(path, argparse.Namespace(width=None, height=None, fps=None),
                                source_only=True, inspect_imports=False, max_import_bytes=master.MAX_INPUT_BYTES)
    for shot in script['shots']: shot['caption'] = caption(shot.get('caption'))
    return script


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result: raise ValueError('Duplicate exact-edit JSON field')
        result[name] = value
    return result


def edit_ranges(path, script):
    raw = cli.read_local_bytes(path, MAX_EDITS_BYTES, 'Exact edit')
    edits = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object)
    render.fields(edits, {'format', 'schema_version', 'script_sha256', 'shots'}, 'exact edit')
    if edits.get('format') != FORMAT or type(edits.get('schema_version')) is not int or edits['schema_version'] != 1:
        raise ValueError('Unsupported exact-edit format/version')
    if edits.get('script_sha256') != script['_script_sha256']:
        raise ValueError('Exact edit refers to a changed script; create/review a new edit template')
    shots = edits.get('shots')
    if not isinstance(shots, list) or len(shots) != len(script['shots']):
        raise ValueError('Exact edit needs one selection for every script shot, in script order')
    ranges = []
    for selection, shot in zip(shots, script['shots']):
        render.fields(selection, {'id', 'source_sha256', 'in_frame', 'out_frame'}, 'exact edit shot')
        if selection.get('id') != shot['id'] or selection.get('source_sha256') != shot['source_sha256']:
            raise ValueError('Exact edit shot order, ID or source hash differs from the script inputs')
        start, stop = selection.get('in_frame'), selection.get('out_frame')
        if type(start) is not int or type(stop) is not int or not 0 <= start < stop:
            raise ValueError('Exact edit requires integer 0 <= in_frame < out_frame')
        ranges.append((start, stop))
    return ranges, factory.digest(raw)


def write_template(script_path, output):
    output = Path(output).absolute()
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('Edit template output must be new and without symlinks')
    script = load(script_path)
    # The template is a starting point, not an export approval. Full ranges may
    # exceed the edit's duration/canvas budgets and need trimming before build.
    sources, total_bytes = [], 0
    for shot in script['shots']:
        raw = cli.read_gif_bytes(shot['source_path']); total_bytes += len(raw)
        if total_bytes > master.MAX_INPUT_BYTES: raise ValueError('Template inputs exceed the encoded byte budget')
        sha = factory.digest(raw)
        if sha != shot['source_sha256']: raise ValueError('Source GIF changed since script snapshot')
        sources.append({'sha256': sha, **master.metadata(raw)})
    template = {'format': FORMAT, 'schema_version': 1, 'script_sha256': script['_script_sha256'],
                'shots': [{'id': shot['id'], 'source_sha256': source['sha256'],
                           'in_frame': 0, 'out_frame': source['frames']}
                          for shot, source in zip(script['shots'], sources)]}
    cli.write_result(output, factory.json_bytes(template))
    return {'status': 'edit-template-written', 'provider_calls': 0,
            'file': str(output), 'sha256': master.file_sha(output),
            'notice': 'Half-open original drawing indices [in_frame, out_frame); no automatic cut approval.'}


def build(script_path, output, *, edits=None, preview=False, dry_run=False, native_canvas=False):
    script = load(script_path)
    ranges, edits_sha = edit_ranges(edits, script) if edits is not None else (None, None)
    sequence = {'script_sha256': script['_script_sha256'], 'edits_sha256': edits_sha,
                'title': script['title'], 'script_fps': script['fps'],
                'timing_policy': 'Exact selected GIF delays; script FPS is not a resampling instruction',
                'canvas_policy': 'native maximum' if native_canvas else 'script canvas; center-pad only',
                'requested_canvas': [script['width'], script['height']],
                'shots': [{'id': shot['id'], 'caption': shot['caption']} for shot in script['shots']]}
    return master.build([shot['source_path'] for shot in script['shots']], output, preview=preview,
                        audio=script.get('audio_path'), dry_run=dry_run, frame_ranges=ranges,
                        canvas=None if native_canvas else (script['width'], script['height']),
                        source_hashes=[shot['source_sha256'] for shot in script['shots']], sequence=sequence)


def timeline(report):
    clock, result = 0, []
    for shot, source in zip(report['sequence']['shots'], report['sources']):
        end = clock + source['selected_duration_cs'] * 10
        result.append({'id': shot['id'], 'source_index': source['index'], 'source_sha256': source['sha256'],
                       'in_frame': source['in_frame'], 'out_frame': source['out_frame'],
                       'frames': source['selected_frames'], 'start_ms': clock, 'end_ms': end,
                       'caption': shot['caption']})
        clock = end
    return result


def sidecars(report):
    def stamp(ms): return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}'
    cues = []
    for shot in report['sequence']['timeline']:
        if shot['caption']:
            cues.append(f"{len(cues) + 1}\n{stamp(shot['start_ms'])} --> {stamp(shot['end_ms'])}\n{shot['caption']}\n")
    return {'captions.srt': '\n'.join(cues).encode('utf-8'),
            'timeline.json': factory.json_bytes({'format': 'gif-cinema-exact-timeline', 'schema_version': 1,
                'script_sha256': report['sequence']['script_sha256'],
                'duration_ms': report['duration_cs'] * 10, 'shots': report['sequence']['timeline']})}
