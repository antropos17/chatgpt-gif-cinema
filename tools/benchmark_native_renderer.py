#!/usr/bin/env python3
"""Compare this renderer with a pinned prior source, without network/providers.

Get the reference with `git show eee37ae:gif_cinema/shot_renderer.py > BEFORE.py`.
Only a selected known Git blob is executable as a reference.
For the empty-light fast path use --baseline-commit e4d9e7d and that revision's source. No performance threshold is
asserted: timings depend on hardware. Every sampled RGB hash must match instead.
"""
import argparse
import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time
import types
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import __version__ as pillow_version
from gif_cinema import shot_renderer, shots
from gif_cinema.shot_project import load_project

BASELINES = {
    'eee37ae': ('eee37ae37e70f59dd87a768306a3dca292a392c4', '71c23ab97d53233820ee340fa6e786c7a2c65e8d'),
    'e4d9e7d': ('e4d9e7daf63f63f975bec694b69d6ab37af51ac1', '5e059c94fd2b16a462110a5530515292a2c9b90d'),
}


def reference_renderer(path, baseline="eee37ae"):
    raw = shots.regular(path, 256*1024)
    blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if blob != BASELINES[baseline][1]:
        raise ValueError('Reference must be the exact shot_renderer.py from '+baseline)
    module = types.ModuleType('verified_baseline_renderer')
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module.Renderer


def sample(renderer_type, project, paths):
    started = time.perf_counter()
    renderer = renderer_type(copy.deepcopy(project), paths)
    initialized = time.perf_counter()
    hashes = []
    for scene in project['scenes']:
        for frame in range(scene['start_frame'], scene['end_frame']):
            hashes.append(hashlib.sha256(renderer.frame(frame/project['fps'], scene).tobytes()).hexdigest())
    ended = time.perf_counter()
    return {'init_seconds': initialized-started, 'render_and_hash_seconds': ended-initialized,
            'total_seconds': ended-started}, hashes


def check_export_clock(directory, project, receipt):
    """Decode actual lossless scenes and viewing video; include the final hold."""
    period = Fraction(1, project['fps'])
    scene_frames = 0
    for scene in project['scenes']:
        record = receipt['completed'][scene['id']]
        count = 0
        for count, frame in enumerate(shots.video_frames(directory/record['file']), 1):
            if frame.pts*frame.time_base != (count-1)*period or frame.duration*frame.time_base != period:
                raise AssertionError('Lossless scene timestamp/hold differs')
        if count != scene['end_frame']-scene['start_frame']:
            raise AssertionError('Lossless scene frame count differs')
        scene_frames += count
    count = 0
    for count, frame in enumerate(shots.video_frames(directory/'film.mp4'), 1):
        if frame.pts*frame.time_base != (count-1)*period or frame.duration*frame.time_base != period:
            raise AssertionError('Viewing movie timestamp/hold differs')
    if count != scene_frames:
        raise AssertionError('Viewing movie frame count differs')
    return {'scene_frames': scene_frames, 'movie_frames': count,
            'pts_mismatches': 0, 'hold_mismatches': 0,
            'duration_ms': float(scene_frames*period*1000)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project')
    parser.add_argument('--baseline-source', required=True)
    parser.add_argument('--baseline-commit', choices=BASELINES, default='eee37ae', help='Pinned source identity; default retains the original static-cache comparison')
    parser.add_argument('--out', required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--build', action='store_true', help='Also compare two full verified FFmpeg builds, one trial each')
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error('--repeats must be 1..10')
    out = Path(args.out).resolve()
    if out.exists():
        parser.error('--out must be a new file')
    before = reference_renderer(args.baseline_source, args.baseline_commit)
    after = shot_renderer.Renderer
    project, paths = load_project(args.project)
    report = {'baseline_commit': BASELINES[args.baseline_commit][0],
              'baseline_renderer_git_blob': BASELINES[args.baseline_commit][1],
              'optimized_renderer_sha256': hashlib.sha256(Path(shot_renderer.__file__).read_bytes()).hexdigest(),
              'python': platform.python_version(), 'platform': platform.platform(), 'pillow': pillow_version,
              'project_sha256': hashlib.sha256(Path(args.project).read_bytes()).hexdigest(),
              'geometry': [project['width'], project['height']], 'fps': project['fps'],
              'runs': {'before': [], 'after': []}, 'provider_calls': 0}
    expected = None
    for run in range(args.repeats):
        for name, implementation in ([('before', before), ('after', after)] if run % 2 == 0
                                      else [('after', after), ('before', before)]):
            timing, hashes = sample(implementation, project, paths)
            if expected is None:
                expected = hashes
            if hashes != expected:
                raise AssertionError('RGB hashes differ; do not claim equivalent optimization')
            report['runs'][name].append(timing)
            print(json.dumps({'run': run+1, 'variant': name, **timing}), flush=True)
    report['frames'] = len(expected)
    report['rgb_sha256'] = expected
    report['rgb_mismatches'] = 0
    report['median_seconds'] = {name: {key: statistics.median(row[key] for row in runs)
        for key in runs[0]} for name, runs in report['runs'].items()}
    if args.build:
        builds = {}
        for name, implementation in [('before', before), ('after', after)]:
            directory = out.parent/(out.stem+'-'+name+'-build')
            if directory.exists():
                raise ValueError('Build outputs must be new directories')
            start = time.perf_counter()
            with patch.object(shot_renderer, 'Renderer', implementation):
                shots.build_project(args.project, directory)
            duration = time.perf_counter()-start
            shots.verify_project(directory)
            rec = shots.read_json(directory/'build-receipt.json')
            actual = [digest for scene in project['scenes']
                      for digest in rec['completed'][scene['id']]['rgb_sha256']]
            if actual != expected:
                raise AssertionError('Full export RGB hashes differ')
            builds[name] = {'build_seconds': duration, 'movie_sha256': rec['movie_sha256'],
                            'audio_sha256': rec['audio_sha256'], 'verified': True,
                            'decoded_clock': check_export_clock(directory, project, rec)}
            print(json.dumps({'full_build': name, **builds[name]}), flush=True)
        if builds['before']['audio_sha256'] != builds['after']['audio_sha256']:
            raise AssertionError('PCM audio changed')
        report['full_builds_single_trial'] = builds
        report['build_scope'] = 'Same current build pipeline, baseline or optimized Renderer injected; both verified. Engine receipt identity is current code in both trials.'
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, allow_nan=False); handle.write('\n')
    print(json.dumps({'report': str(out), 'frames': len(expected), 'rgb_mismatches': 0}), flush=True)


if __name__ == '__main__':
    main()
