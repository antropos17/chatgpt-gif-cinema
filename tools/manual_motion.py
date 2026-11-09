"""Manual direct-OpenAI pilot: offline plan, fail-closed cost gate, frame review."""
import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from PIL import Image, ImageDraw

from gif_cinema import cli, render

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples/motion/chrome-trefoil.film.json"
COST_BOUND = ROOT / "examples/motion/cost-bound.json"
OUT = ROOT / "output/manual-motion"


def request():
    args = cli.build_parser().parse_args(["render", str(SCRIPT), "--dry-run", "--max-api-calls", "0", "--retries", "0"])
    script = render.load_script(SCRIPT, args)
    if len(script["shots"]) != 1 or "reference_inputs" in script["shots"][0]:
        raise ValueError("Pilot must contain exactly one text-only generation shot")
    payload = script["shots"][0].get("payload")
    fixed = {"model": "gpt-image-2.6-flare", "output_format": "gif", "frame_count": 16,
             "frame_duration_ms": 200, "size": "512x512", "quality": "max", "complexity": "high"}
    if not isinstance(payload, dict) or set(payload) != {*fixed, "prompt"} or any(payload[k] != v for k, v in fixed.items()):
        raise ValueError("Pilot parameters differ from the reviewed fixed profile")
    return payload


def request_hash(payload):
    return hashlib.sha256(render.encoded(payload)).hexdigest()


def money(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,6})?", value):
        raise ValueError(f"{label} must be a positive decimal USD amount")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {label}") from exc
    if amount <= 0:
        raise ValueError(f"{label} must be positive")
    return amount


def authorize(payload, bound, approved_usd, confirm_billing, prior_attempts_reviewed, run_attempt, today=None):
    """Validate a reviewed bound; this does not independently verify its evidence."""
    if not confirm_billing or not prior_attempts_reviewed:
        raise ValueError("Confirm the existing OpenAI billing payer and review all previous attempts before spending")
    if run_attempt != "1":
        raise ValueError("Paid workflow reruns are blocked; inspect prior outcome/billing before a new authorized dispatch")
    budget = money(approved_usd, "approved_usd")
    if not isinstance(bound, dict) or bound.get("schema_version") != 1 or bound.get("status") != "reviewed-provider-upper-bound":
        raise ValueError("Native GIF cost upper bound is unknown. No API call permitted; token rates and a spending target are not a quote")
    if bound.get("currency") != "USD" or bound.get("includes_all_charges") is not True:
        raise ValueError("The reviewed bound must include all charges in USD")
    if bound.get("request_sha256") != request_hash(payload):
        raise ValueError("Cost bound does not match the exact effective API request")
    maximum = money(bound.get("maximum_total_usd"), "maximum_total_usd")
    if maximum > budget:
        raise ValueError("Reviewed request maximum exceeds the authorized total")
    if bound.get("basis") != "provider-guaranteed-request-maximum":
        raise ValueError("Only a provider-guaranteed request maximum qualifies; estimates do not")
    url = urlsplit(bound.get("source_url") or "")
    if (url.scheme != "https" or url.hostname not in {"openai.com", "developers.openai.com", "help.openai.com"}
            or url.username or url.password or url.port or url.query or not url.path):
        raise ValueError("Cost evidence must be a public official OpenAI URL without credentials or query data")
    try:
        expiry = date.fromisoformat(bound["valid_until"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("The provider bound needs a valid_until ISO date") from exc
    if expiry < (today or date.today()):
        raise ValueError("Reviewed cost bound has expired")
    return {"authorized_total_usd": str(budget), "reviewed_request_maximum_usd": str(maximum),
            "currency": "USD", "request_sha256": request_hash(payload), "source_url": bound["source_url"],
            "note": "Evidence was manually reviewed, not independently authenticated by this script"}


def prepare():
    payload = request()
    if OUT.exists():
        raise ValueError("Output already exists; preserve it and review previous results rather than overwriting")
    OUT.mkdir(parents=True)
    report = {"status": "unrendered", "route": "direct-openai", "endpoint": cli.API_URL,
              "parameters": payload, "request_sha256": request_hash(payload), "paid_calls": 0,
              "maximum_calls_if_authorized": 1, "automatic_retries": 0,
              "cost_upper_bound_usd": None, "cost_status": "unknown; execution blocked by bundled cost-bound.json",
              "expected_frames": 16, "expected_duration_ms": 3200,
              "review_status": "no media exists; visual review pending"}
    render.save(OUT / "request.json", report)
    render.save(OUT / "cost-bound.json", json.loads(COST_BOUND.read_text()))
    print(json.dumps(report, indent=2))


def execute():
    payload = request()
    if json.loads((OUT / "request.json").read_text())["request_sha256"] != request_hash(payload):
        raise ValueError("Request changed after offline preparation")
    approval = authorize(payload, json.loads(COST_BOUND.read_text()), os.environ.get("APPROVED_USD", ""),
                         os.environ.get("CONFIRM_BILLING") == "true", os.environ.get("PRIOR_ATTEMPTS_REVIEWED") == "true",
                         os.environ.get("GITHUB_RUN_ATTEMPT", ""))
    # No credential is read and no network call occurs before the entire gate passes.
    render.save(OUT / "authorization.json", approval)
    args = cli.build_parser().parse_args(["render", str(SCRIPT), "--execute", "--max-api-calls", "1", "--retries", "0", "--out", str(OUT / "render")])
    render.run(args)


def review():
    source = OUT / "render"
    manifest = json.loads((source / "render-manifest.json").read_text())
    record = manifest["shots"]["chrome-trefoil"]
    path = source / record["output"]
    if path.parent != source or path.suffix != ".gif":
        raise ValueError("Unexpected source GIF path")
    raw = cli.read_gif_bytes(path)
    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise ValueError("Source GIF hash differs from render manifest")
    frames, durations, loop = cli.validate_gif(io.BytesIO(raw))
    if len(frames) > 16 or any(f.size != (512, 512) for f in frames):
        raise ValueError("Returned dimensions/frame count differ from this review budget; preserve the original and investigate")
    target = OUT / "review"
    target.mkdir(exist_ok=False)
    sheet = Image.new("RGB", (4 * 256, 4 * 280), "#181a21")
    draw = ImageDraw.Draw(sheet)
    hashes = []
    for index, frame in enumerate(frames):
        frame.save(target / f"frame-{index:02}.png")
        hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
        thumb = frame.copy()
        thumb.thumbnail((256, 256))
        x, y = index % 4 * 256, index // 4 * 280
        sheet.paste(thumb, (x, y))
        draw.text((x + 8, y + 258), f"Frame {index:02} | {durations[index]} ms", fill="white")
    sheet.save(target / "all-frames.png")
    warnings = []
    if len(frames) != 16 or durations != [200] * 16:
        warnings.append("Actual timing differs from requested 16 x 200 ms")
    if loop != 0:
        warnings.append("GIF does not declare infinite looping")
    if len(set(hashes)) < 2:
        warnings.append("All decoded frames are identical")
    report = {"gif_sha256": record["sha256"], "source_file": record["output"], "actual_frames": len(frames),
              "frame_durations_ms": durations, "total_duration_ms": sum(durations), "loop": loop,
              "unique_decoded_frames": len(set(hashes)), "warnings": warnings,
              "technical_status": "decoded-with-warnings" if warnings else "requested-format-matched",
              "visual_status": "human-review-required", "user_acceptance": "pending",
              "review_checklist": ["Watch actual GIF playback at native timing", "Inspect every numbered frame",
                                   "Check constant tube thickness and topology", "Watch last-to-first motion and highlight stability"],
              "limitations": "Frame differences do not establish genuine object movement, smoothness or loop quality"}
    render.save(target / "review.json", report)
    print(json.dumps(report, indent=2))


def review_if_available():
    # A valid native GIF may have been saved before a later MP4 export failed.
    manifest_path = OUT / "render/render-manifest.json"
    if not manifest_path.exists():
        print("No render attempt record exists; no GIF is available for visual review.")
        return
    manifest = json.loads(manifest_path.read_text())
    if "chrome-trefoil" not in manifest.get("shots", {}):
        print("No saved GIF is available for review. Preserve the attempt record and reconcile any unknown charge.")
        return
    review()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "execute", "review", "review-if-available"])
    args = parser.parse_args()
    try:
        {"prepare": prepare, "execute": execute, "review": review, "review-if-available": review_if_available}[args.command]()
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        # Do not print provider bodies, tracebacks, environment variables or secrets.
        parser.exit(1, f"Pilot stopped: {exc}\n")


if __name__ == "__main__":
    main()
