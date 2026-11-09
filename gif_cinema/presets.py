"""Original offline motion-design recipes for the existing layer compositor.

Run ``python -m gif_cinema.presets NAME --out NEW_DIRECTORY`` to save an
editable scene. This module creates graphics, never new character drawings.
"""
import argparse
import json
import math
from pathlib import Path

from . import layers, text_fonts

NAMES = ('stagger-title', 'orbit-badge', 'split-stage', 'focus-card')
DEFAULT_COPY = {
    'stagger-title': ('MAKE IT', 'MOVE', 'A little rhythm goes a long way'),
    'orbit-badge': ('ORBIT', 'STUDIO', 'Ideas with a gravitational pull'),
    'split-stage': ('OPEN', 'STAGE', 'Make room for the next big idea'),
    'focus-card': ('FIND YOUR', 'FOCUS', 'One clear idea. Every frame.'),
}
COLORS = {'stagger-title': '#b9f36b', 'orbit-badge': '#ad9bff',
          'split-stage': '#ff795c', 'focus-card': '#73dfdc'}


def key(at, **state):
    return {'at': at, **state}


def fixed(x, y):
    return [key(0, x=x, y=y), key(1, x=x, y=y)]


def rect(name, width, height, fill, keys, **extra):
    return {'id': name, 'type': 'rect', 'size': [width, height],
            'fill': fill, 'keyframes': keys, **extra}


def text(name, copy, size, fill, keys):
    return {'id': name, 'type': 'text', 'text': copy, 'font_size': size,
            'font_id': text_fonts.NOTO_FONT, 'fill': fill, 'keyframes': keys}


def entrance(x, y, delay=0, axis='x', offset=-.08):
    """Anticipation, overshoot, settle, reading hold, then return to rest."""
    start = {axis: (x if axis == 'x' else y) + offset}
    overshoot = {axis: (x if axis == 'x' else y) - offset * .15}
    return [key(0, x=x, y=y, opacity=0, zoom=.96),
            key(.06 + delay, **{**{'x': x, 'y': y}, **start}, opacity=0, easing='ease-out'),
            key(.23 + delay, **{**{'x': x, 'y': y}, **overshoot}, opacity=1, zoom=1.025, easing='ease-in-out'),
            key(.32 + delay, x=x, y=y, zoom=1),
            key(.79, x=x, y=y, opacity=1, easing='ease-in'),
            key(.94, x=x, y=y, opacity=0, zoom=.96), key(1, x=x, y=y, opacity=0)]


def make_scene(name, *, headline=None, second_line=None, caption=None, accent=None):
    """Build and validate a 480x320, 3.2 s, 25 fps editable scene.

    Copy must fit the fixed composition; long or unsupported text is rejected
    rather than clipped or silently shrunk. Color is an explicit opaque hex.
    """
    if name not in NAMES:
        raise ValueError(f'Unknown preset; choose from {NAMES}')
    defaults = DEFAULT_COPY[name]
    headline = defaults[0] if headline is None else headline
    second_line = defaults[1] if second_line is None else second_line
    caption = defaults[2] if caption is None else caption
    accent = COLORS[name] if accent is None else layers.color(accent, 'accent')
    if len(accent) != 7:
        raise ValueError('accent must be opaque #RRGGBB')
    ink, paper = '#151824', '#f6f2e9'
    content = [rect('background', 480, 320, ink, fixed(.5, .5))]
    if name == 'stagger-title':
        content += [text('eyebrow', 'TYPE / 01', 13, accent, fixed(.17, .13)),
                    text('headline', headline, 43, paper, entrance(.41, .36)),
                    text('second_line', second_line, 66, accent, entrance(.48, .58, .06, offset=.09)),
                    text('caption', caption, 14, paper, entrance(.5, .86, .10, axis='y', offset=.04))]
        for i in range(3):
            x = .79 + i * .055
            keys = [key(0, x=x, y=.17, zoom=.4, opacity=0),
                    key(.12 + i * .05, x=x, y=.17, zoom=.4, opacity=0, easing='ease-out'),
                    key(.25 + i * .05, x=x, y=.17, zoom=1.25, opacity=1, easing='ease-in-out'),
                    key(.37 + i * .05, x=x, y=.17, zoom=1),
                    key(.79, opacity=1, easing='ease-in'), key(.94, opacity=0, zoom=.4), key(1)]
            content.append({'id': f'beat_{i}', 'type': 'ellipse', 'size': [13, 13],
                            'fill': accent, 'keyframes': keys})
    elif name == 'orbit-badge':
        content += [{'id': 'ring', 'type': 'ellipse', 'size': [234, 234],
                     'fill': '#00000000', 'stroke': '#4a465f', 'stroke_width': 1,
                     'keyframes': fixed(.5, .45)},
                    text('headline', headline, 39, paper, fixed(.5, .40)),
                    text('second_line', second_line, 17, accent, fixed(.5, .56)),
                    text('caption', caption, 14, paper, fixed(.5, .91))]
        for i in range(3):
            keys = []
            for j in range(25):
                angle = 2 * math.pi * (j / 24 + i / 3) - math.pi / 2
                keys.append(key(j / 24, x=.5 + 117 / 480 * math.cos(angle),
                                y=.45 + 117 / 320 * math.sin(angle)))
            keys[-1].update(x=keys[0]['x'], y=keys[0]['y'])
            content.append({'id': f'satellite_{i}', 'type': 'ellipse', 'size': [18 - i * 4] * 2,
                            'fill': (accent, paper, '#ffb575')[i], 'keyframes': keys})
    elif name == 'split-stage':
        content[0]['fill'] = paper
        content += [text('headline', headline, 48, ink, entrance(.5, .33, axis='y', offset=.05)),
                    text('second_line', second_line, 58, ink, entrance(.5, .56, .04, axis='y', offset=.04)),
                    text('caption', caption, 14, ink, fixed(.5, .85)),
                    rect('left_panel', 244, 320, ink,
                         [key(0, x=.25, y=.5), key(.08, easing='smootherstep'),
                          key(.32, x=-.26), key(.76, easing='smootherstep'), key(.96, x=.25), key(1)]),
                    rect('right_panel', 244, 320, accent,
                         [key(0, x=.75, y=.5), key(.08, easing='smootherstep'),
                          key(.32, x=1.26), key(.76, easing='smootherstep'), key(.96, x=.75), key(1)]),
                    rect('seam', 3, 68, paper,
                         [key(0, x=.5, y=.5, opacity=1), key(.07, easing='ease-in'),
                          key(.18, opacity=0), key(.91, opacity=0, easing='ease-out'), key(1, opacity=1)])]
    else:
        content += [text('eyebrow', 'FRAME / 04', 12, accent, fixed(.5, .14)),
                    text('headline', headline, 30, paper, entrance(.5, .38, axis='y', offset=.025)),
                    text('second_line', second_line, 58, accent, entrance(.5, .57, .06, axis='y', offset=.025)),
                    text('caption', caption, 14, paper, entrance(.5, .89, .09, axis='y', offset=.02))]
        for i, (x, y) in enumerate(((.12, .25), (.88, .25), (.12, .74), (.88, .74))):
            for axis, size in (('h', (26, 3)), ('v', (3, 26))):
                # Bracket strokes point inward from their anchor corner.
                px = x + ((1 if x < .5 else -1) * 12 / 480 if axis == 'h' else 0)
                py = y + ((1 if y < .5 else -1) * 12 / 320 if axis == 'v' else 0)
                keys = entrance(px, py, i * .02, offset=(x - .5) * .3)
                content.append(rect(f'corner_{i}_{axis}', *size, accent, keys))
    scene = layers.normalize_scene({'format': layers.FORMAT, 'schema_version': 1,
        'title': f'Motion preset: {name}', 'width': 480, 'height': 320,
        'duration_ms': 3200, 'fps': 25, 'loop': True, 'matte': ink, 'layers': content})
    # Measure actual packaged-font glyphs before writing any scene.
    for layer in scene['layers']:
        if layer['type'] == 'text':
            _, _, _, size = layers.text_layout(layer)
            limit = 192 if name == 'orbit-badge' and layer['id'] in ('headline', 'second_line') else 350
            if size[0] > limit:
                raise ValueError(f'{layer["id"]} is too wide for {name}; shorten the copy')
    return scene


def save_preset(name, out, **options):
    scene = make_scene(name, **options)
    destination = Path(out).absolute()
    if destination.exists() or any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError('Preset output must be a new directory without symlinks')
    raw = layers.serialize_scene(scene)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'scene.json').write_bytes(raw)
    return destination / 'scene.json'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('preset', choices=NAMES)
    parser.add_argument('--out', type=Path, required=True)
    for name in ('headline', 'second-line', 'caption', 'accent'):
        parser.add_argument('--' + name)
    args = parser.parse_args(argv)
    try:
        scene = save_preset(args.preset, args.out, headline=args.headline,
                            second_line=args.second_line, caption=args.caption, accent=args.accent)
        print(json.dumps({'scene': str(scene), 'api_calls': 0}))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Preset error: {exc}\n')


if __name__ == '__main__':
    main()
