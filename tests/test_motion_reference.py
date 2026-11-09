"""Verify the one archived Blender study without requiring or running Blender."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / 'docs/assets/motion-elements'


class MotionReferenceTests(unittest.TestCase):
    def test_original_gif_bytes_timing_and_distinct_frames(self):
        path = MEDIA / 'chrome.gif'
        expected = 'b8795d8927b1749ab0a779112dc445b74bcc1dbac69e3bd5035f799be17dcee3'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)
        receipt = json.loads((MEDIA / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['gif']['sha256'], expected)
        self.assertEqual(receipt['render']['renderer'], 'Blender EEVEE')
        self.assertEqual(receipt['api_calls'], 0)
        with Image.open(path) as im:
            self.assertEqual(im.size, (512, 512))
            self.assertEqual(im.n_frames, 80)
            self.assertEqual(im.info.get('loop'), 0)
            delays, drawings = [], set()
            for frame in ImageSequence.Iterator(im):
                delays.append(frame.info['duration'])
                drawings.add(hashlib.sha256(frame.convert('RGB').tobytes()).digest())
            self.assertEqual(delays, [40] * 80)
            self.assertEqual(sum(delays), 3200)
            self.assertEqual(len(drawings), 80)

    def test_original_mp4_bytes_and_technical_facts(self):
        path = MEDIA / 'chrome.mp4'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         '264b505b8a8879e4e3527bd9b9630a579ebadb2c0aeed46b3f4083e2636ca750')
        result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                                 '-show_format', '-of', 'json', str(path)],
                                check=True, capture_output=True, text=True, timeout=30)
        info = json.loads(result.stdout)
        self.assertEqual(len(info['streams']), 1)
        video = info['streams'][0]
        self.assertEqual(video['codec_name'], 'h264')
        self.assertEqual((video['width'], video['height']), (512, 512))
        self.assertEqual(video['avg_frame_rate'], '25/1')
        self.assertEqual(int(video['nb_read_frames']), 80)
        self.assertAlmostEqual(float(info['format']['duration']), 3.2, places=2)

    def test_archive_is_visible_and_separate_from_native_output(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        visible = re.sub(r'<details\b.*?</details>', '', readme, flags=re.S)
        section = visible.split('## Archived 3D study\n', 1)[1].split('\n## ', 1)[0]
        self.assertIn('docs/assets/motion-elements/chrome.gif', section)
        self.assertIn('Blender EEVEE', section)
        self.assertIn('not native API output', section)
        self.assertIn('One loop is complete', section)
        self.assertIn('(prefers-reduced-motion: reduce)', section)
        self.assertIn('docs/assets/motion-elements/poster.png', section)

    def test_existing_gif_recipe_plans_zero_calls(self):
        result = subprocess.run([sys.executable, '-m', 'gif_cinema', 'render',
                                 str(ROOT / 'tools/motion_elements/source-film.json'),
                                 '--dry-run', '--max-api-calls', '0'], cwd=ROOT,
                                check=True, capture_output=True, text=True, timeout=30)
        plan = json.loads(result.stdout)
        self.assertEqual(plan['minimum_new_api_calls'], 0)
        self.assertEqual(plan['max_api_calls_including_retries'], 0)
        self.assertEqual(plan['shots'][0]['action'], 'import')
        self.assertEqual(plan['shots'][0]['expected_duration_ms'], 3200)


if __name__ == '__main__':
    unittest.main()
