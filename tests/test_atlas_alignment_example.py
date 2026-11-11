"""Technical fixtures only: no generated character art or provider requests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from gif_cinema import pixel_palette as codec
from tools import check_atlas_alignment as example


class AtlasAlignmentExampleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # macOS temporary roots may use /var -> /private/var. Resolve only
        # the fixture root; explicit input/output symlink tests remain intact.
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'source.gif'
        self.out = self.root / 'result'

    def fixture(self, count=7, loop=3):
        # Seven distinct poses cross a row boundary and leave one unused cell.
        frames = []
        for i in range(count):
            frame = Image.new('RGBA', (24, 20))
            draw = ImageDraw.Draw(frame)
            draw.rectangle((i, 2 + i, i + 4, 12 + i), fill=(200, 20, 40, 255))
            draw.point((23, 0), fill=(10, 200, 30, 255))  # Edge pixels must survive.
            frames.append(frame)
        delays = [20 + i * 10 for i in range(count)]
        codec.encode(frames, delays, loop, codec.choose_palette(frames), self.source)
        return frames, delays, loop

    def test_exact_recovery_distinct_poses_partial_final_row_and_no_network(self):
        frames, delays, loop = self.fixture()
        original = self.source.read_bytes()
        with patch('gif_cinema.cli.request_gif', side_effect=AssertionError('provider')), \
                patch('socket.socket', side_effect=AssertionError('network')):
            receipt = example.check(self.source, self.out)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual((self.out / 'original.gif').read_bytes(), original)
        self.assertEqual(receipt['source_sha256'], example.sprites.digest(original))
        self.assertEqual(receipt['api_calls'], 0)
        self.assertIn('synthetic', receipt['fixture'])
        self.assertEqual(receipt['frame_count'], 7)
        spec = json.loads((self.out / 'slice.json').read_text())
        self.assertEqual(spec['grid'], [4, 2])
        self.assertEqual(len(spec['cells']), 7)
        recovered = codec.decode((self.out / 'recovered.gif').read_bytes())
        example.verify(recovered, frames, delays, loop)
        before = codec.decode((self.out / 'synthetic-jitter.gif').read_bytes())
        after = codec.decode((self.out / 'aligned.gif').read_bytes())
        self.assertEqual(before['size'], after['size'])
        self.assertEqual(before['delays_ms'], delays)
        self.assertEqual(after['delays_ms'], delays)
        self.assertNotEqual(before['frames'][1].tobytes(), after['frames'][1].tobytes())
        for name, digest in receipt['files_sha256'].items():
            self.assertEqual(example.sprites.digest((self.out / name).read_bytes()), digest)
        self.assertEqual(json.loads((self.out / 'verification.json').read_text())['loop'], loop)

    def test_native_no_loop_and_infinite_loop(self):
        for loop in (None, 0):
            with self.subTest(loop=loop):
                frames, delays, _ = self.fixture(count=2, loop=loop)
                out = self.root / f'loop-{loop}'
                example.check(self.source, out)
                example.verify(codec.decode((out / 'recovered.gif').read_bytes()), frames, delays, loop)

    def test_existing_outputs_rejected(self):
        self.fixture()
        self.out.mkdir()
        sentinel = self.out / 'keep'
        sentinel.write_bytes(b'accepted')
        with self.assertRaisesRegex(ValueError, 'must be new'):
            example.check(self.source, self.out)
        self.assertEqual(sentinel.read_bytes(), b'accepted')
        file = self.root / 'file'
        file.write_bytes(b'accepted')
        with self.assertRaisesRegex(ValueError, 'must be new'):
            example.check(self.source, file)
        self.assertEqual(file.read_bytes(), b'accepted')

    def test_missing_parent_traversal_and_remote_paths(self):
        self.fixture()
        for out in (self.root / 'missing/child', self.root / '../escape',
                    'https://example.com/out'):
            with self.subTest(out=out), self.assertRaises(ValueError):
                example.check(self.source, out)
        for source in ('https://example.com/input.gif', self.root / '../input.gif'):
            with self.assertRaises(ValueError):
                example.check(source, self.out)
        self.assertFalse(self.out.exists())

    def test_normalized_urls_rejected(self):
        self.fixture()
        for source in ('https:/example.com/input.gif', Path('https://example.com/input.gif')):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'symlinks|URLs'):
                example.check(source, self.out)
        with self.assertRaisesRegex(ValueError, 'URLs'):
            example.check(self.source, 'https:/example.com/out')
        self.assertFalse(self.out.exists())

    def test_source_output_and_parent_symlinks_rejected(self):
        self.fixture()
        cases = [('source-link', self.source, False),
                 ('dangling-output', self.root / 'missing', False),
                 ('parent-link', self.root, True)]
        for name, destination, directory in cases:
            with self.subTest(name=name):
                link = self.root / name
                try:
                    link.symlink_to(destination, target_is_directory=directory)
                except (OSError, NotImplementedError):
                    self.skipTest('Creating symlinks is unavailable')
                source = link if name == 'source-link' else self.source
                out = self.out if name == 'source-link' else link / 'child' if directory else link
                with self.assertRaisesRegex(ValueError, 'symlinks'):
                    example.check(source, out)
        self.assertFalse(self.out.exists())

    def test_source_change_during_export_prevents_publication(self):
        self.fixture()
        real_export = example.sprites.export
        def change_source(*args, **kwargs):
            report = real_export(*args, **kwargs)
            self.source.write_bytes(b'changed by another process')
            return report
        with patch.object(example.sprites, 'export', side_effect=change_source):
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                example.check(self.source, self.out)
        self.assertEqual(self.source.read_bytes(), b'changed by another process')
        self.assertFalse(self.out.exists())
        self.assertFalse(list(self.root.glob('.alignment-*')))

    def test_non_gif_and_directory_inputs_rejected_without_output(self):
        self.source.write_bytes(b'not a gif')
        for source in (self.source, self.root):
            with self.assertRaises((ValueError, OSError)):
                example.check(source, self.out)
            self.assertFalse(self.out.exists())

    def test_256_opaque_colors_rejected_before_output(self):
        frame = Image.new('RGBA', (16, 16))
        frame.putdata([(i, 0, 0, 255) for i in range(256)])
        codec.encode([frame], [20], None, codec.choose_palette([frame]), self.source)
        with self.assertRaisesRegex(ValueError, '255 visible colors'):
            example.check(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_padding_budget_and_unsupported_metadata_rejected_before_output(self):
        self.fixture()
        # The source fits, but the padded demonstration does not.
        with patch.object(codec, 'MAX_PIXEL_FRAMES', 24 * 20 * 7):
            with self.assertRaisesRegex(ValueError, 'Padded synthetic fixture'):
                example.check(self.source, self.out)
        self.assertFalse(self.out.exists())
        raw = bytearray(self.source.read_bytes())
        raw[12] = 1  # Non-square pixel aspect metadata is not preserved by Pillow.
        self.source.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'pixel-aspect'):
            example.check(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_export_failure_leaves_no_result_or_completion_marker(self):
        self.fixture()
        with patch.object(example.sprites, 'export', side_effect=ValueError('injected failure')):
            with self.assertRaisesRegex(ValueError, 'injected failure'):
                example.check(self.source, self.out)
        self.assertFalse(self.out.exists())
        self.assertFalse(list(self.root.glob('.alignment-*')))

    def test_publication_failure_has_no_completion_marker_and_preserves_files(self):
        self.fixture()
        real_publish = example.publish_file
        def fail(stage, target):
            if target.name == 'original.gif':
                (target.parent / 'foreign.txt').write_text('accepted')
                raise OSError('injected failure')
            real_publish(stage, target)
        with patch.object(example, 'publish_file', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'injected failure'):
                example.check(self.source, self.out)
        self.assertEqual((self.out / 'foreign.txt').read_text(), 'accepted')
        self.assertFalse((self.out / 'verification.json').exists())


if __name__ == '__main__':
    unittest.main()
