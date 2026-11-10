"""Non-destructive native-time source selections for GIF and PNG sprite layers."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import layer_gifs, layer_sprites, layers


class SourceTrimTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve(); self.path = self.root / 'scene.json'
        self.drawings = [Image.new('RGBA', (8, 8), color) for color in ('red', 'green', 'blue')]
        stream = io.BytesIO()
        self.drawings[0].save(stream, format='GIF', save_all=True, append_images=self.drawings[1:],
                             duration=[40, 80, 120], loop=0, disposal=2)
        (self.root / 'source.gif').write_bytes(stream.getvalue())
        atlas = Image.new('RGBA', (24, 8))
        for i, drawing in enumerate(self.drawings):
            atlas.paste(drawing, (8 * i, 0))
        atlas.save(self.root / 'atlas.png')
        for target in ('urllib.request.OpenerDirector.open', 'socket.create_connection'):
            guard = patch(target, side_effect=AssertionError('Network forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def scene(self, kind='gif', source_range=None, **changes):
        actor = {'id': 'actor', 'type': kind, 'size': [8, 8],
                 'source': 'source.gif' if kind == 'gif' else 'atlas.png'}
        if kind == 'sprites':
            actor.update(sampling='pixel', frames=[{'rect': [8 * i, 0, 8, 8], 'duration_ms': delay}
                                                  for i, delay in enumerate((40, 80, 120))])
        if source_range is not None:
            actor['source_range_ms'] = source_range
        return {'format': layers.FORMAT, 'schema_version': 1, 'width': 32, 'height': 32,
                'duration_ms': 480, 'fps': 50, 'loop': False, 'layers': [actor], **changes}

    def prepare(self, value):
        self.path.write_text(json.dumps(value), encoding='utf-8')
        return layers.prepare_scene(self.path)

    def test_strict_range_schema_before_asset_reads_and_only_for_animated_types(self):
        bad_values = [None, True, '20:120', [], [0], [0, 20, 40], [-10, 120], [0, 120010],
                      [True, 120], [0.0, 120], [float('nan'), 120], [0, float('inf')],
                      [5, 120], [0, 115], [120, 120], [120, 40], [0, 10]]
        for kind in ('gif', 'sprites'):
            for value in bad_values:
                scene = self.scene(kind); scene['layers'][0]['source_range_ms'] = value
                with self.subTest(kind=kind, value=value), \
                        patch.object(layers, 'read_assets', side_effect=AssertionError('No asset reads')):
                    with self.assertRaises(ValueError):
                        self.prepare(scene)
        for kind in ('image', 'rect'):
            scene = self.scene(); scene['layers'] = [
                {'id': 'still', 'type': kind, 'size': [8, 8], 'source_range_ms': [0, 40]}]
            if kind == 'image':
                scene['layers'][0]['source'] = 'atlas.png'
            with self.assertRaises(ValueError):
                self.prepare(scene)

    def test_normalization_keeps_original_and_no_trim_defaults_unchanged(self):
        for kind in ('gif', 'sprites'):
            value = self.scene(kind, [20, 160]); original = copy.deepcopy(value)
            normalized = layers.normalize_scene(value)
            self.assertEqual(value, original)
            self.assertEqual(normalized, layers.normalize_scene(normalized))
            untrimmed = self.prepare(self.scene(kind))
            self.assertNotIn('source_range_ms', untrimmed['scene']['layers'][0])
            for time, expected in ((0, 0), (40, 1), (120, 2), (240, 2)):
                self.assertEqual(layers.render_at(untrimmed, time)[1]['actor']['source_index'], expected)

    def test_exclusive_end_holds_the_last_included_drawing_not_the_next_one(self):
        for kind in ('gif', 'sprites'):
            prepared = self.prepare(self.scene(kind, [0, 120]))
            for time, expected in ((0, 0), (39, 0), (40, 1), (119, 1), (120, 1), (479, 1), (480, 1)):
                with self.subTest(kind=kind, time=time):
                    image, states = layers.render_at(prepared, time)
                    self.assertEqual(states['actor']['source_index'], expected)
                    self.assertEqual(image.getpixel((15, 15)), self.drawings[expected].getpixel((0, 0)))

    def test_partial_first_last_intervals_keep_exact_native_delays_and_loop_phase(self):
        for kind in ('gif', 'sprites'):
            for playback in ('once', 'loop'):
                scene = self.scene(kind, [20, 160]); scene['layers'][0]['playback'] = playback
                prepared = self.prepare(scene)
                expected = [(0, 0), (19.5, 0), (20, 1), (99.5, 1), (100, 2), (139.5, 2),
                            (140, 0 if playback == 'loop' else 2), (160, 1 if playback == 'loop' else 2)]
                for time, index in expected:
                    with self.subTest(kind=kind, playback=playback, time=time):
                        self.assertEqual(layers.render_at(prepared, time)[1]['actor']['source_index'], index)
                report = layer_gifs.selection_report(
                    prepared['assets']['source.gif'] if kind == 'gif' else layer_sprites.sequence(prepared['scene']['layers'][0]),
                    prepared['scene']['layers'][0], 20)
                self.assertEqual(report['source_range_ms'], [20, 160])
                self.assertEqual(report['selected_delays_ms'], [20, 80, 40])
                self.assertEqual(report['playback_duration_ms'], 140)

    def test_exact_start_and_short_selection_can_keep_one_existing_drawing(self):
        for kind in ('gif', 'sprites'):
            for playback in ('once', 'loop'):
                scene = self.scene(kind, [40, 60]); scene['layers'][0]['playback'] = playback
                prepared = self.prepare(scene)
                for time in (0, 19.9, 20, 100, 480):
                    self.assertEqual(layers.render_at(prepared, time)[1]['actor']['source_index'], 1)

    def test_non_grid_trim_loop_keeps_its_native_phase_without_stretching(self):
        for kind in ('gif', 'sprites'):
            scene = self.scene(kind, [30, 160]); scene['layers'][0]['playback'] = 'loop'
            prepared = self.prepare(scene)
            for time, expected in ((0, 0), (9.5, 0), (10, 1), (90, 2), (129.5, 2),
                                    (130, 0), (140, 1), (260, 0), (270, 1)):
                self.assertEqual(layers.render_at(prepared, time)[1]['actor']['source_index'], expected)

    def test_out_of_source_range_fails_before_resized_cache_allocation(self):
        for kind in ('gif', 'sprites'):
            scene = self.scene(kind, [220, 260])
            with patch.object(layers, 'fit_image', side_effect=AssertionError('No raster cache')):
                with self.assertRaisesRegex(ValueError, 'native animation duration'):
                    self.prepare(scene)

    def test_reused_source_has_independent_selection_and_layer_clocks(self):
        scene = self.scene('gif', [40, 120])
        second = copy.deepcopy(scene['layers'][0])
        second.update(id='later', in_ms=80, source_range_ms=[120, 240], playback='loop')
        scene['layers'].append(second)
        with patch.object(layer_gifs, 'decode', wraps=layer_gifs.decode) as decode:
            prepared = self.prepare(scene)
        self.assertEqual(decode.call_count, 1)
        self.assertIsNone(layers.render_at(prepared, 60)[1]['later'])
        for time in (80, 200, 400):
            states = layers.render_at(prepared, time)[1]
            self.assertEqual(states['actor']['source_index'], 1)
            self.assertEqual(states['later']['source_index'], 2)

    def test_trimmed_and_unsampled_drawings_are_distinguished_in_offline_plan(self):
        scene = self.scene('sprites', [30, 150], fps=25, duration_ms=80)
        # Original intervals: 0..40, 40..120, 120..240. Selection has 10,80,30 ms.
        self.prepare(scene); out = self.root / 'plan'
        with patch.object(layers, 'run_command', side_effect=AssertionError('No encoder')):
            report = layers.render_scene(self.path, out, dry_run=True)['sprite_timing']['actor']
        self.assertEqual(report['selected_source_indices'], [0, 1, 2])
        self.assertEqual(report['selected_delays_ms'], [10, 80, 30])
        self.assertEqual(report['sampled_source_indices'], [0, 1])
        self.assertEqual(report['unsampled_selected_drawings'], [2])
        self.assertEqual(report['trimmed_source_drawings'], [])
        self.assertEqual(report['omitted_source_drawings'], [2]); self.assertFalse(out.exists())
        prepared = self.prepare(self.scene('gif', [40, 120]))
        report = layer_gifs.timing_report(prepared['scene'], prepared['assets'])['actor']
        self.assertEqual(report['trimmed_source_drawings'], [0, 2])
        self.assertEqual(report['unsampled_selected_drawings'], [])
        self.assertEqual(report['source_delays_ms'], [40, 80, 120])

    def test_trim_preserves_full_source_snapshot_and_complete_rerender(self):
        from tools.verify_layered_scene import verify
        for kind, source in (('gif', 'source.gif'), ('sprites', 'atlas.png')):
            original = (self.root / source).read_bytes()
            self.prepare(self.scene(kind, [20, 120], duration_ms=160))
            out = self.root / f'render-{kind}'
            receipt = layers.render_scene(self.path, out)
            self.assertEqual(verify(out)['frames_reopened_and_matched'], 8)
            saved = layers.prepare_scene(out / 'editable/scene.json')
            actor = saved['scene']['layers'][0]
            self.assertEqual(actor['source_range_ms'], [20, 120])
            self.assertEqual(saved['assets'][actor['source']]['raw'], original)
            self.assertEqual((self.root / source).read_bytes(), original)
            self.assertEqual(receipt['samples'][-1]['layers']['actor']['source_index'], 1)

    def test_small_trim_does_not_bypass_full_source_decode_budget(self):
        self.path.write_text(json.dumps(self.scene('gif', [0, 20])), encoding='utf-8')
        with patch.object(layers, 'MAX_TOTAL_ASSET_PIXELS', 64):
            with self.assertRaises(ValueError):
                layers.prepare_scene(self.path)

    def test_trim_starts_after_disposal_dependencies_without_losing_the_composited_drawing(self):
        palette = [0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * (768 - 12)
        frames = []
        for color, box in ((1, (1, 1, 4, 4)), (2, (1, 1, 4, 4)), (3, (4, 4, 7, 7))):
            image = Image.new('P', (8, 8)); image.putpalette(palette)
            image.paste(color, box); frames.append(image)
        expected = {1: (0, 255, 0, 255), 2: (0, 0, 0, 0), 3: (255, 0, 0, 255)}
        source = self.root / 'source.gif'
        for disposal in (1, 2, 3):
            frames[0].save(source, save_all=True, append_images=frames[1:], duration=[40] * 3,
                           transparency=0, disposal=[1, disposal, 1], optimize=False)
            original = source.read_bytes()
            prepared = self.prepare(self.scene('gif', [80, 120]))
            frame, states = layers.render_at(prepared, 0)
            self.assertEqual(states['actor']['source_index'], 2)
            self.assertEqual(frame.getpixel((14, 14)), expected[disposal])
            self.assertEqual(frame.getpixel((17, 17)), (0, 0, 255, 255))
            saved = layers.save_bundle(prepared, self.root / f'disposal-{disposal}')
            reopened = layers.prepare_scene(saved)
            self.assertEqual(layers.render_at(reopened, 0)[0].tobytes(), frame.tobytes())
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
