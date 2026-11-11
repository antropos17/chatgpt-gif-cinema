#!/usr/bin/env python3
"""Rebuild the original offline cutout set and five authored action tracks.

Only Pillow and the Python standard library are used. No model or network calls.
This writes inputs, not compiler exports. Run the sequence CLI to render them.
"""
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'examples/scene-sequence'
ASSETS = OUT / 'assets'
W, H = 640, 360
INK = '#18383c'


def save(name, size, draw):
    im = Image.new('RGBA', size)
    draw(ImageDraw.Draw(im))
    im.save(ASSETS / (name + '.png'))


def robot(d, primary, accent, keeper=False):
    d.ellipse((4,137,100,151), fill='#18383c')
    for x in (24,66):
        d.rounded_rectangle((x,118,x+16,144), 5, fill=primary, outline=INK, width=2)
        d.rounded_rectangle((x-6,136,x+22,149), 5, fill=accent, outline=INK, width=2)
    d.rounded_rectangle((16,72,88,127), 14, fill=primary, outline=INK, width=3)
    d.rounded_rectangle((31,87,73,116), 6, fill=INK)
    d.ellipse((47,93,57,103), fill=accent)
    d.line((42,109,62,109), fill=accent, width=2)
    d.rounded_rectangle((38,60,66,79), 5, fill=accent, outline=INK, width=2)
    d.rounded_rectangle((9,19,95,70), 16, fill=primary, outline=INK, width=3)
    d.rounded_rectangle((19,30,85,59), 9, fill=INK)
    for x in (36,65):
        d.ellipse((x-4,37,x+4,45), fill='#f8eccb')
    d.arc((44,43,60,53), 0, 180, fill=accent, width=2)
    d.line((52,20,52,9), fill=accent, width=3)
    if keeper:
        d.polygon([(52,11),(35,1),(35,11),(52,16)], fill='#bbc991')
        d.polygon([(52,11),(68,0),(68,10),(52,16)], fill='#92b38c')
        d.line((30,73,35,86,70,86,75,73), fill=accent, width=3)
    else:
        d.ellipse((47,0,57,10), fill=accent)
        d.polygon([(14,65),(90,65),(77,77),(28,77),(22,91),(15,84)], fill=accent)
    # The outside arm stays tucked beside the body. The inside arm is a separate pivot.
    x = 88 if keeper else 7
    d.rounded_rectangle((x-5,78,x+7,117), 6, fill=primary, outline=INK, width=2)


def background(d):
    d.rectangle((0,0,W,H), fill='#132f37')
    d.rounded_rectangle((16,16,624,322), 18, fill='#25464b')
    d.ellipse((340,28,586,274), fill='#2d5052')
    d.ellipse((526,49,558,81), fill='#dbd8b3')
    for x,y in [(312,65),(398,42),(479,89),(578,119),(288,120)]:
        d.ellipse((x,y,x+2,y+2), fill='#9cb6ab')
    d.rectangle((16,280,624,322), fill='#34524f')
    d.line((30,291,610,291), fill='#658073', width=1)
    d.rounded_rectangle((506,111,515,295), 3, fill='#6c7c66')
    d.rounded_rectangle((337,109,528,118), 4, fill='#9a9b78')
    for x,y,h in [(68,292,65),(105,298,43),(560,295,68),(588,299,43)]:
        d.line((x,y,x,y-h), fill='#9baa7c', width=2)
        for z in range(3):
            yy=y-h+15*z
            d.polygon([(x,yy+17),(x-18,yy),(x-20,yy+10)], fill='#72977e')
            d.polygon([(x,yy+19),(x+17,yy+1),(x+18,yy+10)], fill='#a1b18b')
        d.rounded_rectangle((x-13,y-1,x+14,y+17), 4, fill='#b68b69')
    f=ImageFont.load_default(size=22)
    d.text((35,32),'A LIGHT FOR THE GARDEN',font=f,fill='#f1e4c5')
    d.text((36,62),'One lantern. Two friends. A place to glow.',font=ImageFont.load_default(size=12),fill='#b6cbbd')
    d.text((22,336),'ORIGINAL CUTOUT STUDY  /  5 ACTIONS  /  10 SEC  /  25 FPS',font=ImageFont.load_default(size=11),fill='#b6cbbd')


def arm(d, primary):
    d.rounded_rectangle((0,3,112,21), 8, fill=INK)
    d.rounded_rectangle((4,6,111,18), 6, fill=primary)
    d.line((13,10,84,10), fill='#dfd2ad', width=2)
    d.ellipse((0,0,24,24), fill=primary, outline=INK, width=3)
    d.ellipse((8,8,16,16), fill='#dfd2ad')


def lantern(d):
    d.arc((12,0,36,25),180,360,fill='#ffe1a0',width=3)
    d.rounded_rectangle((7,18,41,56),5,fill='#b87a46',outline='#ffe1a0',width=2)
    d.rounded_rectangle((13,24,35,49),4,fill='#f7cd77')
    d.ellipse((19,29,29,45),fill='#fff1b2')
    d.line((24,21,24,52),fill='#b87a46',width=2)
    d.rounded_rectangle((3,17,45,22),2,fill='#ffe1a0')
    d.rounded_rectangle((4,53,44,59),2,fill='#d6a16a')


def pose(x,y,rotation=0):
    return {'at':0,'x':x/W,'y':y/H,'rotation':rotation,'easing':'smootherstep'}


def layer(id, source, size, x,y,rotation=0,anchor=None):
    obj={'id':id,'type':'image','source':'assets/'+source+'.png','size':size,'keyframes':[pose(x,y,rotation),{'at':1}]}
    if anchor is not None:obj['anchor']=anchor
    return obj


def segment(parent,duration,point=(.5,.5)):
    return {'start_ms':0,'end_ms':duration,'parent':parent,'point':list(point)}


def track(rotation, end=.8):
    return {'keyframes':[{'at':0},{'at':end,'rotation':rotation,'easing':'smootherstep'},{'at':1}]}


def main():
    ASSETS.mkdir(parents=True,exist_ok=True)
    save('garden',(W,H),background)
    save('courier',(104,152),lambda d:robot(d,'#cd876c','#efc47d'))
    save('keeper',(104,152),lambda d:robot(d,'#84b1a0','#d8d29a',True))
    save('courier-arm',(112,24),lambda d:arm(d,'#cd876c'))
    save('keeper-arm',(112,24),lambda d:arm(d,'#84b1a0'))
    for id,color in [('courier-hand','#efc47d'),('keeper-hand','#b5d0b7')]:
        save(id,(18,18),lambda d,c=color:d.ellipse((1,1,17,17),fill=c,outline=INK,width=2))
    save('lantern',(48,62),lantern)
    # Rigid arms pivot around pixel (12,12), endpoint at pixel (112,12).
    # Both tips coincide at (320,225) during the receive. Hook is the keeper's
    # same endpoint after a 225-degree lift: (349.289...,154.289...).
    hx,hy=420-100/math.sqrt(2),225-100/math.sqrt(2)
    layers=[layer('garden','garden',[W,H],320,180),
            layer('courier','courier',[104,152],195,225),
            layer('keeper','keeper',[104,152],445,225),
            {'id':'hook','type':'stroke','size':[22,44],'points':[[11,0],[11,30],[6,36],[11,40],[16,36]],'stroke':'#e4d7ac','stroke_width':3,'anchor':[.5,40/44],'keyframes':[pose(hx,hy),{'at':1}]},
            layer('courier-arm','courier-arm',[112,24],220,225,-35,[12/112,.5]),
            layer('keeper-arm','keeper-arm',[112,24],420,225,120,[12/112,.5])]
    for who in ('courier','keeper'):
        hand={'id':who+'-hand','type':'image','source':'assets/'+who+'-hand.png','size':[18,18], 'attachments':[segment(who+'-arm',1000,(1,.5))]}
        layers.append(hand)
    layers.append({'id':'lantern','type':'image','source':'assets/lantern.png','size':[48,62],'anchor':[.5,0], 'attachments':[segment('courier-hand',1000)]})
    stage={'format':'gif-cinema-layered-scene','schema_version':1,'title':'A light for the garden — shared stage','width':W,'height':H,'fps':25,'duration_ms':1000,'loop':False,'matte':'#132f37','layers':layers}
    shots=[
        {'id':'01-offer','action':'The courier pivots its arm forward, offering the lantern.','duration_ms':2000,'tracks':{'courier-arm':track(0)}},
        {'id':'02-receive','action':'The keeper reaches the same handle; both hands remain in contact.','duration_ms':2000,'tracks':{'keeper-arm':{'keyframes':[{'at':0},{'at':.2,'zoom':.4},{'at':.45,'rotation':180},{'at':.8,'zoom':1},{'at':1}]}}},
        {'id':'03-release','action':'The keeper takes support; the courier withdraws its hand.','duration_ms':1600,'tracks':{'lantern':{'attachments':[segment('keeper-hand',1600)]},'courier-arm':track(-60)}},
        {'id':'04-lift','action':'The keeper lifts the same lantern to the garden hook.','duration_ms':2400,'tracks':{'keeper-arm':track(225)}},
        {'id':'05-hang','action':'The hook takes support; the keeper clears the handle upward, retracts its mechanical arm, and lowers it.','duration_ms':2000,'tracks':{'lantern':{'attachments':[segment('hook',2000,(.5,40/44))]},'keeper-arm':{'keyframes':[{'at':0},{'at':.2,'rotation':270},{'at':.35,'zoom':.4},{'at':.7,'rotation':120},{'at':.9,'zoom':1},{'at':1}]}}}]
    sequence={'format':'gif-cinema-layer-sequence','schema_version':1,'title':'A light for the garden','stage':'stage.json','shots':shots}
    for name,obj in [('stage',stage),('sequence',sequence)]:
        (OUT/(name+'.json')).write_text(json.dumps(obj,indent=2)+'\n')
    print(OUT/'sequence.json')


def export_review(rendered):
    """Package viewing copies from an already completed compiler export."""
    import hashlib
    import shutil
    rendered = Path(rendered)
    receipt = json.loads((rendered / 'sequence-receipt.json').read_text())
    dest = ROOT / 'docs/assets/scene-sequence'
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(rendered / 'film/film.mp4', dest / 'preview.mp4')
    frames, selected = [], []
    for shot in receipt['timeline']:
        paths = sorted((rendered / 'shots' / shot['id'] / 'frames').glob('*.png'))
        for n in (0,len(paths)//2,len(paths)-1):
            frame = Image.open(paths[n]).convert('RGB')
            ImageDraw.Draw(frame).text((20,318),shot['id']+' / '+str(n*40)+' ms',fill='white',font=ImageFont.load_default(size=12))
            selected.append(frame)
        frames.extend(Image.open(path).convert('RGB') for path in paths)
    frames[0].save(dest/'preview.gif',save_all=True,append_images=frames[1:],duration=40,optimize=True,disposal=2)
    sheet=Image.new('RGB',(W*3,H*5))
    for n,frame in enumerate(selected):sheet.paste(frame,((n%3)*W,(n//3)*H))
    sheet.save(dest/'contact-sheet.png')
    for join in (rendered/'joins').glob('*.png'):shutil.copyfile(join,dest/('join-'+join.name))
    provenance = {
        'title': receipt['title'], 'original_project_sha256': receipt['original_project_sha256'],
        'original_stage_sha256': receipt['original_stage_sha256'],
        'asset_sha256': receipt['asset_sha256'], 'duration_ms': receipt['duration_ms'],
        'frames': receipt['frames'], 'fps': receipt['fps'], 'provider_calls': receipt['provider_calls'],
        'joins': receipt['joins'], 'visual_acceptance': 'not-established',
        'review_scope': 'First/middle/last source PNG samples and all four join triples are provided for review. Packaging does not establish full-motion human approval.',
        'files': {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dest.iterdir()) if p.is_file()}
    }
    (OUT/'preview-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(dest)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-export',type=Path,help='Package viewing copies of an existing completed sequence export, without modifying inputs')
    args=parser.parse_args()
    if args.review_export:export_review(args.review_export)
    else:main()
