#!/usr/bin/env python3
"""Isolated native PCM synthesis benchmark, not whole-film speed or sound quality.

Runs each measured case in a fresh process. RSS is the process high-water mark,
including interpreter/imports, not just Python allocations. Linux/macOS only.
The reference is exactly shot_renderer.py from local commit 4087023.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

from gif_cinema import shots
from gif_cinema.shot_project import load_project
from gif_cinema.shot_renderer import Renderer

REFERENCE_BLOB = 'f8bc9630b88d92de9fc5a7d42c41e1ed3c23ecff'


def reference(path):
    raw = shots.regular(path, 1024*1024)
    blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if blob != REFERENCE_BLOB:
        raise ValueError('Reference source is not the exact 4087023 shot_renderer.py')
    namespace = {'__name__': 'frozen_native_renderer'}
    exec(compile(raw, str(path), 'exec'), namespace)
    return namespace['Renderer']


def worker(recipe, mode, baseline, wav):
    import resource
    value = shots.read_json(recipe)
    if wav.exists() or any(p.is_symlink() for p in (wav, *wav.parents)):
        raise ValueError('Worker output must be a new non-symlink file')
    cls = reference(baseline) if mode == 'before' else Renderer
    instance = object.__new__(cls); instance.project = value
    started = time.perf_counter()
    instance.sound(wav)
    seconds = time.perf_counter()-started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != 'darwin': rss *= 1024
    # Read/hash outside the timed synthesis and after measuring RSS.
    raw = wav.read_bytes()
    return {'seconds': seconds, 'peak_process_rss_bytes': rss,
            'wav_sha256': hashlib.sha256(raw).hexdigest(), 'wav_bytes': len(raw),
            'runtime_source': str(Path(sys.modules[Renderer.__module__].__file__).resolve()),
            'runtime_source_sha256': hashlib.sha256(Path(sys.modules[Renderer.__module__].__file__).read_bytes()).hexdigest()}


def benchmark(project_path, baseline, out, repeats):
    if sys.platform not in ('linux', 'darwin'):
        raise ValueError('RSS benchmark requires Linux/macOS resource accounting')
    value, _ = load_project(project_path)
    reference(baseline)  # Refuse unexpected source before creating any output.
    out = out.absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Output must be a new non-symlink directory')
    out.mkdir(parents=True)
    recipe = {key: value[key] for key in ('fps', 'scenes', 'audio')}
    long = copy.deepcopy(recipe)
    long['fps'] = 25; long['scenes'] = [{'start_frame': 0, 'end_frame': 6500}]
    long['audio'] = {'rate': 8000, 'duration': 260, 'fade_in': .2, 'fade_out': .4,
        'tones': [[start, min(30,260-start), 220+start, .25, -.2] for start in range(0,260,30)],
        'noise': [[0,260,12345,.2]]}
    results = []
    for name, project in (('source-example',recipe), ('bounded-260-second-stress',long)):
        path = out/(name+'.json'); path.write_text(json.dumps(project, indent=2)+'\n')
        runs = {'before': [], 'after': []}
        for run in range(repeats):
            for mode in (('before','after') if run%2==0 else ('after','before')):
                # Each mode has a private output inside this newly claimed folder.
                wav = out/(name+'-'+mode+'-'+str(run)+'.wav')
                command = [sys.executable, str(Path(__file__).resolve()), '--worker', str(path),
                           '--mode', mode, '--baseline-source', str(baseline.absolute()), '--out', str(wav)]
                completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
                runs[mode].append(json.loads(completed.stdout))
        hashes = {r['wav_sha256'] for records in runs.values() for r in records}
        if len(hashes) != 1: raise ValueError('PCM WAV changed across variants or runs')
        row = {'case': name, 'sample_rate': project['audio']['rate'],
               'output_sample_frames': round(project['scenes'][-1]['end_frame']/project['fps']*project['audio']['rate'])-round(project['scenes'][0]['start_frame']/project['fps']*project['audio']['rate']),
               'wav_bytes_equal': True, 'runs': runs,
               'median_seconds': {k:statistics.median(r['seconds'] for r in v) for k,v in runs.items()},
               'median_peak_process_rss_bytes': {k:statistics.median(r['peak_process_rss_bytes'] for r in v) for k,v in runs.items()}}
        results.append(row); print(json.dumps(row), flush=True)
    report = {'platform':platform.platform(),'python':sys.version,'baseline_blob':REFERENCE_BLOB,
              'repeats':repeats,'cases':results,
              'scope':'Native sound synthesis only. Separate fresh-process RSS, not tracemalloc; no scene decode, camera render or final AAC/MP4 timing. WAV bytes, not subjective quality.'}
    (out/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('project', nargs='?', type=Path)
    p.add_argument('--baseline-source', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    p.add_argument('--mode',choices=('before','after'),help=argparse.SUPPRESS)
    args=p.parse_args()
    if args.worker:
        if args.mode is None: p.error('--worker requires --mode')
        print(json.dumps(worker(args.worker,args.mode,args.baseline_source,args.out)))
    else:
        if args.project is None or not 1<=args.repeats<=10: p.error('Need project and repeats 1..10')
        benchmark(args.project,args.baseline_source,args.out,args.repeats)


if __name__=='__main__': main()
