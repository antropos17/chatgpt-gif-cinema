"""Offline behavioral checks for the packaged story compiler and exporter."""
import argparse
from contextlib import ExitStack
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
import zipfile

from PIL import Image
from gif_cinema import cli, render

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.agents/skills/gif-cinema'
EXAMPLE = SKILL / 'assets/example'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


story = module('story_project', SKILL / 'scripts/story_project.py')
packaging = module('package_story_skill', ROOT / 'tools/package_skill.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StorySkillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # Helpers must never dispatch HTTP, even when an environment key exists.
        self.stack.enter_context(patch('gif_cinema.cli.urlopen', side_effect=AssertionError('Network prohibited')))
        self.args = argparse.Namespace(width=None, height=None, fps=None)

    def input(self, data):
        for shot in data['shots']:
            if 'source' in shot and not Path(shot['source']).is_absolute():
                shot['source'] = str(EXAMPLE / shot['source'])
        path = self.root / 'story.json'
        path.write_text(json.dumps(data))
        return path

    def data(self):
        return json.loads((EXAMPLE / 'storyboard.json').read_text())

    def test_existing_story_preserves_sources_and_actual_timing(self):
        before = [sha(EXAMPLE / f'shot-0{i}.gif') for i in range(1, 4)]
        out = self.root / 'project'
        report = story.compile_story(EXAMPLE / 'storyboard.json', out)
        self.assertTrue(report['ready_to_assemble'])
        self.assertEqual(report['provider_calls'], 0)
        self.assertEqual(report['planned_playback_ms'], 9680)
        self.assertEqual([t['drawings'] for t in report['timeline'][1:]], [16, 16, 16])
        self.assertEqual(before, [sha(out / 'media' / f'{sid}.gif') for sid in
                                  ('01-signal', '02-answer', '03-recognition')])
        self.assertEqual(before, [sha(EXAMPLE / f'shot-0{i}.gif') for i in range(1, 4)])
        validated = render.load_script(out / 'film.json', self.args)
        self.assertTrue(all('source_path' in shot for shot in validated['shots']))

    def test_title_moves_then_holds_without_reset(self):
        frames, delays = story.title_frames({'text': 'A STORY', 'duration_ms': 2000}, 256, 256)
        self.assertNotEqual(frames[0].tobytes(), frames[5].tobytes())
        self.assertEqual(frames[5].tobytes(), frames[-1].tobytes())
        self.assertEqual(sum(delays), 2000)

    def test_pillow_10_font_fallback_compiles_a_real_title(self):
        # Pillow 10.0's load_default() accepts no size keyword. Use the real
        # bitmap font where available, not a fake object that skips drawing.
        from PIL import ImageFont
        bitmap = (ImageFont.load_default_imagefont() if hasattr(ImageFont, 'load_default_imagefont')
                  else ImageFont.load_default())

        def legacy_default():
            return bitmap

        data = self.data()
        data['shots'] = [data['shots'][0]]
        data['shots'][0]['title'] = {'text': 'A STORY', 'subtitle': 'A small exchange', 'duration_ms': 1200}
        out = self.root / 'legacy-font'
        with patch.object(ImageFont, 'truetype', side_effect=OSError('No system font')), \
                patch.object(ImageFont, 'load_default', side_effect=legacy_default) as default:
            report = story.compile_story(self.input(data), out)
        self.assertEqual(report['planned_playback_ms'], 1200)
        self.assertTrue(any(call.kwargs.get('size') for call in default.call_args_list))
        self.assertTrue(any(not call.args and not call.kwargs for call in default.call_args_list))
        frames, delays, _ = cli.validate_gif(out / 'media/00-title.gif')
        self.assertEqual(sum(delays), 1200)
        self.assertNotEqual(frames[0].tobytes(), frames[-1].tobytes())

    def test_long_story_is_unrendered_and_actions_have_distinct_inputs(self):
        out = self.root / 'long'
        report = story.compile_story(EXAMPLE / 'long-story.plan.json', out)
        self.assertFalse(report['ready_to_assemble'])
        self.assertFalse((out / 'film.json').exists())
        self.assertTrue((out / 'assembly-template.json').exists())
        self.assertEqual(report['minimum_new_requests_for_missing_shots'], 14)
        self.assertEqual(report['planned_playback_ms'], 35840)
        self.assertEqual({s['status'] for s in report['timeline']}, {'not-generated'})
        prompts = []
        for filename in report['generation_scripts']:
            data = render.load_script(out / filename, self.args)
            self.assertEqual(len(data['shots']), 1)
            prompts.append(data['shots'][0]['payload']['prompt'])
        self.assertEqual(len(set(prompts)), 14)

    def test_existing_reference_is_copied_and_validated(self):
        ref = self.root / 'identity.png'
        Image.new('RGB', (32, 32), '#abcdef').save(ref)
        data = self.data()
        data['shots'] = [data['shots'][1]]
        del data['shots'][0]['source']
        data['shots'][0]['generate'] = {'frames': 4, 'duration_ms': 160, 'references': [str(ref)]}
        out = self.root / 'referenced'
        report = story.compile_story(self.input(data), out)
        generated = render.load_script(out / report['generation_scripts'][0], self.args)['shots'][0]
        self.assertEqual(generated['reference_inputs'][0]['sha256'], sha(ref))
        self.assertEqual(generated['expected_ms'], 640)

    def test_missing_reference_never_publishes_partial_project(self):
        data = self.data()
        data['shots'] = [data['shots'][1]]
        del data['shots'][0]['source']
        data['shots'][0]['generate'] = {'references': ['future-last.png']}
        out = self.root / 'bad'
        with self.assertRaises(FileNotFoundError):
            story.compile_story(self.input(data), out)
        self.assertFalse(out.exists())
        self.assertFalse(list(self.root.glob('.story-stage-*')))

    def test_duplicate_footage_is_reported_not_new_actions(self):
        data = self.data()
        data['shots'][2]['source'] = data['shots'][1]['source']
        report = story.compile_story(self.input(data), self.root / 'repeat')
        self.assertEqual(len(report['warnings']), 1)
        self.assertIn('repetition is not a new story action', report['warnings'][0])

    def test_invalid_story_rejected_before_output(self):
        mutations = [lambda d: d.update(schema_version=True),
                     lambda d: d.update(unrecognized='ignored?'),
                     lambda d: d.update(width=4096),
                     lambda d: d['shots'][1].update(id='../escape'),
                     lambda d: d['shots'][1].update(id=d['shots'][0]['id'].upper()),
                     lambda d: d['shots'][1].update(generate={}),
                     lambda d: d['shots'][0]['title'].update(duration_ms=2050),
                     lambda d: d['shots'][0]['title'].update(text='W' * 100)]
        for index, change in enumerate(mutations):
            with self.subTest(index=index):
                data = self.data()
                change(data)
                out = self.root / f'invalid-{index}'
                with self.assertRaises(ValueError):
                    story.compile_story(self.input(data), out)
                self.assertFalse(out.exists())

    def test_existing_project_is_not_modified(self):
        out = self.root / 'existing'
        out.mkdir()
        (out / 'accepted.txt').write_text('keep')
        with self.assertRaises(ValueError):
            story.compile_story(EXAMPLE / 'storyboard.json', out)
        self.assertEqual((out / 'accepted.txt').read_text(), 'keep')

    def test_title_resource_budget(self):
        with self.assertRaisesRegex(ValueError, 'drawing budget'):
            story.title_frames({'text': 'Story', 'duration_ms': 6000}, 1280, 1280)

    def test_storyboard_size_is_bounded(self):
        source = self.root / 'large.json'
        source.write_bytes(b' ' * (story.MAX_INPUT + 1))
        with self.assertRaisesRegex(ValueError, '1 MiB'):
            story.compile_story(source, self.root / 'large')

    def test_package_is_deterministic_and_self_contained(self):
        first, second = self.root / 'first.zip', self.root / 'second.zip'
        count = packaging.package(first)
        packaging.package(second)
        self.assertEqual(sha(first), sha(second))
        with zipfile.ZipFile(first) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(count, len(archive.namelist()))
            self.assertIn('gif-cinema/THIRD_PARTY_NOTICES.md', archive.namelist())
            self.assertTrue(all(n.startswith('gif-cinema/') and '..' not in n.split('/') for n in archive.namelist()))
            archive.extractall(self.root / 'unpacked')
        installed = self.root / 'unpacked/gif-cinema'
        report = story.compile_story(installed / 'assets/example/storyboard.json', self.root / 'extracted-project')
        self.assertEqual(report['planned_playback_ms'], 9680)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_real_assembly_resume_and_both_gif_loop_modes(self):
        out, movie = self.root / 'project', self.root / 'render'
        story.compile_story(EXAMPLE / 'storyboard.json', out)
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        env.pop('OPENAI_API_KEY', None)
        command = [os.sys.executable, '-m', 'gif_cinema', 'render', str(out / 'film.json'),
                   '--execute', '--max-api-calls', '0', '--out', str(movie)]
        for _ in range(2):
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True, timeout=90)
            self.assertIn('"api_calls": 0', result.stdout)
        digest = sha(movie / 'film.mp4')
        for repeat in (False, True):
            target = self.root / f'export-{repeat}.gif'
            report = story.export_gif(movie / 'film.mp4', target, width=160, fps=10, repeat=repeat)
            self.assertEqual(report['loop'], 0 if repeat else None)
            self.assertEqual(report['duration_ms'], 9700)
            self.assertEqual(report['frames'], 97)
            with self.assertRaises(ValueError):
                story.export_gif(movie / 'film.mp4', target)
        self.assertEqual(sha(movie / 'film.mp4'), digest)

    def test_gif_resource_budget_rejects_before_encoder(self):
        result = argparse.Namespace(stdout=json.dumps({'streams':[{'width':512,'height':512,'duration':'3600'}]}).encode())
        with patch.object(cli, 'run_media', return_value=result) as run:
            with self.assertRaisesRegex(ValueError, 'budget'):
                story.export_gif(self.root / 'long.mp4', self.root / 'large.gif')
            self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
