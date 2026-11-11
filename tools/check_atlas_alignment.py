"""Verify authored column corrections using SYNTHETIC jitter, not an artwork repair.

python tools/check_atlas_alignment.py SOURCE_GIF --out NEW_DIR
Original GIF bytes, poses, native delays and loop are retained. No provider calls.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import tempfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gif_cinema import layers, pixel, pixel_palette as codec, sprites
from gif_cinema.cli import output_lock, publish_file

JITTER = [(0, 0), (6, -4), (-5, 6), (3, -6)]
MARGIN = 6


def local_path(value):
    text = str(value)
    if '..' in Path(text).parts:
        raise ValueError('Use local paths without traversal components')
    return pixel.local_path(text)


def verify(actual, expected, delays, loop):
    if (actual['delays_ms'] != delays or actual['loop'] != loop or
            len(actual['frames']) != len(expected) or
            any(a.size != b.size or codec.canonical_rgba(a).tobytes() !=
                codec.canonical_rgba(b).tobytes()
                for a, b in zip(actual['frames'], expected))):
        raise ValueError('Exact canonical RGBA/native-delay/loop verification failed')


def check(source, out):
    source, target = local_path(source), local_path(out)
    if target.exists() or target.is_symlink():
        raise ValueError('Output directory must be new')
    if not target.parent.is_dir() or any(p.is_symlink() for p in target.parents):
        raise ValueError('Output parent must exist and must not contain symlinks')
    raw = layers.read_regular(source, codec.MAX_BYTES)
    decoded = codec.decode(raw)
    frames, delays, loop = decoded['frames'], decoded['delays_ms'], decoded['loop']
    sprites.validate_timing(delays, loop)
    w, h = decoded['size']
    count, columns = len(frames), len(JITTER)
    rows = math.ceil(count / columns)
    cw, ch = w + 2 * MARGIN, h + 2 * MARGIN
    offsets = [[-dx, -dy] for dx, dy in JITTER]
    left = max(0, -min(dx for dx, dy in offsets))
    top = max(0, -min(dy for dx, dy in offsets))
    size = (cw + left + max(dx for dx, dy in offsets),
            ch + top + max(dy for dx, dy in offsets))
    if (cw * ch * columns * rows > sprites.MAX_SHEET_PIXELS or
            max(cw * columns, ch * rows, *size) > codec.MAX_DIMENSION or
            size[0] * size[1] > codec.MAX_PIXELS or
            size[0] * size[1] * count > codec.MAX_PIXEL_FRAMES):
        raise ValueError('Padded synthetic fixture exceeds bounded pixel budgets')
    sprites.layout_size(size, count, columns, 0)
    palette = codec.choose_palette(frames)
    if len(palette['colors']) > 255:
        raise ValueError('Padded fixture needs a transparency slot: at most 255 visible colors')
    spec = {'schema_version': 1, 'atlas': 'synthetic-jitter.png',
            'grid': [columns, rows], 'cells': [[i % columns, i // columns] for i in range(count)],
            'column_offsets': offsets, 'duration_ms': delays, 'loop': loop,
            'columns': columns, 'padding': 0}
    with output_lock(target), tempfile.TemporaryDirectory(prefix='.alignment-', dir=target.parent) as tmp:
        stage = Path(tmp)
        (stage / 'original.gif').write_bytes(raw)
        sheet = Image.new('RGBA', (cw * columns, ch * rows))
        before, expected = [], []
        for i, frame in enumerate(frames):
            dx, dy = JITTER[i % columns]
            cell = Image.new('RGBA', (cw, ch))
            cell.paste(frame, (MARGIN + dx, MARGIN + dy))
            sheet.paste(cell, ((i % columns) * cw, (i // columns) * ch))
            jittered, aligned = Image.new('RGBA', size), Image.new('RGBA', size)
            jittered.paste(cell, (left, top))
            aligned.paste(frame, (left + MARGIN, top + MARGIN))
            before.append(jittered)
            expected.append(aligned)
        sheet.save(stage / 'synthetic-jitter.png')
        (stage / 'slice.json').write_text(json.dumps(spec, indent=2) + '\n')
        loaded = sprites.load_sheet(stage / 'slice.json')
        report = sprites.export(*loaded, stage / 'sprites')
        recovered, aligned_frames = [], []
        for i in range(count):
            with Image.open(stage / 'sprites' / f'frames/{i:04d}.png') as png:
                frame = png.convert('RGBA')
            aligned_frames.append(frame)
            x, y = left + MARGIN, top + MARGIN
            recovered.append(frame.crop((x, y, x + w, y + h)))
        verify({'frames': aligned_frames, 'delays_ms': delays, 'loop': loop}, expected, delays, loop)
        verify({'frames': recovered, 'delays_ms': delays, 'loop': loop}, frames, delays, loop)
        exports = [('synthetic-jitter.gif', before), ('aligned.gif', aligned_frames),
                   ('recovered.gif', recovered)]
        for name, images in exports:
            codec.encode(images, delays, loop, codec.choose_palette(images), stage / name)
            verify(codec.decode((stage / name).read_bytes()), images, delays, loop)
        receipt = {'schema_version': 1, 'api_calls': 0,
                   'fixture': 'Added synthetic per-column jitter; not a defect discovered in the source artwork.',
                   'limitations': 'Authored translation only; no new poses, anatomy repair or artistic acceptance. Sprite animation.gif is a lossy preview; top-level GIFs are exact.',
                   'source_sha256': sprites.digest(raw), 'source_size': [w, h],
                   'frame_count': count, 'delays_ms': delays, 'duration_ms': sum(delays), 'loop': loop,
                   'synthetic_jitter': JITTER, 'inverse_column_offsets': offsets,
                   'alignment': report['transform']['column_alignment'],
                   'verified': 'Every canonical visible RGBA frame, native delay and loop; not byte-identical GIF encoding.',
                   'files_sha256': {p.relative_to(stage).as_posix(): sprites.digest(p.read_bytes())
                                    for p in sorted(stage.rglob('*')) if p.is_file()}}
        (stage / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if layers.read_regular(pixel.local_path(source), codec.MAX_BYTES) != raw:
            raise ValueError('Source changed during verification; no output published')
        target.mkdir()  # Exclusive reservation: never replace an existing directory.
        identities = {target: sprites.directory_identity(target)}
        for directory in sorted(p for p in stage.rglob('*') if p.is_dir()):
            destination = target / directory.relative_to(stage)
            if any(sprites.directory_identity(p) != identity for p, identity in identities.items()):
                raise ValueError('Output directory changed during publication')
            destination.mkdir()
            identities[destination] = sprites.directory_identity(destination)
        files = sorted(p for p in stage.rglob('*') if p.is_file() and p.name != 'verification.json')
        for path in files + [stage / 'verification.json']:
            if any(sprites.directory_identity(p) != identity for p, identity in identities.items()):
                raise ValueError('Output directory changed during publication')
            publish_file(path, target / path.relative_to(stage))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_gif')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.source_gif, args.out), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f'{exc}\n')


if __name__ == '__main__':
    main()
