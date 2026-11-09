"""Dry-run and execution must agree about reuse without sending requests."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from gif_cinema import cli, render


class GeneratePlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'shot.gif'
        network = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden'))
        network.start()
        self.addCleanup(network.stop)

    def fixture(self):
        data = io.BytesIO()
        Image.new('RGB', (16, 16), 'red').save(data, format='GIF', save_all=True,
            append_images=[Image.new('RGB', (16, 16), 'blue')], duration=200, loop=0)
        raw = data.getvalue()
        self.output.write_bytes(raw)
        self.output.with_suffix('.json').write_text(json.dumps({
            'parameters': cli.make_payload('wave'),
            'sha256': hashlib.sha256(raw).hexdigest(),
        }))

    def run_generate(self, *flags):
        args = cli.build_parser().parse_args(['generate', 'wave', '-o', str(self.output), *flags])
        with patch.dict('os.environ', {}, clear=True), patch('gif_cinema.cli.request_gif') as request, \
                contextlib.redirect_stdout(io.StringIO()):
            result = cli.generate(args)
        request.assert_not_called()
        return result

    def test_verified_resume_plans_zero_calls_and_executes_without_a_key(self):
        self.fixture()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        plan = self.run_generate('--resume', '--dry-run')
        self.assertEqual(plan['action'], 'reuse')
        self.assertEqual(plan['would_send_api_calls'], 0)
        self.assertEqual(plan['api_calls'], 0)
        self.assertIsNone(self.run_generate('--resume'))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_new_resume_and_force_plan_one_request_without_writes(self):
        for flags in ((), ('--resume',)):
            plan = self.run_generate(*flags, '--dry-run')
            self.assertEqual(plan['action'], 'generate')
            self.assertEqual(plan['would_send_api_calls'], 1)
            self.assertEqual(list(self.root.iterdir()), [])
        self.fixture()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertEqual(self.run_generate('--force', '--dry-run')['would_send_api_calls'], 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_existing_output_without_resume_is_rejected_during_planning(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.run_generate('--dry-run')

    def test_incomplete_or_changed_resume_is_rejected_during_planning(self):
        self.fixture()
        meta = self.output.with_suffix('.json')
        saved = json.loads(meta.read_text())
        saved['sha256'] = '0' * 64
        meta.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.run_generate('--resume', '--dry-run')
        meta.unlink()
        with self.assertRaisesRegex(ValueError, 'both required'):
            self.run_generate('--resume', '--dry-run')

    def test_dangling_output_is_rejected_before_any_request(self):
        try:
            self.output.symlink_to(self.root / 'missing')
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows symlink creation requires additional privileges')
            raise
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.run_generate('--dry-run')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.run_generate()
        self.assertTrue(self.output.is_symlink())

    def test_script_model_environment_and_explicit_override(self):
        script = self.root / 'film.json'
        data = {'schema_version': 1, 'title': 'Test', 'ratio': '1:1', 'style_bible': 'paper',
                'shots': [{'id': 'one', 'prompt': 'wave', 'first_frame_target': 'before',
                           'last_frame_target': 'after'}]}
        script.write_text(json.dumps(data))
        args = cli.build_parser().parse_args(['render', str(script), '--dry-run'])
        with patch.dict('os.environ', {'GIF_CINEMA_MODEL': 'gpt-image-2.6-sunburst'}, clear=True):
            self.assertEqual(render.load_script(script, args)['shots'][0]['payload']['model'],
                             'gpt-image-2.6-sunburst')
        with patch.dict('os.environ', {'GIF_CINEMA_MODEL': 'unsupported'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'GIF_CINEMA_MODEL'):
                render.load_script(script, args)
            data['shots'][0]['model'] = 'gpt-image-2.6-flare'
            script.write_text(json.dumps(data))
            self.assertEqual(render.load_script(script, args)['shots'][0]['payload']['model'],
                             'gpt-image-2.6-flare')
