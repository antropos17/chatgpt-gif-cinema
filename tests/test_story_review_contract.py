"""Delivered GIFs fit the actual full-frame review workflow; MP4 reads stay local."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / '.agents/skills/gif-cinema/scripts'


def module(name):
    spec = importlib.util.spec_from_file_location('contract_' + name, SCRIPTS / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


story = module('story_project')
chapters = module('story_chapters')
pages = module('story_pages')
review = module('review_gif')


class ReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_exporters_match_review_capacity(self):
        for exporter in (story, chapters, pages):
            self.assertEqual(exporter.MAX_REVIEW_BYTES, review.MAX_BYTES)
            self.assertEqual(exporter.MAX_REVIEW_FRAMES, review.MAX_FRAMES)
            self.assertEqual(exporter.MAX_REVIEW_PIXELS, review.MAX_PIXELS)

    def test_exact_frame_boundary_and_overflow(self):
        info = {'width': 64, 'height': 64, 'duration': '51.2'}
        self.assertEqual(story.gif_export_plan(info, 64, 10), (51.2, 64, 512))
        for duration in ('51.21', '60'):
            with self.subTest(duration=duration), self.assertRaisesRegex(ValueError, 'review budget'):
                story.gif_export_plan({**info, 'duration': duration}, 64, 10)

    def test_high_resolution_story_uses_review_pixel_budget(self):
        with self.assertRaisesRegex(ValueError, 'review budget'):
            story.gif_export_plan({'width': 512, 'height': 512, 'duration': '9.68'}, 640, 20)
        self.assertEqual(story.gif_export_plan({'width': 512, 'height': 512, 'duration': '9.68'}, 320, 20),
                         (9.68, 320, 194))

    def test_nonfinite_and_invalid_probe_fields_fail_before_encoding(self):
        for duration in ('nan', 'inf', '-inf', '0', '-1'):
            with self.subTest(duration=duration), self.assertRaisesRegex(ValueError, 'finite and positive'):
                story.gif_export_plan({'width': 64, 'height': 64, 'duration': duration}, 64, 10)
        for width, height in ((0, 64), (True, 64), (64, 0), (8192, 8192)):
            with self.subTest(size=(width, height)), self.assertRaises(ValueError):
                story.gif_export_plan({'width': width, 'height': height, 'duration': '1'}, 64, 10)

    def test_snapshot_is_bounded_and_byte_exact(self):
        source = self.root / 'source.mp4'
        raw = b'Binary control bytes\r\n\x1a\x00\xff'
        source.write_bytes(raw)
        target = self.root / 'copy.mp4'
        self.assertEqual(story.snapshot_movie(source, target), hashlib.sha256(raw).hexdigest())
        self.assertEqual(target.read_bytes(), raw)
        with patch.object(story, 'MAX_MOVIE_BYTES', len(raw) - 1), self.assertRaisesRegex(ValueError, '512 MiB'):
            story.snapshot_movie(source, self.root / 'too-large.mp4')
        self.assertFalse((self.root / 'too-large.mp4').exists())

    def test_all_descriptor_readers_request_binary_mode(self):
        source = self.root / 'source.mp4'
        source.write_bytes(b'\r\n\x1a\x00\xff')
        real_open = os.open
        # Observe a sentinel without passing an unknown flag to the POSIX kernel.
        sentinel = getattr(os, 'O_BINARY', 1 << 28)
        seen = []
        def tracked(path, flags, *args, **kwargs):
            seen.append(flags)
            return real_open(path, flags & ~sentinel if os.name != 'nt' else flags, *args, **kwargs)
        with patch.object(os, 'O_BINARY', sentinel, create=True), patch.object(os, 'open', side_effect=tracked):
            story.snapshot_movie(source, self.root / 'snapshot.mp4')
            self.assertEqual(chapters.read_bytes(source, 1024), source.read_bytes())
            self.assertEqual(pages.read_bytes(source, 1024), source.read_bytes())
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(flags & sentinel for flags in seen))

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO test')
    def test_fifo_rejected_without_probe_or_waiting_for_writer(self):
        source = self.root / 'pipe.mp4'
        os.mkfifo(source)
        with patch.object(story.cli, 'run_media') as run, self.assertRaisesRegex(ValueError, 'regular'):
            story.export_gif(source, self.root / 'no.gif')
        run.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'Windows symlink privilege varies')
    def test_dangling_output_symlink_is_not_followed(self):
        target = self.root / 'out.gif'
        target.symlink_to('unrelated.gif')
        with patch.object(story.cli, 'run_media') as run, self.assertRaisesRegex(ValueError, 'new .gif'):
            story.export_gif(self.root / 'missing.mp4', target)
        run.assert_not_called()
        self.assertTrue(target.is_symlink())
        self.assertFalse((self.root / 'unrelated.gif').exists())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_real_export_is_reviewable_and_uses_snapshot_with_local_demuxer(self):
        source = self.root / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                        'testsrc2=size=64x64:rate=10:duration=1', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', str(source)], check=True, capture_output=True, timeout=30)
        original = source.read_bytes()
        real_run = story.cli.run_media
        commands = []
        def run(command):
            commands.append(command)
            result = real_run(command)
            if command[0] == 'ffprobe':
                source.write_bytes(b'An external editor replaced the original after snapshot')
            return result
        out = self.root / 'film.gif'
        with patch.object(story.cli, 'run_media', side_effect=run):
            receipt = story.export_gif(source, out, width=64, fps=10)
        self.assertEqual(receipt['source_sha256'], hashlib.sha256(original).hexdigest())
        self.assertTrue(receipt['full_frame_review_compatible'])
        for command in commands:
            self.assertEqual(command[command.index('-protocol_whitelist') + 1], 'file')
            self.assertEqual(command[command.index('-f') + 1], 'mov')
            self.assertEqual(command[command.index('-enable_drefs') + 1], '0')
            self.assertNotEqual(command[command.index('-i') + 1], str(source))
        audit = review.extract(out, self.root / 'review')
        self.assertEqual(audit['media']['technical_status'], 'passed')
        self.assertEqual(audit['media']['duration_ms'], receipt['duration_ms'])
        self.assertEqual(json.loads((self.root / 'review/review.json').read_text())['user_acceptance'], 'pending')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_renamed_playlist_is_not_auto_detected_or_network_fetched(self):
        source = self.root / 'playlist.mp4'
        source.write_text('#EXTM3U\n#EXTINF:1,\nhttp://127.0.0.1:9/unreachable.ts\n')
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            story.export_gif(source, self.root / 'bad.gif', width=64)
        self.assertIn('-f', caught.exception.cmd)
        self.assertIn('mov', caught.exception.cmd)
        self.assertNotIn(b'Connection refused', caught.exception.stderr)
        self.assertFalse((self.root / 'bad.gif').exists())


if __name__ == '__main__':
    unittest.main()
