#!/usr/bin/env python3
"""Compare exact native light filtering to the frozen 4b193d7 renderer.

Run from a selected checkout with PYTHONPATH=. or from its installed environment.
Rendering medians exclude initialization; optional full exports are one pair only.
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
import sys
import time
from unittest.mock import patch
from PIL import Image, ImageFilter
import PIL
from gif_cinema import shot_renderer, shots
from gif_cinema.shot_project import load_project

REFERENCE_BLOB = '57c3f7ae1a8fc9c93db99401b4853946e6d84bec'


def reference(path):
    raw = shots.regular(path, 1024*1024)
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != REFERENCE_BLOB:
        raise ValueError('Reference must be exact 4b193d7 shot_renderer.py')
    namespace={'__name__':'bounded_blur_reference'}
    exec(compile(raw,str(path),'exec'),namespace)
    return namespace['Renderer']


def loop(cls,value,paths):
    renderer=cls(value,paths)
    hashes=[];start=time.perf_counter()
    for scene in value['scenes']:
        for i in range(scene['start_frame'],scene['end_frame']):
            hashes.append(hashlib.sha256(renderer.frame(i/value['fps'],scene).tobytes()).hexdigest())
    return time.perf_counter()-start,hashes


def filter_work(cls,value,paths):
    renderer=cls(value,paths);work={};original=Image.Image.filter
    def counted(image,operation):
        if isinstance(operation,ImageFilter.GaussianBlur):
            key=image.mode;row=work.setdefault(key,{'calls':0,'pixel_filters':0})
            row['calls']+=1;row['pixel_filters']+=image.width*image.height
        return original(image,operation)
    with patch.object(Image.Image,'filter',counted):
        for scene in value['scenes']:
            for i in range(scene['start_frame'],scene['end_frame']): renderer.frame(i/value['fps'],scene)
    return work


def decoded(directory,receipt):
    import av
    samples=[]
    for scene in receipt['timeline']['scenes']:
        with av.open(str(directory/receipt['completed'][scene['id']]['file'])) as c:
            for frame in c.decode(video=0):
                samples.append((hashlib.sha256(frame.to_image().tobytes()).hexdigest(),
                                str(frame.pts*frame.time_base),str(frame.duration*frame.time_base)))
    return samples


def benchmark(project,baseline,out,repeats,export):
    old=reference(baseline);new=shot_renderer.Renderer
    value,paths=load_project(project);original=copy.deepcopy(value)
    out=out.absolute()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)):
        raise ValueError('Output must be a new non-symlink directory')
    out.mkdir(parents=True)
    runs={'before':[],'after':[]};expected=None
    for i in range(repeats):
        for label,cls in ((('before',old),('after',new)) if i%2==0 else (('after',new),('before',old))):
            seconds,hashes=loop(cls,value,paths);runs[label].append(seconds)
            if expected is None:expected=hashes
            if hashes!=expected: raise ValueError('Rendered RGB changed')
            print(json.dumps({'variant':label,'seconds':seconds,'frames':len(hashes)}),flush=True)
    assert value==original
    source=Path(shot_renderer.__file__)
    report={'pillow':PIL.__version__,'platform':platform.platform(),'python':sys.version,
        'runtime_source':str(source.resolve()),'runtime_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'baseline_blob':REFERENCE_BLOB,'runs':runs,'median_render_hash_seconds':{k:statistics.median(v) for k,v in runs.items()},
        'frames':len(expected),'rgb_sha256':expected,'rgb_mismatches':0,
        'gaussian_filter_work':{label:filter_work(cls,value,paths) for label,cls in (('before',old),('after',new))},
        'scope':'Exact RGB/native clock preservation, not perceptual or identity acceptance. Timing depends on area/radius/version. No generation calls.'}
    if export:
        outputs=[]
        for label,cls in (('before',old),('after',new)):
            directory=out/(label+'-build');start=time.perf_counter()
            with patch.object(shot_renderer,'Renderer',cls), contextlib.redirect_stdout(io.StringIO()):
                shots.build_project(project,directory)
            seconds=time.perf_counter()-start
            receipt=shots.read_json(directory/'build-receipt.json')
            outputs.append((directory,receipt,decoded(directory,receipt)))
            report.setdefault('export_seconds_single_pair',{})[label]=seconds
        a,b=outputs
        report['export']={'decoded_frames_per_variant':len(a[2]),'rgb_pts_hold_equal':a[2]==b[2],
            'pcm_bytes_equal':(a[0]/a[1]['ready']['audio']).read_bytes()==(b[0]/b[1]['ready']['audio']).read_bytes(),
            'mp4_bytes_equal':(a[0]/'film.mp4').read_bytes()==(b[0]/'film.mp4').read_bytes(),
            'pcm_sha256':b[1]['audio_sha256'],'mp4_sha256':b[1]['movie_sha256']}
        if not all(report['export'][key] for key in ('rgb_pts_hold_equal','pcm_bytes_equal','mp4_bytes_equal')):
            raise ValueError('Encoded output changed')
    (out/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project',type=Path)
    p.add_argument('--baseline-source',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--repeats',type=int,default=3);p.add_argument('--export',action='store_true')
    a=p.parse_args()
    if not 1<=a.repeats<=10:p.error('Repeats must be 1..10')
    benchmark(a.project,a.baseline_source,a.out,a.repeats,a.export)


if __name__=='__main__':main()
