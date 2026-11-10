"""PNG atlas playback must keep RGBA, pose coordinates and explicit timing."""
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import layer_gifs, layer_sprites, layers, sprites


def fixture(**changes):
    return {'format': layers.FORMAT, 'schema_version': 1, 'width': 32, 'height': 32,
            'fps': 50, 'duration_ms': 320, 'loop': False, 'layers': [
                {'id': 'actor', 'type': 'sprites', 'source': 'atlas.png', 'size': [8, 8],
                 'sampling': 'pixel', 'frames': [{'rect': [0, 0, 8, 8], 'duration_ms': 60},
                                                {'rect': [8, 0, 8, 8], 'duration_ms': 100}]}], **changes}


class SpriteLayerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve(); self.path = self.root / 'scene.json'
        self.atlas = self.root / 'atlas.png'
        self.first = Image.new('RGBA', (8, 8), (255, 0, 0, 64))
        self.second = Image.new('RGBA', (8, 8), (0, 0, 255, 128))
        sheet = Image.new('RGBA', (16, 8)); sheet.paste(self.first, (0, 0)); sheet.paste(self.second, (8, 0)); sheet.save(self.atlas)
        for target in ('urllib.request.OpenerDirector.open', 'socket.create_connection'):
            guard = patch(target, side_effect=AssertionError('Network forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def prepare(self, value=None):
        self.path.write_bytes(layers.serialize_scene(value or fixture()))
        return layers.prepare_scene(self.path)

    def test_normalization_is_strict_and_does_not_change_authored_records(self):
        value = fixture(); before = copy.deepcopy(value)
        scene = layers.normalize_scene(value)
        self.assertEqual(value, before); self.assertEqual(scene, layers.normalize_scene(scene))
        self.assertEqual(scene['layers'][0]['playback'], 'once')
        for field, bad in [('frames', []), ('frames', [{}]), ('frames', 'atlas.json'),
                           ('sampling', 'cubic'), ('sampling', True), ('playback', 'reverse')]:
            value = fixture(); value['layers'][0][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                layers.normalize_scene(value)

    def test_bad_coordinates_timing_sizes_and_excessive_records_fail_preflight(self):
        bad_rects = ([0, 0, 0, 8], [-1, 0, 8, 8], [0, 0, 8.5, 8], [0, 0, True, 8],
                     [0, 0, 8], [0, 0, 4096, 4096], [float('nan'), 0, 8, 8], [16385, 0, 8, 8])
        for rect in bad_rects:
            value = fixture(); value['layers'][0]['frames'][0]['rect'] = rect
            with self.subTest(rect=rect), self.assertRaises(ValueError):
                layers.normalize_scene(value)
        for delay in (0, 10, 25, 60010, True, 30.0, float('inf')):
            value = fixture(); value['layers'][0]['frames'][0]['duration_ms'] = delay
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                layers.normalize_scene(value)
        for records in ([{'rect': [0, 0, 8, 8], 'duration_ms': 20}] * 257,
                        [{'rect': [0, 0, 8, 8], 'duration_ms': 60000}] * 3,
                        [{'rect': [0, 0, 8, 8], 'duration_ms': 20}, {'rect': [0, 0, 7, 8], 'duration_ms': 20}],
                        [{'rect': [0, 0, 8, 8], 'duration_ms': 20, 'expression': 'ignored?'}]):
            value = fixture(); value['layers'][0]['frames'] = records
            with self.assertRaises(ValueError):
                layers.normalize_scene(value)

    def test_partial_alpha_and_native_delay_boundaries_survive_atlas_playback(self):
        prepared = self.prepare()
        for time, index, rgba in [(0, 0, (255, 0, 0, 64)), (59, 0, (255, 0, 0, 64)),
                                  (60, 1, (0, 0, 255, 128)), (160, 1, (0, 0, 255, 128)),
                                  (319, 1, (0, 0, 255, 128))]:
            frame, states = layers.render_at(prepared, time)
            self.assertEqual(states['actor']['source_index'], index)
            self.assertEqual(frame.getpixel((15, 15)), rgba)
        self.assertEqual(prepared['assets']['atlas.png']['raw'], self.atlas.read_bytes())

    def test_loop_and_two_independent_atlas_selections_use_one_source(self):
        value = fixture(); second = copy.deepcopy(value['layers'][0])
        second.update(id='later', in_ms=80, playback='loop', frames=list(reversed(second['frames'])))
        value['layers'].append(second)
        prepared = self.prepare(value)
        self.assertEqual(len(prepared['assets']), 1)
        self.assertEqual(layers.render_at(prepared, 80)[1]['later']['source_index'], 0)
        self.assertEqual(layers.render_at(prepared, 180)[1]['later']['source_index'], 1)
        self.assertEqual(layers.render_at(prepared, 240)[1]['later']['source_index'], 0)
        self.assertEqual(layers.render_at(prepared, 240)[1]['actor']['source_index'], 1)

    def test_pixel_sampling_does_not_mix_neighboring_atlas_cells(self):
        value = fixture(); value['layers'][0]['size'] = [16, 16]
        prepared = self.prepare(value)
        for time, expected in [(0, (255, 0, 0, 64)), (60, (0, 0, 255, 128))]:
            frame, _ = layers.render_at(prepared, time)
            colors = {frame.getpixel((x, y)) for x in range(frame.width) for y in range(frame.height)}
            self.assertEqual(colors, {(0, 0, 0, 0), expected})

    def test_pixel_sampling_preserves_nonprimary_colors_with_partial_alpha(self):
        for rgba in ((100, 150, 200, 64), (1, 77, 201, 1), (237, 19, 88, 127)):
            Image.new('RGBA', (16, 8), rgba).save(self.atlas)
            prepared = self.prepare()
            self.assertEqual(prepared['gif_rasters']['actor'][0].mode, 'RGBA')
            self.assertEqual(layers.render_at(prepared, 0)[0].getpixel((15, 15)), rgba)

    def test_sprite_budget_counts_crop_work_and_combined_gif_cache_before_cropping(self):
        self.prepare()
        for module, name in [(layer_sprites, 'MAX_CROP_PIXEL_FRAMES'), (layer_gifs, 'MAX_CACHED_PIXELS')]:
            with patch.object(module, name, 1), patch('PIL.Image.Image.crop', side_effect=AssertionError('No crop allocation')):
                with self.assertRaises(ValueError):
                    layers.prepare_scene(self.path)
        scene = layers.normalize_scene(fixture())
        prepared = self.prepare()
        # The sprite cache alone is 128 pixels. GIF and sprite caches share one cap.
        with patch.object(layer_gifs, 'MAX_CACHED_PIXELS', 200):
            with self.assertRaisesRegex(ValueError, 'combined cached'):
                layer_sprites.budgets(scene, prepared['assets'], 100)

    def test_out_of_bounds_rect_fails_before_any_crop(self):
        value = fixture(); value['layers'][0]['frames'][1]['rect'] = [9, 0, 8, 8]
        self.path.write_bytes(layers.serialize_scene(value))
        with patch('PIL.Image.Image.crop', side_effect=AssertionError('No crop allocation')):
            with self.assertRaisesRegex(ValueError, 'rectangle exceeds'):
                layers.prepare_scene(self.path)

    def test_png_only_and_orientation_is_never_silently_reinterpreted(self):
        for format in ('JPEG', 'WEBP'):
            Image.new('RGB', (16, 8), 'red').save(self.atlas, format=format)
            with self.subTest(format=format), self.assertRaisesRegex(ValueError, 'PNG atlas'):
                self.prepare()
        exif = Image.Exif(); exif[274] = 6
        Image.new('RGBA', (16, 8), 'red').save(self.atlas, format='PNG', exif=exif)
        with self.assertRaisesRegex(ValueError, 'EXIF orientation'):
            self.prepare()
        value = fixture(); value['layers'].insert(0, {'id': 'still', 'type': 'image', 'source': 'atlas.png', 'size': [8, 8]})
        with self.assertRaisesRegex(ValueError, 'EXIF orientation'):
            self.prepare(value)

    def test_image_and_sprite_layers_can_share_small_png_without_order_dependence(self):
        value = fixture(); value['layers'].append({'id': 'still', 'type': 'image', 'source': 'atlas.png', 'size': [8, 8]})
        for order in (value['layers'], list(reversed(value['layers']))):
            prepared = self.prepare(fixture(layers=order))
            self.assertEqual(len(prepared['assets']), 1)
            self.assertEqual(layers.render_at(prepared, 0)[1]['actor']['source_index'], 0)

    def test_shared_png_cannot_bypass_the_older_still_image_pixel_limit(self):
        value = fixture(); value['layers'].append({'id': 'still', 'type': 'image', 'source': 'atlas.png', 'size': [8, 8]})
        for order in (value['layers'], list(reversed(value['layers']))):
            self.path.write_bytes(layers.serialize_scene(fixture(layers=order)))
            with patch.object(layers, 'MAX_ASSET_PIXELS', 100):
                with self.assertRaisesRegex(ValueError, 'decoded pixel budget'):
                    layers.prepare_scene(self.path)

    def test_plan_reports_skips_and_keeps_repeated_authored_drawings(self):
        value = fixture(fps=25, duration_ms=80)
        value['layers'][0]['frames'] = [{'rect': [0, 0, 8, 8], 'duration_ms': 20}] * 4
        self.prepare(value)
        out = self.root / 'plan'; report = layers.render_scene(self.path, out, dry_run=True)
        timing = report['sprite_timing']['actor']
        self.assertEqual(timing['source_drawings'], 4)
        self.assertEqual(timing['sampled_source_indices'], [0, 2])
        self.assertEqual(timing['omitted_source_drawings'], [1, 3])
        self.assertFalse(out.exists()); self.assertEqual(report['api_calls'], 0)

    def test_sprite_export_manifest_can_feed_layers_without_a_gif_roundtrip(self):
        exported = sprites.export([self.first, self.second], [60, 100], None,
            {'kind': 'test-drawings'}, {'columns': 2, 'padding': 1}, self.root / 'sprites')
        value = fixture(); value['layers'][0].update(source='sprites/atlas.png',
            sha256=exported['files_sha256']['atlas.png'],
            frames=[{'rect': record['rect'], 'duration_ms': record['duration_ms']} for record in exported['frame_layout']])
        prepared = self.prepare(value)
        self.assertEqual(layers.render_at(prepared, 0)[0].getpixel((15, 15)), (255, 0, 0, 64))
        self.assertEqual(layers.render_at(prepared, 60)[0].getpixel((15, 15)), (0, 0, 255, 128))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Media tools required')
    def test_real_export_reopen_complete_inventory_and_alpha_pngs(self):
        from tools.verify_layered_scene import verify
        self.prepare(); raw = self.atlas.read_bytes(); out = self.root / 'render'
        receipt = layers.render_scene(self.path, out)
        self.assertEqual(receipt['sprite_timing']['actor']['source_delays_ms'], [60, 100])
        self.assertEqual(verify(out)['frames_reopened_and_matched'], 16)
        with Image.open(out / 'frames/0000.png') as frame:
            self.assertEqual(frame.getpixel((15, 15)), (255, 0, 0, 64))
        self.assertEqual(self.atlas.read_bytes(), raw)
        saved = layers.prepare_scene(out / 'editable/scene.json')
        self.assertEqual(len(saved['assets']), 1)
        self.assertEqual(layers.render_at(saved, 0)[0].tobytes(), layers.render_at(layers.prepare_scene(self.path), 0)[0].tobytes())
        # The atlas remains mandatory even if a forged receipt omits it.
        asset = next(name for name in receipt['outputs'] if name.startswith('editable/assets/'))
        receipt['outputs'].pop(asset)
        (out / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'inventory is incomplete'):
            verify(out)


class SpriteImportTests(unittest.TestCase):
    setUp = SpriteLayerTests.setUp

    def manifest(self, delays=(60, 100)):
        directory = self.root / 'packed'
        report = sprites.export([self.first, self.second], list(delays), None,
            {'kind': 'authored-test-drawings'}, {'columns': 2, 'padding': 1}, directory)
        return directory / 'manifest.json', report

    def write_manifest(self, path, report):
        path.write_text(json.dumps(report), encoding='utf-8')

    def test_import_uses_atlas_rgba_even_when_lossy_preview_and_frame_files_are_absent(self):
        path, report = self.manifest()
        (path.parent / 'animation.gif').unlink(); shutil.rmtree(path.parent / 'frames')
        out = self.root / 'imported'
        result = layer_sprites.import_project(path, out, width=32, height=32)
        self.assertEqual(result['api_calls'], 0)
        self.assertEqual(result['drawings'], 2)
        self.assertEqual(result['final_hold_ms'], 0)
        prepared = layers.prepare_scene(out / 'scene.json')
        self.assertEqual(layers.render_at(prepared, 0)[0].getpixel((16, 16)), (255, 0, 0, 64))
        self.assertEqual(layers.render_at(prepared, 60)[0].getpixel((16, 16)), (0, 0, 255, 128))
        self.assertEqual(prepared['assets'][prepared['scene']['layers'][0]['source']]['raw'], (path.parent / 'atlas.png').read_bytes())
        receipt = json.loads((out / 'import-receipt.json').read_text())
        self.assertEqual(receipt['scene'], 'scene.json')
        self.assertEqual(receipt['drawing_rgba_sha256'], [r['rgba_sha256'] for r in report['frame_layout']])

    def test_dry_run_is_offline_writes_nothing_and_reports_final_hold_rounding(self):
        path, _ = self.manifest((30, 80)); out = self.root / 'planned'
        with patch.object(layers, 'run_command', side_effect=AssertionError('No encoder')):
            result = layer_sprites.import_project(path, out, width=32, height=32, dry_run=True)
        self.assertFalse(out.exists())
        self.assertEqual(result['status'], 'planned')
        self.assertEqual(result['source_duration_ms'], 110)
        self.assertEqual(result['duration_ms'], 120)
        self.assertEqual(result['final_hold_ms'], 10)
        with self.assertRaisesRegex(ValueError, 'Exact repeat'):
            layer_sprites.import_project(path, out, repeat=True)
        self.assertFalse(out.exists())

    def test_explicit_repeat_and_pixel_sampling_are_saved(self):
        path, _ = self.manifest(); out = self.root / 'repeat'
        layer_sprites.import_project(path, out, width=32, height=32, repeat=True)
        prepared = layers.prepare_scene(out / 'scene.json')
        self.assertTrue(prepared['scene']['loop'])
        self.assertEqual(prepared['scene']['layers'][0]['playback'], 'loop')
        self.assertEqual(prepared['scene']['layers'][0]['sampling'], 'pixel')
        self.assertEqual(layers.render_at(prepared, 160)[1]['actor']['source_index'], 0)

    def test_shortest_one_pose_import_has_two_output_frames_without_hidden_loop_pause(self):
        for fps, delay in ((50, 20), (25, 40)):
            directory = self.root / f'single-{fps}'
            sprites.export([self.first], [delay], None, {'kind': 'one-authored-pose'},
                           {'columns': 1, 'padding': 1}, directory)
            path = directory / 'manifest.json'
            for repeat in (False, True):
                out = self.root / f'import-{fps}-{repeat}'
                result = layer_sprites.import_project(path, out, width=32, height=32, fps=fps, repeat=repeat)
                self.assertEqual(result['duration_ms'], delay * 2)
                self.assertEqual(result['final_hold_ms'], 0 if repeat else delay)
                self.assertEqual(result['source_cycles'], 2 if repeat else 1)
                scene = layers.prepare_scene(out / 'scene.json')['scene']
                self.assertEqual(scene['duration_ms'] * fps // 1000, 2)

    def test_manifest_shape_counts_and_hashes_fail_before_output(self):
        path, report = self.manifest()
        modifications = [lambda r: r.update(schema_version=True), lambda r: r.update(frame_count=3),
            lambda r: r.update(duration_ms=170), lambda r: r.update(atlas_size=[True, 8]),
            lambda r: r.update(atlas_size=[1, 1]), lambda r: r.update(files_sha256={}),
            lambda r: r['files_sha256'].update({'atlas.png': '0' * 64}),
            lambda r: r['frame_layout'][0].update(index=1),
            lambda r: r['frame_layout'][0].update(rgba_sha256='0' * 64),
            lambda r: r['frame_layout'][0].update(rgba_sha256='oops'),
            lambda r: r['frame_layout'][0].update(rect=[100, 0, 8, 8])]
        out = self.root / 'bad'
        for change in modifications:
            modified = copy.deepcopy(report); change(modified); self.write_manifest(path, modified)
            with self.subTest(modified=modified), self.assertRaises(ValueError):
                layer_sprites.import_project(path, out, width=32, height=32)
            self.assertFalse(out.exists())

    def test_duplicate_keys_and_unsafe_atlas_paths_are_rejected(self):
        path, report = self.manifest(); out = self.root / 'bad'
        for raw in ('{"schema_version":1,"schema_version":1}', '[]', '\ufeff{'):
            path.write_text(raw, encoding='utf-8')
            with self.assertRaises(ValueError):
                layer_sprites.import_project(path, out)
        for name in ('../atlas.png', '/tmp/atlas.png', 'https://example.com/a.png', 'a\\b.png'):
            self.write_manifest(path, {**report, 'atlas': name})
            with self.subTest(name=name), self.assertRaises(ValueError):
                layer_sprites.import_project(path, out)
        self.assertFalse(out.exists())

    def test_crop_and_cache_budgets_apply_before_png_decode_or_rgba_allocation(self):
        path, _ = self.manifest()
        for module, name in [(layer_sprites, 'MAX_CROP_PIXEL_FRAMES'), (layer_gifs, 'MAX_CACHED_PIXELS')]:
            with patch.object(module, name, 1), \
                    patch('PIL.PngImagePlugin.PngImageFile.load', side_effect=AssertionError('No PNG decode')), \
                    patch('PIL.Image.Image.convert', side_effect=AssertionError('No RGBA allocation')):
                with self.assertRaises(ValueError):
                    layer_sprites.import_project(path, self.root / 'bad', width=32, height=32)

    def test_import_refuses_existing_destination_without_changing_sources(self):
        path, _ = self.manifest(); original = path.read_bytes()
        atlas = (path.parent / 'atlas.png').read_bytes()
        with self.assertRaisesRegex(ValueError, 'new directory'):
            layer_sprites.import_project(path, path.parent, width=32, height=32)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual((path.parent / 'atlas.png').read_bytes(), atlas)

    def test_source_change_during_import_prevents_publication(self):
        path, _ = self.manifest(); out = self.root / 'changed'
        original = layer_sprites.budgets
        def mutate(*args):
            result = original(*args)
            path.write_text('{}')
            return result
        with patch.object(layer_sprites, 'budgets', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'manifest changed'):
                layer_sprites.import_project(path, out, width=32, height=32)
        self.assertFalse(out.exists())

    def test_cli_import_produces_a_portable_scene_without_media_tools(self):
        path, _ = self.manifest(); out = self.root / 'command'
        result = subprocess.run([sys.executable, '-m', 'gif_cinema.layers', 'import-sprites', str(path),
            '--out', str(out), '--width', '32', '--height', '32'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'saved')
        self.assertTrue((out / 'scene.json').is_file())


class SpriteExampleTests(unittest.TestCase):
    def assert_portable_example_equal(self, expected, actual):
        scenes = []
        for prepared in (expected, actual):
            scene = copy.deepcopy(prepared['scene'])
            for layer in scene['layers']:
                if layer['type'] == 'sprites':
                    asset = prepared['assets'][layer['source']]
                    self.assertEqual(layer['sha256'], layers.digest(asset['raw']))
                    # PNG encoders can write different lossless byte streams.
                    # Verify each file pin, then compare authored scene meaning
                    # and exact decoded pixels rather than compressed PNG bytes.
                    del layer['sha256']
            scenes.append(scene)
        self.assertEqual(*scenes)
        self.assertEqual(set(expected['assets']), set(actual['assets']))
        for source in expected['assets']:
            before = expected['assets'][source]['rgba']
            after = actual['assets'][source]['rgba']
            self.assertEqual(before.size, after.size)
            self.assertEqual(before.tobytes(), after.tobytes())
        self.assertEqual(layer_sprites.timing_report(expected['scene']),
                         layer_sprites.timing_report(actual['scene']))

    def test_original_example_is_reproducible_and_not_pinned_to_author_machine(self):
        from tools.make_sprite_layer_example import create
        root = Path(__file__).resolve().parents[1]
        authored = root / 'examples/sprite-layer/scene.json'
        self.assertNotIn('text_renderer', json.loads(authored.read_text(encoding='utf-8')))
        with tempfile.TemporaryDirectory() as tmp:
            generated = create(Path(tmp).resolve() / 'example')
            expected = layers.prepare_scene(authored)
            actual = layers.prepare_scene(generated)
            self.assert_portable_example_equal(expected, actual)
            self.assertEqual(len(actual['assets']), 1)
            report = layer_sprites.timing_report(actual['scene'])
            self.assertEqual(report['left']['sampled_source_indices'], list(range(8)))
            self.assertEqual(report['right']['source_duration_ms'], 640)

    def test_lossless_png_reencoding_keeps_pixels_but_never_bypasses_source_pins(self):
        from tools.make_sprite_layer_example import create
        root = Path(__file__).resolve().parents[1]
        expected = layers.prepare_scene(root / 'examples/sprite-layer/scene.json')
        with tempfile.TemporaryDirectory() as tmp:
            generated = create(Path(tmp).resolve() / 'example')
            atlas = generated.parent / 'source/atlas.png'
            original_hash = layers.digest(atlas.read_bytes())
            with Image.open(atlas) as encoded:
                pixels = encoded.convert('RGBA')
            pixels.save(atlas, compress_level=0)
            self.assertNotEqual(layers.digest(atlas.read_bytes()), original_hash)
            # A different encoding is still a source change until explicitly
            # repinned. The normal loader must reject the stale byte hash.
            with self.assertRaisesRegex(ValueError, 'Asset changed: source/atlas.png'):
                layers.prepare_scene(generated)

            def repin():
                data = json.loads(generated.read_text(encoding='utf-8'))
                for layer in data['layers']:
                    if layer['type'] == 'sprites':
                        layer['sha256'] = layers.digest(atlas.read_bytes())
                generated.write_text(json.dumps(data), encoding='utf-8')

            repin()
            self.assert_portable_example_equal(expected, layers.prepare_scene(generated))
            # Even a valid new file pin cannot conceal a different drawing.
            pixels.putpixel((0, 0), (255, 0, 0, 255))
            pixels.save(atlas, compress_level=0)
            repin()
            with self.assertRaises(AssertionError):
                self.assert_portable_example_equal(expected, layers.prepare_scene(generated))


if __name__ == '__main__':
    unittest.main()
