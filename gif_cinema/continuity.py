"""Offline cut-context diagnostics; pixel scores never approve a performance."""
from statistics import median

from PIL import Image, ImageChops, ImageDraw, ImageStat

REVIEW_CHECKS = [
    "character identity and costume",
    "pose, hands, props and contact",
    "gaze and screen direction",
    "action speed and holds around the cut",
    "scene geography, lighting and causality",
]


def pixel_mae(left, right):
    """Compare normalized RGB thumbnails, without judging semantic continuity."""
    a = left.convert("RGB").resize((128, 128))
    b = right.convert("RGB").resize((128, 128))
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


def context(frames, delays, side, frame_offset=0):
    """Describe up to three drawings with timing relative to the hard cut."""
    if len(frames) != len(delays) or not frames:
        raise ValueError("Cut context requires matching frames and delays")
    if any(type(delay) is not int or delay < 20 for delay in delays):
        raise ValueError("Cut context needs frame delays of at least 20 ms")
    if side not in {"previous", "next"}:
        raise ValueError("Unknown side of cut")
    indexes = range(max(0, len(frames) - 3), len(frames)) if side == "previous" else range(min(3, len(frames)))
    cursor = -sum(delays) if side == "previous" else 0
    rows = []
    for index, delay in enumerate(delays):
        if index in indexes:
            rows.append({"frame": index + frame_offset, "start_ms_from_cut": cursor,
                         "end_ms_from_cut": cursor + delay, "duration_ms": delay})
        cursor += delay
    changes = []
    for left, right in zip(rows, rows[1:]):
        score = pixel_mae(frames[left["frame"] - frame_offset], frames[right["frame"] - frame_offset])
        changes.append({"from_frame": left["frame"], "to_frame": right["frame"],
                        "pixel_mae_0_255": round(score, 6),
                        "pixel_mae_per_second": round(score * 1000 / left["duration_ms"], 6)})
    return {"frames": rows, "adjacent_changes": changes, "frame_offset": frame_offset}


def cut_context(previous, previous_delays, following, following_delays, previous_frame_offset=0):
    """Keep real cadence and local changes visible, including unequal frame delays."""
    left = context(previous, previous_delays, "previous", previous_frame_offset)
    right = context(following, following_delays, "next")
    seam = pixel_mae(previous[-1], following[0])
    local = [row["pixel_mae_0_255"] for side in (left, right) for row in side["adjacent_changes"]]
    baseline = median(local) if local else 0
    return {"previous": left, "next": right,
            "cut_pixel_mae_0_255": round(seam, 6),
            "local_change_median_0_255": round(baseline, 6),
            "cut_to_local_change_ratio": round(seam / baseline, 6) if baseline else None,
            "review_checks": list(REVIEW_CHECKS),
            "status": "human-review-required",
            "note": "Scores describe pixels, not identity, motion direction or smoothness. "
                    "A null ratio means no nonzero local baseline; it is not a pass."}


def cut_sheet(previous, following, report):
    """Bounded chronological strip; native endpoint PNGs remain available separately."""
    cells = [(previous, row, "OUT", report["previous"]["frame_offset"]) for row in report["previous"]["frames"]]
    cells += [(following, row, "IN", report["next"]["frame_offset"]) for row in report["next"]["frames"]]
    sheet = Image.new("RGB", (208 * len(cells), 232), "#181818")
    draw = ImageDraw.Draw(sheet)
    for offset, (frames, row, label, frame_offset) in enumerate(cells):
        thumb = frames[row["frame"] - frame_offset].convert("RGB")
        thumb.thumbnail((192, 180))
        x = offset * 208 + 8
        sheet.paste(thumb, (x, 24))
        draw.text((x, 4), f'{label} frame {row["frame"]}', fill="white")
        draw.text((x, 208), f'{row["start_ms_from_cut"]:+} ms | {row["duration_ms"]} ms', fill="white")
    return sheet
