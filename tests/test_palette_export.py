"""Exact palette colors and lossless shared-table storage, without API calls."""
import io
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageSequence

from gif_cinema import layers, motion


def gray_palette():
    palette = Image.new('P', (1, 1))
    palette.putpalette([level for level in range(256) for _ in range(3)])
    return palette


def decode(raw):
    with Image.open(io.BytesIO(raw)) as image:
        loop = image.info.get('loop')
        frames = [(frame.convert('RGBA').tobytes(), frame.info['duration'])
                  for frame in ImageSequence.Iterator(image)]
    return frames, loop


class ExactPaletteTests(unittest.TestCase):
    def test_257th_color_cannot_collapse_existing_256_palette_colors(self):
        source = Image.new('RGB', (257, 1))
        source.putdata([(level,) * 3 for level in range(256)] + [(255, 0, 0)])
        palette = gray_palette()
        before, colors = source.tobytes(), palette.getpalette()
        result = motion.quantize_shared(source, palette).convert('RGB')
        self.assertEqual(result.crop((0, 0, 256, 1)).tobytes(), before[:256 * 3])
        self.assertEqual(source.tobytes(), before)
        self.assertEqual(palette.getpalette(), colors)

    def test_small_frame_with_an_off_palette_color_keeps_exact_members(self):
        source = Image.new('RGB', (8, 1))
        source.putdata([(level,) * 3 for level in range(7)] + [(255, 0, 0)])
        result = motion.quantize_shared(source, gray_palette()).convert('RGB')
        self.assertEqual(result.crop((0, 0, 7, 1)).tobytes(), source.tobytes()[:21])

    def test_only_exact_members_change_and_no_rgb_error_can_increase(self):
        palette = gray_palette()
        source = Image.new('RGB', (256, 4))
        source.putdata([(level,) * 3 for level in range(256)] +
                       [(level, level, (level + delta) % 256)
                        for delta in (1, 3, 17) for level in range(256)])
        old = source.quantize(palette=palette, dither=Image.Dither.NONE).convert('RGB')
        result = motion.quantize_shared(source, palette).convert('RGB')
        for x in range(256):
            self.assertEqual(result.getpixel((x, 0)), source.getpixel((x, 0)))
        self.assertEqual(result.crop((0, 1, 256, 4)).tobytes(), old.crop((0, 1, 256, 4)).tobytes())

    def test_duplicate_palette_entries_do_not_change_exact_color_values(self):
        palette = gray_palette()
        colors = palette.getpalette()
        colors[3:6] = [0, 0, 0]
        palette.putpalette(colors)
        source = Image.new('RGB', (257, 1))
        source.putdata([(level,) * 3 for level in range(256)] + [(255, 0, 0)])
        result = motion.quantize_shared(source, palette).convert('RGB')
        for level in (0, *range(2, 256)):
            self.assertEqual(result.getpixel((level, 0)), (level,) * 3)


class SharedTableTests(unittest.TestCase):
    def test_one_table_preserves_all_colors_changed_rectangles_holds_and_loop(self):
        palette = gray_palette()
        first = Image.new('P', (256, 4))
        first.putpalette(palette.getpalette())
        first.putdata(list(range(256)) * 4)
        second = first.copy(); second.putpixel((13, 2), 255)
        last = first.copy(); last.putpixel((244, 1), 0)
        frames = [first, first.copy(), second, last, last.copy()]
        for loop in (None, 0):
            with self.subTest(loop=loop):
                options = {} if loop is None else {'loop': loop}
                old, new = io.BytesIO(), io.BytesIO()
                for target, extra in ((old, {}), (new, {'palette': palette.getpalette()})):
                    frames[0].save(target, format='GIF', save_all=True, append_images=frames[1:],
                                   duration=[20, 40, 60, 80, 100], optimize=False, disposal=1,
                                   **options, **extra)
                self.assertEqual(decode(new.getvalue()), decode(old.getvalue()))
                decoded, actual_loop = decode(new.getvalue())
                self.assertEqual([delay for _, delay in decoded], [60, 60, 180])
                self.assertEqual(actual_loop, loop)
                self.assertEqual(len(old.getvalue()) - len(new.getvalue()), 2 * 768)


class PublishedComparisonTests(unittest.TestCase):
    def test_shared_examples_match_their_recorded_bytes_pixels_and_timing(self):
        root = Path(__file__).resolve().parents[1] / 'docs' / 'assets' / 'palette-export'
        report = json.loads((root / 'results.json').read_text(encoding='utf-8'))
        self.assertEqual(report['api_calls'], 0)
        for case, prefix in (('gradient-accent', 'gradient'), ('layered-shapes', 'shapes')):
            entry = report['cases'][case]
            for method in ('before', 'after'):
                with self.subTest(case=case, method=method):
                    path = root / f'{prefix}-{method}.gif'
                    expected = entry['methods'][method]
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected['sha256'])
                    self.assertEqual(path.stat().st_size, expected['bytes'])
                    hashes, delays = [], []
                    with Image.open(path) as gif:
                        self.assertEqual(gif.size, (entry['width'], entry['height']))
                        self.assertEqual(gif.info.get('loop'), expected['loop'])
                        for frame in ImageSequence.Iterator(gif):
                            delay = frame.info['duration']; delays.append(delay)
                            value = hashlib.sha256(frame.convert('RGB').tobytes()).hexdigest()
                            self.assertEqual(delay % (1000 // entry['fps']), 0)
                            hashes.extend([value] * (delay // (1000 // entry['fps'])))
                    self.assertEqual(delays, expected['delays_ms'])
                    self.assertEqual(len(hashes), entry['source_frames'])
                    self.assertEqual(hashlib.sha256(''.join(hashes).encode('ascii')).hexdigest(),
                                     expected['decoded_timeline_sha256'])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
class EncoderIntegrationTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target in ('urllib.request.OpenerDirector.open', 'socket.create_connection', 'gif_cinema.cli.request_gif'):
            guard = patch(target, side_effect=AssertionError('Network and paid requests forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def source(self):
        image = Image.new('RGB', (256, 4))
        image.putdata([(level,) * 3 for _ in range(4) for level in range(256)])
        image.putpixel((0, 3), (255, 0, 0))
        path = self.root / 'ramp.png'; image.save(path)
        return image, path

    def assert_ramp(self, path):
        with Image.open(path) as gif:
            row = gif.convert('RGB').crop((0, 0, 256, 1))
            # Median-cut may merge the 257th source color. The remaining grays
            # must not be collapsed again by the fixed-palette lookup cache.
            self.assertGreaterEqual(len(row.getcolors(256)), 250)

    def test_motion_preserves_high_color_ramp_in_delivered_gif(self):
        _, source = self.source()
        before = source.read_bytes()
        for loop in (True, False):
            with self.subTest(loop=loop):
                out = self.root / f'motion-{loop}'
                receipt = motion.motion(source, out, recipe={'still_duration_ms': 80}, gif_loop=loop)
                self.assert_ramp(out / 'take.gif')
                self.assertEqual(receipt['api_calls'], 0)
                self.assertEqual(receipt['candidate_delays_ms'], [80])
                self.assertEqual(receipt['delivery']['gif']['verification'], 'passed')
                with Image.open(out / 'take.gif') as gif:
                    self.assertEqual(gif.info.get('loop'), 0 if loop else None)
                    self.assertEqual(gif.info['duration'], 80)
                    self.assertEqual(gif.n_frames, 1)
        self.assertEqual(source.read_bytes(), before)

    def test_layers_preserve_high_color_ramp_and_play_once(self):
        _, source = self.source()
        path = self.root / 'scene.json'
        path.write_text(json.dumps({'format': layers.FORMAT, 'schema_version': 1,
            'width': 256, 'height': 4, 'duration_ms': 80, 'fps': 25, 'loop': False,
            'layers': [{'id': 'gradient', 'type': 'image', 'source': source.name,
                        'size': [256, 4]}]}), encoding='utf-8')
        out = self.root / 'layers'
        receipt = layers.render_scene(path, out)
        self.assert_ramp(out / 'preview.gif')
        with Image.open(out / 'preview.gif') as gif:
            self.assertIsNone(gif.info.get('loop'))
        self.assertEqual(receipt['api_calls'], 0)


if __name__ == '__main__':
    unittest.main()
