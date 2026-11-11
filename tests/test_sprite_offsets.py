"""Authored column corrections preserve complete RGBA cells and native timing."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from gif_cinema import layer_sprites, sprites


class ColumnOffsetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sheet = Image.new('RGBA', (6, 6))
        # Distinct hidden RGB and partial alpha test byte preservation, not bbox.
        for y in range(6):
            for x in range(6):
                self.sheet.putpixel((x, y), (x * 30, y * 30, 97, [0, 1, 128, 255][(x+y) % 4]))
        self.sheet.save(self.root / 'sheet.png')
        self.base = {'schema_version': 1, 'atlas': 'sheet.png', 'grid': [2, 2],
                     'duration_ms': 40, 'columns': 2, 'padding': 0}

    def load(self, **changes):
        spec = {**self.base, **changes}
        path = self.root / 'spec.json'
        path.write_text(json.dumps(spec))
        return sprites.load_sheet(path)

    def test_mixed_offsets_every_row_reordered_repeated_exact_bytes(self):
        cells = [[1, 1], [0, 0], [1, 0], [0, 1], [0, 1]]
        frames, delays, loop, source, options = self.load(
            cells=cells, column_offsets=[[-2, 1], [3, -2]],
            duration_ms=[20, 40, 60, 80, 100])
        result, metadata, _ = sprites.transform(frames, options)
        alignment = metadata['column_alignment']
        self.assertEqual(alignment['origin'], [2, 2])
        self.assertEqual(alignment['padding'], [2, 2, 3, 1])
        self.assertEqual(alignment['padded_size'], [8, 6])
        self.assertEqual(alignment['frame_translations'], [[5, 0], [0, 3], [5, 0], [0, 3], [0, 3]])
        self.assertEqual(delays, [20, 40, 60, 80, 100])
        self.assertEqual(source['rectangles'], [[x*3, y*3, 3, 3] for x,y in cells])
        for frame, cell, translation in zip(result, cells, alignment['frame_translations']):
            expected = Image.new('RGBA', (8, 6))
            x, y = cell
            expected.paste(self.sheet.crop((x*3, y*3, x*3+3, y*3+3)), tuple(translation))
            self.assertEqual(frame.tobytes(), expected.tobytes())
        self.assertEqual(result[-1].tobytes(), result[-2].tobytes())

    def test_canvas_stable_across_selection_and_negative_offsets(self):
        frames, _, _, _, options = self.load(cells=[[0, 1]], column_offsets=[[-1, -2], [4, 3]])
        result, info, _ = sprites.transform(frames, options)
        self.assertEqual(result[0].size, (8, 8))
        self.assertEqual(info['column_alignment']['frame_translations'], [[0, 0]])
        self.assertEqual(result[0].crop((0, 0, 3, 3)).tobytes(), frames[0].tobytes())

    def test_zero_and_default_keep_identical_pixels(self):
        frames, _, _, _, options = self.load()
        old, _, _ = sprites.transform(frames, options)
        explicit, info, _ = sprites.transform(frames, {**options, 'column_offsets': [[0, 0], [0, 0]]})
        self.assertEqual(info['column_alignment']['origin'], [0, 0])
        self.assertEqual([f.tobytes() for f in old], [f.tobytes() for f in explicit])
        self.assertEqual([f.size for f in old], [f.size for f in explicit])

    def test_margin_checks_original_cells_not_padding(self):
        frames, _, _, _, options = self.load(column_offsets=[[-3, -3], [3, 3]], require_margin=1)
        with self.assertRaisesRegex(ValueError, 'require_margin'):
            sprites.transform(frames, options)
        self.sheet = Image.new('RGBA', (6, 6))
        for x, y in [(1, 1), (4, 1), (1, 4), (4, 4)]:
            self.sheet.putpixel((x, y), (1, 2, 3, 1))
        self.sheet.save(self.root / 'sheet.png')
        frames, _, _, _, options = self.load(column_offsets=[[-3, -3], [3, 3]], require_margin=1)
        sprites.transform(frames, options)

    def test_strict_types_and_bounded_offsets_before_decode(self):
        for value in (None, {}, [], [[0, 0]], [[0, 0], [0, 0], [0, 0]],
                      [[True, 0], [0, 0]], [[0.5, 0], [0, 0]],
                      [[0, '1'], [0, 0]], [[0], [0, 0]],
                      [[16385, 0], [0, 0]], [[0, -16385], [0, 0]]):
            with self.subTest(value=value), patch.object(PngImagePlugin.PngImageFile, 'load', side_effect=AssertionError('decoded')):
                with self.assertRaises(ValueError):
                    self.load(column_offsets=value)

    def test_frame_total_and_atlas_budgets_before_decode_or_canvas_allocation(self):
        cases = [
            ({'column_offsets': [[16384, 16384], [0, 0]]}, None),
            ({'column_offsets': [[1000, 1000], [0, 0]], 'cells': [[0, 0]] * 40}, None),
            ({'column_offsets': [[0, 0], [0, 0]], 'padding': 1}, ('MAX_SHEET_PIXELS', 40)),
        ]
        for changes, limit in cases:
            with self.subTest(changes=changes):
                patches = [patch.object(PngImagePlugin.PngImageFile, 'load', side_effect=AssertionError('decoded')),
                           patch.object(Image, 'new', side_effect=AssertionError('allocated'))]
                if limit:
                    patches.append(patch.object(sprites, *limit))
                from contextlib import ExitStack
                with ExitStack() as stack:
                    for item in patches:
                        stack.enter_context(item)
                    with self.assertRaises(ValueError):
                        self.load(**changes)

    def test_shared_transforms_after_correction(self):
        for changes in ({'scale': 2, 'sampling': 'smooth'},
                        {'crop': [False, 0, 3, 3]}, {'trim': 0},
                        {'trim': True, 'crop': [0, 0, 3, 3]}):
            with self.subTest(changes=changes), patch.object(PngImagePlugin.PngImageFile, 'load', side_effect=AssertionError('decoded')):
                with self.assertRaises(ValueError):
                    self.load(column_offsets=[[1, 0], [0, 0]], **changes)
        frames, _, _, _, options = self.load(crop=[1, 1, 1, 1])
        _, _, warnings = sprites.transform(frames, options)
        self.assertTrue(any('removes visible' in value for value in warnings))
        with self.assertRaisesRegex(ValueError, 'removes visible'):
            sprites.transform(frames, {**options, 'column_offsets': [[1, 0], [0, 0]]})
        # Shared trim retains relative placement; nearest scaling replicates bytes.
        frames, _, _, _, options = self.load(column_offsets=[[1, 0], [0, 0]], trim=True, scale=2)
        result, info, _ = sprites.transform(frames, options)
        translated, _, _ = sprites.transform(frames, {**options, 'trim': False, 'scale': 1})
        bounds = [f.getchannel('A').getbbox() for f in translated]
        box = (min(b[0] for b in bounds), min(b[1] for b in bounds),
               max(b[2] for b in bounds), max(b[3] for b in bounds))
        for original, actual in zip(translated, result):
            cut = original.crop(box)
            expected = cut.resize((cut.width*2, cut.height*2), Image.Resampling.NEAREST)
            self.assertEqual(expected.tobytes(), actual.tobytes())
        self.assertEqual(info['source_size'], [3, 3])
        self.assertEqual(info['column_alignment']['padded_size'], [4, 3])

    def test_explicit_crop_discards_only_transparent_border(self):
        frames, _, _, _, options = self.load(column_offsets=[[2, 0], [2, 0]], crop=[2, 0, 3, 3])
        result, info, _ = sprites.transform(frames, options)
        self.assertEqual([f.tobytes() for f in result], [f.tobytes() for f in frames])
        self.assertEqual(info['crop'], [2, 0, 3, 3])
        self.assertEqual(info['column_alignment']['frame_translations'], [[2, 0]] * 4)

    def test_transparent_cells_preserve_hidden_rgb_and_trim_keeps_canvas(self):
        self.sheet.putalpha(0)
        self.sheet.save(self.root / 'sheet.png')
        frames, _, _, _, options = self.load(column_offsets=[[-2, -1], [1, 2]], trim=True)
        result, info, warnings = sprites.transform(frames, options)
        self.assertEqual(info['crop'], [0, 0, 6, 6])
        self.assertTrue(any('completely transparent' in warning for warning in warnings))
        for original, actual, (x, y) in zip(frames, result, info['column_alignment']['frame_translations']):
            self.assertEqual(actual.crop((x, y, x+3, y+3)).tobytes(), original.tobytes())

    def test_export_timing_lossless_atlas_and_downstream_import(self):
        frames, delays, loop, source, options = self.load(
            column_offsets=[[-2, 1], [3, -2]], cells=[[1, 1], [0, 0], [0, 0]],
            duration_ms=[20, 40, 80], loop=0)
        out = self.root / 'out'
        plan = sprites.export(frames, delays, loop, source, options, out, dry_run=True)
        self.assertFalse(out.exists())
        report = sprites.export(frames, delays, loop, source, options, out)
        for key in ('transform', 'frame_layout', 'source', 'atlas_size'):
            self.assertEqual(plan[key], report[key])
        self.assertEqual(report['consecutive_duplicate_indices'], [2])
        self.assertEqual([r['duration_ms'] for r in report['frame_layout']], delays)
        self.assertEqual(report['preview']['duration_ms'], 140)
        self.assertEqual(report['preview']['loop'], 0)
        corrected, _, _ = sprites.transform(frames, options)
        with Image.open(out / 'atlas.png') as atlas:
            for record, expected in zip(report['frame_layout'], corrected):
                x, y, w, h = record['rect']
                self.assertEqual(atlas.crop((x, y, x+w, y+h)).tobytes(), expected.tobytes())
                with Image.open(out / record['file']) as png:
                    self.assertEqual(png.tobytes(), expected.tobytes())
        imported = layer_sprites.import_project(out / 'manifest.json', self.root / 'scene', dry_run=True)
        self.assertEqual(imported['source_duration_ms'], 140)
        self.assertEqual(imported['drawings'], 3)


if __name__ == '__main__':
    unittest.main()
