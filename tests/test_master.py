"""Strict source cadence, exact FFV1 RGBA and honest viewing-copy behavior."""
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave
from PIL import Image
from gif_cinema import cli, factory, master
try:
 import av
except ImportError:
 av = None


def gif(path, colors, delays, size=(24, 24), disposal=1):
    frames = [Image.new('RGBA', size, color) for color in colors]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=delays, disposal=disposal, loop=0, optimize=False)


class MasterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.out = self.root / 'out'
        self.a, self.b = self.root / 'a.gif', self.root / 'b.gif'
        gif(self.a, ['red', 'yellow', 'blue'], [30, 70, 20])
        gif(self.b, ['lime', 'magenta', 'cyan', 'black'], [20, 30, 70, 20])
        self.paths = [self.a, self.b]
        self.net = patch('gif_cinema.cli.urlopen', side_effect=AssertionError('No network'))
        self.net.start(); self.addCleanup(self.net.stop)

    def test_plan_has_exact_centiseconds_and_no_processes_or_writes(self):
        with patch('subprocess.run', side_effect=AssertionError('No subprocess')), patch.object(master, 'require_av', side_effect=AssertionError('No optional dependency needed')):
            result = master.build(self.paths, self.out, preview=True, dry_run=True)
        self.assertEqual(result['duration_cs'], 26)
        self.assertEqual(result['frame_count'], 7)
        self.assertFalse(self.out.exists())

    def test_one_centisecond_is_preserved_as_declared_not_browser_clamped(self):
        gif(self.a, ['red', 'blue'], [10, 150])
        result = master.plan([self.a]); self.assertEqual(result['duration_cs'], 16)
        self.assertEqual(result['sources'][0]['timing'][0]['duration_cs'], 1)

    def test_semantic_hazards_are_explicitly_rejected(self):
        raw = self.a.read_bytes(); control = raw.index(b'\x21\xf9\x04')
        for name, change in [('aspect', (12, 50)), ('interaction', (control + 3, 2)),
                             ('disposal', (control + 3, 16)), ('reserved', (control + 3, 32))]:
            data = bytearray(raw); data[change[0]] = change[1]
            with self.subTest(name=name), self.assertRaises(ValueError): master.metadata(bytes(data))
        data = bytearray(raw); data[control + 4:control + 6] = b'\x00\x00'
        with self.assertRaisesRegex(ValueError, 'zero delay'): master.metadata(bytes(data))
        no_control = raw[:control] + raw[control + 8:]
        with self.assertRaisesRegex(ValueError, 'own nonzero'): master.metadata(no_control)

    def test_resource_limits_checked_before_encoding(self):
        for key in ['MAX_INPUT_BYTES', 'MAX_PIXELS', 'MAX_DURATION_CS', 'MAX_PREVIEW_PIXELS']:
            with self.subTest(key=key), patch.object(master, key, 1), self.assertRaises(ValueError):
                master.plan(self.paths, preview=True)

    def test_audio_requires_explicit_viewing_copy(self):
        with self.assertRaisesRegex(ValueError, 'request --preview'): master.plan(self.paths, audio=self.a)

    def test_existing_output_and_dangling_symlink_not_replaced(self):
        self.out.mkdir(); (self.out / 'keep').write_text('accepted')
        with self.assertRaises(ValueError): master.build(self.paths, self.out)
        self.assertEqual((self.out / 'keep').read_text(), 'accepted')
        alias = self.root / 'alias'
        try: alias.symlink_to(self.root / 'absent', target_is_directory=True)
        except OSError: return
        with self.assertRaises(ValueError): master.build(self.paths, alias)

    def test_mux_write_budget_is_enforced_before_growth(self):
        path = self.root / 'limited'
        with patch.object(master, 'MAX_MASTER_BYTES', 4):
            sink = master.LimitedFile(path)
            try:
                sink.write(b'1234')
                with self.assertRaises(ValueError): sink.write(b'5')
                self.assertEqual(sink.tell(), 4)
            finally: sink.close()
        self.assertEqual(path.stat().st_size, 4)

    @unittest.skipUnless(av, 'Install optional lossless extra (PyAV)')
    def test_identical_stored_descriptors_are_not_coalesced(self):
        raw = self.a.read_bytes()
        first = raw.index(b'\x21\xf9\x04'); second = raw.index(b'\x21\xf9\x04', first + 1)
        self.a.write_bytes(raw[:second] + raw[first:second] + raw[second:])
        report = master.build([self.a], self.out)
        self.assertEqual(report['frame_count'], 4)
        self.assertEqual(report['frames'][0]['canvas_rgba_sha256'], report['frames'][1]['canvas_rgba_sha256'])
        self.assertEqual([f['pts_cs'] for f in report['frames'][:2]], [0, 3])
        self.assertEqual(report['verification']['frames'], 4)

    @unittest.skipUnless(av, 'Install optional lossless extra (PyAV)')
    def test_2000_drawings_across_twenty_shots_keep_the_complete_timeline(self):
        paths = []
        for shot in range(20):
            path = self.root / f'long-{shot:02}.gif'
            colors = [(n, (n * 7 + shot) % 256, (n * 13) % 256, 255) for n in range(100)]
            gif(path, colors, [20, 30, 50, 90] * 25, size=(32, 32))
            paths.append(path)
        report = master.build(paths, self.out)
        self.assertEqual(report['verification']['frames'], 2000)
        self.assertEqual(report['verification']['duration_ms'], 95000)
        for shot in range(20):
            self.assertEqual(report['frames'][shot * 100]['pts_cs'], shot * 475)
        self.assertEqual(report['frames'][-1]['duration_cs'], 9)

    @unittest.skipUnless(av and shutil.which('ffmpeg'), 'PyAV/FFmpeg required')
    def test_independent_ffmpeg_decoder_matches_all_master_rgba(self):
        report = master.build(self.paths, self.out)
        raw = cli.run_media(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(self.out / 'master.mkv'),
                            '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-']).stdout
        stride = report['width'] * report['height'] * 4
        self.assertEqual(len(raw), report['frame_count'] * stride)
        for frame in report['frames']:
            index = frame['index']
            self.assertEqual(factory.digest(raw[index * stride:(index + 1) * stride]), frame['canvas_rgba_sha256'])

    @unittest.skipUnless(av, 'Install optional lossless extra (PyAV)')
    def test_exact_rgba_pts_delays_and_final_hold(self):
        before = [p.read_bytes() for p in self.paths]
        report = master.build(self.paths, self.out)
        self.assertEqual(report['verification']['frames'], 7)
        self.assertEqual(report['verification']['duration_ms'], 260)
        self.assertEqual([f['pts_cs'] for f in report['frames']], [0, 3, 10, 12, 14, 17, 24])
        self.assertEqual([f['duration_cs'] for f in report['frames']], [3, 7, 2, 2, 3, 7, 2])
        self.assertEqual(master.verify_master(self.out / 'master.mkv', report), report['verification'])
        self.assertEqual(before, [p.read_bytes() for p in self.paths])
        self.assertEqual(report['visual_review'], 'pending')

    @unittest.skipUnless(av, 'Install optional lossless extra (PyAV)')
    def test_one_frame_static_and_long_final_hold(self):
        gif(self.a, ['red'], [150])
        report = master.build([self.a], self.out)
        self.assertEqual(report['frame_count'], 1)
        self.assertEqual(report['verification']['duration_ms'], 150)

    @unittest.skipUnless(av, 'Install optional lossless extra (PyAV)')
    def test_one_pixel_dimension_uses_verified_compatible_ffv1_level(self):
        for size in [(1, 4), (1, 4096), (4096, 1)]:
            with self.subTest(size=size):
                path = self.root / f'narrow-{size[0]}-{size[1]}.gif'
                gif(path, ['red', 'blue'], [10, 150], size=size)
                report = master.build([path], self.root / f'narrow-out-{size[0]}-{size[1]}')
                self.assertEqual(report['ffv1_options'], {'level': '1'})
                self.assertEqual(report['verification']['duration_ms'], 160)

    @unittest.skipUnless(av, 'Install optional lossless extra (PyAV)')
    def test_alpha_disposal_odd_sizes_and_padding_preserve_source_pixels(self):
        for disposal in (1, 2, 3):
            path = self.root / f'disposal-{disposal}.gif'
            frames = [Image.new('RGBA', (25, 21), (10, 40, 90, 0)) for _ in range(3)]
            for index, frame in enumerate(frames):
                for x in range(index * 4, index * 4 + 3): frame.putpixel((x, 10), (255, 0, 90, 255))
            frames[0].save(path, save_all=True, append_images=frames[1:], duration=[30, 70, 150], disposal=disposal, transparency=0, optimize=False)
            report = master.build([path, self.b], self.root / f'alpha-{disposal}')
            self.assertEqual(report['verification']['rgba_mismatches'], 0)
            self.assertEqual((report['width'], report['height']), (25, 24))
            with Image.open(path) as source:
                source.seek(0); self.assertEqual(report['frames'][0]['source_rgba_sha256'], factory.digest(source.convert('RGBA').tobytes()))

    @unittest.skipUnless(av, 'Install optional lossless extra (PyAV)')
    def test_movie_proof_rejects_forged_frame_hash_or_duration(self):
        report = master.build(self.paths, self.out)
        for key, value in [('canvas_rgba_sha256', '0' * 64), ('duration_cs', 999)]:
            edited = json.loads(json.dumps(report)); edited['frames'][0][key] = value
            with self.assertRaises(ValueError): master.verify_master(self.out / 'master.mkv', edited)

    @unittest.skipUnless(av, 'Install optional lossless extra (PyAV)')
    def test_changed_source_after_plan_and_failed_publication_leave_no_output(self):
        original = master.plan
        def mutate(*args, **kwargs):
            result = original(*args, **kwargs); self.a.write_bytes(self.a.read_bytes() + b'changed'); return result
        with patch.object(master, 'plan', side_effect=mutate), self.assertRaisesRegex(ValueError, 'changed after'):
            master.build(self.paths, self.out)
        self.assertFalse(self.out.exists())
        with patch.object(cli, 'publish_file', side_effect=OSError('injected')), self.assertRaises(OSError):
            master.build(self.paths, self.out)
        self.assertFalse(self.out.exists())

    @unittest.skipUnless(av and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'PyAV/FFmpeg/ffprobe required')
    def test_preview_preserves_every_drawing_hold_on_the_100hz_grid(self):
        report = master.build(self.paths, self.out, preview=True)
        raw = cli.run_media(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(self.out / 'preview.mp4'), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']).stdout
        stride = 24 * 24 * 3
        self.assertEqual(len(raw), 26 * stride)
        expected = [(255, 0, 0)] * 3 + [(255, 255, 0)] * 7 + [(0, 0, 255)] * 2 + [(0, 255, 0)] * 2 + [(255, 0, 255)] * 3 + [(0, 255, 255)] * 7 + [(0, 0, 0)] * 2
        for index, color in enumerate(expected):
            frame = Image.frombytes('RGB', (24, 24), raw[index * stride:(index + 1) * stride])
            self.assertLessEqual(max(abs(a-b) for a,b in zip(frame.getpixel((12,12)), color)), 8, index)
        self.assertEqual(report['viewing_copy']['duration_ms'], 260)

    @unittest.skipUnless(av and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'PyAV/FFmpeg/ffprobe required')
    def test_preview_budget_overshoot_is_rejected_before_publication(self):
        for limit in (1, 500):
            with self.subTest(limit=limit), patch.object(master, 'MAX_PREVIEW_BYTES', limit):
                with self.assertRaises(ValueError): master.build(self.paths, self.out, preview=True)
                self.assertFalse(self.out.exists())

    def test_empty_probe_is_a_clear_validation_error(self):
        result = subprocess.CompletedProcess([], 0, stdout=b'{"streams": []}')
        with patch.object(cli, 'run_media', return_value=result), self.assertRaisesRegex(ValueError, 'probe metadata'):
            master.probe_stream(self.a, 'v:0', 'codec_name')

    def audio(self, seconds):
        path = self.root / f'audio-{seconds}.wav'
        samples = [0] * round(seconds * 48000)
        for at in (1920, 5760, 9600):
            for n in range(at, min(at + 48, len(samples))): samples[n] = 18000
        with wave.open(str(path), 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(48000)
            stream.writeframes(struct.pack('<' + 'h' * len(samples), *samples))
        return path

    @unittest.skipUnless(av and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'PyAV/FFmpeg/ffprobe required')
    def test_short_and_long_audio_never_shorten_film_or_add_long_tail(self):
        for seconds in (.08, 1.0):
            with self.subTest(seconds=seconds):
                audio = self.audio(seconds); out = self.root / f'audio-out-{seconds}'
                report = master.build(self.paths, out, preview=True, audio=audio)
                self.assertEqual(report['viewing_copy']['frames'], 26)
                self.assertEqual(report['viewing_copy']['audio']['target_samples'], 12480)
                info = json.loads(cli.run_media(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(out / 'preview.mp4')]).stdout)
                self.assertAlmostEqual(float(info['format']['duration']), .26, places=3)
                raw = cli.run_media(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(out / 'preview.mp4'), '-map', '0:a:0', '-f', 'f32le', '-ac', '1', '-ar', '48000', '-']).stdout
                samples = struct.unpack('<'+'f'*(len(raw)//4), raw)
                # AAC decoding can expose ≤one codec block of padding; it is not original PCM preservation.
                self.assertLessEqual(len(samples), 12480 + 1024)
                for at in ([1920] if seconds < .12 else [1920, 5760, 9600]):
                    peak = max(range(at-10, at+60), key=lambda n:abs(samples[n]))
                    self.assertLessEqual(abs(peak-at), 48)
                self.assertEqual(report['verification']['duration_ms'], 260)


if __name__ == '__main__': unittest.main()
