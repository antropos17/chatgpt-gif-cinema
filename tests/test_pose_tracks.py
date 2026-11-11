"""Authored pose selection uses actual drawings, a local clock and no interpolation."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import layer_gifs, layer_sprites, layers, pose_tracks


def fixture():
    return {'format': layers.FORMAT, 'schema_version': 1, 'width': 32, 'height': 32,
            'duration_ms': 240, 'fps': 50, 'loop': False, 'layers': [
                {'id': 'actor', 'type': 'sprites', 'source': 'atlas.png', 'size': [8, 8],
                 'in_ms': 40, 'sampling': 'pixel',
                 'frames': [{'rect': [i * 8, 0, 8, 8], 'duration_ms': 30} for i in range(3)],
                 'pose_keys': [{'at': 0, 'frame': 2}, {'at': .4, 'frame': 0},
                               {'at': .6, 'frame': 2}, {'at': 1, 'frame': 1}]}]}


class PoseTrackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.path = self.root / 'scene.json'
        atlas = Image.new('RGBA', (24, 8))
        self.colors = [(255, 0, 0, 64), (0, 255, 0, 128), (0, 0, 255, 255)]
        for i, color in enumerate(self.colors):
            atlas.paste(Image.new('RGBA', (8, 8), color), (i * 8, 0))
        atlas.save(self.root / 'atlas.png')
        for target in ('urllib.request.OpenerDirector.open', 'socket.create_connection'):
            guard = patch(target, side_effect=AssertionError('Network forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def prepare(self, value=None):
        self.path.write_bytes(layers.serialize_scene(value or fixture()))
        return layers.prepare_scene(self.path)

    def test_normalization_preserves_records_and_is_idempotent(self):
        value = fixture(); original = copy.deepcopy(value)
        scene = layers.normalize_scene(value)
        self.assertEqual(value, original)
        self.assertEqual(scene, layers.normalize_scene(scene))
        self.assertEqual(scene['layers'][0]['pose_keys'], original['layers'][0]['pose_keys'])
        self.assertEqual(scene['layers'][0]['playback'], 'once')

    def test_rejects_invalid_keys(self):
        valid = [{'at': 0, 'frame': 0}, {'at': 1, 'frame': 1}]
        bad = [None, {}, [], valid[:1], valid * 129,
               [{'at': 0}, valid[-1]], [{'at': 0, 'frame': 0, 'easing': 'linear'}, valid[-1]],
               [{'at': .1, 'frame': 0}, valid[-1]], [valid[0], {'at': .9, 'frame': 1}],
               [valid[0], {'at': .5, 'frame': 0}, {'at': .4, 'frame': 1}, valid[-1]],
               [valid[0], {'at': .4, 'frame': 0}, {'at': .4, 'frame': 1}, valid[-1]],
               [valid[0], {'at': .45, 'frame': 1}, valid[-1]],
               [valid[0], {'at': 1e-12, 'frame': 1}, valid[-1]]]
        for at in (True, False, '0', float('nan'), float('inf'), -1, 2):
            bad.append([{'at': at, 'frame': 0}, valid[-1]])
        for frame in (True, False, 1.0, -1, 3, '1', None, float('nan'), float('inf')):
            bad.append([{'at': 0, 'frame': frame}, valid[-1]])
        for keys in bad:
            value = fixture(); value['layers'][0]['pose_keys'] = keys
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                layers.normalize_scene(value)

    def test_grid_tolerance_and_25fps(self):
        keys = [{'at': 0, 'frame': 0}, {'at': 1 / 3, 'frame': 1}, {'at': 1, 'frame': 0}]
        self.assertEqual(pose_tracks.normalize(keys, 2, 120, 40), keys)
        layer = {'in_ms': 40, 'out_ms': 160, 'pose_keys': keys}
        self.assertEqual(pose_tracks.index_at(layer, 40), 1)
        value = fixture(); value['fps'] = 25
        layers.normalize_scene(value)
        value['layers'][0]['pose_keys'][1]['at'] = .5
        with self.assertRaisesRegex(ValueError, 'frame grid'):
            layers.normalize_scene(value)

    def test_maximum_key_count_and_roundoff_do_not_delay_event(self):
        keys = [{'at': i / 255, 'frame': i % 3} for i in range(256)]
        self.assertEqual(len(pose_tracks.normalize(keys, 3, 5100, 20)), 256)
        keys = [{'at': 0, 'frame': 0}, {'at': .4 + 1e-12, 'frame': 1},
                {'at': 1, 'frame': 2}]
        keys = pose_tracks.normalize(keys, 3, 200, 20)
        layer = {'in_ms': 40, 'out_ms': 240, 'pose_keys': keys}
        self.assertEqual(pose_tracks.index_at(layer, 79.999), 0)
        self.assertEqual(pose_tracks.index_at(layer, 80), 1)

    def test_repeated_keys_are_holds_not_claimed_transitions(self):
        value = fixture()
        for key in value['layers'][0]['pose_keys']:
            key['frame'] = 2
        report = layer_sprites.timing_report(layers.normalize_scene(value))['actor']
        self.assertEqual(report['transitions'], [])
        self.assertEqual(len(report['holds']), 1)
        self.assertEqual(report['holds'][0]['duration_ms'], 200)

    def test_only_sprite_layers_and_no_native_clock_controls(self):
        for changes in ({'playback': 'loop'}, {'source_range_ms': [0, 20]}, {'type': 'gif'}):
            value = fixture(); value['layers'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                layers.normalize_scene(value)
        for field, bad in [('duration_ms', 0), ('duration_ms', True), ('duration_ms', 25)]:
            value = fixture(); value['layers'][0]['frames'][0][field] = bad
            with self.assertRaises(ValueError):
                layers.normalize_scene(value)

    def test_stepped_local_clock_and_conceptual_endpoint(self):
        prepared = self.prepare()
        self.assertIsNone(layers.render_at(prepared, 39)[1]['actor'])
        for time, index in [(40, 2), (70, 2), (119.999, 2), (120, 0),
                            (159.999, 0), (160, 2), (239.999, 2), (240, 1)]:
            frame, states = layers.render_at(prepared, time)
            self.assertEqual(states['actor']['source_index'], index)
            self.assertEqual(frame.getpixel((15, 15)), self.colors[index])
            self.assertEqual({frame.getpixel((x, y)) for x in range(frame.width) for y in range(frame.height)}, {(0, 0, 0, 0), self.colors[index]})
        # A local endpoint is never exported or made visible after an early out.
        value = fixture(); value['duration_ms'] = 280
        value['layers'][0]['out_ms'] = 240
        prepared = self.prepare(value)
        self.assertIsNone(layers.render_at(prepared, 240)[1]['actor'])

    def test_source_delays_do_not_drive_pose_clock_and_legacy_report_is_unchanged(self):
        value = fixture(); prepared = self.prepare(value)
        hashes = [layers.render_at(prepared, t)[0].tobytes() for t in range(0, 241, 20)]
        value['layers'][0]['frames'][0]['duration_ms'] = 60000
        changed = self.prepare(value)
        self.assertEqual(hashes, [layers.render_at(changed, t)[0].tobytes() for t in range(0, 241, 20)])
        del value['layers'][0]['pose_keys']
        legacy = self.prepare(value); layer = legacy['scene']['layers'][0]
        info = layer_sprites.sequence(layer)
        expected = {'source_drawings': 3, 'source_duration_ms': 60060,
                    'source_delays_ms': [60000, 30, 30], 'playback': 'once', 'sampling': 'pixel',
                    **layer_gifs.selection_report(info, layer, 20),
                    'rectangles': [frame['rect'] for frame in layer['frames']]}
        self.assertEqual(layer_sprites.timing_report(legacy['scene'])['actor'], expected)
        self.assertEqual(layers.render_at(legacy, 120)[1]['actor']['source_index'], 0)

    def test_report_save_reopen_and_budgets(self):
        prepared = self.prepare()
        report = layers.render_scene(self.path, self.root / 'unused', dry_run=True)['sprite_timing']['actor']
        self.assertEqual(report['selection'], 'authored-poses')
        self.assertFalse(report['source_delays_used'])
        self.assertEqual(report['exported_source_indices'], [2] * 4 + [0] * 2 + [2] * 4)
        self.assertEqual([hold['duration_ms'] for hold in report['holds']], [80, 40, 80])
        self.assertEqual([event['time_ms'] for event in report['transitions']], [120, 160])
        self.assertEqual(report['conceptual_endpoint'], {'time_ms': 240, 'source_index': 1, 'exported': False})
        self.assertEqual(report['omitted_source_drawings'], [1])
        reopened = layers.prepare_scene(layers.save_bundle(prepared, self.root / 'saved'))
        for time in range(0, 241, 20):
            self.assertEqual(layers.render_at(prepared, time)[0].tobytes(), layers.render_at(reopened, time)[0].tobytes())
        with patch.object(layer_sprites, 'MAX_CROP_PIXEL_FRAMES', 1), self.assertRaisesRegex(ValueError, 'budget'):
            self.prepare()
        with patch.object(layer_gifs, 'MAX_CACHED_PIXELS', 1), self.assertRaisesRegex(ValueError, 'budget'):
            self.prepare()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_export_verifies_all_frames_without_appending_endpoint(self):
        from tools.verify_layered_scene import verify
        self.prepare(); out = self.root / 'render'
        receipt = layers.render_scene(self.path, out)
        self.assertEqual(receipt['frames'], 12)
        self.assertEqual(verify(out)['frames_reopened_and_matched'], 12)
        self.assertEqual(receipt['samples'][-1]['layers']['actor']['source_index'], 2)
        self.assertEqual(receipt['loop_review']['layer_endpoint_states']['actor']['source_index'], 1)
        self.assertEqual(receipt['status'], 'human-review-required')
        self.assertEqual(len(list((out / 'frames').glob('*.png'))), 12)


if __name__ == '__main__':
    unittest.main()
