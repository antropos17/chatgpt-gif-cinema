"""Regressions for small colors, display orientation, GIF bounds and exact timing."""
from fractions import Fraction
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, features
from gif_cinema import cli, motion


def tiny_gif():
    output = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(output, format='GIF', save_all=True,
        append_images=[Image.new('RGB', (2, 2), 'blue')], duration=40, optimize=False, disposal=2)
    return output.getvalue()


class PaletteFidelityTests(unittest.TestCase):
    def shared_palette(self, frames):
        samples = Image.new('RGB', (256, len(frames)))
        for index, frame in enumerate(frames):
            samples.paste(motion.palette_row(frame), (0, index))
        return samples.quantize(colors=256, method=Image.Quantize.MEDIANCUT)

    def test_thin_white_and_isolated_accents_survive_full_resolution_sampling(self):
        frame = Image.new('RGB', (512, 512), 'black')
        frame.paste('white', (254, 10, 258, 502))
        frame.putpixel((1, 1), (255, 0, 0))
        frame.putpixel((12, 403), (0, 255, 0))
        before = frame.tobytes()
        palette = self.shared_palette([frame, frame])
        result = motion.quantize_shared(frame, palette).convert('RGB')
        self.assertEqual(result.tobytes(), before)
        self.assertEqual(result.getpixel((255, 100)), (255, 255, 255))
        self.assertEqual(frame.tobytes(), before)

    def test_all_256_nearby_colors_are_exact_not_merged_by_rgb_lookup_cache(self):
        frames = []
        for start in range(0, 256, 64):
            frame = Image.new('RGB', (64, 1))
            frame.putdata([(i, i, i) for i in range(start, start + 64)])
            frames.append(frame)
        palette = self.shared_palette(frames)
        for frame in frames:
            self.assertEqual(motion.quantize_shared(frame, palette).convert('RGB').tobytes(), frame.tobytes())

    def test_sample_storage_is_bounded_and_contains_no_averaged_filler_color(self):
        frame = Image.new('RGB', (400, 400), (250, 1, 17))
        frame.putpixel((0, 0), (2, 220, 251))
        row = motion.palette_row(frame)
        self.assertEqual(row.size, (256, 1))
        self.assertEqual({color for _, color in row.getcolors()}, {(250, 1, 17), (2, 220, 251)})
        self.assertEqual(row.tobytes(), motion.palette_row(frame).tobytes())

    def test_high_color_fallback_is_deterministic_and_bounded(self):
        frame = Image.new('RGB', (128, 128))
        frame.putdata([(x * 2, y * 2, (x + y) % 256) for y in range(128) for x in range(128)])
        self.assertIsNone(frame.getcolors(256))
        first, second = motion.palette_row(frame), motion.palette_row(frame)
        self.assertEqual(first.size, (256, 1))
        self.assertEqual(first.tobytes(), second.tobytes())
        palette = self.shared_palette([frame])
        result = motion.quantize_shared(frame, palette)
        self.assertEqual(result.size, frame.size)
        self.assertLessEqual(len(result.getcolors()), 256)


class SourceOrientationTests(unittest.TestCase):
    def test_all_exif_orientations_in_still_formats(self):
        transforms = {1: None, 2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
                      4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
                      6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
                      8: Image.Transpose.ROTATE_90}
        formats = ['PNG', 'JPEG'] + (['WEBP'] if features.check('webp') else [])
        image = Image.new('RGBA', (80, 40), (255, 0, 0, 255))
        image.paste((0, 0, 255, 255), (40, 0, 80, 40))
        image.paste((12, 200, 50, 70), (0, 0, 12, 12))
        for fmt in formats:
            for orientation, transform in transforms.items():
                with self.subTest(fmt=fmt, orientation=orientation):
                    exif = Image.Exif(); exif[274] = orientation
                    output = io.BytesIO()
                    source = image.convert('RGB') if fmt == 'JPEG' else image
                    options = {'lossless': True} if fmt == 'WEBP' else {}
                    # Metadata does not authorize color conversion or change pixels.
                    source.save(output, format=fmt, exif=exif, icc_profile=b'profile fixture', **options)
                    raw = output.getvalue()
                    with Image.open(io.BytesIO(raw)) as encoded:
                        expected = encoded.convert('RGBA')
                        if transform is not None:
                            expected = expected.transpose(transform)
                    frames, delays, actual_format = motion.decode_source(raw, 80)
                    self.assertEqual((actual_format, delays, len(frames)), (fmt, [80], 1))
                    self.assertEqual(frames[0].size, expected.size)
                    self.assertEqual(frames[0].tobytes(), expected.tobytes())
                    self.assertEqual(frames[0].info, {})
                    config = motion.normalize_recipe({}, frames[0].size)
                    self.assertEqual((config['width'], config['height']), expected.size)

    def test_gif_still_does_not_require_or_inherit_exif(self):
        output = io.BytesIO()
        Image.new('RGB', (12, 8), 'red').save(output, format='GIF')
        frames, delays, fmt = motion.decode_source(output.getvalue(), 200)
        self.assertEqual((frames[0].size, delays, fmt), ((12, 8), [200], 'GIF'))


class SourcePreflightTests(unittest.TestCase):
    def test_scanner_returns_preallocation_statistics(self):
        self.assertEqual(cli.check_gif_limits(tiny_gif()),
                         {'width': 2, 'height': 2, 'frames': 2, 'pixel_frames': 8, 'canvas_expanded': False})

    def test_later_oversized_disposal_descriptor_is_rejected_before_pillow(self):
        raw = tiny_gif()
        descriptor = raw.rindex(b',')
        oversized = raw[:descriptor + 5] + (2500).to_bytes(2, 'little') + (2000).to_bytes(2, 'little') + raw[descriptor + 9:]
        with patch('PIL.Image.open') as decoder, self.assertRaisesRegex(ValueError, '4 megapixel'):
            motion.decode_source(oversized, 200)
        decoder.assert_not_called()

    def test_small_canvas_expansion_is_also_rejected_before_pillow(self):
        raw = tiny_gif()
        descriptor = raw.rindex(b',')
        growing = raw[:descriptor + 5] + (3).to_bytes(2, 'little') + raw[descriptor + 7:]
        with patch('PIL.Image.open') as decoder, self.assertRaisesRegex(ValueError, 'fixed logical canvas'):
            motion.decode_source(growing, 200)
        decoder.assert_not_called()

    def test_stricter_total_pixel_and_byte_limits_precede_decoder(self):
        raw = tiny_gif()
        for limit, value, message in [('MAX_SOURCE_PIXEL_FRAMES', 7, 'pixel budget'),
                                       ('MAX_BYTES', len(raw) - 1, 'byte limit')]:
            with self.subTest(limit=limit), patch.object(motion, limit, value), \
                    patch('PIL.Image.open') as decoder, self.assertRaisesRegex(ValueError, message):
                motion.decode_source(raw, 200)
            decoder.assert_not_called()
        with patch.object(motion, 'MAX_SOURCE_PIXEL_FRAMES', 8):
            frames, _, _ = motion.decode_source(raw, 200)
        self.assertEqual(len(frames), 2)

    def test_stricter_frame_count_precedes_decoder(self):
        output = io.BytesIO()
        Image.new('RGB', (2, 2), 'red').save(output, format='GIF', duration=40, optimize=False)
        raw = output.getvalue()
        header = 13 + 3 * 2 ** ((raw[10] & 7) + 1)
        too_many = raw[:-1] + raw[header:-1] * 512 + b';'
        with patch('PIL.Image.open') as decoder, self.assertRaisesRegex(ValueError, 'drawing/pixel budget'):
            motion.decode_source(too_many, 200)
        decoder.assert_not_called()


class ExactMotionPlanTests(unittest.TestCase):
    def test_rational_boundary_uses_following_source_drawing(self):
        config = motion.normalize_recipe({'speed': .3}, (32, 32))
        timeline = motion.build_timeline([20, 20, 20, 40, 100], config)
        self.assertEqual(motion.sample_timeline(timeline, 8), 4)
        self.assertEqual(motion.sample_timeline(json.loads(json.dumps(timeline)), 8), 4)
        self.assertEqual(timeline['exact_timing'], {'ticks_per_ms': 3, 'segment_end_ticks': [200, 400, 600, 1000, 2000]})

    def test_all_bins_match_independent_fraction_reference(self):
        delays = [20, 20, 20, 40, 100]
        for speed in [.1, .3, .7, 1.1, 2.7]:
            for fps in (25, 50):
                with self.subTest(speed=speed, fps=fps):
                    config = motion.normalize_recipe({'speed': speed, 'fps': fps}, (32, 32))
                    timeline = motion.build_timeline(delays, config)
                    segments = [Fraction(d) / Fraction(str(speed)) for d in delays]
                    count = timeline['playback_frames']
                    for frame in range(1, count - 1):
                        center = Fraction(2 * frame + 1, 2 * count) * sum(segments)
                        end = 0
                        for expected, duration in enumerate(segments):
                            end += duration
                            if center < end:
                                break
                        self.assertEqual(motion.sample_timeline(timeline, frame), expected)

    def test_rational_ticks_cover_repeats_reverse_and_holds(self):
        config = motion.normalize_recipe({'speed': .3, 'playback': 'reverse', 'repeats': 3,
                                           'hold_start_ms': 70, 'hold_end_ms': 130}, (32, 32))
        timeline = motion.build_timeline([20, 40], config)
        timing = timeline['exact_timing']
        exact = [Fraction(70)] + [Fraction(400, 3), Fraction(200, 3)] * 3 + [Fraction(130)]
        end = Fraction(0)
        for index, duration in enumerate(exact):
            end += duration
            self.assertEqual(Fraction(timing['segment_end_ticks'][index], timing['ticks_per_ms']), end)
        self.assertEqual(timeline['duration_ms'], 800)
        self.assertEqual(motion.sample_timeline(timeline, 0), 1)
        self.assertEqual(motion.sample_timeline(timeline, timeline['playback_frames'] - 1), 0)

    def test_atlas_finds_valid_non_square_grid(self):
        config = motion.normalize_recipe({'width': 1024, 'height': 768, 'spritesheet': True}, (1024, 768))
        timeline = motion.build_timeline([840], config)
        atlas = timeline['spritesheet']
        self.assertEqual(timeline['playback_frames'], 21)
        self.assertEqual(atlas['columns'] * atlas['rows'], 21)
        self.assertLessEqual(atlas['width'], 8192)
        self.assertLessEqual(atlas['height'], 8192)
        self.assertEqual(atlas['width'] * atlas['height'], 16515072)

    def test_atlas_acceptance_matches_integer_grid_search(self):
        for width, height, count in [(1024, 768, 21), (2048, 128, 60), (2048, 2048, 4),
                                     (2048, 2048, 5), (2, 2048, 300)]:
            with self.subTest(width=width, height=height, count=count):
                config = motion.normalize_recipe({'width': width, 'height': height, 'spritesheet': True}, (width, height))
                feasible = [(cols, (count + cols - 1) // cols) for cols in range(1, count + 1)
                            if cols * width <= 8192 and ((count + cols - 1) // cols) * height <= 8192
                            and cols * ((count + cols - 1) // cols) * width * height <= motion.MAX_ATLAS_PIXELS]
                if not feasible:
                    with self.assertRaisesRegex(ValueError, 'Spritesheet exceeds'):
                        motion.build_timeline([count * 40], config)
                else:
                    atlas = motion.build_timeline([count * 40], config)['spritesheet']
                    self.assertIn((atlas['columns'], atlas['rows']), feasible)


class MotionFidelityIntegrationTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target in ['urllib.request.OpenerDirector.open', 'socket.create_connection', 'gif_cinema.cli.request_gif']:
            guard = patch(target, side_effect=AssertionError('Network and paid requests forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
    def test_full_export_keeps_white_mark_and_original_bytes(self):
        source = self.root / 'mark.png'
        image = Image.new('RGB', (512, 512), 'black')
        image.paste('white', (254, 10, 258, 502))
        image.save(source)
        original = source.read_bytes()
        out = self.root / 'mark-export'
        receipt = motion.motion(source, out, recipe={'still_duration_ms': 80, 'background': '#000000'})
        with Image.open(out / 'take.gif') as gif, Image.open(out / 'first.png') as png:
            self.assertEqual(gif.convert('RGB').getpixel((255, 100)), (255, 255, 255))
            self.assertEqual(gif.convert('RGB').tobytes(), png.convert('RGB').tobytes())
            self.assertEqual(gif.info['duration'], 80)
        self.assertEqual(receipt['timeline']['playback_frames'], 2)
        self.assertEqual(receipt['api_calls'], 0)
        self.assertEqual(source.read_bytes(), original)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
    def test_exif_normalization_matches_dry_run_export_and_original_hash(self):
        source = self.root / 'phone.jpg'
        image = Image.new('RGB', (80, 40), 'red')
        image.paste('blue', (40, 0, 80, 40))
        exif = Image.Exif(); exif[274] = 6
        image.save(source, exif=exif)
        original = source.read_bytes()
        plan = motion.motion(source, self.root / 'plan-only', recipe={'still_duration_ms': 80}, dry_run=True)
        self.assertFalse((self.root / 'plan-only').exists())
        self.assertEqual((plan['recipe']['width'], plan['recipe']['height']), (40, 80))
        out = self.root / 'photo-export'
        receipt = motion.motion(source, out, recipe={'still_duration_ms': 80})
        self.assertEqual((receipt['probe']['streams'][0]['width'], receipt['probe']['streams'][0]['height']), (40, 80))
        with Image.open(out / 'first.png') as first:
            self.assertEqual(first.size, (40, 80))
            self.assertGreater(first.getpixel((20, 20))[0], 240)
            self.assertGreater(first.getpixel((20, 60))[2], 240)
        self.assertEqual(receipt['source_sha256'], motion.sha(original))
        self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
