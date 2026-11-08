"""Standalone film shares the bounded audio contract without provider requests."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gif_cinema import audio, cli, doctor
from test_audio_preflight import wav_bytes
from test_reliability import animation


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
class StandaloneFilmAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clip, self.sound, self.out = self.root / 'input.gif', self.root / 'input.wav', self.root / 'film.mp4'
        self.clip.write_bytes(animation((1000, 1000)))
        self.sound.write_bytes(wav_bytes())
        network = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden'))
        network.start(); self.addCleanup(network.stop)
        provider = patch.object(cli, 'request_gif', side_effect=AssertionError('Provider forbidden'))
        provider.start(); self.addCleanup(provider.stop)

    def args(self, *flags, sound=True):
        command = ['film', str(self.clip), '--width', '32', '--height', '32', '--fps', '25', '-o', str(self.out)]
        if sound:
            command += ['--audio', str(self.sound)]
        return cli.build_parser().parse_args(command + list(flags))

    def run_film(self, *flags, sound=True):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = cli.film(self.args(*flags, sound=sound))
        self.assertIsNone(result)  # Keep the existing programmatic return contract.
        self.assertEqual(output.getvalue(), f'Created movie: {self.out.resolve()}\n')

    def assert_no_staging(self):
        self.assertEqual(list(self.root.glob('*.lock')), [])
        self.assertEqual(set(self.root.glob('*.mp4')), {self.out} if self.out.exists() else set())

    def test_truncated_empty_or_invalid_audio_cannot_replace_an_accepted_movie(self):
        self.run_film()
        original = self.out.read_bytes()
        for raw in (wav_bytes()[:48044], wav_bytes(0), b'not audio'):
            with self.subTest(bytes=len(raw)):
                self.sound.write_bytes(raw)
                with patch.object(cli, '_encode_film') as encoder:
                    with self.assertRaisesRegex(ValueError, 'Audio'):
                        cli.film(self.args('--force'))
                    encoder.assert_not_called()
                self.assertEqual(self.out.read_bytes(), original)
                self.assertEqual(self.sound.read_bytes(), raw)
                self.assert_no_staging()

    def test_invalid_audio_does_not_create_destination_directory(self):
        self.sound.write_bytes(b'not audio')
        self.out = self.root / 'new' / 'nested' / 'film.mp4'
        with self.assertRaisesRegex(ValueError, 'Audio probe failed'):
            cli.film(self.args())
        self.assertFalse(self.out.parent.exists())

    def test_existing_output_without_force_does_not_start_audio_preflight(self):
        self.out.write_bytes(b'previous movie')
        with patch.object(audio, 'prepare_audio') as prepare, self.assertRaisesRegex(ValueError, 'already exists'):
            cli.film(self.args())
        prepare.assert_not_called()
        self.assertEqual(self.out.read_bytes(), b'previous movie')

    def test_audio_source_cannot_be_its_own_output(self):
        self.sound = self.root / 'audio-container.mp4'
        original = wav_bytes()
        self.sound.write_bytes(original)
        self.out = self.sound
        with patch.object(audio, 'prepare_audio') as prepare, self.assertRaisesRegex(ValueError, 'replace an input'):
            cli.film(self.args('--force'))
        prepare.assert_not_called()
        self.assertEqual(self.sound.read_bytes(), original)

    def test_missing_ffprobe_has_actionable_error_before_snapshot_or_output(self):
        with patch.object(doctor, 'inspect_tool', return_value={'available': False}) as inspect, \
                patch.object(audio, 'prepare_audio') as prepare:
            with self.assertRaisesRegex(RuntimeError, 'ffprobe is required for films with audio'):
                cli.film(self.args())
        inspect.assert_called_once_with('ffprobe')
        prepare.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_silent_film_keeps_ffmpeg_only_dependency_and_existing_output(self):
        with patch.object(doctor, 'inspect_tool', side_effect=AssertionError('Silent film must not require ffprobe')), \
                patch.object(audio, 'inspect_audio', side_effect=AssertionError('No audio requested')), \
                patch.object(audio, 'verify_film_audio', side_effect=AssertionError('No audio requested')):
            self.run_film(sound=False)
        result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(self.out),
                                 '-map', '0:v:0', '-vf', 'scale=1:1', '-pix_fmt', 'rgb24',
                                 '-f', 'rawvideo', '-'], check=True, capture_output=True, timeout=30)
        self.assertEqual(len(result.stdout) // 3, 50)
        self.assertGreater(result.stdout[-1], 200)  # Last blue pose survives.

    def test_valid_short_equal_long_and_delayed_audio_preserve_timing_and_originals(self):
        for name, seconds, rate in (('short', .2, 48000), ('equal', 2, 48000), ('long', 10, 8000), ('delayed', 2, 48000)):
            with self.subTest(name=name):
                self.sound = self.root / (name + '.wav')
                self.sound.write_bytes(wav_bytes(seconds, rate))
                if name == 'delayed':
                    delayed = self.root / 'delayed.mka'
                    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-itsoffset', '1', '-i', str(self.sound),
                                    '-c:a', 'pcm_s16le', str(delayed)], check=True, capture_output=True, timeout=30)
                    self.sound = delayed
                original_audio, original_gif = self.sound.read_bytes(), self.clip.read_bytes()
                self.run_film('--force')
                facts = audio.verify_film_audio(self.out, 2)
                self.assertEqual(facts['status'], 'decoded-aac')
                self.assertEqual(self.sound.read_bytes(), original_audio)
                self.assertEqual(self.clip.read_bytes(), original_gif)
                info = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                    '-show_entries', 'stream=duration,nb_read_frames', '-of', 'json', str(self.out)],
                    check=True, capture_output=True, timeout=30).stdout)['streams'][0]
                self.assertEqual(int(info['nb_read_frames']), 50)
                self.assertEqual(float(info['duration']), 2)

    def test_encoder_uses_validated_snapshot_when_original_changes(self):
        original = self.sound.read_bytes()
        used = []
        real_run = cli.run_media
        def change_original(command):
            inputs = [Path(command[i + 1]) for i, value in enumerate(command) if value == '-i']
            used.append(inputs[-1])
            self.assertNotEqual(inputs[-1], self.sound)
            self.assertEqual(inputs[-1].read_bytes(), original)
            self.sound.write_bytes(b'changed by another writer')
            return real_run(command)
        with patch.object(cli, 'run_media', side_effect=change_original):
            self.run_film()
        self.assertEqual(audio.verify_film_audio(self.out, 2)['status'], 'decoded-aac')
        self.assertFalse(used[0].exists())
        self.assertEqual(self.sound.read_bytes(), b'changed by another writer')

    def test_missing_or_short_final_audio_cannot_replace_previous_movie(self):
        self.run_film()
        previous = self.out.read_bytes()
        short = self.root / 'short.wav'; short.write_bytes(wav_bytes(.2))
        real_run = cli.run_media
        for fault in ('missing', 'short'):
            def faulty_encoder(command):
                result = real_run(command)
                staged = Path(command[-1]); replacement = staged.with_suffix('.bad.mp4')
                rewrite = ['ffmpeg', '-nostdin', '-v', 'error', '-i', str(staged)]
                if fault == 'short':
                    rewrite += ['-i', str(short), '-map', '0:v:0', '-map', '1:a:0', '-c:a', 'aac']
                else:
                    rewrite += ['-map', '0:v:0', '-an']
                rewrite += ['-c:v', 'copy', str(replacement)]
                subprocess.run(rewrite, check=True, capture_output=True, timeout=30)
                replacement.replace(staged)
                return result
            with self.subTest(fault=fault), patch.object(cli, 'run_media', side_effect=faulty_encoder):
                with self.assertRaisesRegex((ValueError, RuntimeError), 'audio stream|audio coverage'):
                    cli.film(self.args('--force'))
            self.assertEqual(self.out.read_bytes(), previous)
            self.assert_no_staging()

    def test_audio_preflight_or_final_timeout_preserves_output_and_cleans_staging(self):
        self.run_film()
        previous = self.out.read_bytes()
        for target in ('inspect_audio', 'verify_film_audio'):
            with self.subTest(target=target), patch.object(audio, target, side_effect=RuntimeError('Audio decode timed out')):
                with self.assertRaisesRegex(RuntimeError, 'timed out'):
                    cli.film(self.args('--force'))
            self.assertEqual(self.out.read_bytes(), previous)
            self.assert_no_staging()

    def test_audio_size_and_film_duration_limits_apply_before_encoding(self):
        for setting, value, message in (('MAX_AUDIO_BYTES', 10, '128 MiB'), ('MAX_AUDIO_SECONDS', 1, '3600 seconds')):
            with self.subTest(setting=setting), patch.object(audio, setting, value), patch.object(cli, '_encode_film') as encode:
                with self.assertRaisesRegex(ValueError, message):
                    cli.film(self.args())
                encode.assert_not_called()
            self.assertFalse(self.out.exists())

    def test_verification_does_not_weaken_atomic_no_clobber_publication(self):
        real_verify = audio.verify_film_audio
        def competing_writer(path, seconds):
            facts = real_verify(path, seconds)
            self.out.write_bytes(b'foreign output')
            return facts
        with patch.object(audio, 'verify_film_audio', side_effect=competing_writer):
            with self.assertRaises(FileExistsError):
                cli.film(self.args())
        self.assertEqual(self.out.read_bytes(), b'foreign output')
        self.assert_no_staging()


if __name__ == '__main__':
    unittest.main()
