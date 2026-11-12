"""Build a README table from real, locally verified animated GIFs.

Manifest: a JSON list of {id, name, gif, method, source, limitations}.
All asset links are repository-relative. Does not generate or approve artwork.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import quote

from PIL import Image


METHODS = {"drawn-poses": "Drawn poses", "cutout": "Cutout animation", "whole-image": "Whole-image motion"}


def local_file(root, value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Expected a repository-relative file path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Asset must stay inside the repository")
    resolved = (root / path).resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError("Asset must be a regular repository file")
    return resolved


def build_grid(root, records, columns=4):
    if not 1 <= columns <= 6 or not records or len(records) > 100:
        raise ValueError("Use 1–100 GIF entries and 1–6 columns")
    ids, files, cards, facts = set(), set(), [], []
    for item in records:
        identifier = item["id"]
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError("Each character needs a unique nonempty ID")
        ids.add(identifier)
        path = local_file(root, item["gif"])
        if path in files:
            raise ValueError("One GIF cannot count as two characters")
        files.add(path)
        local_file(root, item["source"])
        local_file(root, item["poster"])
        method = METHODS[item["method"]]
        hashes, duration = set(), 0
        with Image.open(path) as gif:
            if gif.format != "GIF" or gif.n_frames < 2 or gif.n_frames > 2000:
                raise ValueError("Grid entries must be actual animated GIFs")
            if gif.width * gif.height * gif.n_frames > 100_000_000:
                raise ValueError("GIF exceeds bounded inspection budget")
            for i in range(gif.n_frames):
                gif.seek(i)
                delay = gif.info.get("duration", 0)
                if not isinstance(delay, int) or delay <= 0:
                    raise ValueError("Every frame needs explicit positive timing")
                duration += delay
                hashes.add(hashlib.sha256(gif.convert("RGBA").tobytes()).hexdigest())
            count, size = gif.n_frames, gif.size
        if len(hashes) < 2:
            raise ValueError("A static image with repeated timing is not animation")
        facts.append({"id": identifier, "file": item["gif"], "frames": count,
                      "unique_decoded_frames": len(hashes), "duration_ms": duration,
                      "size": list(size), "method": item["method"],
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        name = html.escape(item["name"])
        link = html.escape(quote(item["gif"], safe="/"), quote=True)
        source = html.escape(quote(item["source"], safe="/"), quote=True)
        first = html.escape(quote(item.get("first_pose", item["poster"]), safe="/"), quote=True)
        limitation = html.escape(item["limitations"])
        poster = html.escape(quote(item["poster"], safe="/"), quote=True)
        cards.append(f'<td align="center" valign="top">\n'
                     f'<a href="{link}"><picture><source media="(prefers-reduced-motion: reduce)" srcset="{poster}"><img src="{link}" width="160" alt="{name}: {method.lower()}."></picture></a><br>\n'
                     f'<strong>{name}</strong><br>{duration / 1000:.2f} s · {count} frames<br>\n'
                     f'{method}<br><a href="{source}">Source &amp; method</a> · <a href="{first}">First pose</a><br>\n'
                     f'<small>{limitation}</small>\n</td>')
    rows = ["<tr>\n" + "\n".join(cards[i:i + columns]) + "\n</tr>" for i in range(0, len(cards), columns)]
    return "<table>\n" + "\n".join(rows) + "\n</table>\n", facts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    markup, facts = build_grid(args.root, json.loads(args.manifest.read_text()))
    args.out.write_text(markup, encoding="utf-8")
    args.out.with_suffix(".facts.json").write_text(json.dumps(facts, indent=2) + "\n")


if __name__ == "__main__":
    main()
