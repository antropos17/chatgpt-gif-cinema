#!/usr/bin/env python3
"""Verify the real bundled sources and optionally build a decoded-frame gallery.

Offline only: this tool never calls a provider, generates new action, retimes a
source, or modifies an input. Run from any directory; --out must be a new folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "examples/asset-catalog.json"
FACTS = ("sha256", "bytes", "width", "height", "frames", "unique_frames",
         "durations_ms", "total_duration_ms", "loop")


def safe_source(root: Path, relative: str) -> Path:
    """Only ordinary files inside this checkout, not symlinked external inputs."""
    if not isinstance(relative, str) or not relative:
        raise ValueError("Source path must be a nonempty repository-relative string")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Source path must stay in the repository: {relative}")
    root = root.resolve()
    candidate = root / path
    if any(part.is_symlink() for part in [candidate, *candidate.parents] if part != root):
        raise ValueError(f"Symlinked source not accepted: {relative}")
    if not candidate.is_file() or not candidate.resolve().is_relative_to(root):
        raise ValueError(f"Missing repository source: {relative}")
    return candidate


def source_facts(path: Path) -> dict:
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Example source exceeds the 10 MiB inspection budget")
    data = path.read_bytes()
    with Image.open(path) as image:
        if image.format != "GIF" or not 1 < image.n_frames <= 256:
            raise ValueError("Example source must be a 2-256 frame GIF")
        width, height = image.size
        if width * height * image.n_frames > 64 * 1024 * 1024:
            raise ValueError("Example source exceeds the decoded pixel budget")
        loop = image.info.get("loop")
        durations, unique = [], set()
        for frame in range(image.n_frames):
            image.seek(frame)
            delay = image.info.get("duration")
            if type(delay) is not int or delay <= 0:
                raise ValueError("Example source has missing or invalid frame timing")
            durations.append(delay)
            unique.add(hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest())
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "width": width, "height": height, "frames": len(durations),
            "unique_frames": len(unique), "durations_ms": durations,
            "total_duration_ms": sum(durations), "loop": loop}


def verify_catalog(catalog: dict, root: Path = ROOT) -> dict:
    if catalog.get("schema_version") != 1 or type(catalog.get("schema_version")) is not int:
        raise ValueError("Unsupported example catalog schema")
    sources = catalog.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 12:
        raise ValueError("Catalog requires 1-12 sources")
    ids, paths, checked = set(), set(), []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Catalog source must be an object")
        identifier = source.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError("Every source needs a distinct nonempty ID")
        ids.add(identifier)
        relative = source.get("path")
        path = safe_source(root, relative)
        if relative in paths:
            raise ValueError("Catalog cannot count the same source twice")
        paths.add(relative)
        facts = source_facts(path)
        for name in FACTS:
            if name not in source or source[name] != facts[name]:
                raise ValueError(f"{identifier}: {name} differs from the catalog")
        checked.append({"id": identifier, "path": relative, **facts})
    return {"schema_version": 1, "title": catalog["title"], "provider_calls": 0,
            "source_count": len(checked),
            "source_frames": sum(s["frames"] for s in checked),
            "native_action_ms": sum(s["total_duration_ms"] for s in checked),
            "visual_acceptance": "human-review-required", "sources": checked}


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow 10.0 remains supported by the public runtime.
        return ImageFont.load_default()


def storyboard(catalog: dict, root: Path = ROOT) -> tuple[Image.Image, list[dict]]:
    """Show decoded first/middle/last frames, never invented intermediate poses."""
    sources = catalog["sources"]
    background, ink, muted, accent = "#111a20", "#f5eee2", "#a8b4bb", "#e5b581"
    image = Image.new("RGB", (1040, 118 + len(sources) * 398 + 60), background)
    draw = ImageDraw.Draw(image)
    draw.text((28, 22), "A REPLY FROM THE STARS", font=font(25), fill=ink)
    draw.text((28, 61), "REAL SOURCE FRAMES / THREE ACTIONS / ZERO NEW GENERATION", font=font(13), fill=accent)
    draw.text((28, 88), "First, middle and last decoded drawings. Each take plays once in the assembled film.", font=font(13), fill=muted)
    samples = []
    for row, source in enumerate(sources):
        y = 118 + row * 398
        draw.line((28, y, 1012, y), fill="#37434a")
        draw.text((28, y + 14), source["label"], font=font(18), fill=ink)
        draw.text((28, y + 41), source["action"], font=font(13), fill=muted)
        with Image.open(safe_source(root, source["path"])) as gif:
            indices = (0, gif.n_frames // 2, gif.n_frames - 1)
            for col, (name, index) in enumerate(zip(("FIRST", "MIDDLE", "LAST"), indices)):
                gif.seek(index)
                # Entire source image is visible, fitted rather than cropped.
                frame = gif.convert("RGBA")
                frame.thumbnail((316, 316), Image.Resampling.LANCZOS)
                panel = Image.new("RGBA", (316, 316), "black")
                panel.alpha_composite(frame, ((316 - frame.width) // 2, (316 - frame.height) // 2))
                x = 28 + col * 334
                image.paste(panel.convert("RGB"), (x, y + 70))
                timestamp = sum(source["durations_ms"][:index])
                draw.text((x + 9, y + 79), f"{name} / {timestamp / 1000:.2f} s", font=font(12), fill=ink)
                samples.append({"source_id": source["id"], "frame_index": index, "start_ms": timestamp})
    draw.text((28, image.height - 38), "Native timing: 16 drawings x 160 ms per take. Export FPS does not create new character motion.", font=font(13), fill=muted)
    return image, samples


def build(out: Path, catalog: dict, root: Path = ROOT) -> dict:
    out = out.absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError("Output must be a new directory without symlinks")
    report = verify_catalog(catalog, root)
    sheet, samples = storyboard(catalog, root)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".example-stage-", dir=out.parent) as tmp:
        stage = Path(tmp)
        sheet.save(stage / "astronaut-storyboard.png")
        # Recheck source identity after decoding; no changed sources are published.
        if verify_catalog(catalog, root) != report:
            raise ValueError("Source changed while building the gallery")
        report["outputs"] = {"astronaut-storyboard.png": hashlib.sha256((stage / "astronaut-storyboard.png").read_bytes()).hexdigest()}
        report["sampled_frames"] = samples
        report["presentation"] = "Decoded source frames fitted to panels; labels added locally. No new poses."
        (stage / "source-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        out.mkdir()
        for path in stage.iterdir():
            path.replace(out / path.name)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="verify catalog facts without writing files")
    mode.add_argument("--out", type=Path, help="new directory for storyboard PNG and source receipt")
    args = parser.parse_args()
    try:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        report = verify_catalog(catalog) if args.check else build(args.out, catalog)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Example inspection failed: {exc}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
