"""An interrupted publish must never roll back somebody else's edits."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import cli, pixel, sequence


class PixelPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_replaced_or_edited_published_file_survives_later_failure(self):
        for publisher, replace in ((function, change) for function in (pixel.publish, sequence.publish)
                                   for change in (True, False)):
            with self.subTest(publisher=publisher.__module__, replace=replace):
                name = publisher.__module__.rsplit('.', 1)[-1]
                stage = self.root / f'stage-{name}-{replace}'; stage.mkdir()
                (stage / 'a').write_bytes(b'first published file')
                (stage / 'b').write_bytes(b'second published file')
                (stage / 'receipt.json').write_text('{}')
                out = self.root / f'out-{name}-{replace}'
                original = cli.publish_file
                def race(source, target):
                    if target.name == 'b':
                        if replace:
                            (out / 'a').unlink()
                        (out / 'a').write_bytes(b'other writer work')
                        raise OSError('later publication failed')
                    return original(source, target)
                with patch.object(cli, 'publish_file', side_effect=race), self.assertRaises(OSError):
                    publisher(stage, out)
                self.assertEqual((out / 'a').read_bytes(), b'other writer work')
                self.assertFalse((out / 'receipt.json').exists())

    def test_receipt_is_last_and_existing_raced_target_is_never_replaced(self):
        stage = self.root / 'stage'; stage.mkdir()
        for name in ('source.gif', 'preview.gif', 'receipt.json'):
            (stage / name).write_bytes(name.encode())
        out = self.root / 'out'
        seen = []
        original = cli.publish_file
        def record(source, target):
            seen.append(target.name)
            return original(source, target)
        with patch.object(cli, 'publish_file', side_effect=record):
            pixel.publish(stage, out)
        self.assertEqual(seen[-1], 'receipt.json')
        with self.assertRaises(FileExistsError):
            pixel.publish(stage, out)
        self.assertEqual((out / 'source.gif').read_bytes(), b'source.gif')

    def test_rehashed_palette_schema_keeps_strict_integer_type(self):
        source = self.root / 'source.gif'
        Image.new('RGB', (4, 4), 'red').save(source, duration=40)
        out = self.root / 'out'
        pixel.build(source, out)
        for invalid in (True, 1.0):
            document = json.loads((out / 'palette.json').read_text())
            document['schema_version'] = invalid
            pixel.dump(out / 'palette.json', document)
            receipt = json.loads((out / 'receipt.json').read_text())
            receipt['files'] = pixel.file_inventory(out)
            pixel.dump(out / 'receipt.json', receipt)
            with self.subTest(version=invalid), self.assertRaisesRegex(ValueError, 'Palette document differs'):
                pixel.verify(out)

    def test_inventory_byte_counts_keep_strict_integer_types(self):
        source = self.root / 'source.gif'
        Image.new('RGB', (4, 4), 'red').save(source, duration=40)
        out = self.root / 'out'
        pixel.build(source, out)
        receipt = json.loads((out / 'receipt.json').read_text())
        receipt['files']['source.gif']['bytes'] = float(receipt['files']['source.gif']['bytes'])
        pixel.dump(out / 'receipt.json', receipt)
        with self.assertRaisesRegex(ValueError, 'inventory or hashes changed'):
            pixel.verify(out)
