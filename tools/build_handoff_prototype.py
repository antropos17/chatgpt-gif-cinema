#!/usr/bin/env python3
"""Original, offline cutout-animation proof of prop continuity, not a new renderer.

Builds three scene GIFs and preserves every 100 ms authoring frame, then asks the
existing GIF Cinema renderer to assemble them with an explicit zero-call budget.
No external artwork, JavaScript, generative service, or interpolated footage.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import PIL
from PIL import Image, ImageDraw, ImageFont
from gif_cinema.cli import validate_gif

WIDTH, HEIGHT, FPS, SCALE = 960, 540, 10, 2
DELAY_MS = 100
INK = '#23383d'
CREAM = '#f2e5cd'
TITLE = 'ONE SMALL LIGHT'
SCENES = (
    ('01-offer', 24, 'The courier offers a lantern.', 'Courier holds lantern beside their body.', 'Courier holds lantern between both characters.'),
    ('02-handoff', 24, 'The keeper takes the handle; the courier lets go.', 'Courier holds lantern between both characters.', 'Keeper alone holds the same lantern.'),
    ('03-hang', 32, 'The keeper hangs the lantern in the garden.', 'Keeper alone holds the same lantern.', 'Lantern rests on the hook; both hands are clear.'),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def mix(a, b, progress):
    return tuple(round(x + (y - x) * progress, 4) for x, y in zip(a, b))


def curve(a, b, c, steps=32):
    return [((1-t)**2*a[0]+2*(1-t)*t*b[0]+t*t*c[0],
             (1-t)**2*a[1]+2*(1-t)*t*b[1]+t*t*c[1]) for t in [i/steps for i in range(steps+1)]]


class Canvas:
    def __init__(self, image):
        self.image = image
        self.draw = ImageDraw.Draw(image)

    def box(self, xy):
        return tuple(round(v*SCALE) for v in xy)

    def line(self, points, color, width=1):
        self.draw.line([(round(x*SCALE), round(y*SCALE)) for x,y in points], fill=color, width=round(width*SCALE), joint='curve')

    def ellipse(self, box, color, outline=None, width=1):
        self.draw.ellipse(self.box(box), fill=color, outline=outline, width=round(width*SCALE))

    def rect(self, box, color, radius=0, outline=None, width=1):
        self.draw.rounded_rectangle(self.box(box), radius=round(radius*SCALE), fill=color, outline=outline, width=round(width*SCALE))

    def polygon(self, points, color):
        self.draw.polygon([(round(x*SCALE),round(y*SCALE)) for x,y in points], fill=color)

    def text(self, xy, value, size, color):
        self.draw.text(self.box(xy), value, fill=color, font=font(size*SCALE))


@lru_cache(maxsize=16)
def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError as exc:
        raise ValueError('This optional prototype requires Pillow >= 10.1 for scalable default lettering') from exc


def leaf(c, base, end, color, size=12):
    dx, dy = end[0]-base[0], end[1]-base[1]
    norm = max(1, math.hypot(dx,dy))
    mx,my = (base[0]+end[0])/2,(base[1]+end[1])/2
    c.polygon([base,(mx-dy/norm*size,my+dx/norm*size),end,(mx+dy/norm*size,my-dx/norm*size)],color)


@lru_cache(maxsize=1)
def background():
    image = Image.new('RGBA',(WIDTH*SCALE,HEIGHT*SCALE), '#18383e')
    c = Canvas(image)
    # A flat, warm garden set. No camera movement can conceal the handoff.
    c.rect((26,24,934,480),'#24464a',24)
    c.ellipse((560,48,873,360),'#304f50')
    c.ellipse((676,88,724,136),'#e8d6ad')
    for x,y in [(453,104),(526,72),(788,164),(863,99),(396,155),(825,242)]:
        c.ellipse((x,y,x+3,y+3),'#a0b7aa')
    c.rect((26,396,934,480),'#2d4a49',0)
    c.line([(48,420),(911,420)],'#5b7064',1)
    c.line([(86,448),(188,448)],'#47625a',1)
    c.line([(680,453),(864,453)],'#47625a',1)
    # Overhead beam and the only destination hook.
    c.rect((770,171,783,423),'#586a58',5)
    c.rect((510,168,795,180),'#7a805f',5)
    c.line([(520,180),(520,218)],'#c8bd91',3)
    c.line(curve((520,218),(535,235),(520,234)), '#c8bd91',3)
    # Fixed plants are spatial references, not changing generated decoration.
    for x,y,h in [(112,411,118),(164,415,75),(836,416,122),(878,416,83)]:
        c.line([(x,y),(x-5,y-h)],'#81946e',3)
        for n in range(3):
            yy=y-h+25*n+16
            leaf(c,(x-3,yy+20),(x-28,yy),'#68866e',8)
            leaf(c,(x-3,yy+24),(x+21,yy+3),'#94a276',8)
    c.rect((91,412,132,442),'#af7964',8)
    c.rect((140,415,186,441),'#b18e6b',8)
    c.rect((812,417,902,446),'#bd9d73',9)
    c.line([(816,427),(897,427)],'#8b795b',2)
    c.text((60,53),'GIF CINEMA  /  ORIGINAL OFFLINE STUDY',12,'#a7beb2')
    c.text((57,81),TITLE,31,CREAM)
    c.text((60,125),'A little warmth, passed from one hand to another.',14,'#b9c7b6')
    c.text((32,503),'01  OFFER    /    02  HANDOFF    /    03  HANG',12,'#b7c5b4')
    c.text((725,503),'8 SEC  /  10 FPS  /  SILENT',12,'#b7c5b4')
    return image


@lru_cache(maxsize=2)
def body(who):
    image=Image.new('RGBA',(WIDTH*SCALE,HEIGHT*SCALE))
    c=Canvas(image)
    x=288 if who=='courier' else 616
    primary,shade,accent = ('#ce8267','#ab6457','#e8bb83') if who=='courier' else ('#7eaa9b','#5c8d81','#d3c28c')
    c.ellipse((x-66,413,x+66,432),'#1d393b')
    # Boots and short legs preserve each character's silhouette.
    for dx in [-25,25]:
        c.rect((x+dx-11,385,x+dx+11,419),shade,8)
        c.rect((x+dx-18,409,x+dx+18,424),primary,7)
        c.line([(x+dx-10,418),(x+dx+10,418)],accent,2)
    c.rect((x-48,300,x+48,398),primary,22,INK,3)
    c.rect((x-27,327,x+27,374),shade,9)
    c.ellipse((x-5,340,x+5,350),accent)
    c.line([(x-15,362),(x+15,362)],accent,3)
    c.rect((x-15,287,x+15,306),shade,6)
    c.rect((x-56,218,x+56,294),primary,23,INK,3)
    c.rect((x-43,232,x+43,277),INK,15)
    # Fixed, distinctive head details and a gentle smile.
    for eye in [-16,16]:
        c.ellipse((x+eye-5,247,x+eye+5,258),CREAM)
    c.line(curve((x-8,264),(x,269),(x+8,264)),accent,2)
    c.ellipse((x-64,245,x-53,265),shade,INK,2)
    c.ellipse((x+53,245,x+64,265),shade,INK,2)
    if who=='courier':
        c.line([(x,218),(x-7,203)],accent,3)
        c.ellipse((x-12,194,x-2,204),accent)
        c.polygon([(x-51,286),(x+44,286),(x+34,303),(x-30,304)],'#e6b56f')
        c.polygon([(x-31,299),(x-17,301),(x-22,328),(x-36,320)],'#e6b56f')
    else:
        c.line([(x,218),(x+4,205)],'#a3bb87',3)
        leaf(c,(x+3,207),(x-16,193),'#b8c695',7)
        leaf(c,(x+3,207),(x+25,192),'#7da783',8)
        c.line([(x-28,304),(x-24,333)],accent,4)
        c.line([(x+28,304),(x+24,333)],accent,4)
    return image


def state(scene, index):
    """Authored state, including explicit shared-grip and release intervals.

    Hand coordinates denote visible palm centres; prop grasp anchors are defined
    relative to the handle. Owners change only while supported by another anchor.
    """
    count=SCENES[scene][1]
    if not 0<=index<count:
        raise ValueError('Frame index outside scene')
    lantern=(365.0,310.0)
    a=mix(lantern,lantern,0)
    b=(560.0,363.0)
    owner='courier'
    phase='offer'
    if scene==0:
        lantern=mix((365,310),(452,310),smooth((index-3)/16))
    elif scene==1:
        lantern=(452.0,310.0)
        b=mix((560,363),(464,319),smooth(index/9))
        phase='reach' if index<9 else 'shared-grip'
        if index>=9: owner='shared'
        if index>=14:
            owner='keeper';phase='courier-release'
            a=mix((440,319),(347,365),smooth((index-14)/6))
    else:
        owner='keeper';phase='lift'
        lantern=mix((452,310),(520,234),smooth(index/20))
        a=(347.0,365.0)
        if index>=21:
            owner='hook';phase='keeper-release' if index<28 else 'result-hold'
            # Release outward before lowering: never drag the palm through the glass.
            b=(mix((532,243),(568,243),smooth((index-21)/2)) if index<=23
               else mix((568,243),(560,363),smooth((index-23)/5)))
    grasp_a=(lantern[0]-12,lantern[1]+9)
    grasp_b=(lantern[0]+12,lantern[1]+9)
    if owner in ('courier','shared'): a=grasp_a
    if owner in ('keeper','shared'): b=grasp_b
    return {'scene':SCENES[scene][0],'frame':index,'duration_ms':DELAY_MS,
            'phase':phase,'owner':owner,'lantern_anchor':list(lantern),
            'courier_palm':list(a),'keeper_palm':list(b),
            'courier_grasp':list(grasp_a),'keeper_grasp':list(grasp_b),
            'hook_anchor':[520,234],'prop_count':1}


def arm(c, shoulder, palm, bend, color):
    points=curve(shoulder,bend,palm)
    c.line(points,INK,19)
    c.line(points,color,13)
    x,y=palm
    c.ellipse((x-9,y-9,x+9,y+9),color,INK,2)


def draw_lantern(c, anchor):
    x,y=anchor
    # Soft glow is baked artwork; no change in prop count or sprite identity.
    c.ellipse((x-52,y+7,x+52,y+109),(251,202,102,16))
    c.draw.arc(c.box((x-16,y,x+16,y+34)),180,360,fill=CREAM,width=3*SCALE)
    c.line([(x-16,y+17),(x-16,y+33)],CREAM,3)
    c.line([(x+16,y+17),(x+16,y+33)],CREAM,3)
    c.rect((x-23,y+28,x+23,y+78),'#efb958',6,INK,3)
    c.rect((x-16,y+37,x+16,y+68),'#ffdf91',3)
    c.line([(x,y+35),(x,y+69)],'#b88140',2)
    c.rect((x-26,y+26,x+26,y+34),'#d99a4a',3,INK,2)
    c.rect((x-26,y+72,x+26,y+80),'#d99a4a',3,INK,2)


def render_frame(item):
    image=background().copy()
    image.alpha_composite(body('courier'))
    image.alpha_composite(body('keeper'))
    c=Canvas(image)
    # Inactive outer arms always stay beside their character.
    arm(c,(245,316),(230,373),(218,345),'#b96e5e')
    arm(c,(659,316),(675,373),(688,345),'#719b8e')
    arm(c,(331,316),item['courier_palm'],(362,362),'#ce8267')
    arm(c,(573,316),item['keeper_palm'],(527,365),'#7eaa9b')
    # Lantern over the inner arms, then palms over its handle: deliberate occlusion.
    light=Image.new('RGBA',image.size)
    draw_lantern(Canvas(light),item['lantern_anchor'])
    image.alpha_composite(light)
    c=Canvas(image)
    for who,color in [('courier','#e8bb83'),('keeper','#bdcba7')]:
        x,y=item[who+'_palm']
        c.ellipse((x-7,y-7,x+7,y+7),color,INK,1.5)
        c.line([(x-3,y+2),(x+3,y+2)],INK,1)
    return image.convert('RGB').resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS)


def decoded(path):
    frames,delays,_=validate_gif(io.BytesIO(path.read_bytes()))
    return [f.convert('RGB') for f in frames],delays


def expand(frames,delays):
    result=[]
    for frame,delay in zip(frames,delays):
        if delay % DELAY_MS:
            raise ValueError('Unexpected GIF frame duration')
        result.extend([frame]*(delay//DELAY_MS))
    return result


def sheet(frames, selections, labels, out, columns=3):
    tw,th=320,180
    rows=math.ceil(len(selections)/columns)
    result=Image.new('RGB',(columns*tw,rows*(th+30)),'#18383e')
    d=ImageDraw.Draw(result)
    for cell,(index,label) in enumerate(zip(selections,labels)):
        x,y=(cell%columns)*tw,(cell//columns)*(th+30)
        result.paste(frames[index].resize((tw,th),Image.Resampling.LANCZOS),(x,y))
        d.text((x+8,y+th+6),label,fill=CREAM,font=font(12))
    result.save(out)


def run(command):
    return subprocess.run(command,cwd=ROOT,check=True,capture_output=True,timeout=300).stdout


def build(out):
    out=out.absolute()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)):
        raise ValueError('Output must be a new directory without symlinks')
    font(12)
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('FFmpeg and ffprobe are required')
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.handoff-stage-',dir=out.parent) as directory:
        stage=Path(directory)
        (stage/'frames').mkdir();(stage/'media').mkdir();(stage/'layers').mkdir()
        # Reusable originals and geometry sources are preserved alongside the timeline.
        background().save(stage/'layers/background.png')
        body('courier').save(stage/'layers/courier.png')
        body('keeper').save(stage/'layers/keeper.png')
        ledger=[];frames=[];ranges=[]
        for scene,(_,count,*_) in enumerate(SCENES):
            start=len(frames)
            for index in range(count):
                item=state(scene,index)
                frame=render_frame(item)
                name=f'frames/{len(frames):04d}.png'
                frame.save(stage/name)
                item.update(global_frame=len(frames),file=name,sha256=sha(stage/name))
                ledger.append(item);frames.append(frame)
            ranges.append((start,len(frames)))
        # Shared palette means exact scene endpoints remain exact in the GIF sources.
        palette_image=Image.new('RGB',(WIDTH,HEIGHT*3))
        for i,index in enumerate([0,35,75]): palette_image.paste(frames[index],(0,HEIGHT*i))
        palette=palette_image.quantize(colors=256,method=Image.Quantize.MEDIANCUT)
        quantized=[f.quantize(palette=palette,dither=Image.Dither.NONE) for f in frames]
        source_reports=[]
        for (name,count,*_), (start,end) in zip(SCENES,ranges):
            path=stage/'media'/f'{name}.gif'
            quantized[start].save(path,save_all=True,append_images=quantized[start+1:end],duration=DELAY_MS,optimize=False,disposal=1)
            actual,delays=decoded(path)
            expanded=expand(actual,delays)
            expected=quantized[start:end]
            if len(expanded)!=count or any(a.tobytes()!=b.convert('RGB').tobytes() for a,b in zip(expanded,expected)):
                raise ValueError('GIF dropped or changed an authored drawing')
            source_reports.append({'id':name,'file':f'media/{name}.gif','sha256':sha(path),'authoring_ticks':count,
                                   'decoded_gif_frames':len(actual),'duration_ms':sum(delays),'lossless_against_palette_frames':True})
        quantized[0].save(stage/'one-small-light.gif',save_all=True,append_images=quantized[1:],duration=DELAY_MS,optimize=False,disposal=1)
        gif_frames,gif_delays=decoded(stage/'one-small-light.gif')
        full=expand(gif_frames,gif_delays)
        if len(full)!=len(frames) or any(a.tobytes()!=b.convert('RGB').tobytes() for a,b in zip(full,quantized)):
            raise ValueError('Combined GIF changed authored drawing order or timing')
        with Image.open(stage/'one-small-light.gif') as delivered_gif:
            if 'loop' in delivered_gif.info:
                raise ValueError('Combined GIF should play once')
        script={'schema_version':1,'title':TITLE,'ratio':'16:9','width':WIDTH,'height':HEIGHT,'fps':FPS,
                'style_bible':'Original flat cutout robots in a fixed dusk garden. One lantern. Locked identity, camera, scale and geography.',
                'shots':[{'id':s[0],'source':f'media/{s[0]}.gif','first_frame_target':s[3],'last_frame_target':s[4],
                          'caption':s[2],'transition':'cut'} for s in SCENES]}
        dump(stage/'film.json',script)
        dump(stage/'anchor-ledger.json',{'schema_version':1,'coordinates':'pixels in 960x540 output','frames':ledger})
        before={s['file']:s['sha256'] for s in source_reports}
        command=[sys.executable,'-m','gif_cinema','render',str(stage/'film.json'),'--execute','--max-api-calls','0','--out',str(stage/'render')]
        first=run(command);second=run(command)
        (stage/'render-first.log').write_bytes(first);(stage/'render-resume.log').write_bytes(second)
        if before!={name:sha(stage/name) for name in before}:
            raise ValueError('Accepted scene source changed during assembly')
        shutil.copyfile(stage/'render/film.mp4',stage/'one-small-light.mp4')
        probe=json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-of','json',str(stage/'one-small-light.mp4')]))
        video=probe['streams'][0]
        if len(probe['streams'])!=1 or video['codec_name']!='h264' or int(video['nb_read_frames'])!=len(frames) or video['avg_frame_rate']!='10/1' or abs(float(video['duration'])-8)>0.001:
            raise ValueError('MP4 verification failed')
        run(['ffmpeg','-v','error','-xerror','-nostdin','-i',str(stage/'one-small-light.mp4'),'-f','null','-'])
        # Review images are decoded from the delivered files, not just ideal sources.
        (stage/'decoded-mp4').mkdir()
        run(['ffmpeg','-v','error','-nostdin','-i',str(stage/'one-small-light.mp4'),str(stage/'decoded-mp4/%04d.png')])
        movie_frames=[Image.open(p).convert('RGB') for p in sorted((stage/'decoded-mp4').glob('*.png'))]
        picks=[0,12,23,29,35,47,58,68,79]
        labels=['0.0s / OFFER START','1.2s / OFFER','2.3s / OFFER END','2.9s / REACH','3.5s / BOTH GRIP','4.7s / KEEPER OWNS','5.8s / LIFT','6.8s / ON HOOK','7.9s / HANDS CLEAR']
        sheet(movie_frames,picks,labels,stage/'contact-sheet.png')
        sheet(full,picks,labels,stage/'gif-contact-sheet.png')
        sheet(movie_frames,list(range(80)),[f'{i/10:.1f}s' for i in range(80)],stage/'all-exported-frames.png',columns=8)
        movie_frames[35].save(stage/'poster.png')
        joins=[]
        for left,right in [(23,24),(47,48)]:
            equal=frames[left].tobytes()==frames[right].tobytes()
            gif_equal=full[left].tobytes()==full[right].tobytes()
            if not equal or not gif_equal:
                raise ValueError('Scene endpoint state or pixels changed at a cut')
            joins.append({'from':left,'to':right,'png_pixels_identical':equal,'gif_pixels_identical':gif_equal,
                          'visual_review':'required; matching pixels do not validate whole action'})
        sheet(full,[23,24,47,48],['OFFER LAST','HANDOFF FIRST','HANDOFF LAST','HANG FIRST'],stage/'join-sheet.png',columns=2)
        receipt={'title':TITLE,'type':'original procedural cutout continuity prototype','new_provider_calls':0,
                 'dimensions':[WIDTH,HEIGHT],'fps':FPS,'duration_ms':8000,'authoring_ticks':80,
                 'gif_decoded_frames':len(gif_frames),'gif_playback':'once; viewers may override','audio':'silent',
                 'character_motion':'authored procedural arm paths; fixed body/head cutouts, no generated or interpolated footage',
                 'pillow_version':PIL.__version__,'font':'Pillow scalable default','source_scenes':source_reports,
                 'source_frames_preserved':True,'source_gifs_unchanged':True,'joins':joins,'export_verification':probe,
                 'visual_status':'human-review-required','source_reference':{'url':'https://github.com/WoYun520/gif-factory/blob/main/examples/storybooks/tea-party/README.md',
                  'blob_sha':'fca1dfd9d9bf4998d3114794c86f81302bde02a4','influence':'fixed background, prop trajectories, palm anchors, and contact inspection; no art or code copied'},
                 'limitations':['Fixed three-scene study, not a general rigging editor or automatic animation system.',
                                'Original flat vector-style art, not the illustrated quality or book layout of the reference.',
                                'Procedural arm movement and static facial poses are visibly stylized.',
                                'MP4 is lossy H.264; PNG originals and palette-derived GIF frames are preserved separately.'],
                 'files':{p.relative_to(stage).as_posix():sha(p) for p in stage.rglob('*') if p.is_file()}}
        dump(stage/'receipt.json',receipt)
        stage.replace(out)
    return {'out':str(out),'seconds':8,'frames':80,'provider_calls':0,'source_frames_preserved':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(build(args.out),indent=2))


if __name__=='__main__':
    main()
