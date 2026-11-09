"""Offline Unicode coverage, provenance and reproducible text-rendering checks."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageFont
from gif_cinema import layers, text_fonts

RUSSIAN = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя'
AZERBAIJANI = 'ABCÇDEƏFGĞHXIİJKQLMNOÖPRSŞTUÜVYZabcçdeəfgğhxıijkqlmnoöprsştuüvyz'
ROOT = Path(__file__).resolve().parents[1]


def scene(text='Привет, Əli! Azərbaycan', font_id=text_fonts.NOTO_FONT):
    layer = {'id': 'label', 'type': 'text', 'text': text, 'font_size': 24,
             'keyframes': [{'at': 0, 'x': .48}, {'at': 1, 'x': .52}]}
    if font_id is not None:
        layer['font_id'] = font_id
    return {'format': layers.FORMAT, 'schema_version': 1, 'width': 640, 'height': 100,
            'fps': 25, 'duration_ms': 160, 'layers': [layer]}


def clear_caches():
    text_fonts.coverage.cache_clear()
    text_fonts._noto_bytes.cache_clear()
    text_fonts.load_font.cache_clear()


class FontCoverageTests(unittest.TestCase):
    def setUp(self):
        clear_caches()
        self.addCleanup(clear_caches)

    def test_full_russian_and_azerbaijani_alphabets_have_real_glyphs(self):
        coverage = text_fonts.coverage(text_fonts.NOTO_FONT)
        font = text_fonts.load_font(text_fonts.NOTO_FONT, 36)
        missing = bytes(font.getmask('\uffff'))
        for language, alphabet in [('Russian', RUSSIAN), ('Azerbaijani', AZERBAIJANI)]:
            for char in alphabet:
                with self.subTest(language=language, char=char):
                    self.assertIn(ord(char), coverage)
                    self.assertNotEqual(bytes(font.getmask(char)), missing)
                    self.assertIsNotNone(font.getmask(char).getbbox())
        for alphabet in (RUSSIAN, AZERBAIJANI):
            self.assertEqual(layers.normalize_scene(scene(alphabet))['layers'][0]['text'], alphabet)

    def test_legacy_missing_glyphs_are_rejected_before_pixel_allocation(self):
        for text in ('Привет', 'Əli', 'ə ı İ ğ', '😀'):
            with self.subTest(text=text), patch('PIL.Image.new', side_effect=AssertionError('No raster allocation')):
                with self.assertRaisesRegex(ValueError, 'Unsupported text.*U\\+'):
                    layers.normalize_scene(scene(text, font_id=None))

    def test_supported_legacy_punctuation_and_ligatures_keep_coverage(self):
        for text in ('Motion in layers.', '“Hello…” © 2026', 'fi ﬁ fl ﬂ'):
            normalized = layers.normalize_scene(scene(text, font_id=None))
            self.assertEqual(normalized['layers'][0]['font_id'], text_fonts.LEGACY_FONT)
            self.assertEqual(normalized['layers'][0]['text'], text)

    def test_legacy_raster_pixels_match_the_previous_renderer(self):
        from PIL import ImageDraw
        layer = layers.normalize_scene(scene('Motion in layers. “Hello…”', font_id=None))['layers'][0]
        font = ImageFont.load_default(size=layer['font_size'] * 3)
        bounds = font.getbbox(layer['text'])
        raw = Image.new('RGBA', (bounds[2] - bounds[0] + 12, bounds[3] - bounds[1] + 12))
        ImageDraw.Draw(raw).text((6 - bounds[0], 6 - bounds[1]), layer['text'], font=font, fill=layer['fill'])
        import math
        expected = raw.resize((math.ceil(raw.width / 3), math.ceil(raw.height / 3)), Image.Resampling.LANCZOS)
        actual = layers.rasterize(layer, {})
        self.assertEqual(actual.size, expected.size)
        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_noto_rejects_missing_glyphs_and_unhandled_sequences(self):
        for text in ('😀', '漢字', 'abc\u200d', 'A\ufe0f', 'q\u0301', 'abc\u202e', 'x\ue000'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'Unsupported text'):
                layers.normalize_scene(scene(text))

    def test_nfc_normalization_handles_decomposed_ru_and_az_letters(self):
        normalized = layers.normalize_scene(scene('Е\u0308 И\u0306 G\u0306 I\u0307 C\u0327 S\u0327'))
        self.assertEqual(normalized['layers'][0]['text'], 'Ё Й Ğ İ Ç Ş')
        self.assertEqual(normalized['text_renderer']['normalization'], 'NFC')

    def test_font_hash_and_renderer_identity_are_saved_explicitly(self):
        normalized = layers.normalize_scene(scene())
        self.assertEqual(normalized['layers'][0]['font_sha256'], text_fonts.FONTS[text_fonts.NOTO_FONT]['sha256'])
        self.assertEqual(normalized['text_renderer'], text_fonts.renderer_identity())
        self.assertEqual(normalized, layers.normalize_scene(normalized))

    def test_unknown_font_paths_and_font_hash_mismatch_fail_closed(self):
        for font_id in ('/usr/share/fonts/font.ttf', '../font.ttf', 'https://example.com/font.ttf', {}, None):
            candidate = scene()
            candidate['layers'][0]['font_id'] = font_id
            with self.subTest(font=font_id), self.assertRaisesRegex(ValueError, 'font_id'):
                layers.normalize_scene(candidate)
        candidate = scene(); candidate['layers'][0]['font_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'font_sha256'):
            layers.normalize_scene(candidate)

    def test_changed_environment_rejected_instead_of_silent_rerender(self):
        normalized = layers.normalize_scene(scene())
        for field in ('pillow', 'freetype', 'layout_engine', 'normalization'):
            changed = copy.deepcopy(normalized); changed['text_renderer'][field] = 'different'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'text_renderer differs'):
                layers.normalize_scene(changed)

    def test_tampered_font_and_coverage_are_rejected(self):
        real_read = text_fonts._read_asset
        for suffix, operation, message in [('.ttf', lambda: text_fonts.load_font(text_fonts.NOTO_FONT, 24), 'checksum'),
                    ('.coverage.json', lambda: text_fonts.coverage(text_fonts.NOTO_FONT), 'coverage changed')]:
            clear_caches()
            def changed(name, limit):
                raw = real_read(name, limit)
                return raw + b'tampered' if name.endswith(suffix) else raw
            with patch.object(text_fonts, '_read_asset', side_effect=changed), self.assertRaisesRegex(ValueError, message):
                operation()

    def test_unknown_pillow_default_font_bytes_are_not_trusted(self):
        old = ImageFont.load_default(size=24)
        old.font_bytes = b'changed font bytes'
        with patch('PIL.ImageFont.load_default', return_value=old), self.assertRaisesRegex(ValueError, 'not the recorded Aileron'):
            text_fonts.load_font(text_fonts.LEGACY_FONT, 24)

    def test_pinned_font_uses_bytes_and_basic_engine_not_system_search(self):
        real = ImageFont.truetype
        calls = []
        def guarded(font, *args, **kwargs):
            self.assertIsInstance(font, io.BytesIO)
            self.assertEqual(kwargs['layout_engine'], ImageFont.Layout.BASIC)
            calls.append(True)
            return real(font, *args, **kwargs)
        with patch('PIL.ImageFont.truetype', side_effect=guarded):
            text_fonts.load_font(text_fonts.NOTO_FONT, 24)
        self.assertEqual(calls, [True])

    def test_packaged_font_hash_license_and_manifest_match(self):
        folder = ROOT / 'gif_cinema' / 'assets' / 'fonts'
        self.assertEqual(hashlib.sha256((folder / 'NotoSans-Regular.ttf').read_bytes()).hexdigest(),
                         text_fonts.FONTS[text_fonts.NOTO_FONT]['sha256'])
        license = (folder / 'OFL.txt').read_text()
        for required in ('Copyright 2015 Google LLC.', 'SIL OPEN FONT LICENSE', 'PERMISSION & CONDITIONS', 'TERMINATION', 'DISCLAIMER'):
            self.assertIn(required, license)
        for font_id in (text_fonts.LEGACY_FONT, text_fonts.NOTO_FONT):
            descriptor = text_fonts.FONTS[font_id]
            raw = (folder / descriptor['coverage']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), descriptor['coverage_sha256'])
            self.assertEqual(json.loads(raw)['font_sha256'], descriptor['sha256'])


class FontFileTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'output' / 'tmp'; base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'scene.json'
        self.path.write_bytes(layers.serialize_scene(scene()))
        self.network = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden'))
        self.network.start(); self.addCleanup(self.network.stop)

    def test_save_reopen_survives_relocation_and_retains_every_pixel(self):
        prepared = layers.prepare_scene(self.path)
        exported = layers.save_bundle(prepared, self.root / 'saved')
        moved = self.root / 'moved'; shutil.copytree(exported.parent, moved)
        reopened = layers.prepare_scene(moved / 'scene.json')
        for timestamp in (0, 40, 80, 120, 160):
            self.assertEqual(layers.render_at(prepared, timestamp)[0].tobytes(), layers.render_at(reopened, timestamp)[0].tobytes())
        saved = json.loads((moved / 'scene.json').read_text())
        self.assertIn('font_sha256', saved['layers'][0])
        self.assertEqual(saved['text_renderer'], text_fonts.renderer_identity())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real FFmpeg and ffprobe required')
    def test_real_unicode_gif_mp4_export_and_reopen(self):
        from tools.verify_layered_scene import verify
        out = self.root / 'render'
        receipt = layers.render_scene(self.path, out)
        self.assertEqual(receipt['text_renderer'], text_fonts.renderer_identity())
        self.assertEqual(receipt['font_assets'][text_fonts.NOTO_FONT]['sha256'], text_fonts.FONTS[text_fonts.NOTO_FONT]['sha256'])
        self.assertEqual(verify(out)['frames_reopened_and_matched'], 4)

    def test_bad_unicode_fails_dry_run_before_output_or_encoder(self):
        self.path.write_text(json.dumps(scene('Привет', font_id=None)))
        out = self.root / 'bad'
        with patch('subprocess.run', side_effect=AssertionError('No encoder')):
            with self.assertRaisesRegex(ValueError, 'Unsupported text'):
                layers.render_scene(self.path, out, dry_run=True)
        self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
