#!/usr/bin/env python3
"""Compare verified native assembly with pinned 3849555 source, fully offline.

Prepare the reference: git show 3849555:gif_cinema/shots.py > before-shots.py
Pass an existing verified native build. All attempts use new paths. Source scenes
are read-only; no checkpoint is trusted without normal independent verification.
"""
import argparse
import cProfile
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import platform
import shutil
import statistics
import sys
import time
import types
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import av
import PIL
from gif_cinema import shots

BASELINE_BLOB = '7ac7fa2fbaa832387bc8234df145e66f1b95c84e'


def baseline(path):
    raw = shots.regular(path, 256*1024)
    blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if blob != BASELINE_BLOB:
        raise ValueError('Expected exact shots.py from 3849555')
    module = types.ModuleType('gif_cinema._verified_baseline_shots')
    module.__package__ = 'gif_cinema'
    module.__file__ = shots.__file__
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def images(module, context, root, receipt):
    for scene in context.value['scenes']:
        record = receipt['completed'][scene['id']]
        key = receipt['keys'][scene['id']]
        if hasattr(context, 'verified_scene_images'):
            yield from context.verified_scene_images(root, record, key)
        else:
            # Exact previous assembly loop, including its second RGB check.
            path = context.verify_scene(root, record, key)
            for index, frame in enumerate(module.video_frames(path)):
                im = frame.to_image().convert('RGB')
                if module.sha(im.tobytes()) != record['rgb_sha256'][index]:
                    raise ValueError('Scene changed during final assembly')
                yield im


def sample(module, context, root, receipt, output=None, ffmpeg=None):
    real_decode = module.video_frames
    counts = {'scene_decoder_opens': 0, 'decoded_scene_frames': 0, 'yielded_rgb_frames': 0}
    hashes = []
    def decode(path):
        counts['scene_decoder_opens'] += 1
        for frame in real_decode(path):
            counts['decoded_scene_frames'] += 1
            yield frame
    def feed():
        for im in images(module, context, root, receipt):
            counts['yielded_rgb_frames'] += 1
            if output is None: hashes.append(shots.sha(im.tobytes()))
            yield im
    started = time.perf_counter()
    with patch.object(module, 'video_frames', decode):
        if output:
            audio = shots.local(root, receipt['ready']['audio'])
            module.encode(context.raw_command(ffmpeg) + ['-i', str(audio), '-t', str(context.frames/context.value['fps']),
                          '-c:v', 'libx264', '-crf', '16', '-preset', 'medium', '-threads', '2', '-pix_fmt', 'yuv420p',
                          '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(output)], feed())
        else:
            for _ in feed(): pass
    elapsed = time.perf_counter()-started
    return {'seconds': elapsed, **counts}, hashes


def movie_facts(path):
    frames = []
    for frame in shots.video_frames(path):
        frames.append({'rgb_sha256': shots.sha(frame.to_image().convert('RGB').tobytes()),
                       'pts': str(frame.pts*frame.time_base),
                       'duration': str(frame.duration*frame.time_base)})
    audio = []
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            audio.append({'sha256': shots.sha(b''.join(bytes(plane)[:frame.samples*frame.format.bytes*(1 if frame.format.is_planar else len(frame.layout.channels))] for plane in frame.planes)), 'samples': frame.samples,
                          'pts': str(frame.pts*frame.time_base), 'sample_rate': frame.sample_rate})
    return {'frames': frames, 'audio': audio, 'movie_sha256': shots.sha(shots.regular(path))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('built_project')
    parser.add_argument('--baseline-source', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--full-build', action='store_true', help='Also render two fresh complete projects, one trial each')
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10: parser.error('--repeats must be 1..10')
    root, out = Path(args.built_project).resolve(), Path(args.out).resolve()
    if out.exists(): parser.error('--out must be a new directory')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg: parser.error('FFmpeg required')
    before = baseline(args.baseline_source)
    contexts = {name: module.BuildContext(root/'project.json') for name, module in [('before', before), ('after', shots)]}
    receipt = contexts['after'].completed(root)
    expected = [h for scene in contexts['after'].value['scenes'] for h in receipt['completed'][scene['id']]['rgb_sha256']]
    source_hashes = {record['file']: shots.sha(shots.regular(shots.local(root, record['file']))) for record in receipt['completed'].values()}
    source_hashes[receipt['ready']['audio']] = shots.sha(shots.regular(shots.local(root, receipt['ready']['audio'])))
    out.mkdir(parents=True)
    report = {'baseline_commit': '3849555b04c8040ee18f5a856f8bcb43d3986889', 'baseline_shots_blob': BASELINE_BLOB,
              'after_shots_sha256': shots.sha(shots.regular(Path(shots.__file__))),
              'python': platform.python_version(), 'pillow': PIL.__version__, 'av': av.__version__, 'platform': platform.platform(),
              'project_sha256': shots.sha(shots.regular(root/'project.json')), 'source_hashes': source_hashes,
              'frames': len(expected), 'rgb_sha256': expected, 'provider_calls': 0,
              'stream_runs': {'before': [], 'after': []}, 'assembly_runs': {'before': [], 'after': []}}
    reference_movie = None
    for run in range(args.repeats):
        for name, module in ([('before', before), ('after', shots)] if run%2 == 0 else [('after', shots), ('before', before)]):
            timing, actual = sample(module, contexts[name], root, receipt)
            if actual != expected: raise AssertionError('RGB changed')
            report['stream_runs'][name].append(timing)
            output = out/f'{name}-{run+1}.mp4'
            timing, _ = sample(module, contexts[name], root, receipt, output, ffmpeg)
            contexts[name].verify_movie(output)  # independent, not timed
            facts = movie_facts(output)
            if reference_movie is None: reference_movie = facts
            if facts != reference_movie: raise AssertionError('Movie bytes, RGB, PTS, durations or decoded AAC changed')
            report['assembly_runs'][name].append(timing)
            print(json.dumps({'run': run+1, 'variant': name, **timing}), flush=True)
    report['movie_facts'] = reference_movie
    report['median_seconds'] = {kind: {name: statistics.median(r['seconds'] for r in rows) for name, rows in report[kind].items()}
                                for kind in ('stream_runs', 'assembly_runs')}
    for name, module in [('before', before), ('after', shots)]:
        profiler = cProfile.Profile()
        profiler.runcall(sample, module, contexts[name], root, receipt)
        profiler.dump_stats(str(out/f'{name}.prof'))
    if args.full_build:
        full = {}
        for name, module in [('before', before), ('after', shots)]:
            dest = out/f'full-{name}'
            start = time.perf_counter()
            module.build_project(root/'project.json', dest)
            elapsed = time.perf_counter()-start
            shots.verify_project(dest)
            rec = shots.read_json(dest/'build-receipt.json')
            actual = [h for scene in contexts[name].value['scenes'] for h in rec['completed'][scene['id']]['rgb_sha256']]
            if actual != expected: raise AssertionError('Full render RGB changed')
            facts = movie_facts(dest/'film.mp4')
            if facts != reference_movie: raise AssertionError('Full movie differs')
            if rec['audio_sha256'] != receipt['audio_sha256']: raise AssertionError('PCM changed')
            full[name] = {'seconds': elapsed, 'movie_sha256': facts['movie_sha256'], 'audio_sha256': rec['audio_sha256'], 'verified': True}
            print(json.dumps({'full_build': name, **full[name]}), flush=True)
        report['full_build_single_trial'] = full
        report['full_build_scope'] = 'Pinned previous or current shots module; same optimized renderer/assets. Source identity reports current installed code for both injected implementations.'
    for path, digest in source_hashes.items():
        if shots.sha(shots.regular(shots.local(root, path))) != digest: raise AssertionError('Source changed')
    report['mismatches'] = dict(rgb=0, pts=0, duration=0, decoded_aac=0, pcm=0, movie_bytes=0)
    (out/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'report': str(out/'report.json'), 'median_seconds': report['median_seconds']}), flush=True)


if __name__ == '__main__': main()
