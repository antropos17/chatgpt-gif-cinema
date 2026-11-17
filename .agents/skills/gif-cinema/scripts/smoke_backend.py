"""Offline installed-backend proof: native pose cadence and GFC1 frame/hold export."""
import argparse
from contextlib import redirect_stdout
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
from PIL import Image
from gif_cinema import cli, editor_project
import check_install


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rgba(frame):
    image = frame.reformat(format='rgba')
    plane = image.planes[0]
    raw = bytes(plane)
    return b''.join(raw[y*plane.line_size:y*plane.line_size+image.width*4] for y in range(image.height))


def sequence_cli(*arguments):
    """Exercise the installed public parser/dispatcher, including event JSON."""
    output = io.StringIO()
    with patch.object(sys, 'argv', ['gif-cinema', 'sequence', *map(str, arguments)]), redirect_stdout(output):
        cli.main()
    remaining = output.getvalue().strip()
    values = []
    decoder = json.JSONDecoder()
    while remaining:
        value, end = decoder.raw_decode(remaining)
        require(isinstance(value, dict), 'Sequence CLI emitted a non-object result')
        values.append(value)
        remaining = remaining[end:].lstrip()
    require(bool(values) and 'status' in values[-1] and all('event' in row for row in values[:-1]),
            'Sequence CLI did not emit a final result after its events')
    result = values[-1]
    # The existing already-complete resume response omits provider_calls. Its
    # verified saved receipt and byte-identical outputs are checked separately.
    completed_resume = '--resume' in arguments and result.get('already_complete') is True and result.get('status') == 'complete'
    if not (completed_resume and 'provider_calls' not in result):
        require(type(result.get('provider_calls')) is int and result['provider_calls'] == 0,
                'Sequence CLI did not report exactly zero provider calls')
    return result


def make_sources(root):
    """Original technical fixtures, deliberately not downloaded artwork."""
    Image.new('RGB', (16, 16), 'black').save(root/'back.png')
    atlas = Image.new('RGBA', (16, 8), 'red')
    atlas.paste((0, 0, 255, 255), (8, 0, 16, 8)); atlas.save(root/'actor.png')
    files = {name: {'path': name, 'sha256': digest(root/name), 'bytes': (root/name).stat().st_size}
             for name in ('back.png', 'actor.png')}
    value = dict(format='gif-cinema-shot-project', schema_version=1, title='Technical cadence proof',
        width=16, height=16, fps=30, background='back.png', files=files,
        clips={'cells': dict(source='actor.png', frames=2, columns=2, tile_size=[8,8], xy=[0,0], mask='alpha', threshold=0, blur=0)},
        actors=[{'id':'actor', 'tracks':[dict(clip='cells', start=0, end=1, origin=0, duration=.2, loop=True, first=0, last=1)]}],
        shadows=[], shadow_blur=0, occlusion_threshold=0, occlusion_blur=0, glow_blur=0,
        camera_push={'amplitude':0, 'speed':0}, effects=[], overlays=[],
        audio=dict(rate=8000, duration=1, fade_in=.1, fade_out=.1, tones=[[0,.4,440,.1,0]], noise=[]),
        scenes=[dict(id=name, start_frame=lo, end_frame=hi, camera=[0,0,16,16], effects={'gain':1})
                for name,lo,hi in [('first',0,15),('second',15,30)]])
    (root/'native.json').write_text(json.dumps(value), encoding='utf-8')
    # Hidden RGB, partial alpha, identical stored drawings, and a final 150ms hold.
    pixel = bytes([241,97,123,0,33,11,211,128,9,240,71,255,0,0,0,0])
    first = pixel * (256*256*4//len(pixel))
    frames = [first, first, bytes(reversed(first))]
    header = json.dumps({'version':1, 'width':256, 'height':256,
        'scenes':[{'name':'Duplicate translucent drawings', 'delays':[10,30]},
                  {'name':'Final hold', 'delays':[150]}]}).encode()
    (root/'working.gfc').write_bytes(b'GFC1'+len(header).to_bytes(4,'little')+header+b''.join(frames))
    return value, frames


def verify_gfc(output, expected):
    import av
    report = json.loads((output/'manifest.json').read_text())
    require(report['status']=='verified-master' and type(report['provider_calls']) is int and report['provider_calls']==0,
            'GFC exporter did not verify with zero provider calls')
    with av.open(str(output/'master.mkv')) as container:
        require(len(container.streams)==1 and container.streams.video[0].codec_context.name=='ffv1', 'GFC master codec changed')
        decoded = list(container.decode(video=0))
    require(len(decoded)==3, 'GFC stored drawing count changed')
    for index,(frame,start,hold) in enumerate(zip(decoded,(0,10,40),(10,30,150))):
        require((frame.width,frame.height)==(256,256) and rgba(frame)==expected[index], 'GFC RGBA mismatch')
        require(frame.pts*frame.time_base==Fraction(start,1000) and frame.duration*frame.time_base==Fraction(hold,1000), 'GFC PTS/hold mismatch')
    with av.open(str(output/'preview.mp4')) as container:
        decoded = list(container.decode(video=0))
    require(len(decoded)==19, 'GFC preview count changed')
    for index,frame in enumerate(decoded):
        require((frame.width,frame.height)==(256,256) and frame.pts*frame.time_base==Fraction(index,100) and
                frame.duration*frame.time_base==Fraction(1,100), 'GFC preview clock changed')
    return {'stored_frames':3, 'duration_ms':190, 'holds_ms':[10,30,150], 'preview_frames':19,
            'all_stored_rgba_matched':True}


def verify_native(output, project):
    import av
    report = json.loads((output/'build-receipt.json').read_text())
    require(report['status']=='complete' and type(report['provider_calls']) is int and report['provider_calls']==0,
            'Native exporter did not complete with zero provider calls')
    count = 0
    for scene in project['scenes']:
        path = output/report['completed'][scene['id']]['file']
        with av.open(str(path)) as container:
            frames = list(container.decode(video=0))
        require(len(frames)==scene['end_frame']-scene['start_frame'], 'Native scene count changed')
        for local,frame in enumerate(frames):
            index=scene['start_frame']+local
            # Independent, explicit six-sample cadence; includes the old faulty frame18.
            color='red' if index%6<=3 else 'blue'
            expected=Image.new('RGB',(16,16),'black');expected.paste(Image.new('RGB',(8,8),color),(0,0))
            require(frame.to_image().convert('RGB').tobytes()==expected.tobytes(), f'Native pose changed at {index}')
            # Matroska's 1ms clock rounds CFR timestamps; never claim exact 1/30 holds.
            tick=frame.time_base; at=Fraction(local,30)/tick
            pts=(2*at.numerator+at.denominator)//(2*at.denominator)
            require(frame.pts==pts and tick==Fraction(1,1000) and frame.duration in (33,34), 'Native scene clock changed')
            count+=1
    with av.open(str(output/'film.mp4')) as container:
        frames=list(container.decode(video=0))
    require(len(frames)==30, 'Native viewing frame count changed')
    for index,frame in enumerate(frames):
        require(frame.pts*frame.time_base==Fraction(index,30) and frame.duration*frame.time_base==Fraction(1,30), 'Native viewing clock changed')
    require(sequence_cli('verify', output)['status']=='verified', 'Portable native verification failed')
    return {'frames':count, 'fps':30, 'pose_period_ms':200, 'all_lossless_rgb_matched':True,
            'scene_clock':'nearest millisecond; holds 33 or 34ms', 'viewing_clock':'30fps'}


def run_offline(root):
    root=Path(root).absolute()
    skill=Path(__file__).resolve().parents[1]
    require(not any(p.is_symlink() for p in (root,*root.parents)), 'Smoke output must not use symlinks')
    # Check the original components first, then normalize '..' for containment.
    root=root.resolve()
    require(not root.is_relative_to(skill) and not skill.is_relative_to(root), 'Smoke output belongs outside the installed skill')
    require(not root.exists(), 'Smoke output must be a new directory')
    require(all(shutil.which(name) for name in ('ffmpeg','ffprobe')), 'FFmpeg and ffprobe are required')
    installation={'package':check_install.verify_files(), 'runtime':check_install.check_runtime(require_master=True)}
    root.mkdir(parents=True,exist_ok=False)
    project,frames=make_sources(root)
    sources={name:digest(root/name) for name in ('back.png','actor.png','native.json','working.gfc')}
    with patch.object(sys,'argv',['gif-cinema-editor-project',str(root/'working.gfc'),'--out',str(root/'editor')]), redirect_stdout(io.StringIO()):
        editor_project.main()
    gfc=verify_gfc(root/'editor',frames)
    built=sequence_cli('build', root/'native.json', '--out', root/'native')
    require(built['status']=='complete', 'Native CLI build did not complete')
    native=verify_native(root/'native',project)
    before={str(p.relative_to(root/'native')):digest(p) for p in (root/'native').rglob('*') if p.is_file()}
    resumed=sequence_cli('build', root/'native.json', '--out', root/'native', '--resume')
    require(resumed.get('already_complete') is True, 'Completed native build was not resumed')
    require(before=={str(p.relative_to(root/'native')):digest(p) for p in (root/'native').rglob('*') if p.is_file()}, 'Resume changed native movie/audio/checkpoint files')
    require(sources=={name:digest(root/name) for name in sources}, 'Synthetic sources changed')
    require((root/'editor'/'project.gfc').read_bytes()==(root/'working.gfc').read_bytes(), 'Exported GFC differs from working source')
    require(sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) < 16*1024*1024, 'Smoke output exceeds 16MiB budget')
    report={'status':'passed','provider_calls':0,'installation':installation,'gfc':gfc,'native':native,
        'sources_unchanged':True,'resume_files_unchanged':True,'public_sequence_cli_checked':True,'network':'blocked in Python process',
        'limitations':'Technical synthetic fixture only. Not face lock, original GIF fidelity, artistic acceptance, or live website integration. GFC1 preserves its stored RGBA/holds, not pre-import source GIFs; MP4 is lossy and opaque. No new intermediate drawings are generated.'}
    with (root/'verification.json').open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(report,indent=2)+'\n')
    return report


def run(root):
    with patch('socket.socket',side_effect=AssertionError('Network prohibited')), patch('urllib.request.urlopen',side_effect=AssertionError('Network prohibited')):
        return run_offline(root)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True,type=Path)
    print(json.dumps(run(parser.parse_args().out),indent=2))


if __name__=='__main__':
    main()
