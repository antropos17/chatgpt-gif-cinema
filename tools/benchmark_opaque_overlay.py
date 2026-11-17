#!/usr/bin/env python3
"""Fresh-process native overlay benchmarks, with exact decoded output checks.

Use PYTHONPATH=. from the intended checkout or an isolated installed environment.
Rendering medians include RGB hashing but exclude initialization. Full exports
are optionally one pair, not a repeated end-to-end speed guarantee.
"""
import argparse
import contextlib
import copy
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
import PIL
from gif_cinema import shot_renderer, shots
from gif_cinema.shot_project import load_project

REFERENCE_BLOB = 'ada30cf77747203f4786f2939af32eef5d3d8449'


def reference(path):
    raw = shots.regular(path, 1024*1024)
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != REFERENCE_BLOB:
        raise ValueError('Reference must be exact 3ace165 shot_renderer.py')
    namespace = {'__name__': 'opaque_overlay_reference'}
    exec(compile(raw, str(path), 'exec'), namespace)
    return namespace['Renderer']


def decoded(directory, receipt):
    import av
    samples = []
    for scene in receipt['timeline']['scenes']:
        with av.open(str(directory/receipt['completed'][scene['id']]['file'])) as container:
            for frame in container.decode(video=0):
                samples.append((hashlib.sha256(frame.to_image().tobytes()).hexdigest(),
                                str(frame.pts*frame.time_base), str(frame.duration*frame.time_base)))
    return samples


def worker(project, baseline, mode, destination=None):
    import resource
    cls = reference(baseline) if mode == 'before' else shot_renderer.Renderer
    value, paths = load_project(project); original = copy.deepcopy(value)
    if destination is None:
        started = time.perf_counter(); renderer = cls(value, paths)
        init_seconds = time.perf_counter()-started
        rows = []; started = time.perf_counter()
        for scene in value['scenes']:
            for i in range(scene['start_frame'], scene['end_frame']):
                rows.append(hashlib.sha256(renderer.frame(i/value['fps'], scene).tobytes()).hexdigest())
        seconds = time.perf_counter()-started
    else:
        init_seconds = None; started = time.perf_counter()
        with patch.object(shot_renderer, 'Renderer', cls), contextlib.redirect_stdout(io.StringIO()):
            shots.build_project(project, destination)
        seconds = time.perf_counter()-started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform == 'darwin' else 1024)
    assert value == original
    source = baseline if mode == 'before' else Path(shot_renderer.__file__)
    result = {'seconds': seconds, 'initialization_seconds': init_seconds, 'peak_process_rss_bytes': rss,
              'executed_renderer_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    if destination is None:
        result.update(frames=len(rows), rgb_sha256=rows)
    else:
        receipt = shots.read_json(destination/'build-receipt.json')
        # Outside the timed/RSS interval, independently decode the actual result.
        result.update(decoded=decoded(destination, receipt), pcm_sha256=receipt['audio_sha256'],
                      mp4_sha256=receipt['movie_sha256'])
    return result


def benchmark(project, baseline, out, repeats, export):
    reference(baseline)
    out = out.absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Output must be a new non-symlink directory')
    out.mkdir(parents=True)
    def run(mode, destination=None):
        command = [sys.executable, str(Path(__file__).resolve()), str(project.absolute()),
                   '--baseline-source', str(baseline.absolute()), '--worker', mode]
        if destination is not None: command += ['--out', str(destination)]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if proc.returncode:
            raise RuntimeError('Benchmark worker failed: '+proc.stderr[-4096:])
        return json.loads(proc.stdout)
    runs = {'before': [], 'after': []}; expected = None
    for i in range(repeats):
        for mode in (('before', 'after') if i%2 == 0 else ('after', 'before')):
            row = run(mode); runs[mode].append(row)
            if expected is None: expected = row['rgb_sha256']
            if row['rgb_sha256'] != expected: raise ValueError('Rendered RGB changed')
            print(json.dumps({'variant': mode, 'run': i, **{k: v for k, v in row.items() if k != 'rgb_sha256'}}), flush=True)
    report = {'pillow': PIL.__version__, 'platform': platform.platform(), 'python': sys.version,
        'baseline_blob': REFERENCE_BLOB, 'runs': runs,
        'median_render_hash_seconds': {k: statistics.median(r['seconds'] for r in v) for k, v in runs.items()},
        'median_peak_process_rss_bytes': {k: statistics.median(r['peak_process_rss_bytes'] for r in v) for k, v in runs.items()},
        'frames': len(expected), 'rgb_mismatches': 0,
        'scope': 'Opaque native RGB compositing only. Exact RGB/clock preservation, not visual or identity acceptance. Zero provider calls.'}
    if export:
        builds = {mode: run(mode, out/(mode+'-build')) for mode in ('before', 'after')}
        a, b = builds['before'], builds['after']
        result = {'decoded_frames_per_variant': len(a['decoded']), 'rgb_pts_hold_equal': a['decoded'] == b['decoded'],
                  'pcm_bytes_equal': a['pcm_sha256'] == b['pcm_sha256'], 'mp4_bytes_equal': a['mp4_sha256'] == b['mp4_sha256'],
                  'pcm_sha256': b['pcm_sha256'], 'mp4_sha256': b['mp4_sha256']}
        if not all(result[k] for k in ('rgb_pts_hold_equal', 'pcm_bytes_equal', 'mp4_bytes_equal')):
            raise ValueError('Encoded output changed')
        report['export'] = result
        report['export_runs_single_pair'] = {k: {n: v for n, v in row.items() if n != 'decoded'} for k, row in builds.items()}
    (out/'benchmark.json').write_text(json.dumps(report, indent=2)+'\n'); return report


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('project', type=Path)
    p.add_argument('--baseline-source', required=True, type=Path); p.add_argument('--out', type=Path)
    p.add_argument('--repeats', type=int, default=3); p.add_argument('--export', action='store_true')
    p.add_argument('--worker', choices=('before', 'after'), help=argparse.SUPPRESS)
    a = p.parse_args()
    if a.worker:
        print(json.dumps(worker(a.project, a.baseline_source, a.worker, a.out))); return
    if not 1 <= a.repeats <= 10: p.error('Repeats must be 1..10')
    if a.out is None: p.error('--out is required')
    if sys.platform not in ('linux', 'darwin'): p.error('RSS benchmark needs Linux/macOS resource accounting')
    benchmark(a.project, a.baseline_source, a.out, a.repeats, a.export)


if __name__ == '__main__': main()
