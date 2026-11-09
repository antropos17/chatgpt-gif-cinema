#!/usr/bin/env python3
"""Build outlined, static README typography. No network or generation calls.

Optional design dependencies: Pillow, fonttools and the original Open Sans 1.10
Regular/Semibold TTFs. The runtime and README viewers do not need these fonts.
"""
from __future__ import annotations
import argparse
import hashlib
import html
import json
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/assets/identity'
INK, PAPER, MUTED, ACCENT, LINE = '#282722', '#f1ece4', '#68645d', '#8a583b', '#d0c8bd'
FONTS = {
    'regular': ('OpenSans-Regular.ttf', 'e64e508b2aa2880f907e470c4550980ec4c0694d103a43f36150ac3f93189bee'),
    'semibold': ('OpenSans-Semibold.ttf', 'aa3b0ef53db12e3d45094030cac0e69d384e44cc5978643dd4390041cad546e2'),
}


def number(value):
    return f'{value:.2f}'.rstrip('0').rstrip('.') or '0'


class Typesetter:
    def __init__(self, directory):
        self.fonts = {}
        for weight, (name, expected) in FONTS.items():
            path = directory / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise SystemExit(f'{name}: source font differs from the reviewed version')
            self.fonts[weight] = (path, TTFont(path))

    def line(self, content, x, baseline, size, weight='regular', color=INK):
        path, font = self.fonts[weight]
        shape = ImageFont.truetype(str(path), size * 4)
        glyphs = font.getGlyphSet()
        cmap = font.getBestCmap()
        pen = SVGPathPen(glyphs, ntos=number)
        scale = size / font['head'].unitsPerEm
        for i, char in enumerate(content):
            if ord(char) not in cmap:
                raise ValueError(f'No glyph for {char!r}')
            offset = shape.getlength(content[:i], features=['-liga']) / 4
            glyphs[cmap[ord(char)]].draw(TransformPen(pen, (scale, 0, 0, -scale, x + offset, baseline)))
        return f'  <path fill="{color}" d="{pen.getCommands()}"/>\n'


def svg(width, height, title, description, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">\n'
            f'  <title id="title">{html.escape(title)}</title>\n'
            f'  <desc id="desc">{html.escape(description)}</desc>\n'
            f'  <rect width="{width}" height="{height}" rx="8" fill="{PAPER}"/>\n'
            + body + '</svg>\n')


def build(typesetter):
    t = typesetter.line
    title = 'Small takes. Real stories.'
    desc = 'Static editorial typography in Open Sans. Direct, review and assemble. This is not an animation sample.'
    wide = t('A small motion workshop', 48, 47, 22, color=MUTED)
    wide += t('Small takes.', 43, 145, 88, 'semibold')
    wide += t('Real stories.', 43, 246, 88, 'semibold')
    wide += f'  <path d="M848 48V266M48 292H1152" fill="none" stroke="{LINE}"/>\n'
    for y, n, label in [(102, '01', 'Direct'), (173, '02', 'Review'), (244, '03', 'Assemble')]:
        wide += t(n, 891, y, 18, 'semibold', ACCENT) + t(label, 945, y, 25)
    wide += t('An agent skill + local filmmaking toolkit', 48, 326, 22, color=MUTED)
    mobile = t('A small motion workshop', 30, 45, 24, color=MUTED)
    mobile += t('Small takes.', 26, 132, 66, 'semibold')
    mobile += t('Real stories.', 26, 213, 66, 'semibold')
    mobile += f'  <path d="M30 255H570" fill="none" stroke="{LINE}"/>\n'
    for x, label in [(30, 'Direct'), (191, 'Review'), (371, 'Assemble')]:
        mobile += t(label, x, 300, 25, color=ACCENT)
    story = f'  <path d="M333 26V184M667 26V184" fill="none" stroke="{LINE}"/>\n'
    for x, n, label in [(32, '01', 'A signal'), (367, '02', 'A reply'), (700, '03', 'A feeling')]:
        story += t(n, x, 54, 19, 'semibold', ACCENT)
        story += t(label, x, 117, 33, 'semibold')
        story += t('2.56 seconds', x, 169, 19, color=MUTED)
    return {
        'cover.svg': svg(1200, 354, title, desc, wide),
        'cover-mobile.svg': svg(600, 342, title, desc, mobile),
        'story-strip.svg': svg(1000, 210, 'A signal. A reply. A feeling.',
                               'Static three-shot diagram, not movie frames. Each existing source lasts 2.56 seconds.', story),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-dir', type=Path, default=Path('/usr/share/fonts/truetype/open-sans'))
    parser.add_argument('--check', action='store_true', help='Verify without changing any files')
    args = parser.parse_args()
    outputs = build(Typesetter(args.font_dir))
    for name, content in outputs.items():
        target = OUT / name
        if args.check:
            if target.read_text(encoding='utf-8') != content:
                raise SystemExit(f'Out of date: {target.relative_to(ROOT)}')
        else:
            target.write_text(content, encoding='utf-8')
    if not args.check:
        path = OUT / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['typography'] = {'family': 'Open Sans', 'version': '1.10', 'outlined': True,
                                  'license': 'Apache-2.0', 'source_fonts': [
                                      {'file': n, 'sha256': sha} for n, sha in FONTS.values()]}
        for asset in manifest['assets']:
            if Path(asset['path']).name in outputs:
                data = (ROOT / asset['path']).read_bytes()
                asset['bytes'] = len(data)
                asset['sha256'] = hashlib.sha256(data).hexdigest()
        path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Verified static README typography' if args.check else 'Built three static outlined SVGs')


if __name__ == '__main__':
    main()
