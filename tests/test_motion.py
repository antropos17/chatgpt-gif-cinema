"""Offline motion recipes: validation, rational timing, transforms and delivery."""
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import motion


class BoundedInputTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFOs required')
    def test_source_and_recipe_fifos_fail_without_blocking_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.png'
            Image.new('RGB', (16, 16)).save(source)
            fifo = root / 'input.fifo'
            os.mkfifo(fifo)
            for args in ([str(fifo)], [str(source), '--recipe', str(fifo)]):
                with self.subTest(args=args):
                    output = root / 'output'
                    result = subprocess.run(
                        [sys.executable, '-m', 'gif_cinema', 'motion', *args,
                         '--out', str(output), '--dry-run'],
                        capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('regular local file', result.stderr)
                    self.assertFalse(output.exists())

    def test_replaced_nonregular_descriptor_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            source.write_bytes(b'valid')
            fake_stat = type('Stat', (), {'st_mode': 0})()
            with patch('gif_cinema.motion.os.fstat', return_value=fake_stat):
                with self.assertRaisesRegex(ValueError, 'regular local file'):
                    motion.read_bounded(source, 10)

    def test_regular_snapshot_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            source.write_bytes(b'1234')
            self.assertEqual(motion.read_bounded(source, 4), b'1234')
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                motion.read_bounded(source, 3)


class RecipeTests(unittest.TestCase):
    def recipe(self, **changes):
        return motion.normalize_recipe(changes, (32, 24))

    def test_defaults_and_input_immutability(self):
        data = {'keyframes': [{'at': 0, 'zoom': 1.5}, {'at': 1}]}
        before = copy.deepcopy(data)
        result = motion.normalize_recipe(data, (31, 23))
        self.assertEqual(data, before)
        self.assertEqual((result['width'], result['height']), (32, 24))
        self.assertIn(result['fps'], (25, 50))
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual(result['keyframes'][1]['zoom'], 1.5)
        self.assertEqual(result['keyframes'][1]['x'], .5)
        self.assertFalse(result['spritesheet'])

    def test_unknown_fields_and_enums(self):
        for changes in ({'typo': 1}, {'schema_version': 2}, {'fps': 30},
                        {'fit': 'stretch'}, {'playback': 'loop'}, {'background': 'red'},
                        {'spritesheet': 1}, {'keyframes': [{'at': 0, 'typo': 2}, {'at': 1}]},
                        {'keyframes': [{'at': 0, 'easing': 'smooth'}, {'at': 1}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.recipe(**changes)

    def test_numeric_bounds_and_boolean_rejection(self):
        invalid = {'width': [True, 0, 3, 2050], 'height': [False, 1, 2049],
                   'fps': [True, 0, 24, 51], 'speed': [True, 0, .09, 8.01],
                   'repeats': [True, 0, 1.5, 17], 'trim_start_ms': [True, -1],
                   'hold_start_ms': [True, -1, 10001], 'hold_end_ms': [False, -1, 10001],
                   'still_duration_ms': [True, 39, 30001]}
        for key, values in invalid.items():
            for value in values + [float('nan'), float('inf'), -float('inf')]:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.recipe(**{key: value})

    def test_huge_integer_validation_is_a_value_error(self):
        with self.assertRaises(ValueError):
            self.recipe(speed=10 ** 1000)

    def test_frame_pixel_and_atlas_budgets(self):
        for budget, changes in [('MAX_FRAMES', {}), ('MAX_PIXEL_FRAMES', {}),
                                ('MAX_ATLAS_PIXELS', {'spritesheet': True})]:
            with self.subTest(budget=budget), patch.object(motion, budget, 1):
                with self.assertRaises(ValueError):
                    motion.build_timeline([100, 200], self.recipe(**changes))

    def test_sample_index_and_progress_validation(self):
        recipe = self.recipe()
        timeline = motion.build_timeline([100, 100], recipe)
        for index in (-1, True, .5, timeline['playback_frames']):
            with self.subTest(index=index), self.assertRaises(ValueError):
                motion.sample_timeline(timeline, index)
        for progress in (-.1, 1.1, True, float('nan')):
            with self.subTest(progress=progress), self.assertRaises(ValueError):
                motion.evaluate_keyframes(recipe['keyframes'], progress)

    def test_keyframe_bounds_and_order(self):
        bad = [[], [{'at': 0}], [{'at': .1}, {'at': 1}], [{'at': 0}, {'at': .9}],
               [{'at': 0}, {'at': .5}, {'at': .5}, {'at': 1}],
               [{'at': 0}, {'at': .7}, {'at': .4}, {'at': 1}],
               [{'at': i / 32} for i in range(33)]]
        for key, values in {'at': [True, float('nan')], 'zoom': [True, .09, 8.1],
                            'x': [-2.1, 3.1], 'y': [-2.1, 3.1],
                            'rotation': [-3601, 3601], 'opacity': [-.1, 1.1]}.items():
            for value in values + [float('inf')]:
                bad.append([{'at': 0, key: value}, {'at': 1}])
        for frames in bad:
            with self.subTest(frames=frames), self.assertRaises(ValueError):
                self.recipe(keyframes=frames)

    def test_timeline_trim_splits_holds_and_speed(self):
        recipe = self.recipe(trim_start_ms=50, trim_end_ms=450, speed=2)
        timeline = motion.build_timeline([100, 200, 300], recipe)
        self.assertEqual(timeline['segments'], [
            {'source_index': 0, 'duration_ms': 25},
            {'source_index': 1, 'duration_ms': 100},
            {'source_index': 2, 'duration_ms': 75}])
        self.assertEqual(timeline['duration_ms'], 200)
        self.assertEqual(timeline['playback_frames'], 5)

    def test_reverse_pingpong_and_repeats(self):
        reverse = motion.build_timeline([100, 200, 300], self.recipe(playback='reverse'))
        self.assertEqual([s['source_index'] for s in reverse['segments']], [2, 1, 0])
        ping = motion.build_timeline([100, 200, 300, 400], self.recipe(playback='ping-pong', repeats=2))
        self.assertEqual([s['source_index'] for s in ping['segments']], [0, 1, 2, 3, 2, 1] * 2)
        self.assertEqual(ping['duration_ms'], 3000)
        two = motion.build_timeline([100, 200], self.recipe(playback='ping-pong'))
        self.assertEqual([s['source_index'] for s in two['segments']], [0, 1])

    def test_holds_applied_once_after_repetition(self):
        timeline = motion.build_timeline([100, 200], self.recipe(
            repeats=3, hold_start_ms=70, hold_end_ms=130))
        self.assertEqual(timeline['duration_ms'], 1100)
        self.assertEqual(timeline['segments'][0]['source_index'], 0)
        self.assertEqual(timeline['segments'][-1]['source_index'], 1)
        self.assertEqual(sum(s['duration_ms'] for s in timeline['segments']), 1100)

    def test_quantization_and_centered_sampling_preserve_endpoints(self):
        timeline = motion.build_timeline([20, 160, 20], self.recipe())
        self.assertEqual([motion.sample_timeline(timeline, i) for i in range(5)], [0, 1, 1, 1, 2])
        rational = motion.build_timeline([100, 200], self.recipe(speed=3))
        self.assertAlmostEqual(rational['duration_ms'], 100)
        self.assertEqual(rational['output_duration_ms'], rational['playback_frames'] * 40)
        self.assertAlmostEqual(rational['duration_quantization_ms'], rational['output_duration_ms'] - 100)
        with self.assertRaisesRegex(ValueError, 'at least two'):
            motion.build_timeline([20, 20], self.recipe(speed=8))

    def test_empty_trim_rejected(self):
        for changes in ({'trim_start_ms': 300}, {'trim_start_ms': 200, 'trim_end_ms': 100},
                        {'trim_end_ms': 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                motion.build_timeline([100, 200], self.recipe(**changes))

    def test_keyframe_inheritance_and_left_easing(self):
        frames = self.recipe(keyframes=[{'at': 0, 'zoom': 1, 'x': .2, 'easing': 'step'},
                                       {'at': .5, 'zoom': 2, 'easing': 'linear'},
                                       {'at': 1, 'zoom': 4}])['keyframes']
        self.assertEqual(motion.evaluate_keyframes(frames, .25)['zoom'], 1)
        self.assertEqual(motion.evaluate_keyframes(frames, .5)['zoom'], 2)
        self.assertEqual(motion.evaluate_keyframes(frames, .75)['zoom'], 3)
        self.assertEqual(motion.evaluate_keyframes(frames, 1)['zoom'], 4)
        self.assertEqual(motion.evaluate_keyframes(frames, .75)['x'], .2)

    def test_smootherstep_loop_has_matching_endpoints_and_soft_turns(self):
        frames = self.recipe(keyframes=[
            {'at': 0, 'rotation': -4, 'easing': 'smootherstep'},
            {'at': .5, 'rotation': 4, 'easing': 'smootherstep'},
            {'at': 1, 'rotation': -4}])['keyframes']
        evaluate = lambda t: motion.evaluate_keyframes(frames, t)['rotation']
        self.assertEqual(evaluate(0), evaluate(1))
        self.assertEqual(evaluate(.5), 4)
        # Local velocity and acceleration approach zero at turnarounds and the seam.
        delta = .0001
        for t in (0, .5):
            self.assertLess(abs(evaluate(t + delta) - evaluate(t)) / delta, .0001)
            self.assertLess(abs(evaluate(t + 2 * delta) - 2 * evaluate(t + delta) + evaluate(t)) / delta ** 2, .5)
        self.assertAlmostEqual(evaluate(.25), evaluate(.75))

    def test_easing_progress(self):
        expected = {'linear': .25, 'ease-in': .0625, 'ease-out': .4375, 'ease-in-out': .15625, 'smootherstep': .103515625}
        for easing, fraction in expected.items():
            frames = self.recipe(keyframes=[{'at': 0, 'opacity': 0, 'easing': easing},
                                           {'at': 1, 'opacity': 1}])['keyframes']
            with self.subTest(easing=easing):
                self.assertAlmostEqual(motion.evaluate_keyframes(frames, .25)['opacity'], fraction)

    def test_render_transparency_position_and_opacity(self):
        source = Image.new('RGBA', (8, 8), (255, 0, 0, 255))
        recipe = self.recipe(width=32, height=32, background='#00ff00')
        transform = motion.evaluate_keyframes(recipe['keyframes'], 0)
        transform.update(zoom=.5, x=.75, opacity=.5)
        frame = motion.render_frame(source, recipe, transform)
        self.assertEqual((frame.mode, frame.size), ('RGBA', (32, 32)))
        self.assertEqual(frame.getpixel((0, 0))[3], 0)
        self.assertIn(frame.getpixel((24, 16))[3], (127, 128))
        self.assertEqual(frame.getpixel((24, 16))[:3], (255, 0, 0))
        self.assertEqual(source.getpixel((0, 0)), (255, 0, 0, 255))

    def test_positive_rotation_is_clockwise(self):
        source = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
        source.paste((255, 0, 0, 255), (14, 2, 18, 7))
        recipe = self.recipe(width=32, height=32)
        transform = motion.evaluate_keyframes(recipe['keyframes'], 0)
        transform['rotation'] = 90
        result = motion.render_frame(source, recipe, transform)
        box = result.getchannel('A').getbbox()
        self.assertIsNotNone(box)
        self.assertGreater(box[0], 20)
        self.assertLess(box[1], 20)

    def test_contain_vs_cover(self):
        source = Image.new('RGBA', (32, 16), 'red')
        for fit, corner_alpha in [('contain', 0), ('cover', 255)]:
            recipe = self.recipe(width=32, height=32, fit=fit)
            result = motion.render_frame(source, recipe, motion.evaluate_keyframes(recipe['keyframes'], 0))
            self.assertEqual(result.getpixel((1, 1))[3], corner_alpha)


class MotionIntegrationTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source.gif'
        frames = [Image.new('RGB', (32, 24), color) for color in ('red', 'green', 'blue')]
        frames[0].save(self.source, save_all=True, append_images=frames[1:], duration=[80, 120, 200], loop=0)
        self.original = self.source.read_bytes()
        network = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden'))
        network.start()
        self.addCleanup(network.stop)
        sockets = patch('socket.create_connection', side_effect=AssertionError('Network forbidden'))
        sockets.start()
        self.addCleanup(sockets.stop)

    def test_dry_run_no_output_encoder_or_network(self):
        out = self.root / 'planned'
        with patch('shutil.which', return_value=None), patch('subprocess.run', side_effect=AssertionError('Encoder forbidden')):
            plan = motion.motion(self.source, out, dry_run=True)
        self.assertIsInstance(plan, dict)
        self.assertFalse(out.exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_duplicate_and_oversized_recipe_rejected(self):
        recipe = self.root / 'recipe.json'
        recipe.write_text('{"speed": 1, "speed": 2}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            motion.load_recipe(recipe)
        recipe.write_text(' ' * (motion.MAX_RECIPE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'limit'):
            motion.load_recipe(recipe)

    def test_single_frame_gif_uses_still_duration(self):
        source = self.root / 'single.gif'
        Image.new('RGB', (16, 16), 'red').save(source)
        out = self.root / 'single-planned'
        result = motion.motion(source, out, recipe={'still_duration_ms': 200}, dry_run=True)
        self.assertIsInstance(result, dict)
        self.assertFalse(out.exists())

    def test_animated_png_is_rejected_without_output(self):
        source = self.root / 'animated.png'
        Image.new('RGBA', (16, 16), 'red').save(source, save_all=True,
            append_images=[Image.new('RGBA', (16, 16), 'blue')], duration=100)
        out = self.root / 'animated-planned'
        with self.assertRaises(ValueError):
            motion.motion(source, out, dry_run=True)
        self.assertFalse(out.exists())

    def test_bad_recipe_and_existing_destination_preserved(self):
        out = self.root / 'bad'
        with self.assertRaises(ValueError):
            motion.motion(self.source, out, recipe={'speed': 0})
        self.assertFalse(out.exists())
        out.mkdir()
        keep = out / 'keep.txt'
        keep.write_text('preserve')
        with self.assertRaises(ValueError):
            motion.motion(self.source, out)
        self.assertEqual(keep.read_text(), 'preserve')
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_symlink_destination_preserved(self):
        target = self.root / 'target'
        target.mkdir()
        link = self.root / 'linked'
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows symlink creation requires additional privileges')
            raise
        with self.assertRaises(ValueError):
            motion.motion(self.source, link)
        self.assertEqual(list(target.iterdir()), [])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
    def test_export_decodes_and_preserves_exact_endpoints(self):
        out = self.root / 'rendered'
        result = motion.motion(self.source, out, recipe={'spritesheet': True})
        for name in ('take.gif', 'review.mp4', 'first.png', 'last.png', 'contact-sheet.png',
                     'recipe.json', 'receipt.json', 'spritesheet.png', 'spritesheet.json'):
            self.assertTrue((out / name).is_file(), name)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertIsInstance(result, dict)
        self.assertEqual(receipt['timeline']['playback_frames'], 10)
        self.assertEqual(receipt['source_sha256'], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(receipt['api_calls'], 0)
        for name, digest in receipt['outputs'].items():
            self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), digest)
        for row in receipt['samples']:
            path = out / 'frames' / f"{row['frame']:04}.png"
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['png_sha256'])
        files = sorted((out / 'frames').glob('*.png'))
        self.assertEqual(len(files), 10)
        for name, index, color in [('first.png', 0, (255, 0, 0)), ('last.png', -1, (0, 0, 255))]:
            with Image.open(out / name) as endpoint, Image.open(files[index]) as frame:
                self.assertEqual(endpoint.convert('RGBA').tobytes(), frame.convert('RGBA').tobytes())
                self.assertEqual(endpoint.convert('RGB').getpixel((16, 12)), color)
        with Image.open(out / 'take.gif') as gif:
            total = 0
            for index in range(gif.n_frames):
                gif.seek(index)
                total += gif.info['duration']
            self.assertEqual(total, 400)
            self.assertEqual(gif.size, (32, 24))
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-count_frames',
            '-select_streams', 'v:0', '-show_entries', 'stream=width,height,nb_read_frames,codec_name',
            '-of', 'json', str(out / 'review.mp4')]))['streams'][0]
        self.assertEqual((probe['width'], probe['height'], int(probe['nb_read_frames'])), (32, 24, 10))
        self.assertEqual(probe['codec_name'], 'h264')
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(out / 'review.mp4'), '-f', 'null', '-'], check=True, capture_output=True)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), hashlib.sha256(self.original).digest())
        before = (out / 'receipt.json').read_bytes()
        with self.assertRaises(ValueError):
            motion.motion(self.source, out)
        self.assertEqual((out / 'receipt.json').read_bytes(), before)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
    def test_encoder_failure_cleans_stage_and_publishes_nothing(self):
        out = self.root / 'failed'
        with patch('gif_cinema.motion.run_command', side_effect=subprocess.TimeoutExpired('ffmpeg', 300)):
            with self.assertRaises(subprocess.TimeoutExpired):
                motion.motion(self.source, out)
        self.assertEqual(list(out.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), self.original)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
    def test_late_foreign_file_never_overwritten_and_no_receipt(self):
        out = self.root / 'collision'
        original_command = motion.run_command
        def collide(command, commands):
            result = original_command(command, commands)
            (out / 'take.gif').write_bytes(b'foreign candidate')
            return result
        with patch('gif_cinema.motion.run_command', side_effect=collide):
            with self.assertRaises(FileExistsError):
                motion.motion(self.source, out)
        self.assertEqual((out / 'take.gif').read_bytes(), b'foreign candidate')
        self.assertFalse((out / 'receipt.json').exists())
        self.assertFalse(any(path.name.startswith('.stage-') for path in out.iterdir()))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
    def test_source_mutation_blocks_publication(self):
        out = self.root / 'mutation'
        original_command = motion.run_command
        def mutate(command, commands):
            result = original_command(command, commands)
            self.source.write_bytes(self.original + b'changed externally')
            return result
        with patch('gif_cinema.motion.run_command', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                motion.motion(self.source, out)
        self.assertEqual(list(out.iterdir()), [])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
    def test_transparent_still_keeps_png_alpha_and_flattens_video(self):
        source = self.root / 'logo.png'
        image = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
        image.paste((255, 0, 0, 255), (4, 4, 12, 12))
        image.save(source)
        out = self.root / 'still'
        motion.motion(source, out, recipe={'still_duration_ms': 200, 'background': '#00ff00'})
        with Image.open(out / 'first.png') as first:
            self.assertEqual(first.mode, 'RGBA')
            self.assertEqual(first.getpixel((0, 0))[3], 0)
        with Image.open(out / 'take.gif') as gif:
            self.assertEqual(gif.convert('RGB').getpixel((0, 0)), (0, 255, 0))
        self.assertEqual(len(list((out / 'frames').glob('*.png'))), 5)


if __name__ == '__main__':
    unittest.main()
