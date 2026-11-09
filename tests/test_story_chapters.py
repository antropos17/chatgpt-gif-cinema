"""Shot-aligned chapter planning and real encoded export, with zero provider calls."""
from contextlib import ExitStack, redirect_stdout
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw
from gif_cinema import cli, render

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.agents/skills/gif-cinema'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


chapters = module('chapter_helper', SKILL / 'scripts/story_chapters.py')
packaging = module('chapter_package', ROOT / 'tools/package_skill.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')


class ChapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.movie = self.root / 'render'
        self.movie.mkdir()
        self.script = self.root / 'film.json'
        self.output = self.root / 'chapters'
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('gif_cinema.cli.urlopen', side_effect=AssertionError('No provider calls')))
        self.data = {'schema_version': 1, 'title': 'Distinct color actions', 'style_bible': 'Test fixtures only',
                     'ratio': '1:1', 'width': 64, 'height': 64, 'fps': 25, 'shots': []}
        self.records = {}
        self.colors = ['#ca3030', '#30ca30', '#3030ca']
        for index in range(3):
            self.add_shot(index, 280)
        (self.movie / 'film.mp4').write_bytes(b'Not a real MP4: planning fixture only')
        self.save()

    def add_shot(self, index, delay):
        sid = f'shot-{index:02}'
        path = self.movie / f'{sid}.gif'
        frames = [Image.new('RGB', (64, 64), self.colors[index % 3]) for _ in range(2)]
        ImageDraw.Draw(frames[1]).rectangle((4, 4, 12, 12), fill='white')
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=delay, optimize=False)
        self.data['shots'].append({'id': sid, 'source': str(path), 'first_frame_target': 'Start', 'last_frame_target': 'End'})
        self.records[sid] = {'status': 'verified-gif', 'output': path.name, 'sha256': sha(path),
                             'duration_ms': 2 * delay, 'frames': 2, 'frame_durations_ms': [delay, delay]}

    def save(self):
        write_json(self.script, self.data)
        self.manifest = {'schema_version': 1, 'script_sha256': sha(self.script), 'runs': [{'status': 'complete'}],
                         'shots': self.records, 'film': {'output': 'film.mp4', 'sha256': sha(self.movie / 'film.mp4'),
                         'probe': {'width': 64, 'height': 64, 'nb_read_frames': str(sum(round(r['duration_ms'] * 25 / 1000) for r in self.records.values())),
                                   'duration': str(sum(round(r['duration_ms'] * 25 / 1000) for r in self.records.values()) / 25)}}}
        write_json(self.movie / 'render-manifest.json', self.manifest)

    def plan(self, **kwargs):
        return chapters.plan_chapters(self.script, self.movie, width=64, **kwargs)

    def test_groups_whole_shots_with_no_gap_or_overlap(self):
        plan = self.plan(max_seconds=1)
        self.assertEqual([c['shot_ids'] for c in plan['chapters']], [['shot-00'], ['shot-01'], ['shot-02']])
        self.assertEqual([(c['start_frame'], c['end_frame']) for c in plan['chapters']], [(0, 14), (14, 28), (28, 42)])
        self.assertEqual([c['duration_ms'] for c in plan['chapters']], [600] * 3)
        self.assertEqual(plan['source_frames'], 42)
        self.assertEqual(plan['source_duration_ms'], 1680)
        self.assertEqual(self.plan(max_seconds=2)['chapters'][0]['shot_ids'], ['shot-00', 'shot-01', 'shot-02'])

    def test_pixel_budget_splits_even_when_requested_seconds_allow_more(self):
        with patch.object(cli, 'MAX_GIF_PIXEL_FRAMES', 64 * 64 * 11):
            plan = self.plan(max_seconds=15)
        self.assertEqual(len(plan['chapters']), 3)

    def test_single_shot_over_budget_rejected_not_cut(self):
        with patch.object(cli, 'MAX_GIF_FRAMES', 5):
            with self.assertRaisesRegex(ValueError, 'whole shot'):
                self.plan()
        self.assertFalse(self.output.exists())

    def test_dry_run_has_no_processes_or_files(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        with patch.object(cli, 'run_media', side_effect=AssertionError('No media process')):
            result = chapters.export_chapters(self.script, self.movie, self.output, width=64, dry_run=True)
        self.assertEqual(result['provider_calls'], 0)
        self.assertEqual(result['verification'], 'inputs-hashed; movie-decode-pending')
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))

    def test_changed_script_or_movie_rejected(self):
        self.script.write_text(self.script.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'Script does not match'):
            self.plan()
        self.save()
        (self.movie / 'film.mp4').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Movie hash'):
            self.plan()

    def test_changed_shot_hash_and_recorded_timing_rejected(self):
        (self.movie / 'shot-00.gif').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'shot hash'):
            self.plan()
        self.data['shots'], self.records = [], {}
        for index in range(3):
            self.add_shot(index, 280)
        self.save()
        self.manifest['shots']['shot-00']['duration_ms'] += 10
        write_json(self.movie / 'render-manifest.json', self.manifest)
        with self.assertRaisesRegex(ValueError, 'timing mismatch'):
            self.plan()

    def test_incomplete_and_missing_shots_rejected(self):
        self.manifest['runs'][-1]['status'] = 'incomplete'
        write_json(self.movie / 'render-manifest.json', self.manifest)
        with self.assertRaisesRegex(ValueError, 'must be complete'):
            self.plan()
        self.save()
        del self.manifest['shots']['shot-01']
        write_json(self.movie / 'render-manifest.json', self.manifest)
        with self.assertRaisesRegex(ValueError, 'missing verified'):
            self.plan()

    def test_escaping_manifest_paths_rejected(self):
        self.manifest['shots']['shot-00']['output'] = '../film.json'
        write_json(self.movie / 'render-manifest.json', self.manifest)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            self.plan()

    def test_duplicate_ids_and_transitions_rejected(self):
        self.data['shots'][1]['id'] = self.data['shots'][0]['id'].upper()
        self.save()
        with self.assertRaisesRegex(ValueError, 'unique safe'):
            self.plan()
        self.data['shots'][1]['id'] = 'shot-01'
        self.data['shots'][0]['transition'] = 'dissolve'
        self.save()
        with self.assertRaisesRegex(ValueError, 'hard cuts'):
            self.plan()

    def test_options_strictly_validated(self):
        for kwargs in ({'fps': True}, {'fps': 12}, {'max_seconds': 0}, {'max_seconds': 121}, {'repeat': 'yes'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.plan(**kwargs)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO not supported')
    def test_regular_file_checks_reject_fifo_without_blocking(self):
        fifo = self.root / 'pipe'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, 'regular local'):
            chapters.read_bytes(fifo, 1024)
        with self.assertRaisesRegex(ValueError, 'regular local'):
            chapters.movie_digest(fifo)

    def test_json_and_movie_size_limits(self):
        with patch.object(chapters, 'MAX_JSON_BYTES', 8):
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                self.plan()
        with patch.object(chapters, 'MAX_MOVIE_BYTES', 8):
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                self.plan()

    def test_existing_and_dangling_output_never_overwritten(self):
        self.output.mkdir()
        (self.output / 'accepted.txt').write_text('Keep')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            chapters.export_chapters(self.script, self.movie, self.output)
        self.assertEqual((self.output / 'accepted.txt').read_text(), 'Keep')
        if hasattr(os, 'symlink'):
            target = self.root / 'dangling'
            try:
                target.symlink_to(self.root / 'absent')
            except OSError as exc:
                # Windows needs admin rights or Developer Mode for symlinks.
                self.skipTest(f'symlinks unavailable: {exc}')
            with self.assertRaisesRegex(ValueError, 'new directory'):
                chapters.export_chapters(self.script, self.movie, target)
            self.assertTrue(target.is_symlink())

    def test_failed_encode_does_not_publish_partial_chapters(self):
        with patch.object(chapters, 'verify_movie'), patch.object(cli, 'run_media', side_effect=RuntimeError('Encoder fault')):
            with self.assertRaisesRegex(RuntimeError, 'Encoder fault'):
                chapters.export_chapters(self.script, self.movie, self.output, width=64)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.chapters-stage-*')))
        self.assertFalse(self.output.with_name(self.output.name + '.lock').exists())

    def test_movie_changed_between_plan_and_snapshot_rejected(self):
        original = chapters.movie_digest
        calls = 0

        def change(path, target=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                Path(path).write_bytes(b'replaced movie')
            return original(path, target)

        with patch.object(chapters, 'movie_digest', side_effect=change), patch.object(cli, 'run_media') as run:
            with self.assertRaisesRegex(ValueError, 'changed since planning'):
                chapters.export_chapters(self.script, self.movie, self.output, width=64)
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_package_includes_executable_chapter_helper(self):
        archive = self.root / 'skill.zip'
        packaging.package(archive)
        with zipfile.ZipFile(archive) as zipped:
            entry = 'gif-cinema/scripts/story_chapters.py'
            self.assertEqual(zipped.read(entry), (SKILL / 'scripts/story_chapters.py').read_bytes())
            compile(zipped.read(entry), entry, 'exec')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_real_chapters_preserve_boundary_colors_and_loop_modes(self):
        render_dir = self.root / 'real-render'
        args = argparse.Namespace(script=str(self.script), width=None, height=None, fps=None, out=str(render_dir),
                                  execute=True, max_api_calls=0, force=False, force_shot=[], retries=0, dry_run=False)
        with redirect_stdout(io.StringIO()):
            receipt = render.run(args)
        self.assertEqual(receipt['api_calls'], 0)
        before = {p.name: sha(p) for p in render_dir.iterdir() if p.is_file()}
        for repeat in (False, True):
            out = self.root / f'real-chapters-{repeat}'
            plan = chapters.export_chapters(self.script, render_dir, out, width=64, fps=10, max_seconds=1, repeat=repeat)
            self.assertEqual(len(plan['chapters']), 3)
            self.assertEqual(plan['source_frames'], 42)
            for index, chapter in enumerate(plan['chapters']):
                frames, delays, loop = cli.validate_gif(out / chapter['file'])
                self.assertEqual(sum(delays), 600)
                self.assertEqual(loop, 0 if repeat else None)
                self.assertEqual(chapter['gif_sha256'], sha(out / chapter['file']))
                for frame in (frames[0], frames[-1]):
                    color = frame.getpixel((32, 32))
                    self.assertGreater(color[index], 150)
                    self.assertLess(max(color[j] for j in range(3) if j != index), 100)
            self.assertFalse((out / 'source.mp4').exists())
            self.assertEqual(json.loads((out / 'chapters.json').read_text()), plan)
        self.assertEqual(before, {p.name: sha(p) for p in render_dir.iterdir() if p.is_file()})

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_real_render_overrides_use_effective_dimensions_and_fps(self):
        render_dir = self.root / 'overridden-render'
        args = argparse.Namespace(script=str(self.script), width=128, height=128, fps=20, out=str(render_dir),
                                  execute=True, max_api_calls=0, force=False, force_shot=[], retries=0, dry_run=False)
        with redirect_stdout(io.StringIO()):
            render.run(args)
        plan = chapters.export_chapters(self.script, render_dir, self.output, width=64, max_seconds=1)
        self.assertEqual((plan['source_width'], plan['source_height'], plan['source_fps']), (128, 128, 20))
        self.assertEqual(plan['source_frames'], 33)
        self.assertEqual([(c['start_frame'], c['end_frame']) for c in plan['chapters']], [(0, 11), (11, 22), (22, 33)])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_real_35_second_14_shot_film_exports_all_chapters(self):
        self.data['shots'], self.records = [], {}
        for index in range(14):
            self.add_shot(index, 1280)
        self.save()
        render_dir = self.root / 'long-render'
        args = argparse.Namespace(script=str(self.script), width=None, height=None, fps=None, out=str(render_dir),
                                  execute=True, max_api_calls=0, force=False, force_shot=[], retries=0, dry_run=False)
        with redirect_stdout(io.StringIO()):
            render.run(args)
        plan = chapters.export_chapters(self.script, render_dir, self.output, width=64)
        self.assertEqual(plan['source_duration_ms'], 35840)
        self.assertEqual(plan['source_frames'], 896)
        self.assertEqual([len(c['shot_ids']) for c in plan['chapters']], [5, 5, 4])
        self.assertEqual([c['duration_ms'] for c in plan['chapters']], [12800, 12800, 10300])
        self.assertEqual([sid for c in plan['chapters'] for sid in c['shot_ids']], [s['id'] for s in self.data['shots']])
        self.assertEqual(sum(c['duration_ms'] for c in plan['chapters']), 35900)
        # These are synthetic colored technical fixtures, not a generated cartoon.
        self.assertEqual(plan['provider_calls'], 0)


if __name__ == '__main__':
    unittest.main()
