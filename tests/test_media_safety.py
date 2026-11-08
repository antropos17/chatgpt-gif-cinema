"""Resource limits, local preflight and bounded subprocesses. No provider calls."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import cli, doctor, render
from test_reliability import animation


class GIFBudgetTests(unittest.TestCase):
    def setUp(self):
        self.raw = animation()

    def test_exact_byte_limit_is_accepted_and_stream_stays_open(self):
        source = io.BytesIO(self.raw)
        source.seek(5)  # Like Pillow, the validator starts at the GIF header.
        with patch.object(cli, 'MAX_GIF_BYTES', len(self.raw)):
            frames, delays, loop = cli.validate_gif(source)
        self.assertFalse(source.closed)
        self.assertEqual((len(frames), delays, loop), (2, [200, 400], 0))
        self.assertEqual(frames[-1].getpixel((0, 0)), (0, 0, 255))

    def test_byte_overflow_is_rejected_before_image_decoder(self):
        source = io.BytesIO(self.raw)
        with patch.object(cli, 'MAX_GIF_BYTES', len(self.raw) - 1), \
                patch('PIL.Image.open') as decoder, self.assertRaisesRegex(ValueError, 'input limit'):
            cli.validate_gif(source)
        decoder.assert_not_called()

    def test_actual_stream_reads_are_bounded(self):
        class GrowingSource(io.BytesIO):
            def read(self, amount=-1):
                self.amount = amount
                return b'x' * amount
        source = GrowingSource()
        with patch.object(cli, 'MAX_GIF_BYTES', 100), self.assertRaises(ValueError):
            cli.read_gif_bytes(source)
        self.assertEqual(source.amount, 101)

    def test_nonseekable_stream_remains_supported(self):
        class ReadOnlyStream:
            def __init__(self, raw):
                self.stream = io.BytesIO(raw)
            def read(self, amount):
                return self.stream.read(amount)
        self.assertEqual(len(cli.validate_gif(ReadOnlyStream(self.raw))[0]), 2)

    def test_file_reads_share_limit_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.gif'
            path.write_bytes(self.raw)
            with patch.object(cli, 'MAX_GIF_BYTES', len(self.raw)):
                self.assertEqual(len(cli.validate_gif(path)[0]), 2)
            with patch.object(cli, 'MAX_GIF_BYTES', len(self.raw) - 1), self.assertRaises(ValueError):
                cli.validate_gif(str(path))
            self.assertEqual(path.read_bytes(), self.raw)

    def test_large_canvas_is_rejected_before_allocating_frame(self):
        # Alter only the logical screen dimensions. The tiny fixture stays tiny.
        raw = self.raw[:6] + (4097).to_bytes(2, 'little') + (4096).to_bytes(2, 'little') + self.raw[10:]
        with patch('PIL.Image.open') as decoder, self.assertRaisesRegex(ValueError, 'frame exceeds'):
            cli.validate_gif(io.BytesIO(raw))
        decoder.assert_not_called()

    def test_large_descriptor_disposal_is_rejected_before_pillow_allocation(self):
        # A tiny header does not bound a disposal=2 frame's allocation in Pillow.
        data = io.BytesIO()
        Image.new('RGB', (32, 32), 'red').save(data, format='GIF', save_all=True,
            append_images=[Image.new('RGB', (32, 32), 'blue')], duration=200, disposal=2)
        raw = data.getvalue()
        for descriptor in (raw.index(b','), raw.rindex(b',')):
            with self.subTest(descriptor=descriptor):
                oversized = raw[:descriptor + 5] + (4097).to_bytes(2, 'little') + (4096).to_bytes(2, 'little') + raw[descriptor + 9:]
                with patch('PIL.Image.open') as decoder, self.assertRaisesRegex(ValueError, 'frame exceeds'):
                    cli.validate_gif(io.BytesIO(oversized))
                decoder.assert_not_called()

    def test_missing_trailer_and_truncated_sub_blocks_are_rejected(self):
        for raw in (self.raw[:-1], self.raw[:-4], b'GIF89a' + b'\x01\x00\x01\x00\x00\x00\x00' + b'!'):
            with self.subTest(length=len(raw)), self.assertRaisesRegex(ValueError, 'truncated'):
                cli.validate_gif(io.BytesIO(raw))

    def extension_before_frames(self, extension):
        table = (3 << ((self.raw[10] & 7) + 1)) if self.raw[10] & 128 else 0
        start = 13 + table
        return self.raw[:start] + extension + self.raw[start:]

    def hidden_descriptor(self, extension):
        """Regression for an extension that makes Pillow skip one block too far."""
        def single(size):
            out = io.BytesIO()
            Image.new('RGB', size, 'red').save(out, format='GIF', duration=200, disposal=2)
            raw = out.getvalue()
            start = 13 + ((3 << ((raw[10] & 7) + 1)) if raw[10] & 128 else 0)
            return raw[:start], raw[start:-1]
        header, small_body = single((32, 32))
        _, inner = single((64, 64))
        inner = bytearray(inner)
        descriptor = inner.index(b',')
        inner[descriptor + 5:descriptor + 9] = (4097).to_bytes(2, 'little') + (4096).to_bytes(2, 'little')
        outer = bytearray(b',' + b'\0\0\0\0\x20\0\x20\0\0' + b'\x02\xff' + b'X' * 255 + b'\0')
        # Pillow treats the outer ',' as length 44, then resumes at the hidden
        # descriptor. A generic block scanner only sees the harmless 32x32 outer.
        outer[45] = 0
        outer[46:46 + len(inner)] = inner
        return header + extension + outer + small_body + b';'

    def test_hidden_disposal_descriptor_after_empty_extension_is_rejected_before_open(self):
        extensions = (b'!\x01\0', b'!\xf9\0', b'!\xff\0', b'!\x02\0',
                      b'!\xff\x0bNETSCAPE2.0\0')
        for extension in extensions:
            raw = self.hidden_descriptor(extension)
            with self.subTest(extension=extension), patch('PIL.Image.open') as decoder:
                with self.assertRaisesRegex(ValueError, 'extension'):
                    cli.validate_gif(io.BytesIO(raw))
                decoder.assert_not_called()

    def test_malformed_extension_headers_and_loop_payloads_are_rejected(self):
        extensions = (b'!\xf9\x03\0\x14\0\0', b'!\xf9\x05\0\x14\0\0\0\0',
                      b'!\xf9\x04\0\x14\0\0\x01x\0',
                      b'!\x01\x0b' + b'\0' * 12, b'!\xff\x0a0123456789\0',
                      b'!\x02\x01x\0', b'!\xff\x0bNETSCAPE2.0\x01\x01\0',
                      b'!\xff\x0bNETSCAPE2.0\x03\x02\0\0\0',
                      b'!\xff\x0bNETSCAPE2.0\x03\x01\0\0\x01x\0')
        for extension in extensions:
            raw = self.extension_before_frames(extension)
            with self.subTest(extension=extension), patch('PIL.Image.open') as decoder:
                with self.assertRaisesRegex(ValueError, 'extension'):
                    cli.validate_gif(io.BytesIO(raw))
                decoder.assert_not_called()

    def test_standard_comments_plaintext_and_application_metadata_remain_supported(self):
        extensions = (b'!\xfe\0', b'!\xfe\x03abc\x02!,\0',
                      b'!\x01\x0c' + b'\0' * 12 + b'\0',
                      b'!\xff\x0bMYAPP0010.0\0',
                      b'!\xff\x0bMYAPP0010.0\x02!,\x03abc\0',
                      b'!\xff\x0bNETSCAPE2.0\x03\x01\x02\0\0')
        for extension in extensions:
            with self.subTest(extension=extension):
                frames, delays, _ = cli.validate_gif(io.BytesIO(self.extension_before_frames(extension)))
                self.assertEqual(len(frames), 2)
                self.assertEqual(delays, [200, 400])
                self.assertEqual(frames[-1].getpixel((0, 0)), (0, 0, 255))

    def test_exact_frame_and_pixel_budgets_are_accepted(self):
        with patch.object(cli, 'MAX_GIF_FRAMES', 2), \
                patch.object(cli, 'MAX_GIF_FRAME_PIXELS', 32 * 32), \
                patch.object(cli, 'MAX_GIF_PIXEL_FRAMES', 2 * 32 * 32):
            self.assertEqual(len(cli.validate_gif(io.BytesIO(self.raw))[0]), 2)

    def test_frame_count_and_total_pixels_are_separately_bounded(self):
        for constant, value, message in (('MAX_GIF_FRAMES', 1, 'frame limit'),
                                         ('MAX_GIF_PIXEL_FRAMES', 2 * 32 * 32 - 1, 'pixel budget')):
            with self.subTest(constant=constant), patch.object(cli, constant, value), \
                    patch('PIL.Image.open') as decoder, self.assertRaisesRegex(ValueError, message):
                cli.validate_gif(io.BytesIO(self.raw))
            decoder.assert_not_called()

    def test_decoder_decompression_bomb_is_clean_validation_error(self):
        with patch('PIL.Image.open', side_effect=Image.DecompressionBombError('huge')):
            with self.assertRaisesRegex(ValueError, 'safe image dimensions'):
                cli.validate_gif(io.BytesIO(self.raw))


class MediaCommandTests(unittest.TestCase):
    def test_all_media_commands_have_deadline_and_closed_stdin(self):
        with patch('gif_cinema.cli.subprocess.run') as run:
            cli.run_media(['ffmpeg', '-version'])
        self.assertEqual(run.call_args.kwargs,
                         {'check': True, 'capture_output': True, 'stdin': subprocess.DEVNULL, 'timeout': 300})

    def test_real_timed_out_child_is_stopped_and_reported_cleanly(self):
        with patch.object(cli, 'MEDIA_TIMEOUT_SECONDS', 0.05), self.assertRaisesRegex(RuntimeError, 'timed out'):
            cli.run_media([sys.executable, '-c', 'import time; time.sleep(10)'])

    def test_timeout_does_not_echo_child_output_or_command_arguments(self):
        error = subprocess.TimeoutExpired(['ffmpeg', 'private detail'], 300,
                                          output=b'private stdout', stderr=b'private stderr')
        with patch('gif_cinema.cli.subprocess.run', side_effect=error), self.assertRaises(RuntimeError) as caught:
            cli.run_media(['ffmpeg', 'private detail'])
        self.assertNotIn('private', str(caught.exception))

    def test_both_probe_and_complete_decode_have_deadlines(self):
        info = {'codec_name': 'h264', 'width': 32, 'height': 32, 'duration': '0.6', 'nb_read_frames': '15'}
        response = subprocess.CompletedProcess([], 0, json.dumps({'streams': [info]}).encode())
        with patch('gif_cinema.cli.subprocess.run', return_value=response) as run:
            self.assertEqual(render.probe(Path('fixture.mp4'), 32, 32, 0.6, 25, 1), info)
        self.assertEqual([call.args[0][0] for call in run.call_args_list], ['ffprobe', 'ffmpeg'])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 300)
            self.assertEqual(call.kwargs['stdin'], subprocess.DEVNULL)

    def test_decode_timeout_is_not_a_successful_verification(self):
        info = {'codec_name': 'h264', 'width': 32, 'height': 32, 'duration': '0.6', 'nb_read_frames': '15'}
        response = subprocess.CompletedProcess([], 0, json.dumps({'streams': [info]}).encode())
        with patch('gif_cinema.cli.subprocess.run', side_effect=[response, subprocess.TimeoutExpired('ffmpeg', 300)]):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                render.probe(Path('fixture.mp4'), 32, 32, 0.6, 25, 1)

    def test_encoder_timeout_keeps_old_movie_and_cleans_staging_and_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clip, output = root / 'input.gif', root / 'film.mp4'
            clip.write_bytes(animation())
            output.write_bytes(b'accepted movie')
            args = cli.build_parser().parse_args(['film', str(clip), '-o', str(output), '--force'])
            with patch('shutil.which', return_value='fixture'), \
                    patch('gif_cinema.doctor.require_film_capabilities'), \
                    patch('gif_cinema.cli.subprocess.run', side_effect=subprocess.TimeoutExpired('ffmpeg', 300)):
                with self.assertRaisesRegex(RuntimeError, 'timed out'):
                    cli.film(args)
            self.assertEqual(output.read_bytes(), b'accepted movie')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['film.mp4', 'input.gif'])


class CapabilityTests(unittest.TestCase):
    def test_capability_names_are_detected_from_encoder_and_filter_listing(self):
        encoders = ' V....D libx264 H.264\n A..... aac AAC\n'
        filters = '\n'.join(' ... ' + name + ' V->V' for name in
                            ('fps', 'scale', 'pad', 'concat', 'tpad', 'trim', 'setpts', 'format', 'setsar', 'apad'))
        responses = [subprocess.CompletedProcess([], 0, encoders), subprocess.CompletedProcess([], 0, filters)]
        with patch('gif_cinema.doctor.subprocess.run', side_effect=responses):
            capabilities = doctor.inspect_ffmpeg_capabilities()
        self.assertTrue(capabilities['h264_encoder'])
        self.assertTrue(capabilities['core_filters'])
        self.assertTrue(capabilities['aac_encoder'])
        self.assertTrue(capabilities['audio_padding'])
        self.assertFalse(capabilities['motion_interpolation'])

    def test_optional_audio_and_motion_are_not_required_for_silent_film(self):
        with patch('gif_cinema.doctor.inspect_ffmpeg_capabilities', return_value={'h264_encoder': True, 'core_filters': True}):
            doctor.require_film_capabilities()
            with self.assertRaisesRegex(RuntimeError, 'AAC encoder, apad'):
                doctor.require_film_capabilities(audio=True)

    def test_missing_encoder_or_filter_prevents_execution(self):
        for field, message in (('h264_encoder', 'libx264'), ('core_filters', 'video filters'),
                               ('aac_encoder', 'AAC encoder'), ('audio_padding', 'apad')):
            caps = dict.fromkeys(('h264_encoder', 'core_filters', 'aac_encoder', 'audio_padding'), True)
            caps[field] = False
            with self.subTest(field=field), patch('gif_cinema.doctor.inspect_ffmpeg_capabilities', return_value=caps):
                with self.assertRaisesRegex(RuntimeError, message):
                    doctor.require_film_capabilities(audio=True)

    def test_capability_timeout_fails_closed(self):
        with patch('gif_cinema.doctor.subprocess.run', side_effect=subprocess.TimeoutExpired('ffmpeg', 10)):
            with self.assertRaisesRegex(RuntimeError, 'libx264'):
                doctor.require_film_capabilities()


if __name__ == '__main__':
    unittest.main()
