"""Offline geometry, coverage, source immutability and actual media regressions."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops
from gif_cinema import layers, strokes


def fixture(**changes):
    return {'format': layers.FORMAT, 'schema_version': 1, 'width': 64, 'height': 32,
            'duration_ms': 320, 'fps': 25, 'loop': False, 'layers': [
                {'id': 'ink', 'type': 'stroke', 'size': [64, 32],
                 'points': [[8, 16], [12, 16], [56, 16]], 'stroke': '#40c0ff', 'stroke_width': 4,
                 'keyframes': [{'at': 0, 'reveal': 0}, {'at': .5, 'reveal': 1}, {'at': 1}]}], **changes}


class GeometryTests(unittest.TestCase):
    def test_arclength_not_vertex_count_and_exact_endpoints(self):
        path = strokes.prepare_path([[0, 0], [1, 0], [10, 0], [10, 10]])
        self.assertEqual(strokes.prefix(path, 0), [])
        self.assertEqual(strokes.prefix(path, .25)[-1], (5, 0))
        self.assertEqual(strokes.prefix(path, .5)[-1], (10, 0))
        self.assertEqual(strokes.prefix(path, .75)[-1], (10, 5))
        self.assertEqual(strokes.prefix(path, 1), path['points'])
        self.assertEqual(path['length'], 20)

    def test_repeated_vertices_and_microscopic_edges_do_not_divide_by_zero(self):
        path = strokes.prepare_path([[0, 0], [0, 0], [100, 0], [100, 1e-300]])
        self.assertEqual(strokes.prefix(path, .5)[-1], (50, 0))
        self.assertEqual(strokes.prefix(path, 1)[-1], (100, 0))

    def test_distance_is_geometric_along_diagonal(self):
        path = strokes.prepare_path([[0, 0], [3, 4], [8, 4]])
        self.assertEqual(path['length'], 10)
        self.assertEqual(strokes.prefix(path, .25)[-1], (1.5, 2))
        self.assertEqual(strokes.prefix(path, .75)[-1], (5.5, 4))

    def test_exact_simplification_keeps_backtracking_and_tiny_turns(self):
        for points in ([[0, 0], [10, 0], [5, 0]], [[0, 0], [1, 0], [2, 1e-20]]):
            self.assertEqual(strokes.prepare_path(points)['points'], [tuple(p) for p in points])

    def test_reveal_requires_finite_bounded_nonboolean_number(self):
        path = strokes.prepare_path([[0, 0], [1, 1]])
        for value in (-1, 1.1, True, None, '1', float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                strokes.prefix(path, value)

    def test_collinear_subdivision_preserves_coverage_at_every_pen_position(self):
        for width in (1, 2, 3, 4, 7, 12):
            for start, end in [([8, 32], [56, 32]), ([32, 8], [32, 56]),
                               ([8, 8], [56, 56]), ([8, 56], [56, 8]),
                               ([8, 16], [56, 40])]:
                middle = [(a + b) / 2 for a, b in zip(start, end)]
                simple, split = strokes.prepare_path([start, end]), strokes.prepare_path([start, middle, end])
                layer = {'size': [64, 64], 'stroke_width': width, 'stroke': '#ff000080'}
                for reveal in (.25, .5, .75, 1):
                    with self.subTest(width=width, start=start, end=end, reveal=reveal):
                        first = strokes.rasterize(layer, simple, reveal, layers.SUPERSAMPLE)
                        second = strokes.rasterize(layer, split, reveal, layers.SUPERSAMPLE)
                        self.assertEqual(first.tobytes(), second.tobytes())


class ContractTests(unittest.TestCase):
    def test_roundtrip_and_inheritance_preserve_author_input(self):
        value = fixture()
        original = copy.deepcopy(value)
        scene = layers.normalize_scene(value)
        self.assertEqual(value, original)
        self.assertEqual(scene, layers.normalize_scene(scene))
        self.assertEqual(scene, layers.parse_scene(layers.serialize_scene(scene)))
        keys = scene['layers'][0]['keyframes']
        self.assertEqual([k['reveal'] for k in keys], [0, 1, 1])
        self.assertEqual(layers.evaluate(keys, .25)['reveal'], .5)
        self.assertEqual(layers.evaluate(keys, 1)['reveal'], 1)

    def test_stroke_defaults_to_fully_visible(self):
        value = fixture(); value['layers'][0].pop('keyframes')
        scene = layers.normalize_scene(value)
        self.assertEqual([k['reveal'] for k in scene['layers'][0]['keyframes']], [1, 1])

    def test_other_layer_types_reject_reveal_and_strokes_reject_extra_fields(self):
        for kind, fields in [('rect', {'size': [10, 10]}), ('ellipse', {'size': [10, 10]}),
                             ('text', {'text': 'Hi'}), ('image', {'source': 'a.png', 'size': [10, 10]})]:
            value = fixture(layers=[{'id': 'other', 'type': kind, **fields,
                'keyframes': [{'at': 0, 'reveal': 0}, {'at': 1, 'reveal': 1}]}])
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'Keyframe'):
                layers.normalize_scene(value)
        for key in ('svg', 'path', 'url', 'fill', 'expression', 'dashes', 'mask'):
            value = fixture(); value['layers'][0][key] = 'unsupported'
            with self.subTest(key=key), self.assertRaises(ValueError):
                layers.normalize_scene(value)

    def test_invalid_points_width_and_reveal_fail_preflight(self):
        cases = [('points', value) for value in (None, [], [[1, 1]], [[1, 1]] * 2,
            [[0, 0]] * 513, [[0, 0], [64, 0]], [[0, -1], [2, 1]], [[0, 0], [1]],
            [[0, 0], [float('nan'), 1]], [[0, 0], [True, 1]], [[0, 0], [1, 32]],
            [[0, 0], ['2', 1]], 'M0,0 L2,2')]
        cases += [('stroke_width', value) for value in (0, 129, 2.5, True, float('inf'))]
        for field, value in cases:
            scene = fixture(); scene['layers'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                layers.normalize_scene(scene)
        for value in (-.1, 1.1, True, '1', None, float('nan'), float('inf')):
            scene = fixture(); scene['layers'][0]['keyframes'][0]['reveal'] = value
            with self.subTest(reveal=value), self.assertRaises(ValueError):
                layers.normalize_scene(scene)

    def test_reveal_uses_existing_easing_and_can_erase(self):
        keys = layers.normalize_keyframes([{'at': 0, 'reveal': 0, 'easing': 'ease-in'},
            {'at': .5, 'reveal': 1, 'easing': [0, 0, 1, 1]}, {'at': 1, 'reveal': 0}], stroke=True)
        self.assertEqual(layers.evaluate(keys, .25)['reveal'], .25)
        self.assertAlmostEqual(layers.evaluate(keys, .75)['reveal'], .5)
        self.assertEqual(layers.evaluate(keys, 1)['reveal'], 0)

    def test_dynamic_work_budgets_reject_before_any_allocation(self):
        for name, text in [('MAX_RASTER_PIXEL_FRAMES', 'dynamic stroke raster'),
                            ('MAX_SEGMENT_FRAMES', 'dynamic stroke segment')]:
            with patch.object(strokes, name, 1), patch('PIL.Image.new', side_effect=AssertionError('No pixels')):
                with self.assertRaisesRegex(ValueError, text):
                    layers.normalize_scene(fixture())
        value = fixture(layers=[{**fixture()['layers'][0], 'id': str(i)} for i in range(2)])
        single = layers.raster_budget(layers.normalize_scene(fixture()))
        double = layers.raster_budget(layers.normalize_scene(value))
        self.assertEqual(double['stroke_segment_frames'], 2 * single['stroke_segment_frames'])
        self.assertEqual(double['stroke_supersampled_pixel_frames'], 2 * single['stroke_supersampled_pixel_frames'])


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'scene.json'
        for name in ('urllib.request.OpenerDirector.open', 'socket.create_connection'):
            guard = patch(name, side_effect=AssertionError('Network forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def prepare(self, value=None):
        self.path.write_bytes(layers.serialize_scene(value or fixture()))
        return layers.prepare_scene(self.path)

    def test_blank_start_growing_tip_and_completed_hold(self):
        prepared = self.prepare()
        first, states = layers.render_at(prepared, 0)
        middle, _ = layers.render_at(prepared, 80)
        last, _ = layers.render_at(prepared, 160)
        hold, _ = layers.render_at(prepared, 280)
        self.assertEqual(states['ink']['reveal'], 0)
        self.assertIsNone(first.getchannel('A').getbbox())
        self.assertGreaterEqual(middle.getpixel((20, 16))[3], 240)
        self.assertEqual(middle.getpixel((48, 16))[3], 0)
        self.assertGreaterEqual(last.getpixel((48, 16))[3], 240)
        self.assertEqual(last.tobytes(), hold.tobytes())
        self.assertEqual(prepared['rasters']['ink'].mode, 'RGBa')

    def test_round_caps_antialias_and_alpha_do_not_accumulate_at_joins(self):
        value = fixture(); layer = value['layers'][0]
        layer['stroke'] = '#ff884480'
        layer['points'] = [[8, 16], [32, 16], [32, 24], [32, 16], [56, 16]]
        prepared = self.prepare(value)
        frame, _ = layers.render_at(prepared, 160)
        for actual, expected in zip(frame.getpixel((20, 16))[:3], (255, 136, 68)):
            self.assertLessEqual(abs(actual - expected), 1)  # Premultiplied 8-bit rounding.
        self.assertGreaterEqual(frame.getpixel((20, 16))[3], 120)
        self.assertGreaterEqual(frame.getpixel((32, 16))[3], 120)
        self.assertLessEqual(frame.getpixel((32, 16))[3], 128)
        self.assertGreater(frame.getpixel((7, 16))[3], 0)
        alphas = set(frame.getchannel('A').tobytes())
        self.assertGreater(len(alphas), 3)
        self.assertEqual(max(alphas), 128)

    def test_transform_opacity_and_layer_lifetime_apply_to_reveal(self):
        value = fixture(); layer = value['layers'][0]
        layer.update(in_ms=80, out_ms=240,
            keyframes=[{'at': 0, 'reveal': 0, 'opacity': .5, 'y': .25},
                       {'at': .5, 'reveal': 1}, {'at': 1}])
        prepared = self.prepare(value)
        before, _ = layers.render_at(prepared, 40)
        active, states = layers.render_at(prepared, 160)
        after, _ = layers.render_at(prepared, 240)
        self.assertIsNone(before.getchannel('A').getbbox())
        self.assertIsNone(after.getchannel('A').getbbox())
        self.assertEqual(states['ink']['reveal'], 1)
        self.assertGreaterEqual(active.getpixel((20, 8))[3], 120)
        self.assertLessEqual(active.getpixel((20, 8))[3], 128)
        self.assertEqual(active.getpixel((20, 24))[3], 0)

    def test_portable_save_reopens_every_frame_and_does_not_change_source(self):
        prepared = self.prepare(); original = self.path.read_bytes()
        saved = layers.save_bundle(prepared, self.root / 'saved')
        reopened = layers.prepare_scene(saved)
        for time in range(0, 321, 40):
            self.assertEqual(layers.render_at(prepared, time)[0].tobytes(),
                             layers.render_at(reopened, time)[0].tobytes())
        self.assertEqual(self.path.read_bytes(), original)

    def test_static_stroke_reuses_cached_raster_and_zero_reveal_never_draws(self):
        prepared = self.prepare()
        with patch.object(strokes, 'rasterize', side_effect=AssertionError('Should be cached or blank')):
            layers.render_at(prepared, 0)
            layers.render_at(prepared, 160)
            layers.render_at(prepared, 280)

    def test_full_raster_matches_direct_draw_and_reveal_is_monotonic(self):
        prepared = self.prepare()
        layer = prepared['scene']['layers'][0]
        full = strokes.rasterize(layer, prepared['stroke_paths']['ink'], 1, layers.SUPERSAMPLE)
        cached = prepared['rasters']['ink'].convert('RGBA')
        self.assertIsNone(ImageChops.difference(full, cached).getbbox())
        areas = [sum(layers.render_at(prepared, time)[0].getchannel('A').tobytes()) for time in (0, 40, 80, 120, 160)]
        self.assertEqual(areas, sorted(set(areas)))

    def test_dry_run_is_offline_and_writes_nothing(self):
        self.prepare(); output = self.root / 'not-written'
        with patch.object(layers, 'run_command', side_effect=AssertionError('No encoder')):
            plan = layers.render_scene(self.path, output, dry_run=True)
        self.assertFalse(output.exists())
        self.assertEqual(plan['api_calls'], 0)
        self.assertGreater(plan['raster_budget']['stroke_segment_frames'], 0)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
    def test_actual_gif_mp4_receipt_and_all_frame_reopen(self):
        from tools.verify_layered_scene import verify
        self.prepare(); output = self.root / 'render'
        receipt = layers.render_scene(self.path, output)
        self.assertEqual(receipt['status'], 'human-review-required')
        self.assertEqual(receipt['samples'][0]['layers']['ink']['reveal'], 0)
        self.assertEqual(receipt['samples'][-1]['layers']['ink']['reveal'], 1)
        self.assertEqual(receipt['api_calls'], 0)
        self.assertEqual(receipt['layer_previews']['ink']['status'], 'visible')
        self.assertEqual(verify(output)['frames_reopened_and_matched'], 8)
        with Image.open(output / 'preview.gif') as gif:
            self.assertNotIn('loop', gif.info)
            delays = []
            for index in range(gif.n_frames):
                gif.seek(index); delays.append(gif.info['duration'])
            self.assertEqual(sum(delays), 320)
        with self.assertRaisesRegex(ValueError, 'new directory'):
            layers.render_scene(self.path, output)

    def test_failed_encoder_leaves_no_completed_output(self):
        self.prepare(); output = self.root / 'failed'
        with patch.object(layers.shutil, 'which', return_value='/ffmpeg'), \
             patch.object(layers, 'run_command', side_effect=RuntimeError('encoder failed')):
            with self.assertRaises(RuntimeError):
                layers.render_scene(self.path, output)
        self.assertFalse(output.exists())


class IncludedExampleTests(unittest.TestCase):
    def test_original_example_has_distinct_strokes_and_actual_final_hold(self):
        path = Path(__file__).resolve().parents[1] / 'examples' / 'stroke-reveal.json'
        prepared = layers.prepare_scene(path)
        self.assertEqual(prepared['assets'], {})
        self.assertFalse(prepared['scene']['loop'])
        self.assertEqual(prepared['scene']['duration_ms'], 4000)
        _, drawing = layers.render_at(prepared, 2000)
        self.assertGreater(drawing['heart']['reveal'], 0)
        self.assertLess(drawing['heart']['reveal'], 1)
        self.assertEqual(drawing['underline']['reveal'], 0)
        self.assertEqual(drawing['spark']['reveal'], 0)
        last, states = layers.render_at(prepared, 3980)
        for name in ('heart', 'underline', 'spark'):
            self.assertEqual(states[name]['reveal'], 1)
        for at in range(3600, 4000, 20):
            self.assertEqual(last.tobytes(), layers.render_at(prepared, at)[0].tobytes())


if __name__ == '__main__':
    unittest.main()
