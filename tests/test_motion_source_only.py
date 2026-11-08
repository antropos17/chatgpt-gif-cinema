"""Motion integrates with the published backend without preview-only resources."""
import contextlib
import io
import subprocess
import unittest
from unittest.mock import patch

from gif_cinema import cli, motion
import test_media_safety


class SourceOnlyMotionTests(unittest.TestCase):
    def test_motion_parser_does_not_expose_unpublished_commands(self):
        parser = cli.build_parser()
        args = parser.parse_args(['motion', 'poster.png', '--preset', 'push-in', '--out', 'candidate', '--dry-run'])
        self.assertIs(args.func, motion.run)
        self.assertTrue(args.dry_run)
        for command in ('demo', 'edit', 'finish', 'doctor'):
            with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args([command])

    def test_media_commands_use_the_shared_bounded_runner(self):
        commands = []
        command = ['ffmpeg', '-version']
        response = subprocess.CompletedProcess(command, 0, stdout=b'fixture')
        with patch('gif_cinema.cli.run_media', return_value=response) as run:
            self.assertEqual(motion.run_command(command, commands), b'fixture')
        run.assert_called_once_with(command)
        self.assertEqual(commands, [command])

    def test_shared_timeout_is_not_downgraded_to_success(self):
        with patch('gif_cinema.cli.run_media', side_effect=RuntimeError('ffmpeg timed out')):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                motion.run_command(['ffmpeg', '-version'], [])

    def test_all_known_extension_bypasses_still_fail_before_motion_decode(self):
        fixture = test_media_safety.GIFBudgetTests()
        fixture.setUp()
        extensions = (b'!\x01\0', b'!\xf9\0', b'!\xff\0', b'!\x02\0',
                      b'!\xff\x0bNETSCAPE2.0\0')
        for extension in extensions:
            raw = fixture.hidden_descriptor(extension)
            with self.subTest(extension=extension), patch('PIL.Image.open') as decoder:
                with self.assertRaisesRegex(ValueError, 'extension'):
                    motion.decode_source(raw, 200)
                decoder.assert_not_called()


if __name__ == '__main__':
    unittest.main()
