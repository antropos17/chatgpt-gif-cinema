import unittest
from PIL import Image
from gif_cinema.motion_review import anchor_motion

def frame(x):
    f = Image.new("RGBA", (20, 20))
    f.paste((255, 0, 0, 255), (x, 5, x + 2, 10))
    return f

class AnchorTests(unittest.TestCase):
    def test_constant_speed_variable_delays(self):
        r = anchor_motion([frame(1), frame(2), frame(4)], [100, 200, 100])
        self.assertEqual(r["velocity_changes"][0]["velocity_change_px_per_second"], 0)
    def test_jump(self):
        r = anchor_motion([frame(1), frame(2), frame(8)], [100]*3)
        self.assertEqual(r["velocity_changes"][0]["velocity_change_px_per_second"], 50)
    def test_opaque_and_empty_unknown(self):
        for middle in [Image.new("RGBA",(20,20)), Image.new("RGBA",(20,20),"red")]:
            r = anchor_motion([frame(1), middle, frame(4)], [100]*3)
            self.assertIsNone(r["positions"][1])
            self.assertIsNone(r["velocity_changes"][0]["velocity_change_px_per_second"])
    def test_no_mutation(self):
        frames = [frame(1), frame(2)]
        original = [f.tobytes() for f in frames]
        anchor_motion(frames, [100,100])
        self.assertEqual(original, [f.tobytes() for f in frames])
    def test_split_hold_preserves_rates(self):
        joined = anchor_motion([frame(1), frame(3), frame(5)], [200, 200, 100])
        split = anchor_motion([frame(1), frame(1), frame(3), frame(5)], [100, 100, 200, 100])
        self.assertEqual(joined['positions'], split['positions'])
        self.assertEqual([r['velocity_change_px_per_second'] for r in joined['velocity_changes']],
                         [r['velocity_change_px_per_second'] for r in split['velocity_changes']])
        self.assertEqual(split['holds'][0], {'first_frame': 0, 'last_frame': 1, 'duration_ms': 200})

    def test_legacy_receipt_still_verifies(self):
        import json
        import tempfile
        from pathlib import Path
        from gif_cinema import motion_review as review
        from tests.test_motion_review import gif
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve()
            source = path / 'test.gif'
            source.write_bytes(gif([0, 20, 40]))
            report = review.build(source, path / 'review')
            self.assertEqual(report['schema_version'], 2)
            report.pop('anchor_motion')
            report['schema_version'] = 1
            (path / 'review' / 'receipt.json').write_text(json.dumps(report))
            self.assertEqual(review.verify(path / 'review'), report)
            report['schema_version'] = 3
            (path / 'review' / 'receipt.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'Unsupported'):
                review.verify(path / 'review')
