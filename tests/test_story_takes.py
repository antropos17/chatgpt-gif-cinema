"""Reviewed take selection and portable long-story handoff, with no API requests."""
import argparse
from contextlib import ExitStack
import copy
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


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


story = load_module('story_takes_helper', SKILL / 'scripts/story_project.py')
packaging = load_module('story_takes_package', ROOT / 'tools/package_skill.py')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StoryTakeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('gif_cinema.cli.urlopen', side_effect=AssertionError('No HTTP')))
        self.args = argparse.Namespace(width=None, height=None, fps=None)
        self.pending = json.loads((EXAMPLE / 'storyboard.pending.json').read_text())
        self.takes = json.loads((EXAMPLE / 'takes.example.json').read_text())
        for take in self.takes['takes']:
            take['source'] = str(EXAMPLE / take['source'])

    def write(self, filename, data):
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return path

    def compile(self, name='selected', pending=None, takes=None):
        return story.compile_story(self.write('story.json', pending or self.pending),
                                   self.root / name, takes_path=self.write('takes.json', takes or self.takes))

    def test_all_takes_make_a_source_only_film_and_retain_requests(self):
        before = {take['source']: digest(Path(take['source'])) for take in self.takes['takes']}
        result = self.compile()
        project = self.root / 'selected'
        self.assertEqual(result['selected_take_count'], 3)
        self.assertEqual(result['provider_calls'], 0)
        self.assertEqual(result['minimum_new_requests_for_missing_shots'], 0)
        self.assertEqual(result['planned_playback_ms'], 9680)
        self.assertEqual(result['visual_acceptance'], 'not-established')
        self.assertTrue(result['ready_to_assemble'])
        self.assertFalse((project / 'assembly-template.json').exists())
        actual = render.load_script(project / 'film.json', self.args)
        self.assertTrue(all('source_path' in shot for shot in actual['shots']))
        self.assertEqual(json.loads((project / 'storyboard.original.json').read_text()), self.pending)
        receipt = json.loads((project / 'take-selections.json').read_text())
        for take in receipt['takes']:
            self.assertEqual(take['sha256'], digest(project / take['source']))
            self.assertEqual(take['requested_duration_ms'], 2560)
            self.assertEqual(take['source_duration_ms'], 2560)
            request = render.load_script(project / take['generation_script'], self.args)
            self.assertIn('payload', request['shots'][0])
        self.assertEqual(before, {name: digest(Path(name)) for name in before})

    def test_partial_selection_leaves_missing_actions_explicit(self):
        partial = copy.deepcopy(self.takes)
        partial['takes'] = partial['takes'][:1]
        result = self.compile(takes=partial)
        self.assertFalse(result['ready_to_assemble'])
        self.assertEqual(result['minimum_new_requests_for_missing_shots'], 2)
        self.assertEqual(result['selected_take_count'], 1)
        self.assertEqual([shot['status'] for shot in result['timeline']],
                         ['visual-review-required', 'caller-review-recorded', 'not-generated', 'not-generated'])
        self.assertFalse((self.root / 'selected/film.json').exists())

    def test_partial_project_moves_and_continues_without_original_sources(self):
        reference = self.root / 'identity.png'
        Image.new('RGB', (24, 24), '#abcdef').save(reference)
        self.pending['shots'][2]['generate']['references'] = [str(reference)]
        partial = copy.deepcopy(self.takes)
        partial['takes'] = partial['takes'][:1]
        self.compile(takes=partial)
        relocated = self.root / 'elsewhere'
        shutil.move(self.root / 'selected', relocated)
        reference.unlink()
        self.pending = json.loads((relocated / 'storyboard.json').read_text())
        self.assertTrue(all('source' in shot for shot in self.pending['shots'][:2]))
        before = {path.relative_to(relocated): digest(path) for path in relocated.rglob('*') if path.is_file()}
        remaining = copy.deepcopy(self.takes)
        remaining['takes'] = remaining['takes'][1:]
        result = story.compile_story(relocated / 'storyboard.json', self.root / 'finished',
                                     takes_path=self.write('more/takes.json', remaining))
        self.assertTrue(result['ready_to_assemble'])
        self.assertEqual(result['selected_take_count'], 2)
        self.assertEqual(result['planned_playback_ms'], 9680)
        self.assertEqual(before, {p.relative_to(relocated): digest(p) for p in relocated.rglob('*') if p.is_file()})
        self.assertEqual(digest(relocated / 'media/00-title.gif'), digest(self.root / 'finished/media/00-title.gif'))
        self.assertEqual(digest(relocated / 'media/01-signal.gif'), digest(self.root / 'finished/media/01-signal.gif'))

    def test_portable_sources_are_hash_pinned_against_later_changes(self):
        self.compile()
        project = self.root / 'selected'
        portable = json.loads((project / 'storyboard.json').read_text())
        for shot in portable['shots']:
            self.assertEqual(shot['source_sha256'], digest(project / shot['source']))
        shutil.copyfile(EXAMPLE / 'shot-02.gif', project / 'media/01-signal.gif')
        with self.assertRaisesRegex(ValueError, 'source SHA-256 mismatch'):
            story.compile_story(project / 'storyboard.json', self.root / 'changed')
        self.assertFalse((self.root / 'changed').exists())

    def test_source_hash_cannot_be_attached_to_unrendered_shots(self):
        self.pending['shots'][1]['source_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'only valid for a source shot'):
            self.compile()
        self.assertFalse((self.root / 'selected').exists())

    def test_manifest_paths_are_relative_to_manifest_not_story_or_cwd(self):
        source = self.root / 'takes-area/take.gif'
        source.parent.mkdir()
        shutil.copyfile(EXAMPLE / 'shot-01.gif', source)
        self.takes['takes'] = [self.takes['takes'][0]]
        self.takes['takes'][0]['source'] = 'take.gif'
        result = story.compile_story(self.write('story-area/story.json', self.pending), self.root / 'project',
                                     takes_path=self.write('takes-area/takes.json', self.takes))
        self.assertEqual(result['selected_take_count'], 1)

    def test_actual_delays_replace_planned_duration_and_warn(self):
        source = self.root / 'short.gif'
        frames = [Image.new('RGB', (32, 32), color) for color in ('red', 'blue')]
        frames[0].save(source, save_all=True, append_images=frames[1:], duration=[70, 130], disposal=2)
        self.takes['takes'][0].update(source=str(source), sha256=digest(source))
        result = self.compile()
        selected = result['timeline'][1]
        self.assertEqual(selected['requested_duration_ms'], 2560)
        self.assertEqual(selected['source_duration_ms'], 200)
        self.assertEqual(selected['end_ms'] - selected['start_ms'], 200)
        self.assertEqual(selected['drawings'], 2)
        self.assertEqual(result['planned_playback_ms'], 7320)
        self.assertTrue(any('timeline uses actual timing' in text for text in result['warnings']))

    def test_repeated_selected_bytes_are_not_new_story_actions(self):
        self.takes['takes'][1].update(source=self.takes['takes'][0]['source'], sha256=self.takes['takes'][0]['sha256'])
        result = self.compile()
        self.assertTrue(any('repetition is not a new story action' in text for text in result['warnings']))

    def test_reject_unknown_duplicate_unreviewed_or_wrong_digest_selections(self):
        changes = [lambda d: d.update(schema_version=True),
                   lambda d: d.update(extra=True),
                   lambda d: d.update(takes=[]),
                   lambda d: d['takes'][0].update(shot_id='not-a-shot'),
                   lambda d: d['takes'][0].update(shot_id='01-SIGNAL'),
                   lambda d: d['takes'][0].update(shot_id='../escape'),
                   lambda d: d['takes'].append(dict(d['takes'][0])),
                   lambda d: d['takes'][0].update(review_notes='  '),
                   lambda d: d['takes'][0].update(sha256='not-a-digest'),
                   lambda d: d['takes'][0].update(sha256='0' * 64),
                   lambda d: d['takes'][0].update(extra=True)]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                data = copy.deepcopy(self.takes)
                change(data)
                with self.assertRaises(ValueError):
                    self.compile(name=f'bad-{index}', takes=data)
                self.assertFalse((self.root / f'bad-{index}').exists())
                self.assertFalse(list(self.root.glob('.story-stage-*')))

    def test_missing_or_invalid_selected_media_leaves_no_partial_output(self):
        for exists in (False, True):
            with self.subTest(exists=exists):
                source = self.root / 'invalid.gif'
                if exists:
                    source.write_bytes(b'GIF89a is not a valid animation')
                data = copy.deepcopy(self.takes)
                data['takes'][0].update(source=str(source), sha256=digest(source) if exists else '0' * 64)
                with self.assertRaises((ValueError, OSError)):
                    self.compile(name=f'invalid-{exists}', takes=data)
                self.assertFalse((self.root / f'invalid-{exists}').exists())

    def test_take_cannot_replace_existing_source_or_title(self):
        source_story = json.loads((EXAMPLE / 'storyboard.json').read_text())
        for shot_id in ('00-title', '01-signal'):
            with self.subTest(shot_id=shot_id):
                data = copy.deepcopy(self.takes)
                data['takes'] = [data['takes'][0]]
                data['takes'][0]['shot_id'] = shot_id
                with self.assertRaisesRegex(ValueError, 'existing sources and titles are preserved'):
                    self.compile(name=shot_id, pending=source_story, takes=data)
                self.assertFalse((self.root / shot_id).exists())

    def test_manifest_limit_and_media_budget(self):
        manifest = self.root / 'huge.json'
        manifest.write_bytes(b' ' * (story.MAX_INPUT + 1))
        with self.assertRaisesRegex(ValueError, '1 MiB'):
            story.load_takes(manifest)
        pending = copy.deepcopy(self.pending)
        pending['shots'] = pending['shots'][1:]
        with patch.object(story, 'MAX_PROJECT_BYTES', 1):
            with self.assertRaisesRegex(ValueError, '512 MiB'):
                self.compile(pending=pending)
        self.assertFalse((self.root / 'selected').exists())

    def test_selected_shots_still_validate_generation_contract(self):
        self.pending['shots'][1]['generate']['frames'] = 1000
        with self.assertRaises(ValueError):
            self.compile()
        self.assertFalse((self.root / 'selected').exists())

    def test_cli_from_extracted_package_supports_selection_and_portable_recompile(self):
        archive = self.root / 'skill.zip'
        packaging.package(archive)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(self.root / 'installed')
        installed = self.root / 'installed/gif-cinema'
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        env.pop('OPENAI_API_KEY', None)
        command = [os.sys.executable, str(installed / 'scripts/story_project.py'), 'compile',
                   str(installed / 'assets/example/storyboard.pending.json'), '--takes',
                   str(installed / 'assets/example/takes.example.json'), '--out', str(self.root / 'first')]
        done = subprocess.run(command, cwd=self.root, env=env, check=True, capture_output=True, text=True, timeout=60)
        self.assertEqual(json.loads(done.stdout)['selected_take_count'], 3)
        shutil.rmtree(installed)
        result = story.compile_story(self.root / 'first/storyboard.json', self.root / 'second')
        self.assertTrue(result['ready_to_assemble'])
        self.assertEqual(result['planned_playback_ms'], 9680)
        for source in (self.root / 'first/media').glob('*.gif'):
            self.assertEqual(digest(source), digest(self.root / 'second/media' / source.name))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_selected_takes_assemble_and_resume_with_zero_calls(self):
        self.compile()
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        env.pop('OPENAI_API_KEY', None)
        command = [os.sys.executable, '-m', 'gif_cinema', 'render', str(self.root / 'selected/film.json'),
                   '--execute', '--max-api-calls', '0', '--out', str(self.root / 'render')]
        for _ in range(2):
            result = subprocess.run(command, env=env, check=True, capture_output=True, text=True, timeout=90)
            self.assertIn('"api_calls": 0', result.stdout)
        result = story.export_gif(self.root / 'render/film.mp4', self.root / 'story.gif', width=160, fps=10)
        self.assertEqual(result['provider_calls'], 0)
        self.assertEqual(result['duration_ms'], 9700)
        self.assertEqual(result['loop'], None)


if __name__ == '__main__':
    unittest.main()
