"""Independent arithmetic and persisted-source checks for outfit motion triage."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import motion_review as review, pixel_palette as codec


def gif(values, delays=None, loop=0):
    frames = [Image.new('RGBA', (8, 8), (value, value, value, 255)) for value in values]
    stream = io.BytesIO()
    options = {'loop': loop} if loop is not None else {}
    frames[0].save(stream, format='GIF', save_all=True, append_images=frames[1:],
                   duration=delays or [80] * len(frames), **options)
    return stream.getvalue()


class MotionReviewTests(unittest.TestCase):
    def test_internal_jump_is_ranked_not_just_loop(self):
        report = review.analyze(gif([0, 10, 200, 0]))
        self.assertEqual(report['edges'][1]['visible_mae_0_255'], 190)
        self.assertEqual(report['edges'][3]['visible_mae_0_255'], 0)
        self.assertEqual(report['ranked_edge_indexes'][:2], [2, 1])
        self.assertEqual(report['visual_acceptance'], 'not-established')

    def test_native_holds_define_rate_and_timestamps(self):
        report = review.analyze(gif([0, 20, 40], [20, 200, 80]))
        self.assertEqual([r['at_ms'] for r in report['edges']], [20, 220, 300])
        self.assertEqual([r['visible_mae_per_second'] for r in report['edges']], [1000, 100, 500])
        self.assertEqual(report['adjacent_median_rate'], 550)

    def test_transparent_padding_does_not_dilute_changed_character(self):
        a = Image.new('RGBA', (20, 20)); b = a.copy()
        a.putpixel((5, 5), (0, 0, 0, 255))
        b.putpixel((6, 5), (0, 0, 0, 255))
        metric = review.change(a, b)
        self.assertEqual(metric['visible_union_pixels'], 2)
        self.assertEqual(metric['changed_pixels'], 2)
        self.assertEqual(metric['changed_visible_fraction'], 1)
        self.assertEqual(metric['visible_mae_0_255'], 255.0)

    def test_invisible_rgb_is_normalized(self):
        a = codec.canonical_rgba(Image.new('RGBA', (8, 8), (255, 0, 1, 0)))
        b = Image.new('RGBA', (8, 8))
        self.assertEqual(review.change(a, b)['changed_pixels'], 0)

    def test_focus_removes_static_opaque_background_dilution(self):
        a = Image.new('RGBA', (8, 8), 'white'); b = a.copy()
        b.putpixel((0, 0), (0, 0, 0, 255))
        stream = io.BytesIO()
        a.save(stream, format='GIF', save_all=True, append_images=[b], duration=80)
        full = review.analyze(stream.getvalue())
        focus = review.analyze(stream.getvalue(), [0, 0, 1, 1])
        self.assertEqual(full['edges'][0]['changed_visible_fraction'], 1/64)
        self.assertEqual(focus['edges'][0]['changed_visible_fraction'], 1)
        self.assertFalse(focus['loop_seam_is_played'])

    def test_invalid_focus_rejected(self):
        for box in ([True, 0, 1, 1], [0, 0, 0, 1], [-1, 0, 1, 1], [0, 0, 9, 8], [0, 0, 1], 'all'):
            with self.subTest(box=box), self.assertRaises(ValueError):
                review.analyze(gif([0, 10]), box)

    def test_single_frame_has_no_baseline_and_never_passes(self):
        report = review.analyze(gif([0], loop=None))
        self.assertIsNone(report['edges'][0]['rate_to_adjacent_median'])
        self.assertFalse(report['loop_seam_is_played'])
        json.dumps(report, allow_nan=False)
        self.assertEqual(review.sheet(codec.decode(gif([0], loop=None)), report).size, (640, 200))

    def test_explicit_symlink_source_and_output_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Canonicalize only our fixture root (macOS /var points to /private/var).
            # User-supplied links must still reach and fail the production guard.
            root = Path(tmp).resolve()
            source = root / 'input.gif'
            source.write_bytes(gif([0, 10]))
            alias = root / 'alias'
            try:
                alias.symlink_to(root, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('Directory symlinks unavailable')
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                review.build(alias / 'input.gif', root / 'review')
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                review.build(source, alias / 'review')
            self.assertFalse((root / 'review').exists())
            self.assertEqual(source.read_bytes(), gif([0, 10]))

    def test_round_trip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'input.gif'; source.write_bytes(gif([0, 10, 80]))
            original = source.read_bytes()
            result = review.build(source, root / 'review')
            self.assertEqual(result, review.verify(root / 'review'))
            self.assertEqual(source.read_bytes(), original)
            with self.assertRaises(ValueError):
                review.build(source, root / 'review')
            self.assertEqual(result, review.verify(root / 'review'))

    def test_receipt_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'input.gif'; source.write_bytes(gif([0, 10]))
            review.build(source, root / 'review')
            receipt = root / 'review/receipt.json'
            report = json.loads(receipt.read_text()); report['visual_acceptance'] = 'accepted'
            receipt.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                review.verify(root / 'review')

    def test_changed_source_cannot_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'input.gif'; source.write_bytes(gif([0, 10]))
            original_verify = review.verify
            def change_source(stage):
                result = original_verify(stage)
                source.write_bytes(gif([0, 20]))
                return result
            with patch.object(review, 'verify', side_effect=change_source), self.assertRaisesRegex(ValueError, 'changed'):
                review.build(source, root / 'review')
            self.assertFalse((root / 'review').exists())

    def test_split_identical_holds_do_not_inflate_rate(self):
        # Build a GIF with duplicate image records without Pillow merging them.
        raw = gif([0, 255], [100, 100], loop=None)
        original = codec.decode(raw)
        expanded = {**original, 'frames': [original['frames'][0], original['frames'][0], original['frames'][1]],
                    'delays_ms': [80, 20, 100]}
        baseline = review.analyze(raw)
        with patch.object(codec, 'decode', return_value=expanded):
            split = review.analyze(raw)
        self.assertEqual(split['edges'][1]['visible_mae_per_second'], baseline['edges'][0]['visible_mae_per_second'])
        self.assertEqual(split['adjacent_median_rate'], baseline['adjacent_median_rate'])
        self.assertEqual(split['edges'][1]['effective_visible_hold_ms'], 100)

    def test_play_once_first_context_does_not_wrap(self):
        raw = gif([0, 255, 20], loop=None)
        report = review.analyze(raw)
        picture = review.sheet(codec.decode(raw), report)
        self.assertEqual(report['ranked_edge_indexes'][0], 0)
        self.assertEqual(picture.getpixel((8, 24)), (0, 0, 0))

    def test_png_tamper_rejected_even_with_rehashed_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'input.gif'; source.write_bytes(gif([0, 10]))
            review.build(source, root / 'review')
            Image.new('RGBA', (8, 8), 'red').save(root / 'review/frames/0000.png')
            receipt = root / 'review/receipt.json'; report = json.loads(receipt.read_text())
            report['files'] = review.pixel.file_inventory(root / 'review')
            receipt.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                review.verify(root / 'review')
