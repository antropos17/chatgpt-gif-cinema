"""OpenAI GIF client and FFmpeg film assembler."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tempfile
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.openai.com/v1/images/generations"
MODELS = ("gpt-image-2.6-flare", "gpt-image-2.6-sunburst")


class APIError(RuntimeError):
    """Safe status-only error; raw server bodies must never reach receipts."""
    def __init__(self, status):
        self.status = status
        super().__init__(f"OpenAI API HTTP {status}; response body omitted to protect credentials")

def validate_gif(source):
    """Decode every frame before accepting an animated GIF."""
    from PIL import Image, ImageSequence
    try:
        with Image.open(source) as im:
            if im.format != "GIF":
                raise ValueError("not a GIF")
            frames, durations = [], []
            loop = im.info.get("loop")
            for frame in ImageSequence.Iterator(im):
                duration = int(frame.info.get("duration", 0))
                if duration < 20:
                    raise ValueError("GIF frames must have a duration of at least 20 ms")
                frames.append(frame.convert("RGB").copy())
                durations.append(duration)
            if len(frames) < 2:
                raise ValueError("GIF must contain at least two frames")
            return frames, durations, loop
    except (OSError, EOFError) as exc:
        raise ValueError("Invalid or truncated GIF") from exc

@contextmanager
def output_lock(path):
    """Prevent concurrent CLI calls from paying for the same output."""
    lock = path.with_name(path.name + ".lock")
    try:
        handle = lock.open("x")
    except FileExistsError as exc:
        raise ValueError(f"Output is busy: {path}. Check the other process before removing {lock}.") from exc
    try:
        with handle:
            yield
    finally:
        lock.unlink()

def publish_file(staged, target, force=False):
    if force:
        os.replace(staged, target)
    else:
        # Atomic no-clobber publication, including a file created during the run.
        os.link(staged, target)

def write_result(path, raw, force=False):
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        publish_file(staged, path, force)
    finally:
        staged.unlink(missing_ok=True)

def make_payload(prompt, model="gpt-image-2.6-flare", frames=9, duration=200, size="auto", quality="low", complexity="low"):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must not be empty")
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
        raise APIError(exc.code) from exc
    except URLError as exc:
        raise RuntimeError("OpenAI network request failed; check connectivity") from exc
    except (TimeoutError, OSError) as exc:
        raise RuntimeError("OpenAI network request failed or timed out; no automatic retry was made") from exc
    try:
        raw = base64.b64decode(body["data"][0]["b64_json"], validate=True)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise RuntimeError("Missing/invalid b64_json in image response") from exc
    validate_gif(io.BytesIO(raw))
    return raw, body.get("usage")

def generate(args):
    payload = make_payload(args.prompt,args.model,args.frames,args.duration,args.size,args.quality,args.complexity)
    out = Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    if out.suffix.lower() != ".gif":
        raise ValueError("Output must have a .gif extension")
    meta = out.with_suffix(".json")
    force = getattr(args, "force", False)
    with output_lock(out):
        if out.exists() or meta.exists():
            if getattr(args, "resume", False):
                if not out.is_file() or not meta.is_file():
                    raise ValueError("Cannot resume: GIF and metadata are both required")
                raw = out.read_bytes()
                saved = json.loads(meta.read_text(encoding="utf-8"))
                validate_gif(io.BytesIO(raw))
                if not isinstance(saved, dict) or saved.get("parameters") != payload or saved.get("sha256") != hashlib.sha256(raw).hexdigest():
                    raise ValueError("Cannot resume: parameters or GIF checksum do not match")
                print(f"Reused verified GIF: {out} (no API request)")
                return
            if not force:
                raise ValueError("Output or metadata already exists; use --resume to reuse or --force to regenerate")
        if out.is_dir() or meta.is_dir():
            raise ValueError("Output and metadata must be files")
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("Set OPENAI_API_KEY in your environment. Never commit it.")
        start = time.monotonic()
        raw,usage = request_gif(payload,key)
        frames, durations, _ = validate_gif(io.BytesIO(raw))
        metadata={"prompt":args.prompt,"parameters":payload,"output":str(out),
                  "seconds":round(time.monotonic()-start,2),"usage":usage,
                  "sha256":hashlib.sha256(raw).hexdigest(),
                  "actual_frames":len(frames),"actual_duration_ms":sum(durations)}
        write_result(out, raw, force)
        write_result(meta, json.dumps(metadata,ensure_ascii=False,indent=2).encode("utf-8"), force)
        print(f"Created {out} ({len(raw):,} bytes)")

def film(args):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required: https://ffmpeg.org/download.html")
    if args.width <= 0 or args.height <= 0 or args.width % 2 or args.height % 2 or args.fps <= 0:
        raise ValueError("Film dimensions must be positive even integers and FPS must be positive")
    clips=[Path(p).resolve() for p in args.clips]
    for clip in clips:
        validate_gif(clip)
    out=Path(args.output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    if out.suffix.lower() != ".mp4":
        raise ValueError("Film output must have a .mp4 extension")
    if out in clips or (args.audio and out == Path(args.audio).resolve()):
        raise ValueError("Output must not replace an input file")
    force = getattr(args, "force", False)
    if out.exists() and (not force or not out.is_file()):
        raise ValueError("Film output already exists; use --force to replace it")
    command=["ffmpeg","-hide_banner","-loglevel","error","-nostdin","-y"]
    for clip in clips:
        command+=["-ignore_loop","1","-i",str(clip)]
    if args.audio:
        if not Path(args.audio).is_file():raise ValueError(f"audio not found: {args.audio}")
        command+=["-i",str(Path(args.audio).resolve())]
    filters=[]
    for i in range(len(clips)):
        filters.append(f"[{i}:v]fps={args.fps},scale={args.width}:{args.height}:force_original_aspect_ratio=decrease,pad={args.width}:{args.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{i}]")
    filters.append("".join(f"[v{i}]" for i in range(len(clips)))+f"concat=n={len(clips)}:v=1:a=0[outv]")
    command+=["-filter_complex",";".join(filters),"-map","[outv]"]
    if args.audio:command+=["-map",f"{len(clips)}:a:0","-af","apad","-shortest","-c:a","aac"]
    with output_lock(out):
        fd, name = tempfile.mkstemp(dir=out.parent, suffix=".mp4")
        os.close(fd)
        staged = Path(name)
        try:
            command+=["-c:v","libx264","-pix_fmt","yuv420p","-movflags","+faststart",str(staged)]
            subprocess.run(command,check=True)
            if staged.stat().st_size == 0:
                raise RuntimeError("FFmpeg produced an empty movie")
            publish_file(staged, out, force)
        finally:
            staged.unlink(missing_ok=True)
    print(f"Created movie: {out}")

def gif_frames(path):
    return validate_gif(path)

def inspect(args):
    frames,durations,loop=gif_frames(args.gif)
    data={"file":str(args.gif),"frames":len(frames),"width":frames[0].width,"height":frames[0].height,
          "duration_ms":sum(durations),"frame_durations_ms":durations,"loop":loop}
    print(json.dumps(data,indent=2))
    if args.output:
        save_report(args.output, data, [args.gif], getattr(args, "force", False))

def save_report(output, data, inputs, force=False):
    p = Path(output)
    if p.resolve() in [Path(item).resolve() for item in inputs]:
        raise ValueError("Report output must not replace an input file")
    p.parent.mkdir(parents=True, exist_ok=True)
    write_result(p, json.dumps(data, indent=2).encode("utf-8"), force)

def endpoints(args):
    frames,_,_=gif_frames(args.gif)
    p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True)
    outputs = [Path(str(p)+"-first.png"), Path(str(p)+"-last.png")]
    force = getattr(args, "force", False)
    if not force and any(path.exists() for path in outputs):
        raise ValueError("Endpoint output already exists; use --force to replace it")
    for frame, path in zip([frames[0], frames[-1]], outputs):
        data = io.BytesIO()
        frame.save(data, format="PNG")
        write_result(path, data.getvalue(), force)

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
        save_report(args.output, report, [args.previous, args.next], getattr(args, "force", False))

def build_parser():
    p=argparse.ArgumentParser(prog="gif-cinema",description="GPT Image GIF generator and film assembler")
    sub=p.add_subparsers(dest="command",required=True)
    from .render import add_parser
    add_parser(sub)
    g=sub.add_parser("generate");g.add_argument("prompt");g.add_argument("-o","--output",default="output/scene.gif")
    reuse = g.add_mutually_exclusive_group()
    reuse.add_argument("--resume",action="store_true",help="Reuse an existing GIF with matching parameters and checksum")
    reuse.add_argument("--force",action="store_true",help="Replace existing output; makes a new paid API request")
    g.add_argument("--model",choices=MODELS,default=MODELS[0]);g.add_argument("--frames",type=int,default=9)
    g.add_argument("--duration",type=int,default=200);g.add_argument("--size",default="auto")
    g.add_argument("--quality",choices=["auto","low","medium","high","xhigh","max"],default="low")
    g.add_argument("--complexity",choices=["low","medium","high"],default="low");g.set_defaults(func=generate)
    f=sub.add_parser("film");f.add_argument("clips",nargs="+");f.add_argument("-o","--output",default="output/film.mp4")
    f.add_argument("--force",action="store_true",help="Replace an existing film after successful encoding")
    f.add_argument("--width",type=int,default=720);f.add_argument("--height",type=int,default=1280)
    f.add_argument("--fps",type=int,default=24);f.add_argument("--audio");f.set_defaults(func=film)
    i=sub.add_parser("inspect");i.add_argument("gif");i.add_argument("-o","--output");i.set_defaults(func=inspect)
    e=sub.add_parser("endpoints");e.add_argument("gif");e.add_argument("-o","--output",default="output/edge");e.set_defaults(func=endpoints)
    c=sub.add_parser("continuity");c.add_argument("previous");c.add_argument("next");c.add_argument("-o","--output")
    c.add_argument("--threshold",type=float,default=35.0);c.set_defaults(func=continuity)
    for output_parser in (i, e, c):
        output_parser.add_argument("--force", action="store_true", help="Replace existing report or endpoint output")
    return p

def main():
    args=build_parser().parse_args()
    try:args.func(args)
    except (RuntimeError,ValueError,OSError,subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}",file=sys.stderr)
        raise SystemExit(1) from exc
