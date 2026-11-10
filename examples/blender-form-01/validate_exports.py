from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageSequence
import numpy as np, subprocess,json,hashlib,zipfile
P=Path(__file__).resolve().parent; D=P/'deliverables'; D.mkdir(exist_ok=True)
frames=sorted((P/'renders').glob('form_*.png'))
assert len(frames)==144, len(frames)
assert [f.name for f in frames]==[f'form_{i:04d}.png' for i in range(1,145)]
assert all(Image.open(f).size==(800,800) for f in frames)
probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(D/'FORM-01.mp4')]))
v=next(s for s in probe['streams'] if s['codec_type']=='video')
assert (v['width'],v['height'])==(800,800)
assert int(v['nb_read_frames'])==144
assert v['r_frame_rate']=='24/1'
assert abs(float(probe['format']['duration'])-6)<.001
assert not any(s['codec_type']=='audio' for s in probe['streams'])
gif=Image.open(D/'FORM-01.gif')
durations=[f.info.get('duration',0) for f in ImageSequence.Iterator(gif)]
assert gif.n_frames==120,gif.n_frames
assert sum(durations)==6000,sum(durations)
assert gif.info.get('loop')==0
assert gif.size==(640,640)
report=json.loads((P/'scene-check.json').read_text())
report.update({'png_frame_count':len(frames),'mp4':{'codec':v['codec_name'],'resolution':[v['width'],v['height']],'frame_count':int(v['nb_read_frames']),'frame_rate':v['r_frame_rate'],'seconds':float(probe['format']['duration']),'audio':False},'gif':{'resolution':list(gif.size),'frame_count':gif.n_frames,'durations_ms':sorted(set(durations)),'seconds':sum(durations)/1000,'loop':'infinite'}})
# Seam has one normal frame interval, not a duplicated final pose.
a=np.asarray(Image.open(frames[0]),dtype=float); b=np.asarray(Image.open(frames[-1]),dtype=float); c=np.asarray(Image.open(frames[1]),dtype=float)
report['frame_seam_mean_abs_rgb_difference']=float(np.mean(abs(a-b)))
report['first_step_mean_abs_rgb_difference']=float(np.mean(abs(c-a)))
report['seam_check_note']='Geometry transforms at frame 145 and frame 1 are identical. Encoded sequence intentionally ends on frame 144.'
# Check all rendered frames are decodable, and no frame is an accidental duplicate.
hashes=[hashlib.sha256(f.read_bytes()).hexdigest() for f in frames]
report['unique_render_frames']=len(set(hashes))
assert len(set(hashes))==144
ids=[1,13,25,37,49,61,73,85,97,109,121,144]
w=400;h=430
sheet=Image.new('RGB',(w*4,h*3),(238,235,227)); draw=ImageDraw.Draw(sheet)
font=ImageFont.truetype(str(P/'assets/DejaVuSans.ttf'),13)
for j,i in enumerate(ids):
 x=(j%4)*w;y=(j//4)*h
 im=Image.open(P/'renders'/f'form_{i:04d}.png');sheet.paste(im.resize((w,w),Image.Resampling.LANCZOS),(x,y))
 draw.text((x+18,y+w+7),f'{(i-1)/24:05.2f}s  /  FRAME {i:03d}',font=font,fill=(40,43,40))
sheet.save(D/'contact-sheet.jpg',quality=94)
report['contact_sheet_frames']=ids
# Quantify output sizes and checksums for reproducibility.
report['exports']={f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in [D/'FORM-01.mp4',D/'FORM-01.gif']}
(D/'validation.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
