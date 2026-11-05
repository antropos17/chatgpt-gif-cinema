"""OpenAI GIF client and FFmpeg film assembler ."""
import argparse
import base64
import json
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.openai.com/v1/images/generations"
MODELS = ("gpt-image-2.6-flare", "gpt-image-2.6-sunburst")

def make_payload(prompt, model="gpt-image-2.6-flare", frames=9, duration=200, size="auto", quality="low", complexity="low"):
    if not 2 <= frames <= 16:
        raise ValueError("frames must be 2..16 (conservative compatibility range)")
    if not 20 <= duration <= 2000:
        raise ValueError("duration must be 20..2000 milliseconds")
    if model not in MODELS:
        raise ValueError("unsupported model")
    if size != "auto":
        try:
            w, h = (int(s) for s in size.lower().split("x"))
        except (ValueError, TypeError) as exc:
            raise ValueError("size must be auto or WIDTHxHEIGHT") from exc
        if w <= 0 or h <= 0 or w % 16 or h % 16 or not 1/3 <= w/h <= 3:
            raise ValueError("dimensions must be positive multiples of 16, aspect ratio 1:3..3:1")
    return {"model":model, "prompt":prompt, "output_format":"gif", "frame_count":frames,
            "frame_duration_ms":duration, "size":size, "quality":quality, "complexity":complexity}

def request_gif(payload, key, endpoint=API_URL, transport=urlopen):
    req = Request(endpoint, data=json.dumps(payload).encode(),
                  headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"}, method="POST")
    try:
        with transport(req, timeout=180) as res:
            body = json.load(res)
    except HTTPError as exc:
        raise RuntimeError(f"OpenAI API HTTP {exc.code}; response body omitted to protect credentials") from exc
    except URLError as exc:
        raise RuntimeError("OpenAI network request failed; no automatic retry was made") from exc
    except (TimeoutError, OSError) as exc:
        raise RuntimeError("OpenAI request timed out or failed; no automatic retry was made") from exc
    try:
        raw = base64.b64decode(body["data"][0]["b64_json"], validate=True)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise RuntimeError("Missing/invalid b64_json in image response") from exc
    gif_frames(io.BytesIO(raw))
    return raw, body.get("usage")

def generate(args):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY in your environment. Never commit it.")
    payload = make_payload(args.prompt,args.model,args.frames,args.duration,args.size,args.quality,args.complexity)
    out = Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    if out.suffix.lower() != ".gif":
        raise ValueError("Output must have a .gif extension")
    if out.exists() or out.with_suffix(".json").exists():
        raise ValueError("Output or metadata already exists; choose a new path before a paid request")
    start = time.monotonic()
    raw,usage = request_gif(payload,key)
    out.write_bytes(raw)
    metadata={"prompt":args.prompt,"parameters":payload,"output":str(out),
              "seconds":round(time.monotonic()-start,2),"usage":usage,
              "sha256":hashlib.sha256(raw).hexdigest()}
    out.with_suffix(".json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Created {out} ({len(raw):,} bytes)")

def film(args):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required: https://ffmpeg.org/download.html")
    clips=[Path(p).resolve() for p in args.clips]
    for clip in clips:
        if not clip.is_file() or clip.read_bytes()[:6] not in (b"GIF87a",b"GIF89a"):
            raise ValueError(f"not a valid GIF: {clip}")
    out=Path(args.output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    command=["ffmpeg","-hide_banner","-y"]
    for clip in clips:
        command+=["-i",str(clip)]
    if args.audio:
        if not Path(args.audio).is_file():raise ValueError(f"audio not found: {args.audio}")
        command+=["-i",str(Path(args.audio).resolve())]
    filters=[]
    for i in range(len(clips)):
        filters.append(f"[{i}:v]fps={args.fps},scale={args.width}:{args.height}:force_original_aspect_ratio=decrease,pad={args.width}:{args.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{i}]")
    filters.append("".join(f"[v{i}]" for i in range(len(clips)))+f"concat=n={len(clips)}:v=1:a=0[outv]")
    command+=["-filter_complex",";".join(filters),"-map","[outv]"]
    if args.audio:command+=["-map",f"{len(clips)}:a:0","-shortest","-c:a","aac"]
    command+=["-c:v","libx264","-pix_fmt","yuv420p","-movflags","+faststart",str(out)]
    subprocess.run(command,check=True)
    print(f"Created movie: {out}")

def gif_frames(path):
    try:
        from PIL import Image,ImageSequence
    except ImportError as exc:
        raise RuntimeError("Install Pillow: pip install Pillow") from exc
    with Image.open(path) as im:
        if im.format!="GIF":raise ValueError("not a GIF")
        frames=[];durations=[]
        for frame in ImageSequence.Iterator(im):
            frames.append(frame.convert("RGB").copy())
            duration = int(frame.info.get("duration", 0))
            if duration < 20:
                raise ValueError("GIF frames must have a duration of at least 20 ms")
            durations.append(duration)
        if len(frames) < 2:
            raise ValueError("GIF must contain at least two frames")
        return frames,durations,im.info.get("loop")

def inspect(args):
    frames,durations,loop=gif_frames(args.gif)
    data={"file":str(args.gif),"frames":len(frames),"width":frames[0].width,"height":frames[0].height,
          "duration_ms":sum(durations),"frame_durations_ms":durations,"loop":loop}
    print(json.dumps(data,indent=2))
    if args.output:
        p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2))

def endpoints(args):
    frames,_,_=gif_frames(args.gif)
    p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True)
    frames[0].save(str(p)+"-first.png");frames[-1].save(str(p)+"-last.png")

def continuity(args):
    from PIL import ImageChops,ImageStat
    a,_,_=gif_frames(args.previous);b,_,_=gif_frames(args.next)
    diff=ImageChops.difference(a[-1].resize((128,128)),b[0].resize((128,128)))
    mae=sum(ImageStat.Stat(diff).mean)/3
    report={"previous":str(args.previous),"next":str(args.next),"pixel_mae_0_255":round(mae,3),
            "threshold":args.threshold,"status":"review-required" if mae>args.threshold else "pixel-similar-review-still-required",
            "note":"Pixel MAE cannot measure identity or narrative continuity."}
    print(json.dumps(report,indent=2))
    if args.output:
        p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(report,indent=2))

def build_parser():
    p=argparse.ArgumentParser(prog="gif-cinema",description="GPT Image GIF generator and film assembler")
    sub=p.add_subparsers(dest="command",required=True)
    g=sub.add_parser("generate");g.add_argument("prompt");g.add_argument("-o","--output",default="output/scene.gif")
    g.add_argument("--model",choices=MODELS,default=MODELS[0]);g.add_argument("--frames",type=int,default=9)
    g.add_argument("--duration",type=int,default=200);g.add_argument("--size",default="auto")
    g.add_argument("--quality",choices=["auto","low","medium","high","xhigh","max"],default="low")
    g.add_argument("--complexity",choices=["low","medium","high"],default="low");g.set_defaults(func=generate)
    f=sub.add_parser("film");f.add_argument("clips",nargs="+");f.add_argument("-o","--output",default="output/film.mp4")
    f.add_argument("--width",type=int,default=720);f.add_argument("--height",type=int,default=1280)
    f.add_argument("--fps",type=int,default=24);f.add_argument("--audio");f.set_defaults(func=film)
    i=sub.add_parser("inspect");i.add_argument("gif");i.add_argument("-o","--output");i.set_defaults(func=inspect)
    e=sub.add_parser("endpoints");e.add_argument("gif");e.add_argument("-o","--output",default="output/edge");e.set_defaults(func=endpoints)
    c=sub.add_parser("continuity");c.add_argument("previous");c.add_argument("next");c.add_argument("-o","--output")
    c.add_argument("--threshold",type=float,default=35.0);c.set_defaults(func=continuity)
    return p

def main():
    args=build_parser().parse_args()
    try:args.func(args)
    except (RuntimeError,ValueError,OSError,subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}",file=sys.stderr)
        raise SystemExit(1) from exc
