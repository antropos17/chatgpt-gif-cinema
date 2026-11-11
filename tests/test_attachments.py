"""Authored prop anchors are offline transforms, never automatic contact acceptance."""
import copy
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import attachments, layers
from tools.verify_layered_scene import verify

ROOT = Path(__file__).resolve().parents[1]


def binding(parent='hand', start=0, end=160, point=None):
    return {'parent': parent, 'point': point or [1, .5], 'start_ms': start, 'end_ms': end}


def scene():
    return {'format': layers.FORMAT, 'schema_version': 1, 'width': 64, 'height': 64,
        'duration_ms': 160, 'fps': 25, 'loop': False, 'layers': [
            {'id': 'hand', 'type': 'rect', 'size': [16, 8], 'fill': '#00ff00',
             'keyframes': [{'at': 0, 'x': .25}, {'at': 1, 'x': .75}]},
            {'id': 'prop', 'type': 'rect', 'size': [4, 4], 'fill': '#ff0000',
             'attachments': [binding()]}]}


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS exposes its temporary directory through the /var symlink.
        # Use the physical test directory; do not relax production output guards.
        self.root = Path(self.temp.name).resolve()

    def prepare(self, value=None):
        path = self.root / 'scene.json'
        path.write_text(json.dumps(scene() if value is None else value), encoding='utf-8')
        return layers.prepare_scene(path)

    def test_normalization_roundtrip_and_no_input_mutation(self):
        value = scene(); original = copy.deepcopy(value)
        normalized = layers.normalize_scene(value)
        self.assertEqual(value, original)
        self.assertEqual(normalized, layers.parse_scene(layers.serialize_scene(normalized)))

    def test_target_point_moves_with_parent_and_actual_rendered_prop(self):
        prepared = self.prepare()
        for timestamp, expected in ((0, 24), (40, 32), (80, 40), (120, 48), (160, 56)):
            frame, states = layers.render_at(prepared, timestamp, only_layer='prop')
            self.assertEqual(states['prop']['x'] * 64, expected)
            self.assertEqual(frame.getbbox(), (expected - 2, 30, expected + 2, 34))
            self.assertEqual(states['prop']['attachment']['parent'], 'hand')

    def test_rotation_zoom_and_noncentral_parent_and_child_anchor(self):
        value = scene()
        parent, child = value['layers']
        parent['anchor'] = [0, 0]
        parent['keyframes'] = [{'at': 0, 'rotation': 90, 'zoom': 2}, {'at': 1}]
        child['anchor'] = [0, 0]
        child['attachments'][0]['point'] = [.5, .5]
        prepared = self.prepare(value)
        frame, states = layers.render_at(prepared, 0, only_layer='prop')
        self.assertAlmostEqual(states['prop']['x'] * 64, 24)
        self.assertAlmostEqual(states['prop']['y'] * 64, 48)
        self.assertEqual(frame.getbbox(), (24, 48, 28, 52))
        self.assertEqual(states['prop']['rotation'], 0)
        self.assertEqual(states['prop']['zoom'], 1)

    def test_parent_opacity_is_not_inherited(self):
        value = scene(); value['layers'][0]['keyframes'][0]['opacity'] = 0
        frame, states = layers.render_at(self.prepare(value), 40)
        self.assertEqual(states['prop']['opacity'], 1)
        self.assertGreater(frame.getchannel('A').getextrema()[1], 0)

    def test_actual_fitted_raster_not_declared_box_sets_point(self):
        Image.new('RGBA', (8, 4), 'blue').save(self.root / 'source.png')
        value = scene()
        value['layers'][0] = {'id': 'hand', 'type': 'image', 'source': 'source.png', 'size': [32, 32]}
        value['layers'][1]['attachments'][0]['point'] = [1, 1]
        prepared = self.prepare(value)
        self.assertEqual(prepared['rasters']['hand'].size, (32, 16))
        state = attachments.resolve(prepared, 0)['prop']
        self.assertEqual((state['x'] * 64, state['y'] * 64), (48, 40))

    def test_nested_attachments_work_independent_of_paint_order(self):
        value = scene()
        value['layers'].append({'id': 'glow', 'type': 'ellipse', 'size': [2, 2],
                                'attachments': [binding('prop', point=[.5, .5])]})
        prepared = self.prepare(value)
        first, state = layers.render_at(prepared, 80, only_layer='glow')
        value['layers'].reverse()
        second, reversed_state = layers.render_at(self.prepare(value), 80, only_layer='glow')
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertEqual(state, reversed_state)
        self.assertEqual(state['glow']['x'] * 64, 40)

    def switched(self, gap=False):
        value = scene()
        value['layers'].append({'id': 'hook', 'type': 'rect', 'size': [8, 8],
                               'keyframes': [{'at': 0, 'x': .75 if gap else .625}, {'at': 1}]})
        value['layers'][1]['attachments'] = [binding(end=80), binding('hook', 80, 160, [.5, .5])]
        return value

    def test_exact_switch_boundary_and_closing_endpoint(self):
        prepared = self.prepare(self.switched())
        self.assertEqual(attachments.resolve(prepared, 80, before=True)['prop']['attachment']['parent'], 'hand')
        self.assertEqual(attachments.resolve(prepared, 80)['prop']['attachment']['parent'], 'hook')
        self.assertEqual(attachments.resolve(prepared, 160)['prop']['attachment']['parent'], 'hook')
        report = attachments.review(prepared)
        self.assertEqual(report['max_switch_gap_px'], 0)
        self.assertEqual(report['status'], 'human-review-required')
        self.assertEqual(len(report['switches']), 1)

    def test_switch_gap_is_visible_and_never_silently_repaired(self):
        prepared = self.prepare(self.switched(True))
        report = attachments.review(prepared)
        self.assertEqual(report['max_switch_gap_px'], 8)
        self.assertEqual(report['switches'][0]['before_anchor_px'], [40, 32])
        self.assertEqual(report['switches'][0]['after_anchor_px'], [48, 32])
        self.assertEqual(attachments.resolve(prepared, 80)['prop']['x'] * 64, 48)

    def test_ancestor_switch_gap_is_reported_for_descendants(self):
        value = self.switched(True)
        value['layers'].append({'id': 'glow', 'type': 'ellipse', 'size': [2, 2],
                                'attachments': [binding('prop', point=[.5, .5])]})
        report = attachments.review(self.prepare(value))
        inherited = next(row for row in report['switches'] if row['layer'] == 'glow')
        self.assertFalse(inherited['own_schedule_switch'])
        self.assertEqual(inherited['anchor_gap_px'], 8)

    def test_step_jump_at_transfer_uses_true_outgoing_pose(self):
        value = self.switched()
        value['layers'][0]['keyframes'] = [{'at': 0, 'x': .25, 'easing': 'step'},
                                          {'at': .5, 'x': .5}, {'at': 1}]
        report = attachments.review(self.prepare(value))
        self.assertEqual(report['switches'][0]['before_anchor_px'], [24, 32])
        self.assertEqual(report['switches'][0]['after_anchor_px'], [40, 32])
        self.assertEqual(report['max_switch_gap_px'], 16)

    def test_parent_can_end_when_attachment_changes(self):
        value = self.switched()
        value['layers'][0]['out_ms'] = 80
        # The old parent's closing pose changes because its local duration changed.
        report = attachments.review(self.prepare(value))
        self.assertEqual(report['switches'][0]['before_anchor_px'], [56, 32])
        self.assertEqual(report['switches'][0]['after_anchor_px'], [40, 32])

    def test_no_attachments_preserves_legacy_pixel_and_state_contract(self):
        value = scene(); del value['layers'][1]['attachments']
        prepared = self.prepare(value)
        self.assertIsNone(attachments.review(prepared))
        frame, states = layers.render_at(prepared, 40)
        for layer in prepared['scene']['layers']:
            self.assertEqual(states[layer['id']], layers.layer_transform(prepared['scene'], layer, 40))
        self.assertEqual(frame.getpixel((32, 32)), (255, 0, 0, 255))

    def test_bad_schedule_schema_values_and_limits(self):
        for bad in (None, [], 'hand', [binding()] * 33, [{}],
                    [{**binding(), 'script': 'x'}], [{**binding(), 'point': [1]}],
                    [{**binding(), 'point': [1, float('nan')]}], [{**binding(), 'point': [True, .5]}],
                    [{**binding(), 'point': [2, 0]}], [{**binding(), 'parent': []}],
                    [binding('HAND')], [binding('missing')], [binding('prop')],
                    [binding(start=True)], [binding(end=159)], [binding(start=40)],
                    [binding(end=80)], [binding(end=80), binding(start=40)],
                    [binding(end=40), binding(start=80)]):
            with self.subTest(bad=bad):
                value = scene(); value['layers'][1]['attachments'] = bad
                with self.assertRaises(ValueError):
                    layers.normalize_scene(value)

    def test_parent_visibility_and_position_rejected_before_rasterization(self):
        for field, value in (('in_ms', 40), ('out_ms', 120)):
            data = scene(); data['layers'][0][field] = value
            with patch.object(layers, 'rasterize', side_effect=AssertionError), self.assertRaisesRegex(ValueError, 'active'):
                self.prepare(data)
        data = scene(); data['layers'][1]['keyframes'] = [{'at': 0}, {'at': 1, 'x': .6}]
        with self.assertRaisesRegex(ValueError, 'cannot animate x/y'):
            self.prepare(data)

    def test_direct_and_temporally_disjoint_cycles_rejected(self):
        data = scene(); data['layers'][0].pop('keyframes')
        data['layers'][0]['attachments'] = [binding('prop')]
        with self.assertRaisesRegex(ValueError, 'acyclic'):
            layers.normalize_scene(data)
        data['layers'].append({'id': 'root', 'type': 'rect', 'size': [2, 2]})
        data['layers'][0]['attachments'] = [binding('prop', end=80), binding('root', 80, 160)]
        data['layers'][1]['attachments'] = [binding('root', end=80), binding('hand', 80, 160)]
        with self.assertRaisesRegex(ValueError, 'acyclic'):
            layers.normalize_scene(data)

    def test_nonzero_child_start_uses_scene_milliseconds(self):
        data = scene(); child = data['layers'][1]
        child['in_ms'] = 40; child['out_ms'] = 120
        child['attachments'] = [binding(start=40, end=120)]
        prepared = self.prepare(data)
        self.assertIsNone(attachments.resolve(prepared, 0)['prop'])
        self.assertEqual(attachments.resolve(prepared, 40)['prop']['x'] * 64, 32)
        self.assertIsNone(attachments.resolve(prepared, 120)['prop'])

    def test_dry_run_no_network_encoder_or_output(self):
        self.prepare(self.switched())
        target = self.root / 'not-created'
        with patch.object(socket, 'socket', side_effect=AssertionError), patch.object(layers, 'run_command', side_effect=AssertionError):
            report = layers.render_scene(self.root / 'scene.json', target, dry_run=True)
        self.assertFalse(target.exists())
        self.assertEqual(report['api_calls'], 0)
        self.assertEqual(report['attachment_review']['max_switch_gap_px'], 0)

    def test_portable_save_and_reopen_preserve_every_position_and_pixel(self):
        prepared = self.prepare(self.switched())
        saved = layers.prepare_scene(layers.save_bundle(prepared, self.root / 'saved'))
        for time in (0, 40, 80, 120, 160):
            a, sa = layers.render_at(prepared, time)
            b, sb = layers.render_at(saved, time)
            self.assertEqual(a.tobytes(), b.tobytes())
            self.assertEqual(sa, sb)
        with self.assertRaises(ValueError):
            layers.save_bundle(prepared, self.root / 'saved')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_actual_export_every_frame_verification_and_immutable_input(self):
        self.prepare(self.switched())
        source = (self.root / 'scene.json').read_bytes()
        with patch.object(socket, 'socket', side_effect=AssertionError):
            report = layers.render_scene(self.root / 'scene.json', self.root / 'render')
            checked = verify(self.root / 'render')
        self.assertEqual(checked['frames_reopened_and_matched'], 4)
        self.assertEqual(report['samples'][2]['layers']['prop']['attachment']['parent'], 'hook')
        self.assertEqual((self.root / 'scene.json').read_bytes(), source)
        self.assertEqual(report['attachment_review']['max_switch_gap_px'], 0)

    def test_animated_parent_and_child_keep_native_source_clock(self):
        a, b = Image.new('RGB', (8, 4), 'blue'), Image.new('RGB', (8, 4), 'yellow')
        a.save(self.root / 'action.gif', save_all=True, append_images=[b], duration=[40, 80])
        value = scene()
        value['layers'][0] = {'id': 'hand', 'type': 'gif', 'source': 'action.gif', 'size': [32, 16], 'playback': 'loop'}
        value['layers'][1] = {'id': 'prop', 'type': 'gif', 'source': 'action.gif', 'size': [8, 4],
                               'playback': 'once', 'attachments': [binding()]}
        prepared = self.prepare(value)
        _, states = layers.render_at(prepared, 120)
        self.assertEqual(states['hand']['source_index'], 0)
        self.assertEqual(states['prop']['source_index'], 1)
        self.assertEqual(states['prop']['x'] * 64, 48)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_verifier_rejects_changed_attachment_report_or_per_frame_state(self):
        self.prepare(self.switched())
        layers.render_scene(self.root / 'scene.json', self.root / 'render')
        receipt = self.root / 'render/receipt.json'
        original = receipt.read_bytes()
        report = json.loads(original)
        report['attachment_review']['max_switch_gap_px'] = 999
        receipt.write_text(json.dumps(report), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Attachment review'):
            verify(self.root / 'render')
        report = json.loads(original)
        report['samples'][0]['layers']['prop']['attachment']['parent'] = 'invented'
        receipt.write_text(json.dumps(report), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Attachment layer states'):
            verify(self.root / 'render')

    def test_published_example_bytes_and_media_timing_match_receipt(self):
        import hashlib
        from PIL import ImageSequence
        report = json.loads((ROOT / 'examples/prop-anchors/verification.json').read_text())
        source = ROOT / 'examples/prop-anchors/scene.json'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), report['source_scene_sha256'])
        for name, record in report['files'].items():
            raw = (ROOT / name).read_bytes()
            self.assertEqual(len(raw), record['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record['sha256'])
        with Image.open(ROOT / 'docs/assets/prop-anchors/preview.gif') as gif:
            self.assertEqual(gif.size, (480, 300))
            self.assertIsNone(gif.info.get('loop'))
            delays = [frame.info['duration'] for frame in ImageSequence.Iterator(gif)]
        self.assertEqual(delays, report['gif_delays_ms'])
        self.assertEqual(len(delays), report['gif_drawings'])
        self.assertEqual(sum(delays), 6000)
        self.assertEqual(report['all_frame_verification']['frames_reopened_and_matched'], 150)

    def test_bundled_example_has_one_persistent_prop_and_no_switch_gaps(self):
        prepared = layers.prepare_scene(ROOT / 'examples/prop-anchors/scene.json')
        report = attachments.review(prepared)
        self.assertLess(report['max_switch_gap_px'], 1e-8)
        prop = next(row for row in prepared['scene']['layers'] if row['id'] == 'lantern')
        self.assertEqual([segment['parent'] for segment in prop['attachments']], ['courier-hand', 'keeper-hand', 'hook'])
        for time in range(0, 6000, 40):
            state = attachments.resolve(prepared, time)['lantern']
            self.assertEqual(state['opacity'], 1)
