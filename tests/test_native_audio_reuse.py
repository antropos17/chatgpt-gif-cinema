"""Reuse verified visuals without preparing sprite caches solely for sound."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib
from PIL import Image

from gif_cinema import shot_renderer, shots
from test_native_shots import fixture
from test_native_stream_audio import LegacyRenderer, project, render_sound


class ProjectSoundTests(unittest.TestCase):
    def test_project_writer_matches_independent_legacy_pcm_with_crops_and_noise(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            for rate, fps, first, last in ((8001, 25, 0, 23), (8192, 30, 7, 31), (44100, 60, 17, 59)):
                value = project(rate=rate, duration=1.2, fps=fps, first=first, last=last)
                before = copy.deepcopy(value)
                expected = render_sound(LegacyRenderer, value, root/'old.wav')
                with patch.object(shot_renderer.Image, 'open', side_effect=AssertionError('sound must not open artwork')):
                    shot_renderer.write_sound(value, root/'new.wav')
                self.assertEqual((root/'new.wav').read_bytes(), expected); self.assertEqual(value, before)

    def test_renderer_sound_keeps_compatibility_wrapper(self):
        instance = object.__new__(shot_renderer.Renderer); instance.project = project()
        with patch.object(shot_renderer, 'write_sound') as writer:
            instance.sound('audio.wav')
        writer.assert_called_once_with(instance.project, 'audio.wav')

    def test_reused_writer_decodes_each_unique_source_without_preparing_tiles(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); value = fixture(root)
            value['clips']['unused-duplicate'] = copy.deepcopy(value['clips']['cells'])
            paths = {name: root/fact['path'] for name, fact in value['files'].items()}
            opened = []; ordinary = Image.open
            def read(path, *args, **kwargs):
                opened.append(Path(path)); return ordinary(path, *args, **kwargs)
            with patch.object(Image, 'open', read), patch.object(shot_renderer, 'write_sound') as writer:
                shot_renderer.write_reused_sound(value, paths, root/'audio.wav')
            self.assertEqual(opened, [root/'back.png', root/'actor.png'])
            writer.assert_called_once_with(value, root/'audio.wav')

    def test_benchmark_rejects_unpinned_reference_before_execution(self):
        path = Path(__file__).resolve().parents[1]/'tools/benchmark_audio_reuse.py'
        spec = importlib.util.spec_from_file_location('audio_benchmark', path)
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td).resolve()/'bad.py'; bad.write_text('raise AssertionError("must not execute")')
            with self.assertRaisesRegex(ValueError, 'exact 8d1cc28'): tool.reference(bad)


@unittest.skipUnless(shutil.which('ffmpeg') and importlib.util.find_spec('av'), 'FFmpeg and PyAV required')
class AudioReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); root = Path(cls.temp.name).resolve()
        cls.inputs = root/'input'; cls.inputs.mkdir(); value = fixture(cls.inputs)
        (cls.inputs/'project.json').write_text(json.dumps(value))
        cls.built = root/'base'
        with contextlib.redirect_stdout(io.StringIO()): shots.build_project(cls.inputs/'project.json', cls.built)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name).resolve()
        self.input = self.root/'input'; self.base = self.root/'base'
        shutil.copytree(self.inputs, self.input); shutil.copytree(self.built, self.base)
        self.path = self.input/'project.json'; self.value = json.loads(self.path.read_text())
        self.value['audio']['tones'][0][2] = 660; self.write()
        self.before = {str(p.relative_to(self.base)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in self.base.rglob('*') if p.is_file()}
        self.out = self.root/'revision'

    def write(self): self.path.write_text(json.dumps(self.value))

    def build(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()): return shots.build_project(self.path, self.out, **kwargs)

    def unchanged_base(self):
        self.assertEqual({str(p.relative_to(self.base)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in self.base.rglob('*') if p.is_file()}, self.before)

    def test_audio_only_revision_reuses_every_scene_without_renderer(self):
        with patch.object(shot_renderer.Renderer, '__init__', side_effect=AssertionError('no compositor needed')):
            result = self.build(reuse_from=self.base)
        self.assertEqual(result['scene_exports'], {'rendered': 0, 'reused': 2, 'resumed': 0})
        old = shots.read_json(self.base/'build-receipt.json'); new = shots.read_json(self.out/'build-receipt.json')
        self.assertNotEqual(old['audio_sha256'], new['audio_sha256'])
        from tools.benchmark_opaque_overlay import decoded
        self.assertEqual(decoded(self.base, old), decoded(self.out, new))
        self.assertEqual(shots.verify_project(self.out)['status'], 'verified'); self.unchanged_base()

    def test_audio_failure_after_fresh_visuals_resumes_without_renderer(self):
        with patch.object(shot_renderer.Renderer, 'sound', side_effect=OSError('sound interrupted')):
            with self.assertRaisesRegex(OSError, 'sound interrupted'): self.build()
        state = shots.read_json(self.out/'checkpoint.json'); self.assertEqual(len(state['completed']), 2)
        before = {row['file']: (self.out/row['file']).read_bytes() for row in state['completed'].values()}
        self.assertFalse((self.out/'film.mp4').exists()); self.assertFalse((self.out/'build-receipt.json').exists())
        with patch.object(shot_renderer.Renderer, '__init__', side_effect=AssertionError('resume must not construct renderer')):
            result = self.build(resume=True)
        self.assertEqual(result['scene_exports'], {'rendered': 0, 'reused': 0, 'resumed': 2})
        for name, raw in before.items(): self.assertEqual((self.out/name).read_bytes(), raw)
        self.assertEqual(shots.verify_project(self.out)['status'], 'verified')

    def test_direct_writer_failure_preserves_attempt_and_allows_clean_retry(self):
        failed = []
        def interrupted(value, path):
            Path(path).write_bytes(b'unfinished PCM attempt'); failed.append(Path(path)); raise OSError('direct write interrupted')
        with patch.object(shot_renderer, 'write_sound', interrupted):
            with self.assertRaisesRegex(OSError, 'direct write interrupted'): self.build(reuse_from=self.base)
        self.assertEqual(failed[0].read_bytes(), b'unfinished PCM attempt')
        self.assertFalse((self.out/'film.mp4').exists()); self.assertFalse((self.out/'build-receipt.json').exists())
        with patch.object(shot_renderer.Renderer, '__init__', side_effect=AssertionError('no renderer on retry')):
            self.build(reuse_from=self.base, resume=True)
        rec = shots.read_json(self.out/'build-receipt.json')
        self.assertNotEqual(rec['ready']['audio'], failed[0].name)
        self.assertEqual(failed[0].read_bytes(), b'unfinished PCM attempt'); self.unchanged_base()

    def test_mixed_revision_keeps_renderer_and_sound_method(self):
        self.value['scenes'][1]['effects']['gain'] = .5; self.write()
        initialized = []; sounded = []
        old_init = shot_renderer.Renderer.__init__; old_sound = shot_renderer.Renderer.sound
        def init(instance, *args): initialized.append(True); return old_init(instance, *args)
        def sound(instance, path): sounded.append(True); return old_sound(instance, path)
        with patch.object(shot_renderer.Renderer, '__init__', init), patch.object(shot_renderer.Renderer, 'sound', sound):
            result = self.build(reuse_from=self.base)
        self.assertEqual(result['scene_exports'], {'rendered': 1, 'reused': 1, 'resumed': 0})
        self.assertEqual(len(initialized), 1); self.assertEqual(len(sounded), 1); self.unchanged_base()

    def test_corrupt_scene_is_rejected_before_audio_or_publication(self):
        rec = shots.read_json(self.base/'build-receipt.json'); path = self.base/next(iter(rec['completed'].values()))['file']
        path.write_bytes(path.read_bytes()[:20])
        with patch.object(shot_renderer, 'write_sound', side_effect=AssertionError('must verify scenes first')):
            with self.assertRaises(ValueError): self.build(reuse_from=self.base)
        self.assertFalse(self.out.exists())

    def test_corrupt_asset_is_rejected_before_audio_or_publication(self):
        (self.input/'actor.png').write_bytes(b'changed source')
        with patch.object(shot_renderer, 'write_sound', side_effect=AssertionError('must validate art')):
            with self.assertRaisesRegex(ValueError, 'hash'): self.build(reuse_from=self.base)
        self.assertFalse(self.out.exists()); self.unchanged_base()

    def add_unused(self, name, raw):
        (self.input/name).write_bytes(raw)
        self.value['files'][name] = dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.value['clips']['unused'] = {**self.value['clips']['cells'], 'source': name}
        self.write()
        prior = shots.read_json(self.base/'build-receipt.json')
        self.assertEqual(shots.BuildContext(self.path).identities(prior['engine']), prior['keys'])

    def test_header_hash_and_crc_valid_but_undecodable_unused_clip_is_rejected(self):
        raw = bytearray((self.input/'actor.png').read_bytes()); offset = 8
        while offset < len(raw):
            size = struct.unpack('>I', raw[offset:offset+4])[0]; start = offset+8
            if raw[offset+4:start] == b'IDAT':
                raw[start:start+2] = b'\0\0'
                raw[start+size:start+size+4] = struct.pack('>I', zlib.crc32(raw[offset+4:start+size]) & 0xffffffff)
                break
            offset += size+12
        else: self.fail('fixture has no IDAT')
        self.add_unused('unused.png', raw)
        with Image.open(self.input/'unused.png') as image:
            self.assertEqual(image.size, (16, 8)); image.verify()
        with patch.object(shot_renderer.Renderer, '__init__', side_effect=AssertionError('must not create renderer')), \
                patch.object(shot_renderer, 'write_sound', side_effect=AssertionError('must reject compressed source')):
            with self.assertRaises(OSError): self.build(reuse_from=self.base)
        self.assertFalse((self.out/'film.mp4').exists()); self.assertFalse((self.out/'build-receipt.json').exists())
        self.unchanged_base()

    def test_source_color_conversion_errors_are_not_skipped(self):
        stream = io.BytesIO(); Image.new('LAB', (16, 8)).save(stream, format='TIFF')
        self.add_unused('unsupported.png', stream.getvalue())
        with Image.open(self.input/'unsupported.png') as image:
            image.load(); self.assertEqual(image.mode, 'LAB')
        # Pillow mode support varies by version. Inject a conversion failure on
        # this decodable source, not on the RGB video verification frames.
        convert = Image.Image.convert; calls = []
        def unsupported(image, mode=None, *args, **kwargs):
            if image.mode == 'LAB' and mode == 'RGB':
                calls.append(True); raise ValueError('source mode conversion failed')
            return convert(image, mode, *args, **kwargs)
        with patch.object(Image.Image, 'convert', unsupported), \
                patch.object(shot_renderer.Renderer, '__init__', side_effect=AssertionError('must not create renderer')), \
                patch.object(shot_renderer, 'write_sound', side_effect=AssertionError('must validate conversion')):
            with self.assertRaisesRegex(ValueError, 'source mode conversion failed'): self.build(reuse_from=self.base)
        self.assertEqual(calls, [True])
        self.assertFalse((self.out/'film.mp4').exists()); self.assertFalse((self.out/'build-receipt.json').exists())
        self.unchanged_base()

    def test_source_drift_during_audio_blocks_final_publication(self):
        write = shot_renderer.write_sound
        def changed(value, path):
            write(value, path); self.value['title'] = 'changed while writing'; self.write()
        with patch.object(shot_renderer, 'write_sound', changed):
            with self.assertRaisesRegex(ValueError, 'Inputs changed during build'): self.build(reuse_from=self.base)
        self.assertFalse((self.out/'film.mp4').exists()); self.assertFalse((self.out/'build-receipt.json').exists())
        self.assertEqual(len(shots.read_json(self.out/'checkpoint.json')['completed']), 2); self.unchanged_base()

    def test_engine_change_still_blocks_interrupted_resume(self):
        with patch.object(shot_renderer, 'write_sound', side_effect=OSError('stop audio')):
            with self.assertRaises(OSError): self.build(reuse_from=self.base)
        with patch.object(shots, 'engine_identity', return_value='different-engine'):
            with self.assertRaisesRegex(ValueError, 'Resume input or engine changed'):
                self.build(reuse_from=self.base, resume=True)
        self.assertFalse((self.out/'film.mp4').exists()); self.assertFalse((self.out/'build-receipt.json').exists())
