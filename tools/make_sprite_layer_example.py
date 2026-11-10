"""Create eight original soft-alpha light cels and an editable two-stage scene.

Procedural graphic artwork, not a character-action or generated-model example.
Run in the repository with a NEW --out directory; no provider/network is used.
"""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from gif_cinema import layers, sprites


def drawing(index):
    phase = 2 * math.pi * index / 8
    radius = 18 + 2 * math.sin(phase)
    frame = Image.new('RGBA', (96, 96))
    data = []
    for y in range(96):
        for x in range(96):
            dx, dy = x - 47.5, y - 47.5
            distance = math.hypot(dx, dy)
            if distance >= 44:
                data.append((0, 0, 0, 0)); continue
            halo = max(0, 85 * math.exp(-(distance / (radius * 1.35)) ** 2) - 4)
            coverage = max(0, min(1, radius + .5 - distance))
            light = math.exp(-((dx + radius * .32) ** 2 + (dy + radius * .36) ** 2) / (radius * .4) ** 2)
            alpha = round(halo + (230 - halo) * coverage)
            if alpha == 0:
                data.append((0, 0, 0, 0)); continue
            # Smooth RGB shading and partial alpha intentionally exceed the GIF
            # preview's palette/binary-alpha capabilities.
            red = round(28 + 190 * light * coverage + 12 * coverage)
            green = round(175 + 65 * light * coverage + 20 * coverage)
            blue = round(205 + 45 * light * coverage + 5 * coverage)
            data.append((red, green, blue, alpha))
    frame.putdata(data)
    return frame


def create(out):
    out = Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Example destination must be a new directory without symlinks')
    out.mkdir(parents=True, exist_ok=False)
    report = sprites.export([drawing(i) for i in range(8)], [80] * 8, 0,
        {'kind': 'original-procedural-graphic', 'description': 'Eight authored RGBA light-pulse cels; no model generation'},
        {'columns': 4, 'padding': 1, 'sampling': 'pixel'}, out / 'source')
    actor = {'type': 'sprites', 'source': 'source/atlas.png', 'sha256': report['files_sha256']['atlas.png'],
        'size': [160, 160], 'sampling': 'smooth', 'playback': 'loop',
        'frames': [{'rect': row['rect'], 'duration_ms': row['duration_ms']} for row in report['frame_layout']]}
    scene = {'format': layers.FORMAT, 'schema_version': 1, 'title': 'One atlas, two stages',
        'width': 480, 'height': 288, 'fps': 50, 'duration_ms': 2560, 'loop': True,
        'matte': '#101622', 'layers': [
            {'id': 'dark', 'type': 'rect', 'size': [240, 288], 'fill': '#101622',
             'keyframes': [{'at': 0, 'x': .25}, {'at': 1}]},
            {'id': 'light', 'type': 'rect', 'size': [240, 288], 'fill': '#f1e9dd',
             'keyframes': [{'at': 0, 'x': .75}, {'at': 1}]},
            {'id': 'header', 'type': 'rect', 'size': [480, 56], 'fill': '#0b1019',
             'keyframes': [{'at': 0, 'y': 28 / 288}, {'at': 1}]},
            {'id': 'title', 'type': 'text', 'text': 'ONE ATLAS. TWO STAGES.', 'font_size': 22, 'fill': '#f6f9ff',
             'keyframes': [{'at': 0, 'y': 28 / 288}, {'at': 1}]},
            {**actor, 'id': 'left', 'keyframes': [{'at': 0, 'x': .25, 'y': .54}, {'at': 1}]},
            {**actor, 'id': 'right', 'keyframes': [
                {'at': 0, 'x': .73, 'y': .54, 'easing': 'smootherstep'},
                {'at': .5, 'x': .77, 'easing': 'smootherstep'}, {'at': 1, 'x': .73}]},
            {'id': 'dark_label', 'type': 'text', 'text': 'Soft alpha / dark', 'font_size': 17, 'fill': '#abc0d6',
             'keyframes': [{'at': 0, 'x': .25, 'y': .89}, {'at': 1}]},
            {'id': 'light_label', 'type': 'text', 'text': 'Soft alpha / light', 'font_size': 17, 'fill': '#425268',
             'keyframes': [{'at': 0, 'x': .75, 'y': .89}, {'at': 1}]}]}
    # An authored recipe stays portable across supported Pillow versions. The
    # render/save step records the exact text renderer in its saved snapshot.
    layers.normalize_scene(scene)
    (out / 'scene.json').write_text(json.dumps(scene, indent=2) + '\n', encoding='utf-8')
    return out / 'scene.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    print(create(args.out))
