"""Offline held-out-frame benchmark. Uses Pillow and installed FFmpeg only.

Run from a checkout with the package installed:
    python tools/benchmark_interpolation.py --out output/held-out-benchmark

This measures reconstruction of existing drawings, not perceived motion quality.
No API requests, downloaded models, RIFE runtime, or cross-shot interpolation.
"""
import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import PIL
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageSequence, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gif_cinema.cli import validate_gif


def clean_rgb(image):
    """Drop GIF transparency metadata so PNG pixel formats cannot change mid-run."""
    result = image.convert("RGB").copy()
    result.info.clear()
    return result


def decode_opaque(source):
    """RGB palette values behind transparent pixels are not a visual reference."""
    frames, durations, _ = validate_gif(source)
    with Image.open(source) as image:
        for frame in ImageSequence.Iterator(image):
            if frame.convert("RGBA").getchannel("A").getextrema() != (255, 255):
                raise ValueError("Benchmark requires opaque GIF frames; composite transparent footage onto an explicit background first")
    return [clean_rgb(frame) for frame in frames], durations


def split_indices(frame_count):
    known = list(range(0, frame_count, 2))
    hidden = list(range(1, known[-1], 2))
    return known, hidden


def motion_mask(left, right):
    difference = ImageChops.difference(left, right)
    channels = difference.split()
    maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    return maximum.point(lambda value: 255 if value > 12 else 0).filter(ImageFilter.MaxFilter(7))


def score(prediction, target, mask):
    difference = ImageChops.difference(prediction, target)
    stats = ImageStat.Stat(difference)
    mse = sum(value * value for value in stats.rms) / 3
    active = sum(mask.histogram()[1:])
    masked = ImageStat.Stat(difference, mask) if active else None
    pred_edges = prediction.convert("L").filter(ImageFilter.FIND_EDGES)
    true_edges = target.convert("L").filter(ImageFilter.FIND_EDGES)
    return {
        "mae_0_255": sum(stats.mean) / 3,
        "mse": mse,
        "psnr_db": 10 * math.log10(255 ** 2 / mse) if mse else None,
        "motion_mae_0_255": sum(masked.mean) / 3 if masked else None,
        "edge_mae_0_255": ImageStat.Stat(ImageChops.difference(pred_edges, true_edges)).mean[0],
        "motion_mask_pixels": active,
    }


def interpolate_known(known_frames, duration_ms, folder):
    """This function receives ONLY visible frames, never held-out ground truth."""
    inputs = folder / "visible-inputs"
    outputs = folder / "motion-predictions"
    inputs.mkdir(); outputs.mkdir()
    for index, frame in enumerate(known_frames):
        clean_rgb(frame).save(inputs / f"{index:03}.png")
    input_fps = Fraction(1000, duration_ms * 2)
    output_fps = Fraction(1000, duration_ms)
    count = len(known_frames) * 2 - 1
    # A duplicated leading frame provides context, shifted to negative time.
    # Trim by time before numbering output frames; validate known timestamps below.
    filters = ("format=yuv444p,tpad=start_mode=clone:start=1:stop_mode=clone:stop=3,"
               "setpts=PTS-STARTPTS-1,"
               f"minterpolate=fps={output_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
               f"trim=start=0,trim=end_frame={count}")
    command = ["ffmpeg", "-v", "error", "-nostdin", "-framerate", str(input_fps),
               "-i", str(inputs / "%03d.png"), "-vf", filters,
               "-fps_mode", "passthrough", "-start_number", "0", str(outputs / "%03d.png")]
    start = time.monotonic()
    subprocess.run(command, check=True, capture_output=True, timeout=300)
    elapsed = time.monotonic() - start
    paths = sorted(outputs.glob("*.png"))
    if len(paths) != count:
        raise RuntimeError(f"Unexpected interpolated frame count: {len(paths)} != {count}")
    frames = []
    for path in paths:
        with Image.open(path) as image:
            frames.append(clean_rgb(image))
    calibration = []
    for index, original in enumerate(known_frames):
        mae = sum(ImageStat.Stat(ImageChops.difference(frames[index * 2], original)).mean) / 3
        calibration.append(mae)
        if mae > 1.0:
            raise RuntimeError(f"Known frame {index * 2} failed timestamp/color calibration: MAE={mae:.3f}")
    return frames, {"command": command, "seconds": elapsed, "known_frame_mae": calibration}


def aggregate(rows):
    result = {}
    for method in ("hold", "blend", "motion"):
        values = [row["scores"][method] for row in rows]
        stats = {"samples": len(values)}
        for key in ("mae_0_255", "motion_mae_0_255", "edge_mae_0_255", "mse"):
            available = [value[key] for value in values if value[key] is not None]
            stats[key] = sum(available) / len(available) if available else None
        stats["psnr_from_mean_mse_db"] = 10 * math.log10(255 ** 2 / stats["mse"]) if stats["mse"] else None
        result[method] = stats
    return result


def comparison_sheet(cases, path):
    sheet = Image.new("RGB", (1024, len(cases) * 286), "#202020")
    draw = ImageDraw.Draw(sheet)
    for row_index, case in enumerate(cases):
        for column, method in enumerate(("truth", "hold", "blend", "motion")):
            image = case["images"][method].copy()
            image.thumbnail((256, 256))
            x, y = column * 256, row_index * 286
            sheet.paste(image, (x, y))
            label = f"{method} | shot {case['shot']} frame {case['hidden_index']}"
            draw.text((x + 4, y + 259), label, fill="white")
            if method != "truth":
                value = case["scores"][method]["motion_mae_0_255"]
                draw.text((x + 4, y + 272), f"motion MAE {value:.2f}" if value is not None else "no motion mask", fill="white")
    sheet.save(path)


def run(sources, out):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Installed FFmpeg is required")
    prepared = []
    for source in sources:
        source = Path(source).resolve()
        frames, durations = decode_opaque(source)
        if not 5 <= len(frames) <= 64 or len(set(durations)) != 1:
            raise ValueError("Benchmark requires 5..64 drawings with uniform delays; variable timing is not silently normalized")
        prepared.append((source, frames, durations[0], hashlib.sha256(source.read_bytes()).hexdigest()))
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    records, sources_receipt, selected = [], [], []
    for index, (source, frames, duration, sha) in enumerate(prepared, 1):
        folder = out / f"shot-{index:02}"
        folder.mkdir()
        known, hidden = split_indices(len(frames))
        predictions, receipt = interpolate_known([frames[i] for i in known], duration, folder)
        cases = []
        for frame in hidden:
            left, right, truth = frames[frame - 1], frames[frame + 1], frames[frame]
            mask = motion_mask(left, right)
            images = {"truth": truth, "hold": left, "blend": Image.blend(left, right, 0.5), "motion": predictions[frame]}
            scores = {method: score(images[method], truth, mask) for method in ("hold", "blend", "motion")}
            record = {"shot": index, "hidden_index": frame, "time_ms": frame * duration,
                      "visible_neighbors": [frame - 1, frame + 1], "scores": scores}
            records.append(record)
            cases.append({**record, "images": images})
            truth.save(folder / f"truth-{frame:03}.png")
        comparison_sheet(cases, folder / "all-hidden-frames.png")
        # Deterministic difficult example, selected by baseline error, not winner.
        selected.append(max(cases, key=lambda case: case["scores"]["hold"]["motion_mae_0_255"] or 0))
        if hashlib.sha256(source.read_bytes()).hexdigest() != sha:
            raise RuntimeError("Source changed during benchmark")
        sources_receipt.append({"file": str(source), "sha256": sha, "source_unchanged": True,
                                "drawings": len(frames), "native_delay_ms": duration, "visible_gap_ms": 2 * duration,
                                "visible_indices": known, "hidden_indices": hidden, **receipt})
    comparison_sheet(selected, out / "hardest-cases.png")
    result = {
        "scope": "Offline held-out native drawings; no RIFE, new models, network or API generation",
        "python": platform.python_version(), "pillow": PIL.__version__,
        "ffmpeg": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
        "methodology": {
            "visible": "Even native drawings only. All odd drawings are excluded from inference.",
            "hidden": "Odd drawings strictly between two visible neighbors; unbracketed last drawing excluded.",
            "hold": "Repeat left visible drawing.", "blend": "50/50 RGB average of visible neighbors.",
            "motion": "FFmpeg motion compensation with all visible even drawings as temporal context.",
            "mask": "Endpoint RGB max difference >12, dilated by 7x7. No hidden-frame data defines mask.",
            "alignment": "Known output drawings must have RGB MAE <=1/255; stable RGB PNG inputs, no inherited GIF metadata.",
        },
        "limitations": ["Native generated drawings are a reference, not a unique physically correct trajectory.",
                        "Visible spacing is twice each source's native delay; see per-source native_delay_ms and visible_gap_ms. This differs from filling native gaps.",
                        "The endpoint-change mask is not complete motion segmentation: an object can move away and return to the same endpoint position.",
                        "Metrics favor pixel agreement, can reward blur, and do not measure temporal smoothness or narrative continuity.",
                        "No interpolation across scene boundaries; per-frame metrics do not assess cuts.",
                        "Results cover only these selected shots and settings, not RIFE or private showcase quality."],
        "sources": sources_receipt, "aggregate": aggregate(records), "samples": records,
    }
    (out / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(out), "aggregate": result["aggregate"]}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    sources = args.sources or [ROOT / f".agents/skills/gif-cinema/assets/example/shot-{i:02}.gif" for i in range(1, 4)]
    run(sources, args.out)
