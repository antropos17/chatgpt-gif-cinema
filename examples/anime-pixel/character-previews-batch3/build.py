from PIL import Image,ImageSequence
from pathlib import Path
import json,hashlib
root=Path(__file__).resolve().parent
entries=[]
for key,xs,stride,h,name in [('violinist',[7,321,634,948],313.5,313,'Violinist · bow gesture'),('blacksmith',[7,321,634,948],313.5,313,'Blacksmith · hammer inspection')]:
 src=root/'sources'/f'{key}-sheet.png'; sheet=Image.open(src).convert('RGB'); frames=[]
 folder=root/'frames'/key;folder.mkdir(exist_ok=True,parents=True)
 for i in range(16):
  x=xs[i%4];y=round((i//4)*stride)
  f=Image.new('RGB',(320,344),(243,238,229));f.paste(sheet.crop((x,y,x+300,y+h)),(10,8));f.save(folder/f'{i:02}.png');frames.append(f)
 palette=Image.new('RGB',(320,344*16))
 for i,f in enumerate(frames):palette.paste(f,(0,i*344))
 palette=palette.quantize(colors=256)
 frames=[f.quantize(palette=palette,dither=Image.Dither.NONE) for f in frames]
 out=root/f'{key}.gif';frames[0].save(out,save_all=True,append_images=frames[1:],duration=120,loop=0,optimize=False,disposal=2)
 with Image.open(out) as im:
  decoded=[f.convert('RGB').copy() for f in ImageSequence.Iterator(im)]
  durations=[]
  for j in range(im.n_frames):im.seek(j);durations.append(im.info['duration'])
 e=dict(id=key,name=name,gif=out.name,source='sources/'+src.name,method='drawn-poses',frames=len(decoded),unique_frames=len({hashlib.sha256(f.tobytes()).hexdigest() for f in decoded}),duration_ms=sum(durations),dimensions=[320,344],limitations='Generated-pose preview. Residual face/outline drift; opaque ivory background; short 1.92 s loop, not a 15 s narrative or finished acting animation.',extraction=dict(column_origins=xs,row_stride=stride,cell_size=[300,h],strategy='Fixed per-column crops; no per-frame resizing, silhouette recentering, interpolation, crossfade or reverse.'))
 entries.append(e)
 # Contact sheet from decoded GIF, confirms actual encoded pixels.
 contact=Image.new('RGB',(1280,1376))
 for i,f in enumerate(decoded):contact.paste(f,((i%4)*320,(i//4)*344))
 contact.save(root/f'{key}-decoded-contact.png')
(root/'manifest.json').write_text(json.dumps({'entries':entries},indent=2))
print(json.dumps(entries,indent=2))
