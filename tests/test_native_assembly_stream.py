"""Single-pass final assembly retains validation and publishes only after exhaustion."""
import copy
from fractions import Fraction
import importlib.util
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image
from gif_cinema import shots
from test_native_shots import fixture


class Frame:
    def __init__(self, color, index=0, size=(16, 16)):
        self.image = Image.new('RGB', size, color)
        self.width, self.height = size
        self.pts, self.time_base, self.duration = index, Fraction(1, 25), 1
        self.conversions = 0

    def to_image(self):
        self.conversions += 1
        return self.image


class VerifiedSceneStreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.project = fixture(self.root)
        self.path = self.root/'project.json'
        self.path.write_text(json.dumps(self.project))
        self.context = shots.BuildContext(self.path)
        self.scene = self.root/'scene.mkv'
        self.scene.write_bytes(b'independent decoder fixture')
        self.frames = [Frame('red', 0), Frame('blue', 1), Frame('green', 2)]
        self.record = dict(file='scene.mkv', key='k', frames=3,
                           sha256=shots.sha(self.scene.read_bytes()),
                           rgb_sha256=[shots.sha(f.image.tobytes()) for f in self.frames])
        self.closed = False

    def decoder(self, path):
        try:
            yield from self.frames
        finally:
            self.closed = True

    def consume(self):
        with mock.patch.object(shots, 'video_frames', self.decoder):
            return list(self.context.verified_scene_images(self.root, self.record, 'k'))

    def test_one_decode_and_one_conversion_per_frame(self):
        with mock.patch.object(shots, 'video_frames', wraps=self.decoder) as decode:
            images = list(self.context.verified_scene_images(self.root, self.record, 'k'))
        self.assertEqual(decode.call_count, 1)
        self.assertEqual([im.tobytes() for im in images], [f.image.tobytes() for f in self.frames])
        self.assertEqual([f.conversions for f in self.frames], [1, 1, 1])
        self.assertTrue(self.closed)

    def test_file_hash_key_and_record_count_rejected_before_decode(self):
        for field, bad in [('sha256', 'bad'), ('key', 'bad'), ('frames', 2), ('frames', True)]:
            with self.subTest(field=field, bad=bad):
                record = {**self.record, field: bad}
                with mock.patch.object(shots, 'video_frames') as decode:
                    with self.assertRaises(ValueError):
                        list(self.context.verified_scene_images(self.root, record, 'k'))
                decode.assert_not_called()

    def test_bad_pixels_geometry_pts_and_missing_pts_close_decoder(self):
        for kind in ('pixel', 'size', 'pts', 'missing_pts', 'missing_time_base'):
            with self.subTest(kind=kind):
                self.closed = False
                frame = Frame('blue', 1)
                if kind == 'pixel': frame.image = Image.new('RGB', (16, 16), 'white')
                if kind == 'size': frame.width = 15
                if kind == 'pts': frame.pts = 2
                if kind == 'missing_pts': frame.pts = None
                if kind == 'missing_time_base': frame.time_base = None
                self.frames[1] = frame
                with self.assertRaises(ValueError): self.consume()
                self.assertTrue(self.closed)

    def test_short_extra_empty_and_late_decoder_error(self):
        original = self.frames[:]
        for frames in (original[:-1], [], original+[Frame('green', 3)]):
            self.frames = frames
            with self.assertRaises(ValueError): self.consume()
            self.assertTrue(self.closed)
        def broken(path):
            yield from original
            raise RuntimeError('decoder failure at EOF')
        with mock.patch.object(shots, 'video_frames', broken):
            with self.assertRaisesRegex(RuntimeError, 'EOF'):
                list(self.context.verified_scene_images(self.root, self.record, 'k'))

    def test_changed_or_replaced_file_after_buffered_last_frame_is_rejected(self):
        for replace in (False, True):
            self.scene.write_bytes(b'independent decoder fixture')
            def decode(path):
                yield from self.frames
                if replace:
                    replacement = self.root/'replacement'
                    replacement.write_bytes(b'other same-path file')
                    replacement.replace(path)
                else:
                    path.write_bytes(b'mutated')
            with mock.patch.object(shots, 'video_frames', decode):
                with self.assertRaisesRegex(ValueError, 'changed during decoding'):
                    list(self.context.verified_scene_images(self.root, self.record, 'k'))

    def test_early_close_releases_decoder_without_claiming_completion(self):
        with mock.patch.object(shots, 'video_frames', self.decoder), mock.patch.object(shots, 'regular', wraps=shots.regular) as read:
            images = self.context.verified_scene_images(self.root, self.record, 'k')
            next(images)
            images.close()
            self.assertTrue(self.closed)
            self.assertEqual(read.call_count, 1, 'Early close must not masquerade as completed verification')

    def test_verify_scene_keeps_path_return_and_exhausts_all_checks(self):
        with mock.patch.object(shots, 'video_frames', wraps=self.decoder) as decode:
            self.assertEqual(self.context.verify_scene(self.root, self.record, 'k'), self.scene)
        self.assertEqual(decode.call_count, 1)
        self.assertTrue(self.closed)


@unittest.skipUnless(shutil.which('ffmpeg') and importlib.util.find_spec('av'), 'FFmpeg and PyAV required')
class AssemblyPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root/'project.json'
        self.path.write_text(json.dumps(fixture(self.root)))

    def test_real_assembly_opens_each_scene_once_and_preserves_clock_audio(self):
        import av
        out = self.root/'out'
        real_encode, real_decode = shots.encode, shots.video_frames
        active, calls = [False], []
        def decode(path):
            if active[0]: calls.append(path)
            yield from real_decode(path)
        def encode(command, images):
            active[0] = 'libx264' in command
            try: return real_encode(command, images)
            finally: active[0] = False
        with mock.patch.object(shots, 'encode', encode), mock.patch.object(shots, 'video_frames', decode):
            shots.build_project(self.path, out)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(set(calls)), 2)
        rec = shots.read_json(out/'build-receipt.json')
        for key in rec['completed']:
            record = rec['completed'][key]
            frames = list(real_decode(out/record['file']))
            self.assertEqual([shots.sha(f.to_image().convert('RGB').tobytes()) for f in frames], record['rgb_sha256'])
            self.assertEqual([f.pts*f.time_base for f in frames], [Fraction(i, 25) for i in range(4)])
            self.assertTrue(all(f.duration*f.time_base == Fraction(1, 25) for f in frames))
        frames = list(real_decode(out/'film.mp4'))
        self.assertEqual(len(frames), 8)
        self.assertEqual([f.pts*f.time_base for f in frames], [Fraction(i, 25) for i in range(8)])
        self.assertTrue(all(f.duration*f.time_base == Fraction(1, 25) for f in frames))
        with av.open(str(out/'film.mp4')) as media:
            self.assertEqual(media.streams.audio[0].channels, 2)
            self.assertGreater(sum(f.samples for f in media.decode(audio=0)), 0)
        self.assertEqual(shots.verify_project(out)['status'], 'verified')

    def test_late_failures_never_publish_and_unchanged_scenes_resume(self):
        for failure in ('mutation', 'previous_mutation', 'short', 'extra', 'decoder'):
            with self.subTest(failure=failure):
                out = self.root/failure
                real_encode, real_decode = shots.encode, shots.video_frames
                active, restored = [False], {}
                def encode(command, images):
                    active[0] = 'libx264' in command
                    try: return real_encode(command, images)
                    finally: active[0] = False
                def decode(path):
                    if not active[0] or not path.name.startswith('second-'):
                        yield from real_decode(path)
                        return
                    frames = list(real_decode(path))
                    if failure == 'short':
                        yield from frames[:-1]
                        return
                    yield from frames
                    if failure in ('mutation', 'previous_mutation'):
                        if failure == 'previous_mutation':
                            path = next((out/'scenes').glob('first-*.mkv'))
                        restored[path] = path.read_bytes()
                        path.write_bytes(b'corrupted after decoder buffered all good frames')
                    elif failure == 'extra': yield frames[-1]
                    elif failure == 'decoder': raise RuntimeError('late decode failure')
                with mock.patch.object(shots, 'encode', encode), mock.patch.object(shots, 'video_frames', decode):
                    with self.assertRaises((ValueError, RuntimeError)):
                        shots.build_project(self.path, out)
                self.assertFalse((out/'film.mp4').exists())
                self.assertFalse((out/'build-receipt.json').exists())
                state = shots.read_json(out/'checkpoint.json')
                self.assertEqual(len(state['completed']), 2)
                if failure != 'previous_mutation': self.assertNotIn('ready', state)
                for path, raw in restored.items(): path.write_bytes(raw)
                result = shots.build_project(self.path, out, resume=True)
                self.assertEqual(result['scene_exports'], dict(rendered=0, reused=0, resumed=2))
                self.assertEqual(shots.verify_project(out)['status'], 'verified')

    def test_real_corruption_fails_even_with_matching_file_hash(self):
        out = self.root/'corruption'
        shots.build_project(self.path, out)
        rec = shots.read_json(out/'build-receipt.json')
        record = copy.deepcopy(rec['completed']['second'])
        path = out/record['file']
        path.write_bytes(b'not a Matroska stream')
        record['sha256'] = shots.sha(path.read_bytes())
        with self.assertRaises(Exception):
            list(shots.BuildContext(self.path).verified_scene_images(out, record, record['key']))


class EncoderCleanupTests(unittest.TestCase):
    def test_broken_pipe_closes_suspended_input_and_pipe(self):
        closed = []
        def images():
            try:
                yield Image.new('RGB', (16, 16))
            finally:
                closed.append(True)
        process = mock.Mock()
        events = []
        process.terminate.side_effect = lambda: events.append('terminate')
        process.stdin.close.side_effect = lambda: events.append('close')
        process.stdin.write.side_effect = BrokenPipeError('encoder exited')
        process.poll.return_value = None
        with mock.patch.object(shots.subprocess, 'Popen', return_value=process):
            with self.assertRaises(BrokenPipeError):
                shots.encode(['fake-test-encoder'], images())
        self.assertEqual(closed, [True])
        process.stdin.close.assert_called_once()
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)
        self.assertEqual(events, ['terminate', 'close'], 'Never flush a pipe before stopping a live failed encoder')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_real_encoder_failure_closes_input(self):
        closed = []
        def images():
            try:
                for _ in range(20):
                    yield Image.new('RGB', (128, 128))
            finally:
                closed.append(True)
        with self.assertRaises((BrokenPipeError, RuntimeError)):
            shots.encode(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo',
                          '-pix_fmt', 'rgb24', '-s', '128x128', '-i', 'pipe:0',
                          '-c:v', 'gif_cinema_intentionally_missing_encoder', '-f', 'null', '-'], images())
        self.assertEqual(closed, [True])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux pipe capacity API required")
    def test_stalled_encoder_cleanup_never_flushes_a_full_pipe_first(self):
        code = "\nimport sys, fcntl\nfrom unittest.mock import patch\nfrom gif_cinema import shots\noriginal = shots.subprocess.Popen\nholder=[]\ndef launch(*a, **kw):\n p=original(*a, **kw); holder.append(p); return p\nclass Bytes:\n def __init__(self, size): self.size=size\n def tobytes(self): return b'x'*self.size\ndef images():\n capacity=fcntl.fcntl(holder[0].stdin.fileno(), fcntl.F_GETPIPE_SZ)\n yield Bytes(capacity)\n yield Bytes(1)\n raise ValueError('late input failure')\nwith patch.object(shots.subprocess, 'Popen', launch):\n try: shots.encode([sys.executable,'-c','import time; time.sleep(30)'], images())\n except ValueError: print('returned', flush=True)\n"
        child = subprocess.Popen([sys.executable, '-c', code], start_new_session=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = child.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.communicate()
            self.fail('Encoder cleanup blocked flushing a full pipe before termination')
        self.assertEqual(child.returncode, 0, stderr.decode(errors='replace'))
        self.assertEqual(stdout, b'returned\n')
