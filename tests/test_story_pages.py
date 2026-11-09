"""Real story-page GIFs, source timing and portable offline projects."""
from contextlib import ExitStack
import argparse
import copy
import errno
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


pages = module('story_pages', SKILL / 'scripts/story_pages.py')
packaging = module('pages_package', ROOT / 'tools/package_skill.py')


class StoryPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('gif_cinema.cli.urlopen', side_effect=AssertionError('No provider calls')))
        self.source = self.root / 'source.gif'
        frames = []
        for x in (4, 20, 40):
            image = Image.new('RGB', (64, 48), 'white')
            ImageDraw.Draw(image).rectangle((x, 10, x + 8, 25), fill='red')
            frames.append(image)
        frames[0].save(self.source, save_all=True, append_images=frames[1:], duration=[40, 80, 120], loop=0, optimize=False)
        self.before = self.source.read_bytes()
        self.spec = {'schema_version': 1, 'title': 'A test story', 'layout': 'landscape',
                     'width': 640, 'height': 400,
                     'pages': [{'id': 'first', 'source': str(self.source), 'heading': 'A wave.', 'text': 'Hello from the Moon.'}]}
        self.input = self.root / 'story.json'
        self.out = self.root / 'project'
        self.save()

    def save(self):
        self.input.write_text(json.dumps(self.spec), encoding='utf-8')

    def export(self, **kwargs):
        self.save()
        return pages.export_pages(self.input, self.out, **kwargs)

    def test_real_gif_preserves_variable_delays_and_action(self):
        report = self.export()
        entry = report['pages'][0]
        frames, delays, loop = cli.validate_gif(self.out / entry['output'])
        self.assertEqual(delays, [40, 80, 120])
        self.assertEqual(loop, None)
        self.assertEqual(report['duration_ms'], 240)
        self.assertEqual(report['provider_calls'], 0)
        self.assertEqual(report['verification'], 'decoded-all-page-frames; visual-review-required')
        self.assertEqual(entry['source_loop'], 0)
        self.assertEqual({frame.size for frame in frames}, {(640, 400)})
        self.assertNotEqual(frames[0].tobytes(), frames[-1].tobytes())
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual((self.out / 'sources/first.gif').read_bytes(), self.before)
        film = render.load_script(self.out / 'film.json', argparse.Namespace(width=None, height=None, fps=None))
        self.assertEqual(len(film['shots']), 1)
        self.assertEqual(film['fps'], 50)

    def test_portrait_reflows_without_cropping(self):
        self.spec.update(layout='portrait', width=400, height=640)
        report = self.export()
        entry = report['pages'][0]
        x, y, right, bottom = entry['image_box']
        self.assertGreater(right - x, 300)
        self.assertLess(bottom, 400)
        frames, _, _ = cli.validate_gif(self.out / entry['output'])
        self.assertEqual(frames[0].size, (400, 640))
        self.assertNotEqual(frames[0].tobytes(), frames[-1].tobytes())

    def test_transparent_source_composited_on_explicit_matte(self):
        frames = []
        for x in (2, 26, 48):
            image = Image.new('RGBA', (64, 48), (0, 0, 0, 0))
            ImageDraw.Draw(image).rectangle((x, 12, x + 5, 30), fill='red')
            frames.append(image)
        frames[0].save(self.source, save_all=True, append_images=frames[1:], duration=[40, 80, 120], disposal=2)
        self.spec['image_background'] = '#00FF00'
        report = self.export()
        encoded, _, _ = cli.validate_gif(self.out / 'pages/first.gif')
        x, y, right, bottom = report['pages'][0]['image_box']
        for frame in encoded:
            self.assertEqual(frame.getpixel((x + 10, y + 10)), (0, 255, 0))

    def test_dry_run_writes_nothing_and_never_runs_media(self):
        before = sorted(p.name for p in self.root.iterdir())
        with patch.object(cli, 'run_media', side_effect=AssertionError('No processes')):
            result = self.export(dry_run=True)
        self.assertEqual(result['provider_calls'], 0)
        self.assertEqual(before, sorted(p.name for p in self.root.iterdir()))
        self.assertFalse(self.out.exists())

    def test_portable_reopen_after_original_disappears(self):
        first = self.export()
        self.source.unlink()
        second_out = self.root / 'reopened'
        second = pages.export_pages(self.out / 'storybook.json', second_out)
        self.assertEqual(first['pages'][0]['gif_sha256'], second['pages'][0]['gif_sha256'])
        self.assertEqual((self.out / 'pages/first.gif').read_bytes(), (second_out / 'pages/first.gif').read_bytes())

    def test_pinned_sources_and_fonts_reject_mutation(self):
        self.export()
        source = self.out / 'sources/first.gif'
        original = source.read_bytes()
        source.write_bytes(original + b'changed')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            pages.export_pages(self.out / 'storybook.json', self.root / 'bad-source')
        source.write_bytes(original)
        font = self.out / 'font.ttf'
        font.write_bytes(font.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            pages.export_pages(self.out / 'storybook.json', self.root / 'bad-font')

    def test_existing_and_dangling_output_not_overwritten(self):
        self.out.mkdir()
        (self.out / 'accepted').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            self.export()
        self.assertEqual((self.out / 'accepted').read_bytes(), b'keep')
        dangling = self.root / 'dangling'
        try:
            dangling.symlink_to(self.root / 'missing')
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314 or exc.errno in (errno.ENOSYS, errno.ENOTSUP):
                self.skipTest('Symlink creation is unavailable on this system')
            raise
        with self.assertRaisesRegex(ValueError, 'new directory'):
            pages.export_pages(self.input, dangling)
        self.assertTrue(dangling.is_symlink())

    def test_failed_encode_does_not_publish_or_leave_stage(self):
        with patch.object(Image.Image, 'save', side_effect=OSError('Encoder fault')):
            with self.assertRaisesRegex(OSError, 'Encoder fault'):
                self.export()
        self.assertFalse(self.out.exists())
        self.assertFalse(list(self.root.glob('.story-pages-*')))
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_strict_schema_and_geometry(self):
        initial = copy.deepcopy(self.spec)
        mutations = [lambda d: d.update(schema_version=True), lambda d: d.update(unknown=True),
                     lambda d: d.update(layout='square'), lambda d: d.update(width=True),
                     lambda d: d.update(width=2000), lambda d: d.update(width=641),
                     lambda d: d.update(width=640, height=640), lambda d: d.update(background='red'),
                     lambda d: d['pages'][0].update(id='../escape'),
                     lambda d: d['pages'][0].update(text='\x00'),
                     lambda d: d['pages'][0].update(heading=''),
                     lambda d: d['pages'][0].update(source='https://example.com/file.gif'),
                     lambda d: d['pages'].append(dict(d['pages'][0], id='FIRST'))]
        for mutate in mutations:
            self.spec = copy.deepcopy(initial)
            mutate(self.spec)
            with self.subTest(spec=self.spec), self.assertRaises(ValueError):
                self.export()
            self.assertFalse(self.out.exists())

    def test_lost_motion_fails_clearly_instead_of_publishing_a_still(self):
        # Explicit fault injection: simulate all drawing differences disappearing
        # during layout, a real risk for subtle motions under resampling.
        def static_compose(spec, raw, base, art):
            return [base.copy(), base.copy(), base.copy()]
        with patch.object(pages, 'compose', side_effect=static_compose):
            with self.assertRaisesRegex(ValueError, 'no visible animation'):
                self.export()
        self.assertFalse(self.out.exists())
        self.assertFalse(list(self.root.glob('.story-pages-*')))

    def test_long_text_rejected_instead_of_clipped(self):
        self.spec['pages'][0]['text'] = 'A very long passage. ' * 30
        with self.assertRaisesRegex(ValueError, 'does not fit'):
            self.export()
        self.assertFalse(self.out.exists())

    def test_long_words_wrap_and_newlines_remain(self):
        font = pages.ImageFont.truetype(str(pages.default_font_path()), 20)
        draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        lines = pages.wrap('abcdefghijklm\n\nHello', font, 70, draw)
        self.assertIn('', lines)
        self.assertEqual(''.join(lines), 'abcdefghijklmHello')
        self.assertTrue(all(draw.textbbox((0, 0), line, font=font)[2] <= 70 for line in lines))

    def test_installed_font_fallback_and_missing_font_message(self):
        installed = pages.ImageFont.truetype(str(pages.default_font_path()), 20)
        with patch.object(pages.ImageFont, 'truetype', side_effect=[OSError('unavailable'), installed]) as lookup:
            self.assertEqual(pages.default_font_path(), Path(os.fsdecode(installed.path)))
            self.assertEqual(lookup.call_count, 2)
        with patch.object(pages.ImageFont, 'truetype', side_effect=OSError('unavailable')):
            with self.assertRaisesRegex(ValueError, 'licensed local font'):
                pages.default_font_path()

    def test_explicit_font_does_not_depend_on_system_discovery(self):
        font = pages.default_font_path()
        with patch.object(pages, 'default_font_path', side_effect=AssertionError('Unexpected font discovery')):
            self.assertEqual(self.export(font_path=font)['provider_calls'], 0)

    def test_source_and_output_limits(self):
        for name, value, message in [('MAX_INPUT_BYTES', 10, 'combined'),
                                     ('MAX_PAGE_PIXELS', 10, 'pixel budget'),
                                     ('MAX_PROJECT_PIXELS', 10, 'pixel budget'),
                                     ('MAX_OUTPUT_BYTES', 10, 'output byte budget')]:
            with self.subTest(name=name), patch.object(pages, name, value), self.assertRaisesRegex(ValueError, message):
                self.export()
            self.assertFalse(self.out.exists())
            self.assertFalse(list(self.root.glob('.story-pages-*')))

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO unavailable')
    def test_fifo_rejected_without_waiting(self):
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, 'regular local'):
            pages.read_bytes(fifo, 100)

    def test_source_hash_checked(self):
        self.spec['pages'][0]['source_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.export()

    def test_example_and_skill_package_include_source_recipe(self):
        out = self.root / 'example'
        result = pages.export_pages(SKILL / 'assets/example/storybook.json', out)
        self.assertEqual(result['duration_ms'], 7680)
        self.assertEqual([p['source_frames'] for p in result['pages']], [16, 16, 16])
        self.assertEqual([p['encoded_frames'] for p in result['pages']], [16, 16, 16])
        archive = self.root / 'skill.zip'
        packaging.package(archive)
        with zipfile.ZipFile(archive) as package:
            for name in ('scripts/story_pages.py', 'assets/example/storybook.json', 'references/story-pages.md'):
                self.assertIn('gif-cinema/' + name, package.namelist())
