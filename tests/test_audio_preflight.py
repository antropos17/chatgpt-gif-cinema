"""No provider calls: bounded audio preflight and requested-audio verification."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from gif_cinema import audio, cli, render
from test_reliability import animation


def wav_bytes(seconds=2, rate=48000):
    out = io.BytesIO()
    with wave.open(out, 'wb') as stream:
        stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\x00\x00' * round(seconds * rate))
    return out.getvalue()


class AudioLimitTests(unittest.TestCase):
    def test_commands_have_timeout_and_do_not_read_stdin_or_retain_error_payloads(self):
        with patch('gif_cinema.audio.subprocess.run') as run:
            self.assertEqual(audio.run_command(['ffprobe'], 'Audio probe'), b'')
        self.assertEqual(run.call_args.kwargs['timeout'], 30)
        self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs['stderr'], subprocess.DEVNULL)

    def test_real_timeout_kills_child_and_returns_actionable_error(self):
        with patch.object(audio, 'AUDIO_TIMEOUT_SECONDS', 0.05), self.assertRaisesRegex(RuntimeError, 'Audio decode timed out'):
            audio.run_command([sys.executable, '-c', 'import time; time.sleep(10)'], 'Audio decode')

    def test_subprocess_error_does_not_echo_private_input_or_provider_data(self):
        error = subprocess.CalledProcessError(1, ['ffmpeg', 'private source'], stderr=b'private metadata')
        with patch('gif_cinema.audio.subprocess.run', side_effect=error), self.assertRaises(ValueError) as caught:
            audio.run_command(['ffmpeg'], 'Audio decode')
        self.assertIn('corrupt', str(caught.exception))
        self.assertNotIn('private', str(caught.exception))

    def test_output_reads_are_bounded(self):
        def write_output(*args, **kwargs):
            kwargs['stdout'].write(b'x' * 33)
        with patch.object(audio, 'MAX_PROCESS_OUTPUT', 32), \
                patch('gif_cinema.audio.subprocess.run', side_effect=write_output), \
                self.assertRaisesRegex(ValueError, 'output limit'):
            audio.run_command(['ffprobe'], 'Audio probe')

    def test_decode_is_strict_single_threaded_and_has_duration_and_protocol_limits(self):
        metadata = {'streams': [{'codec_type': 'audio', 'codec_name': 'pcm_s16le', 'channels': 1,
                                 'sample_rate': '48000', 'duration': '2.0'}]}
        with patch.object(audio, 'run_command', side_effect=[json.dumps(metadata).encode(),
                b'out_time_us=2000000\nprogress=end\n']) as run:
            result = audio.inspect_audio(Path('input.wav'))
        self.assertEqual(result['decoded_seconds'], 2)
        command = run.call_args_list[-1].args[0]
        for flag in ('-xerror', '-err_detect', '-max_alloc', '-max_streams', '-probesize', '-analyzeduration', '-threads', '-t'):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index('-protocol_whitelist') + 1], 'file')
        self.assertNotIn('hls', command[command.index('-format_whitelist') + 1])

    def test_metadata_cannot_hide_excessive_or_empty_decoded_audio(self):
        metadata = {'streams': [{'codec_type': 'audio', 'codec_name': 'aac', 'channels': 1,
                                 'sample_rate': '48000', 'duration': '2.0'}]}
        for duration in ('0', '3601000000', 'nan'):
            with self.subTest(duration=duration), patch.object(audio, 'run_command', side_effect=[
                    json.dumps(metadata).encode(), f'out_time_us={duration}\nprogress=end\n'.encode()]):
                with self.assertRaises(ValueError):
                    audio.inspect_audio(Path('input.wav'))

    def test_probe_rejects_oversized_channel_rate_and_duration_before_decode(self):
        for change in ({'channels': 9}, {'sample_rate': '192001'}, {'duration': '3601'}, {'duration': 'nan'}):
            stream = {'codec_type': 'audio', 'codec_name': 'aac', 'channels': 1,
                      'sample_rate': '48000', 'duration': '2.0', **change}
            with self.subTest(change=change), patch.object(audio, 'run_command', return_value=json.dumps({'streams': [stream]}).encode()) as run:
                with self.assertRaises(ValueError):
                    audio.inspect_audio(Path('input.wav'))
                self.assertEqual(run.call_count, 1)

    def test_size_limits_apply_to_actual_snapshot_bytes_before_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.wav'
            source.write_bytes(b'12345')
            with patch.object(audio, 'MAX_AUDIO_BYTES', 4), patch.object(audio, 'inspect_audio') as inspect:
                with self.assertRaisesRegex(ValueError, '128 MiB'):
                    with audio.prepare_audio(source):
                        pass
                inspect.assert_not_called()
            with patch.object(audio, 'MAX_AUDIO_BYTES', 5), patch.object(audio, 'inspect_audio', return_value={}):
                with audio.prepare_audio(source) as prepared:
                    snapshot = prepared['path']
                    self.assertEqual(snapshot.read_bytes(), b'12345')
                    self.assertEqual(prepared['bytes'], 5)
                self.assertFalse(snapshot.exists())

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO test')
    def test_nonregular_audio_cannot_block_open(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'fifo'
            os.mkfifo(source)
            with self.assertRaisesRegex(ValueError, 'regular local file'):
                with audio.prepare_audio(source):
                    pass

    def test_final_coverage_allows_aac_padding_but_rejects_missing_duration(self):
        facts = {'codec_name': 'aac', 'sample_rate': 48000, 'channels': 1, 'duration_seconds': 1.984,
                 'start_seconds': 0, 'decoded_seconds': 2.005333}
        with patch.object(audio, 'inspect_audio', return_value=facts):
            self.assertEqual(audio.verify_film_audio(Path('film.mp4'), 2)['status'], 'decoded-aac')
        for change in ({'duration_seconds': .2}, {'decoded_seconds': .2}, {'start_seconds': 1},
                       {'codec_name': 'mp3'}, {'duration_seconds': None}):
            with self.subTest(change=change), patch.object(audio, 'inspect_audio', return_value={**facts, **change}):
                with self.assertRaisesRegex(RuntimeError, 'audio coverage'):
                    audio.verify_film_audio(Path('film.mp4'), 2)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
class AudioRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'input.wav'
        self.source.write_bytes(wav_bytes())
        self.clip = self.root / 'input.gif'
        self.clip.write_bytes(animation((1000, 1000)))
        self.script = self.root / 'film.json'
        self.out = self.root / 'project'
        self.data = {'schema_version': 1, 'title': 'Audio test', 'style_bible': 'Synthetic frames',
                     'ratio': '1:1', 'width': 32, 'height': 32, 'fps': 25, 'audio': 'input.wav',
                     'shots': [{'id': 'one', 'source': 'input.gif', 'first_frame_target': 'red',
                                'last_frame_target': 'blue', 'caption': 'Full shot'}]}
        network = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden'))
        network.start(); self.addCleanup(network.stop)
        output = patch('sys.stdout', new_callable=io.StringIO)
        output.start(); self.addCleanup(output.stop)

    def args(self, *flags):
        self.script.write_text(json.dumps(self.data))
        return cli.build_parser().parse_args(['render', str(self.script), '--out', str(self.out), *flags])

    def generated(self):
        shot = self.data['shots'][0]
        shot.pop('source')
        shot.update(prompt='Synthetic test', frames=2, duration_ms=1000)

    def test_invalid_or_truncated_audio_prevents_paid_dispatch_and_output(self):
        self.generated()
        environment_get = os.environ.get
        def forbid_key(name, *args):
            if name == 'OPENAI_API_KEY':
                raise AssertionError('Audio must validate before key lookup')
            return environment_get(name, *args)
        for raw in (b'not a sound file', wav_bytes()[:48044]):
            with self.subTest(length=len(raw)):
                self.source.write_bytes(raw)
                with patch('os.environ.get', side_effect=forbid_key), patch.object(cli, 'request_gif') as request:
                    with self.assertRaisesRegex(ValueError, 'Audio (probe|decode) failed'):
                        render.run(self.args('--execute', '--max-api-calls', '1'))
                    request.assert_not_called()
                self.assertFalse(self.out.exists())

    def test_playlist_is_rejected_without_following_local_media_reference(self):
        self.source.write_text('#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\nmissing-private-file.ts\n#EXT-X-ENDLIST\n')
        with patch.object(cli, 'request_gif') as request, self.assertRaisesRegex(ValueError, 'unsupported'):
            render.run(self.args('--execute', '--max-api-calls', '0'))
        request.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_dry_run_is_explicitly_not_audio_decode_and_never_requires_ffmpeg(self):
        self.source.write_bytes(b'not a sound file')
        with patch('subprocess.run', side_effect=AssertionError('No subprocesses during planning')), \
                patch.object(cli, 'request_gif') as request:
            plan = render.run(self.args('--dry-run'))
        self.assertIn('dry-run does not decode audio', plan['audio_validation'])
        request.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_preflight_timeout_prevents_dispatch_and_output(self):
        self.generated()
        with patch.object(audio, 'run_command', side_effect=RuntimeError('Audio probe timed out')), patch.object(cli, 'request_gif') as request:
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                render.run(self.args('--execute'))
        request.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_valid_short_equal_long_audio_renders_and_resumes_with_coverage(self):
        for name, seconds, rate in (('short', .2, 48000), ('equal', 2, 48000), ('long', 10, 8000)):
            with self.subTest(name=name):
                self.out = self.root / name
                self.source.write_bytes(wav_bytes(seconds, rate))
                original = self.source.read_bytes()
                with patch.object(cli, 'request_gif') as request:
                    first = render.run(self.args('--execute', '--max-api-calls', '0'))
                    movie = (self.out / 'film.mp4').read_bytes()
                    second = render.run(self.args('--execute', '--max-api-calls', '0'))
                    request.assert_not_called()
                self.assertEqual(first['film_seconds'], 2)
                self.assertEqual(first['audio']['status'], 'decoded-aac')
                self.assertEqual(second['skipped'], 1)
                self.assertEqual((self.out / 'film.mp4').read_bytes(), movie)
                self.assertEqual(self.source.read_bytes(), original)
                manifest = json.loads((self.out / 'render-manifest.json').read_text())
                self.assertEqual(manifest['audio_preflight']['sha256'], hashlib.sha256(original).hexdigest())
                self.assertIn('00:00:00,000 --> 00:00:02,000', (self.out / 'captions.srt').read_text())

    def test_validated_snapshot_survives_source_change_during_stubbed_generation(self):
        self.generated()
        original = self.source.read_bytes()
        def request(*args, **kwargs):
            self.source.write_bytes(b'changed by another writer')
            return self.clip.read_bytes(), None
        real_film, used = cli.film, []
        def film(args):
            used.append(Path(args.audio))
            self.assertNotEqual(Path(args.audio), self.source)
            self.assertEqual(Path(args.audio).read_bytes(), original)
            return real_film(args)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-placeholder'}), \
                patch.object(cli, 'request_gif', side_effect=request) as provider, patch.object(cli, 'film', side_effect=film):
            result = render.run(self.args('--execute', '--max-api-calls', '1'))
        self.assertEqual(provider.call_count, 1)  # Stub only, no HTTP request.
        self.assertEqual(result['audio']['status'], 'decoded-aac')
        self.assertFalse(used[0].exists())
        self.assertEqual(self.source.read_bytes(), b'changed by another writer')

    def test_invalid_new_audio_preserves_previous_export_and_manifest(self):
        render.run(self.args('--execute', '--max-api-calls', '0'))
        before = {name: (self.out / name).read_bytes() for name in ('film.mp4', 'render-manifest.json')}
        self.source.write_bytes(b'bad replacement')
        with patch.object(cli, 'request_gif') as request, self.assertRaisesRegex(ValueError, 'Audio probe failed'):
            render.run(self.args('--execute', '--max-api-calls', '0'))
        request.assert_not_called()
        for name, raw in before.items():
            self.assertEqual((self.out / name).read_bytes(), raw)

    def test_requested_audio_cannot_be_missing_from_a_verified_film(self):
        render.run(self.args('--execute', '--max-api-calls', '0'))
        silent = self.root / 'silent.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(self.out / 'film.mp4'),
                        '-an', '-c:v', 'copy', str(silent)], check=True, capture_output=True, timeout=30)
        with self.assertRaisesRegex(ValueError, 'audio stream'):
            render.probe(silent, 32, 32, 2, 25, 1, expected_audio=True)
        self.assertEqual(render.probe(silent, 32, 32, 2, 25, 1)['codec_name'], 'h264')

    def test_missing_audio_in_replacement_preserves_previously_accepted_movie(self):
        render.run(self.args('--execute', '--max-api-calls', '0'))
        previous = (self.out / 'film.mp4').read_bytes()
        self.data.update(width=64, height=64)
        real_film = cli.film
        def omit_audio(args):
            args.audio = None
            real_film(args)
        with patch.object(cli, 'film', side_effect=omit_audio), patch.object(cli, 'request_gif') as request:
            with self.assertRaisesRegex(ValueError, 'audio stream'):
                render.run(self.args('--execute', '--max-api-calls', '0'))
            request.assert_not_called()
        self.assertEqual((self.out / 'film.mp4').read_bytes(), previous)
        self.assertFalse(list(self.out.glob('encode-*')))
        self.assertFalse(list(self.out.glob('*.lock')))

    def test_silent_script_keeps_previous_verification_contract(self):
        del self.data['audio']
        with patch.object(render, 'verify_film_audio', side_effect=AssertionError('No audio requested')):
            result = render.run(self.args('--execute', '--max-api-calls', '0'))
        self.assertNotIn('audio', result)
        self.assertEqual(result['verification'], 'decoded-h264; narrative-human-review-required')

    def test_54_second_six_fps_timeline_preserves_video_audio_and_caption(self):
        self.data['fps'] = 6
        self.clip.write_bytes(animation((27000, 27000)))
        self.source.write_bytes(wav_bytes(54, 8000))
        result = render.run(self.args('--execute', '--max-api-calls', '0'))
        info = json.loads((self.out / 'film-inspect.json').read_text())
        self.assertEqual(int(info['nb_read_frames']), 324)
        self.assertEqual(result['film_seconds'], 54)
        self.assertLess(abs(result['audio']['duration_seconds'] - 54), result['audio']['coverage_tolerance_seconds'])
        self.assertIn('00:00:00,000 --> 00:00:54,000', (self.out / 'captions.srt').read_text())


if __name__ == '__main__':
    unittest.main()
