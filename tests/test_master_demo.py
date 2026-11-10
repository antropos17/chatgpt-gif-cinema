"""The comparison helper accepts current and older ffprobe frame-duration keys."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from gif_cinema import cli

spec = importlib.util.spec_from_file_location('master_timing_demo', Path(__file__).resolve().parents[1] / 'tools/demo_preserved_timing.py')
demo = importlib.util.module_from_spec(spec); spec.loader.exec_module(demo)


class MasterDemoTests(unittest.TestCase):
    def test_current_and_legacy_duration_keys(self):
        for key in ('duration_time', 'pkt_duration_time'):
            with self.subTest(key=key):
                probe = subprocess.CompletedProcess([], 0, stdout=json.dumps({'frames': [{'pts_time': '0.030000', key: '0.070000'}]}).encode())
                raw = subprocess.CompletedProcess([], 0, stdout=bytes([255, 0, 0]) * 48 * 48)
                with patch.object(cli, 'run_media', side_effect=[probe, raw]) as runner:
                    frames = demo.decoded(Path('fixture.mp4'))
                decode = runner.call_args_list[1].args[0]
                self.assertNotIn('-vsync', decode)
                self.assertEqual(decode[decode.index('-fps_mode') + 1], 'passthrough')
                self.assertEqual(frames, [{'start_ms': 30, 'duration_ms': 70, 'rgb': [255, 0, 0]}])

    def test_missing_duration_is_a_clear_error(self):
        probe = subprocess.CompletedProcess([], 0, stdout=b'{"frames":[{"pts_time":"0"}]}')
        raw = subprocess.CompletedProcess([], 0, stdout=bytes(48 * 48 * 3))
        with patch.object(cli, 'run_media', side_effect=[probe, raw]), self.assertRaisesRegex(ValueError, 'duration'):
            demo.decoded(Path('fixture.mp4'))
