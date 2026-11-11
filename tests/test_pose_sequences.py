"""Drawn atlas poses continue across actions without a native animation reset."""
import copy
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
from gif_cinema import layers, sequence


class PoseSequenceFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        atlas = Image.new('RGBA', (48, 16))
        draw = ImageDraw.Draw(atlas)
        for n, color in enumerate(('blue', 'orange', 'green')):
            draw.rectangle((n * 16 + 2, 2, n * 16 + 13, 13), fill=color)
        atlas.save(self.root / 'poses.png')
        self.seed = {'format': layers.FORMAT, 'schema_version': 1, 'width': 32,
            'height': 32, 'fps': 25, 'duration_ms': 80, 'loop': False, 'layers': [
                {'id': 'actor', 'type': 'sprites', 'source': 'poses.png', 'size': [16, 16],
                 'sampling': 'pixel', 'frames': [{'rect': [n * 16, 0, 16, 16], 'duration_ms': 40}
                                                  for n in range(3)],
                 'pose_keys': [{'at': 0, 'frame': 0}, {'at': 1, 'frame': 0}]},
                {'id': 'prop', 'type': 'ellipse', 'size': [2, 2], 'fill': '#ff0000',
                 'attachments': [{'start_ms': 0, 'end_ms': 80, 'parent': 'actor', 'point': [.5, .5]}]}]}
        self.project = {'format': sequence.FORMAT, 'schema_version': 1, 'title': 'Three drawn poses',
            'stage': 'stage.json', 'shots': [
                {'id': 'open', 'action': 'Open.', 'duration_ms': 160, 'tracks': {'actor': {
                    'pose_keys': [{'at': 0}, {'at': .5, 'frame': 1}, {'at': 1, 'frame': 1}]}}},
                {'id': 'carry', 'action': 'Carry the opened pose.', 'duration_ms': 160,
                 'tracks': {'actor': {'keyframes': [{'at': 0}, {'at': 1, 'x': .75}]}}},
                {'id': 'settle', 'action': 'Settle into another drawing.', 'duration_ms': 160,
                 'tracks': {'actor': {'pose_keys': [{'at': 0}, {'at': .5, 'frame': 2}, {'at': 1, 'frame': 2}]}}}]}
        self.path = self.root / 'sequence.json'
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.project), encoding='utf-8')
        (self.root / 'stage.json').write_text(json.dumps(self.seed), encoding='utf-8')

    def compile(self):
        self.save()
        return sequence.compile_sequence(self.path)


class PoseSequenceTests(PoseSequenceFixture, unittest.TestCase):
    def test_drawing_identity_and_holder_carry_without_repeating_keys(self):
        result = self.compile()
        expected = [[0, 0, 1, 1], [1, 1, 1, 1], [1, 1, 2, 2]]
        for prepared, indices in zip(result['compiled'], expected):
            self.assertEqual([layers.render_at(prepared, n * 40)[1]['actor']['source_index']
                              for n in range(4)], indices)
        rows = result['report']['timeline']
        self.assertEqual([r['start_state']['actor']['source_index'] for r in rows], [0, 1, 1])
        self.assertEqual([r['end_state']['actor']['source_index'] for r in rows], [1, 1, 2])
        for row in rows:
            self.assertEqual(row['end_state']['prop']['attachment']['parent'], 'actor')
            self.assertEqual(row['end_state']['prop']['x'], row['end_state']['actor']['x'])
        self.assertEqual(result['report']['visual_acceptance'], 'not-established')

    def test_identical_transforms_with_changed_drawings_have_different_pixels(self):
        prepared = self.compile()['compiled'][0]
        start, before = layers.render_at(prepared, 0)
        changed, after = layers.render_at(prepared, 80)
        self.assertNotEqual(start.tobytes(), changed.tobytes())
        for key in layers.DEFAULTS:
            self.assertEqual(before['actor'][key], after['actor'][key])

    def test_implicit_boundary_pose_reset_is_rejected(self):
        self.project['shots'][1]['tracks']['actor']['pose_keys'] = [
            {'at': 0, 'frame': 0}, {'at': 1, 'frame': 0}]
        with self.assertRaisesRegex(ValueError, 'source_index: first pose differs'):
            self.compile()

    def test_conceptual_endpoint_pose_is_carried_not_last_stored_pose(self):
        self.project['shots'][0]['tracks']['actor']['pose_keys'] = [{'at': 0}, {'at': 1, 'frame': 1}]
        result = self.compile()
        self.assertEqual(layers.render_at(result['compiled'][0], 120)[1]['actor']['source_index'], 0)
        self.assertEqual(result['report']['timeline'][1]['start_state']['actor']['source_index'], 1)
        join = sequence.render_join(*result['compiled'][:2])
        self.assertTrue(join['endpoint_pixels_equal'])
        self.assertFalse(join['last_stored_pixels_equal'])

    def test_nonzero_seed_pose_is_preserved_without_native_clock(self):
        for key in self.seed['layers'][0]['pose_keys']:
            key['frame'] = 2
        self.project['shots'] = [{'id': 'hold', 'action': 'Hold drawing two.', 'duration_ms': 400}]
        row = self.compile()['report']['timeline'][0]
        self.assertEqual(row['start_state']['actor']['source_index'], 2)
        self.assertEqual(row['end_state']['actor']['source_index'], 2)

    def test_dynamic_or_native_clock_seed_still_fails(self):
        self.seed['layers'][0]['pose_keys'][-1]['frame'] = 1
        with self.assertRaisesRegex(ValueError, 'static starting sprite pose'):
            self.compile()
        del self.seed['layers'][0]['pose_keys']
        with self.assertRaisesRegex(ValueError, 'clocks cannot implicitly reset'):
            self.compile()

    def test_bad_tracks_fail_without_writing_or_dispatch(self):
        original = copy.deepcopy(self.project)
        for keys in (None, [], [None], [{'at': 0}, {'at': 1}],
                     [{'at': 0}, {'at': .25, 'frame': 7}, {'at': 1, 'frame': 1}],
                     [{'at': 0}, {'at': .1, 'frame': 1}, {'at': 1, 'frame': 1}]):
            self.project = copy.deepcopy(original)
            self.project['shots'][0]['tracks']['actor']['pose_keys'] = keys
            self.save()
            with self.subTest(keys=keys), patch.object(socket, 'socket', side_effect=AssertionError):
                with self.assertRaises(ValueError):
                    sequence.build_sequence(self.path, self.root / 'output', dry_run=True)
                self.assertFalse((self.root / 'output').exists())
        self.project = copy.deepcopy(original)
        self.project['shots'][0]['tracks']['prop'] = {'pose_keys': [{'at': 0, 'frame': 0}, {'at': 1, 'frame': 0}]}
        with self.assertRaisesRegex(ValueError, 'Only sprite'):
            self.compile()

    def test_dry_run_preserves_original_source_bytes(self):
        self.save()
        paths = [self.path, self.root / 'stage.json', self.root / 'poses.png']
        before = [p.read_bytes() for p in paths]
        with patch.object(socket, 'socket', side_effect=AssertionError):
            plan = sequence.build_sequence(self.path, self.root / 'output', dry_run=True)
        self.assertEqual(plan['provider_calls'], 0)
        self.assertEqual(before, [p.read_bytes() for p in paths])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class PoseSequenceIntegrationTests(PoseSequenceFixture, unittest.TestCase):
    def test_portable_real_build_reopens_all_drawn_pose_frames(self):
        result = sequence.build_sequence(self.path, self.root / 'output')
        self.assertEqual(result['frames_reopened_and_matched'], 12)
        self.assertEqual(result['provider_calls'], 0)
        (self.root / 'output').rename(self.root / 'moved')
        self.assertEqual(sequence.verify_sequence(self.root / 'moved')['scene_count'], 3)
        recipe = json.loads((self.root / 'moved/shots/carry/editable/scene.json').read_text())
        actor = recipe['layers'][0]
        self.assertEqual([key['frame'] for key in actor['pose_keys']], [1, 1])
        self.assertTrue((self.root / 'moved/shots/carry/editable' / actor['source']).is_file())

    def test_rehashed_wrong_pose_pixels_do_not_verify(self):
        root = self.root / 'output'
        sequence.build_sequence(self.path, root)
        frame_path = root / 'shots/open/frames/0002.png'
        wrong, _ = layers.render_at(sequence.compile_sequence(root / 'sequence.json')['compiled'][0], 0)
        wrong.save(frame_path)
        receipt_path = root / 'sequence-receipt.json'
        receipt = json.loads(receipt_path.read_text())
        receipt['files'] = sequence.file_inventory(root)
        sequence.dump(receipt_path, receipt)
        child_path = root / 'shots/open/receipt.json'
        child = json.loads(child_path.read_text())
        child['outputs']['frames/0002.png'] = layers.digest(frame_path.read_bytes())
        sequence.dump(child_path, child)
        receipt['files'] = sequence.file_inventory(root)
        sequence.dump(receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, 'Saved scene PNG differs'):
            sequence.verify_sequence(root)

    def test_rehashed_fictional_pose_timing_report_is_rejected(self):
        root = self.root / 'output'
        sequence.build_sequence(self.path, root)
        child_path = root / 'shots/open/receipt.json'
        child = json.loads(child_path.read_text())
        child['sprite_timing']['actor']['source_delays_used'] = True
        sequence.dump(child_path, child)
        receipt_path = root / 'sequence-receipt.json'
        receipt = json.loads(receipt_path.read_text())
        receipt['files'] = sequence.file_inventory(root)
        sequence.dump(receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, 'sprite timing differs'):
            sequence.verify_sequence(root)
