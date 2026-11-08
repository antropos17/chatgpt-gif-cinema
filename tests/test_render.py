"""Behavioral script-render tests. The real network is forbidden throughout."""
import contextlib
import base64
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from PIL import Image

from gif_cinema import cli, render
from gif_cinema import durability
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
                patch("gif_cinema.doctor.require_film_capabilities"), \
                patch("gif_cinema.doctor.inspect_tool", return_value={"available": True}), \
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

    def test_references_use_edit_endpoint_and_resume_without_exposing_image_bytes(self):
        reference = self.root / "hero.png"
        Image.new("RGB", (16, 16), "green").save(reference)
        self.data["shots"] = [{**self.shot("01"), "references": ["hero.png"]}]
        with self.execution() as request:
            render.run(self.args("--execute", "--retries", "0"))
            sent = request.call_args
            self.assertEqual(sent.kwargs["endpoint"], "https://api.openai.com/v1/images/edits")
            image_url = sent.args[0]["images"][0]["image_url"]
            self.assertEqual(base64.b64decode(image_url.split(",", 1)[1]), reference.read_bytes())
        manifest = self.manifest()
        self.assertEqual(manifest["shots"]["01"]["references"][0]["sha256"], render.digest(reference.read_bytes()))
        self.assertNotIn("data:image", json.dumps(manifest))
        with self.execution() as request:
            render.run(self.args("--execute", "--max-api-calls", "0"))
            request.assert_not_called()
        Image.new("RGB", (16, 16), "blue").save(reference)
        with self.execution() as request, self.assertRaisesRegex(ValueError, "force-shot"):
            render.run(self.args("--execute"))
        request.assert_not_called()

    def test_invalid_reference_in_last_shot_prevents_all_spending(self):
        self.data["shots"][-1]["references"] = ["invalid.png"]
        (self.root / "invalid.png").write_bytes(b"not an image")
        with self.execution() as request, self.assertRaises(OSError):
            render.run(self.args("--execute"))
        request.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_reference_change_during_run_stops_before_second_request(self):
        reference = self.root / "hero.png"
        Image.new("RGB", (16, 16), "green").save(reference)
        self.data["shots"] = [self.shot("01"), {**self.shot("02"), "references": ["hero.png"]}]
        def first_request(*args, **kwargs):
            Image.new("RGB", (16, 16), "red").save(reference)
            return animation(), None
        with self.execution(first_request) as request, self.assertRaisesRegex(ValueError, "Reference image changed"):
            render.run(self.args("--execute"))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.manifest()["runs"][-1]["api_calls"], 1)

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
        with self.execution([cli.APIError(429), cli.APIError(429)]) as request, patch("time.sleep"), self.assertRaises(RuntimeError):
            render.run(self.args("--execute", "--max-api-calls", "2"))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(self.manifest()["attempts"]), 2)
        self.assertEqual(self.manifest()["runs"][-1]["api_calls"], 2)

    def test_transient_retry_can_succeed_and_auth_never_retries(self):
        self.data["shots"] = [self.shot("01")]
        with self.execution([cli.APIError(429), (animation(), None)]) as request, patch("time.sleep"):
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

    def test_uncertain_request_blocks_restart_until_explicit_review(self):
        self.data["shots"] = [self.shot("01")]
        for index, value in enumerate((TimeoutError("secret-fixture"),
                                       URLError("secret-fixture"),
                                       RuntimeError("secret-fixture"),
                                       (b"GIF89a", None), cli.APIError(408), cli.APIError(503))):
            with self.subTest(value=type(value).__name__):
                self.out = self.root / f"uncertain-{index}"
                with self.execution([value]) as request, patch("time.sleep"), self.assertRaises(RuntimeError):
                    render.run(self.args("--execute"))
                self.assertEqual(request.call_count, 1)
                self.assertEqual(self.manifest()["attempts"][-1]["status"], "unknown")
                before = (self.out / "render-manifest.json").read_bytes()
                for flags in (("--execute",), ("--dry-run",)):
                    with self.execution() as request, self.assertRaisesRegex(ValueError, "unknown cost"):
                        render.run(self.args(*flags))
                    request.assert_not_called()
                self.assertEqual((self.out / "render-manifest.json").read_bytes(), before)
                with self.execution() as request:
                    render.run(self.args("--execute", "--force-shot", "01", "--max-api-calls", "1"))
                self.assertEqual(request.call_count, 1)
                with self.execution() as request:
                    render.run(self.args("--execute", "--max-api-calls", "0"))
                request.assert_not_called()

    def test_real_client_timeout_cannot_be_paid_again_on_restart(self):
        self.data["shots"] = [self.shot("01")]
        client = cli.request_gif
        def timeout(*args, **kwargs):
            raise TimeoutError("secret-fixture")
        def request_with_timeout(payload, key):
            return client(payload, key, transport=timeout)
        with self.execution(request_with_timeout) as request, self.assertRaises(RuntimeError):
            render.run(self.args("--execute"))
        self.assertEqual(request.call_count, 1)
        with self.execution() as request, self.assertRaisesRegex(ValueError, "unknown cost"):
            render.run(self.args("--execute"))
        request.assert_not_called()
        self.assertNotIn("secret-fixture", (self.out / "render-manifest.json").read_text())

    def test_legacy_failed_attempts_require_review_unless_definitely_rejected(self):
        self.data["shots"] = [self.shot("01")]
        errors = ("Operation failed; provider and process details omitted", "Validation failed",
                  "API HTTP 408", "API HTTP 503", "API HTTP 401", "API HTTP 429")
        for index, error in enumerate(errors):
            with self.subTest(error=error):
                self.out = self.root / f"legacy-{index}"
                self.out.mkdir()
                manifest = {"schema_version": 1, "shots": {}, "runs": [],
                            "attempts": [{"shot": "01", "status": "failed", "error": error}]}
                (self.out / "render-manifest.json").write_text(json.dumps(manifest))
                if error in {"API HTTP 401", "API HTTP 429"}:
                    with self.execution() as request:
                        render.run(self.args("--execute", "--max-api-calls", "1"))
                    self.assertEqual(request.call_count, 1)
                else:
                    with self.execution() as request, self.assertRaisesRegex(ValueError, "unknown cost"):
                        render.run(self.args("--execute"))
                    request.assert_not_called()
                self.assertEqual(self.manifest()["attempts"][0], manifest["attempts"][0])

    def test_definitively_rejected_request_can_restart_without_force(self):
        self.data["shots"] = [self.shot("01")]
        with self.execution([cli.APIError(401)]) as request, self.assertRaises(RuntimeError):
            render.run(self.args("--execute"))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.manifest()["attempts"][-1]["status"], "failed")
        self.assertEqual(self.manifest()["attempts"][-1]["http_status"], 401)
        with self.execution() as request:
            render.run(self.args("--execute", "--max-api-calls", "1"))
        self.assertEqual(request.call_count, 1)

    def test_failed_retake_preserves_and_reuses_accepted_footage(self):
        with self.execution():
            render.run(self.args("--execute"))
        before = self.manifest()["shots"]
        film = (self.out / "film.mp4").read_bytes()
        with self.execution([TimeoutError()]) as request, self.assertRaises(RuntimeError):
            render.run(self.args("--execute", "--force-shot", "02", "--max-api-calls", "1"))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.manifest()["shots"], before)
        self.assertEqual((self.out / "film.mp4").read_bytes(), film)
        with self.execution() as request:
            receipt = render.run(self.args("--execute", "--max-api-calls", "0"))
        request.assert_not_called()
        self.assertEqual(receipt["skipped"], 3)

    def test_local_publication_failure_keeps_request_unresolved(self):
        self.data["shots"] = [self.shot("01")]
        write = cli.write_result
        def fail_gif(path, *args, **kwargs):
            if path.suffix == ".gif":
                raise OSError("fixture disk failure")
            return write(path, *args, **kwargs)
        with self.execution() as request, patch("gif_cinema.cli.write_result", side_effect=fail_gif), self.assertRaises(OSError):
            render.run(self.args("--execute"))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.manifest()["attempts"][-1]["status"], "started")
        with self.execution() as request, self.assertRaisesRegex(ValueError, "unknown cost"):
            render.run(self.args("--execute"))
        request.assert_not_called()

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

    def test_missing_encoder_or_filters_blocks_before_key_lookup_or_output(self):
        environment_get = os.environ.get
        def no_key(name, *args):
            if name == 'OPENAI_API_KEY':
                raise AssertionError('Key lookup forbidden')
            return environment_get(name, *args)
        for capability in ('h264_encoder', 'core_filters'):
            caps = {'h264_encoder': True, 'core_filters': True}
            caps[capability] = False
            with self.subTest(capability=capability), \
                    patch('gif_cinema.render.shutil.which', return_value='fixture'), \
                    patch('gif_cinema.doctor.inspect_ffmpeg_capabilities', return_value=caps), \
                    patch('os.environ.get', side_effect=no_key), \
                    patch('gif_cinema.cli.request_gif') as request, self.assertRaisesRegex(RuntimeError, 'FFmpeg'):
                render.run(self.args('--execute'))
            request.assert_not_called()
            self.assertFalse(self.out.exists())

    def test_unusable_ffprobe_blocks_requests_and_output_creation(self):
        with patch('gif_cinema.render.shutil.which', return_value='fixture'), \
                patch('gif_cinema.doctor.require_film_capabilities'), \
                patch('gif_cinema.doctor.inspect_tool', return_value={'available': False}), \
                patch('gif_cinema.cli.request_gif') as request, self.assertRaisesRegex(RuntimeError, 'ffprobe could not run'):
            render.run(self.args('--execute'))
        request.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_audio_capabilities_are_checked_before_paid_calls(self):
        (self.root / 'audio.wav').write_bytes(b'local audio fixture')
        self.data['audio'] = 'audio.wav'
        caps = {'h264_encoder': True, 'core_filters': True, 'aac_encoder': False, 'audio_padding': True}
        with patch('gif_cinema.render.shutil.which', return_value='fixture'), \
                patch('gif_cinema.doctor.inspect_ffmpeg_capabilities', return_value=caps), \
                patch('gif_cinema.cli.request_gif') as request, self.assertRaisesRegex(RuntimeError, 'AAC encoder'):
            render.run(self.args('--execute'))
        request.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_dry_run_never_probes_local_tools(self):
        with patch('gif_cinema.doctor.inspect_ffmpeg_capabilities') as capabilities, \
                patch('gif_cinema.doctor.inspect_tool') as tool:
            render.run(self.args('--dry-run'))
        capabilities.assert_not_called()
        tool.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_render_attempt_is_file_and_directory_synced_before_dispatch(self):
        self.data['shots'] = [self.shot('01')]
        events = []
        real_fsync = os.fsync
        real_write = durability.durable_write
        def fsync(fd):
            real_fsync(fd)
            events.append('fsync')
        def write(path, raw):
            before = len(events)
            real_write(path, raw)
            if path.name == 'render-manifest.json' and json.loads(raw).get('attempts'):
                self.assertGreater(len(events), before)
                events.append('synced attempt')
        def request(*args, **kwargs):
            self.assertEqual(events[-1], 'synced attempt')
            self.assertEqual(self.manifest()['attempts'][-1]['status'], 'started')
            return animation(), None
        with self.execution(request), patch.object(render, 'durable_write', side_effect=write), \
                patch('gif_cinema.durability.os.fsync', side_effect=fsync):
            render.run(self.args('--execute', '--max-api-calls', '1'))

    def test_pre_request_file_sync_failure_prevents_dispatch(self):
        real_write = durability.durable_write
        def fail_attempt(path, raw):
            if path.name == 'render-manifest.json' and json.loads(raw).get('attempts'):
                with patch('gif_cinema.durability.os.fsync', side_effect=OSError('file fsync failed')):
                    return real_write(path, raw)
            return real_write(path, raw)
        with self.execution() as request, patch.object(render, 'durable_write', side_effect=fail_attempt):
            with self.assertRaisesRegex(OSError, 'file fsync failed'):
                render.run(self.args('--execute'))
        request.assert_not_called()
        self.assertEqual(self.manifest()['attempts'], [])
        self.assertFalse(list(self.out.glob('*.tmp')))
        self.assertFalse(list(self.out.glob('*.lock')))

    def test_pre_request_directory_sync_failure_keeps_started_attempt_blocked(self):
        real_write = durability.durable_write
        def fail_attempt(path, raw):
            if path.name == 'render-manifest.json' and json.loads(raw).get('attempts'):
                with patch('gif_cinema.durability.sync_directory', side_effect=OSError('directory fsync failed')):
                    return real_write(path, raw)
            return real_write(path, raw)
        with self.execution() as request, patch.object(render, 'durable_write', side_effect=fail_attempt):
            with self.assertRaisesRegex(OSError, 'directory fsync failed'):
                render.run(self.args('--execute'))
        request.assert_not_called()
        self.assertEqual(self.manifest()['attempts'][-1]['status'], 'started')
        with self.execution() as request, self.assertRaisesRegex(ValueError, 'unknown cost'):
            render.run(self.args('--execute'))
        request.assert_not_called()

    def test_new_project_directory_sync_failure_prevents_dispatch(self):
        with self.execution() as request, patch.object(render, 'sync_directory', side_effect=OSError('directory fsync failed')):
            with self.assertRaisesRegex(OSError, 'directory fsync failed'):
                render.run(self.args('--execute'))
        request.assert_not_called()
        self.assertFalse((self.out / 'render-manifest.json').exists())

    def test_nested_project_directory_entries_are_synced(self):
        self.out = self.root / 'new' / 'nested' / 'project'
        with patch.object(render, 'sync_directory') as sync:
            render.create_project_directory(self.out)
        self.assertEqual([call.args[0] for call in sync.call_args_list],
                         [self.out.parent, self.out.parent.parent, self.root])

    def test_oversized_import_in_last_shot_prevents_all_requests(self):
        self.data['shots'][-1] = {'id': '03', 'source': 'large.gif',
                                   'first_frame_target': 'red', 'last_frame_target': 'blue'}
        (self.root / 'large.gif').write_bytes(animation())
        with patch.object(cli, 'MAX_GIF_PIXEL_FRAMES', 1), self.execution() as request:
            with self.assertRaisesRegex(ValueError, 'pixel budget'):
                render.run(self.args('--execute'))
        request.assert_not_called()
        self.assertFalse(self.out.exists())

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

    def test_older_export_is_rebuilt_locally_without_new_generation(self):
        with self.execution():
            render.run(self.args("--execute"))
        manifest = self.manifest()
        old_movie = (self.out / "film.mp4").read_bytes()
        manifest["film"]["fingerprint"] = render.digest(render.encoded({
            "shots": [r["sha256"] for r in manifest["shots"].values()],
            "width": 32, "height": 32, "fps": 25, "audio": None}))
        (self.out / "render-manifest.json").write_text(json.dumps(manifest))
        with self.execution() as request, patch("gif_cinema.cli.film") as encode:
            encode.side_effect = lambda args: Path(args.output).write_bytes(b"updated offline film")
            render.run(self.args("--execute", "--max-api-calls", "0"))
        request.assert_not_called()
        encode.assert_called_once()
        archive = self.out / f"film-{render.digest(old_movie)[:16]}.mp4"
        self.assertEqual(archive.read_bytes(), old_movie)

    def test_probe_rejects_decodable_movie_with_a_missing_frame(self):
        info = {"codec_name": "h264", "width": 32, "height": 32,
                "duration": "1.76", "nb_read_frames": "44"}
        with patch("gif_cinema.cli.subprocess.run") as run, self.assertRaisesRegex(RuntimeError, "verification"):
            run.return_value.stdout = json.dumps({"streams": [info]}).encode()
            render.probe(self.root / "film.mp4", 32, 32, 1.8, 25, 3)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
    def test_short_shot_caption_matches_minimum_one_frame(self):
        self.imports()
        self.data["fps"] = 1
        self.data["shots"] = self.data["shots"][:1]
        (self.root / "source0.gif").write_bytes(animation((20, 20)))
        with patch("gif_cinema.cli.request_gif") as request:
            receipt = render.run(self.args("--execute", "--max-api-calls", "0"))
        request.assert_not_called()
        self.assertEqual(receipt["film_seconds"], 1.0)
        self.assertIn("00:00:00,000 --> 00:00:01,000", (self.out / "captions.srt").read_text())


if __name__ == "__main__":
    unittest.main()
