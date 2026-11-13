"""The original reviewed compositor, using bundled lossless motion atlases.

No generation, interpolation inference, downloads or machine-specific paths.
Camera coverage and per-scene canopy gain come from timeline.json.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageEnhance
import math, random, json, wave, array
W,H,FPS,DURATION=960,540,25,20.8
BG=None
clips={}
positions={}

def load_assets(root):
    global BG, clips, positions
    root=Path(root)
    BG=Image.open(root/'assets/garden.png').convert('RGB')
    manifest=json.loads((root/'assets/manifest.json').read_text(encoding='utf-8'))
    clips={};positions={}
    for name,rec in manifest['clips'].items():
        xy=tuple(rec['xy']);positions[name]=xy
        back=BG.crop((*xy,xy[0]+320,xy[1]+320));frames=[]
        with Image.open(root/rec['path']) as sheet:
            for i in range(rec['frames']):
                x=i%8*320;y=i//8*320
                im=sheet.crop((x,y,x+320,y+320)).convert('RGB')
                mask=ImageChops.difference(im,back).convert('L').point(lambda v:255 if v>5 else 0).filter(ImageFilter.GaussianBlur(.45))
                frames.append((im,mask))
        clips[name]=frames

def ease(u):u=max(0,min(1,u));return u*u*(3-2*u)
def mix(a,b,u):return tuple(x+(y-x)*u for x,y in zip(a,b))
def bez(a,b,c,u):return tuple((1-u)**2*x+2*(1-u)*u*y+u*u*z for x,y,z in zip(a,b,c))
def draw_actor(im,name,u,first=0,last=None):
    last=len(clips[name])-1 if last is None else last;i=round(first+max(0,min(1,u))*(last-first));tile,mask=clips[name][i];im.paste(tile,positions[name],mask)
def idle(im,name,t):draw_actor(im,name,(t%2.56)/2.56)
def actors(im,t):
    if t<.64:idle(im,'idle-girl',t)
    elif t<3.2:draw_actor(im,'cast',(t-.64)/2.56)
    elif t<4.32:draw_actor(im,'cast',1)
    elif t<7.52:draw_actor(im,'catch',(t-4.32)/3.2)
    elif t<10.4:draw_actor(im,'release',(t-7.52)/2.88)
    elif t<12.8:idle(im,'idle-girl',t-10.4)
    elif t<14.72:draw_actor(im,'bow',(t-12.8)/1.92)
    else:idle(im,'idle-girl',t-14.72)
    if 3.2<=t<5.6:draw_actor(im,'boy',(t-3.2)/2.4,0,47)
    elif 10.4<=t<12.8:draw_actor(im,'boy',(t-10.4)/2.4,48,95)
    else:idle(im,'idle-boy',t+.8)
PALM=[(124.7,192.6),(117.2,192.1),(113.2,186.5),(114.6,174.6),(113.8,166.9),(112,156.4),(109.8,153.6),(107.4,152.7),(101.1,148.7),(94.2,145.7),(94.5,144.4),(87,138.9),(88.7,137.9),(84.6,141.8),(87.1,147.9),(92.3,157),(91.8,158.9),(90.5,159.6),(86,157.3),(86.8,151.4),(81,148.2),(80,148.3),(80.9,147.2),(78.3,147.7)]
def orb(t):
    if t<3.2:
        index=max(0,min(23,(t-.64)/2.56*23.75));lo=int(index);p=mix(PALM[lo],PALM[min(23,lo+1)],index-lo);return (560+p[0],190+p[1]-14)
    if t<4.32:return bez((638.3,323.7),(435,100),(240,207),(t-3.2)/1.12)
    if t<5.12:
        a=(t-4.32)/.8*math.tau;return (240+38*math.sin(a),207-26*math.sin(a/2))
    if t<6.96:return bez((240,207),(510,70),(712,340),ease((t-5.12)/1.84))
    return mix((712,340),(715,327),ease((t-7.52)/1.1))
rng=random.Random(831)
particles=[(rng.uniform(0,math.tau),rng.uniform(.6,1.5),rng.random(),rng.uniform(.7,2)) for _ in range(120)]
ambient=[(rng.uniform(0,960),rng.uniform(80,500),rng.uniform(.5,1.5),rng.random()*6.28) for _ in range(45)]
petals=[(rng.uniform(-200,960),rng.uniform(10,500),rng.uniform(12,35),rng.uniform(0,6.28)) for _ in range(22)]
def frame(t, scene):
    im=BG.copy();shade=Image.new('RGBA',(W,H));sd=ImageDraw.Draw(shade)
    for x,y in [(720,493),(240,483)]:sd.ellipse((x-58,y-8,x+58,y+8),fill=(8,17,30,100))
    im=Image.alpha_composite(im.convert('RGBA'),shade.filter(ImageFilter.GaussianBlur(5))).convert('RGB');actors(im,t)
    core=Image.new('RGB',(W,H));glow=Image.new('RGB',(W,H));d=ImageDraw.Draw(core);g=ImageDraw.Draw(glow)
    def light(x,y,r=2,c=(125,238,245),p=1):
        p=max(0,min(1,p));c=tuple(int(v*p) for v in c);g.ellipse((x-r*4,y-r*4,x+r*4,y+r*4),fill=tuple(int(v*.65) for v in c));d.ellipse((x-r,y-r,x+r,y+r),fill=c)
        if r>3:d.ellipse((x-r*.35,y-r*.35,x+r*.35,y+r*.35),fill=tuple(int(v*p) for v in (245,255,248)))
    for x,y,r,a in ambient:light(x+8*math.sin(t*.5+a),y+8*math.cos(t*.3+a),r,(250,202,120),.35+.2*math.sin(t*2+a)**2)
    # The light follows the hand during charge and catch; trails use past positions.
    if .7<t<9.0:
        x,y=orb(t);power=ease((t-.7)/.6)*(1-ease((t-8.72)/.28))
        if 3.2<t<6.96:
            pts=[orb(max(3.2,t-i*.014)) for i in range(44)]
            for i in range(43):
                v=int(210*(1-i/44)*power);g.line([pts[i],pts[i+1]],fill=(v//3,v*3//4,v),width=max(1,15-i//4));d.line([pts[i],pts[i+1]],fill=(v//2,v,v),width=max(1,5-i//10))
        light(x,y,7+math.sin(t*12),p=power)
        for k in range(6):
            a=t*3+k*math.tau/6;r=14+5*math.sin(t*3);light(x+math.cos(a)*r,y+math.sin(a)*r*.45,1.8,p=power)
        # Charge rings contract into the palm, not random unrelated overlays.
        if t<3.2:
            for j in range(2):
                rr=10+((3.2-t)*35+j*18)%55;v=int(110*power*(1-rr/80));g.ellipse((x-rr,y-rr*.45,x+rr,y+rr*.45),outline=(v//3,v,v),width=2)
    for event,xy,color in [(3.2,(638.3,323.7),(100,220,255)),(4.32,(240,207),(255,195,100)),(6.96,(712,340),(100,240,255)),(8.96,(715,327),(255,210,115))]:
        u=t-event
        if 0<=u<.64:
            rr=8+u*160;v=1-u/.64;col=tuple(int(c*v) for c in color);g.ellipse((xy[0]-rr,xy[1]-rr*.6,xy[0]+rr,xy[1]+rr*.6),outline=col,width=5)
            for k in range(12):
                a=k*math.tau/12+.3;px=xy[0]+math.cos(a)*u*165;py=xy[1]+math.sin(a)*u*110;light(px,py,1.6,color,v)
    # Keep palm/flight effects in front. The canopy lives behind the actors so
    # bright ribbons cannot wash out their faces or erase costume details.
    front_core=core;front_glow=glow
    core=Image.new('RGB',(W,H));glow=Image.new('RGB',(W,H));d=ImageDraw.Draw(core);g=ImageDraw.Draw(glow)
    # Main payoff: three animated ribbons divide into a moving star canopy.
    if t>=8.8:
        u=t-8.8
        for band in range(3):
            pts=[]
            for i in range(75):
                q=i/74;arrival=ease(u/2.5);x=715+(q*2-1)*340*arrival
                y=327-200*arrival+math.sin(q*math.tau*1.4-u*1.2+band*1.9)*45*arrival
                pts.append((x,y+band*10))
            strength=ease(u/.5)*(1-ease((u-6.7)/1.4));col=(int(170*strength),int(130*strength),int(65*strength))
            if strength>0:g.line(pts,fill=col,width=10);d.line(pts,fill=tuple(int(v*.8) for v in col),width=2)
        for i,(a,s,q,phase) in enumerate(particles):
            target=(70+(i*107)%820,60+(i*71)%240);travel=ease((u-q*.8)/2.0);x,y=bez((715,327),(500+math.cos(a)*240,15),target,travel)
            x+=math.sin(u*phase+a)*13*travel;y+=math.cos(u*.7+a)*9*travel
            strength=ease((u-q*.8)/.5);col=(255,206,112) if i%3 else (117,236,255)
            light(x,y,1.2+s*.75,col,strength*(.6+.35*math.sin(u*4+a)**2))
            if i%9==0 and travel>.9:
                v=int(110*strength);d.line((x-4,y,x+4,y),fill=(v,v,v//2));d.line((x,y-4,x,y+4),fill=(v,v,v//2))
    # Each visible lantern receives one descending light; bloom persists afterward.
    for k,(x,y) in enumerate([(834,174),(421,205),(190,226)]):
        start=13.6+k*.64;u=t-start
        if -.8<u<0:
            q=(u+.8)/.8;px,py=bez((500+k*60,70),(x,90),(x,y),q);light(px,py,5,(255,205,110))
        if u>=0:
            light(x,y,8,(255,178,83),ease(u/.48)*.65)
            if u<.8:
                rr=10+u*85;v=int((1-u/.8)*140);g.ellipse((x-rr,y-rr,x+rr,y+rr),outline=(v,int(v*.65),v//3),width=3)
    gain=scene["effects"]["canopy_gain"]
    if gain != 1:
        core=ImageEnhance.Brightness(core).enhance(gain)
        glow=ImageEnhance.Brightness(glow).enhance(gain)
    occlusion=ImageChops.difference(im,BG).convert('L').point(lambda v:255 if v>6 else 0).filter(ImageFilter.GaussianBlur(.5))
    glow=glow.filter(ImageFilter.GaussianBlur(9));glow.paste((0,0,0),(0,0,W,H),occlusion);core.paste((0,0,0),(0,0,W,H),occlusion)
    im=ImageChops.add(im,glow);im=ImageChops.add(im,core)
    im=ImageChops.add(im,front_glow.filter(ImageFilter.GaussianBlur(9)));im=ImageChops.add(im,front_core)
    # Foreground petals move with depth while the illustrated actors perform.
    overlay=Image.new('RGBA',(W,H));pdraw=ImageDraw.Draw(overlay)
    for x,y,s,a in petals:
        xx=(x+t*s)%1120-80;yy=y+math.sin(t*.9+a)*22;rr=2+s/18;ang=t+a
        pdraw.ellipse((xx-rr,yy-rr*.4,xx+rr,yy+rr*.4),fill=(245,155,183,120))
    im=Image.alpha_composite(im.convert('RGBA'),overlay).convert('RGB')
    box=scene["camera"]
    # Small continuous optical push within a shot, never used as character action.
    z=1+.012*math.sin(t*.4);cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2;bw=(box[2]-box[0])/z;bh=(box[3]-box[1])/z
    return im.crop((cx-bw/2,cy-bh/2,cx+bw/2,cy+bh/2)).resize((W,H),Image.Resampling.LANCZOS)
def sound(path):
    rate=24000;n=round(DURATION*rate);left=[0.0]*n;right=[0.0]*n
    def tone(start,length,freq,gain,pan=0):
        begin=round(start*rate);count=round(length*rate)
        for j in range(min(count,n-begin)):
            u=j/rate;e=(1-math.exp(-u*40))*math.exp(-u*3/max(.1,length));v=(math.sin(math.tau*freq*u)+.3*math.sin(math.tau*freq*2.003*u))*e*gain
            left[begin+j]+=v*(1-pan)*.5;right[begin+j]+=v*(1+pan)*.5
    for t,f,pan in [(1.1,587.33,.5),(2,739.99,.5),(3.2,1174.66,.4),(4.32,880,-.5),(5.12,987.77,-.5),(6.96,1174.66,.5),(8.96,1479.98,.4),(13.6,1174.66,.7),(14.24,1479.98,0),(14.88,1760,-.5),(18.4,587.33,0)]:tone(t,1.6,f,.18,pan)
    for k in range(3):
        for f in [146.83,220,293.66,369.99]:tone(k*7,7.5,f,.035)
    for start,end in [(3.2,4.32),(5.12,6.96),(8.8,10.8)]:
        randomizer=random.Random(int(start*100));v=0
        for i in range(round(start*rate),round(end*rate)):
            u=(i/rate-start)/(end-start);v=.88*v+.12*randomizer.uniform(-1,1);val=v*math.sin(math.pi*u)**2*.22;pan=math.sin(u*math.pi-math.pi/2);left[i]+=val*(1-pan);right[i]+=val*(1+pan)
    out=array.array('h')
    for i,(l,r) in enumerate(zip(left,right)):
        fade=min(1,i/rate/1.2,(DURATION-i/rate)/1.1)
        out.extend([round(math.tanh(l)*fade*26000),round(math.tanh(r)*fade*26000)])
    with wave.open(str(path),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(rate);f.writeframes(out.tobytes())
