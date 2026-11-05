"""Behavioral script-render tests. The real network is forbidden throughout."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gif_cinema import cli, render
from test_reliability import animation


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / "film.json"
        self.out = self.root / "project"
        self.data = {"schema_version": 1, "title": "Test story", "ratio": "1:1", "width": 32, "height": 32, "fps": 25,
                     "style_bible": "One red signal turns blue", "shots": [self.shot("01"), self.shot("02"), self.shot("03")]}
        self.network = patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network forbidden"))
        self.network.start(); self.addCleanup(self.network.stop)
        output = patch("sys.stdout", new_callable=io.StringIO)
        output.start(); self.addCleanup(output.stop)

    def shot(self, sid):
        return {"id": sid, "prompt": "red becomes blue", "frames": 2, "duration_ms": 200,
                "first_frame_target": "red", "last_frame_target": "blue", "caption": "A signal"}

    def args(self, *extra):
        self.script.write_text(json.dumps(self.data), encoding="utf-8")
        return cli.build_parser().parse_args(["render", str(self.script), "--out", str(self.out), *extra])

    def imports(self):
        for index, shot in enumerate(self.data["shots"]):
            for key in ("prompt", "frames", "duration_ms"):
                shot.pop(key)
            shot["source"] = f"source{index}.gif"
            (self.root / shot["source"]).write_bytes(animation((200, 400)))

    @contextlib.contextmanager
    def execution(self, responses=None):
        def encode(args):
            Path(args.output).write_bytes(b"offline film fixture")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret-fixture"}), \
                patch("gif_cinema.render.shutil.which", return_value="fixture"), \
                patch("gif_cinema.cli.request_gif", side_effect=responses, return_value=(animation((200, 200)), {"total_tokens": 10})) as request, \
                patch("gif_cinema.cli.film", side_effect=encode), \
                patch("gif_cinema.render.probe", return_value={"duration": "1.2", "codec_name": "h264"}):
            yield request

    def manifest(self):
        return json.loads((self.out / "render-manifest.json").read_text())

    def test_default_and_explicit_dry_run_never_write_or_request(self):
        for flags in ((), ("--dry-run",)):
            with patch.dict(os.environ, {}, clear=True), patch("gif_cinema.cli.request_gif") as request:
                plan = render.run(self.args(*flags))
                self.assertEqual(plan["minimum_new_api_calls"], 3)
                request.assert_not_called()
                self.assertFalse(self.out.exists())

    def test_entire_script_validated_before_any_request(self):
        for change in ({"id": "../evil"}, {"id": "01"}, {"transition": "dissolve"}, {"frames": True}, {"duration_ms": 201}, {"unexpected": 1}):
            with self.subTest(change=change):
                self.data["shots"][-1] = {**self.shot("03"), **change}
                with self.execution() as request, self.assertRaises(ValueError):
                    render.run(self.args("--execute"))
                request.assert_not_called()
                self.assertFalse(self.out.exists())

    def test_call_cap_partial_resume_and_no_key_for_completed_project(self):
        with self.execution() as request, self.assertRaisesRegex(RuntimeError, "budget exhausted"):
            render.run(self.args("--execute", "--max-api-calls", "1"))
        self.assertEqual(request.call_count, 1)
        first = self.manifest()["shots"]["01"]
        original = (self.out / first["output"]).read_bytes()
        with self.execution() as request:
            receipt = render.run(self.args("--execute", "--max-api-calls", "2"))
            self.assertEqual(request.call_count, 2)
            self.assertEqual(receipt["skipped"], 1)
        self.assertEqual((self.out / first["output"]).read_bytes(), original)
        with self.execution() as request, patch.dict(os.environ, {}, clear=True):
            receipt = render.run(self.args("--execute", "--max-api-calls", "0"))
            request.assert_not_called()
            self.assertEqual(receipt["skipped"], 3)
        self.assertTrue((self.out / "contact-sheet.png").exists())
        report = json.loads((self.out / "continuity-report.json").read_text())
        self.assertEqual(len(report["joins"]), 2)
        self.assertTrue(all(j["status"] == "human-review-required" for j in report["joins"]))

    def test_retry_cap_counts_failed_attempts(self):
        with self.execution([cli.APIError(429), cli.APIError(503)]) as request, patch("time.sleep"), self.assertRaises(RuntimeError):
            render.run(self.args("--execute", "--max-api-calls", "2"))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(self.manifest()["attempts"]), 2)
        self.assertEqual(self.manifest()["runs"][-1]["api_calls"], 2)

    def test_transient_retry_can_succeed_and_auth_never_retries(self):
        self.data["shots"] = [self.shot("01")]
        with self.execution([cli.APIError(503), (animation(), None)]) as request, patch("time.sleep"):
            receipt = render.run(self.args("--execute", "--max-api-calls", "2"))
            self.assertEqual(receipt["api_calls"], 2)
        self.out = self.root / "auth-failure"
        with self.execution([cli.APIError(401)]) as request, self.assertRaises(RuntimeError):
            render.run(self.args("--execute"))
        self.assertEqual(request.call_count, 1)

    def test_invalid_result_and_unknown_errors_not_retried_or_leaked(self):
        for value in ((b"GIF89a", None), RuntimeError("secret-fixture private provider body")):
            self.out = self.root / ("invalid" if isinstance(value, tuple) else "unknown")
            with self.execution([value]) as request, self.assertRaises(RuntimeError) as caught:
                render.run(self.args("--execute"))
            self.assertEqual(request.call_count, 1)
            self.assertNotIn("secret-fixture", str(caught.exception))
            self.assertNotIn("secret-fixture", (self.out / "render-manifest.json").read_text())

    def test_imports_zero_requests_and_invalid_input_preflight(self):
        self.imports()
        with self.execution() as request, patch.dict(os.environ, {}, clear=True):
            receipt = render.run(self.args("--execute", "--max-api-calls", "0"))
            request.assert_not_called()
            self.assertEqual(receipt["imported"], 3)
        self.out = self.root / "bad-import"
        (self.root / "source2.gif").write_bytes(b"GIF89a")
        with self.execution() as request, self.assertRaises(ValueError):
            render.run(self.args("--execute"))
        request.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_force_one_shot_preserves_other_accepted_shots(self):
        with self.execution():
            render.run(self.args("--execute"))
        before = self.manifest()["shots"]
        self.data["shots"][1]["prompt"] = "different action"
        with self.execution() as request, self.assertRaisesRegex(ValueError, "force-shot"):
            render.run(self.args("--execute"))
        request.assert_not_called()
        with self.execution() as request:
            receipt = render.run(self.args("--execute", "--force-shot", "02", "--max-api-calls", "1"))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(receipt["skipped"], 2)
        self.assertEqual(before["01"], self.manifest()["shots"]["01"])
        self.assertTrue((self.out / before["02"]["output"]).exists())

    def test_interrupted_request_requires_explicit_review(self):
        with self.execution([KeyboardInterrupt()]), self.assertRaises(KeyboardInterrupt):
            render.run(self.args("--execute"))
        with self.execution() as request, self.assertRaisesRegex(ValueError, "interrupted request"):
            render.run(self.args("--execute"))
        request.assert_not_called()

    def test_missing_ffmpeg_blocks_requests(self):
        with patch("gif_cinema.render.shutil.which", return_value=None), patch("gif_cinema.cli.request_gif") as request, self.assertRaisesRegex(RuntimeError, "ffmpeg"):
            render.run(self.args("--execute"))
        request.assert_not_called()

    def test_ffprobe_missing_invalid_fps_and_foreign_output_block_requests(self):
        with patch("gif_cinema.render.shutil.which", side_effect=lambda name: "ffmpeg" if name == "ffmpeg" else None), patch("gif_cinema.cli.request_gif") as request, self.assertRaisesRegex(RuntimeError, "ffprobe"):
            render.run(self.args("--execute"))
        request.assert_not_called()
        with self.execution() as request, self.assertRaisesRegex(ValueError, "fps"):
            render.run(self.args("--execute", "--fps", "0"))
        request.assert_not_called()
        self.out.mkdir(); (self.out / "keep.txt").write_text("unrelated")
        with self.execution() as request, self.assertRaisesRegex(ValueError, "not empty"):
            render.run(self.args("--execute"))
        request.assert_not_called()

    def test_changed_saved_gif_blocks_paid_calls(self):
        with self.execution():
            render.run(self.args("--execute"))
        record = self.manifest()["shots"]["01"]
        (self.out / record["output"]).write_bytes(b"broken")
        with self.execution() as request, self.assertRaisesRegex(ValueError, "missing or changed"):
            render.run(self.args("--execute"))
        request.assert_not_called()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
    def test_real_three_shot_movie_timing_resume_and_failed_export(self):
        self.imports()
        with patch("gif_cinema.cli.request_gif") as request:
            receipt = render.run(self.args("--execute", "--max-api-calls", "0"))
        request.assert_not_called()
        self.assertAlmostEqual(receipt["film_seconds"], 1.8, places=2)
        info = json.loads((self.out / "film-inspect.json").read_text())
        self.assertEqual(int(info["nb_read_frames"]), 45)
        original = (self.out / "film.mp4").read_bytes()
        with patch("gif_cinema.cli.film") as encoder:
            render.run(self.args("--execute", "--max-api-calls", "0"))
            encoder.assert_not_called()
        self.data["width"] = self.data["height"] = 64
        with patch("gif_cinema.cli.film", side_effect=RuntimeError("encoder failed")), self.assertRaises(RuntimeError):
            render.run(self.args("--execute", "--max-api-calls", "0"))
        self.assertEqual((self.out / "film.mp4").read_bytes(), original)

    def test_provider_usage_text_is_not_persisted(self):
        self.data["shots"] = [self.shot("01")]
        with self.execution([(animation(), {"total_tokens": 42, "debug": "secret-fixture"})]):
            render.run(self.args("--execute"))
        self.assertEqual(self.manifest()["shots"]["01"]["usage"], {"total_tokens": 42})
        self.assertNotIn("secret-fixture", (self.out / "render-manifest.json").read_text())


if __name__ == "__main__":
    unittest.main()
