"""Layer compositor tests. All fixtures and encoder checks are offline."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops
from gif_cinema import layers


def fixture(**changes):
    return {'format': layers.FORMAT, 'schema_version': 1, 'width': 32, 'height': 32,
            'duration_ms': 160, 'fps': 25, 'layers': [
                {'id': 'back', 'type': 'rect', 'size': [32, 32], 'fill': '#0000ff'},
                {'id': 'front', 'type': 'rect', 'size': [8, 8], 'fill': '#ff0000',
                 'keyframes': [{'at': 0, 'x': .25}, {'at': .5, 'x': .75}, {'at': 1, 'x': .25}]}], **changes}


class ValidationTests(unittest.TestCase):
    def test_normalization_and_roundtrip_do_not_mutate_input(self):
        value = fixture()
        before = copy.deepcopy(value)
        normalized = layers.normalize_scene(value)
        self.assertEqual(before, value)
        self.assertEqual(normalized, layers.normalize_scene(normalized))
        self.assertEqual(normalized, json.loads(layers.serialize_scene(value)))
        self.assertEqual(normalized['layers'][0]['keyframes'][1]['zoom'], 1)

    def test_unknown_fields_and_unsupported_expression_rejected(self):
        for key in ('typo', 'expressions', 'fonts', 'scripts', 'assets', 'lottie'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                layers.normalize_scene(fixture(**{key: 'ignored?'}))
        for key in ('expression', 'script', 'mask', 'parent', 'font_path', 'url'):
            scene = fixture(); scene['layers'][0][key] = 'do-not-execute'
            with self.subTest(key=key), self.assertRaises(ValueError):
                layers.normalize_scene(scene)
        with self.assertRaisesRegex(ValueError, 'not a Lottie'):
            layers.normalize_scene(fixture(format='lottie'))

    def test_numbers_must_be_finite_and_not_boolean(self):
        for key, bad in {'width': [0, 3, 1026], 'height': [1, 2048], 'fps': [24, 30, 51],
                         'duration_ms': [39, 41, 159, 30001], 'schema_version': [0, 2]}.items():
            for value in bad + [True, False, float('nan'), float('inf'), 10 ** 1000, '50']:
                with self.subTest(key=key, value=str(value)[:40]), self.assertRaises(ValueError):
                    layers.normalize_scene(fixture(**{key: value}))

    def test_layer_validation(self):
        invalid = [[], [{}], [dict(fixture()['layers'][0], type='movie')], fixture()['layers'] * 9]
        invalid += [[dict(fixture()['layers'][0], id=value)] for value in ('', '../oops', 'same name', True)]
        invalid.append([dict(fixture()['layers'][0], id='Back'), fixture()['layers'][0]])
        for value in invalid:
            with self.subTest(value=str(value)[:100]), self.assertRaises(ValueError):
                layers.normalize_scene(fixture(layers=value))

    def test_size_color_text_and_layer_time_bounds(self):
        for key, value in [('size', [0, 2]), ('size', [1, True]), ('size', [2049, 2]),
                           ('size', 'wide'), ('fill', 'red'), ('fill', '#12ff'),
                           ('stroke_width', 17), ('radius', -1), ('anchor', [0]), ('anchor', [-1, 0]),
                           ('in_ms', 160), ('out_ms', 0), ('in_ms', 20), ('out_ms', 159)]:
            scene = fixture(); scene['layers'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                layers.normalize_scene(scene)
        for bad in ('', '\n', 'a' * 161, 15):
            with self.assertRaises(ValueError):
                layers.normalize_scene(fixture(layers=[{'id': 't', 'type': 'text', 'text': bad}]))
        for bad in (None, True, '#fffffff', '#ff000000'):
            with self.assertRaises(ValueError):
                layers.normalize_scene(fixture(matte=bad))

    def test_strict_keyframes(self):
        for keys in ([], [{'at': 0}], [{'at': .1}, {'at': 1}], [{'at': 0}, {'at': .9}],
                     [{'at': 0}, {'at': .5}, {'at': .5}, {'at': 1}], [{'at': 0}, {'at': 1, 'expression': '1'}],
                     [{'at': 0}, {'at': 1, 'zoom': 0}], [{'at': 0, 'easing': [0, 0, 1]}, {'at': 1}],
                     [{'at': 0, 'easing': [0, False, 1, 1]}, {'at': 1}],
                     [{'at': 0, 'easing': [0, -1, 1, 1]}, {'at': 1}]):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                layers.normalize_keyframes(keys)

    def test_budget_checks(self):
        for name in ('MAX_PIXEL_FRAMES', 'MAX_LAYER_PIXEL_FRAMES', 'MAX_LAYER_RASTER_PIXELS',
                     'MAX_TOTAL_RASTER_PIXELS', 'MAX_RASTER_PIXEL_FRAMES', 'MAX_SUPERSAMPLED_RASTER_PIXELS'):
            with patch.object(layers, name, 1), self.assertRaises(ValueError):
                layers.normalize_scene(fixture())

    def test_paths_cannot_be_urls_absolute_or_escape(self):
        for value in ('', '/etc/passwd', '../a.png', './a.png', 'a/../b.png', 'https://x/a.png',
                      'http:x', '//host/x', 'a//b', 'C:\\x.png', 'a\\b.png', 'a\x00.png'):
            with self.subTest(path=value), self.assertRaises(ValueError):
                layers.source_name(value)
        self.assertEqual(layers.source_name('assets/my image.png'), 'assets/my image.png')


class InterpolationTests(unittest.TestCase):
    def test_left_keyframe_easing_and_property_inheritance(self):
        keys = layers.normalize_keyframes([{'at': 0, 'x': .1, 'zoom': 2, 'easing': 'step'},
                                           {'at': .5, 'x': .5}, {'at': 1, 'x': .9}])
        self.assertEqual(layers.evaluate(keys, .49)['x'], .1)
        self.assertEqual(layers.evaluate(keys, .5)['x'], .5)
        self.assertAlmostEqual(layers.evaluate(keys, .75)['x'], .7)
        self.assertEqual(layers.evaluate(keys, 1)['zoom'], 2)

    def test_cubic_bezier_solves_time_coordinate(self):
        for t in (0, .01, .25, .5, .9, 1):
            self.assertAlmostEqual(layers.ease(t, [0, 0, 1, 1]), t, places=8)
        self.assertAlmostEqual(layers.ease(.5, [.42, 0, .58, 1]), .5, places=8)
        self.assertLess(layers.ease(.25, [.42, 0, .58, 1]), .25)
        self.assertGreater(layers.ease(.75, [.42, 0, .58, 1]), .75)

    def test_all_easing_names(self):
        expected = {'linear': .25, 'ease-in': .0625, 'ease-out': .4375, 'ease-in-out': .15625,
                    'smootherstep': .103515625, 'step': 0}
        for name, answer in expected.items():
            self.assertAlmostEqual(layers.ease(.25, name), answer)

    def test_layer_lifetime_and_local_time(self):
        scene = layers.normalize_scene(fixture())
        layer = copy.deepcopy(scene['layers'][1]); layer.update(in_ms=40, out_ms=120)
        self.assertIsNone(layers.layer_transform(scene, layer, 0))
        self.assertEqual(layers.layer_transform(scene, layer, 40)['x'], .25)
        self.assertEqual(layers.layer_transform(scene, layer, 80)['x'], .75)
        self.assertIsNone(layers.layer_transform(scene, layer, 120))
        self.assertIsNone(layers.layer_transform(scene, layer, 160))
        self.assertEqual(layers.layer_transform(scene, scene['layers'][1], 160)['x'], .25)

    def test_progress_validation(self):
        keys = layers.normalize_keyframes([{'at': 0}, {'at': 1}])
        for value in (-1, 2, True, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                layers.evaluate(keys, value)


class FileTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'scene.json'
        self.path.write_bytes(layers.serialize_scene(fixture()))
        self.network = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden'))
        self.network.start(); self.addCleanup(self.network.stop)
        self.sockets = patch('socket.create_connection', side_effect=AssertionError('Network forbidden'))
        self.sockets.start(); self.addCleanup(self.sockets.stop)

    def set_scene(self, value):
        self.path.write_bytes(layers.serialize_scene(value))
        return layers.prepare_scene(self.path)

    def image_scene(self):
        asset = self.root / 'assets' / 'test.png'; asset.parent.mkdir(exist_ok=True)
        Image.new('RGBA', (8, 8), (200, 20, 30, 128)).save(asset)
        self.set_scene(fixture(layers=[{'id': 'image', 'type': 'image', 'source': 'assets/test.png', 'size': [16, 16]}]))
        return asset

    def test_duplicate_keys_oversized_invalid_utf8_rejected(self):
        for raw in (b'{"layers": [], "layers": []}', b'x' * (layers.MAX_SCENE_BYTES + 1), b'\xff'):
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):
                layers.load_scene(self.path)

    def test_scene_hash_uses_the_same_bytes_that_were_parsed(self):
        raw = self.path.read_bytes()
        with patch.object(layers, 'read_regular', return_value=raw) as read:
            prepared = layers.prepare_scene(self.path)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(prepared['source_sha256'], layers.digest(raw))

    def test_oversized_rasters_rejected_before_decode_or_allocation(self):
        for kind in ('rect', 'ellipse', 'image'):
            scene = fixture(width=2, height=2, fps=50, duration_ms=30000,
                layers=[{'id': f'layer_{i}', 'type': kind, 'size': [2048, 2048],
                         **({'source': 'not-decoded.png'} if kind == 'image' else {})} for i in range(16)])
            self.path.write_text(json.dumps(scene))
            with (self.subTest(kind=kind),
                  patch.object(layers, 'read_assets', side_effect=AssertionError('No decoding')),
                  patch.object(layers, 'rasterize', side_effect=AssertionError('No rasterization'))):
                with self.assertRaisesRegex(ValueError, 'raster/supersampling'):
                    layers.prepare_scene(self.path)

    def test_total_raster_memory_and_pixel_frame_budget_preflight(self):
        cases = [
            (fixture(width=2, height=2, duration_ms=80, layers=[
                {'id': f'l{i}', 'type': 'rect', 'size': [1024, 1024]} for i in range(5)]), 'total layer raster'),
            (fixture(width=2, height=2, fps=50, duration_ms=30000, layers=[
                {'id': 'large', 'type': 'rect', 'size': [512, 512]}]), 'raster pixel-frame')]
        for value, message in cases:
            self.path.write_text(json.dumps(value))
            with patch('PIL.Image.new', side_effect=AssertionError('No raster allocation')):
                with self.assertRaisesRegex(ValueError, message):
                    layers.prepare_scene(self.path)

    def test_text_budget_measures_before_allocating_pixels(self):
        self.path.write_text(json.dumps(fixture(layers=[
            {'id': 't', 'type': 'text', 'text': 'MMMMMMMMMMMMMMMMMMMM', 'font_size': 160}])))
        with patch.object(layers, 'MAX_LAYER_RASTER_PIXELS', 1), patch.object(layers, 'rasterize', side_effect=AssertionError('No raster allocation')):
            with self.assertRaisesRegex(ValueError, 'raster/supersampling'):
                layers.prepare_scene(self.path)

    def test_premultiplied_rasters_cached_once(self):
        prepared = layers.prepare_scene(self.path)
        for raster in prepared['rasters'].values():
            self.assertEqual(raster.mode, 'RGBa')
            raster.convert = lambda *args, **kwargs: self.fail('Source raster converted again during frame rendering')
        for at in (0, 40, 80, 120):
            frame, _ = layers.render_at(prepared, at)
            self.assertEqual(frame.mode, 'RGBA')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'Named pipes require POSIX')
    def test_fifo_scene_and_asset_fail_promptly_without_output(self):
        scene_fifo = self.root / 'pipe.json'; os.mkfifo(scene_fifo)
        asset_fifo = self.root / 'pipe.png'; os.mkfifo(asset_fifo)
        self.path.write_bytes(layers.serialize_scene(fixture(layers=[
            {'id': 'image', 'type': 'image', 'source': 'pipe.png', 'size': [8, 8]}])))
        for path in (scene_fifo, self.path):
            result = subprocess.run([sys.executable, '-m', 'gif_cinema.layers', 'render', str(path),
                '--out', str(self.root / 'fifo-output'), '--dry-run'], capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b'regular local file', result.stderr)
            self.assertFalse((self.root / 'fifo-output').exists())

    @unittest.skipUnless(hasattr(os, 'mkfifo') and hasattr(os, 'O_NONBLOCK'), 'FIFO race defense requires POSIX')
    def test_fifo_replacement_between_stat_and_open_cannot_block(self):
        target = self.root / 'raced-input'; target.write_bytes(b'original')
        script = f'''
import os
from unittest.mock import patch
from gif_cinema import layers
path = {str(target)!r}
original_open = os.open
def replace_and_open(name, flags):
    assert flags & os.O_NONBLOCK
    os.unlink(name)
    os.mkfifo(name)
    return original_open(name, flags)
with patch.object(layers.os, 'open', side_effect=replace_and_open):
    try:
        layers.read_regular(path, 100)
    except ValueError as error:
        assert 'regular local file' in str(error)
    else:
        raise AssertionError('FIFO was accepted')
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_dense_valid_scene_can_be_saved_and_reopened(self):
        values = {name: .1234567890123456 for name in layers.DEFAULTS}
        keys = [{'at': i / 31, **values, 'easing': [.1234567890123456] * 4} for i in range(32)]
        scene = fixture(width=2, height=2, fps=50, duration_ms=40, layers=[
            {'id': f'layer_{i}', 'type': 'rect', 'size': [2, 2], 'keyframes': keys} for i in range(16)])
        raw = json.dumps(scene, separators=(',', ':')).encode()
        self.assertLess(len(raw), 128 * 1024)
        self.path.write_bytes(raw)
        prepared = layers.prepare_scene(self.path)
        exported = layers.save_bundle(prepared, self.root / 'dense-saved')
        self.assertGreater(exported.stat().st_size, 128 * 1024)
        reopened = layers.prepare_scene(exported)
        self.assertEqual(prepared['scene'], reopened['scene'])

    def test_save_serialization_failure_does_not_create_destination(self):
        prepared = layers.prepare_scene(self.path)
        destination = self.root / 'bad-save'
        with patch.object(layers, 'serialize_scene', side_effect=ValueError('size budget')):
            with self.assertRaisesRegex(ValueError, 'size budget'):
                layers.save_bundle(prepared, destination)
        self.assertFalse(destination.exists())

    def test_layer_order_and_independent_animation(self):
        prepared = layers.prepare_scene(self.path)
        first, states = layers.render_at(prepared, 0)
        middle, _ = layers.render_at(prepared, 80)
        self.assertEqual(first.getpixel((8, 16)), (255, 0, 0, 255))
        self.assertEqual(first.getpixel((24, 16)), (0, 0, 255, 255))
        self.assertEqual(middle.getpixel((24, 16)), (255, 0, 0, 255))
        before_back, _ = layers.render_at(prepared, 0, only_layer='back')
        after_back, _ = layers.render_at(prepared, 80, only_layer='back')
        self.assertEqual(before_back.tobytes(), after_back.tobytes())
        reversed_scene = fixture(); reversed_scene['layers'].reverse()
        reversed_frame, _ = layers.render_at(self.set_scene(reversed_scene), 0)
        self.assertEqual(reversed_frame.getpixel((8, 16)), (0, 0, 255, 255))

    def test_source_alpha_and_opacity_composite(self):
        self.image_scene()
        image_scene = json.loads(self.path.read_text())
        image_scene['layers'][0]['keyframes'] = [{'at': 0, 'opacity': .5}, {'at': 1}]
        frame, _ = layers.render_at(self.set_scene(image_scene), 0)
        self.assertIn(frame.getpixel((16, 16))[3], (63, 64))
        self.assertEqual(frame.getpixel((0, 0))[3], 0)
        self.assertGreater(frame.getpixel((16, 16))[0], 190)

    def test_positive_rotation_clockwise_and_anchor(self):
        asset = self.root / 'marker.png'
        image = Image.new('RGBA', (32, 32)); image.paste((255, 0, 0, 255), (14, 2, 18, 7)); image.save(asset)
        scene = fixture(layers=[{'id': 'marker', 'type': 'image', 'source': 'marker.png', 'size': [32, 32],
                                'keyframes': [{'at': 0, 'rotation': 90}, {'at': 1}]}])
        frame, _ = layers.render_at(self.set_scene(scene), 0)
        box = frame.getchannel('A').getbbox(); self.assertGreater(box[0], 20); self.assertLess(box[1], 20)
        scene = fixture(layers=[{'id': 'box', 'type': 'rect', 'size': [8, 8], 'anchor': [0, 0]}])
        frame, _ = layers.render_at(self.set_scene(scene), 0)
        self.assertEqual(frame.getchannel('A').getbbox(), (16, 16, 24, 24))

    def test_text_is_editable_and_isolated(self):
        scene = fixture(layers=[{'id': 'text', 'type': 'text', 'text': 'One', 'font_size': 12}])
        prepared = self.set_scene(scene)
        first, _ = layers.render_at(prepared, 0)
        scene['layers'][0]['text'] = 'Two'
        second, _ = layers.render_at(self.set_scene(scene), 0)
        self.assertNotEqual(first.tobytes(), second.tobytes())
        self.assertEqual(first.getpixel((0, 0))[3], 0)

    def test_save_reopen_relocation_and_asset_hash(self):
        original_asset = self.image_scene()
        prepared = layers.prepare_scene(self.path)
        before = original_asset.read_bytes()
        exported = layers.save_bundle(prepared, self.root / 'portable')
        relocated = self.root / 'moved'
        shutil.copytree(exported.parent, relocated)
        reopened = layers.prepare_scene(relocated / 'scene.json')
        for time_ms in (0, 40, 80, 120, 160):
            self.assertEqual(layers.render_at(prepared, time_ms)[0].tobytes(), layers.render_at(reopened, time_ms)[0].tobytes())
        self.assertEqual(before, original_asset.read_bytes())
        source = relocated / reopened['scene']['layers'][0]['source']
        Image.new('RGB', (8, 8), 'green').save(source, format='PNG')
        with self.assertRaisesRegex(ValueError, 'Asset changed'):
            layers.prepare_scene(relocated / 'scene.json')

    def test_asset_symlink_escape_rejected(self):
        outside = self.root / 'outside.png'; Image.new('RGB', (2, 2)).save(outside)
        inside = self.root / 'inside'; inside.mkdir()
        (inside / 'escape.png').symlink_to(outside)
        self.path = inside / 'scene.json'
        with self.assertRaisesRegex(ValueError, 'escapes'):
            self.set_scene(fixture(layers=[{'id': 'image', 'type': 'image', 'source': 'escape.png', 'size': [8, 8]}]))

    def test_animated_asset_is_rejected(self):
        a = Image.new('RGB', (8, 8), 'red'); b = Image.new('RGB', (8, 8), 'blue')
        a.save(self.root / 'animated.png', save_all=True, append_images=[b], duration=40)
        with self.assertRaisesRegex(ValueError, 'still'):
            self.set_scene(fixture(layers=[{'id': 'image', 'type': 'image', 'source': 'animated.png', 'size': [8, 8]}]))

    def test_asset_budgets(self):
        self.image_scene()
        for name in ('MAX_ASSET_BYTES', 'MAX_TOTAL_ASSET_BYTES', 'MAX_ASSET_PIXELS', 'MAX_TOTAL_ASSET_PIXELS'):
            with self.subTest(name=name), patch.object(layers, name, 1), self.assertRaises(ValueError):
                layers.prepare_scene(self.path)

    def test_dry_run_no_output_encoder_or_network(self):
        out = self.root / 'dry'
        with patch('shutil.which', return_value=None), patch('subprocess.run', side_effect=AssertionError('No encoder')):
            plan = layers.render_scene(self.path, out, dry_run=True)
        self.assertEqual(plan['api_calls'], 0); self.assertEqual(plan['frames'], 4)
        self.assertFalse(out.exists())

    def test_missing_encoder_and_existing_output_preserve_originals(self):
        before = self.path.read_bytes()
        with patch('shutil.which', return_value=None), self.assertRaisesRegex(ValueError, 'FFmpeg'):
            layers.render_scene(self.path, self.root / 'no-encoder')
        out = self.root / 'existing'; out.mkdir(); (out / 'keep').write_text('original')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            layers.render_scene(self.path, out)
        with self.assertRaisesRegex(ValueError, 'new directory'):
            layers.save_bundle(layers.prepare_scene(self.path), out)
        self.assertEqual((out / 'keep').read_text(), 'original')
        self.assertEqual(before, self.path.read_bytes())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real FFmpeg and ffprobe required')
    def test_real_gif_mp4_export_reopen_every_frame_and_loop(self):
        self.image_scene()
        before = self.path.read_bytes()
        out = self.root / 'render'
        receipt = layers.render_scene(self.path, out)
        self.assertEqual(receipt['frames'], 4)
        self.assertEqual(sum(receipt['gif_delays_ms']), 160)
        self.assertTrue(receipt['source_unchanged'])
        self.assertEqual(receipt['api_calls'], 0)
        self.assertTrue(receipt['loop_review']['closing_endpoint_rgba_equal'])
        self.assertIn('decoded_gif_seam_rgb_mae', receipt['loop_review'])
        self.assertIn('decoded_mp4_seam_rgb_mae', receipt['loop_review'])
        self.assertEqual(before, self.path.read_bytes())
        reopened = layers.prepare_scene(out / 'editable' / 'scene.json')
        for sample in receipt['samples']:
            frame, _ = layers.render_at(reopened, sample['time_ms'])
            self.assertEqual(layers.digest(frame.tobytes()), sample['rgba_sha256'])
            with Image.open(out / 'frames' / f'{sample["frame"]:04}.png') as png:
                self.assertEqual(frame.tobytes(), png.tobytes())
        for name, sha in receipt['outputs'].items():
            self.assertEqual(layers.digest((out / name).read_bytes()), sha)
        self.assertEqual(receipt['samples'][-1]['time_ms'], 120)
        self.assertEqual(receipt['loop_review']['endpoint_time_ms'], 160)
        self.assertFalse(any(p.name.startswith('.render-stage') for p in self.root.iterdir()))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real FFmpeg and ffprobe required')
    def test_output_appearing_during_export_is_not_replaced(self):
        out = self.root / 'raced'
        original = layers.run_command
        def race(command, commands):
            if not out.exists():
                out.mkdir()
                (out / 'keep').write_text('untouched')
            return original(command, commands)
        with patch.object(layers, 'run_command', side_effect=race), self.assertRaises(FileExistsError):
            layers.render_scene(self.path, out)
        self.assertEqual((out / 'keep').read_text(), 'untouched')
        self.assertEqual([p.name for p in out.iterdir()], ['keep'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real FFmpeg and ffprobe required')
    def test_source_change_during_export_prevents_publication(self):
        out = self.root / 'changed'
        original = layers.run_command
        def edit_source(command, commands):
            self.path.write_bytes(layers.serialize_scene(fixture(title='Changed during export')))
            return original(command, commands)
        with patch.object(layers, 'run_command', side_effect=edit_source), self.assertRaisesRegex(ValueError, 'Source scene changed'):
            layers.render_scene(self.path, out)
        self.assertFalse(out.exists())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real FFmpeg and ffprobe required')
    def test_nonloop_export_has_no_repeat_extension(self):
        self.set_scene(fixture(loop=False))
        out = self.root / 'nonloop'
        receipt = layers.render_scene(self.path, out)
        with Image.open(out / 'preview.gif') as gif:
            self.assertNotIn('loop', gif.info)
        self.assertEqual(sum(receipt['gif_delays_ms']), 160)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real FFmpeg and ffprobe required')
    def test_max_frame_layer_receipt_can_be_reopened_by_verifier(self):
        from tools.verify_layered_scene import verify
        self.set_scene(fixture(width=2, height=2, fps=50, duration_ms=30000, layers=[
            {'id': f'layer_{i:02d}_' + 'x' * 31, 'type': 'rect', 'size': [2, 2]} for i in range(16)]))
        out = self.root / 'large-receipt'
        layers.render_scene(self.path, out)
        self.assertGreater((out / 'receipt.json').stat().st_size, 4 * 1024 * 1024)
        self.assertLess((out / 'receipt.json').stat().st_size, layers.MAX_RECEIPT_BYTES)
        self.assertEqual(verify(out)['frames_reopened_and_matched'], 1500)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real FFmpeg and ffprobe required')
    def test_receipt_limit_is_checked_before_output_completion(self):
        out = self.root / 'receipt-too-large'
        with patch.object(layers, 'MAX_RECEIPT_BYTES', 10), self.assertRaisesRegex(ValueError, 'shared writer/verifier'):
            layers.render_scene(self.path, out)
        self.assertFalse(out.exists())

    def test_failed_export_has_no_completion_or_partial_output(self):
        out = self.root / 'failure'
        with patch('shutil.which', return_value='/mock/ffmpeg'), patch.object(layers, 'run_command', side_effect=ValueError('encoder failed')):
            with self.assertRaisesRegex(ValueError, 'encoder failed'):
                layers.render_scene(self.path, out)
        self.assertFalse(out.exists())
        self.assertFalse(any(p.name.startswith('.failure-stage') for p in self.root.iterdir()))


if __name__ == '__main__':
    unittest.main()
