"""Index-first scaling preserves the previous GIF bytes and independent RGBA truth."""
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import GifImagePlugin, Image
from gif_cinema import pixel_palette as pp
from test_pixel_palette import indexed, rgba, source_gif


def previous_writer(frames, delays, loop, plan, scale):
    """Reference order: upscale RGBA, then map every output pixel to its index."""
    colors = {color: i for i, color in enumerate(plan['colors'])}
    out = io.BytesIO()
    for n, (source, delay) in enumerate(zip(frames, delays)):
        frame = pp.canonical_rgba(source).resize((source.width*scale, source.height*scale), Image.Resampling.NEAREST)
        values = bytes(colors[(r, g, b)] if a else plan['transparent_index'] for r, g, b, a in pp._pixels(frame))
        image = Image.frombytes('P', frame.size, values)
        image.putpalette(plan['palette'])
        info = {'optimize': False, 'duration': delay, 'disposal': 2,
                'include_color_table': False, 'background': plan['transparent_index'] or 0}
        if plan['transparent_index'] is not None:
            info['transparency'] = plan['transparent_index']
        if loop is not None:
            info['loop'] = loop
        if n == 0:
            for block in GifImagePlugin.getheader(image, info=info)[0]:
                out.write(block)
        for block in GifImagePlugin.getdata(image, **info):
            out.write(block)
    return out.getvalue()+b';'


class IndexScalingTests(unittest.TestCase):
    def compare(self, frames, delays, loop, scale, requested=None):
        original = [f.tobytes() for f in frames]
        plan = pp.choose_palette(frames, requested); original_plan = copy.deepcopy(plan)
        expected_bytes = previous_writer(frames, delays, loop, plan, scale)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'output.gif'
            pp.encode(frames, delays, loop, plan, path, scale)
            raw = path.read_bytes()
        self.assertEqual(raw, expected_bytes)
        actual = pp.decode(raw)
        self.assertEqual(len(actual['frames']), len(frames))
        self.assertEqual(actual['delays_ms'], delays)
        self.assertEqual(actual['loop'], loop)
        self.assertEqual(pp.inspect_tables(raw), {'global_palette': bytes(plan['palette']), 'local_count': 0})
        for source, decoded in zip(frames, actual['frames']):
            expected = pp.canonical_rgba(source).resize(decoded.size, Image.Resampling.NEAREST)
            self.assertEqual(expected.tobytes(), decoded.tobytes())
        self.assertEqual(original, [f.tobytes() for f in frames])
        self.assertEqual(plan, original_plan)

    def test_every_integer_scale_odd_canvas_hidden_rgb_and_duplicate_holds(self):
        colors = [(0, 0, 0, 255), (1, 0, 0, 255), (31, 40, 50, 255), (30, 40, 50, 255), (170, 20, 90, 0)]
        first = rgba(colors*3, (5, 3)); last = rgba(list(reversed(colors))*3, (5, 3))
        for scale in range(1, 9):
            for loop in (None, 0, 7):
                with self.subTest(scale=scale, loop=loop):
                    self.compare([first, first.copy(), last], [20, 110, 790], loop, scale,
                        [(100, 120, 140), (31, 40, 50), (1, 0, 0), (0, 0, 0), (30, 40, 50)])

    def test_extreme_palette_indices_and_all_transparent_index_zero(self):
        for scale in (1, 2, 8):
            for colors in ([(v, 11, 19) for v in range(256)],
                           [(v, 11, 19) for v in range(255)]+[(19, 20, 21, 0)],
                           [(21, 40, 80, 0)]*256):
                with self.subTest(scale=scale, count=len(colors)):
                    self.compare([rgba(colors, (16, 16))], [120000], None, scale)

    def test_source_local_tables_and_disposal_two_three_at_scaled_resolution(self):
        colors = [(0, 0, 0), (250, 50, 20), (20, 50, 250), (50, 250, 20)]
        for disposal in (2, 3):
            frames = [indexed(colors, [1, 1], transparent=0),
                      indexed(colors, [2, 0], transparent=0),
                      indexed(colors, [0, 3], transparent=0)]
            source = source_gif(frames, [50, 90, 750], loop=3, disposal=[1, disposal, 1])
            self.assertGreater(pp.inspect_tables(source)['local_count'], 0)
            decoded = pp.decode(source)
            for scale in (2, 8):
                self.compare(decoded['frames'], decoded['delays_ms'], decoded['loop'], scale)

    def test_index_mapping_visits_source_pixels_not_scaled_pixels(self):
        frames = [rgba([(0, 0, 0), (255, 0, 0), (4, 5, 6, 0)], (3, 1))]*2
        plan = pp.choose_palette(frames); sizes = []
        original = pp._pixels
        def observe(frame):
            sizes.append(frame.size)
            return original(frame)
        with tempfile.TemporaryDirectory() as tmp, patch.object(pp, '_pixels', observe):
            pp.encode(frames, [20, 750], 0, plan, Path(tmp)/'output.gif', scale=8)
        # Palette audit uses getcolors on this small fixture; only indexing calls _pixels.
        self.assertEqual(sizes, [(3, 1), (3, 1)])

    def test_scaled_budget_still_rejects_before_indexing_or_publication(self):
        frames = [Image.new('RGBA', (512, 512), (10, 20, 30, 255))]
        plan = pp.choose_palette(frames)
        with tempfile.TemporaryDirectory() as tmp, patch.object(pp, '_pixels', side_effect=AssertionError):
            path = Path(tmp)/'no-output.gif'
            with self.assertRaisesRegex(ValueError, 'pixel budget'):
                pp.encode(frames, [20], None, plan, path, scale=4)
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
