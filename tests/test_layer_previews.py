"""Offline regression tests for previews selected from visible export samples."""
import gc
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import weakref

from PIL import Image
from gif_cinema import layers


def rect(identifier='layer', **changes):
    return {'id': identifier, 'type': 'rect', 'size': [8, 8], 'fill': '#eeaa66', **changes}


def scene(layer_list=None, **changes):
    return {'format': layers.FORMAT, 'schema_version': 1, 'width': 32, 'height': 32,
            'duration_ms': 160, 'fps': 25, 'layers': layer_list or [rect()], **changes}


class PreviewTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'scene.json'
        for name in ('urllib.request.OpenerDirector.open', 'socket.create_connection'):
            guard = patch(name, side_effect=AssertionError('Network forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def prepare(self, value):
        self.path.write_bytes(layers.serialize_scene(value))
        return layers.prepare_scene(self.path)

    def collect(self, prepared):
        candidates = {}
        value = prepared['scene']
        for timestamp in range(0, value['duration_ms'], 1000 // value['fps']):
            layers.render_at(prepared, timestamp, _layer_previews=candidates)
        return candidates

    def assert_sample(self, prepared, candidate, timestamp):
        self.assertEqual(candidate['time_ms'], timestamp)
        self.assertEqual(candidate['frame'], timestamp // (1000 // prepared['scene']['fps']))
        self.assertIsNotNone(candidate['image'].getchannel('A').getbbox())
        expected, _ = layers.render_at(prepared, timestamp, only_layer='layer')
        self.assertEqual(candidate['image'].tobytes(), expected.tobytes())

    def test_early_and_late_intervals_do_not_use_global_midpoint(self):
        for start, end, expected in ((40, 160, 80), (800, 960, 880)):
            with self.subTest(interval=(start, end)):
                prepared = self.prepare(scene([rect(in_ms=start, out_ms=end)], duration_ms=1000))
                old, _ = layers.render_at(prepared, 500, only_layer='layer')
                self.assertIsNone(old.getchannel('A').getbbox())
                self.assert_sample(prepared, self.collect(prepared)['layer'], expected)

    def test_one_frame_interval_and_exclusive_out_time(self):
        prepared = self.prepare(scene([rect(in_ms=80, out_ms=120)]))
        self.assert_sample(prepared, self.collect(prepared)['layer'], 80)
        candidates = {}
        layers.render_at(prepared, 120, _layer_previews=candidates)
        self.assertEqual(candidates, {})

    def test_midpoint_transparent_uses_nearest_visible_earlier_tie(self):
        keys = [{'at': 0, 'opacity': 1}, {'at': .5, 'opacity': 0}, {'at': 1, 'opacity': 1}]
        prepared = self.prepare(scene([rect(keyframes=keys)]))
        self.assert_sample(prepared, self.collect(prepared)['layer'], 40)

    def test_off_canvas_midpoint_does_not_hide_other_visible_frames(self):
        keys = [{'at': 0, 'x': .5}, {'at': .5, 'x': -2}, {'at': 1, 'x': .5}]
        prepared = self.prepare(scene([rect(keyframes=keys)]))
        self.assert_sample(prepared, self.collect(prepared)['layer'], 0)

    def test_exact_midpoint_and_half_frame_ties_at_both_frame_rates(self):
        for fps, duration, expected in ((25, 160, 80), (25, 120, 40), (50, 80, 40), (50, 60, 20)):
            with self.subTest(fps=fps, duration=duration):
                prepared = self.prepare(scene(fps=fps, duration_ms=duration))
                self.assert_sample(prepared, self.collect(prepared)['layer'], expected)

    def test_no_visible_export_frame_keeps_blank_png_and_explicit_metadata(self):
        cases = [rect(fill='#12345600'),
                 rect(keyframes=[{'at': 0, 'opacity': 0}, {'at': 1}]),
                 rect(keyframes=[{'at': 0, 'opacity': .001}, {'at': 1}]),
                 rect(keyframes=[{'at': 0, 'x': -2}, {'at': 1}])]
        for index, layer in enumerate(cases):
            with self.subTest(layer=layer):
                prepared = self.prepare(scene([layer]))
                candidates = self.collect(prepared)
                self.assertEqual(candidates, {})
                destination = self.root / f'blank-{index}'; destination.mkdir()
                record = layers._write_layer_previews(candidates, prepared['scene'], destination)['layer']
                self.assertEqual(record, {'filename': 'layers/layer.png', 'in_ms': 0, 'out_ms': 160,
                    'status': 'no-visible-export-frame', 'frame': None, 'time_ms': None, 'alpha_bbox': None})
                with Image.open(destination / 'layer.png') as image:
                    self.assertEqual((image.mode, image.size), ('RGBA', (32, 32)))
                    self.assertIsNone(image.getchannel('A').getbbox())

    def test_transparent_image_has_no_visible_sample(self):
        Image.new('RGBA', (8, 8), (20, 30, 40, 0)).save(self.root / 'transparent.png')
        prepared = self.prepare(scene([{'id': 'layer', 'type': 'image', 'source': 'transparent.png', 'size': [8, 8]}]))
        self.assertEqual(self.collect(prepared), {})

    def test_visibility_between_samples_or_at_closing_endpoint_is_not_exported(self):
        cases = [([{'at': 0, 'opacity': 0}, {'at': .125, 'opacity': 1},
                   {'at': .25, 'opacity': 0}, {'at': 1}], 20),
                 ([{'at': 0, 'opacity': 0, 'easing': 'step'}, {'at': 1, 'opacity': 1}], 160)]
        for keys, diagnostic_time in cases:
            with self.subTest(time=diagnostic_time):
                prepared = self.prepare(scene([rect(keyframes=keys)]))
                candidates = self.collect(prepared)
                diagnostic, _ = layers.render_at(prepared, diagnostic_time, _layer_previews=candidates)
                self.assertIsNotNone(diagnostic.getchannel('A').getbbox())
                self.assertEqual(candidates, {})

    def test_collector_does_not_change_compositing_or_states_and_ignores_occlusion(self):
        prepared = self.prepare(scene([rect('layer'), rect('cover', size=[32, 32], fill='#112233')]))
        candidates = {}
        for timestamp in (0, 40, 80, 120):
            before, states = layers.render_at(prepared, timestamp)
            after, actual_states = layers.render_at(prepared, timestamp, _layer_previews=candidates)
            self.assertEqual(before.tobytes(), after.tobytes())
            self.assertEqual(states, actual_states)
        self.assert_sample(prepared, candidates['layer'], 80)
        self.assertEqual(set(candidates), {'layer', 'cover'})

    def test_collector_retains_without_copy_and_ties_do_not_depend_on_visit_order(self):
        value = layers.normalize_scene(scene(duration_ms=120))
        layer = value['layers'][0]
        image = Image.new('RGBA', (32, 32), 'red')
        candidates = {}
        with patch.object(image, 'copy', side_effect=AssertionError('No extra pixel copy')):
            for timestamp in (80, 0, 40, 80):
                layers._collect_layer_preview(candidates, value, layer, timestamp, image)
        self.assertIs(candidates['layer']['image'], image)
        self.assertEqual(candidates['layer']['time_ms'], 40)

    def test_saved_preview_matches_isolated_rgba_including_hidden_rgb(self):
        value = scene([rect(type='ellipse', size=[19, 19], keyframes=[
            {'at': 0, 'rotation': 17, 'opacity': .03}, {'at': 1}])])
        prepared = self.prepare(value)
        candidates = self.collect(prepared)
        destination = self.root / 'low-alpha'; destination.mkdir()
        record = layers._write_layer_previews(candidates, prepared['scene'], destination)['layer']
        expected, _ = layers.render_at(prepared, record['time_ms'], only_layer='layer')
        with Image.open(destination / 'layer.png') as actual:
            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_candidate_count_is_bounded_and_writer_releases_images(self):
        prepared = self.prepare(scene([rect(f'l{i}') for i in range(16)]))
        candidates = self.collect(prepared)
        self.assertEqual(len(candidates), 16)
        references = [weakref.ref(entry['image']) for entry in candidates.values()]
        destination = self.root / 'previews'; destination.mkdir()
        records = layers._write_layer_previews(candidates, prepared['scene'], destination)
        gc.collect()
        self.assertEqual(len(records), 16)
        self.assertEqual(candidates, {})
        self.assertTrue(all(reference() is None for reference in references))

    def test_dry_run_does_not_collect_or_claim_selected_previews(self):
        self.prepare(scene())
        with patch.object(layers, '_collect_layer_preview', side_effect=AssertionError('Dry-run must not render')):
            plan = layers.render_scene(self.path, self.root / 'dry', dry_run=True)
        self.assertNotIn('layer_previews', plan)
        self.assertFalse((self.root / 'dry').exists())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real FFmpeg and ffprobe required')
    def test_real_export_contract_reopen_legacy_receipt_and_single_render_pass(self):
        from tools.verify_layered_scene import verify
        value = scene([rect('early', in_ms=0, out_ms=40), rect('late', in_ms=120),
                       rect('blank', fill='#ffffff00')])
        prepared = self.prepare(value)
        out = self.root / 'export'
        with patch.object(layers, 'render_at', wraps=layers.render_at) as render:
            receipt = layers.render_scene(self.path, out)
        self.assertEqual(receipt['schema_version'], 1)
        self.assertEqual(receipt['frames'], 4)
        self.assertEqual(sum(receipt['gif_delays_ms']), 160)
        self.assertEqual(receipt['sampling'], 'frame i at i/fps; endpoint at duration is diagnostic and is not exported twice')
        # Four timeline frames, four reopened checks, closing and first-frame
        # diagnostics. No second isolated render pass for layer previews.
        self.assertEqual(render.call_count, 10)
        self.assertFalse(any(call.kwargs.get('only_layer') is not None for call in render.call_args_list))
        for layer in prepared['scene']['layers']:
            record = receipt['layer_previews'][layer['id']]
            self.assertIn(record['filename'], receipt['outputs'])
            with Image.open(out / record['filename']) as image:
                if record['status'] == 'visible':
                    expected, _ = layers.render_at(prepared, record['time_ms'], only_layer=layer['id'])
                    self.assertEqual(image.tobytes(), expected.tobytes())
                    self.assertEqual(list(image.getchannel('A').getbbox()), record['alpha_bbox'])
                    self.assertTrue(layer['in_ms'] <= record['time_ms'] < layer['out_ms'])
                else:
                    self.assertIsNone(image.getchannel('A').getbbox())
        self.assertEqual(receipt['layer_previews']['early']['time_ms'], 0)
        self.assertEqual(receipt['layer_previews']['late']['time_ms'], 120)
        self.assertEqual(verify(out)['frames_reopened_and_matched'], 4)
        # These new fields are additive; the existing verifier still accepts
        # historical schema-1 receipts without preview metadata.
        receipt.pop('layer_previews'); receipt.pop('layer_preview_sampling')
        (out / 'receipt.json').write_text(json.dumps(receipt))
        self.assertEqual(verify(out)['frames_reopened_and_matched'], 4)


if __name__ == '__main__':
    unittest.main()
