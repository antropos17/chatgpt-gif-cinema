"""Behavioral checks for editable, bounded, offline motion recipes."""
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gif_cinema import layers, presets


class MotionPresetTests(unittest.TestCase):
    def test_published_gifs_match_receipt_and_actual_decoded_timing(self):
        from PIL import Image, ImageSequence
        root = Path(__file__).resolve().parents[1] / 'docs/assets/motion-presets'
        receipt = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['api_calls'], 0)
        self.assertEqual(set(receipt['presets']), set(presets.NAMES))
        for name, record in receipt['presets'].items():
            with self.subTest(name=name):
                for kind in ('gif', 'scene'):
                    self.assertEqual(hashlib.sha256((root / record[kind]).read_bytes()).hexdigest(), record[kind + '_sha256'])
                with Image.open(root / record['gif']) as image:
                    self.assertEqual(image.size, (480, 320))
                    self.assertEqual(image.info['loop'], 0)
                    frames, delays = [], []
                    for frame in ImageSequence.Iterator(image):
                        frames.append(frame.convert('RGB').tobytes())
                        delays.append(frame.info['duration'])
                self.assertEqual(delays, record['gif_delays_ms'])
                self.assertEqual(sum(delays), 3200)
                self.assertEqual(len(set(frames)), record['unique_decoded_drawings'])
                self.assertGreater(len(set(frames)), 30)

    def test_all_presets_render_reopen_and_close_without_network(self):
        with tempfile.TemporaryDirectory() as temporary, patch('socket.create_connection', side_effect=AssertionError('Network forbidden')):
            for name in presets.NAMES:
                with self.subTest(name=name):
                    path = presets.save_preset(name, Path(temporary).resolve() / name)
                    original = path.read_bytes()
                    prepared = layers.prepare_scene(path)
                    self.assertEqual(prepared['assets'], {})
                    self.assertEqual(prepared['scene']['duration_ms'], 3200)
                    first = layers.render_at(prepared, 0)[0]
                    closing = layers.render_at(prepared, 3200)[0]
                    self.assertEqual(first.tobytes(), closing.tobytes())
                    middle = layers.render_at(prepared, 1600)[0]
                    self.assertNotEqual(first.tobytes(), middle.tobytes())
                    bundle = layers.save_bundle(prepared, Path(temporary).resolve() / (name + '-bundle'))
                    reopened = layers.prepare_scene(bundle)
                    for timestamp in (0, 480, 1600, 3160):
                        self.assertEqual(layers.render_at(prepared, timestamp)[0].tobytes(),
                                         layers.render_at(reopened, timestamp)[0].tobytes())
                    self.assertEqual(path.read_bytes(), original)

    def test_reading_hold_text_fits_canvas_and_orbit_interior(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in presets.NAMES:
                prepared = layers.prepare_scene(presets.save_preset(name, Path(temporary).resolve() / name))
                for layer in prepared['scene']['layers']:
                    if layer['type'] != 'text':
                        continue
                    raster = prepared['rasters'][layer['id']]
                    for timestamp in (1200, 1600, 2200):
                        state = layers.layer_transform(prepared['scene'], layer, timestamp)
                        x, y = state['x'] * 480, state['y'] * 320
                        half_w, half_h = raster.width * state['zoom'] / 2, raster.height * state['zoom'] / 2
                        self.assertGreaterEqual(x - half_w, 20)
                        self.assertLessEqual(x + half_w, 460)
                        self.assertGreaterEqual(y - half_h, 20)
                        self.assertLessEqual(y + half_h, 304)
                        self.assertEqual(state['opacity'], 1)

    def test_custom_copy_unicode_and_color_are_preserved(self):
        scene = presets.make_scene('focus-card', headline='НАЙДИ', second_line='РИТМ', caption='Твой следующий кадр', accent='#eebb55')
        copy = {row['id']: row for row in scene['layers'] if row['type'] == 'text'}
        self.assertEqual(copy['headline']['text'], 'НАЙДИ')
        self.assertEqual(copy['second_line']['fill'], '#eebb55')
        self.assertEqual(layers.parse_scene(layers.serialize_scene(scene)), scene)

    def test_bad_copy_fails_before_writing_and_existing_output_is_immutable(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary).resolve() / 'new'
            for options in ({'headline': 'X' * 100}, {'caption': '😀'}, {'accent': '#ffffff00'}, {'headline': ''}):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    presets.save_preset('orbit-badge', destination, **options)
                self.assertFalse(destination.exists())
            path = presets.save_preset('focus-card', destination)
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                presets.save_preset('stagger-title', destination)
            self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
