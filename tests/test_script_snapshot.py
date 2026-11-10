"""A render manifest must identify the script bytes that produced its timeline."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from gif_cinema import cli, render

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'snapshot_chapters', ROOT / '.agents/skills/gif-cinema/scripts/story_chapters.py')
chapters = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chapters)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ScriptSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # render.run canonicalizes the script path; macOS temp roots (or an
        # explicit TMPDIR) may themselves be symlinks.
        self.root = Path(self.temp.name).resolve()
        self.script = self.root / 'film.json'
        self.output = self.root / 'render'
        self.data = {'schema_version': 1, 'title': 'Snapshot fixture', 'ratio': '1:1',
                     'width': 64, 'height': 64, 'fps': 25, 'style_bible': 'Synthetic colors',
                     'shots': []}
        for name, color in (('red', (220, 35, 35)), ('blue', (35, 35, 220))):
            frames = [Image.new('RGB', (64, 64), color) for _ in range(2)]
            ImageDraw.Draw(frames[1]).rectangle((0, 0, 7, 7), fill='white')
            frames[0].save(self.root / f'{name}.gif', save_all=True, append_images=frames[1:],
                           duration=[500, 500], loop=0)
            self.data['shots'].append({'id': name, 'source': f'{name}.gif', 'caption': name,
                                      'first_frame_target': name, 'last_frame_target': name})
        self.write_script(self.data)
        self.original = self.script.read_bytes()
        self.source_hashes = {p.name: sha(p.read_bytes()) for p in self.root.glob('*.gif')}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.request = self.stack.enter_context(patch.object(cli, 'request_gif',
                                                           side_effect=AssertionError('No provider')))
        self.stack.enter_context(patch('urllib.request.OpenerDirector.open',
                                      side_effect=AssertionError('No network')))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def write_script(self, data):
        self.script.write_text(json.dumps(data), encoding='utf-8')

    def args(self, *extra):
        return cli.build_parser().parse_args(['render', str(self.script), '--out', str(self.output),
                                             '--max-api-calls', '0', *extra])

    def reverse_script(self):
        self.write_script({**self.data, 'shots': list(reversed(self.data['shots']))})

    @contextlib.contextmanager
    def change_after_parse(self, change):
        real_load = render.load_script
        def load_and_change(path, args):
            result = real_load(path, args)
            change()
            return result
        with patch.object(render, 'load_script', side_effect=load_and_change):
            yield

    @contextlib.contextmanager
    def fake_media(self):
        def encode(args):
            Path(args.output).write_bytes(b'Local encoder fixture, not real media')
        with patch('gif_cinema.render.shutil.which', return_value='fixture'), \
                patch('gif_cinema.doctor.require_film_capabilities'), \
                patch('gif_cinema.doctor.inspect_tool', return_value={'available': True}), \
                patch.object(cli, 'film', side_effect=encode), \
                patch.object(render, 'probe', return_value={'duration': '2.0'}):
            yield

    def manifest(self):
        return json.loads((self.output / 'render-manifest.json').read_text())

    def test_exact_bom_crlf_bytes_are_hashed_before_gif_and_reference_reads(self):
        reference = self.root / 'hero.png'
        Image.new('RGB', (8, 8), 'white').save(reference)
        data = {**self.data, 'shots': [*self.data['shots'], {
            'id': 'generated', 'prompt': 'A white dot moves', 'references': ['hero.png'],
            'first_frame_target': 'left', 'last_frame_target': 'right'}]}
        raw = b'\xef\xbb\xbf' + json.dumps(data, indent=2).replace('\n', '\r\n').encode('utf-8') + b'\r\n'
        self.script.write_bytes(raw)
        parsed = render.load_script(self.script, self.args())
        self.assertEqual(parsed['_script_sha256'], sha(raw))
        self.assertNotEqual(parsed['_script_sha256'], sha(reference.read_bytes()))
        self.assertEqual([shot['id'] for shot in parsed['shots']], ['red', 'blue', 'generated'])
        self.assertFalse(self.output.exists())
        self.request.assert_not_called()

    def test_input_cannot_supply_internal_snapshot_hash(self):
        self.write_script({**self.data, '_script_sha256': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'unknown fields'):
            render.load_script(self.script, self.args())

    def test_script_snapshot_read_is_bounded_before_json_parsing(self):
        self.script.write_bytes(b' ' * (1024 * 1024 + 1))
        with patch.object(render.json, 'loads') as parse:
            with self.assertRaisesRegex(ValueError, 'Script.*input limit'):
                render.load_script(self.script, self.args())
        parse.assert_not_called()

    def test_manifest_identifies_exact_bounded_reader_result_with_one_script_read(self):
        # The returned snapshot, not a later path read or reserialized JSON, must
        # identify the plan. All other local inputs still use the real reader.
        self.reverse_script()
        real_read = cli.read_local_bytes
        script_reads = []
        def bounded_snapshot(source, limit, label):
            if Path(source) == self.script:
                script_reads.append((limit, label))
                return self.original
            return real_read(source, limit, label)
        with patch.object(cli, 'read_local_bytes', side_effect=bounded_snapshot), self.fake_media():
            receipt = render.run(self.args('--execute'))
        self.assertEqual(script_reads, [(render.MAX_SCRIPT_BYTES, 'Script')])
        self.assertEqual(self.manifest()['script_sha256'], sha(self.original))
        self.assertNotEqual(self.manifest()['script_sha256'], sha(self.script.read_bytes()))
        self.assertEqual(receipt['api_calls'], 0)

    def test_edit_during_input_validation_does_not_relabel_the_snapshot(self):
        real_read = cli.read_gif_bytes
        def change_script(source):
            self.reverse_script()
            return real_read(source)
        with patch.object(cli, 'read_gif_bytes', side_effect=change_script):
            parsed = render.load_script(self.script, self.args())
        self.assertEqual(parsed['_script_sha256'], sha(self.original))
        self.assertNotEqual(parsed['_script_sha256'], sha(self.script.read_bytes()))
        self.assertEqual([shot['id'] for shot in parsed['shots']], ['red', 'blue'])

    def test_edit_after_parse_keeps_original_manifest_hash_and_captions(self):
        with self.change_after_parse(self.reverse_script), self.fake_media():
            receipt = render.run(self.args('--execute'))
        self.assertEqual(self.manifest()['script_sha256'], sha(self.original))
        self.assertNotEqual(self.manifest()['script_sha256'], sha(self.script.read_bytes()))
        captions = (self.output / 'captions.srt').read_text()
        self.assertLess(captions.index('red'), captions.index('blue'))
        self.assertEqual(receipt['api_calls'], 0)
        self.request.assert_not_called()

    def test_deleted_script_after_parse_is_not_reopened_for_manifest_identity(self):
        with self.change_after_parse(self.script.unlink), self.fake_media():
            receipt = render.run(self.args('--execute'))
        self.assertFalse(self.script.exists())
        self.assertEqual(self.manifest()['script_sha256'], sha(self.original))
        self.assertEqual(receipt['api_calls'], 0)
        self.assertEqual(list(self.output.rglob('*.lock')), [])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_real_equal_duration_reordering_blocks_mislabeled_chapters_then_rerenders(self):
        with self.change_after_parse(self.reverse_script):
            receipt = render.run(self.args('--execute'))
        manifest = self.manifest()
        original_movie = (self.output / 'film.mp4').read_bytes()
        self.assertEqual(manifest['script_sha256'], sha(self.original))
        self.assertEqual(receipt['api_calls'], 0)
        rejected = self.root / 'rejected-chapters'
        with patch.object(cli, 'run_media', side_effect=AssertionError('No export process')):
            with self.assertRaisesRegex(ValueError, 'Script does not match'):
                chapters.export_chapters(self.script, self.output, rejected, width=64, max_seconds=1)
        self.assertFalse(rejected.exists())

        # The actual input snapshot still exports in the movie's original order.
        original_script = self.root / 'original.json'
        original_script.write_bytes(self.original)
        old_chapters = self.root / 'original-chapters'
        plan = chapters.export_chapters(original_script, self.output, old_chapters, width=64, max_seconds=1)
        self.assertEqual([c['shot_ids'] for c in plan['chapters']], [['red'], ['blue']])
        with Image.open(old_chapters / 'chapter-01.gif') as image:
            red, _, blue = image.convert('RGB').getpixel((32, 32))
        self.assertGreater(red, 200); self.assertLess(blue, 50)

        # A new invocation takes the new snapshot and reuses the saved GIFs for free.
        rerun = render.run(self.args('--execute'))
        self.assertEqual((rerun['api_calls'], rerun['skipped']), (0, 2))
        self.assertEqual(self.manifest()['script_sha256'], sha(self.script.read_bytes()))
        self.assertNotEqual((self.output / 'film.mp4').read_bytes(), original_movie)
        archive = self.output / f'film-{sha(original_movie)[:16]}.mp4'
        self.assertEqual(archive.read_bytes(), original_movie)
        new_chapters = self.root / 'new-chapters'
        plan = chapters.export_chapters(self.script, self.output, new_chapters, width=64, max_seconds=1)
        self.assertEqual([c['shot_ids'] for c in plan['chapters']], [['blue'], ['red']])
        with Image.open(new_chapters / 'chapter-01.gif') as image:
            red, _, blue = image.convert('RGB').getpixel((32, 32))
        self.assertGreater(blue, 200); self.assertLess(red, 50)
        new_movie_hash = sha((self.output / 'film.mp4').read_bytes())
        with patch.object(cli, 'film', side_effect=AssertionError('Do not encode unchanged movie')):
            resumed = render.run(self.args('--execute'))
        self.assertEqual((resumed['api_calls'], resumed['skipped']), (0, 2))
        self.assertEqual(sha((self.output / 'film.mp4').read_bytes()), new_movie_hash)
        self.assertEqual(self.source_hashes, {p.name: sha(p.read_bytes()) for p in self.root.glob('*.gif')})
        self.assertEqual(list(self.output.rglob('*.lock')), [])
        self.request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
