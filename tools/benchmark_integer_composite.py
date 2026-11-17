#!/usr/bin/env python3
"""Pinned before/after layer-render timing with exact pixels, states and exports."""
import argparse
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
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import __version__ as pillow_version
from gif_cinema import layers

BASELINE='2ec4d091eb40392fbd35a3702604f699ac7464e9'
BLOB='c1be9b2e8ad5b14a345c60ec5f6d6bee10f0947e'


def reference(path):
    raw=layers.read_regular(Path(path),128*1024)
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=BLOB:
        raise ValueError('Reference must be exact layers.py from '+BASELINE)
    module=types.ModuleType('gif_cinema.baseline_layers');module.__package__='gif_cinema';module.__file__=str(path)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module.render_at


def verify_export_clock(directory, fps, count):
    """Decode every viewing frame after timing the build, including the last hold."""
    import av
    actual = 0
    with av.open(str(Path(directory)/'preview.mp4')) as movie:
        for actual, frame in enumerate(movie.decode(video=0), 1):
            if (frame.pts*frame.time_base != Fraction(actual-1, fps)
                    or frame.duration*frame.time_base != Fraction(1, fps)):
                raise AssertionError('MP4 timestamp or hold changed')
    if actual != count:
        raise AssertionError('MP4 frame count changed')
    return {'decoded_frames': actual, 'pts_mismatches': 0, 'hold_mismatches': 0}


def run(projects, baseline_source, out, repeats=3, export=False):
    out=Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)):
        raise ValueError('Use a new non-symlink output directory')
    if type(repeats) is not int or not 1<=repeats<=10 or not 1<=len(projects)<=8:
        raise ValueError('Require 1..10 repeats and 1..8 scene inputs')
    before=reference(baseline_source);after=layers.render_at;out.mkdir(parents=True)
    report={'baseline_commit':BASELINE,'baseline_blob':BLOB,'after_layers_sha256':hashlib.sha256(Path(layers.__file__).read_bytes()).hexdigest(),
      'python':platform.python_version(),'platform':platform.platform(),'pillow':pillow_version,'provider_calls':0,'scenes':[],
      'scope':'Existing layered scenes only. No cache, retiming, synthesized drawings, audio changes or perceptual/identity claim. Timings are machine/content-dependent; do not infer native camera-renderer speedup.'}
    for index,path in enumerate(projects):
        path=Path(path).absolute();prepared=layers.prepare_scene(path);scene=prepared['scene'];step=1000//scene['fps']
        inputs={prepared['source_path']:prepared['source_sha256'],**{path.parent/name:fact['sha256'] for name,fact in prepared['assets'].items()}}
        row={'title':scene['title'],'source_sha256':prepared['source_sha256'],'frames':scene['duration_ms']//step,
             'fps':scene['fps'],'duration_ms':scene['duration_ms'],'size':[scene['width'],scene['height']],
             'runs':{'before':[],'after':[]}};expected=None
        for repeat in range(repeats):
            for name,render in ([('before',before),('after',after)] if repeat%2==0 else [('after',after),('before',before)]):
                start=time.perf_counter();hashes=[];states=[]
                for t in range(0,scene['duration_ms'],step):
                    image,state=render(prepared,t);hashes.append(hashlib.sha256(image.tobytes()).hexdigest());states.append(state)
                elapsed=time.perf_counter()-start;row['runs'][name].append(elapsed)
                if expected is None:expected=(hashes,states)
                if (hashes,states)!=expected:raise AssertionError('RGBA or source state differs')
                print(json.dumps({'scene':index,'repeat':repeat+1,'variant':name,'seconds':elapsed}),flush=True)
        row['median_render_hash_state_seconds']={k:statistics.median(v) for k,v in row['runs'].items()}
        row.update(rgba_sha256=expected[0],rgba_mismatches=0,state_mismatches=0)
        if export and index==0:
            results={}
            for name,render in [('before',before),('after',after)]:
                dest=out/(name+'-export');start=time.perf_counter()
                with patch.object(layers,'render_at',render):receipt=layers.render_scene(path,dest)
                results[name]={'seconds':time.perf_counter()-start,'receipt':receipt}
            a,b=results['before']['receipt'],results['after']['receipt']
            for key in ('samples','sprite_timing','gif_timing','gif_delays_ms','layer_previews','loop_review'):
                if a[key]!=b[key]:raise AssertionError('Export metadata differs: '+key)
            if a['outputs']!=b['outputs']:raise AssertionError('Export artifact bytes differ')
            if [x['rgba_sha256'] for x in a['samples']]!=expected[0]:raise AssertionError('Saved export samples differ')
            decoded = {name: verify_export_clock(out/(name+'-export'), scene['fps'], row['frames'])
                       for name in ('before','after')}
            row['exports']={'decoded_clock': decoded, 'before_seconds':results['before']['seconds'],'after_seconds':results['after']['seconds'],
              'all_output_bytes_equal':True,'gif_sha256':a['outputs']['preview.gif'],'mp4_sha256':a['outputs']['preview.mp4'],
              'saved_png_frames':len(a['samples']),'gif_duration_ms':sum(a['gif_delays_ms']),'audio':'none, unchanged',
              'scope':'One full export pair, including preview collection, PNG/GIF/MP4 encoding and checks; not a repeated performance median.'}
        for file,digest in inputs.items():
            if hashlib.sha256(file.read_bytes()).hexdigest()!=digest:raise AssertionError('Input bytes changed')
        report['scenes'].append(row)
    (out/'benchmark.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('projects',nargs='+');parser.add_argument('--baseline-source',required=True)
    parser.add_argument('--out',required=True);parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--export',action='store_true')
    args=parser.parse_args();report=run(args.projects,args.baseline_source,args.out,args.repeats,args.export)
    print(json.dumps({'scenes':[{'title':r['title'],'frames':r['frames'],'median':r['median_render_hash_state_seconds'],**({'exports':r['exports']} if 'exports' in r else {})} for r in report['scenes']]},indent=2))
