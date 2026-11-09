"""Offline sprite contracts: timing, alpha, shared geometry and bounded IO."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageSequence

from gif_cinema import sprites
from gif_cinema.cli import build_parser


class SpriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sheet = Image.new('RGBA', (24, 12))
        draw = ImageDraw.Draw(self.sheet)
        draw.rectangle((2, 3, 4, 8), fill=(240, 20, 30, 255))
        draw.rectangle((18, 4, 21, 8), fill=(20, 230, 30, 128))
        self.sheet.save(self.root / 'sheet.png')
        self.spec = {'schema_version': 1, 'atlas': 'sheet.png', 'grid': [2, 1],
                     'duration_ms': [120, 240], 'loop': 0}

    def load(self, changes=None):
        spec = dict(self.spec)
        spec.update(changes or {})
        path = self.root / 'spec.json'
        path.write_text(json.dumps(spec), encoding='utf-8')
        return sprites.load_sheet(path)

    def export(self, changes=None, **kwargs):
        frames, delays, loop, source, options = self.load(changes)
        return sprites.export(frames, delays, loop, source, options,
                              self.root / 'out', **kwargs)

    def test_exact_rgba_roundtrip_coordinates_and_timing(self):
        report = self.export({'padding': 2, 'columns': 1})
        self.assertEqual(report['frame_count'], 2)
        self.assertEqual(report['duration_ms'], 360)
        self.assertEqual(report['atlas_size'], [16, 32])
        with Image.open(self.root / 'out/atlas.png') as atlas:
            for frame in report['frame_layout']:
                x, y, w, h = frame['rect']
                with Image.open(self.root / 'out' / frame['file']) as png:
                    self.assertEqual(atlas.crop((x, y, x + w, y + h)).tobytes(), png.tobytes())
                    self.assertEqual(sprites.digest(png.tobytes()), frame['rgba_sha256'])
            self.assertEqual(atlas.getpixel((8, 22)), (20, 230, 30, 128))
            self.assertEqual(atlas.getpixel((0, 0)), (0, 0, 0, 0))
        self.assertEqual(report['preview']['durations_ms'], [120, 240])
        self.assertEqual(report['preview']['loop'], 0)
        for name, expected in report['files_sha256'].items():
            self.assertEqual(sprites.digest((self.root / 'out' / name).read_bytes()), expected)
        self.assertEqual(json.loads((self.root / 'out/manifest.json').read_text()), report)
        self.assertEqual(report['api_calls'], 0)
        self.assertEqual(report['review_status'], 'human-review-required')

    def test_shared_trim_keeps_pose_offsets_and_scale(self):
        report = self.export({'trim': True, 'scale': 2})
        self.assertEqual(report['transform']['crop'], [2, 3, 8, 6])
        self.assertEqual(report['frame_layout'][0]['rect'][2:], [16, 12])
        with Image.open(self.root / 'out/frames/0000.png') as first, \
             Image.open(self.root / 'out/frames/0001.png') as second:
            self.assertEqual(first.getchannel('A').getbbox(), (0, 0, 6, 12))
            self.assertEqual(second.getchannel('A').getbbox(), (8, 2, 16, 12))
            self.assertEqual(second.getpixel((8, 2)), (20, 230, 30, 128))

    def test_selected_order_repeats_and_delays_are_preserved_in_atlas(self):
        report = self.export({'cells': [[1, 0], [0, 0], [0, 0]], 'duration_ms': [20, 40, 80]})
        self.assertEqual(report['consecutive_duplicate_indices'], [2])
        self.assertEqual([f['duration_ms'] for f in report['frame_layout']], [20, 40, 80])
        self.assertEqual(report['preview']['duration_ms'], 140)
        self.assertEqual(report['source']['rectangles'], [[12, 0, 12, 12], [0, 0, 12, 12], [0, 0, 12, 12]])

    def test_dry_run_writes_nothing_and_never_calls_network(self):
        frames, delays, loop, source, options = self.load()
        before = sorted(self.root.iterdir())
        with patch('gif_cinema.cli.request_gif') as network:
            report = sprites.export(frames, delays, loop, source, options,
                                    self.root / 'missing/child', dry_run=True)
        network.assert_not_called()
        self.assertEqual(sorted(self.root.iterdir()), before)
        self.assertNotIn('preview', report)

    def test_existing_directory_file_and_symlink_never_overwritten(self):
        target = self.root / 'out'
        target.mkdir()
        sentinel = target / 'keep.txt'
        sentinel.write_text('accepted')
        with self.assertRaisesRegex(ValueError, 'must be new'):
            self.export()
        self.assertEqual(sentinel.read_text(), 'accepted')
        sentinel.unlink()
        target.rmdir()
        target.write_text('accepted file')
        with self.assertRaisesRegex(ValueError, 'must be new'):
            self.export()
        self.assertEqual(target.read_text(), 'accepted file')

    def test_dangling_output_symlink_rejected(self):
        try:
            (self.root / 'out').symlink_to(self.root / 'missing', target_is_directory=True)
        except OSError:
            self.skipTest('Creating symlinks is unavailable')
        with self.assertRaisesRegex(ValueError, 'must be new'):
            self.export()

    def test_staging_failure_publishes_nothing(self):
        with patch.object(sprites, 'write_preview', side_effect=ValueError('failed verification')):
            with self.assertRaisesRegex(ValueError, 'failed verification'):
                self.export()
        self.assertFalse((self.root / 'out').exists())
        self.assertFalse((self.root / 'out.lock').exists())
        self.assertFalse(list(self.root.glob('.sprites-*')))

    def test_partial_publish_preserves_files_without_completion_marker(self):
        from gif_cinema.cli import publish_file
        def fail_after_first(stage, target):
            if target.name == 'atlas.png':
                (target.parent / 'foreign.txt').write_text('do not delete')
                raise OSError('simulated full disk')
            publish_file(stage, target)
        with patch('gif_cinema.cli.publish_file', side_effect=fail_after_first):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual((self.root / 'out/foreign.txt').read_text(), 'do not delete')
        self.assertFalse((self.root / 'out/manifest.json').exists())
        self.assertTrue((self.root / 'out/animation.gif').exists())

    def test_failed_publish_never_deletes_concurrent_replacement(self):
        from gif_cinema.cli import publish_file
        def replace_and_fail(stage, target):
            if target.name == 'atlas.png':
                old = target.parent / 'animation.gif'
                old.unlink()
                old.write_bytes(b'accepted replacement')
                raise OSError('simulated full disk')
            publish_file(stage, target)
        with patch('gif_cinema.cli.publish_file', side_effect=replace_and_fail):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual((self.root / 'out/animation.gif').read_bytes(), b'accepted replacement')
        self.assertFalse((self.root / 'out/manifest.json').exists())

    def test_directory_swap_stops_further_publication(self):
        from gif_cinema.cli import publish_file
        def swap_after_first(stage, target):
            publish_file(stage, target)
            if target.name == 'animation.gif':
                target.parent.rename(self.root / 'preserved')
                target.parent.mkdir()
        with patch('gif_cinema.cli.publish_file', side_effect=swap_after_first):
            with self.assertRaisesRegex(ValueError, 'directory changed'):
                self.export()
        self.assertEqual(list((self.root / 'out').iterdir()), [])
        self.assertTrue((self.root / 'preserved/animation.gif').exists())
        self.assertFalse((self.root / 'preserved/manifest.json').exists())

    def test_frames_directory_swap_stops_further_publication(self):
        from gif_cinema.cli import publish_file
        def swap_after_first(stage, target):
            publish_file(stage, target)
            if target.name == 'animation.gif':
                (target.parent / 'frames').rename(target.parent / 'preserved-frames')
                (target.parent / 'frames').mkdir()
        with patch('gif_cinema.cli.publish_file', side_effect=swap_after_first):
            with self.assertRaisesRegex(ValueError, 'directory changed'):
                self.export()
        self.assertFalse((self.root / 'out/atlas.png').exists())
        self.assertFalse((self.root / 'out/manifest.json').exists())

    def test_directory_identity_rejects_symlinks(self):
        destination = self.root / 'destination'
        destination.mkdir()
        link = self.root / 'link'
        try:
            link.symlink_to(destination, target_is_directory=True)
        except OSError:
            self.skipTest('Creating symlinks is unavailable')
        with self.assertRaisesRegex(ValueError, 'directory changed'):
            sprites.directory_identity(link)

    def test_margin_catches_nonempty_edge_strips(self):
        report = self.export({'require_margin': 2}, dry_run=True)
        self.assertEqual(report['frame_count'], 2)
        with self.assertRaisesRegex(ValueError, 'require_margin'):
            self.export({'require_margin': 3}, dry_run=True)

    def test_explicit_common_crop_warns_on_removed_pixels(self):
        report = self.export({'crop': [1, 1, 5, 9]})
        self.assertTrue(any('removes visible pixels' in warning for warning in report['warnings']))
        self.assertEqual(report['frame_layout'][1]['rect'][2:], [5, 9])

    def test_static_and_empty_inputs_are_not_claimed_as_motion(self):
        Image.new('RGBA', (24, 12)).save(self.root / 'sheet.png')
        report = self.export({'trim': True})
        self.assertEqual(report['transform']['crop'], [0, 0, 12, 12])
        self.assertEqual(report['consecutive_duplicate_indices'], [1])
        self.assertTrue(any('completely transparent' in warning for warning in report['warnings']))
        self.assertEqual(report['preview']['duration_ms'], 360)

    def test_gif_alpha_and_finite_loop_survive_unpack(self):
        frames, _, _, _, _ = self.load()
        path = self.root / 'source.gif'
        sprites.write_preview(frames, [120, 240], 2, path)
        unpacked, delays, loop, source = sprites.load_gif(path)
        self.assertEqual((delays, loop), ([120, 240], 2))
        self.assertEqual(unpacked[0].getpixel((0, 0))[3], 0)
        self.assertEqual(unpacked[1].getpixel((6, 4))[3], 255)
        self.assertEqual(source['sha256'], sprites.digest(path.read_bytes()))

    def test_no_loop_extension_means_play_once(self):
        self.spec.pop('loop')
        report = self.export()
        with Image.open(self.root / 'out/animation.gif') as gif:
            self.assertNotIn('loop', gif.info)
        self.assertIsNone(report['loop'])

    def test_binary_alpha_and_black_color_remain_separate(self):
        frame = Image.new('RGBA', (4, 4))
        frame.putpixel((1, 1), (0, 0, 0, 255))
        frame.putpixel((1, 2), (0, 0, 0, 127))
        path = self.root / 'black.gif'
        sprites.write_preview([frame], [100], None, path)
        with Image.open(path) as gif:
            rgba = gif.convert('RGBA')
            self.assertEqual(rgba.getpixel((1, 1)), (0, 0, 0, 255))
            self.assertEqual(rgba.getpixel((1, 2))[3], 0)

    def test_strict_schema_and_parameter_validation(self):
        invalid = [({'schema_version': True}, 'schema_version'),
                   ({'unknown': 1}, 'documented'), ({'atlas': 'https://example.com/x.png'}, 'local'),
                   ({'grid': [5, 1]}, 'divide'), ({'grid': [256, 256]}, 'cell limit'),
                   ({'grid': [0, 1]}, 'grid'), ({'cells': []}, 'cells'),
                   ({'cells': [[2, 0]]}, 'outside'), ({'cells': [[False, 0]]}, 'cell'),
                   ({'duration_ms': [100]}, 'match'), ({'duration_ms': 21}, 'multiple'),
                   ({'duration_ms': True}, 'duration_ms'), ({'loop': -1}, 'loop'),
                   ({'trim': 'yes'}, 'boolean'), ({'crop': [0, 0, 0, 1]}, 'outside'),
                   ({'crop': [0, 0, 4, 4], 'trim': True}, 'not both'),
                   ({'scale': 0}, 'scale'), ({'sampling': 'auto'}, 'sampling'),
                   ({'columns': True}, 'columns'), ({'padding': -1}, 'padding')]
        for changes, message in invalid:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                self.export(changes, dry_run=True)

    def test_duplicate_json_key_is_rejected(self):
        path = self.root / 'duplicate.json'
        path.write_text('{"schema_version": 1, "schema_version": 2}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
            sprites.load_sheet(path)

    def test_byte_and_pixel_limits_fail_before_frame_conversion(self):
        with patch.object(sprites, 'MAX_INPUT_BYTES', 1), patch('PIL.Image.open') as decoder:
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                self.load()
            decoder.assert_not_called()
        with patch.object(sprites, 'MAX_SHEET_PIXELS', 100), patch('PIL.Image.Image.convert') as convert:
            with self.assertRaisesRegex(ValueError, '16 megapixel'):
                self.load()
            convert.assert_not_called()
        with patch.object(sprites, 'MAX_PIXEL_FRAMES', 200), self.assertRaisesRegex(ValueError, 'pixel budget'):
            self.load()

    def test_output_bounds_and_timing_cap(self):
        with patch.object(sprites, 'MAX_SHEET_PIXELS', 300), self.assertRaisesRegex(ValueError, 'Packed atlas'):
            self.export({'padding': 10}, dry_run=True)
        with patch.object(sprites, 'MAX_PIXEL_FRAMES', 1000), self.assertRaisesRegex(ValueError, 'pixel budget'):
            self.export({'scale': 4}, dry_run=True)
        with self.assertRaisesRegex(ValueError, '120 second'):
            self.load({'cells': [[0, 0]] * 3, 'duration_ms': 60000})

    def test_gif_tighter_frame_limit_precedes_pillow_disposal_allocation(self):
        data = io.BytesIO()
        Image.new('RGB', (1, 1), 'red').save(data, format='GIF', duration=100, disposal=2)
        raw = bytearray(data.getvalue())
        raw[6:10] = (2049).to_bytes(2, 'little') * 2
        descriptor = raw.index(b',')
        raw[descriptor + 5:descriptor + 9] = (2049).to_bytes(2, 'little') * 2
        path = self.root / 'oversized.gif'
        path.write_bytes(raw)
        with patch('PIL.Image.open') as decoder, self.assertRaisesRegex(ValueError, '4 megapixel'):
            sprites.load_gif(path)
        decoder.assert_not_called()

    def test_animated_png_and_non_png_sheet_rejected(self):
        self.sheet.convert('RGB').save(self.root / 'wrong.jpg')
        with self.assertRaisesRegex(ValueError, 'still PNG'):
            self.load({'atlas': 'wrong.jpg'})
        self.sheet.save(self.root / 'animated.png', save_all=True,
                        append_images=[Image.new('RGBA', self.sheet.size, 'blue')], duration=100)
        with self.assertRaisesRegex(ValueError, 'still PNG'):
            self.load({'atlas': 'animated.png'})

    def test_cli_slice_and_pack(self):
        self.load()
        args = build_parser().parse_args(['sprites', 'slice', str(self.root / 'spec.json'),
                                         '--out', str(self.root / 'out')])
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            args.func(args)
        self.assertEqual(json.loads(output.getvalue())['frame_count'], 2)
        args = build_parser().parse_args(['sprites', 'pack', str(self.root / 'out/animation.gif'),
                                         '--out', str(self.root / 'packed'), '--trim', '--dry-run'])
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            args.func(args)
        self.assertEqual(json.loads(output.getvalue())['source']['kind'], 'gif')
        self.assertFalse((self.root / 'packed').exists())


if __name__ == '__main__':
    unittest.main()
