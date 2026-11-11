"""Local holds are intentional timing, never successful single-frame generation."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import cli, render


class TimedHoldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'hold.gif'
        Image.new('RGB', (16, 16), 'red').save(self.source, duration=160)

    def test_only_explicit_local_decode_accepts_one_timed_drawing(self):
        with self.assertRaisesRegex(ValueError, 'at least two'):
            cli.validate_gif(self.source)
        frames, delays, _ = cli.validate_gif(self.source, allow_still=True)
        self.assertEqual(len(frames), 1)
        self.assertEqual(delays, [160])
        for invalid in (1, None, 'yes'):
            with self.assertRaises(ValueError):
                cli.validate_gif(self.source, allow_still=invalid)

    def test_local_inspection_and_endpoints_do_not_label_hold_as_motion(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            cli.inspect(argparse.Namespace(gif=self.source, output=None))
        report = json.loads(output.getvalue())
        self.assertEqual(report['frames'], 1)
        self.assertEqual(report['duration_ms'], 160)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.endpoints(argparse.Namespace(gif=self.source, output=str(self.root / 'hold'), force=False))
        with Image.open(self.root / 'hold-first.png') as first, Image.open(self.root / 'hold-last.png') as last:
            self.assertEqual(first.tobytes(), last.tobytes())

    def test_hold_still_requires_valid_delay_and_decoding_budget(self):
        Image.new('RGB', (16, 16), 'red').save(self.source, duration=10)
        with self.assertRaisesRegex(ValueError, 'at least 20'):
            cli.validate_gif(self.source, allow_still=True)
        Image.new('RGB', (16, 16), 'red').save(self.source, duration=160)
        with patch.object(cli, 'MAX_GIF_FRAME_PIXELS', 1), self.assertRaises(ValueError):
            cli.validate_gif(self.source, allow_still=True)

    def test_generated_cache_cannot_adopt_a_static_response(self):
        raw = self.source.read_bytes()
        record = {'output': 'hold.gif', 'fingerprint': 'same', 'sha256': hashlib.sha256(raw).hexdigest()}
        with self.assertRaisesRegex(ValueError, 'at least two'):
            render.cached(self.root, record, {'id': 'one', 'prompt': 'move', 'fingerprint': 'same'})
        self.assertTrue(render.cached(self.root, record, {'id': 'one', 'source': 'hold.gif', 'fingerprint': 'same'}))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_real_source_hold_film_and_zero_call_resume_keep_exact_duration(self):
        script = {'schema_version': 1, 'title': 'Intentional result hold', 'ratio': '1:1',
            'width': 16, 'height': 16, 'fps': 25, 'style_bible': 'Local hold, no new drawings.',
            'shots': [{'id': 'hold', 'source': 'hold.gif', 'first_frame_target': 'red', 'last_frame_target': 'red', 'transition': 'cut'}]}
        path = self.root / 'film.json'; path.write_text(json.dumps(script), encoding='utf-8')
        args = cli.build_parser().parse_args(['render', str(path), '--execute', '--max-api-calls', '0', '--out', str(self.root / 'render')])
        with patch.object(cli, 'request_gif', side_effect=AssertionError), contextlib.redirect_stdout(io.StringIO()):
            first = render.run(args); second = render.run(args)
        self.assertEqual(first['api_calls'], 0)
        self.assertEqual(second['skipped'], 1)
        self.assertEqual(second['film_seconds'], .16)
        info = json.loads((self.root / 'render/film-inspect.json').read_text())
        self.assertEqual(int(info['nb_read_frames']), 4)
