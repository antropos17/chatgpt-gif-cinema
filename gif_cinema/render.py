"""Script-driven rendering. Planning is offline; execution is explicitly opted in."""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from PIL import Image, ImageChops, ImageDraw, ImageStat

from . import cli

VERSION = 1


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def save(path, value):
    cli.write_result(path, encoded(value), force=True)


def text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 16000:
        raise ValueError(f"{label} must be nonempty text of at most 16000 characters")
    return value


def integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer in {low}..{high}")
    return value


def fields(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f"{label}: invalid object or unknown fields")


def load_script(path, args):
    """Validate the entire script and every local input before any API request."""
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Script exceeds 1 MiB")
    script = json.loads(path.read_text(encoding="utf-8-sig"))
    fields(script, {"schema_version", "title", "ratio", "style_bible", "shots", "width", "height", "fps", "audio", "audio_notes"}, "script")
    if type(script.get("schema_version")) is not int or script["schema_version"] != VERSION:
        raise ValueError("schema_version must be 1")
    text(script.get("title"), "title")
    text(script.get("style_bible"), "style_bible")
    ratio = script.get("ratio")
    if not isinstance(ratio, str) or not re.fullmatch(r"[1-9][0-9]?:[1-9][0-9]?", ratio):
        raise ValueError("ratio must be WIDTH:HEIGHT, for example 1:1 or 9:16")
    rw, rh = map(int, ratio.split(":"))
    width = args.width if args.width is not None else script.get("width", 512)
    integer(width, "width", 2, 4096)
    height = args.height if args.height is not None else script.get("height", round(width * rh / rw / 2) * 2)
    fps = args.fps if args.fps is not None else script.get("fps", 25)
    integer(width, "width", 2, 4096); integer(height, "height", 2, 4096)
    integer(fps, "fps", 1, 120)
    if width % 2 or height % 2 or abs(width / height - rw / rh) > 0.01:
        raise ValueError("Dimensions must be even and match the script ratio")
    script.update(width=width, height=height, fps=fps)
    if "audio_notes" in script:
        text(script["audio_notes"], "audio_notes")
    if script.get("audio"):
        audio = (path.parent / text(script["audio"], "audio")).resolve()
        if not audio.is_file():
            raise ValueError("Audio file does not exist")
        script["audio_path"] = audio
    shots = script.get("shots")
    if not isinstance(shots, list) or not 1 <= len(shots) <= 64:
        raise ValueError("shots must contain 1..64 entries")
    seen = set()
    for shot in shots:
        fields(shot, {"id", "prompt", "source", "frames", "duration_ms", "transition", "first_frame_target", "last_frame_target", "audio_notes", "caption", "model", "size", "quality", "complexity"}, "shot")
        sid = shot.get("id")
        if not isinstance(sid, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}", sid) or sid.lower() in seen:
            raise ValueError("Shot IDs must be unique safe identifiers (case-insensitive)")
        seen.add(sid.lower())
        if shot.get("transition", "cut") != "cut":
            raise ValueError("Only hard-cut transitions are supported")
        for key in ("first_frame_target", "last_frame_target"):
            text(shot.get(key), key)
        for key in ("audio_notes", "caption"):
            if key in shot:
                text(shot[key], key)
        if ("source" in shot) == ("prompt" in shot):
            raise ValueError("Each shot needs exactly one of source or prompt")
        shot["transition"] = "cut"
        if "source" in shot:
            if set(shot) & {"frames", "duration_ms", "model", "size", "quality", "complexity"}:
                raise ValueError("Imported shots use their actual timing, not generation parameters")
            source = (path.parent / text(shot["source"], "source")).resolve()
            frames, durations, _ = cli.validate_gif(source)
            shot["source_path"] = source
            shot["source_sha256"] = digest(source.read_bytes())
            shot["expected_ms"] = sum(durations)
            basis = {"source_sha256": shot["source_sha256"]}
        else:
            prompt = text(shot["prompt"], "prompt")
            count = integer(shot.get("frames", 9), "frames", 2, 16)
            duration = integer(shot.get("duration_ms", 200), "duration_ms", 20, 2000)
            if duration % 10:
                raise ValueError("duration_ms must be a multiple of 10")
            quality = shot.get("quality", "low")
            complexity = shot.get("complexity", "low")
            if quality not in {"auto", "low", "medium", "high", "xhigh", "max"} or complexity not in {"low", "medium", "high"}:
                raise ValueError("Invalid quality or complexity")
            full_prompt = (f"Style and character bible: {script['style_bible']}\n"
                           f"Shot {sid}: {prompt}\nStart: {shot['first_frame_target']}\n"
                           f"End: {shot['last_frame_target']}\nOne continuous shot. No captions or text.")
            shot["payload"] = cli.make_payload(full_prompt, shot.get("model", "gpt-image-2.6-flare"), count, duration, shot.get("size", "auto"), quality, complexity)
            shot["expected_ms"] = count * duration
            basis = shot["payload"]
        shot["fingerprint"] = digest(encoded(basis))
    return script


def local_path(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Manifest path escapes project directory")
    return path


def cached(root, record, shot):
    if not record or record.get("fingerprint") != shot["fingerprint"]:
        return False
    path = local_path(root, record["output"])
    if not path.is_file() or digest(path.read_bytes()) != record.get("sha256"):
        raise ValueError(f"Saved shot {shot['id']} is missing or changed; use a new project directory")
    cli.validate_gif(path)
    return True


def probe(path, width, height, expected_seconds, fps, shots):
    command = ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height,duration,nb_read_frames", "-of", "json", str(path)]
    result = subprocess.run(command, capture_output=True, check=True)
    info = json.loads(result.stdout)["streams"][0]
    actual = float(info["duration"])
    count = int(info["nb_read_frames"])
    if (info["codec_name"] != "h264" or info["width"] != width or info["height"] != height
            or count < 1 or not math.isfinite(actual) or abs(actual - expected_seconds) > (shots + 1) / fps):
        raise RuntimeError("Encoded film failed codec, dimensions or duration verification")
    # Decode all frames, not just the container metadata.
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"], check=True, capture_output=True)
    return info


def diagnostics(root, script, records):
    sheet = Image.new("RGB", (480, len(records) * 205), "#181818")
    draw = ImageDraw.Draw(sheet)
    joins, previous = [], None
    for index, (shot, record) in enumerate(zip(script["shots"], records)):
        frames, _, _ = cli.validate_gif(local_path(root, record["output"]))
        for label, frame, x in (("first", frames[0], 0), ("last", frames[-1], 240)):
            output = root / f"{shot['id']}-{label}.png"
            data = io.BytesIO(); frame.save(data, format="PNG")
            cli.write_result(output, data.getvalue(), force=True)
            thumbnail = frame.copy(); thumbnail.thumbnail((238, 180))
            sheet.paste(thumbnail, (x, index * 205))
            draw.text((x + 4, index * 205 + 183), f"{shot['id']} {label}", fill="white")
        if previous is not None:
            diff = ImageChops.difference(previous.resize((128, 128)), frames[0].resize((128, 128)))
            joins.append({"previous": script["shots"][index - 1]["id"], "next": shot["id"],
                          "pixel_mae_0_255": round(sum(ImageStat.Stat(diff).mean) / 3, 3),
                          "previous_end_target": script["shots"][index - 1]["last_frame_target"],
                          "next_start_target": shot["first_frame_target"], "status": "human-review-required"})
        previous = frames[-1]
    data = io.BytesIO(); sheet.save(data, format="PNG")
    cli.write_result(root / "contact-sheet.png", data.getvalue(), force=True)
    report = {"status": "human-review-required", "note": "Pixel MAE cannot measure identity, motion or narrative continuity. Targets are instructions, not verified observations.", "joins": joins}
    save(root / "continuity-report.json", report)


def safe_error(exc):
    if isinstance(exc, cli.APIError):
        return f"API HTTP {exc.status}"
    return {ValueError: "Validation failed", OSError: "Local file operation failed"}.get(type(exc), "Operation failed; provider and process details omitted")


def safe_usage(usage):
    """Keep numeric accounting only; never persist arbitrary provider text."""
    if not isinstance(usage, dict):
        return None
    result = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        if type(usage.get(key)) is int and usage[key] >= 0:
            result[key] = usage[key]
    return result or None


def run(args):
    script_path = Path(args.script).resolve()
    script = load_script(script_path, args)
    integer(args.max_api_calls, "max-api-calls", 0, 100)
    integer(args.retries, "retries", 0, 5)
    root = Path(args.out).resolve()
    manifest_path = root / "render-manifest.json"
    manifest = {"schema_version": VERSION, "shots": {}, "attempts": [], "runs": []}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != VERSION or not all(isinstance(manifest.get(k), t) for k, t in (("shots", dict), ("attempts", list), ("runs", list))):
            raise ValueError("Invalid render manifest")
    elif root.exists() and any(root.iterdir()):
        raise ValueError("Output directory is not empty and has no render manifest; use a new directory")
    forced = set(args.force_shot)
    if forced - {s["id"] for s in script["shots"]}:
        raise ValueError("Unknown force-shot ID")
    if forced & {s["id"] for s in script["shots"] if "source" in s}:
        raise ValueError("force-shot applies only to prompt-based shots, never imported originals")
    actions = []
    for shot in script["shots"]:
        record = manifest["shots"].get(shot["id"])
        force = "payload" in shot and (args.force or shot["id"] in forced)
        reuse = cached(root, record, shot) if record and not force else False
        if record and "payload" in shot and not reuse and not force:
            raise ValueError(f"Shot {shot['id']} changed; explicitly use --force-shot {shot['id']} or a new directory")
        if "source_path" in shot and shot["source_path"].is_relative_to(root):
            raise ValueError("Imported sources must live outside the render output directory")
        if not reuse and "payload" in shot and not force and any(a.get("shot") == shot["id"] and a.get("status") == "started" for a in manifest["attempts"]):
            raise ValueError(f"Shot {shot['id']} has an interrupted request of unknown cost; review before using --force-shot")
        actions.append("reuse" if reuse else "import" if "source" in shot else "generate")
    plan = {"title": script["title"], "mode": "execute" if args.execute else "dry-run", "minimum_new_api_calls": actions.count("generate"),
            "max_api_calls_including_retries": args.max_api_calls, "cost": "unknown; usage is not a currency quote",
            "shots": [{"id": s["id"], "action": a, "expected_duration_ms": s["expected_ms"]} for s, a in zip(script["shots"], actions)]}
    print(json.dumps(plan, indent=2), flush=True)
    if not args.execute:
        return plan
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is required before execution; no API requests made")
    if actions.count("generate") and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY to execute generated shots; imported shots do not require it")
    if script_path.is_relative_to(root):
        raise ValueError("Script must live outside the render output directory")
    root.mkdir(parents=True, exist_ok=True)
    with cli.output_lock(manifest_path):
        # Do not execute a plan made against an older project revision.
        if manifest_path.exists() and json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Project changed since planning; rerun to refresh the plan")
        run_record = {"status": "running", "api_calls": 0, "generated": 0, "imported": 0, "skipped": 0, "max_api_calls": args.max_api_calls}
        manifest["runs"].append(run_record)
        manifest["title"] = script["title"]
        manifest["script_sha256"] = digest(script_path.read_bytes())
        save(manifest_path, manifest)
        records = []
        try:
            for shot, action in zip(script["shots"], actions):
                sid = shot["id"]
                if action == "reuse":
                    run_record["skipped"] += 1
                    records.append(manifest["shots"][sid])
                    continue
                if action == "import":
                    raw = shot["source_path"].read_bytes()
                    if digest(raw) != shot["source_sha256"]:
                        raise ValueError("Imported source changed during rendering")
                    usage, seconds = None, 0
                else:
                    for retry in range(args.retries + 1):
                        if run_record["api_calls"] >= args.max_api_calls:
                            raise RuntimeError("API call budget exhausted; completed shots are saved")
                        attempt = {"shot": sid, "status": "started", "model": shot["payload"]["model"], "parameters": shot["payload"], "prompt_sha256": digest(shot["payload"]["prompt"].encode())}
                        manifest["attempts"].append(attempt)
                        run_record["api_calls"] += 1
                        save(manifest_path, manifest)  # Count BEFORE sending, including retries.
                        start = time.monotonic()
                        try:
                            raw, usage = cli.request_gif(shot["payload"], os.environ["OPENAI_API_KEY"])
                            usage = safe_usage(usage)
                            cli.validate_gif(io.BytesIO(raw))
                        except Exception as exc:
                            attempt.update(status="failed", error=safe_error(exc), seconds=round(time.monotonic() - start, 3))
                            save(manifest_path, manifest)
                            transient = isinstance(exc, cli.APIError) and (exc.status == 429 or 500 <= exc.status < 600)
                            if not transient or retry == args.retries or run_record["api_calls"] >= args.max_api_calls:
                                raise RuntimeError(f"Shot {sid}: {safe_error(exc)}; completed shots are saved") from None
                            time.sleep(min(2 ** retry, 8))
                            continue
                        seconds = round(time.monotonic() - start, 3)
                        # The started status remains durable until the file is published.
                        break
                frames, durations, _ = cli.validate_gif(io.BytesIO(raw))
                sha = digest(raw)
                filename = f"{sid}-{shot['fingerprint'][:12]}-{sha[:12]}.gif"
                target = local_path(root, filename)
                if target.exists():
                    if digest(target.read_bytes()) != sha:
                        raise ValueError("Shot output collision")
                else:
                    cli.write_result(target, raw)
                record = {"fingerprint": shot["fingerprint"], "sha256": sha, "output": filename, "frames": len(frames),
                          "duration_ms": sum(durations), "frame_durations_ms": durations, "seconds": seconds,
                          "usage": usage, "origin": "imported" if action == "import" else "generated", "status": "verified-gif"}
                if action == "generate":
                    record["parameters"] = shot["payload"]
                    attempt.update(status="succeeded", seconds=seconds, usage=usage, output=filename)
                else:
                    record["source_sha256"] = shot["source_sha256"]
                manifest["shots"][sid] = record
                run_record["generated" if action == "generate" else "imported"] += 1
                save(manifest_path, manifest)
                records.append(record)
            diagnostics(root, script, records)
            movie_fingerprint = digest(encoded({"shots": [r["sha256"] for r in records], "width": script["width"], "height": script["height"], "fps": script["fps"], "audio": digest(script["audio_path"].read_bytes()) if script.get("audio_path") else None}))
            old_film = manifest.get("film", {})
            film_path = root / "film.mp4"
            expected = sum(r["duration_ms"] for r in records) / 1000
            if old_film.get("fingerprint") == movie_fingerprint and film_path.exists() and digest(film_path.read_bytes()) == old_film.get("sha256"):
                info = probe(film_path, script["width"], script["height"], expected, script["fps"], len(records))
            else:
                # Stage the entire movie and verify before replacing an accepted export.
                with tempfile.TemporaryDirectory(dir=root, prefix="encode-") as staging:
                    staged = Path(staging) / "film.mp4"
                    cli.film(argparse.Namespace(clips=[local_path(root, r["output"]) for r in records], output=staged,
                                               width=script["width"], height=script["height"], fps=script["fps"],
                                               audio=script.get("audio_path"), force=False))
                    info = probe(staged, script["width"], script["height"], expected, script["fps"], len(records))
                    if film_path.exists() and (not old_film or digest(film_path.read_bytes()) != old_film.get("sha256")):
                        raise ValueError("Existing film is untracked or changed; refusing to overwrite")
                    if film_path.exists():
                        archive = root / f"film-{old_film['sha256'][:16]}.mp4"
                        if not archive.exists():
                            cli.write_result(archive, film_path.read_bytes())
                    cli.write_result(film_path, staged.read_bytes(), force=film_path.exists())
                manifest["film"] = {"fingerprint": movie_fingerprint, "sha256": digest(film_path.read_bytes()), "output": "film.mp4", "probe": info}
            save(root / "film-inspect.json", info)
            # Captions are a separate, editable SRT; they do not alter source GIFs.
            clock, subtitles = 0, []
            def stamp(ms):
                return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
            for shot, record in zip(script["shots"], records):
                end = clock + round(record["duration_ms"] * script["fps"] / 1000) * 1000 / script["fps"]
                if shot.get("caption"):
                    subtitles.append(f"{len(subtitles)+1}\n{stamp(round(clock))} --> {stamp(round(end))}\n{shot['caption']}\n")
                clock = end
            cli.write_result(root / "captions.srt", "\n".join(subtitles).encode("utf-8"), force=True)
            run_record.update(status="complete", film_seconds=float(info["duration"]), verification="decoded-h264; narrative-human-review-required")
            save(manifest_path, manifest)
            receipt = {**run_record, "film": str(film_path), "usage_from_completed_shots_including_reused": [r["usage"] for r in records if r.get("usage")],
                       "cost": "not calculated; imported shots made no new API calls", "continuity": "human-review-required"}
            save(root / "receipt.json", receipt)
            print(json.dumps(receipt, indent=2))
            return receipt
        except Exception as exc:
            run_record.update(status="incomplete", error=safe_error(exc))
            save(manifest_path, manifest)
            raise


def add_parser(sub):
    parser = sub.add_parser("render", help="Plan or execute a resumable film script")
    parser.add_argument("script")
    parser.add_argument("--out", default="output/film-project")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Offline plan (default); no writes or API calls")
    mode.add_argument("--execute", action="store_true", help="Execute imports and explicitly allow bounded API generation")
    parser.add_argument("--max-api-calls", type=int, default=3)
    parser.add_argument("--retries", type=int, default=2, help="Only retry HTTP 429/5xx, within total call cap")
    parser.add_argument("--force", action="store_true", help="Regenerate ALL prompt-based shots; may incur charges")
    parser.add_argument("--force-shot", action="append", default=[], help="Regenerate one named shot; retain other accepted shots")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--fps", type=int)
    parser.set_defaults(func=run)
