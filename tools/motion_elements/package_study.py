#!/usr/bin/env python3
"""Validate rendered PNG frames and package one actual motion study. No API calls."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from PIL import Image, ImageChops, ImageStat


def run(args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=300).stdout


def inspect_gif(path):
    delays=[];hashes=[];diffs=[];previous=None;first=None
    with Image.open(path) as im:
        size=list(im.size);loop=im.info.get('loop')
        for i in range(im.n_frames):
            im.seek(i);frame=im.convert('RGB');delays.append(im.info.get('duration',0));hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
            if previous is not None:diffs.append(sum(ImageStat.Stat(ImageChops.difference(frame,previous)).mean)/3)
            if first is None:first=frame.copy()
            previous=frame.copy()
    seam=sum(ImageStat.Stat(ImageChops.difference(previous,first)).mean)/3
    return {'file':path.name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'dimensions':size,'frames':len(delays),'unique_frames':len(set(hashes)),'duration_ms':sum(delays),'frame_delays_ms':delays,'loop':loop,'seam_pixel_mae':round(seam,5),'adjacent_pixel_mae_median':round(sorted(diffs)[len(diffs)//2],5),'silent':True}


def build(source,out,dither):
    source=source.resolve();out=out.absolute()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)):raise ValueError('Output must be new and have no symlink parents')
    if dither not in ('bayer:bayer_scale=3','sierra2_4a','none'):raise ValueError('Unsupported GIF dither')
    if (source/'render.json').is_symlink():raise ValueError('Render receipt must be a regular file')
    receipt=json.loads((source/'render.json').read_text());count=receipt['frames'];width,height=receipt['dimensions']
    if receipt.get('study')!='chrome' or receipt.get('renderer')!='Blender EEVEE' or receipt.get('api_calls')!=0:raise ValueError('Expected an original chrome EEVEE render receipt')
    if type(count) is not int or not 2<=count<=250 or receipt['fps']!=25:raise ValueError('Expected 2..250 frames at exactly 25 fps')
    if any(type(v) is not int or not 128<=v<=1080 for v in (width,height)):raise ValueError('Source dimensions must be bounded to 128..1080')
    if len(list(source.glob('*.png')))!=count:raise ValueError('Frame count mismatch')
    for i in range(count):
        if (source/f'{i:04d}.png').is_symlink():raise ValueError('Source frames must be regular files')
        with Image.open(source/f'{i:04d}.png') as im:
            im.load()
            if im.size!=(width,height) or im.mode!='RGB':raise ValueError('Source dimensions or mode mismatch')
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.motion-package-',dir=out.parent) as tmp:
        stage=Path(tmp);name=receipt['study']
        common=['ffmpeg','-v','error','-nostdin','-framerate','25','-i',str(source/'%04d.png')]
        run(common+['-vf','palettegen=stats_mode=full:reserve_transparent=0','-frames:v','1',str(stage/'palette.png')])
        filter_='[0:v][1:v]paletteuse=dither='+dither+':diff_mode=rectangle'
        run(common+['-i',str(stage/'palette.png'),'-lavfi',filter_,'-frames:v',str(count),'-loop','0',str(stage/(name+'.gif'))])
        run(common+['-frames:v',str(count),'-c:v','libx264','-crf','17','-pix_fmt','yuv420p','-movflags','+faststart','-map_metadata','-1',str(stage/(name+'.mp4'))])
        info=inspect_gif(stage/(name+'.gif'))
        if info['frames']!=count or info['duration_ms']!=count*40 or info['loop']!=0 or info['unique_frames']!=count:raise ValueError('GIF verification failed')
        run(['ffmpeg','-v','error','-xerror','-nostdin','-i',str(stage/(name+'.gif')),'-f','null','-'])
        video=json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-of','json',str(stage/(name+'.mp4'))]))['streams']
        if len(video)!=1 or video[0]['codec_name']!='h264' or video[0]['avg_frame_rate']!='25/1' or int(video[0]['nb_read_frames'])!=count:raise ValueError('Video verification failed')
        shutil.copyfile(source/'0000.png',stage/'poster.png')
        phases=Image.new('RGB',(width*2,height*2))
        with Image.open(stage/(name+'.gif')) as gif:
            for slot,index in enumerate((0,count//4,count//2,count*3//4)):
                gif.seek(index);phases.paste(gif.convert('RGB'),((slot%2)*width,(slot//2)*height))
        phases.save(stage/'decoded-phases.png')
        report={'provenance':'Original procedural 3D geometry, rendered in Blender EEVEE, encoded locally; not model-generated GIF footage.','api_calls':0,'render':receipt,'gif':info,'encoding':{'dither':dither,'palette':'One global palette from every rendered source frame','opaque':True},'video':{'file':name+'.mp4','duration_ms':count*40,'dimensions':[width,height],'fps':25,'audio':False},'review':'Technical checks and visual review are not user aesthetic approval.'}
        (stage/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
        stage.rename(out)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--dither',choices=('bayer:bayer_scale=3','sierra2_4a','none'),default='bayer:bayer_scale=3')
    a=p.parse_args()
    try:r=build(a.source,a.out,a.dither)
    except (ValueError,OSError,subprocess.SubprocessError) as e:p.exit(2,f'error: {e}\n')
    print(json.dumps(r['gif']))
