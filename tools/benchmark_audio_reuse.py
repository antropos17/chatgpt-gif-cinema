#!/usr/bin/env python3
"""Compare complete audio-only revisions with identical verified visual reuse.

Both variants use the current engine identity and reuse the same current-engine
seed. Only the old eager Renderer constructor/sound path is reinstated for the
baseline. This avoids comparing invalidated old-engine scenes to valid reuse.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from unittest.mock import patch
from gif_cinema import shot_renderer, shots
from gif_cinema.shot_project import load_project

REFERENCE_BLOB = 'a75f461f42fec801510fcefa601f620c035ddb3b'


def reference(path):
    raw = shots.regular(path, 1024*1024)
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != REFERENCE_BLOB:
        raise ValueError('Reference must be exact 8d1cc28 shot_renderer.py')
    namespace = {'__name__': 'audio_reuse_reference'}
    exec(compile(raw, str(path), 'exec'), namespace)
    return namespace['Renderer']


def signature(directory, receipt):
    import av
    digest = hashlib.sha256(); count = 0
    for scene in receipt['timeline']['scenes']:
        with av.open(str(directory/receipt['completed'][scene['id']]['file'])) as container:
            for frame in container.decode(video=0):
                row = [hashlib.sha256(frame.to_image().tobytes()).hexdigest(),
                       str(frame.pts*frame.time_base), str(frame.duration*frame.time_base)]
                digest.update(json.dumps(row).encode()+b'\n'); count += 1
    return count, digest.hexdigest()


def worker(project, prior, baseline, out, mode):
    import resource
    legacy = reference(baseline)
    value, paths = load_project(project)
    initializations = []; retained_renderers = []; writer = shot_renderer.write_reused_sound
    def eager(value, checked_paths, path):
        initializations.append(True)
        renderer = legacy(value, checked_paths)
        # The former compositor local lived until BuildContext.build returned.
        # Keep its caches through assembly/verification, not just sound synthesis.
        retained_renderers.append(renderer)
        renderer.sound(path)
    started = time.perf_counter(); cpu = time.process_time()
    # A current visual compositor would mean this is not the intended workload.
    with patch.object(shot_renderer.Renderer, '__init__', side_effect=AssertionError('visual rendering was not fully reused')), \
            patch.object(shot_renderer, 'write_reused_sound', eager if mode == 'before' else writer), \
            contextlib.redirect_stdout(io.StringIO()):
        result = shots.build_project(project, out, reuse_from=prior)
    retained_renderers.clear()
    seconds = time.perf_counter()-started; cpu = time.process_time()-cpu
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform == 'darwin' else 1024)
    expected = {'rendered': 0, 'reused': len(value['scenes']), 'resumed': 0}
    if result['scene_exports'] != expected or len(initializations) != (1 if mode == 'before' else 0):
        raise ValueError('Benchmark did not take equivalent all-scenes reuse paths')
    receipt = shots.read_json(out/'build-receipt.json'); previous = shots.read_json(prior/'build-receipt.json')
    frames, digest = signature(out, receipt)
    if signature(prior, previous) != (frames, digest): raise ValueError('Reused visuals/clock changed')
    if receipt['audio_sha256'] == previous['audio_sha256']:
        raise ValueError('Use a real audio-only edit, not an unchanged soundtrack')
    return {'seconds': seconds, 'self_cpu_seconds': cpu, 'peak_process_rss_bytes': rss,
        'scene_exports': result['scene_exports'], 'eager_renderer_initializations': len(initializations),
        'frames': frames, 'rgb_pts_holds_sha256': digest,
        'pcm_sha256': receipt['audio_sha256'], 'mp4_sha256': receipt['movie_sha256'],
        'runtime_source_sha256': {m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (shots, shot_renderer)}}


def benchmark(project, prior, baseline, out, repeats):
    reference(baseline)
    out = out.absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Output must be a new non-symlink directory')
    out.mkdir(parents=True); runs = {'before': [], 'after': []}; expected = None
    for i in range(repeats):
        for mode in (('before', 'after') if i%2 == 0 else ('after', 'before')):
            command = [sys.executable, str(Path(__file__).resolve()), str(project.absolute()),
                '--reuse-from', str(prior.absolute()), '--baseline-source', str(baseline.absolute()),
                '--out', str(out/(mode+'-'+str(i))), '--worker', mode]
            process = subprocess.run(command, capture_output=True, text=True, timeout=300)
            if process.returncode: raise RuntimeError('Benchmark worker failed: '+process.stderr[-4096:])
            row = json.loads(process.stdout); runs[mode].append(row)
            fact = tuple(row[k] for k in ('frames', 'rgb_pts_holds_sha256', 'pcm_sha256', 'mp4_sha256'))
            if expected is None: expected = fact
            if fact != expected: raise ValueError('Frames, clock, PCM or movie changed between variants')
            print(json.dumps({'mode': mode, 'run': i, **row}), flush=True)
    report = {'platform': platform.platform(), 'python': sys.version, 'baseline_blob': REFERENCE_BLOB,
        'runs': runs, 'medians': {label: {key: statistics.median(row[key] for row in values)
            for key in ('seconds', 'self_cpu_seconds', 'peak_process_rss_bytes')} for label, values in runs.items()},
        'all_actual_exports_equal': True,
        'scope': 'Complete audio-only revisions with verified all-scenes reuse, current engine identity in both variants. Initial seed build excluded. Baseline reinstates only frozen old eager renderer initialization/sound and retains its caches until build returns. No generation or identity claims.'}
    (out/'benchmark.json').write_text(json.dumps(report, indent=2)+'\n'); return report


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('project', type=Path)
    parser.add_argument('--reuse-from', required=True, type=Path); parser.add_argument('--baseline-source', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path); parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--worker', choices=('before', 'after'), help=argparse.SUPPRESS); args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.project, args.reuse_from, args.baseline_source, args.out, args.worker))); return
    if not 1 <= args.repeats <= 10: parser.error('Repeats must be 1..10')
    if sys.platform not in ('linux', 'darwin'): parser.error('RSS measurement needs Linux/macOS resource accounting')
    benchmark(args.project, args.reuse_from, args.baseline_source, args.out, args.repeats)


if __name__ == '__main__': main()
