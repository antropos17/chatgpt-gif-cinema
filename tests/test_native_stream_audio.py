"""Exact legacy PCM oracle and bounded native soundtrack synthesis."""
import array
import contextlib
import copy
from fractions import Fraction
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import random
import shutil
import tempfile
import tracemalloc
import unittest
from unittest import mock
import wave

from gif_cinema import shots
from gif_cinema.shot_project import load_project
from gif_cinema.shot_renderer import Renderer
from test_native_shots import fixture


class LegacyRenderer:
    # Frozen sound implementation from 4087023, not the optimized renderer.
    def sound(self, path):
        p = self.project; audio = p['audio']; rate = audio['rate']
        duration = audio['duration']; n = round(duration*rate)
        left, right = [0.0]*n, [0.0]*n
        for event in audio['tones']:
            start, length, freq, gain, pan = event
            begin, count = round(start*rate), round(length*rate)
            for j in range(min(count, n-begin)):
                u = j/rate; envelope = (1-math.exp(-u*40))*math.exp(-u*3/max(.1, length))
                v = (math.sin(math.tau*freq*u)+.3*math.sin(math.tau*freq*2.003*u))*envelope*gain
                left[begin+j] += v*(1-pan)*.5; right[begin+j] += v*(1+pan)*.5
        for start, end, seed, gain in audio['noise']:
            rng = random.Random(seed); v = 0
            for i in range(round(start*rate), round(end*rate)):
                u = (i/rate-start)/(end-start); v = .88*v+.12*rng.uniform(-1, 1)
                val = v*math.sin(math.pi*u)**2*gain; pan = math.sin(u*math.pi-math.pi/2)
                left[i] += val*(1-pan); right[i] += val*(1+pan)
        out = array.array('h')
        lo = round(p['scenes'][0]['start_frame']/p['fps']*rate)
        hi = round(p['scenes'][-1]['end_frame']/p['fps']*rate)
        for i in range(lo, hi):
            fade = min(1, i/rate/audio['fade_in'], (duration-i/rate)/audio['fade_out'])
            out.extend([round(math.tanh(left[i])*fade*26000), round(math.tanh(right[i])*fade*26000)])
        if __import__('sys').byteorder != 'little':
            out.byteswap()
        with wave.open(str(path), 'wb') as stream:
            stream.setnchannels(2); stream.setsampwidth(2); stream.setframerate(rate); stream.writeframes(out.tobytes())


def project(rate=8000, duration=1.2, fps=25, first=0, last=25):
    return {'fps': fps, 'scenes': [{'start_frame': first, 'end_frame': last}],
        'audio': {'rate': rate, 'duration': duration, 'fade_in': .07, 'fade_out': .13,
                  'tones': [[0, .7, 311, .8, -.6], [.15, 1, 427, .9, .4]],
                  'noise': [[0, duration, 13, .8], [.1, duration, 99, .7]]}}


def render_sound(cls, value, path):
    instance = object.__new__(cls)
    instance.project = value
    instance.sound(path)
    return path.read_bytes()


class StreamAudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def equal(self, value):
        before = copy.deepcopy(value)
        original = render_sound(LegacyRenderer, value, self.root/'old.wav')
        actual = render_sound(Renderer, value, self.root/'new.wav')
        self.assertEqual(actual, original)
        self.assertEqual(value, before)
        with wave.open(str(self.root/'new.wav'), 'rb') as wav:
            rate = value['audio']['rate']
            frames = round(value['scenes'][-1]['end_frame']/value['fps']*rate) - round(value['scenes'][0]['start_frame']/value['fps']*rate)
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()),
                             (2, 2, rate, frames))
            self.assertEqual(len(wav.readframes(frames+1)), frames*4)
        return actual

    def test_seeded_noise_continues_across_blocks_and_crop(self):
        value = project(duration=2, first=17, last=45)
        self.equal(value)
        full = copy.deepcopy(value); full['scenes'][0]['start_frame'] = 0
        self.equal(full)
        with wave.open(str(self.root/'new.wav'), 'rb') as wav:
            all_pcm = wav.readframes(wav.getnframes())
        self.equal(value)
        with wave.open(str(self.root/'new.wav'), 'rb') as wav:
            self.assertEqual(wav.readframes(wav.getnframes()), all_pcm[round(17/25*8000)*4:])

    def test_many_overlapping_tones_noise_and_stereo_extremes(self):
        value = project()
        value['audio']['tones'] = [[i*.00017, .9, 100+i*17, 1, (-1,0,1)[i%3]] for i in range(128)]
        value['audio']['noise'] = [[0, 1.2, i, 1] for i in range(32)]
        self.equal(value)

    def test_rounded_event_boundaries_and_short_final_blocks(self):
        for rate, fps, last in ((8190, 2, 1), (8192, 2, 1), (8194, 2, 1), (8001, 30, 17), (44100, 60, 17)):
            value = project(rate=rate, duration=1.2, fps=fps, last=last)
            value['audio']['tones'] += [[4095.5/rate, .3, 333, 1, -1],
                [4096.5/rate, .3, 222, 1, 1], [0.5/rate, .00001, 111, 1, 0],
                [1.2, 30, 111, 1, 0]]
            value['audio']['noise'] += [[4095.5/rate, 1.2, 133, 1], [4096.5/rate, 1.2, 134, 1]]
            with self.subTest(rate=rate, fps=fps): self.equal(value)

    def test_silent_zero_gain_and_events_after_selected_end(self):
        value = project(duration=2, last=4)
        value['audio']['tones'] = [[1, 1, 440, 1, 0], [0, 2, 440, 0, 1]]
        value['audio']['noise'] = [[1, 2, 42, 1], [0, 2, 12, 0]]
        raw = self.equal(value)
        self.assertEqual(set(raw[44:]), {0})
        value['audio']['tones'] = []; value['audio']['noise'] = []
        self.equal(value)

    def test_randomized_clocks_events_and_cropped_ranges(self):
        rng = random.Random(20261116)
        for case in range(16):
            rate = rng.choice((8000, 8001, 11025, 16000, 22050, 24000, 32000, 44100, 48000))
            fps = rng.choice((24, 25, 30, 50, 60)); end = rng.randint(fps//2, fps)
            value = project(rate=rate, fps=fps, first=rng.randrange(end), last=end)
            value['audio']['fade_in'] = rng.choice((.00001, .1, 3))
            value['audio']['fade_out'] = rng.choice((.00001, .1, 3))
            value['audio']['tones'] = [[rng.random(), rng.uniform(.00001, 2), rng.uniform(1, rate/2), rng.random(), rng.uniform(-1,1)] for _ in range(6)]
            value['audio']['noise'] = [[rng.random(), 1.2, rng.randrange(1000000), rng.random()] for _ in range(3)]
            with self.subTest(case=case,rate=rate,fps=fps): self.equal(value)

    def test_live_recipe_edits_and_repeated_calls_do_not_reuse_noise_state(self):
        value = project()
        a = self.equal(value)
        self.assertEqual(self.equal(value), a)
        value['audio']['noise'][0][2] += 1
        self.assertNotEqual(self.equal(value), a)

    def test_pcm_writes_are_bounded_even_for_long_sources(self):
        value = project(duration=12, last=290)
        lengths = []; original = wave.Wave_write.writeframesraw
        def record(wav, data):
            lengths.append(len(data)); return original(wav, data)
        with mock.patch.object(wave.Wave_write, 'writeframesraw', record):
            render_sound(Renderer, value, self.root/'bounded.wav')
        self.assertGreater(len(lengths), 20)
        self.assertLessEqual(max(lengths), 4096*4)
        self.assertEqual(sum(lengths), round(290/25*8000)*4)

    def test_python_peak_does_not_scale_with_total_samples(self):
        peaks = []
        for last in (25, 250):
            value = project(duration=11, last=last)
            value['audio']['tones'] = [[0, 11, 440, .2, 0]]
            value['audio']['noise'] = [[0, 11, 123, .2]]
            tracemalloc.start()
            try:
                render_sound(Renderer, value, self.root/'memory.wav')
                peaks.append(tracemalloc.get_traced_memory()[1])
            finally: tracemalloc.stop()
        # Includes the helper's readback (up to320kB), unlike the production stream.
        self.assertLess(max(peaks), 1024*1024)
        self.assertLess(peaks[1], peaks[0]+512*1024)

    def test_benchmark_refuses_unknown_reference_before_execution(self):
        source = Path(__file__).resolve().parents[1]/'tools/benchmark_stream_audio.py'
        spec = importlib.util.spec_from_file_location('audio_benchmark', source)
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        bad = self.root/'bad.py'
        bad.write_text('raise AssertionError("must not execute")')
        with self.assertRaisesRegex(ValueError, 'exact 4087023'):
            tool.reference(bad)

    def test_write_failure_closes_wave_handle(self):
        value = project()
        handles=[]; original=wave.open
        def opened(*args, **kwargs):
            wav=original(*args, **kwargs); handles.append(wav); return wav
        with mock.patch('wave.open', side_effect=opened), mock.patch.object(wave.Wave_write, 'writeframesraw', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                render_sound(Renderer, value, self.root/'failed.wav')
        self.assertIsNone(handles[0]._file)

    @unittest.skipUnless(shutil.which('ffmpeg') and importlib.util.find_spec('av'), 'FFmpeg and PyAV required')
    def test_real_export_bytes_clocks_and_failed_audio_resume(self):
        value=fixture(self.root)
        value['audio'].update(tones=project()['audio']['tones'],noise=project(duration=1)['audio']['noise'])
        path=self.root/'project.json'; path.write_text(json.dumps(value))
        load_project(path)
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(Renderer,'sound',LegacyRenderer.sound):
            shots.build_project(path,self.root/'before')
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(wave.Wave_write,'writeframesraw',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):
                shots.build_project(path,self.root/'after')
        self.assertFalse((self.root/'after/build-receipt.json').exists())
        self.assertFalse((self.root/'after/film.mp4').exists())
        partial=list((self.root/'after').glob('sound-*.wav'))
        self.assertEqual(len(partial),1)
        with contextlib.redirect_stdout(io.StringIO()):
            result=shots.build_project(path,self.root/'after',resume=True)
        self.assertEqual(result['scene_exports']['resumed'],2)
        self.assertEqual(shots.verify_project(self.root/'after')['status'],'verified')
        self.assertEqual((self.root/'before/film.mp4').read_bytes(),(self.root/'after/film.mp4').read_bytes())
        receipts=[shots.read_json(self.root/name/'build-receipt.json') for name in ('before','after')]
        self.assertEqual(receipts[0]['audio_sha256'],receipts[1]['audio_sha256'])
        self.assertTrue(partial[0].exists(), 'Failed private attempt is preserved, not mistaken for selected audio')
        import av
        with av.open(str(self.root/'after/film.mp4')) as movie:
            for index,frame in enumerate(movie.decode(video=0)):
                shots.verify_video_clock(frame,index,25,(16,16),'test')
            self.assertEqual(index+1,8)
        for row in receipts[0]['completed']:
            self.assertEqual(receipts[0]['completed'][row]['rgb_sha256'],receipts[1]['completed'][row]['rgb_sha256'])
