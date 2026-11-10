"""Build a bounded offline GIF collection, static gallery and verified ZIP.

Only local GIFs and existing GIF Cinema layer scenes are accepted. No provider
calls, JavaScript animation, HTML input, remote URLs or executable recipes.
"""
import argparse
import bisect
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import struct
import tempfile
import zipfile

from PIL import Image, ImageDraw, ImageSequence

from . import cli, layers

FORMAT = 'gif-cinema-factory'
MAX_MANIFEST_BYTES = 128 * 1024
MAX_ITEMS = 12
RESERVED_IDS = {'con', 'prn', 'aux', 'nul', *('com' + str(n) for n in range(1, 10)), *('lpt' + str(n) for n in range(1, 10))}
MAX_GIF_BYTES = 32 * 1024 * 1024
MAX_FRAMES = 512
MAX_PIXELS = 64 * 1024 * 1024
MAX_BATCH_PIXELS = 256 * 1024 * 1024
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_CATALOG_BYTES = 2 * 1024 * 1024
NOTICE = 'Technical verification is not visual approval. Inspect the delivered GIFs; visual review and user acceptance remain pending.'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON field: {key}')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f'Non-finite JSON number: {value}')
    try:
        result = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Expected UTF-8 JSON') from exc
    if not isinstance(result, dict):
        raise ValueError('Expected a JSON object')
    return result


def safe_input(base, name):
    name = layers.source_name(name)
    path = base / name
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Factory inputs must not use symlinks')
    if not path.resolve().is_relative_to(base.resolve()):
        raise ValueError('Input path escapes the manifest directory')
    return path


def decode_gif(raw):
    if len(raw) > MAX_GIF_BYTES:
        raise ValueError('Factory GIF exceeds 32 MiB')
    stats = cli.check_gif_limits(raw, max_frames=MAX_FRAMES, max_pixel_frames=MAX_PIXELS, fixed_canvas=True)
    frames, delays, hashes = [], [], []
    try:
        with Image.open(io.BytesIO(raw)) as source:
            loop = source.info.get('loop')
            for frame in ImageSequence.Iterator(source):
                delay = frame.info.get('duration')
                if type(delay) is not int or not 20 <= delay <= 60000:
                    raise ValueError('GIF delays must be 20..60000 ms')
                if frame.size != (stats['width'], stats['height']):
                    raise ValueError('GIF canvas changed during decode')
                rgba = frame.convert('RGBA').copy()
                rgba.info.clear()
                frames.append(rgba)
                delays.append(delay)
                hashes.append(digest(rgba.tobytes()))
    except (OSError, EOFError, Image.DecompressionBombError) as exc:
        raise ValueError('Invalid or unsafe GIF') from exc
    if not frames or sum(delays) > 120000:
        raise ValueError('GIF must contain drawings and last at most 120 seconds')
    info = {'width': stats['width'], 'height': stats['height'], 'frames': len(frames),
            'duration_ms': sum(delays), 'delays_ms': delays, 'loop': loop,
            'animated': len(set(hashes)) > 1, 'rgba_sha256': hashes}
    info['motion_sha256'] = digest(json_bytes(info))
    return frames, info


def prepare_scene(path):
    scene = layers.parse_scene(layers.read_regular(path, layers.MAX_SCENE_BYTES))
    for layer in scene['layers']:
        if layer['type'] in ('gif', 'image', 'sprites'):
            safe_input(path.parent, layer['source'])
    return layers.prepare_scene(path)


def scene_signature(prepared):
    return {'scene_sha256': prepared['source_sha256'],
            'assets': {name: asset['sha256'] for name, asset in prepared['assets'].items()}}


def plan_factory(manifest):
    manifest = Path(manifest).absolute()
    if any(p.is_symlink() for p in (manifest, *manifest.parents)):
        raise ValueError('Manifest must not use symlinks')
    raw = layers.read_regular(manifest, MAX_MANIFEST_BYTES)
    data = parse_json(raw)
    layers.require_fields(data, ('format', 'schema_version', 'title', 'items'),
                          ('format', 'schema_version', 'title', 'items'), 'Factory manifest')
    if data['format'] != FORMAT or type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise ValueError('Expected gif-cinema-factory schema_version 1')
    layers.text_value(data['title'], 'title', 120)
    if not isinstance(data['items'], list) or not 1 <= len(data['items']) <= MAX_ITEMS:
        raise ValueError('Factory requires 1..12 entries')
    entries, ids, motions, total_bytes, total_pixels = [], set(), set(), 0, 0
    for item in data['items']:
        layers.require_fields(item, ('id', 'title', 'group', 'caption', 'gif', 'scene', 'sha256'),
                              ('id', 'title', 'sha256'), 'Entry')
        sid = item['id']
        if not isinstance(sid, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', sid) or sid in ids or sid in RESERVED_IDS:
            raise ValueError('Entry IDs must be unique lowercase ASCII slugs, at most 40 characters')
        ids.add(sid)
        for key, limit in (('title', 120), ('group', 80), ('caption', 500)):
            if key in item:
                layers.text_value(item[key], key, limit)
        if not isinstance(item['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', item['sha256']):
            raise ValueError('Every entry requires its lowercase source SHA-256')
        kinds = set(item) & {'gif', 'scene'}
        if len(kinds) != 1:
            raise ValueError('Every entry requires exactly one of gif or scene')
        kind = next(iter(kinds))
        path = safe_input(manifest.parent, item[kind])
        source = layers.read_regular(path, MAX_GIF_BYTES if kind == 'gif' else layers.MAX_SCENE_BYTES)
        if digest(source) != item['sha256']:
            raise ValueError(f'{sid}: source hash mismatch')
        entry = dict(item, kind=kind)
        if kind == 'gif':
            frames, info = decode_gif(source)
            del frames
            if info['motion_sha256'] in motions:
                raise ValueError('Duplicate decoded GIF entries are not distinct animations')
            motions.add(info['motion_sha256'])
            entry['expected'] = info
            size = len(source)
            pixels = info['width'] * info['height'] * info['frames']
        else:
            # Check the cheap output budget before constructing layer raster caches.
            scene = layers.parse_scene(source)
            count = scene['duration_ms'] * scene['fps'] // 1000
            pixels = scene['width'] * scene['height'] * count
            if count > MAX_FRAMES or pixels > MAX_PIXELS:
                raise ValueError(f'{sid}: scene exceeds factory review limits; lower resolution/duration')
            prepared = prepare_scene(path)
            if prepared['source_sha256'] != item['sha256']:
                raise ValueError(f'{sid}: scene changed during planning')
            entry['signature'] = scene_signature(prepared)
            entry['expected'] = {key: scene[key] for key in ('width', 'height', 'duration_ms', 'loop')}
            entry['expected']['render_frames'] = count
            size = len(source) + sum(len(asset['raw']) for asset in prepared['assets'].values())
            del prepared
        total_bytes += size
        total_pixels += pixels
        if total_bytes > MAX_INPUT_BYTES or total_pixels > MAX_BATCH_PIXELS:
            raise ValueError('Factory exceeds aggregate input/decoded-work budget; use a smaller batch')
        entries.append(entry)
    return {'format': FORMAT, 'schema_version': 1, 'title': data['title'],
            'manifest_sha256': digest(raw), 'provider_calls': 0, 'status': 'planned',
            'input_bytes': total_bytes, 'decoded_pixel_frames_upper_bound': total_pixels,
            'entries': entries, 'visual_review': 'pending', 'notice': NOTICE}


# Tiny original 5x7 numeric labels avoid platform/default-font differences in
# regenerated contact sheets. These glyphs are drawing data, not a font download.
LABEL_GLYPHS = dict(zip('0123456789/ms', (
    ('01110','10001','10011','10101','11001','10001','01110'),
    ('00100','01100','00100','00100','00100','00100','01110'),
    ('01110','10001','00001','00010','00100','01000','11111'),
    ('11110','00001','00001','01110','00001','00001','11110'),
    ('00010','00110','01010','10010','11111','00010','00010'),
    ('11111','10000','10000','11110','00001','00001','11110'),
    ('01110','10000','10000','11110','10001','10001','01110'),
    ('11111','00001','00010','00100','01000','01000','01000'),
    ('01110','10001','10001','01110','10001','10001','01110'),
    ('01110','10001','10001','01111','00001','00001','01110'),
    ('00001','00010','00010','00100','01000','01000','10000'),
    ('00000','00000','11010','10101','10101','10101','10101'),
    ('00000','00000','01111','10000','01110','00001','11110'),
)))


def draw_label(draw, position, value):
    x, y = position
    for char in value:
        for row, line in enumerate(LABEL_GLYPHS.get(char, ())):
            for column, pixel in enumerate(line):
                if pixel == '1':
                    draw.rectangle((x + column * 2, y + row * 2, x + column * 2 + 1, y + row * 2 + 1), fill='#f5f4f1')
        x += 12


def preview_bytes(frames, delays):
    """Only actual composited output GIF drawings, selected by elapsed time."""
    ends, total = [], 0
    for delay in delays:
        total += delay
        ends.append(total)
    selected = [0, bisect.bisect_right(ends, total // 4), bisect.bisect_right(ends, total // 2),
                bisect.bisect_right(ends, total * 3 // 4), len(frames) - 1]
    poster = frames[selected[2]].copy()
    poster.thumbnail((480, 360), Image.Resampling.LANCZOS)
    sheet = Image.new('RGB', (240 * 5, 208), '#171a22')
    draw = ImageDraw.Draw(sheet)
    for column, index in enumerate(selected):
        image = frames[index].copy()
        image.thumbnail((232, 176), Image.Resampling.LANCZOS)
        x, y = column * 240 + (240 - image.width) // 2, (176 - image.height) // 2
        # A neutral checker makes preserved alpha visible without editing the GIF.
        for cy in range(y, y + image.height, 12):
            for cx in range(x, x + image.width, 12):
                fill = '#333842' if ((cx - x) // 12 + (cy - y) // 12) % 2 else '#484e59'
                draw.rectangle((cx, cy, min(cx + 11, x + image.width - 1), min(cy + 11, y + image.height - 1)), fill=fill)
        sheet.paste(image, (x, y), image)
        start = 0 if index == 0 else ends[index - 1]
        draw_label(draw, (column * 240 + 8, 184), f'{index} / {start} ms')
    result = []
    for image in (poster, sheet):
        output = io.BytesIO()
        image.save(output, format='PNG')
        result.append(output.getvalue())
    return result, selected


def gallery_html(catalog):
    esc = html.escape
    cards = []
    for item in catalog['items']:
        info = item['gif_info']
        loop = 'plays once' if info['loop'] is None else ('loops forever' if info['loop'] == 0 else f"loop metadata: {info['loop']}")
        status = 'animated GIF' if info['animated'] else 'single visual state'
        cards.append(f'''<article><p class="group">{esc(item['group'])}</p><h2>{esc(item['title'])}</h2>
<picture><source media="(prefers-reduced-motion: reduce)" srcset="{item['poster']}"><img src="{item['gif']}" alt="{esc(item['caption'], quote=True)}" width="{info['width']}" height="{info['height']}" loading="lazy"></picture>
<p>{esc(item['caption'])}</p><p class="facts">{info['width']} × {info['height']} · {info['duration_ms'] / 1000:g} s · {info['frames']} drawings · {loop}<br>{status} · silent · review pending</p>
<p><a href="{item['gif']}" download>Download GIF</a> <a href="{item['poster']}">Still preview</a> <a href="{item['sheet']}">Decoded samples</a></p></article>''')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{esc(catalog['title'])}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#10131b;color:#f6f1e8;font:16px/1.6 system-ui,sans-serif}}main{{max-width:1160px;margin:auto;padding:40px 22px}}h1{{font-size:clamp(32px,6vw,64px);line-height:1.1;margin:12px 0 24px}}h2{{margin:0 0 16px;font-size:23px}}header{{max-width:800px;margin-bottom:40px}}.eyebrow,.group{{color:#dcae8a;letter-spacing:.08em;text-transform:uppercase;font-size:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr));gap:24px}}article{{border:1px solid #393d47;border-radius:12px;padding:22px;background:#191d27}}picture{{display:block;background:#0d1016;border-radius:8px;overflow:hidden}}img{{display:block;width:100%;height:auto;max-height:380px;object-fit:contain}}.facts{{font-size:13px;color:#c4c7d0}}a{{color:#ffcfaa;text-underline-offset:4px;margin-right:14px}}a:focus-visible{{outline:2px solid #f6f1e8;outline-offset:4px}}footer{{margin-top:40px;color:#c4c7d0;font-size:14px}}
</style></head><body><main><header><p class="eyebrow">GIF Cinema / Offline collection</p><h1>{esc(catalog['title'])}</h1><p>Local GIF files, actual decoded previews, no scripts or remote assets. Reduced-motion mode shows still previews.</p></header>
<section class="grid" aria-label="GIF collection">{''.join(cards)}</section>
<footer><p>{esc(NOTICE)}</p><a href="catalog.json">Timing, provenance and checksums</a></footer></main></body></html>\n'''.encode('utf-8')


def write_archive(root, files):
    archive = root / 'collection.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_STORED) as handle:
        for name in sorted(files):
            entry = zipfile.ZipInfo('collection/' + name, (2026, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_STORED
            handle.writestr(entry, layers.read_regular(root / name, MAX_OUTPUT_BYTES))
    return archive


def verify_factory(root):
    """Read the saved gallery and ZIP without extracting or trusting archive paths."""
    root = Path(root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('Collection must not use symlinks')
    raw = layers.read_regular(root / 'catalog.json', MAX_CATALOG_BYTES)
    catalog = parse_json(raw)
    if catalog.get('format') != FORMAT or type(catalog.get('schema_version')) is not int or catalog['schema_version'] != 1:
        raise ValueError('Invalid factory catalog')
    files = catalog.get('files')
    items = catalog.get('items')
    if not isinstance(files, dict) or not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise ValueError('Invalid factory file/item list')
    expected_names = {'index.html'}
    ids, total = set(), 0
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', item['id']) or item['id'] in ids or item['id'] in RESERVED_IDS:
            raise ValueError('Invalid or duplicate saved entry ID')
        sid = item['id']; ids.add(sid)
        for key, limit in (('title', 120), ('group', 80), ('caption', 500)):
            layers.text_value(item.get(key), key, limit)
        paths = {'gif': f'gifs/{sid}.gif', 'poster': f'previews/{sid}-poster.png', 'sheet': f'previews/{sid}-sheet.png'}
        if any(item.get(key) != value for key, value in paths.items()):
            raise ValueError('Saved entry paths do not match its ID')
        expected_names.update(paths.values())
    if set(files) != expected_names:
        raise ValueError('Catalog file allowlist does not match the collection')
    for name, info in files.items():
        if not isinstance(info, dict) or set(info) != {'bytes', 'sha256'} or type(info['bytes']) is not int or not 0 <= info['bytes'] <= MAX_OUTPUT_BYTES:
            raise ValueError('Invalid output file receipt')
        total += info['bytes']
        if total > MAX_OUTPUT_BYTES:
            raise ValueError('Collection exceeds output budget')
        data = layers.read_regular(safe_input(root, name), min(MAX_OUTPUT_BYTES, info['bytes']))
        if len(data) != info['bytes'] or digest(data) != info['sha256']:
            raise ValueError(f'Output hash/length mismatch: {name}')
    layers.text_value(catalog.get('title'), 'title', 120)
    motion_hashes, decoded_pixels = set(), 0
    for item in items:
        data = layers.read_regular(root / item['gif'], MAX_GIF_BYTES)
        frames, info = decode_gif(data)
        if info != item.get('gif_info') or info['motion_sha256'] in motion_hashes:
            raise ValueError('Saved GIF timing/pixels changed or decoded entries are duplicates')
        motion_hashes.add(info['motion_sha256'])
        decoded_pixels += info['width'] * info['height'] * info['frames']
        if decoded_pixels > MAX_BATCH_PIXELS:
            raise ValueError('Collection exceeds aggregate decoded-work budget')
        previews, selected = preview_bytes(frames, info['delays_ms'])
        del frames
        if selected != item.get('preview_frames'):
            raise ValueError('Saved preview selection mismatch')
        # Compare decoded PNG pixels, not PNG encoder bytes/version.
        for key, expected in zip(('poster', 'sheet'), previews):
            with Image.open(io.BytesIO(expected)) as a, Image.open(root / item[key]) as b:
                if b.format != 'PNG' or getattr(b, 'n_frames', 1) != 1:
                    raise ValueError('Previews must be single-frame PNGs')
                if a.size != b.size or a.convert('RGBA').tobytes() != b.convert('RGBA').tobytes():
                    raise ValueError('Preview does not match actual decoded GIF pixels')
    if layers.read_regular(root / 'index.html', MAX_CATALOG_BYTES) != gallery_html(catalog):
        raise ValueError('Gallery HTML differs from the safe static template')
    expected_names.add('catalog.json')
    zip_raw = layers.read_regular(safe_input(root, 'collection.zip'), MAX_OUTPUT_BYTES + MAX_CATALOG_BYTES + 65536)
    # Our bounded, non-ZIP64 archive has no comment. Validate its central
    # directory budget before ZipFile can allocate arbitrary member metadata.
    if len(zip_raw) < 22 or zip_raw[-22:-18] != b'PK\x05\x06':
        raise ValueError('Invalid collection ZIP trailer')
    _, disk, start_disk, disk_count, count, central_bytes, offset, comment = struct.unpack('<4s4H2IH', zip_raw[-22:])
    if (disk or start_disk or comment or disk_count != len(expected_names) or count != len(expected_names)
            or central_bytes > len(expected_names) * 512 or offset + central_bytes != len(zip_raw) - 22):
        raise ValueError('Archive directory exceeds its exact allowlist/budget')
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_raw))
    except zipfile.BadZipFile as exc:
        raise ValueError('Invalid collection ZIP') from exc
    with archive:
        entries = archive.infolist()
        if len(entries) != len(expected_names) or {i.filename for i in entries} != {'collection/' + n for n in expected_names}:
            raise ValueError('Archive entries do not match the exact collection allowlist')
        for entry in entries:
            name = entry.filename.removeprefix('collection/')
            expected = {'bytes': len(raw), 'sha256': digest(raw)} if name == 'catalog.json' else files[name]
            if entry.file_size != expected['bytes'] or entry.compress_type != zipfile.ZIP_STORED or entry.is_dir() or entry.external_attr >> 16 != 0o100644:
                raise ValueError('Invalid archive file metadata')
            if digest(archive.read(entry)) != expected['sha256']:
                raise ValueError('Archive readback hash mismatch')
    return {'format': FORMAT, 'status': 'verified', 'provider_calls': 0, 'items': len(items),
            'files_verified': len(expected_names), 'zip_sha256': digest(zip_raw),
            'visual_review': 'pending', 'notice': NOTICE}


def publish_directory(stage, out):
    """Claim a new directory; publish completion catalog last, without clobbering."""
    created = []
    out.mkdir(exist_ok=False)
    try:
        for name in ('gifs', 'previews'):
            (out / name).mkdir(exist_ok=False)
            created.append(out / name)
        for path in sorted(stage.rglob('*'), key=lambda p: (p.name == 'catalog.json', p.as_posix())):
            if not path.is_file():
                continue
            target = out / path.relative_to(stage)
            cli.publish_file(path, target)
            created.append(target)
    except Exception:
        for path in reversed(created):
            if path.is_file() and not path.is_symlink():
                path.unlink()
            elif path.is_dir() and not path.is_symlink():
                try:
                    path.rmdir()
                except OSError:
                    pass
        try:
            out.rmdir()
        except OSError:
            pass
        raise


def build_factory(manifest, out, dry_run=False):
    out, manifest = Path(out).absolute(), Path(manifest).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Factory output must be a new directory without symlinks')
    plan = plan_factory(manifest)
    if dry_run:
        return plan
    out.parent.mkdir(parents=True, exist_ok=True)
    with cli.output_lock(out), tempfile.TemporaryDirectory(prefix='.factory-stage-', dir=out.parent) as temporary:
        stage, work = Path(temporary) / 'collection', Path(temporary) / 'work'
        stage.mkdir(); work.mkdir()
        (stage / 'gifs').mkdir(); (stage / 'previews').mkdir()
        catalog = {'format': FORMAT, 'schema_version': 1, 'title': plan['title'],
                   'manifest_sha256': plan['manifest_sha256'], 'provider_calls': 0,
                   'visual_review': 'pending', 'notice': NOTICE, 'items': [], 'files': {}}
        motions = set()
        for entry in plan['entries']:
            sid, kind = entry['id'], entry['kind']
            source = safe_input(manifest.parent, entry[kind])
            if kind == 'gif':
                raw = layers.read_regular(source, MAX_GIF_BYTES)
                if digest(raw) != entry['sha256']:
                    raise ValueError(f'{sid}: source changed after preflight')
                provenance = {'kind': 'existing-gif', 'source_sha256': entry['sha256']}
            else:
                prepared = prepare_scene(source)
                if scene_signature(prepared) != entry['signature']:
                    raise ValueError(f'{sid}: scene/assets changed after preflight')
                snapshot = layers.save_bundle(prepared, work / f'{sid}-input')
                del prepared
                rendered = work / f'{sid}-render'
                layers.render_scene(snapshot, rendered)
                raw = layers.read_regular(rendered / 'preview.gif', MAX_GIF_BYTES)
                provenance = {'kind': 'local-layer-render', **entry['signature']}
            frames, info = decode_gif(raw)
            if info['motion_sha256'] in motions:
                raise ValueError('Duplicate decoded output GIFs are not distinct collection entries')
            motions.add(info['motion_sha256'])
            if kind == 'scene':
                expected = entry['expected']
                if any(info[key] != expected[key] for key in ('width', 'height', 'duration_ms')) or info['loop'] != (0 if expected['loop'] else None):
                    raise ValueError('Rendered GIF differs from the planned scene')
            previews, selected = preview_bytes(frames, info['delays_ms'])
            del frames
            paths = {'gif': f'gifs/{sid}.gif', 'poster': f'previews/{sid}-poster.png', 'sheet': f'previews/{sid}-sheet.png'}
            for key, data in zip(('gif', 'poster', 'sheet'), (raw, *previews)):
                (stage / paths[key]).write_bytes(data)
            catalog['items'].append({'id': sid, 'title': entry['title'], 'group': entry.get('group', 'Collection'),
                                     'caption': entry.get('caption', entry['title']), **paths, 'provenance': provenance,
                                     'gif_info': info, 'preview_frames': selected})
            # Renderer intermediates are not delivery files and are removed per item.
            if kind == 'scene':
                shutil.rmtree(rendered)
                shutil.rmtree(snapshot.parent)
        (stage / 'index.html').write_bytes(gallery_html(catalog))
        total = 0
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                size = path.stat().st_size
                total += size
                if total > MAX_OUTPUT_BYTES:
                    raise ValueError('Factory exceeds 256 MiB output budget')
                data = layers.read_regular(path, MAX_OUTPUT_BYTES)
                catalog['files'][path.relative_to(stage).as_posix()] = {'bytes': len(data), 'sha256': digest(data)}
        encoded_catalog = json_bytes(catalog)
        if len(encoded_catalog) > MAX_CATALOG_BYTES:
            raise ValueError('Catalog exceeds 2 MiB')
        (stage / 'catalog.json').write_bytes(encoded_catalog)
        write_archive(stage, [*catalog['files'], 'catalog.json'])
        verification = verify_factory(stage)
        publish_directory(stage, out)
    return verification


def run(args):
    try:
        result = (build_factory(args.manifest, args.out, args.dry_run) if args.factory_command == 'build'
                  else verify_factory(args.directory))
    except zipfile.BadZipFile as exc:
        raise ValueError('Invalid collection ZIP') from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def add_parser(sub):
    parser = sub.add_parser('factory', help='Build/verify an offline GIF collection, static gallery and ZIP')
    commands = parser.add_subparsers(dest='factory_command', required=True)
    build = commands.add_parser('build', help='Build hash-pinned GIF/layer-scene entries without provider calls')
    build.add_argument('manifest', type=Path)
    build.add_argument('--out', type=Path, required=True)
    build.add_argument('--dry-run', action='store_true', help='Validate inputs and budgets without outputs or media processes')
    build.set_defaults(func=run)
    verify = commands.add_parser('verify', help='Decode delivered GIFs and compare previews and every ZIP member')
    verify.add_argument('directory', type=Path)
    verify.set_defaults(func=run)
    return parser


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    add_parser(sub)
    # Module invocation is equivalent to `gif-cinema factory ...`.
    args = parser.parse_args(['factory', *(argv if argv is not None else __import__('sys').argv[1:])])
    try:
        return run(args)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        parser.exit(2, f'Factory error: {exc}\n')


if __name__ == '__main__':
    main()
