"""Film color metadata must agree with the actual encoded YUV samples."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from gif_cinema import cli, render


class FilmColorVerificationTests(unittest.TestCase):
    def test_render_rejects_missing_or_inconsistent_color_tags(self):
        valid = {'codec_name': 'h264', 'width': 64, 'height': 64,
                 'duration': '0.6', 'nb_read_frames': '15', **cli.FILM_COLOR_TAGS}
        for field in cli.FILM_COLOR_TAGS:
            for value in (None, 'unknown', 'smpte170m'):
                info = {**valid, field: value}
                if value is None:
                    del info[field]
                response = subprocess.CompletedProcess([], 0, json.dumps({'streams': [info]}).encode())
                with self.subTest(field=field, value=value), patch.object(cli, 'run_media', return_value=response) as run:
                    with self.assertRaisesRegex(RuntimeError, 'color verification'):
                        render.probe(Path('fixture.mp4'), 64, 64, .6, 25, 1)
                    self.assertEqual(run.call_count, 1)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
class RealFilmColorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'patches.gif'
        self.colors = [(215, 52, 36), (50, 210, 95), (35, 70, 220), (180, 180, 180)]
        frames = []
        for index in range(2):
            frame = Image.new('RGB', (64, 64))
            draw = ImageDraw.Draw(frame)
            for quadrant, color in enumerate(self.colors):
                x, y = quadrant % 2 * 32, quadrant // 2 * 32
                draw.rectangle((x, y, x + 31, y + 31), fill=color)
            draw.rectangle((index * 4, 0, index * 4 + 3, 3), fill='white')
            frames.append(frame)
        frames[0].save(self.source, save_all=True, append_images=frames[1:], duration=[300, 300], loop=0)
        self.original = self.source.read_bytes()
        network = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden'))
        network.start(); self.addCleanup(network.stop)
        provider = patch.object(cli, 'request_gif', side_effect=AssertionError('Provider forbidden'))
        provider.start(); self.addCleanup(provider.stop)

    def test_sd_and_hd_encode_matching_matrix_tags_and_pixel_colors(self):
        for width, height in ((64, 64), (1280, 720)):
            with self.subTest(size=(width, height)):
                output = self.root / f'film-{width}.mp4'
                args = cli.build_parser().parse_args(['film', str(self.source), '-o', str(output),
                    '--width', str(width), '--height', str(height), '--fps', '25'])
                with contextlib.redirect_stdout(io.StringIO()):
                    cli.film(args)
                info = render.probe(output, width, height, .6, 25, 1)
                self.assertEqual({key: info[key] for key in cli.FILM_COLOR_TAGS}, cli.FILM_COLOR_TAGS)
                elementary = self.root / f'film-{width}.h264'
                cli.run_media(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(output),
                    '-map', '0:v:0', '-c:v', 'copy', '-bsf:v', 'h264_mp4toannexb', str(elementary)])
                raw_info = json.loads(cli.run_media(['ffprobe', '-v', 'error', '-show_streams',
                    '-of', 'json', str(elementary)]).stdout)['streams'][0]
                # The signal must survive without MP4 container metadata.
                self.assertEqual({key: raw_info[key] for key in cli.FILM_COLOR_TAGS}, cli.FILM_COLOR_TAGS)
                decoded = cli.run_media(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(output),
                    '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']).stdout
                rgb = Image.frombytes('RGB', (width, height), decoded)
                # Test actual luma as well as metadata: tagging a BT.601 conversion
                # as BT.709 would pass the probe but fail this numerical check.
                yuv = cli.run_media(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(output),
                    '-frames:v', '1', '-pix_fmt', 'yuv420p', '-f', 'rawvideo', '-']).stdout
                size = min(width, height)
                left, top = (width - size) // 2, (height - size) // 2
                for quadrant, expected in enumerate(self.colors):
                    x = left + size * (1 if quadrant % 2 == 0 else 3) // 4
                    y = top + size * (1 if quadrant // 2 == 0 else 3) // 4
                    actual = rgb.getpixel((x, y))
                    self.assertLessEqual(max(abs(a - b) for a, b in zip(actual, expected)), 5)
                    luma = 16 + (219 / 255) * sum(c * w for c, w in zip(expected, (.2126, .7152, .0722)))
                    self.assertAlmostEqual(yuv[y * width + x], luma, delta=2)
                    chroma_index = (y // 2) * (width // 2) + x // 2
                    u = 128 + (224 / 255) * sum(c * w for c, w in zip(expected, (-.114572, -.385428, .5)))
                    v = 128 + (224 / 255) * sum(c * w for c, w in zip(expected, (.5, -.454153, -.045847)))
                    self.assertAlmostEqual(yuv[width * height + chroma_index], u, delta=2)
                    self.assertAlmostEqual(yuv[width * height * 5 // 4 + chroma_index], v, delta=2)
                if width != height:
                    self.assertLessEqual(max(rgb.getpixel((0, 0))), 2)
                    self.assertAlmostEqual(yuv[0], 16, delta=1)
                self.assertEqual(self.source.read_bytes(), self.original)
                self.assertEqual(list(self.root.glob('*.lock')), [])


if __name__ == '__main__':
    unittest.main()
