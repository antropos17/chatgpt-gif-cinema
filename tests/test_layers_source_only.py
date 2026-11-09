"""The experimental layer package needs no unpublished finishing or demo assets."""
import contextlib
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from gif_cinema import layers, motion


class SourceOnlyLayerTests(unittest.TestCase):
    def test_uses_published_bounded_media_runner(self):
        self.assertIs(layers.run_command, motion.run_command)
        command = ['ffmpeg', '-version']
        commands = []
        result = subprocess.CompletedProcess(command, 0, stdout=b'fixture')
        with patch('gif_cinema.cli.run_media', return_value=result) as run:
            self.assertEqual(layers.run_command(command, commands), b'fixture')
        run.assert_called_once_with(command)
        self.assertEqual(commands, [command])

    def test_shared_runner_timeout_has_clean_cli_error(self):
        error = io.StringIO()
        with patch.object(layers, 'render_scene', side_effect=RuntimeError('ffmpeg timed out')), \
                contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as caught:
            layers.main(['render', 'scene.json', '--out', 'unused'])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn('failed or timed out', error.getvalue())
        self.assertNotIn('Traceback', error.getvalue())

    def test_included_json_example_is_asset_free_and_independently_animated(self):
        path = Path(__file__).resolve().parents[1] / 'examples' / 'layered-shapes.json'
        original = path.read_bytes()
        prepared = layers.prepare_scene(path)
        self.assertEqual(prepared['assets'], {})
        self.assertEqual(len(prepared['scene']['layers']), 4)
        first, opening = layers.render_at(prepared, 0)
        middle, moving = layers.render_at(prepared, 500)
        self.assertEqual(opening['background'], moving['background'])
        self.assertNotEqual(opening['dot'], moving['dot'])
        self.assertNotEqual(opening['label'], moving['label'])
        self.assertNotEqual(first.tobytes(), middle.tobytes())
        self.assertEqual(path.read_bytes(), original)

    def test_example_card_rotation_stops_smoothly_at_turn_and_loop(self):
        path = Path(__file__).resolve().parents[1] / 'examples' / 'layered-shapes.json'
        scene = layers.load_scene(path)
        card = next(row for row in scene['layers'] if row['id'] == 'card')
        duration = scene['duration_ms'] / 1000

        def angle(seconds):
            return layers.layer_transform(scene, card, seconds * 1000)['rotation']

        turn, epsilon = duration / 2, duration * 1e-4
        velocities = {
            'before turn': (angle(turn) - angle(turn - epsilon)) / epsilon,
            'after turn': (angle(turn + epsilon) - angle(turn)) / epsilon,
            'before seam': (angle(duration) - angle(duration - epsilon)) / epsilon,
            'after seam': (angle(epsilon) - angle(0)) / epsilon,
        }
        self.assertEqual(angle(0), angle(duration))
        self.assertNotEqual(angle(0), angle(turn))
        for label, velocity in velocities.items():
            with self.subTest(boundary=label):
                # Quintic easing tends to zero angular speed on both sides.
                # A missing outgoing easing yields 12 degrees/second here.
                self.assertLess(abs(velocity), 1e-3)

    def test_example_card_rendered_motion_is_symmetric_at_turn_and_loop(self):
        path = Path(__file__).resolve().parents[1] / 'examples' / 'layered-shapes.json'
        prepared = layers.prepare_scene(path)
        duration = prepared['scene']['duration_ms']
        first, _ = layers.render_at(prepared, 0, only_layer='card')
        middle, _ = layers.render_at(prepared, duration / 2, only_layer='card')
        self.assertNotEqual(first.tobytes(), middle.tobytes())
        # Check actual rasterized positions around the seam and direction change,
        # not just keyframe names or the conceptual closing position.
        for progress in (0, .04, .46, .48):
            with self.subTest(progress=progress):
                left, _ = layers.render_at(prepared, duration * progress, only_layer='card')
                right, _ = layers.render_at(prepared, duration * (1 - progress), only_layer='card')
                self.assertEqual(layers.digest(left.tobytes()), layers.digest(right.tobytes()))


if __name__ == '__main__':
    unittest.main()
