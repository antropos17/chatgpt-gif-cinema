"""Offline constraints for the native 540x960, explicitly upscaled demo."""
import copy
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from gif_cinema import layers

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'vertical-motion.json'
# Author-chosen margins, not an official or universal platform safe-area spec.
SAFE_RECT = (54, 120, 454, 750)


def conservative_bounds(prepared, layer, timestamp):
    state = layers.layer_transform(prepared['scene'], layer, timestamp)
    if state is None:
        return None
    raster = prepared['rasters'][layer['id']]
    anchor_x, anchor_y = layer['anchor'][0] * raster.width, layer['anchor'][1] * raster.height
    cx, cy = state['x'] * prepared['scene']['width'], state['y'] * prepared['scene']['height']
    angle = math.radians(state['rotation'])
    cosine, sine, zoom = math.cos(angle), math.sin(angle), state['zoom']
    corners = [(cx + zoom * (cosine * (x - anchor_x) - sine * (y - anchor_y)),
                cy + zoom * (sine * (x - anchor_x) + cosine * (y - anchor_y)))
               for x in (0, raster.width) for y in (0, raster.height)]
    # Expand raster corners by two canvas pixels for resampling fringes.
    return (math.floor(min(x for x, _ in corners)) - 2,
            math.floor(min(y for _, y in corners)) - 2,
            math.ceil(max(x for x, _ in corners)) + 2,
            math.ceil(max(y for _, y in corners)) + 2)


def luminance(color):
    channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))


class VerticalExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch('socket.create_connection', side_effect=AssertionError('Network forbidden')):
            cls.prepared = layers.prepare_scene(EXAMPLE)
        cls.scene = cls.prepared['scene']

    def test_native_resolution_asset_free_structure_and_workload(self):
        self.assertEqual((self.scene['width'], self.scene['height']), (540, 960))
        self.assertEqual(self.scene['width'] * 16, self.scene['height'] * 9)
        self.assertEqual((self.scene['fps'], self.scene['duration_ms']), (50, 3200))
        self.assertEqual(len(self.scene['layers']), 12)
        self.assertEqual(self.prepared['assets'], {})
        self.assertLess(EXAMPLE.stat().st_size, 8192)
        self.assertEqual({layer['type'] for layer in self.scene['layers']}, {'text', 'rect', 'ellipse'})
        self.assertLess(layers.raster_budget(self.scene)['raster_pixel_frames_upper_bound'], layers.MAX_RASTER_PIXEL_FRAMES)

    def test_english_demo_copy_pinned_font_and_nominal_reading_sizes(self):
        text = [layer for layer in self.scene['layers'] if layer['type'] == 'text']
        self.assertEqual(len(text), 5)
        self.assertEqual(self.scene['title'], 'Vertical study: Layered motion')
        self.assertEqual({layer['id']: layer['text'] for layer in text}, {
            'study_label': 'MOTION / 01',
            'title_line_1': 'Layered',
            'title_line_2': 'Motion',
            'layer_caption': 'Layers · Text · Rhythm',
            'format_caption': '540 × 960   ·   9:16',
        })
        # Russian/Azerbaijani glyph and export regressions live in test_text_fonts.py;
        # they do not determine the language of this public-facing example.
        for layer in text:
            self.assertEqual(layer['font_id'], 'noto-sans-regular-2.004')
            self.assertGreaterEqual(layer['font_size'], 18)
            # At a 360-pixel wide 9:16 display this is at least 12 nominal px.
            self.assertGreaterEqual(layer['font_size'] * 360 / self.scene['width'], 12)
            self.assertIsNotNone(self.prepared['rasters'][layer['id']].getbbox())
        titles = {layer['id']: layer for layer in text}
        self.assertGreaterEqual(titles['title_line_1']['font_size'], 40)
        self.assertGreaterEqual(titles['title_line_2']['font_size'], 40)

    def test_every_export_sample_fits_declared_safe_area(self):
        left, top, right, bottom = SAFE_RECT
        for timestamp in range(0, self.scene['duration_ms'], 20):
            for layer in self.scene['layers']:
                if layer['id'] == 'background':
                    continue
                bounds = conservative_bounds(self.prepared, layer, timestamp)
                with self.subTest(layer=layer['id'], timestamp=timestamp):
                    self.assertIsNotNone(bounds)
                    self.assertGreaterEqual(bounds[0], left)
                    self.assertGreaterEqual(bounds[1], top)
                    self.assertLessEqual(bounds[2], right)
                    self.assertLessEqual(bounds[3], bottom)

    def test_text_contrast_and_no_overlapping_animated_graphics(self):
        text = [layer for layer in self.scene['layers'] if layer['type'] == 'text']
        graphics = [layer for layer in self.scene['layers'] if layer['type'] != 'text' and layer['id'] != 'background']
        for layer in text:
            contrast = (luminance(layer['fill']) + .05) / (luminance(self.scene['matte']) + .05)
            self.assertGreater(contrast, 7)
            a = conservative_bounds(self.prepared, layer, 0)
            for timestamp in range(0, self.scene['duration_ms'], 20):
                for graphic in graphics:
                    b = conservative_bounds(self.prepared, graphic, timestamp)
                    self.assertTrue(a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1],
                                    (layer['id'], graphic['id'], timestamp))

    def test_loop_endpoints_and_smootherstep_seam_speed(self):
        epsilon = .0001
        animated = 0
        for layer in self.scene['layers']:
            keys = layer['keyframes']
            start, end = layers.evaluate(keys, 0), layers.evaluate(keys, 1)
            self.assertEqual(start, end)
            if len(keys) == 3:
                animated += 1
                self.assertEqual([key['at'] for key in keys], [0, .5, 1])
                self.assertEqual([key['easing'] for key in keys[:-1]], ['smootherstep', 'smootherstep'])
                for name in layers.DEFAULTS:
                    for boundary in (0, .5, 1):
                        point = layers.evaluate(keys, boundary)[name]
                        for offset in (-epsilon, epsilon):
                            if 0 <= boundary + offset <= 1:
                                speed = abs(layers.evaluate(keys, boundary + offset)[name] - point) / epsilon
                                self.assertLess(speed, .001)
        self.assertEqual(animated, 5)

    def test_selected_rgba_frames_remain_opaque_and_closing_matches_start(self):
        first, _ = layers.render_at(self.prepared, 0)
        closing, _ = layers.render_at(self.prepared, 3200)
        self.assertEqual(first.tobytes(), closing.tobytes())
        for timestamp in (0, 800, 1600, 2400, 3180):
            image, _ = layers.render_at(self.prepared, timestamp)
            self.assertEqual(image.getchannel('A').getextrema(), (255, 255))
        middle, _ = layers.render_at(self.prepared, 1600)
        self.assertNotEqual(first.tobytes(), middle.tobytes())

    def test_native_full_hd_is_not_claimed_or_enabled(self):
        oversized = copy.deepcopy(self.scene)
        oversized.update(width=1080, height=1920)
        with self.assertRaises(ValueError):
            layers.normalize_scene(oversized)


if __name__ == '__main__':
    unittest.main()
