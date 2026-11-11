"""Independent, real-GIF checks for the offline exact-palette bundle workflow."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import GifImagePlugin, Image
from gif_cinema import pixel


def indexed(colors, values, size=None, transparent=None):
    image = Image.frombytes('P', size or (len(values), 1), bytes(values))
    image.putpalette([v for color in colors for v in color] + [0] * (768 - 3 * len(colors)))
    if transparent is not None:
        image.info['transparency'] = transparent
    return image


def gif_bytes(frames, delays=None, loop=0, disposals=None):
    """Use Pillow's block writer to prevent fixture frame coalescing/optimization."""
    target = io.BytesIO()
    for i, frame in enumerate(frames):
        options = {'duration': (delays or [30] * len(frames))[i],
                   'disposal': (disposals or [1] * len(frames))[i],
                   'include_color_table': bool(i), 'optimize': False}
        if loop is not None:
            options['loop'] = loop
        if 'transparency' in frame.info:
            options['transparency'] = frame.info['transparency']
            options['background'] = frame.info['transparency']
        if i == 0:
            for block in GifImagePlugin.getheader(frame, info=options)[0]:
                target.write(block)
        for block in GifImagePlugin.getdata(frame, **options):
            target.write(block)
    target.write(b';')
    return target.getvalue()


def timeline(path, scale=1):
    """Compare decoded display runs, not encoder-specific stored frame counts."""
    runs = []
    with Image.open(path) as image:
        loop = image.info.get('loop')
        size = (image.width * scale, image.height * scale)
        for index in range(image.n_frames):
            image.seek(index)
            frame = image.convert('RGBA').resize(size, Image.Resampling.NEAREST)
            raw = bytearray(frame.tobytes())
            for offset in range(0, len(raw), 4):
                if raw[offset + 3] == 0:
                    raw[offset:offset + 3] = b'\0\0\0'
            key = bytes(raw)
            delay = image.info.get('duration', 0)
            if runs and runs[-1][0] == key:
                runs[-1] = (key, runs[-1][1] + delay)
            else:
                runs.append((key, delay))
    return size, loop, runs


def tables(raw):
    """Walk GIF blocks independently; return global table and local-table count."""
    if not raw[10] & 128:
        raise AssertionError('Missing global palette')
    end = 13 + 3 * 2 ** ((raw[10] & 7) + 1)
    global_table = raw[13:end]
    pos, local = end, 0
    while raw[pos] != 0x3b:
        tag = raw[pos]
        if tag == 0x21:
            pos += 2
        elif tag == 0x2c:
            flags = raw[pos + 9]
            pos += 10
            if flags & 128:
                local += 1
                pos += 3 * 2 ** ((flags & 7) + 1)
            pos += 1  # LZW minimum code size
        else:
            raise AssertionError('Invalid GIF block')
        while raw[pos]:
            pos += raw[pos] + 1
        pos += 1
    return global_table, local


class PixelWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = self.root / 'art.gif'
        self.out = self.root / 'bundle'
        self.palette = self.root / 'requested.json'
        self.colors = ['#1e2832', '#1f2832', '#c81433']
        frames = [indexed([(30, 40, 50), (31, 40, 50)], [0] * 15 + [1], (4, 4)),
                  indexed([(200, 20, 51), (30, 40, 50)], [0] + [1] * 15, (4, 4))]
        self.source.write_bytes(gif_bytes(frames, [20, 170]))

    def save_palette(self, colors=None):
        self.palette.write_text(json.dumps({'format': 'gif-cinema-palette',
            'schema_version': 1, 'colors': self.colors if colors is None else colors}), encoding='utf-8')

    def rehash(self):
        receipt_path = self.out / 'receipt.json'
        receipt = json.loads(receipt_path.read_text())
        receipt['files'] = {p.relative_to(self.out).as_posix():
            {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in self.out.rglob('*') if p.is_file() and p != receipt_path}
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')

    def test_build_preserves_exact_rare_pixels_timing_and_sources_offline(self):
        self.save_palette(['#123456'] + self.colors)
        before = self.source.read_bytes(), self.palette.read_bytes()
        with patch.object(socket, 'socket', side_effect=AssertionError('Network forbidden')):
            result = pixel.build(self.source, self.out, scale=3, palette_path=self.palette)
            self.assertIsInstance(result, dict)
            self.assertIsInstance(pixel.verify(self.out), dict)
        self.assertEqual(timeline(self.source, 3), timeline(self.out / 'preview.gif'))
        self.assertEqual(before, (self.source.read_bytes(), self.palette.read_bytes()))
        self.assertEqual((self.out / 'source.gif').read_bytes(), before[0])
        self.assertEqual((self.out / 'requested-palette.json').read_bytes(), before[1])
        for name in ('palette.json', 'frames/0000.png', 'loop-seam.png', 'palette.png', 'receipt.json'):
            self.assertTrue((self.out / name).is_file(), name)
        table, locals_count = tables((self.out / 'preview.gif').read_bytes())
        self.assertEqual(locals_count, 0)
        self.assertEqual(table[:12], bytes.fromhex('1234561e28321f2832c81433'))

    def test_native_absent_infinite_and_finite_loop_preserved(self):
        frame = indexed([(10, 11, 12)], [0, 0])
        for loop in (None, 0, 3):
            with self.subTest(loop=loop):
                self.source.write_bytes(gif_bytes([frame, frame], [20, 70], loop))
                out = self.root / ('loop-' + str(loop))
                pixel.build(self.source, out)
                self.assertEqual(timeline(self.source), timeline(out / 'preview.gif'))

    def test_local_tables_and_disposal_transparency_are_decoded_before_scaling(self):
        colors = [(99, 88, 77), (0, 0, 0), (1, 2, 3)]
        frames = [indexed(colors, [1, 0, 0, 0], (2, 2), 0),
                  indexed(colors, [0, 2, 0, 0], (2, 2), 0),
                  indexed(colors, [0, 0, 1, 0], (2, 2), 0)]
        for disposal in (2, 3):
            with self.subTest(disposal=disposal):
                self.source.write_bytes(gif_bytes(frames, [40, 90, 20], 2, [1, disposal, 1]))
                self.assertGreater(tables(self.source.read_bytes())[1], 0)
                out = self.root / ('disposal-' + str(disposal))
                pixel.build(self.source, out, scale=2)
                self.assertEqual(timeline(self.source, 2), timeline(out / 'preview.gif'))

    def test_empty_palette_only_usable_for_fully_transparent_art(self):
        self.save_palette([])
        with self.assertRaises(ValueError):
            pixel.build(self.source, self.out, palette_path=self.palette)
        self.source.write_bytes(gif_bytes([indexed([(77, 88, 99)], [0] * 4, (2, 2), 0)]))
        pixel.build(self.source, self.out, palette_path=self.palette)
        self.assertEqual(timeline(self.source), timeline(self.out / 'preview.gif'))

    def test_inspect_overfull_union_but_build_never_quantizes(self):
        frames = [indexed([(i, 0, 0) for i in range(256)], list(range(256))),
                  indexed([(0, 1, 0)], [0] * 256)]
        self.source.write_bytes(gif_bytes(frames))
        self.assertIsInstance(pixel.inspect(self.source), dict)
        with self.assertRaises(ValueError):
            pixel.build(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_invalid_scales_missing_colors_and_strict_palette_json(self):
        for scale in (True, False, 0, 9, -1, 1.5, '2', None):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                pixel.build(self.source, self.out, scale=scale)
        self.save_palette(['#000000'])
        with self.assertRaises(ValueError):
            pixel.build(self.source, self.out, palette_path=self.palette)
        valid = {'format': 'gif-cinema-palette', 'schema_version': 1, 'colors': self.colors}
        invalids = [[], None, dict(valid, unknown=True), dict(valid, schema_version=True),
                    dict(valid, schema_version=1.0), dict(valid, colors='red'),
                    dict(valid, colors=['red']), dict(valid, colors=[True]),
                    dict(valid, colors=['#1e2832', '#1e2832']), dict(valid, format='other')]
        for value in invalids:
            self.palette.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(ValueError):
                pixel.build(self.source, self.out, palette_path=self.palette)
        self.palette.write_text('{"format":"gif-cinema-palette","schema_version":1,"colors":[],"colors":[]}')
        with self.assertRaises(ValueError):
            pixel.build(self.source, self.out, palette_path=self.palette)
        self.assertFalse(self.out.exists())

    def test_inspect_and_dry_run_write_nothing_and_make_no_network_calls(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with patch.object(socket, 'socket', side_effect=AssertionError('Network forbidden')):
            self.assertIsInstance(pixel.inspect(self.source, scale=2), dict)
            self.assertIsInstance(pixel.build(self.source, self.out, dry_run=True), dict)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_bundle_can_be_moved_and_no_requested_palette_is_invented(self):
        pixel.build(self.source, self.out)
        self.assertFalse((self.out / 'requested-palette.json').exists())
        moved = self.root / 'moved'
        self.out.rename(moved)
        self.source.unlink()
        self.assertIsInstance(pixel.verify(moved), dict)

    def test_existing_output_marker_and_symlink_sources_are_protected(self):
        self.out.mkdir()
        marker = self.out / 'keep.txt'
        marker.write_text('Never replace me')
        with self.assertRaises((ValueError, FileExistsError)):
            pixel.build(self.source, self.out)
        self.assertEqual(marker.read_text(), 'Never replace me')
        alias = self.root / 'alias.gif'
        try:
            alias.symlink_to(self.source)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError):
            pixel.inspect(alias)
        with self.assertRaises(ValueError):
            pixel.build(alias, self.root / 'new')

    def test_symlinked_palette_output_parent_and_bundle_entries_are_rejected(self):
        self.save_palette()
        alias = self.root / 'palette-alias.json'
        try:
            alias.symlink_to(self.palette)
            (self.root / 'parent-alias').symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError):
            pixel.build(self.source, self.out, palette_path=alias)
        with self.assertRaises(ValueError):
            pixel.build(self.source, self.root / 'parent-alias' / 'hidden-bundle')
        self.assertFalse((self.root / 'hidden-bundle').exists())
        pixel.build(self.source, self.out)
        frame = self.out / 'frames/0000.png'
        snapshot = self.root / 'frame.png'
        frame.rename(snapshot)
        frame.symlink_to(snapshot)
        with self.assertRaises(ValueError):
            pixel.verify(self.out)

    def test_receipt_cannot_hide_missing_or_extra_files(self):
        for operation in ('delete', 'extra'):
            with self.subTest(operation=operation):
                if self.out.exists():
                    shutil.rmtree(self.out)
                pixel.build(self.source, self.out)
                if operation == 'delete':
                    (self.out / 'palette.png').unlink()
                else:
                    (self.out / 'unexpected.txt').write_text('not a bundle artifact')
                self.rehash()
                with self.assertRaises(ValueError):
                    pixel.verify(self.out)

    def test_urls_rejected_without_network(self):
        with patch.object(socket, 'socket', side_effect=AssertionError('Network forbidden')):
            with self.assertRaises(ValueError):
                pixel.inspect('https://example.com/art.gif')

    def test_rehashed_tampering_fails_semantic_verification(self):
        self.save_palette(['#123456'] + self.colors)
        for target in ('frames/0000.png', 'palette.png', 'loop-seam.png', 'preview.gif',
                       'source.gif', 'requested-palette.json', 'palette.json'):
            with self.subTest(target=target):
                if self.out.exists():
                    shutil.rmtree(self.out)
                pixel.build(self.source, self.out, palette_path=self.palette)
                path = self.out / target
                if path.suffix == '.png':
                    with Image.open(path) as image:
                        changed = image.convert('RGBA')
                    changed.putpixel((0, 0), (19, 20, 21, 255))
                    changed.save(path)
                elif path.suffix == '.gif':
                    raw = bytearray(path.read_bytes())
                    raw[13] ^= 1  # Modify a used RGB entry, preserving a well-formed GIF.
                    path.write_bytes(raw)
                else:
                    value = json.loads(path.read_text())
                    value['colors'][0] = '#654321'
                    path.write_text(json.dumps(value))
                self.rehash()
                with self.assertRaises(ValueError):
                    pixel.verify(self.out)

    def test_rehashed_native_delay_tampering_is_rejected(self):
        pixel.build(self.source, self.out)
        path = self.out / 'preview.gif'
        raw = bytearray(path.read_bytes())
        gce = raw.index(b'\x21\xf9\x04')
        raw[gce + 4] += 1
        path.write_bytes(raw)
        self.rehash()
        with self.assertRaises(ValueError):
            pixel.verify(self.out)

    def test_output_budget_failure_cleans_staging_and_preserves_source(self):
        before = self.source.read_bytes()
        with patch.object(pixel, 'MAX_OUTPUT_BYTES', 1), self.assertRaises(ValueError):
            pixel.build(self.source, self.out)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_source_or_palette_edit_after_staging_verification_prevents_publication(self):
        self.save_palette()
        original_verify = pixel.verify
        for changed in (self.source, self.palette):
            with self.subTest(changed=changed.name):
                before = changed.read_bytes()
                def verify_then_edit(directory):
                    result = original_verify(directory)
                    changed.write_bytes(before + b'\n')
                    return result
                with patch.object(pixel, 'verify', side_effect=verify_then_edit):
                    with self.assertRaisesRegex(ValueError, 'changed during build'):
                        pixel.build(self.source, self.out, palette_path=self.palette)
                self.assertFalse(self.out.exists())
                self.assertEqual(changed.read_bytes(), before + b'\n')
                self.assertEqual(set(self.root.iterdir()), {self.source, self.palette})
                changed.write_bytes(before)

    def test_failed_staged_verification_never_publishes_partial_bundle(self):
        before = self.source.read_bytes()
        with patch.object(pixel, 'verify', side_effect=ValueError('verification failed')):
            with self.assertRaisesRegex(ValueError, 'verification failed'):
                pixel.build(self.source, self.out)
        self.assertEqual(list(self.root.iterdir()), [self.source])
        self.assertEqual(self.source.read_bytes(), before)

    def test_cli_real_inspect_dry_run_build_and_verify(self):
        commands = [ ['inspect', str(self.source)],
            ['build', str(self.source), '--out', str(self.root / 'plan'), '--dry-run'],
            ['build', str(self.source), '--out', str(self.out), '--scale', '2'],
            ['verify', str(self.out)] ]
        for args in commands:
            result = subprocess.run([sys.executable, '-m', 'gif_cinema', 'pixel', *args],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'plan').exists())
        self.assertEqual(timeline(self.source, 2), timeline(self.out / 'preview.gif'))


if __name__ == '__main__':
    unittest.main()
