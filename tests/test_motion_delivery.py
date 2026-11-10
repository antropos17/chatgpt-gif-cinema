"""GIF delivery is independent of source playback, samples and MP4 presentation."""
import contextlib
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

from PIL import Image, ImageSequence
from gif_cinema import cli, motion


HAS_MEDIA = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))
INFINITE_LOOP_EXTENSION = b'\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00'


class MotionDeliveryTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source.gif'
        self.drawings = [Image.new('RGB', (32, 24), color)
                         for color in ('red', 'green', 'blue', 'yellow')]
        # A finite input loop must not become the output's delivery policy.
        self.drawings[0].save(self.source, save_all=True, append_images=self.drawings[1:],
                             duration=[90, 150, 210, 110], loop=3)
        self.original = self.source.read_bytes()
        for name in ('urllib.request.OpenerDirector.open', 'socket.create_connection'):
            guard = patch(name, side_effect=AssertionError('Network forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def assert_policy(self, result, loop, verified=False):
        self.assertEqual(result['recipe']['gif_loop'], loop)
        self.assertEqual(result['delivery'], {
            'gif': {'loop_policy': 'infinite' if loop else 'play-once',
                    'loop_extension': 0 if loop else None,
                    'verification': 'passed' if verified else 'pending'},
            'mp4': {'loop_policy': 'player-controlled'}})

    def test_recipe_default_and_strict_booleans(self):
        self.assertIs(motion.normalize_recipe({}, (32, 24))['gif_loop'], True)
        for loop in (False, True):
            self.assertIs(motion.normalize_recipe({'gif_loop': loop}, (32, 24))['gif_loop'], loop)
        for invalid in (None, 0, 1, 0.0, 1.0, 'true', 'false', '', [], {}, float('nan')):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'gif_loop must be true or false'):
                motion.normalize_recipe({'gif_loop': invalid}, (32, 24))

    def test_api_override_precedence_and_input_immutability(self):
        out = self.root / 'plan'
        with patch('shutil.which', return_value=None), \
                patch('gif_cinema.motion.run_command', side_effect=AssertionError('Encoder forbidden')):
            # Keep the preexisting five positional arguments working unchanged.
            self.assert_policy(motion.motion(self.source, out, None, None, True), True)
            for chosen in (False, True):
                recipe = {'gif_loop': chosen, 'repeats': 2}
                before = copy.deepcopy(recipe)
                for override in (None, False, True):
                    with self.subTest(chosen=chosen, override=override):
                        result = motion.motion(self.source, out, recipe, dry_run=True, gif_loop=override)
                        self.assert_policy(result, chosen if override is None else override)
                        self.assertEqual(result['recipe']['repeats'], 2)
                        self.assertEqual(recipe, before)
        self.assertFalse(out.exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_invalid_override_is_rejected_before_reading_or_writing(self):
        out = self.root / 'invalid'
        for invalid in (0, 1, .5, 'false', '', [], {}):
            with self.subTest(invalid=invalid), patch.object(motion, 'read_bounded') as read:
                with self.assertRaisesRegex(ValueError, 'gif_loop override'):
                    motion.motion(self.source, out, gif_loop=invalid)
                read.assert_not_called()
        self.assertFalse(out.exists())

    def test_override_cannot_hide_an_invalid_recipe_boolean(self):
        out = self.root / 'invalid'
        for chosen in (None, 0, 1, 'false'):
            for override in (False, True):
                with self.subTest(chosen=chosen, override=override):
                    with self.assertRaisesRegex(ValueError, 'gif_loop must be true or false'):
                        motion.motion(self.source, out, {'gif_loop': chosen}, gif_loop=override)
        self.assertFalse(out.exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_cli_flags_are_mutually_exclusive_and_not_value_options(self):
        parser = cli.build_parser()
        base = ['motion', str(self.source), '--out', str(self.root / 'out')]
        self.assertIsNone(parser.parse_args(base).gif_loop)
        self.assertIs(parser.parse_args(base + ['--play-once']).gif_loop, False)
        self.assertIs(parser.parse_args(base + ['--loop']).gif_loop, True)
        for flags in (['--play-once', '--loop'], ['--loop', '--play-once'],
                      ['--play-once=false'], ['--loop=false']):
            with self.subTest(flags=flags), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(base + flags)

    def test_cli_dry_run_reports_effective_recipe_and_preset_policies(self):
        recipe = self.root / 'recipe.json'
        recipe.write_text(json.dumps({'gif_loop': False}), encoding='utf-8')
        original = recipe.read_bytes()
        cases = [([], True), (['--play-once'], False),
                 (['--preset', 'pop-in', '--play-once'], False),
                 (['--recipe', str(recipe)], False),
                 (['--recipe', str(recipe), '--loop'], True),
                 (['--recipe', str(recipe), '--play-once'], False)]
        out = self.root / 'plan'
        with patch('shutil.which', return_value=None), \
                patch('gif_cinema.motion.run_command', side_effect=AssertionError('Encoder forbidden')):
            for flags, expected in cases:
                with self.subTest(flags=flags):
                    args = cli.build_parser().parse_args(
                        ['motion', str(self.source), '--out', str(out), '--dry-run', *flags])
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        args.func(args)
                    self.assert_policy(json.loads(stdout.getvalue()), expected)
        self.assertFalse(out.exists())
        self.assertEqual(recipe.read_bytes(), original)

    def test_delivery_policy_never_changes_source_timeline_or_transforms(self):
        for playback in ('forward', 'reverse', 'ping-pong'):
            recipe = {'trim_start_ms': 20, 'trim_end_ms': 500, 'speed': 1.25,
                      'playback': playback, 'repeats': 2, 'hold_start_ms': 40,
                      'hold_end_ms': 80, 'keyframes': motion.PRESETS['pop-in']}
            once = motion.motion(self.source, self.root / 'plan', recipe, dry_run=True, gif_loop=False)
            looping = motion.motion(self.source, self.root / 'plan', recipe, dry_run=True, gif_loop=True)
            with self.subTest(playback=playback):
                self.assertEqual(once['timeline'], looping['timeline'])
                self.assertEqual(once['recipe']['keyframes'], looping['recipe']['keyframes'])
                self.assertEqual(once['omitted_source_drawings'], looping['omitted_source_drawings'])
                self.assertEqual(once['source_duration_ms'], 560)
                self.assertEqual(once['source_drawings'], 4)
                self.assertEqual(once['recipe']['playback'], playback)
                self.assertEqual(once['recipe']['repeats'], 2)
                self.assertEqual(once['recipe']['keyframes'][0]['opacity'], 0)
                self.assertEqual(once['recipe']['keyframes'][-1]['opacity'], 1)

    @unittest.skipUnless(HAS_MEDIA, 'FFmpeg/ffprobe required')
    def test_real_modes_preserve_gif_pixels_timing_pngs_mp4_and_source(self):
        recipe = {'trim_start_ms': 20, 'trim_end_ms': 500, 'speed': 1.25,
                  'playback': 'ping-pong', 'repeats': 2, 'hold_start_ms': 40,
                  'hold_end_ms': 80, 'keyframes': motion.PRESETS['pop-in']}
        before = copy.deepcopy(recipe)
        rendered = []
        for name, options, loop in [('legacy', {}, True), ('explicit', {'gif_loop': True}, True),
                                    ('once', {'gif_loop': False}, False)]:
            out = self.root / name
            receipt = motion.motion(self.source, out, recipe, **options)
            self.assert_policy(receipt, loop, verified=True)
            self.assertEqual(receipt['loop_review']['applies_to_gif_delivery'], loop)
            self.assertEqual(receipt, json.loads((out / 'receipt.json').read_text()))
            self.assertEqual(json.loads((out / 'recipe.json').read_text())['gif_loop'], loop)
            self.assertEqual(receipt['timeline']['duration_ms'], 1464)
            self.assertEqual(receipt['timeline']['output_duration_ms'], 1480)
            self.assertEqual(receipt['timeline']['playback_frames'], 37)
            frames = []
            with Image.open(out / 'take.gif') as gif:
                self.assertEqual(gif.info.get('loop'), 0 if loop else None)
                self.assertEqual('loop' in gif.info, loop)
                for frame in ImageSequence.Iterator(gif):
                    frames.append((frame.info['duration'], frame.convert('RGB').tobytes()))
            self.assertEqual(sum(delay for delay, _ in frames), 1480)
            self.assertEqual([delay for delay, _ in frames], receipt['candidate_delays_ms'])
            for row in receipt['samples']:
                png = out / 'frames' / f"{row['frame']:04}.png"
                self.assertEqual(motion.sha(png.read_bytes()), row['png_sha256'])
                with Image.open(png) as image:
                    self.assertEqual(motion.sha(image.tobytes()), row['rgba_sha256'])
            for filename, digest in receipt['outputs'].items():
                self.assertEqual(motion.sha((out / filename).read_bytes()), digest)
            # FFmpeg's raw video output is an independent full decode of every frame.
            decoded_mp4 = subprocess.check_output([
                'ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-i', str(out / 'review.mp4'),
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
            self.assertEqual(len(decoded_mp4), 37 * 32 * 24 * 3)
            self.assertEqual(receipt['probe']['streams'][0]['codec_name'], 'h264')
            self.assertEqual(len(receipt['probe']['streams']), 1)  # Still silent.
            rendered.append((out, receipt, frames, decoded_mp4))
        legacy, explicit, once = rendered
        for other in (explicit, once):
            self.assertEqual(legacy[1]['timeline'], other[1]['timeline'])
            self.assertEqual(legacy[1]['samples'], other[1]['samples'])
            self.assertEqual(legacy[2:], other[2:])
            for png in (legacy[0] / 'frames').glob('*.png'):
                self.assertEqual(png.read_bytes(), (other[0] / 'frames' / png.name).read_bytes())
            for filename in ('first.png', 'last.png', 'review.mp4'):
                self.assertEqual((legacy[0] / filename).read_bytes(), (other[0] / filename).read_bytes())
        looping_bytes = (legacy[0] / 'take.gif').read_bytes()
        self.assertEqual(looping_bytes, (explicit[0] / 'take.gif').read_bytes())
        self.assertEqual(looping_bytes.count(INFINITE_LOOP_EXTENSION), 1)
        self.assertEqual(looping_bytes.replace(INFINITE_LOOP_EXTENSION, b''), (once[0] / 'take.gif').read_bytes())
        with Image.open(once[0] / 'first.png') as first, Image.open(once[0] / 'last.png') as last:
            self.assertIsNone(first.getchannel('A').getbbox())
            self.assertIsNotNone(last.getchannel('A').getbbox())
        self.assertEqual(recipe, before)
        self.assertEqual(self.source.read_bytes(), self.original)

    @unittest.skipUnless(HAS_MEDIA, 'FFmpeg/ffprobe required')
    def test_real_cli_recipe_overrides_and_output_summary(self):
        recipe = self.root / 'recipe.json'
        for flag, recipe_loop, expected in [('--play-once', True, False), ('--loop', False, True)]:
            recipe.write_text(json.dumps({'gif_loop': recipe_loop}), encoding='utf-8')
            original = recipe.read_bytes()
            out = self.root / flag.lstrip('-')
            result = subprocess.run([
                sys.executable, '-m', 'gif_cinema', 'motion', str(self.source), '--recipe', str(recipe),
                flag, '--out', str(out)], check=True, capture_output=True, text=True, timeout=30)
            summary = json.loads(result.stdout)
            receipt = json.loads((out / 'receipt.json').read_text())
            self.assertEqual(summary['delivery'], receipt['delivery'])
            self.assert_policy(receipt, expected, verified=True)
            with Image.open(out / 'take.gif') as gif:
                self.assertEqual('loop' in gif.info, expected)
                self.assertEqual(gif.info.get('loop'), 0 if expected else None)
            self.assertEqual(recipe.read_bytes(), original)
        self.assertEqual(self.source.read_bytes(), self.original)

    @unittest.skipUnless(HAS_MEDIA, 'FFmpeg/ffprobe required')
    def test_static_still_merging_keeps_once_policy_and_full_duration(self):
        source = self.root / 'still.png'
        Image.new('RGBA', (16, 16), (255, 0, 0, 128)).save(source)
        original = source.read_bytes()
        for loop in (False, True):
            out = self.root / f'still-{loop}'
            result = motion.motion(source, out, {'still_duration_ms': 200, 'gif_loop': loop})
            self.assert_policy(result, loop, verified=True)
            self.assertEqual(result['timeline']['playback_frames'], 5)
            self.assertEqual(result['candidate_drawings'], 1)
            self.assertEqual(result['candidate_delays_ms'], [200])
            with Image.open(out / 'take.gif') as gif:
                self.assertEqual(gif.n_frames, 1)
                self.assertEqual('loop' in gif.info, loop)
                self.assertEqual(gif.info['duration'], 200)
            self.assertEqual(int(result['probe']['streams'][0]['nb_read_frames']), 5)
        self.assertEqual(source.read_bytes(), original)

    @unittest.skipUnless(HAS_MEDIA, 'FFmpeg/ffprobe required')
    def test_wrong_encoded_loop_metadata_blocks_publication(self):
        original_save = Image.Image.save
        for requested, encoded in [(False, 0), (False, 1), (True, None), (True, 1)]:
            out = self.root / f'wrong-{requested}-{encoded}'

            def save(image, path, *args, **kwargs):
                if Path(path).name == 'take.gif':
                    kwargs.pop('loop', None)
                    if encoded is not None:
                        kwargs['loop'] = encoded
                return original_save(image, path, *args, **kwargs)

            with self.subTest(requested=requested, encoded=encoded), \
                    patch.object(Image.Image, 'save', save), patch.object(motion, 'run_command') as commands:
                with self.assertRaisesRegex(ValueError, 'Encoded GIF loop policy mismatch'):
                    motion.motion(self.source, out, gif_loop=requested)
                commands.assert_not_called()
            self.assertEqual(list(out.iterdir()), [])
            self.assertEqual(self.source.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
