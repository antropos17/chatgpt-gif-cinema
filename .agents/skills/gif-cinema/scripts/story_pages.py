"""Compose existing GIF actions into readable story pages, without provider calls.

Landscape places text beside the action; portrait places it below. Each action
plays once at its actual source cadence. No synthetic poses or page-turn effects.
"""
import argparse
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence
from gif_cinema import cli, render

MAX_JSON_BYTES = 1024 * 1024
MAX_FONT_BYTES = 10 * 1024 * 1024
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_PAGE_PIXELS = 32 * 1024 * 1024
MAX_PROJECT_PIXELS = 128 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024 * 1024


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_bytes(path, limit):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Inputs must be regular local files')
        if info.st_size > limit:
            raise ValueError('Input exceeds its byte limit')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Input exceeds its byte limit')
    return raw


def only(value, keys, label):
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ValueError(f'{label}: invalid object or unknown fields')


def text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{label}: expected nonempty text, at most {limit} characters')
    if any(ord(c) < 32 and c != '\n' for c in value):
        raise ValueError(f'{label}: control characters are not supported')
    return value


def pin(raw, expected, label):
    if expected is not None and (not isinstance(expected, str) or
            not re.fullmatch('[0-9a-f]{64}', expected) or digest(raw) != expected):
        raise ValueError(f'{label}: SHA-256 mismatch')


def color(value, label):
    if not isinstance(value, str) or not re.fullmatch('#[0-9a-fA-F]{6}', value):
        raise ValueError(f'{label}: use an opaque #RRGGBB color')
    return value


def local(base, name):
    text(name, 'Local file path', 4000)
    if '://' in name:
        raise ValueError('Only local files are supported')
    return base / name


def layout_boxes(width, height, layout):
    margin = round(min(width, height) * .06)
    gap = round(margin * .75)
    if layout == 'landscape':
        split = round(width * .43)
        words = (margin, margin, split - gap, height - margin)
        art = (split, margin, width - margin, height - margin)
    else:
        split = round(height * .57)
        art = (margin, margin, width - margin, split)
        words = (margin, split + gap, width - margin, height - margin)
    return words, art


def wrap(value, font, width, draw):
    """Keep explicit paragraphs and break long words rather than clip them."""
    lines = []
    for paragraph in value.split('\n'):
        words, current = paragraph.split(), ''
        for word in words:
            candidate = f'{current} {word}' if current else word
            if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ''
            for char in word:
                if draw.textbbox((0, 0), current + char, font=font)[2] > width:
                    if not current:
                        raise ValueError('A text glyph does not fit the page')
                    lines.append(current)
                    current = ''
                current += char
        lines.append(current)
    return lines


def page_base(spec, page, index, count, font_raw):
    image = Image.new('RGB', (spec['width'], spec['height']), spec['background'])
    draw = ImageDraw.Draw(image)
    box, art = layout_boxes(*image.size, spec['layout'])
    x, y, right, bottom = box
    width = right - x
    size = max(16, round(min(image.size) * .038))
    fonts = [ImageFont.truetype(io.BytesIO(font_raw), s) for s in (size, round(size * 1.5))]
    draw.line((x, y, x + min(width, size * 3), y), fill=spec['accent'], width=3)
    y += size
    blocks = [(f'{index:02} / {count:02}', fonts[0], spec['accent']),
              (page['heading'], fonts[1], spec['foreground']),
              (page['text'], fonts[0], spec['foreground'])]
    for value, font, fill in blocks:
        ascent, descent = font.getmetrics()
        line_height = math.ceil((ascent + descent) * 1.15)
        for line in wrap(value, font, width, draw):
            bounds = draw.textbbox((0, 0), line, font=font)
            if bounds[2] - bounds[0] > width or y + max(line_height, bounds[3] - bounds[1]) > bottom:
                raise ValueError(f"{page['id']}: text does not fit; shorten it or enlarge the page")
            draw.text((x - bounds[0], y - bounds[1]), line, font=font, fill=fill)
            y += line_height
        y += size * .7
    draw.rectangle(art, fill=spec['image_background'])
    return image, art


def prepare(path, font_path=None):
    path = Path(path).absolute()
    data = json.loads(read_bytes(path, MAX_JSON_BYTES).decode('utf-8-sig'))
    only(data, {'schema_version', 'title', 'layout', 'width', 'height', 'background', 'foreground',
                'accent', 'image_background', 'font', 'font_sha256', 'pages'}, 'storybook')
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('schema_version must be 1')
    text(data.get('title'), 'title', 200)
    layout = data.get('layout', 'landscape')
    if layout not in ('landscape', 'portrait'):
        raise ValueError('layout must be landscape or portrait')
    spec = copy.deepcopy(data)
    spec['layout'] = layout
    w, h = (960, 640) if layout == 'landscape' else (640, 960)
    for key, default in (('width', w), ('height', h)):
        spec[key] = render.integer(data.get(key, default), key, 256, 1280)
    w, h = spec['width'], spec['height']
    divisor = math.gcd(w, h)
    if w % 2 or h % 2 or max(w // divisor, h // divisor) > 99:
        raise ValueError('Dimensions must be even, with reduced ratio terms at most 99')
    if (layout == 'landscape' and w <= h) or (layout == 'portrait' and w >= h):
        raise ValueError('Dimensions must match the selected layout')
    for key, default in (('background', '#F2EDE4'), ('foreground', '#263A38'),
                         ('accent', '#B84329'), ('image_background', '#FFFFFF')):
        spec[key] = color(data.get(key, default), key)
    pages = data.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= 24:
        raise ValueError('pages must contain 1..24 entries')
    if font_path and data.get('font_sha256'):
        raise ValueError('Pinned project font cannot be overridden; edit a copy deliberately')
    if font_path is None:
        if 'font' in data:
            font_path = local(path.parent, data['font'])
        else:
            try:
                font_path = ImageFont.truetype('DejaVuSans.ttf', 20).path
            except OSError as exc:
                raise ValueError('No default DejaVu Sans found; supply a licensed local font with --font') from exc
    font_raw = read_bytes(font_path, MAX_FONT_BYTES)
    pin(font_raw, data.get('font_sha256'), 'Font')
    snapshots, entries, seen = [], [], set()
    total_bytes = total_pixels = 0
    for index, page in enumerate(pages, 1):
        only(page, {'id', 'source', 'source_sha256', 'heading', 'text'}, 'page')
        sid = page.get('id')
        if not isinstance(sid, str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}', sid) or sid.lower() in seen:
            raise ValueError('Page IDs must be unique safe ASCII identifiers')
        seen.add(sid.lower())
        text(page.get('heading'), 'heading', 100)
        text(page.get('text'), 'text', 800)
        page_base(spec, page, index, len(pages), font_raw)  # Reject clipping before any output.
        raw = read_bytes(local(path.parent, page.get('source')), cli.MAX_GIF_BYTES)
        total_bytes += len(raw)
        if total_bytes > MAX_INPUT_BYTES:
            raise ValueError('Sources exceed the combined 128 MiB byte budget')
        pin(raw, page.get('source_sha256'), sid)
        frames, delays, loop = cli.validate_gif(io.BytesIO(raw))
        dimensions = [frame.size for frame in frames]
        count = len(frames)
        del frames
        pixels = count * w * h
        total_pixels += pixels
        if pixels > MAX_PAGE_PIXELS or total_pixels > MAX_PROJECT_PIXELS:
            raise ValueError('Story pages exceed the rendered pixel budget; use smaller dimensions or fewer pages')
        if len(set(dimensions)) != 1:
            raise ValueError('Source frames must use one consistent canvas')
        snapshots.append(raw)
        entries.append({'id': sid, 'source_sha256': digest(raw), 'source_frames': count,
                        'source_width': dimensions[0][0], 'source_height': dimensions[0][1],
                        'frame_durations_ms': delays, 'duration_ms': sum(delays), 'source_loop': loop})
    report = {'schema_version': 1, 'provider_calls': 0, 'width': w, 'height': h, 'layout': layout,
              'duration_ms': sum(e['duration_ms'] for e in entries), 'pages': entries,
              'font_sha256': digest(font_raw), 'repeat': False, 'audio': False,
              'verification': 'decoded-sources-and-text-fit; page-encoding-pending',
              'notes': ['Existing actions only; no new character poses, interpolation or page-turn animation.',
                        'Each source plays once with its original delays; no added reading holds.',
                        'Opaque GIF pages use at most 256 colors; review text glyphs, color and actual playback.',
                        'Film uses 50 fps to preserve 20 ms source steps; other delays may round by up to 10 ms per page.']}
    return spec, snapshots, font_raw, report


def compose(spec, raw, base, art):
    frames = []
    x, y, right, bottom = art
    with Image.open(io.BytesIO(raw)) as source:
        for frame in ImageSequence.Iterator(source):
            image = base.copy()
            drawing = ImageOps.contain(frame.convert('RGBA'), (right - x, bottom - y), Image.Resampling.LANCZOS)
            px = x + (right - x - drawing.width) // 2
            py = y + (bottom - y - drawing.height) // 2
            image.paste(drawing, (px, py), drawing)
            frames.append(image)
    return frames


def export_pages(path, out, font_path=None, dry_run=False):
    out = Path(os.path.abspath(out))  # Do not resolve away a dangling output symlink.
    if os.path.lexists(out):
        raise ValueError('Output must be a new directory; existing projects are never overwritten')
    spec, snapshots, font_raw, report = prepare(path, font_path)
    if dry_run:
        return report
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.story-pages-', dir=out.parent) as temporary:
        stage = Path(temporary) / 'project'
        stage.mkdir()
        for folder in ('sources', 'pages', 'review'):
            (stage / folder).mkdir()
        (stage / 'font.ttf').write_bytes(font_raw)
        portable = copy.deepcopy(spec)
        portable.update(font='font.ttf', font_sha256=digest(font_raw))
        total = sum(map(len, snapshots)) + len(font_raw)
        shots = []
        for index, (page, raw, record) in enumerate(zip(spec['pages'], snapshots, report['pages']), 1):
            sid = page['id']
            source_name = f'sources/{sid}.gif'
            (stage / source_name).write_bytes(raw)
            portable['pages'][index - 1].update(source=source_name, source_sha256=digest(raw))
            base, art = page_base(spec, page, index, len(spec['pages']), font_raw)
            frames = compose(spec, raw, base, art)
            target = stage / 'pages' / f'{sid}.gif'
            # Per-frame palettes retain changing colors. Pillow may coalesce
            # identical drawings, so verify timing rather than claim new frames.
            frames[0].save(target, save_all=True, append_images=frames[1:], duration=record['frame_durations_ms'],
                           optimize=False, disposal=1)
            del frames
            encoded = read_bytes(target, cli.MAX_GIF_BYTES)
            with Image.open(io.BytesIO(encoded)) as check:
                if check.n_frames < 2:
                    raise ValueError('Page has no visible animation after resizing/palette conversion; use larger dimensions or a clearer action')
            decoded, delays, loop = cli.validate_gif(io.BytesIO(encoded))
            if (sum(delays) != record['duration_ms'] or loop is not None or
                    any(frame.size != (spec['width'], spec['height']) for frame in decoded)):
                raise ValueError('Encoded page failed dimensions/timing/play-once verification')
            first = stage / 'review' / f'{sid}-first.png'
            last = stage / 'review' / f'{sid}-last.png'
            decoded[0].save(first)
            decoded[-1].save(last)
            record.update(output=f'pages/{sid}.gif', gif_sha256=digest(encoded), encoded_frames=len(decoded),
                          encoded_frame_durations_ms=delays, first=f'review/{sid}-first.png',
                          last=f'review/{sid}-last.png', image_box=list(art))
            del decoded
            total += len(encoded) + first.stat().st_size + last.stat().st_size
            if total > MAX_OUTPUT_BYTES:
                raise ValueError('Project exceeds the 256 MiB output byte budget')
            shots.append({'id': sid, 'source': record['output'], 'first_frame_target': 'Review the first page frame',
                          'last_frame_target': 'Review the last page frame', 'transition': 'cut'})
        divisor = math.gcd(spec['width'], spec['height'])
        film = {'schema_version': 1, 'title': spec['title'], 'style_bible': 'Offline storybook composition of existing actions. Review identity and cuts.',
                'ratio': f"{spec['width'] // divisor}:{spec['height'] // divisor}",
                'width': spec['width'], 'height': spec['height'], 'fps': 50, 'shots': shots}
        report['verification'] = 'decoded-all-page-frames; visual-review-required'
        for name, value in (('storybook.json', portable), ('film.json', film), ('pages.json', report)):
            (stage / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if os.path.lexists(out):
            raise ValueError('Output appeared during export; refusing to overwrite')
        stage.rename(out)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('story', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--font', type=Path, help='Licensed local TrueType/OpenType font; copied for reproducibility')
    parser.add_argument('--dry-run', action='store_true', help='Decode sources and check text fit, without output writes')
    args = parser.parse_args()
    try:
        print(json.dumps(export_pages(args.story, args.out, args.font, args.dry_run), indent=2))
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
