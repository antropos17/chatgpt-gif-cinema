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


if __name__ == '__main__':
    unittest.main()
