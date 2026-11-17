#!/usr/bin/env python3
"""Measure complete native exports with/without guarded direct-child pipe IO.

This is a reliability/overhead comparison, not a rendering-speed claim. Both
variants keep the current engine identity and all output verification.
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
from gif_cinema import shots

REFERENCE_BLOB = '97dade53139c4732be9dd17588dd2edfd9c27dba'


def reference(path):
    raw = shots.regular(path, 1024*1024)
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != REFERENCE_BLOB:
        raise ValueError('Reference must be exact 658e446 shots.py')
    ns = {'__name__': 'gif_cinema.encoder_reference', '__package__': 'gif_cinema'}
    exec(compile(raw, str(path), 'exec'), ns)
    return ns['encode']


def signature(directory, receipt):
    import av
    h=hashlib.sha256(); count=0
    for scene in receipt['timeline']['scenes']:
        with av.open(str(directory/receipt['completed'][scene['id']]['file'])) as container:
            for frame in container.decode(video=0):
                row=[hashlib.sha256(frame.to_image().tobytes()).hexdigest(),str(frame.pts*frame.time_base),str(frame.duration*frame.time_base)]
                h.update(json.dumps(row).encode()+b'\n');count+=1
    return count,h.hexdigest()


def worker(project, baseline, out, mode):
    import resource
    encoder=reference(baseline) if mode=='before' else shots.encode
    t=time.perf_counter();cpu=time.process_time()
    with patch.object(shots,'encode',encoder),contextlib.redirect_stdout(io.StringIO()):
        result=shots.build_project(project,out)
    seconds=time.perf_counter()-t;cpu=time.process_time()-cpu
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
    receipt=shots.read_json(out/'build-receipt.json');frames,digest=signature(out,receipt)
    pcm=hashlib.sha256((out/receipt['ready']['audio']).read_bytes()).hexdigest()
    movie=hashlib.sha256((out/'film.mp4').read_bytes()).hexdigest()
    if pcm!=receipt['audio_sha256'] or movie!=receipt['movie_sha256']:raise ValueError('Actual audio/movie differ from verified receipt')
    if result['scene_exports']!={'rendered':len(receipt['timeline']['scenes']),'reused':0,'resumed':0}:raise ValueError('Require equivalent fresh builds')
    return dict(seconds=seconds,self_cpu_seconds=cpu,peak_process_rss_bytes=rss,frames=frames,
        rgb_pts_holds_sha256=digest,pcm_sha256=pcm,mp4_sha256=movie,
        current_shots_sha256=hashlib.sha256(Path(shots.__file__).read_bytes()).hexdigest(),
        encoder_source_sha256=hashlib.sha256((baseline if mode=='before' else Path(shots.__file__)).read_bytes()).hexdigest())


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project',type=Path)
    p.add_argument('--baseline-source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--repeats',type=int,default=3);p.add_argument('--worker',choices=('before','after'),help=argparse.SUPPRESS);a=p.parse_args()
    if a.worker:print(json.dumps(worker(a.project,a.baseline_source,a.out,a.worker)));return
    if not 1<=a.repeats<=10:p.error('Repeats must be 1..10')
    if sys.platform not in ('linux','darwin'):p.error('RSS accounting needs Linux/macOS')
    reference(a.baseline_source);out=a.out.absolute()
    if out.exists() or any(x.is_symlink() for x in (out,*out.parents)):p.error('Output must be a new non-symlink directory')
    out.mkdir(parents=True);runs={'before':[],'after':[]};expected=None
    for n in range(a.repeats):
        for mode in (('before','after') if n%2==0 else ('after','before')):
            command=[sys.executable,str(Path(__file__).resolve()),str(a.project.absolute()),'--baseline-source',str(a.baseline_source.absolute()),'--out',str(out/f'{mode}-{n}'),'--worker',mode]
            proc=subprocess.run(command,capture_output=True,text=True,timeout=600)
            if proc.returncode:raise RuntimeError(proc.stderr[-4096:])
            row=json.loads(proc.stdout);runs[mode].append(row)
            fact=tuple(row[k] for k in ('frames','rgb_pts_holds_sha256','pcm_sha256','mp4_sha256'))
            if expected is None:expected=fact
            if fact!=expected:raise ValueError('Actual RGB/clock/audio/movie mismatch')
            print(json.dumps(dict(mode=mode,run=n,**row)),flush=True)
    report=dict(platform=platform.platform(),python=sys.version,baseline_blob=REFERENCE_BLOB,runs=runs,
        medians={label:{k:statistics.median(row[k] for row in values) for k in ('seconds','self_cpu_seconds','peak_process_rss_bytes')} for label,values in runs.items()},
        all_outputs_equal=True,scope='Complete fresh builds. Only encode() is replaced by the frozen baseline; current engine and verification in both variants. RSS excludes FFmpeg children. Output hashing for this comparison follows timing. Not a speedup claim.')
    (out/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
