"""Native GIF timing, alpha, resource safety and portable layered exports."""
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import layer_gifs, layers


def fixture(**changes):
    return {'format': layers.FORMAT, 'schema_version': 1, 'width': 32, 'height': 32,
            'fps': 50, 'duration_ms': 480, 'loop': False, 'layers': [
                {'id': 'actor', 'type': 'gif', 'source': 'actor.gif', 'size': [8, 8]}], **changes}


def gif_bytes(delays=(40, 80, 120), loop=0):
    frames = []
    palette = [0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * (768 - 12)
    for index in range(len(delays)):
        frame = Image.new('P', (8, 8), 0); frame.putpalette(palette)
        frame.paste(index % 3 + 1, (2, 2, 6, 6))
        frames.append(frame)
    stream = io.BytesIO()
    options = {} if loop is None else {'loop': loop}
    frames[0].save(stream, format='GIF', save_all=True, append_images=frames[1:],
                   duration=list(delays), transparency=0, disposal=2, optimize=False, **options)
    return stream.getvalue()


class GifLayerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.path = self.root / 'scene.json'
        self.asset = self.root / 'actor.gif'; self.asset.write_bytes(gif_bytes())
        for target in ('urllib.request.OpenerDirector.open', 'socket.create_connection'):
            guard = patch(target, side_effect=AssertionError('Network forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def prepare(self, value=None):
        self.path.write_bytes(layers.serialize_scene(value or fixture()))
        return layers.prepare_scene(self.path)

    def test_default_once_inheritance_and_strict_schema(self):
        value = fixture(); original = copy.deepcopy(value)
        normalized = layers.normalize_scene(value)
        self.assertEqual(value, original)
        self.assertEqual(normalized, layers.normalize_scene(normalized))
        self.assertEqual(normalized['layers'][0]['playback'], 'once')
        for bad in (True, None, 'reverse', 'auto', 2, []):
            value = fixture(); value['layers'][0]['playback'] = bad
            with self.subTest(playback=bad), self.assertRaises(ValueError):
                layers.normalize_scene(value)
        value = fixture(); value['layers'][0]['speed'] = 2
        with self.assertRaises(ValueError):
            layers.normalize_scene(value)
        value = fixture(); value['layers'][0]['type'] = 'image'; value['layers'][0]['playback'] = 'loop'
        with self.assertRaises(ValueError):
            layers.normalize_scene(value)

    def test_native_unequal_delays_and_exact_boundaries(self):
        prepared = self.prepare()
        expected = [(0, 0), (20, 0), (40, 1), (100, 1), (120, 2), (220, 2), (240, 2), (480, 2)]
        for time, index in expected:
            with self.subTest(time=time):
                frame, state = layers.render_at(prepared, time)
                self.assertEqual(state['actor']['source_index'], index)
                self.assertEqual(frame.getpixel((15, 15)), [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)][index])

    def test_explicit_loop_wraps_while_native_loop_is_ignored(self):
        value = fixture(); value['layers'][0]['playback'] = 'loop'
        self.asset.write_bytes(gif_bytes(loop=None))
        prepared = self.prepare(value)
        for time, expected in [(0, 0), (239, 2), (240, 0), (280, 1), (360, 2), (480, 0)]:
            self.assertEqual(layers.render_at(prepared, time)[1]['actor']['source_index'], expected)
        self.assertIsNone(prepared['assets']['actor.gif']['native_loop'])
        # Conversely, an infinitely repeating source does not override once.
        self.asset.write_bytes(gif_bytes(loop=0)); once = self.prepare()
        self.assertEqual(layers.render_at(once, 300)[1]['actor']['source_index'], 2)

    def test_non_grid_native_delays_keep_true_boundaries_and_loop_phase(self):
        self.asset.write_bytes(gif_bytes((30, 70, 110)))
        value = fixture(); value['layers'][0]['playback'] = 'loop'
        prepared = self.prepare(value)
        for time, index in [(0, 0), (20, 0), (30, 1), (40, 1), (99, 1),
                            (100, 2), (209, 2), (210, 0), (220, 0), (240, 1)]:
            with self.subTest(time=time):
                self.assertEqual(layers.render_at(prepared, time)[1]['actor']['source_index'], index)
        timing = layer_gifs.timing_report(prepared['scene'], prepared['assets'])['actor']
        self.assertEqual(timing['source_delays_ms'], [30, 70, 110])
        self.assertEqual(timing['source_duration_ms'], 210)

    def test_incremental_gif_disposal_accumulates_clears_or_restores(self):
        palette = [0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * (768 - 12)
        frames = []
        for color, box in [(1, (1, 1, 4, 4)), (2, (1, 1, 4, 4)), (3, (4, 4, 7, 7))]:
            frame = Image.new('P', (8, 8)); frame.putpalette(palette); frame.paste(color, box); frames.append(frame)
        expected = {1: (0, 255, 0, 255), 2: (0, 0, 0, 0), 3: (255, 0, 0, 255)}
        for disposal in (1, 2, 3):
            with self.subTest(disposal=disposal):
                frames[0].save(self.asset, save_all=True, append_images=frames[1:], duration=[40] * 3,
                               transparency=0, disposal=[1, disposal, 1], optimize=False)
                prepared = self.prepare(); decoded = prepared['assets']['actor.gif']['frames']
                self.assertEqual(decoded[1].getpixel((2, 2)), (0, 255, 0, 255))
                self.assertEqual(decoded[2].getpixel((2, 2)), expected[disposal])
                self.assertEqual(decoded[2].getpixel((5, 5)), (0, 0, 255, 255))

    def test_each_layer_has_its_own_clock_and_shared_source_is_decoded_once(self):
        value = fixture(); second = copy.deepcopy(value['layers'][0])
        second.update(id='later', in_ms=80, playback='loop'); value['layers'].append(second)
        with patch.object(layer_gifs, 'decode', wraps=layer_gifs.decode) as decode:
            prepared = self.prepare(value)
        self.assertEqual(decode.call_count, 1)
        states = layers.render_at(prepared, 80)[1]
        self.assertEqual(states['actor']['source_index'], 1)
        self.assertEqual(states['later']['source_index'], 0)
        self.assertIsNone(layers.render_at(prepared, 60)[1]['later'])

    def test_transparent_background_native_disposal_and_opacity_are_preserved(self):
        value = fixture(); value['layers'].insert(0,
            {'id': 'back', 'type': 'rect', 'size': [32, 32], 'fill': '#ffffff'})
        value['layers'][1]['keyframes'] = [{'at': 0, 'opacity': .5}, {'at': 1}]
        prepared = self.prepare(value)
        for time, expected in [(0, (255, 127, 127)), (40, (127, 255, 127)), (120, (127, 127, 255))]:
            frame, _ = layers.render_at(prepared, time)
            self.assertEqual(frame.getpixel((15, 15))[:3], expected)
            self.assertEqual(frame.getpixel((12, 12)), (255, 255, 255, 255))
            isolated, _ = layers.render_at(prepared, time, only_layer='actor')
            self.assertEqual(isolated.getpixel((12, 12))[3], 0)

    def test_visibility_transforms_and_cached_drawings(self):
        value = fixture(); value['layers'][0].update(in_ms=80, out_ms=320,
            keyframes=[{'at': 0, 'x': .25, 'zoom': 2}, {'at': 1}])
        prepared = self.prepare(value)
        with patch.object(layers, 'fit_image', side_effect=AssertionError('Rasters must be cached')):
            active, state = layers.render_at(prepared, 120)
            self.assertEqual(state['actor']['source_index'], 1)
            self.assertEqual(active.getpixel((8, 16)), (0, 255, 0, 255))
            self.assertIsNone(layers.render_at(prepared, 320)[0].getchannel('A').getbbox())
        self.assertTrue(all(r.mode == 'RGBa' for r in prepared['gif_rasters']['actor']))
        self.assertIs(prepared['gif_rasters']['actor'][0], prepared['rasters']['actor'])

    def test_plan_reports_skipped_drawings_instead_of_claiming_new_poses(self):
        self.asset.write_bytes(gif_bytes(delays=(20, 20, 20, 20)))
        self.prepare(fixture(fps=25, duration_ms=80))
        out = self.root / 'plan'
        with patch.object(layers, 'run_command', side_effect=AssertionError('Offline plan only')):
            plan = layers.render_scene(self.path, out, dry_run=True)
        timing = plan['gif_timing']['actor']
        self.assertEqual(timing['sampled_source_indices'], [0, 2])
        self.assertEqual(timing['omitted_source_drawings'], [1, 3])
        self.assertEqual(timing['source_delays_ms'], [20] * 4)
        self.assertEqual(plan['api_calls'], 0); self.assertFalse(out.exists())

    def test_image_layers_stay_still_and_cannot_silently_accept_gif(self):
        value = fixture(); value['layers'][0]['type'] = 'image'
        with self.assertRaisesRegex(ValueError, 'use a gif layer'):
            self.prepare(value)
        Image.new('RGBA', (8, 8), 'red').save(self.asset, format='PNG')
        with self.assertRaisesRegex(ValueError, 'not a GIF'):
            self.prepare()

    def test_byte_decoded_frame_duration_and_cache_budgets(self):
        self.prepare()
        for name, module in [('MAX_ASSET_BYTES', layers), ('MAX_TOTAL_ASSET_BYTES', layers),
                             ('MAX_ASSET_PIXELS', layers), ('MAX_TOTAL_ASSET_PIXELS', layers),
                             ('MAX_FRAMES', layer_gifs), ('MAX_DURATION_MS', layer_gifs),
                             ('MAX_CACHED_PIXELS', layer_gifs)]:
            with self.subTest(limit=name), patch.object(module, name, 1), \
                    patch.object(layers, 'fit_image', side_effect=AssertionError('No raster allocation')):
                with self.assertRaises(ValueError):
                    layers.prepare_scene(self.path)
        for delays in ((0, 40), (10, 40), (60010, 40), (60000, 60000, 20)):
            self.asset.write_bytes(gif_bytes(delays=delays))
            with self.subTest(delays=delays), self.assertRaises(ValueError):
                layers.prepare_scene(self.path)

    def test_decoded_budget_rejects_before_pillow_opens_animation(self):
        raw = self.asset.read_bytes()
        with patch('PIL.Image.open', side_effect=AssertionError('No allocation')):
            with self.assertRaises(ValueError):
                layer_gifs.decode(raw, 64, 128)  # Three full 8×8 drawings exceed 128.
            with self.assertRaises(ValueError):
                layer_gifs.decode(raw, 63, 1024)

    def test_fixed_canvas_expansion_is_rejected_before_decode(self):
        raw = bytearray(self.asset.read_bytes()); index = raw.index(b'\x2c', 13 + 768)
        raw[index + 1:index + 3] = (8).to_bytes(2, 'little')
        with patch('PIL.Image.open', side_effect=AssertionError('No allocation')):
            with self.assertRaisesRegex(ValueError, 'fixed logical canvas'):
                layer_gifs.decode(bytes(raw), 1000, 1000)

    def test_total_decoded_pixels_include_every_gif_drawing(self):
        value = fixture(); value['layers'].append(
            {'id': 'other', 'type': 'gif', 'source': 'second.gif', 'size': [8, 8]})
        (self.root / 'second.gif').write_bytes(self.asset.read_bytes())
        self.path.write_bytes(layers.serialize_scene(value))
        with patch.object(layers, 'MAX_TOTAL_ASSET_PIXELS', 300), \
                patch.object(layers, 'fit_image', side_effect=AssertionError('No raster allocation')):
            with self.assertRaisesRegex(ValueError, 'decoded pixel budget'):
                layers.prepare_scene(self.path)

    def test_portable_scene_snapshots_unique_gif_and_reopens_every_frame(self):
        value = fixture(); value['layers'].append({**value['layers'][0], 'id': 'second', 'playback': 'loop'})
        prepared = self.prepare(value); raw = self.asset.read_bytes(); original = self.path.read_bytes()
        saved = layers.save_bundle(prepared, self.root / 'portable')
        self.assertEqual(len(list((saved.parent / 'assets').iterdir())), 1)
        relocated = self.root / 'relocated'; saved.parent.rename(relocated)
        reopened = layers.prepare_scene(relocated / 'scene.json')
        for time in range(0, 481, 20):
            self.assertEqual(layers.render_at(prepared, time)[0].tobytes(), layers.render_at(reopened, time)[0].tobytes())
        self.assertEqual(raw, self.asset.read_bytes()); self.assertEqual(original, self.path.read_bytes())
        asset = next((relocated / 'assets').iterdir()); asset.write_bytes(gif_bytes((60, 60, 120)))
        with self.assertRaisesRegex(ValueError, 'Asset changed'):
            layers.prepare_scene(relocated / 'scene.json')

    def test_missing_escape_and_hash_tampering_fail_without_output(self):
        value = fixture(); value['layers'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Asset changed'):
            self.prepare(value)
        value = fixture(); value['layers'][0]['source'] = '../actor.gif'
        with self.assertRaises(ValueError):
            self.prepare(value)
        self.asset.unlink()
        with self.assertRaises(FileNotFoundError):
            self.prepare()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Media tools required')
    def test_real_export_complete_inventory_reopen_and_source_immutability(self):
        from tools.verify_layered_scene import verify
        self.prepare(); source = self.asset.read_bytes(); out = self.root / 'render'
        receipt = layers.render_scene(self.path, out)
        self.assertEqual(receipt['gif_timing']['actor']['source_delays_ms'], [40, 80, 120])
        self.assertEqual(receipt['samples'][2]['layers']['actor']['source_index'], 1)
        self.assertEqual(receipt['samples'][-1]['layers']['actor']['source_index'], 2)
        self.assertEqual(receipt['layer_previews']['actor']['status'], 'visible')
        self.assertEqual(verify(out)['frames_reopened_and_matched'], 24)
        self.assertEqual(self.asset.read_bytes(), source)
        self.assertEqual(receipt['api_calls'], 0)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Media tools required')
    def test_verifier_requires_gif_asset_once_even_when_two_layers_share_it(self):
        from tools.verify_layered_scene import expected_outputs, verify
        value = fixture(); value['layers'].append({**value['layers'][0], 'id': 'second'})
        self.prepare(value); out = self.root / 'shared-render'
        receipt = layers.render_scene(self.path, out)
        saved = layers.load_scene(out / 'editable' / 'scene.json')
        assets = [name for name in expected_outputs(saved) if name.startswith('editable/assets/')]
        self.assertEqual(len(assets), 1)
        self.assertEqual(verify(out)['frames_reopened_and_matched'], 24)
        receipt['outputs'].pop(assets[0]); (out / 'receipt.json').write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'inventory'):
            verify(out)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Media tools required')
    def test_source_change_during_export_prevents_publication(self):
        self.prepare(); out = self.root / 'changed-source'
        original_render = layers.render_at
        changed = False
        def render_and_change(*args, **kwargs):
            nonlocal changed
            result = original_render(*args, **kwargs)
            if not changed:
                self.asset.write_bytes(gif_bytes((60, 60, 120))); changed = True
            return result
        with patch.object(layers, 'render_at', side_effect=render_and_change):
            with self.assertRaisesRegex(ValueError, 'Source assets changed'):
                layers.render_scene(self.path, out)
        self.assertFalse(out.exists())

    def test_static_gif_is_accepted_without_claiming_new_motion(self):
        self.asset.write_bytes(gif_bytes((80,)))
        prepared = self.prepare()
        timing = layer_gifs.timing_report(prepared['scene'], prepared['assets'])['actor']
        self.assertEqual(timing['source_drawings'], 1)
        self.assertEqual(timing['sampled_source_indices'], [0])
        self.assertEqual(layers.render_at(prepared, 0)[0].tobytes(), layers.render_at(prepared, 460)[0].tobytes())

    def test_source_kind_cannot_be_reused_with_different_decoder(self):
        value = fixture(); value['layers'].append({'id': 'still', 'type': 'image', 'source': 'actor.gif', 'size': [8, 8]})
        with self.assertRaisesRegex(ValueError, 'both image and GIF'):
            self.prepare(value)


class ExampleTests(unittest.TestCase):
    def test_example_reuses_all_native_astronaut_drawings_and_has_final_hold(self):
        root = Path(__file__).resolve().parents[1]
        prepared = layers.prepare_scene(root / 'examples' / 'gif-layer' / 'scene.json')
        source = prepared['assets']['astronaut.gif']
        self.assertEqual(source['raw'], (root / '.agents/skills/gif-cinema/assets/example/shot-01.gif').read_bytes())
        timing = layer_gifs.timing_report(prepared['scene'], prepared['assets'])['astronaut']
        self.assertEqual(timing['source_delays_ms'], [160] * 16)
        self.assertEqual(timing['omitted_source_drawings'], [])
        last, states = layers.render_at(prepared, 3180)
        self.assertEqual(states['astronaut']['source_index'], 15)
        self.assertEqual(last.tobytes(), layers.render_at(prepared, 2560)[0].tobytes())


if __name__ == '__main__':
    unittest.main()
