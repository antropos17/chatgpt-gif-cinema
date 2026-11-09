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
# Shared ingestion limits cover imported footage and decoded provider results.
# The pixel budget counts every retained, fully composited RGB drawing.
MAX_GIF_BYTES = 128 * 1024 * 1024
MAX_GIF_FRAME_PIXELS = 16 * 1024 * 1024
MAX_GIF_FRAMES = 1500
MAX_GIF_PIXEL_FRAMES = 160 * 1024 * 1024
MEDIA_TIMEOUT_SECONDS = 300
MODEL_ENV = "GIF_CINEMA_MODEL"


def default_model():
    """Model used when none is given: $GIF_CINEMA_MODEL, else the first known model."""
    model = os.environ.get(MODEL_ENV, "").strip() or MODELS[0]
    if model not in MODELS:
        raise ValueError(f"{MODEL_ENV}={model!r} is not supported; choose one of: {', '.join(MODELS)}")
    return model


class APIError(RuntimeError):
    """Safe status-only error; raw server bodies must never reach receipts."""
    def __init__(self, status):
        self.status = status
        super().__init__(f"OpenAI API HTTP {status}; response body omitted to protect credentials")

def read_gif_bytes(source):
    """Bound actual reads, including streams and files that grow during reading."""
    if hasattr(source, "read"):
        try:
            source.seek(0)
        except (AttributeError, io.UnsupportedOperation):
            pass  # Non-seekable streams are consumed from their current position.
        raw = source.read(MAX_GIF_BYTES + 1)
    else:
        with open(source, "rb") as stream:
            raw = stream.read(MAX_GIF_BYTES + 1)
    if len(raw) > MAX_GIF_BYTES:
        raise ValueError("GIF exceeds the 128 MiB input limit")
    return raw


def check_gif_limits(raw, *, max_frames=None, max_pixel_frames=None, fixed_canvas=False):
    """Scan GIF block sizes before Pillow can allocate disposal/composite images.

    This is a resource preflight, not a substitute for decoding every frame.
    In particular, a later image descriptor can grow a tiny logical screen.
    Callers may request tighter limits and reject canvas growth. The shared
    ingestion ceilings remain the upper bounds and defaults remain unchanged.
    """
    for name, value in (("max_frames", max_frames), ("max_pixel_frames", max_pixel_frames)):
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError(f"{name} must be a positive integer")
    frame_limit = MAX_GIF_FRAMES if max_frames is None else min(max_frames, MAX_GIF_FRAMES)
    pixel_limit = (MAX_GIF_PIXEL_FRAMES if max_pixel_frames is None
                   else min(max_pixel_frames, MAX_GIF_PIXEL_FRAMES))
    if raw[:6] not in (b"GIF87a", b"GIF89a"):
        raise ValueError("not a GIF")
    if len(raw) < 13:
        raise ValueError("Invalid or truncated GIF")
    width, height = int.from_bytes(raw[6:8], 'little'), int.from_bytes(raw[8:10], 'little')
    initial_size = (width, height)
    if not width or not height:
        raise ValueError("Invalid GIF dimensions")
    if width * height > MAX_GIF_FRAME_PIXELS:
        raise ValueError("GIF frame exceeds the 16 megapixel limit")
    canvas_width, canvas_height = width, height
    offset = 13 + ((3 << ((raw[10] & 7) + 1)) if raw[10] & 128 else 0)
    count, pixels = 0, 0

    def skip_blocks(position):
        while position < len(raw):
            size = raw[position]
            position += 1
            if size == 0:
                return position
            position += size
        raise ValueError("Invalid or truncated GIF data blocks")

    while offset < len(raw):
        marker = raw[offset]
        offset += 1
        if marker == 0x3B:  # Trailer.
            return {'frames': count, 'pixel_frames': pixels, 'width': width, 'height': height,
                    'canvas_expanded': (width, height) != initial_size}
        if marker == 0x21:
            if offset + 2 > len(raw):
                raise ValueError("Invalid or truncated GIF extension")
            label, size = raw[offset], raw[offset + 1]
            offset += 2
            if label == 0xFE:  # Comments may have an empty first data block.
                offset = skip_blocks(offset - 1)
                continue
            # Pillow consumes the first extension block separately, then more
            # blocks. An empty non-comment header can make it eat the following
            # image marker as a block length and expose hidden image descriptors.
            required = {0xF9: 4, 0x01: 12, 0xFF: 11}.get(label)
            if required is None or size != required or offset + size >= len(raw):
                raise ValueError("Invalid or unsupported GIF extension header")
            header = raw[offset:offset + size]
            offset += size
            if label == 0xF9:
                if raw[offset] != 0:
                    raise ValueError("Invalid GIF graphic control extension terminator")
                offset += 1
            elif label == 0xFF and header == b"NETSCAPE2.0":
                # Pillow also reads Netscape's loop block separately. Require
                # its complete fixed layout, including the single terminator,
                # so an empty loop block cannot desynchronize the decoder.
                if (offset + 5 > len(raw) or raw[offset:offset + 2] != b"\x03\x01"
                        or raw[offset + 4] != 0):
                    raise ValueError("Invalid GIF NETSCAPE loop extension")
                offset += 5
            else:
                offset = skip_blocks(offset)
            continue
        if marker != 0x2C or offset + 9 > len(raw):
            raise ValueError("Invalid or truncated GIF image descriptor")
        x, y, w, h = (int.from_bytes(raw[position:position + 2], 'little')
                      for position in range(offset, offset + 8, 2))
        if not w or not h:
            raise ValueError("Invalid GIF frame dimensions")
        if fixed_canvas and (x + w > canvas_width or y + h > canvas_height):
            raise ValueError("GIF frame exceeds the fixed logical canvas")
        width, height = max(width, x + w), max(height, y + h)
        if width * height > MAX_GIF_FRAME_PIXELS:
            raise ValueError("GIF frame exceeds the 16 megapixel limit")
        count += 1
        pixels += width * height
        if count > frame_limit:
            raise ValueError(f"GIF exceeds the {frame_limit} frame limit")
        if pixels > pixel_limit:
            raise ValueError(f"GIF exceeds the decoded pixel budget ({pixel_limit} pixels across frames)")
        flags = raw[offset + 8]
        offset += 9 + ((3 << ((flags & 7) + 1)) if flags & 128 else 0)
        offset = skip_blocks(offset + 1)  # Skip the LZW code size, then image data.
    raise ValueError("Invalid or truncated GIF; missing trailer")


def validate_gif(source):
    """Decode every accepted frame within explicit file, frame and pixel budgets."""
    from PIL import Image, ImageSequence
    try:
        raw = read_gif_bytes(source)
        check_gif_limits(raw)
        with Image.open(io.BytesIO(raw)) as im:
            if im.format != "GIF":
                raise ValueError("not a GIF")
            frames, durations = [], []
            pixels = 0
            loop = im.info.get("loop")
            for frame in ImageSequence.Iterator(im):
                # Check before convert/load allocates this composited drawing.
                # Later GIF descriptors can expand the logical canvas.
                frame_pixels = frame.width * frame.height
                if frame_pixels > MAX_GIF_FRAME_PIXELS:
                    raise ValueError("GIF frame exceeds the 16 megapixel limit")
                if len(frames) >= MAX_GIF_FRAMES:
                    raise ValueError("GIF exceeds the 1500 frame limit")
                if pixels + frame_pixels > MAX_GIF_PIXEL_FRAMES:
                    raise ValueError("GIF exceeds the decoded pixel budget (160 megapixels across frames)")
                duration = int(frame.info.get("duration", 0))
                if duration < 20:
                    raise ValueError("GIF frames must have a duration of at least 20 ms")
                frames.append(frame.convert("RGB").copy())
                durations.append(duration)
                pixels += frame_pixels
            if len(frames) < 2:
                raise ValueError("GIF must contain at least two frames")
            return frames, durations, loop
    except Image.DecompressionBombError as exc:
        raise ValueError("GIF exceeds the decoder's safe image dimensions") from exc
    except (OSError, EOFError) as exc:
        raise ValueError("Invalid or truncated GIF") from exc


def run_media(command):
    """Bound encoder/probe work and never allow subprocesses to wait for stdin."""
    try:
        return subprocess.run(command, check=True, capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=MEDIA_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        tool = Path(command[0]).name
        raise RuntimeError(f"{tool} timed out after {MEDIA_TIMEOUT_SECONDS} seconds; output was not published") from None

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

def generation_action(out, payload, *, resume=False, force=False):
    """Validate the current output state for both planning and locked execution."""
    meta = out.with_suffix(".json")
    if os.path.lexists(out) or os.path.lexists(meta):
        if resume:
            if not out.is_file() or not meta.is_file():
                raise ValueError("Cannot resume: GIF and metadata are both required")
            raw = read_gif_bytes(out)
            saved = json.loads(meta.read_text(encoding="utf-8"))
            validate_gif(io.BytesIO(raw))
            if not isinstance(saved, dict) or saved.get("parameters") != payload or saved.get("sha256") != hashlib.sha256(raw).hexdigest():
                raise ValueError("Cannot resume: parameters or GIF checksum do not match")
            return "reuse"
        if not force:
            raise ValueError("Output or metadata already exists; use --resume to reuse or --force to regenerate")
    if out.is_dir() or meta.is_dir():
        raise ValueError("Output and metadata must be files")
    return "generate"


def generate(args):
    payload = make_payload(args.prompt,args.model or default_model(),args.frames,args.duration,args.size,args.quality,args.complexity)
    out = Path(args.output)
    if out.suffix.lower() != ".gif":
        raise ValueError("Output must have a .gif extension")
    force = getattr(args, "force", False)
    resume = getattr(args, "resume", False)
    if getattr(args, "dry_run", False):
        # Offline preview uses the same output checks, without locks or writes.
        action = generation_action(out, payload, resume=resume, force=force)
        plan = {"mode": "dry-run", "api_calls": 0, "would_send_api_calls": int(action == "generate"),
                "action": action, "output": str(out), "output_exists": out.exists(), "payload": payload,
                "cost": "no new API calls; reuses a verified GIF" if action == "reuse" else
                        "unknown; rerun without --dry-run to send one paid request",
                "note": "Execution rechecks the output under its lock; this preview writes nothing."}
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return plan
    out.parent.mkdir(parents=True,exist_ok=True)
    meta = out.with_suffix(".json")
    with output_lock(out):
        if generation_action(out, payload, resume=resume, force=force) == "reuse":
            print(f"Reused verified GIF: {out} (no API request)")
            return
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
    from .audio import MAX_AUDIO_SECONDS, prepare_audio
    from .doctor import inspect_tool, require_film_capabilities
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required: https://ffmpeg.org/download.html")
    if args.width <= 0 or args.height <= 0 or args.width % 2 or args.height % 2 or args.fps <= 0:
        raise ValueError("Film dimensions must be positive even integers and FPS must be positive")
    clips=[Path(p).resolve() for p in args.clips]
    clip_frames = []
    for clip in clips:
        _, durations, _ = validate_gif(clip)
        clip_frames.append(max(1, round(sum(durations) * args.fps / 1000)))
    out=Path(args.output).resolve()
    if out.suffix.lower() != ".mp4":
        raise ValueError("Film output must have a .mp4 extension")
    if out in clips or (args.audio and out == Path(args.audio).resolve()):
        raise ValueError("Output must not replace an input file")
    force = getattr(args, "force", False)
    if out.exists() and (not force or not out.is_file()):
        raise ValueError("Film output already exists; use --force to replace it")
    require_film_capabilities(audio=bool(args.audio))
    audio_path = Path(args.audio).resolve() if args.audio else None
    if audio_path is not None:
        if not audio_path.exists():
            raise ValueError(f"audio not found: {args.audio}")
        if sum(clip_frames) / args.fps > MAX_AUDIO_SECONDS:
            raise ValueError("Films with audio must be at most 3600 seconds")
        if not inspect_tool("ffprobe")["available"]:
            raise RuntimeError("Working ffprobe is required for films with audio; no output was published")
    # Reuse render's strict bounded input contract, including its snapshot.
    # Silent assembly does not gain an ffprobe dependency or new media limits.
    with prepare_audio(audio_path) as prepared:
        out.parent.mkdir(parents=True, exist_ok=True)
        _encode_film(args, clips, clip_frames, out, force, prepared["path"] if prepared else None)
    print(f"Created movie: {out}")


def _encode_film(args, clips, clip_frames, out, force, audio_path):
    from .audio import verify_film_audio
    command=["ffmpeg","-hide_banner","-loglevel","error","-nostdin","-y"]
    for clip in clips:
        command+=["-ignore_loop","1","-i",str(clip)]
    if audio_path is not None:
        command+=["-i",str(audio_path)]
    filters=[]
    for i in range(len(clips)):
        # Pad before resampling so FFmpeg cannot drop the final GIF delay.
        # Trim to an explicit nearest-frame duration (ties to even), at least one.
        filters.append(f"[{i}:v]tpad=stop_mode=clone:stop=-1,fps={args.fps},trim=end_frame={clip_frames[i]},scale={args.width}:{args.height}:force_original_aspect_ratio=decrease,pad={args.width}:{args.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{i}]")
    filters.append("".join(f"[v{i}]" for i in range(len(clips)))+f"concat=n={len(clips)}:v=1:a=0[outv]")
    command+=["-filter_complex",";".join(filters),"-map","[outv]"]
    if audio_path is not None:command+=["-map",f"{len(clips)}:a:0","-af","apad","-shortest","-c:a","aac"]
    with output_lock(out):
        fd, name = tempfile.mkstemp(dir=out.parent, suffix=".mp4")
        os.close(fd)
        staged = Path(name)
        try:
            command+=["-r",str(args.fps),"-c:v","libx264","-pix_fmt","yuv420p","-movflags","+faststart",str(staged)]
            run_media(command)
            if staged.stat().st_size == 0:
                raise RuntimeError("FFmpeg produced an empty movie")
            if audio_path is not None:
                verify_film_audio(staged, sum(clip_frames) / args.fps)
            publish_file(staged, out, force)
        finally:
            staged.unlink(missing_ok=True)

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
    from .continuity import cut_context
    a,ad,_=gif_frames(args.previous);b,bd,_=gif_frames(args.next)
    context = cut_context(a, ad, b, bd)
    mae = context["cut_pixel_mae_0_255"]
    report={"previous":str(args.previous),"next":str(args.next),"pixel_mae_0_255":round(mae,3),
            "threshold":args.threshold,"status":"review-required" if mae>args.threshold else "pixel-similar-review-still-required",
            "note":"Pixel MAE cannot measure identity or narrative continuity.", "cut_context":context}
    print(json.dumps(report,indent=2))
    if args.output:
        save_report(args.output, report, [args.previous, args.next], getattr(args, "force", False))

def build_parser():
    p=argparse.ArgumentParser(prog="gif-cinema",description="GPT Image GIF generator and film assembler")
    sub=p.add_subparsers(dest="command",required=True)
    from .render import add_parser
    from .doctor import add_parser as add_doctor_parser
    from .sprites import add_parser as add_sprites_parser
    add_parser(sub)
    add_doctor_parser(sub)
    add_sprites_parser(sub)
    from .motion import add_parser as add_motion_parser
    add_motion_parser(sub)
    g=sub.add_parser("generate");g.add_argument("prompt");g.add_argument("-o","--output",default="output/scene.gif")
    reuse = g.add_mutually_exclusive_group()
    reuse.add_argument("--resume",action="store_true",help="Reuse an existing GIF with matching parameters and checksum")
    reuse.add_argument("--force",action="store_true",help="Replace existing output; makes a new paid API request")
    g.add_argument("--dry-run",action="store_true",help="Print the request that would be sent; no API call, key or writes")
    g.add_argument("--model",choices=MODELS,default=None,help=f"Default: ${MODEL_ENV} or {MODELS[0]}");g.add_argument("--frames",type=int,default=9)
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
    except (RuntimeError,ValueError,OSError,subprocess.SubprocessError) as exc:
        print(f"Error: {exc}",file=sys.stderr)
        raise SystemExit(1) from exc
