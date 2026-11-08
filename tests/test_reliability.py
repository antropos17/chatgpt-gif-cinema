"""Offline behavioral regressions. No test may contact the OpenAI API."""
import base64
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from PIL import Image
from gif_cinema.cli import build_parser, generate, film, request_gif, make_payload, validate_gif


def animation(durations=(200, 400)):
    stream = io.BytesIO()
    images = [Image.new("RGB", (32, 32), color) for color in ("red", "blue")]
    images[0].save(stream, format="GIF", save_all=True, append_images=images[1:], duration=list(durations), loop=0)
    return stream.getvalue()


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.network = patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network forbidden in offline tests"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def args(self, *extra):
        return build_parser().parse_args(["generate", "test shot", "-o", str(self.root / "shot.gif"), *extra])

    def response(self, raw):
        return lambda *a, **k: io.BytesIO(json.dumps({"data": [{"b64_json": base64.b64encode(raw).decode()}]}).encode())

    def test_corrupt_and_static_response_rejected(self):
        static = io.BytesIO()
        Image.new("RGB", (32, 32)).save(static, format="GIF", duration=200)
        for raw in (b"GIF89a", animation()[:40], static.getvalue()):
            with self.subTest(raw_length=len(raw)), self.assertRaises(ValueError):
                request_gif(make_payload("test"), "fixture", transport=self.response(raw))

    def test_real_gif_decoded_with_variable_timing(self):
        raw, _ = request_gif(make_payload("test"), "fixture", transport=self.response(animation()))
        frames, durations, _ = validate_gif(io.BytesIO(raw))
        self.assertEqual(len(frames), 2)
        self.assertEqual(durations, [200, 400])
        self.assertEqual(frames[-1].getpixel((0, 0)), (0, 0, 255))

    def test_existing_output_blocks_network(self):
        for name in ("shot.gif", "shot.json"):
            with self.subTest(name=name):
                p = self.root / name
                p.write_bytes(b"original")
                with patch("gif_cinema.cli.request_gif") as request, self.assertRaises(ValueError):
                    generate(self.args())
                request.assert_not_called()
                self.assertEqual(p.read_bytes(), b"original")
                p.unlink()

    def test_generate_and_resume_without_key_or_request(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture"}), patch("gif_cinema.cli.request_gif", return_value=(animation(), None)) as request:
            generate(self.args())
            self.assertEqual(request.call_count, 1)
        with patch.dict(os.environ, {}, clear=True), patch("gif_cinema.cli.request_gif") as request:
            generate(self.args("--resume"))
            request.assert_not_called()
        metadata = json.loads((self.root / "shot.json").read_text())
        self.assertEqual(metadata["actual_duration_ms"], 600)

    def test_resume_rejects_changed_prompt_or_file(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture"}), patch("gif_cinema.cli.request_gif", return_value=(animation(), None)):
            generate(self.args())
        with patch("gif_cinema.cli.request_gif") as request:
            changed = self.args("--resume")
            changed.prompt = "other shot"
            with self.assertRaises(ValueError):
                generate(changed)
            (self.root / "shot.gif").write_bytes(animation((300, 500)))
            with self.assertRaises(ValueError):
                generate(self.args("--resume"))
            request.assert_not_called()

    def test_failed_force_preserves_previous_result(self):
        p = self.root / "shot.gif"
        p.write_bytes(b"original")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture"}), patch("gif_cinema.cli.request_gif", return_value=(b"GIF89a", None)), self.assertRaises(ValueError):
            generate(self.args("--force"))
        self.assertEqual(p.read_bytes(), b"original")
        self.assertFalse(list(self.root.glob("*.lock")))

    def test_active_output_lock_prevents_request(self):
        (self.root / "shot.gif.lock").write_text("other process")
        with patch("gif_cinema.cli.request_gif") as request, self.assertRaises(ValueError):
            generate(self.args())
        request.assert_not_called()

    def test_http_error_does_not_echo_credentials(self):
        from urllib.error import HTTPError
        secret = "private-fixture-value"
        def fail(*a, **k):
            raise HTTPError("https://api.openai.com", 401, "unauthorized", {}, io.BytesIO(secret.encode()))
        with self.assertRaises(RuntimeError) as ctx:
            request_gif(make_payload("test"), secret, transport=fail)
        self.assertNotIn(secret, str(ctx.exception))
        self.assertIn("401", str(ctx.exception))

    def test_malformed_json_and_timeout_fail_cleanly(self):
        with self.assertRaises(ValueError):
            request_gif(make_payload("test"), "fixture", transport=lambda *a, **k: io.BytesIO(b"not json"))
        def timeout(*a, **k):
            raise TimeoutError("private detail")
        with self.assertRaises(RuntimeError) as ctx:
            request_gif(make_payload("test"), "fixture", transport=timeout)
        self.assertNotIn("private detail", str(ctx.exception))

    def test_missing_ffmpeg_is_actionable(self):
        with patch("gif_cinema.cli.shutil.which", return_value=None), self.assertRaisesRegex(RuntimeError, "ffmpeg is required"):
            film(build_parser().parse_args(["film", "missing.gif"]))

    def test_reports_and_endpoints_protect_existing_files(self):
        p = self.root / "source.gif"
        raw = animation()
        p.write_bytes(raw)
        for command in (["inspect", str(p), "-o", str(p), "--force"],
                        ["continuity", str(p), str(p), "-o", str(p), "--force"]):
            args = build_parser().parse_args(command)
            with self.assertRaises(ValueError):
                args.func(args)
            self.assertEqual(p.read_bytes(), raw)
        prefix = str(self.root / "edge")
        args = build_parser().parse_args(["endpoints", str(p), "-o", prefix])
        args.func(args)
        with self.assertRaises(ValueError):
            args.func(args)
        with Image.open(prefix + "-last.png") as last:
            self.assertEqual(last.getpixel((0, 0)), (0, 0, 255))


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for integration tests")
class FilmTests(unittest.TestCase):
    setUp = OfflineTests.setUp

    def film_args(self, *extra):
        p = self.root / "input.gif"
        p.write_bytes(animation((400, 800)))
        return build_parser().parse_args(["film", str(p), str(p), "--width", "32", "--height", "32", "--fps", "25", "-o", str(self.root / "film.mp4"), *extra])

    def test_audio_never_truncates_video_and_last_frame_survives(self):
        for audio_length in (None, 0.2, 4.0):
            with self.subTest(audio_length=audio_length):
                extra = ["--force"]
                if audio_length:
                    audio = self.root / "audio.wav"
                    with wave.open(str(audio), "wb") as wav:
                        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                        wav.writeframes(b"\0\0" * int(8000 * audio_length))
                    extra += ["--audio", str(audio)]
                film(self.film_args(*extra))
                path = str(self.root / "film.mp4")
                result = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-map", "0:v:0", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True)
                self.assertEqual(len(result.stdout) // 3, 60)  # 2 * 1.2 seconds * 25 FPS
                r, g, b = result.stdout[-3:]
                self.assertGreater(b, 200)
                self.assertLess(r, 30)
                self.assertLess(g, 30)

    def test_fractional_durations_have_explicit_per_shot_frame_counts(self):
        for durations, fps, expected in (((40, 60), 25, 4),
                                         ((60, 80), 25, 8),
                                         ((20, 20), 1, 2)):
            with self.subTest(durations=durations, fps=fps):
                source = self.root / "fractional.gif"
                raw = animation(durations)
                source.write_bytes(raw)
                output = self.root / "fractional.mp4"
                args = build_parser().parse_args([
                    "film", str(source), str(source), "--width", "32", "--height", "32",
                    "--fps", str(fps), "-o", str(output), "--force"])
                film(args)
                decoded = subprocess.run([
                    "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:v:0",
                    "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"
                ], capture_output=True, check=True)
                self.assertEqual(len(decoded.stdout) // 3, expected)
                self.assertEqual(source.read_bytes(), raw)

    def test_existing_movie_and_failed_force_are_preserved(self):
        args = self.film_args()
        out = Path(args.output)
        out.write_bytes(b"old movie")
        with self.assertRaises(ValueError):
            film(args)
        args.force = True
        with patch("gif_cinema.cli.subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg")), self.assertRaises(subprocess.CalledProcessError):
            film(args)
        self.assertEqual(out.read_bytes(), b"old movie")
        self.assertFalse(list(self.root.glob("*.lock")))
        self.assertEqual(list(self.root.glob("*.mp4")), [out])

    def test_invalid_dimensions_rejected(self):
        args = self.film_args()
        args.width = 31
        with self.assertRaises(ValueError):
            film(args)


if __name__ == "__main__":
    unittest.main()
