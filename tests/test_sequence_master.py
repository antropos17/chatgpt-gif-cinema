"""Source-PNG masters preserve alpha, holds and all samples across authored cuts."""
import importlib.util
import json
import shutil
import socket
import unittest
from unittest.mock import patch

from gif_cinema import master, sequence, sequence_master
from test_sequence import SequenceFixture


@unittest.skipUnless(importlib.util.find_spec('av') and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'PyAV and FFmpeg required')
class SequenceMasterTests(SequenceFixture, unittest.TestCase):
    def build_source(self):
        self.save()
        path = self.root / 'built'
        sequence.build_sequence(self.path, path)
        return path

    def test_original_rgba_and_holds_all_shots_offline(self):
        source = self.build_source()
        with patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')):
            result = sequence_master.build(source, self.root / 'master')
        self.assertEqual(result['frames'], 10)
        self.assertEqual(result['duration_ms'], 400)
        self.assertTrue(result['alpha_preserved'])
        self.assertEqual(result['provider_calls'], 0)
        report = json.loads((self.root / 'master/master-receipt.json').read_text())
        self.assertEqual([f['pts_cs'] for f in report['frames']], list(range(0, 40, 4)))
        self.assertEqual(report['frames'][4]['shot'], '02-release')
        self.assertEqual(report['frames'][8]['shot'], '03-result')
        self.assertEqual(master.verify_master(self.root / 'master/master.mkv', report)['rgba_mismatches'], 0)
        with self.assertRaises(ValueError):
            sequence_master.build(source, self.root / 'master')

    def test_fifteen_second_authored_sequence_at_fifty_fps(self):
        self.seed['fps'] = 50
        for shot in self.value['shots']:
            shot['duration_ms'] = 5000
        self.value['shots'][1]['tracks']['prop']['attachments'][0]['end_ms'] = 5000
        source = self.build_source()
        result = sequence_master.build(source, self.root / 'master')
        self.assertEqual((result['frames'], result['duration_ms']), (750, 15000))

    def test_rejects_changed_source_without_publication(self):
        source = self.build_source()
        (source / 'shots/01-carry/frames/0000.png').write_bytes(b'invalid')
        with self.assertRaises(ValueError):
            sequence_master.build(source, self.root / 'master')
        self.assertFalse((self.root / 'master').exists())

    def test_rejects_drift_during_encoding(self):
        source = self.build_source()
        verify = master.verify_master
        def mutate(path, report):
            result = verify(path, report)
            (source / 'shots/01-carry/frames/0000.png').write_bytes(b'changed')
            return result
        with patch.object(master, 'verify_master', side_effect=mutate), self.assertRaises(ValueError):
            sequence_master.build(source, self.root / 'master')
        self.assertFalse((self.root / 'master').exists())

    def test_receipt_drift_during_verification_is_rejected(self):
        source = self.build_source()
        verify = sequence.verify_sequence
        def mutate(path):
            result = verify(path)
            receipt = source / 'sequence-receipt.json'
            value = json.loads(receipt.read_text())
            value['fps'] = 50
            receipt.write_text(json.dumps(value))
            return result
        with patch.object(sequence, 'verify_sequence', side_effect=mutate), self.assertRaisesRegex(ValueError, 'during verification'):
            sequence_master.build(source, self.root / 'master')
        self.assertFalse((self.root / 'master').exists())

    def test_nested_output_is_rejected_without_creating_anything(self):
        source = self.build_source()
        with self.assertRaisesRegex(ValueError, 'outside'):
            sequence_master.build(source, source / 'master')
        self.assertFalse((source / 'master').exists())
