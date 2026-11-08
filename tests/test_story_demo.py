"""Focused tests for the optional fixed story demo, not the core render API."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock
import hashlib
import json
import shutil
import tempfile

spec = importlib.util.spec_from_file_location('story_demo', Path(__file__).resolve().parents[1] / 'tools/build_story_demo.py')
story = importlib.util.module_from_spec(spec)
spec.loader.exec_module(story)


class StoryDemoTests(unittest.TestCase):
    def test_native_indices_play_once_and_keep_every_drawing(self):
        delays = [160] * 16
        indices = [story.source_index(delays, time) for time in range(0, 3760, 40)]
        self.assertEqual(indices, sorted(indices))
        self.assertEqual(set(indices), set(range(16)))
        self.assertEqual(indices.count(0), 14)  # native 160ms + 400ms establish
        self.assertEqual(indices.count(15), 24)  # native 160ms + 800ms result
        for index in range(1, 15):
            self.assertEqual(indices.count(index), 4)

    def test_duration_separates_native_action_and_presentation(self):
        samples, pages = story.timeline([([None] * 16, [160] * 16, 'GIF')] * 3)
        self.assertEqual(len(samples), 306)
        self.assertEqual(len(samples) / story.FPS, 12.24)
        self.assertEqual(sum(page['action_ms'] for page in pages), 7680)
        self.assertEqual(len([s for s in samples if s['kind'] == 'transition']), 24)
        self.assertEqual([p['start_ms'] for p in pages], [0, 4240, 8480])
        self.assertEqual(pages[-1]['end_ms'], 12240)

    def test_transitions_freeze_original_endpoints(self):
        samples, _ = story.timeline([([None] * 16, [160] * 16, 'GIF')] * 3)
        transition = [sample for sample in samples if sample['kind'] == 'transition']
        self.assertTrue(all(t['from_source_index'] == 15 and t['to_source_index'] == 0 for t in transition))
        self.assertTrue(all(0 < t['progress'] < 1 for t in transition))

    def test_existing_output_refused_before_decode(self):
        with self.assertRaisesRegex(ValueError, 'new directory'):
            story.build(Path(__file__).parent)

    def test_incoming_typography_does_not_flash_after_transition(self):
        from PIL import Image
        source = Image.new("RGBA", (512,512), "black")
        incoming = story.render_page(1, source, 0, 0, True)
        first_page_frame = story.render_page(1, source, 0, 0)
        self.assertEqual(incoming.tobytes(), first_page_frame.tobytes())

    def test_old_pillow_reports_requirement_before_output(self):
        story.load_font.cache_clear()
        with mock.patch.object(story.ImageFont, 'load_default', side_effect=TypeError('no size argument')):
            with self.assertRaisesRegex(ValueError, 'Pillow >= 10.1'):
                story.load_font(12)
        story.load_font.cache_clear()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'real FFmpeg/ffprobe required')
    def test_real_export_is_offline_and_sources_stay_unchanged(self):
        output = story.ROOT / 'output'
        output.mkdir(exist_ok=True)
        sources = story.ROOT / '.agents/skills/gif-cinema/assets/example'
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources.glob('*.gif')}
        with tempfile.TemporaryDirectory(prefix='story-test-', dir=output) as directory:
            destination = Path(directory) / 'render'
            with mock.patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
                result = story.build(destination)
            receipt = json.loads((destination / 'receipt.json').read_text())
            self.assertEqual(result['frames'], 306)
            self.assertEqual(receipt['native_source_drawings'], 48)
            self.assertEqual(receipt['native_action_seconds'], 7.68)
            self.assertEqual(receipt['new_provider_calls'], 0)
            self.assertEqual(receipt['repeat_count_per_shot'], 1)
            self.assertFalse(receipt['subject_interpolation'])
            self.assertEqual(receipt['font'], 'Pillow scalable default (no added font assets)')
            self.assertEqual(receipt['pillow_version'], story.PIL.__version__)
            for name, expected in receipt['outputs'].items():
                self.assertEqual(hashlib.sha256((destination / name).read_bytes()).hexdigest(), expected)
            self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources.glob('*.gif')})

    def test_easing_endpoints(self):
        self.assertEqual(story.smooth(-1), 0)
        self.assertEqual(story.smooth(2), 1)
        self.assertEqual(story.smooth(.5), .5)

if __name__ == '__main__':
    unittest.main()
