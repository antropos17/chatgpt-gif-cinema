"""The public demo uses existing local footage and always keeps earlier output."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gif_cinema import cli, doctor, render
from tools import demo


class DemoLauncherTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def test_default_reserves_new_directories_without_touching_previous_files(self):
        with patch.object(demo, 'ROOT', self.root):
            first = demo.reserve_output(None); (first/'keep.txt').write_bytes(b'keep')
            second = demo.reserve_output(None)
            self.assertEqual(first, self.root/'output/demo')
            self.assertEqual(second, self.root/'output/demo-2')
            self.assertEqual((first/'keep.txt').read_bytes(), b'keep')
            (self.root/'output/demo-3').write_bytes(b'unrelated file')
            self.assertEqual(demo.reserve_output(None), self.root/'output/demo-4')
            self.assertEqual((self.root/'output/demo-3').read_bytes(), b'unrelated file')

    def test_explicit_existing_file_empty_directory_and_symlink_are_preserved(self):
        targets = [self.root/'file', self.root/'directory']
        targets[0].write_bytes(b'keep'); targets[1].mkdir()
        for path in targets:
            with self.assertRaisesRegex(demo.DemoError, 'already exists'): demo.reserve_output(path)
        self.assertEqual(targets[0].read_bytes(), b'keep'); self.assertEqual(list(targets[1].iterdir()), [])
        link = self.root/'link'
        try: link.symlink_to(self.root/'missing', target_is_directory=True)
        except (OSError, NotImplementedError): return
        with self.assertRaisesRegex(demo.DemoError, 'already exists'): demo.reserve_output(link)
        self.assertTrue(link.is_symlink())
        with self.assertRaisesRegex(demo.DemoError, 'symbolic'): demo.reserve_output(link/'child')

    def test_missing_ffprobe_fails_before_output_or_renderer(self):
        with patch.object(doctor, 'inspect_tool', side_effect=lambda n: {'available': n != 'ffprobe'}), \
             patch.object(render, 'run') as run, patch.object(demo, 'reserve_output') as reserve:
            with self.assertRaisesRegex(demo.DemoError, 'ffprobe.*PATH|ffprobe.*cannot run'): demo.run_demo(self.root/'out')
        run.assert_not_called(); reserve.assert_not_called()

    def test_missing_encoder_fails_before_output_or_renderer(self):
        with patch.object(doctor, 'inspect_tool', return_value={'available': True}), \
             patch.object(doctor, 'require_film_capabilities', side_effect=ValueError('libx264 is required')), \
             patch.object(render, 'run') as run, patch.object(demo, 'reserve_output') as reserve:
            with self.assertRaisesRegex(ValueError, 'libx264'): demo.run_demo(self.root/'out')
        run.assert_not_called(); reserve.assert_not_called()

    def test_python_and_pillow_versions_report_manual_setup(self):
        with patch.object(demo.sys, 'version_info', (3, 9)):
            with self.assertRaisesRegex(demo.DemoError, 'Python 3.10'): demo.prerequisites()
        import PIL
        with patch.object(PIL, '__version__', '10.0.0'):
            with self.assertRaisesRegex(demo.DemoError, 'pip install'): demo.prerequisites()

    def test_missing_pillow_is_actionable_without_installing(self):
        import builtins
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name == 'PIL': raise ImportError('missing fixture')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', missing):
            with self.assertRaisesRegex(demo.DemoError, 'Pillow is missing.*pip install'): demo.prerequisites()

    def test_generated_shot_is_rejected_before_creating_output_even_with_key(self):
        (self.root/'examples').mkdir()
        value = json.loads((demo.ROOT/'examples/film.json').read_text())
        value['shots'][0].pop('source'); value['shots'][0]['prompt'] = 'Never send this'
        (self.root/'examples/film.json').write_text(json.dumps(value))
        with patch.object(demo, 'ROOT', self.root), patch.object(demo, 'prerequisites', return_value=render), \
             patch.dict(os.environ, {'OPENAI_API_KEY': 'must-not-be-used'}), \
             patch.object(cli, 'request_gif', side_effect=AssertionError('No requests')) as request:
            with self.assertRaisesRegex(ValueError, 'existing source GIFs'): demo.run_demo(self.root/'out')
        request.assert_not_called(); self.assertFalse((self.root/'out').exists())

    def test_main_help_and_failure_do_not_open_browser_or_install(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
            demo.main(['--help'])
        self.assertEqual(result.exception.code, 0)
        with patch.object(demo, 'run_demo', side_effect=demo.DemoError('missing tool')), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(demo.main([]), 1)
        self.assertIn('missing tool', err.getvalue()); self.assertIn('doctor', err.getvalue())


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
class RealDemoTests(unittest.TestCase):
    def test_actual_export_repeat_and_changed_file_are_kept_without_api(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); original_reserve = demo.reserve_output
            def reserve(requested):
                if requested is not None: return original_reserve(requested)
                with patch.object(demo, 'ROOT', root): return original_reserve(None)
            def hashes(folder):
                return {str(p.relative_to(folder)): (render.digest(p.read_bytes()), p.stat().st_mtime_ns)
                        for p in folder.rglob('*') if p.is_file()}
            sources = [demo.ROOT/'examples/film.json', *sorted((demo.ROOT/'.agents/skills/gif-cinema/assets/example').glob('shot-*.gif'))]
            before = {str(p): p.read_bytes() for p in sources}
            with patch.object(demo, 'reserve_output', reserve), \
                 patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden')), \
                 patch('socket.create_connection', side_effect=AssertionError('Network forbidden')), \
                 patch.object(cli, 'request_gif', side_effect=AssertionError('No API calls')) as request, \
                 patch.dict(os.environ, {'OPENAI_API_KEY': 'must-not-be-used'}), contextlib.redirect_stdout(io.StringIO()) as console:
                first = demo.run_demo(); first_files = hashes(first.parent)
                second = demo.run_demo()
                self.assertNotEqual(first.parent, second.parent)
                self.assertEqual(hashes(first.parent), first_files)
                with self.assertRaisesRegex(demo.DemoError, 'already exists'): demo.run_demo(first.parent)
                self.assertEqual(hashes(first.parent), first_files)
                # An unrelated replacement is not repaired or overwritten on retry.
                first.write_bytes(b'user file'); changed = hashes(first.parent)
                with self.assertRaisesRegex(demo.DemoError, 'already exists'): demo.run_demo(first.parent)
                self.assertEqual(hashes(first.parent), changed)
            request.assert_not_called(); self.assertIn('192 frames', console.getvalue())
            self.assertEqual(before, {str(p): p.read_bytes() for p in sources})
            inspection = json.loads((second.parent/'film-inspect.json').read_text())
            self.assertEqual(int(inspection['nb_read_frames']), 192)
            self.assertAlmostEqual(float(inspection['duration']), 7.68, places=5)
            self.assertEqual((inspection['width'], inspection['height'], inspection['codec_name']), (512,512,'h264'))
            receipt = json.loads((second.parent/'receipt.json').read_text())
            self.assertEqual((receipt['api_calls'], receipt['generated'], receipt['imported']), (0,0,3))
