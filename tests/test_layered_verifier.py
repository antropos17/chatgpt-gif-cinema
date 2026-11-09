"""Verify complete offline layered exports, not a caller-selected hash subset."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import layers
from tools.verify_layered_scene import expected_outputs, verify


def scene(**changes):
    return layers.normalize_scene({'format': layers.FORMAT, 'schema_version': 1,
        'width': 32, 'height': 32, 'fps': 25, 'duration_ms': 160, 'layers': [
            {'id': 'back', 'type': 'rect', 'size': [32, 32], 'fill': '#112233'},
            {'id': 'front', 'type': 'rect', 'size': [8, 8], 'keyframes': [
                {'at': 0, 'x': .25}, {'at': 1, 'x': .75}]}], **changes})


class InventoryTests(unittest.TestCase):
    def test_required_outputs_follow_scene_without_receipt(self):
        names = expected_outputs(scene())
        self.assertEqual(len(names), 9 + 4 + 2)
        self.assertTrue({'preview.gif', 'preview.mp4', 'editable/scene.json',
                         'frames/0003.png', 'layers/front.png'} <= names)
        self.assertNotIn('receipt.json', names)

    def test_shared_portable_assets_are_counted_once(self):
        value = scene(layers=[{'id': name, 'type': 'image', 'source': 'assets/shared.image',
                              'size': [8, 8]} for name in ('first', 'second')])
        self.assertEqual(expected_outputs(value) - expected_outputs(scene()),
                         {'editable/assets/shared.image', 'layers/first.png', 'layers/second.png'})
        self.assertEqual(len(expected_outputs(value)), 9 + 4 + 2 + 1)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'Real FFmpeg and ffprobe required')
class ExportVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        # macOS exposes its temporary directory through /var -> /private/var.
        # Use the canonical directory; the renderer intentionally rejects symlink parents.
        cls.root = Path(cls.temporary.name).resolve()
        Image.new('RGBA', (8, 8), '#ff8844').save(cls.root / 'sprite.png')
        value = scene(layers=[{'id': name, 'type': 'image', 'source': 'sprite.png',
            'size': [8, 8], 'keyframes': [{'at': 0, 'x': .25}, {'at': 1, 'x': .75}]}
            for name in ('first', 'second')])
        source = cls.root / 'scene.json'
        source.write_bytes(layers.serialize_scene(value))
        cls.original = cls.root / 'original'
        with patch('socket.socket', side_effect=AssertionError('No network')):
            cls.receipt = layers.render_scene(source, cls.original)

    def setUp(self):
        self.working = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.working.cleanup)
        self.output = Path(self.working.name) / 'relocated'
        shutil.copytree(self.original, self.output)
        self.network = patch('socket.socket', side_effect=AssertionError('No network'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def write_receipt(self, receipt):
        (self.output / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')

    def test_real_complete_relocated_export_passes_without_encoder_or_network(self):
        with patch('subprocess.run', side_effect=AssertionError('No encoder')):
            report = verify(self.output)
        self.assertEqual(report['status'], 'verified')
        self.assertEqual(report['output_hashes_verified'], len(self.receipt['outputs']))
        self.assertEqual(report['frames_reopened_and_matched'], 4)
        self.assertEqual(report['api_calls'], 0)
        self.assertEqual(report['loop_review']['status'], 'human-review-required')

    def test_empty_inventory_and_absent_previews_are_not_verified(self):
        receipt = copy.deepcopy(self.receipt)
        receipt['outputs'] = {}
        self.write_receipt(receipt)
        (self.output / 'preview.gif').unlink()
        (self.output / 'preview.mp4').unlink()
        with patch.object(layers, 'render_at', side_effect=AssertionError('Reject before rerender')):
            with self.assertRaisesRegex(ValueError, 'inventory'):
                verify(self.output)

    def test_every_required_entry_cannot_be_omitted_even_if_file_exists(self):
        for name in self.receipt['outputs']:
            with self.subTest(name=name):
                receipt = copy.deepcopy(self.receipt)
                del receipt['outputs'][name]
                self.write_receipt(receipt)
                with self.assertRaisesRegex(ValueError, 'inventory'):
                    verify(self.output)

    def test_each_listed_file_must_exist(self):
        for name in self.receipt['outputs']:
            with self.subTest(name=name):
                path = self.output / name
                raw = path.read_bytes()
                path.unlink()
                try:
                    with self.assertRaises((ValueError, OSError)):
                        verify(self.output)
                finally:
                    path.write_bytes(raw)

    def test_unexpected_or_aliased_receipt_entry_is_rejected(self):
        for name in ('extra.png', 'receipt.json', '../outside', './preview.gif',
                     'frames\\0000.png', 'https://example.invalid/media'):
            with self.subTest(name=name):
                receipt = copy.deepcopy(self.receipt)
                receipt['outputs'][name] = '0' * 64
                self.write_receipt(receipt)
                with self.assertRaisesRegex(ValueError, 'inventory'):
                    verify(self.output)

    def test_missing_nonobject_or_oversized_outputs_are_rejected(self):
        for outputs in (None, [], '', 1, {f'{i}.png': '0' * 64 for i in range(1601)}):
            with self.subTest(kind=type(outputs).__name__):
                receipt = copy.deepcopy(self.receipt)
                if outputs is None:
                    receipt.pop('outputs')
                else:
                    receipt['outputs'] = outputs
                self.write_receipt(receipt)
                with self.assertRaisesRegex(ValueError, 'outputs must be an object'):
                    verify(self.output)

    def test_invalid_hash_values_are_rejected(self):
        for invalid in (None, True, [], {}, 'f' * 63, 'g' * 64, 'A' * 64):
            with self.subTest(value=invalid):
                receipt = copy.deepcopy(self.receipt)
                receipt['outputs']['preview.gif'] = invalid
                self.write_receipt(receipt)
                with self.assertRaisesRegex(ValueError, 'Invalid SHA-256'):
                    verify(self.output)

    def test_duplicate_receipt_fields_are_rejected(self):
        raw = json.dumps(self.receipt)
        raw = raw.replace('"outputs": {', '"outputs": {}, "outputs": {', 1)
        (self.output / 'receipt.json').write_text(raw, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate receipt field: outputs'):
            verify(self.output)

    def test_unchanged_hashes_detect_modified_media(self):
        for name in ('preview.gif', 'preview.mp4', 'contact-sheet.png', 'layers/first.png'):
            with self.subTest(name=name):
                path = self.output / name
                raw = path.read_bytes()
                path.write_bytes(raw + b'changed')
                try:
                    with self.assertRaisesRegex(ValueError, 'Export hash changed'):
                        verify(self.output)
                finally:
                    path.write_bytes(raw)

    def test_rehashed_modified_png_still_fails_pixel_comparison(self):
        path = self.output / 'frames/0000.png'
        Image.new('RGBA', (32, 32), '#00ff00').save(path)
        receipt = copy.deepcopy(self.receipt)
        receipt['outputs']['frames/0000.png'] = layers.digest(path.read_bytes())
        self.write_receipt(receipt)
        with self.assertRaisesRegex(ValueError, 'Saved PNG differs'):
            verify(self.output)

    def test_legacy_receipt_without_layer_preview_metadata_still_passes(self):
        receipt = copy.deepcopy(self.receipt)
        receipt.pop('layer_previews')
        receipt.pop('layer_preview_sampling')
        self.write_receipt(receipt)
        self.assertEqual(verify(self.output)['status'], 'verified')

    def test_extra_unlisted_review_report_is_not_part_of_export_contract(self):
        (self.output / 'review-notes.txt').write_text('Human review still pending')
        self.assertEqual(verify(self.output)['output_hashes_verified'], len(self.receipt['outputs']))


if __name__ == '__main__':
    unittest.main()
