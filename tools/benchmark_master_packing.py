#!/usr/bin/env python3
"""Fresh-process exact master preparation benchmarks; no generation providers."""
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
from PIL import Image
from gif_cinema import master, shots

REFERENCE_BLOB = 'afa8ba20bd138307f586dbdc535eb447d1f5d83a'


def reference(path):
    raw=shots.regular(path,1024*1024)
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=REFERENCE_BLOB:
        raise ValueError('Reference must be exact e4853eb master.py')
    ns={'__name__':'gif_cinema.master_reference','__package__':'gif_cinema'}
    exec(compile(raw,str(path),'exec'),ns);return ns


def signature(path):
    av=master.require_av();digest=hashlib.sha256();count=0
    with av.open(str(path)) as media:
        for frame in media.decode(video=0):
            rgba=master.rgba_frame(frame)
            row=[rgba.size,hashlib.sha256(rgba.tobytes()).hexdigest(),str(frame.pts*frame.time_base),str(frame.duration*frame.time_base)]
            digest.update(json.dumps(row).encode()+b'\n');count+=1
    return count,digest.hexdigest()


def worker(args,mode):
    import resource
    old=reference(args.baseline_source);av=master.require_av()
    if args.packing:
        w,h,n=args.packing;raw=(bytes(range(256))*((w*h*4+255)//256))[:w*h*4]
        image=Image.frombytes('RGBA',(w,h),raw);del raw
        before=bytes(old['video_frame'](av,image).planes[0]);after=bytes(master.video_frame(av,image).planes[0])
        if before!=after:raise ValueError('Actual packed plane differs, including row padding')
        pack=old['video_frame'] if mode=='before' else master.video_frame
        start=time.perf_counter();cpu=time.process_time()
        for _ in range(n):frame=pack(av,image)
        seconds=time.perf_counter()-start;cpu=time.process_time()-cpu
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
        proof={'plane_sha256':hashlib.sha256(bytes(frame.planes[0])).hexdigest(),'size':[w,h],'frames':n}
    else:
        start=time.perf_counter();cpu=time.process_time()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            if mode=='before':
                stack.enter_context(patch.object(master,'video_frame',old['video_frame']))
                stack.enter_context(patch.object(master,'encode_master',old['encode_master']))
            report=master.build(args.clips,args.out,preview=args.preview,audio=args.audio)
        seconds=time.perf_counter()-start;cpu=time.process_time()-cpu
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
        count,digest=signature(args.out/'master.mkv')
        proof={'rgba_pts_holds_sha256':digest,'frames':count,'duration_cs':report['duration_cs'],
               'frame_manifest_sha256':hashlib.sha256(json.dumps(report['frames'],sort_keys=True).encode()).hexdigest(),
               'source_sha256':[s['sha256'] for s in report['sources']]}
        if args.preview:
            proof['preview_sha256']=master.file_sha(args.out/'preview.mp4')
            if args.audio:
                raw=master.cli.run_media(['ffmpeg','-nostdin','-v','error','-i',str(args.out/'preview.mp4'),'-vn','-f','s16le','-']).stdout
                proof['decoded_preview_pcm_sha256']=hashlib.sha256(raw).hexdigest()
    return dict(seconds=seconds,self_cpu_seconds=cpu,peak_process_rss_bytes=rss,proof=proof,
                current_master_sha256=hashlib.sha256(Path(master.__file__).read_bytes()).hexdigest(),
                executed_master_source_sha256=hashlib.sha256((args.baseline_source if mode=='before' else Path(master.__file__)).read_bytes()).hexdigest())


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('clips',nargs='*',type=Path)
    p.add_argument('--packing',nargs=3,type=int,metavar=('WIDTH','HEIGHT','FRAMES'))
    p.add_argument('--preview',action='store_true');p.add_argument('--audio',type=Path)
    p.add_argument('--baseline-source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--repeats',type=int,default=3);p.add_argument('--worker',choices=('before','after'),help=argparse.SUPPRESS);a=p.parse_args()
    if sys.platform not in ('linux','darwin'):p.error('RSS accounting needs Linux/macOS')
    if a.packing:
        w,h,n=a.packing
        if a.clips or a.preview or a.audio or not (1<=w<=4096 and 1<=h<=4096 and w*h<=4_000_000 and 1<=n<=2000):p.error('Packing needs bounded dimensions/frame count and no source/preview/audio')
    elif not 1<=len(a.clips)<=64:p.error('Choose 1..64 GIFs or --packing')
    if a.worker:print(json.dumps(worker(a,a.worker)));return
    if not 1<=a.repeats<=10:p.error('Repeats must be 1..10')
    reference(a.baseline_source);out=a.out.absolute()
    if out.exists() or any(x.is_symlink() for x in (out,*out.parents)):p.error('Output must be a new non-symlink directory')
    out.mkdir(parents=True);runs={'before':[],'after':[]};expected=None
    for n in range(a.repeats):
        for mode in (('before','after') if n%2==0 else ('after','before')):
            command=[sys.executable,str(Path(__file__).resolve()),*[str(x.absolute()) for x in a.clips],
                '--baseline-source',str(a.baseline_source.absolute()),'--out',str(out/f'{mode}-{n}'),'--worker',mode]
            if a.packing:command+=['--packing',*[str(x) for x in a.packing]]
            if a.preview:command+=['--preview']
            if a.audio:command+=['--audio',str(a.audio.absolute())]
            proc=subprocess.run(command,capture_output=True,text=True,timeout=600)
            if proc.returncode:raise RuntimeError(proc.stderr[-4096:])
            row=json.loads(proc.stdout);runs[mode].append(row)
            if expected is None:expected=row['proof']
            if expected!=row['proof']:raise ValueError('Frame/plane, timing, source or viewing output mismatch')
            print(json.dumps(dict(mode=mode,run=n,**row)),flush=True)
    report=dict(platform=platform.platform(),python=sys.version,baseline_blob=REFERENCE_BLOB,runs=runs,
        medians={m:{k:statistics.median(x[k] for x in xs) for k in ['seconds','self_cpu_seconds','peak_process_rss_bytes']} for m,xs in runs.items()},
        all_proofs_equal=True,scope='Packing-only primitive' if a.packing else 'Complete verified master builds; optional preview/audio if requested. Exact frozen encode_master+video_frame baseline; current verification in both. Matroska container bytes need not be identical. Comparison hashing follows timing. RSS excludes FFmpeg children.')
    (out/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
