"""Multi-scene pose/holder continuation is explicit, bounded and strictly offline."""
import copy
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import attachments, cli, layers, sequence


def stage():
    return {'format': layers.FORMAT, 'schema_version': 1, 'width': 32, 'height': 32,
        'fps': 25, 'duration_ms': 80, 'loop': False, 'layers': [
            {'id': 'hand', 'type': 'rect', 'size': [8, 4], 'fill': '#00ff00',
             'keyframes': [{'at': 0, 'x': .25, 'y': .5}, {'at': 1}]},
            {'id': 'hook', 'type': 'ellipse', 'size': [4, 4], 'fill': '#0000ff',
             'keyframes': [{'at': 0, 'x': .75, 'y': .5}, {'at': 1}]},
            {'id': 'prop', 'type': 'rect', 'size': [4, 4], 'fill': '#ff0000',
             'attachments': [{'start_ms': 0, 'end_ms': 80, 'parent': 'hand', 'point': [.5, .5]}]}]}


def project():
    return {'format': sequence.FORMAT, 'schema_version': 1, 'title': 'Carry, release, leave',
        'stage': 'stage.json', 'shots': [
            {'id': '01-carry', 'action': 'Carry the prop to the hook.', 'duration_ms': 160,
             'tracks': {'hand': {'keyframes': [{'at': 0}, {'at': .5, 'x': .75}, {'at': 1}]}}},
            {'id': '02-release', 'action': 'Leave the prop on the hook and withdraw the hand.', 'duration_ms': 160,
             'tracks': {'prop': {'attachments': [{'start_ms': 0, 'end_ms': 160, 'parent': 'hook', 'point': [.5, .5]}]},
                        'hand': {'keyframes': [{'at': 0}, {'at': .5, 'x': .25}, {'at': 1}]}}},
            {'id': '03-result', 'action': 'Keep the hanging prop visible.', 'duration_ms': 80}]}


class SequenceFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / 'sequence.json'
        self.stage = self.root / 'stage.json'
        self.value, self.seed = project(), stage()
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.value), encoding='utf-8')
        self.stage.write_text(json.dumps(self.seed), encoding='utf-8')

    def compile(self):
        self.save()
        return sequence.compile_sequence(self.path)


class SequenceTests(SequenceFixture, unittest.TestCase):
    def test_carries_poses_and_holder_without_repeating_keyframes(self):
        result = self.compile()
        report = result['report']
        self.assertEqual(report['duration_ms'], 400)
        self.assertEqual(report['frames'], 10)
        self.assertEqual([row['start_ms'] for row in report['timeline']], [0, 160, 320])
        for row in report['timeline'][1:]:
            self.assertEqual(row['start_state']['prop']['x'], .75)
            self.assertEqual(row['end_state']['prop']['x'], .75)
            self.assertEqual(row['start_state']['prop']['attachment']['parent'], 'hook')
        self.assertEqual(report['timeline'][2]['start_state']['hand']['x'], .25)
        self.assertEqual(report['visual_acceptance'], 'not-established')
        self.assertEqual(report['provider_calls'], 0)

    def test_does_not_modify_authored_inputs(self):
        original = copy.deepcopy(self.value)
        result = self.compile()
        self.assertEqual(self.value, original)
        self.assertEqual(json.loads(self.path.read_text()), original)
        self.assertEqual(len(result['compiled']), 3)

    def test_boundary_teleport_is_rejected_not_repaired(self):
        for layer, track in [('hand', {'keyframes': [{'at': 0, 'x': .2}, {'at': 1}]}),
                             ('prop', {'attachments': [{'start_ms': 0, 'end_ms': 160,
                                'parent': 'hand', 'point': [0, 0]}]})]:
            with self.subTest(layer=layer):
                self.value = project(); self.value['shots'][1]['tracks'][layer] = track
                with self.assertRaisesRegex(ValueError, 'first pose differs'):
                    self.compile()

    def test_first_shot_must_start_from_stage_pose(self):
        self.value['shots'][0]['tracks']['hand']['keyframes'][0]['rotation'] = 30
        with self.assertRaisesRegex(ValueError, 'first pose differs'):
            self.compile()

    def test_explicit_detach_preserves_world_position_and_later_free_motion(self):
        self.value['shots'][1]['tracks']['prop'] = {'attachments': None,
            'keyframes': [{'at': 0}, {'at': 1, 'y': .75}]}
        report = self.compile()['report']
        released = report['timeline'][1]
        self.assertNotIn('attachment', released['start_state']['prop'])
        self.assertEqual(released['start_state']['prop']['x'], .75)
        self.assertEqual(released['start_state']['prop']['y'], .5)
        self.assertEqual(report['timeline'][2]['start_state']['prop']['y'], .75)
        self.assertNotIn('attachment', report['timeline'][2]['end_state']['prop'])

    def test_preserves_local_rotation_zoom_opacity_and_stroke_reveal(self):
        self.seed['layers'].append({'id': 'ink', 'type': 'stroke', 'size': [8, 8],
            'points': [[1, 1], [6, 6]], 'stroke': '#ffffff', 'stroke_width': 2,
            'keyframes': [{'at': 0, 'reveal': 0}, {'at': 1}]})
        self.value['shots'][0]['tracks']['ink'] = {'keyframes': [{'at': 0},
            {'at': 1, 'reveal': 1, 'rotation': 45, 'zoom': 2, 'opacity': .7}]}
        report = self.compile()['report']
        first = report['timeline'][0]['end_state']['ink']
        for row in report['timeline'][1:]:
            self.assertEqual(row['start_state']['ink'], first)
            self.assertEqual(row['end_state']['ink'], first)

    def test_uses_conceptual_endpoint_not_last_stored_drawing(self):
        self.value['shots'] = self.value['shots'][:1] + [{'id': '02-hold', 'action': 'Hold the result.', 'duration_ms': 80}]
        self.value['shots'][0]['tracks']['hand']['keyframes'] = [{'at': 0}, {'at': 1, 'x': .75}]
        compiled = self.compile()['compiled']
        ending = attachments.resolve(compiled[0], 160)['hand']['x']
        stored = attachments.resolve(compiled[0], 120)['hand']['x']
        beginning = attachments.resolve(compiled[1], 0)['hand']['x']
        self.assertEqual(ending, beginning)
        self.assertNotEqual(stored, beginning)
        review = sequence.render_join(compiled[0], compiled[1])
        self.assertTrue(review['endpoint_pixels_equal'])
        self.assertFalse(review['last_stored_pixels_equal'])

    def test_unknown_fields_layer_ids_and_track_payloads_fail(self):
        for key, bad in [('format', 'other'), ('schema_version', True), ('shots', []),
                         ('stage', '../outside.json'), ('stage', 'https://example.com/stage.json')]:
            self.value = project(); self.value[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.compile()
        for tracks in ({'missing': {}}, {'HAND': {}}, [], {'hand': {'fill': '#ffffff'}},
                       {'prop': {'attachments': {}}}, {'hand': {'keyframes': []}},
                       {'hand': {'keyframes': [None]}}):
            self.value = project(); self.value['shots'][0]['tracks'] = tracks
            with self.subTest(tracks=tracks), self.assertRaises(ValueError):
                self.compile()

    def test_ids_duration_and_aggregate_budgets(self):
        for sid in ('../escape', 'CON', 'aux', 'two words', '01-carry', True):
            self.value = project(); self.value['shots'][1]['id'] = sid
            with self.subTest(id=sid), self.assertRaises(ValueError):
                self.compile()
        for duration in (True, 41, -1, 30001, float('inf')):
            self.value = project(); self.value['shots'][0]['duration_ms'] = duration
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.compile()
        for name in ('MAX_DURATION_MS', 'MAX_FRAMES', 'MAX_PIXEL_FRAMES'):
            self.value = project()
            with patch.object(sequence, name, 1), self.assertRaisesRegex(ValueError, 'aggregate'):
                self.compile()

    def test_dynamic_partial_and_animated_stages_are_rejected(self):
        self.seed['layers'][0]['keyframes'][1]['x'] = .5
        with self.assertRaisesRegex(ValueError, 'static seed'):
            self.compile()
        self.seed = stage(); self.seed['layers'][0]['out_ms'] = 40
        self.seed['layers'][2]['attachments'][0]['parent'] = 'hook'
        with self.assertRaisesRegex(ValueError, 'active throughout'):
            self.compile()
        image = Image.new('RGB', (2, 2), 'red'); image.save(self.root / 'still.gif', duration=80)
        self.seed = stage(); self.seed['layers'].append({'id': 'moving', 'type': 'gif', 'source': 'still.gif', 'size': [2, 2]})
        with self.assertRaisesRegex(ValueError, 'animated GIF/sprite'):
            self.compile()

    def test_dry_run_does_not_write_call_network_or_start_encoder(self):
        with patch.object(socket, 'socket', side_effect=AssertionError), patch.object(layers, 'run_command', side_effect=AssertionError):
            report = sequence.build_sequence(self.path, self.root / 'plan', dry_run=True)
        self.assertEqual(report['status'], 'planned')
        self.assertFalse((self.root / 'plan').exists())
        self.assertFalse((self.root / 'plan.lock').exists())

    def test_cli_parser_routes_zero_call_sequence_commands(self):
        args = cli.build_parser().parse_args(['sequence', 'build', str(self.path), '--out', str(self.root / 'out'), '--dry-run'])
        self.assertEqual(args.func, sequence.run)
        self.assertTrue(args.dry_run)
        self.assertFalse(hasattr(args, 'max_api_calls'))

    def test_duplicate_json_fields_and_json_budgets(self):
        self.path.write_text('{"format":"x","format":"y"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            sequence.compile_sequence(self.path)
        self.save()
        with patch.object(sequence, 'MAX_PROJECT_BYTES', 10), self.assertRaisesRegex(ValueError, 'limit'):
            sequence.compile_sequence(self.path)

    def test_inventory_rejects_symlinks_and_encoded_output_budget(self):
        (self.root / 'large').write_bytes(b'12345')
        with patch.object(sequence, 'MAX_OUTPUT_BYTES', 1), self.assertRaisesRegex(ValueError, 'output budget'):
            sequence.file_inventory(self.root)
        try:
            (self.root / 'alias').symlink_to(self.path)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable')
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            sequence.file_inventory(self.root)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class SequenceIntegrationTests(SequenceFixture, unittest.TestCase):
    def test_real_build_relocation_and_all_frame_reopen(self):
        before = self.path.read_bytes(), self.stage.read_bytes()
        with patch.object(socket, 'socket', side_effect=AssertionError):
            result = sequence.build_sequence(self.path, self.root / 'output')
        self.assertEqual(result['frames_reopened_and_matched'], 10)
        self.assertEqual(result['duration_ms'], 400)
        moved = self.root / 'moved'; (self.root / 'output').rename(moved)
        self.assertEqual(sequence.verify_sequence(moved)['frames_reopened_and_matched'], 10)
        self.assertEqual(before, (self.path.read_bytes(), self.stage.read_bytes()))
        with self.assertRaises(ValueError):
            sequence.build_sequence(self.path, moved)

    def test_tampered_png_or_join_evidence_cannot_be_rehashed_into_a_pass(self):
        sequence.build_sequence(self.path, self.root / 'output')
        root = self.root / 'output'
        join = root / 'joins/01.png'
        Image.new('RGB', (96, 60), 'black').save(join)
        receipt = json.loads((root / 'sequence-receipt.json').read_text())
        receipt['files'] = sequence.file_inventory(root)
        sequence.dump(root / 'sequence-receipt.json', receipt)
        with self.assertRaisesRegex(ValueError, 'Join sheet differs'):
            sequence.verify_sequence(root)

    def test_missing_export_file_cannot_be_hidden_by_editing_inventory(self):
        sequence.build_sequence(self.path, self.root / 'output')
        root = self.root / 'output'
        (root / 'shots/01-carry/preview.gif').unlink()
        receipt = json.loads((root / 'sequence-receipt.json').read_text())
        receipt['files'] = sequence.file_inventory(root)
        sequence.dump(root / 'sequence-receipt.json', receipt)
        with self.assertRaisesRegex(ValueError, 'export hash'):
            sequence.verify_sequence(root)

    def test_rehashed_unrelated_film_source_cache_is_rejected(self):
        sequence.build_sequence(self.path, self.root / 'output')
        root = self.root / 'output'
        manifest_path = root / 'film/render-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        record = manifest['shots']['01-carry']
        cached = root / 'film' / record['output']
        Image.new('RGB', (32, 32), 'purple').save(cached, duration=160)
        record['sha256'] = layers.digest(cached.read_bytes())
        sequence.dump(manifest_path, manifest)
        receipt = json.loads((root / 'sequence-receipt.json').read_text())
        receipt['files'] = sequence.file_inventory(root)
        sequence.dump(root / 'sequence-receipt.json', receipt)
        with self.assertRaisesRegex(ValueError, 'source cache differs'):
            sequence.verify_sequence(root)

    def test_changed_input_during_render_does_not_publish_completed_output(self):
        original = layers.render_scene
        def changed(*args, **kwargs):
            report = original(*args, **kwargs)
            if not hasattr(changed, 'done'):
                changed.done = True
                self.value['title'] = 'Changed while rendering'; self.save()
            return report
        with patch.object(layers, 'render_scene', side_effect=changed), self.assertRaisesRegex(ValueError, 'inputs changed'):
            sequence.build_sequence(self.path, self.root / 'output')
        self.assertFalse((self.root / 'output').exists())
        self.assertFalse((self.root / 'output.lock').exists())

    def test_encoder_failure_keeps_existing_work_and_leaves_no_completed_bundle(self):
        marker = self.root / 'accepted'; marker.write_bytes(b'accepted')
        with patch.object(layers, 'render_scene', side_effect=RuntimeError('encoder failed')), self.assertRaises(RuntimeError):
            sequence.build_sequence(self.path, self.root / 'output')
        self.assertFalse((self.root / 'output').exists())
        self.assertEqual(marker.read_bytes(), b'accepted')
