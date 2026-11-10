"""Offline collection build, actual-GIF previews, strict paths and ZIP readback."""
import copy
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw, ImageFont

from gif_cinema import cli, factory, layers

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DOM(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='factory test ')
        self.addCleanup(self.temp.cleanup)
        # macOS /var is a symlink; use the physical temporary path.
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'sources'
        self.source.mkdir()
        self.manifest = self.source / 'factory.json'
        self.out = self.root / 'collection'
        self.data = {'format': factory.FORMAT, 'schema_version': 1, 'title': 'A local collection', 'items': []}
        for i, color in enumerate(('#d5a374', '#b4b9d4')):
            self.add_gif(f'entry-{i}', color, loop=0 if i == 0 else None)
        self.save()
        self.network = patch('gif_cinema.cli.urlopen', side_effect=AssertionError('No provider calls'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def add_gif(self, sid, color, loop=None):
        frames = [Image.new('RGBA', (48, 32), (0, 0, 0, 0)) for _ in range(3)]
        for i, frame in enumerate(frames):
            ImageDraw.Draw(frame).rectangle((4 + i * 7, 8, 17 + i * 7, 23), fill=color)
        path = self.source / (sid + '.gif')
        options = {} if loop is None else {'loop': loop}
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=[80, 120, 240], disposal=2, optimize=False, **options)
        self.data['items'].append({'id': sid, 'title': sid.title(), 'group': 'Motion', 'caption': 'Existing drawings',
                                   'gif': path.name, 'sha256': sha(path)})
        return path

    def save(self):
        self.manifest.write_bytes(factory.json_bytes(self.data))

    def build(self, **kwargs):
        self.save()
        return factory.build_factory(self.manifest, self.out, **kwargs)

    def catalog(self):
        return json.loads((self.out / 'catalog.json').read_text(encoding='utf-8'))

    def test_repository_manifest_sources_remain_hash_pinned(self):
        with patch('subprocess.run', side_effect=AssertionError('Planning starts no processes')):
            plan = factory.plan_factory(ROOT / 'factory.example.json')
        self.assertEqual(plan['status'], 'planned')
        self.assertEqual([item['kind'] for item in plan['entries']], ['gif', 'scene'])
        self.assertEqual(plan['provider_calls'], 0)

    def test_build_copies_exact_gifs_and_verifies_complete_archive(self):
        before = {p.name: sha(p) for p in self.source.iterdir()}
        result = self.build()
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['provider_calls'], 0)
        self.assertEqual(result['visual_review'], 'pending')
        catalog = self.catalog()
        for item in catalog['items']:
            self.assertEqual(sha(self.out / item['gif']), sha(self.source / (item['id'] + '.gif')))
            self.assertEqual(item['gif_info']['delays_ms'], [80, 120, 240])
            self.assertEqual(item['gif_info']['duration_ms'], 440)
            self.assertEqual(item['preview_frames'], [0, 1, 2, 2, 2])
        self.assertEqual([i['gif_info']['loop'] for i in catalog['items']], [0, None])
        self.assertEqual(result, factory.verify_factory(self.out))
        with zipfile.ZipFile(self.out / 'collection.zip') as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(len(z.namelist()), 8)
            z.extractall(self.root / 'extracted')
        for name in [*catalog['files'], 'catalog.json']:
            self.assertEqual((self.root / 'extracted/collection' / name).read_bytes(), (self.out / name).read_bytes())
        self.assertEqual(before, {p.name: sha(p) for p in self.source.iterdir()})

    def test_posters_are_exact_decoded_rgba_including_transparency(self):
        self.build()
        for item in self.catalog()['items']:
            with Image.open(self.out / item['gif']) as gif:
                gif.seek(item['preview_frames'][2])
                expected = gif.convert('RGBA')
            with Image.open(self.out / item['poster']) as poster:
                self.assertEqual(poster.convert('RGBA').tobytes(), expected.tobytes())
                self.assertEqual(poster.getpixel((0, 0))[3], 0)

    def test_dry_run_writes_nothing_and_uses_no_media_process(self):
        before = sorted(self.root.rglob('*'))
        with patch.object(cli, 'run_media', side_effect=AssertionError('No media process')):
            plan = self.build(dry_run=True)
        self.assertEqual(plan['status'], 'planned')
        self.assertEqual(len(plan['entries']), 2)
        self.assertEqual(before, sorted(self.root.rglob('*')))

    def test_preview_verification_does_not_depend_on_freetype_or_default_font(self):
        self.build()
        with patch.object(ImageFont, 'core', None), patch.object(ImageDraw.ImageDraw, 'text', side_effect=AssertionError('No implicit font')):
            self.assertEqual(factory.verify_factory(self.out)['status'], 'verified')

    def test_html_escapes_user_text_and_has_only_local_links(self):
        self.data['title'] = '<script>alert(1)</script>'
        self.data['items'][0]['caption'] = '\" onerror=\"alert(1) <img src=https://bad.invalid>'
        self.build()
        page = (self.out / 'index.html').read_text(encoding='utf-8')
        self.assertIn('&lt;script&gt;', page)
        dom = DOM(); dom.feed(page)
        self.assertFalse(any(t in ('script', 'iframe', 'object', 'form') for t, _ in dom.elements))
        for _, attrs in dom.elements:
            self.assertFalse(any(k.startswith('on') for k in attrs))
            for key in ('href', 'src', 'srcset'):
                if key in attrs:
                    self.assertTrue((self.out / attrs[key]).is_file(), attrs[key])
        self.assertNotIn('@keyframes', page)
        self.assertIn('prefers-reduced-motion: reduce', page)
        self.assertIn('Content-Security-Policy', page)

    def test_identical_inputs_rejected_even_with_different_names(self):
        self.data['items'][1]['gif'] = self.data['items'][0]['gif']
        self.data['items'][1]['sha256'] = self.data['items'][0]['sha256']
        with self.assertRaisesRegex(ValueError, 'Duplicate decoded'):
            self.build()
        self.assertFalse(self.out.exists())

    def test_deterministic_bundle_and_relocation(self):
        self.build()
        another = self.root / 'second'
        factory.build_factory(self.manifest, another)
        self.assertEqual((self.out / 'collection.zip').read_bytes(), (another / 'collection.zip').read_bytes())
        moved = self.root / 'moved'
        self.out.rename(moved)
        self.assertEqual(factory.verify_factory(moved)['status'], 'verified')

    def test_invalid_manifest_options_and_cross_platform_ids(self):
        original = copy.deepcopy(self.data)
        changes = [lambda d: d.update(schema_version=True), lambda d: d.update(extra='bad'),
                   lambda d: d['items'][0].update(id='CON'), lambda d: d['items'][0].update(id='con'),
                   lambda d: d['items'][0].update(id='com1'), lambda d: d['items'][0].update(id='../escape'),
                   lambda d: d['items'][1].update(id=d['items'][0]['id']),
                   lambda d: d['items'][0].update(sha256='bad'), lambda d: d['items'][0].update(scene='also.json'),
                   lambda d: d['items'][0].update(caption='bad\ntext'), lambda d: d.update(items=[])]
        for change in changes:
            self.data = copy.deepcopy(original); change(self.data)
            with self.assertRaises(ValueError):
                self.build()
        self.assertFalse(self.out.exists())

    def test_duplicate_json_keys_rejected(self):
        self.manifest.write_text('{"title":"a", "title":"b"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
            factory.plan_factory(self.manifest)

    def test_paths_reject_traversal_urls_absolute_and_symlinks(self):
        original = self.data['items'][0]['gif']
        for name in ('../else.gif', '/tmp/else.gif', 'https://example.test/a.gif', 'a\\b.gif', './a.gif'):
            self.data['items'][0]['gif'] = name
            with self.assertRaises(ValueError):
                self.build()
        self.data['items'][0]['gif'] = original
        linked = self.source / 'linked.gif'
        try:
            linked.symlink_to(self.source / original)
        except (OSError, NotImplementedError):
            return
        self.data['items'][0]['gif'] = linked.name
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            self.build()

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO not supported on this platform')
    def test_fifo_rejected_without_waiting(self):
        path = self.source / 'pipe.gif'; os.mkfifo(path)
        self.data['items'][0]['gif'] = path.name
        with self.assertRaisesRegex(ValueError, 'regular local'):
            self.build()

    def test_bounds_reject_before_any_output(self):
        for name, value in (('MAX_MANIFEST_BYTES', 8), ('MAX_GIF_BYTES', 8), ('MAX_FRAMES', 2),
                            ('MAX_PIXELS', 2000), ('MAX_INPUT_BYTES', 16), ('MAX_BATCH_PIXELS', 5000)):
            with patch.object(factory, name, value), self.assertRaises(ValueError):
                self.build()
        self.assertFalse(self.out.exists())

    def test_changed_source_after_preflight_does_not_publish(self):
        original = factory.plan_factory
        def change(path):
            plan = original(path)
            (self.source / self.data['items'][0]['gif']).write_bytes(b'changed')
            return plan
        with patch.object(factory, 'plan_factory', side_effect=change), self.assertRaisesRegex(ValueError, 'changed after preflight'):
            self.build()
        self.assertFalse(self.out.exists())
        self.assertFalse(list(self.root.glob('.factory-stage-*')))
        self.assertFalse(self.out.with_name(self.out.name + '.lock').exists())

    def test_existing_output_and_competing_writer_are_preserved(self):
        self.out.mkdir(); (self.out / 'accepted').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            self.build()
        self.assertEqual((self.out / 'accepted').read_text(), 'keep')
        shutil.rmtree(self.out)
        original = factory.verify_factory
        def race(path):
            result = original(path)
            self.out.mkdir(); (self.out / 'accepted').write_text('other writer')
            return result
        with patch.object(factory, 'verify_factory', side_effect=race), self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual((self.out / 'accepted').read_text(), 'other writer')

    def test_failed_publication_cleans_only_new_output(self):
        real = cli.publish_file
        count = 0
        def fail(source, target, force=False):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError('injected failure')
            return real(source, target, force)
        with patch.object(cli, 'publish_file', side_effect=fail), self.assertRaisesRegex(OSError, 'injected failure'):
            self.build()
        self.assertFalse(self.out.exists())

    def test_corrupted_gif_preview_and_zip_are_detected(self):
        self.build()
        catalog = self.catalog()
        for name in (catalog['items'][0]['gif'], catalog['items'][0]['poster'], 'collection.zip'):
            path = self.out / name; before = path.read_bytes()
            path.write_bytes(b'broken')
            with self.assertRaises(ValueError):
                factory.verify_factory(self.out)
            path.write_bytes(before)

    def test_rehashed_wrong_preview_is_still_rejected(self):
        self.build()
        catalog = self.catalog()
        name = catalog['items'][0]['poster']
        path = self.out / name
        Image.new('RGBA', (48, 32), 'red').save(path)
        catalog['files'][name] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
        (self.out / 'catalog.json').write_bytes(factory.json_bytes(catalog))
        with self.assertRaisesRegex(ValueError, 'actual decoded GIF pixels'):
            factory.verify_factory(self.out)

    def test_rehashed_animated_png_preview_is_rejected(self):
        self.build()
        catalog = self.catalog()
        name = catalog['items'][0]['poster']
        path = self.out / name
        with Image.open(path) as source:
            first = source.convert('RGBA').copy()
        second = Image.new('RGBA', first.size, 'red')
        first.save(path, format='PNG', save_all=True, append_images=[second], duration=[100, 100], loop=0)
        catalog['files'][name] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
        (self.out / 'catalog.json').write_bytes(factory.json_bytes(catalog))
        with self.assertRaisesRegex(ValueError, 'single-frame PNG'):
            factory.verify_factory(self.out)

    def test_rehashed_script_in_gallery_is_rejected(self):
        self.build()
        path = self.out / 'index.html'; path.write_text('<script>alert(1)</script>', encoding='utf-8')
        catalog = self.catalog()
        catalog['files']['index.html'] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
        (self.out / 'catalog.json').write_bytes(factory.json_bytes(catalog))
        with self.assertRaisesRegex(ValueError, 'safe static template'):
            factory.verify_factory(self.out)

    def test_archive_extra_and_duplicate_members_rejected(self):
        self.build()
        path = self.out / 'collection.zip'; before = path.read_bytes()
        for name in ('../../escape', 'collection/index.html'):
            path.write_bytes(before)
            import warnings
            with warnings.catch_warnings(), zipfile.ZipFile(path, 'a') as archive:
                warnings.simplefilter('ignore', UserWarning)
                archive.writestr(name, 'bad')
            with self.assertRaisesRegex(ValueError, 'allowlist'):
                factory.verify_factory(self.out)

    def test_cli_build_verify_and_errors(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
        env.pop('OPENAI_API_KEY', None)
        def command(*args):
            return subprocess.run([sys.executable, '-m', 'gif_cinema', 'factory', *map(str, args)],
                                  cwd=self.root, env=env, capture_output=True, text=True, timeout=60)
        built = command('build', self.manifest, '--out', self.out)
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertEqual(json.loads(built.stdout)['items'], 2)
        checked = command('verify', self.out)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        (self.out / 'collection.zip').write_bytes(b'bad')
        bad = command('verify', self.out)
        self.assertNotEqual(bad.returncode, 0)
        self.assertNotIn('Traceback', bad.stderr)

    def add_scene(self):
        scene = {'format': layers.FORMAT, 'schema_version': 1, 'title': 'Two-color motion', 'width': 64, 'height': 48,
                 'fps': 25, 'duration_ms': 400, 'loop': False, 'matte': '#161924', 'layers': [
                    {'id': 'dot', 'type': 'ellipse', 'size': [12, 12], 'fill': '#c7a581',
                     'keyframes': [{'at': 0, 'x': .2, 'y': .5}, {'at': 1, 'x': .8, 'y': .5}]}]}
        path = self.source / 'scene.json'; path.write_bytes(factory.json_bytes(scene))
        self.data['items'].append({'id': 'scene', 'title': 'Local scene', 'scene': path.name, 'sha256': sha(path)})
        return path, scene

    def test_layer_scene_preflight_is_offline_and_review_bounded(self):
        path, scene = self.add_scene()
        with patch.object(layers, 'render_scene', side_effect=AssertionError('No rendering in dry-run')):
            result = self.build(dry_run=True)
        self.assertEqual(result['entries'][-1]['expected']['render_frames'], 10)
        scene.update(width=1024, height=1024, duration_ms=1000)
        path.write_bytes(factory.json_bytes(scene)); self.data['items'][-1]['sha256'] = sha(path)
        self.data['items'] = [self.data['items'][-1]]
        with patch.object(factory, 'MAX_PIXELS', 1024), self.assertRaisesRegex(ValueError, 'review limits'):
            self.build(dry_run=True)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_real_layer_scene_and_existing_gifs_build_as_one_collection(self):
        path, _ = self.add_scene()
        before = sha(path)
        result = self.build()
        item = self.catalog()['items'][-1]
        self.assertEqual(result['items'], 3)
        self.assertEqual(item['provenance']['kind'], 'local-layer-render')
        self.assertEqual(item['gif_info']['duration_ms'], 400)
        self.assertEqual(item['gif_info']['loop'], None)
        self.assertEqual(item['gif_info']['frames'], 10)
        self.assertEqual(sha(path), before)
        self.assertEqual(factory.verify_factory(self.out)['status'], 'verified')
        self.assertFalse(any(p.suffix == '.mp4' for p in self.out.rglob('*')))


if __name__ == '__main__':
    unittest.main()
