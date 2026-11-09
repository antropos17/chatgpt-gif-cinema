"""Offline fixture validation only; no paid generation or aesthetic assertions."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import cli, motion, render


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.network = patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def run_cmd(self, *argv):
        args = cli.build_parser().parse_args(["motion", *map(str, argv)])
        with contextlib.redirect_stdout(io.StringIO()):
            args.func(args)

    def compile(self, route="openai-direct-16"):
        out = self.root / route
        self.run_cmd("compile", "--route", route, "--out", out)
        return out

    def test_profiles_and_reproducibility(self):
        prompts = set()
        for name in motion.PRESETS:
            a = motion.compile_request(name, "openai-direct-16")
            self.assertEqual(a, motion.compile_request(name, "openai-direct-16"))
            self.assertEqual(a["parameters"]["model"], "gpt-image-2.6-flare")
            self.assertEqual(a["dispatch"]["endpoint"], cli.API_URL)
            self.assertNotIn("background", a["parameters"])
            self.assertEqual(a["artifact_requirements"], {"background": "opaque"})
            prompts.add(a["source_prompt"])
            for route in motion.ROUTES:
                p = motion.compile_request(name, route)["parameters"]
                self.assertEqual(p["frame_count"] * p["frame_duration_ms"], 3200)
                self.assertEqual(p["frame_count"], 16)
        self.assertEqual(len(prompts), 6)

    def test_default_route_is_direct_and_other_routes_rejected(self):
        out = self.root / "default-direct"
        self.run_cmd("compile", "--out", out)
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual(manifest["route"], "openai-direct-16")
        self.assertEqual(motion.ROUTES, ("openai-direct-16",))
        with self.assertRaises(ValueError):
            motion.compile_request("chrome-trefoil", "unsupported-third-party")

    def test_manifest_and_exact_direct_payloads(self):
        out = self.compile("openai-direct-16")
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual(manifest["paid_calls_made"], 0)
        for item in manifest["requests"]:
            request_path = out / item["request"]
            request, digest = motion.read_request(request_path)
            self.assertEqual(digest, item["sha256"])
            script_path = out / (item["preset"] + ".film.json")
            args = cli.build_parser().parse_args(["render", str(script_path), "--dry-run"])
            script = render.load_script(script_path, args)
            self.assertEqual(script["shots"][0]["payload"], request["parameters"])

    def test_no_clobber_and_symlink_ancestor(self):
        out = self.compile()
        with self.assertRaises(FileExistsError):
            self.compile()
        link = self.root / "link"
        link.symlink_to(out, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.run_cmd("compile", "--route", motion.ROUTES[0], "--out", link / "child")
        self.assertFalse((out / "child").exists())

    def test_failure_cleans_partial_output(self):
        out = self.root / "failed"
        with patch.object(motion, "write_result", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                self.run_cmd("compile", "--route", motion.ROUTES[0], "--out", out)
        self.assertFalse(out.exists())

    def test_inspect_actual_frames_and_warnings(self):
        out = self.compile()
        source = self.root / "actual.gif"
        frames = [Image.new("RGB", (16, 16), color) for color in ("red", "green", "blue")]
        frames[0].save(source, save_all=True, append_images=frames[1:], duration=[50, 60, 70], loop=1)
        digest = motion.sha(source.read_bytes())
        report_dir = self.root / "review"
        self.run_cmd("inspect", source, "--request", out / "chrome-trefoil.request.json", "--out", report_dir)
        report = json.loads((report_dir / "inspection.json").read_text())
        self.assertEqual(report["actual"]["frame_durations_ms"], [50, 60, 70])
        self.assertEqual(report["actual"]["unique_decoded_frames"], 3)
        self.assertEqual(report["gif_sha256"], digest)
        self.assertEqual(motion.sha(source.read_bytes()), digest)
        self.assertEqual(report["visual_status"], "human-review-required")
        self.assertEqual(len(report["warnings"]), 4)
        self.assertTrue((report_dir / "contact-sheet.png").is_file())
        self.assertEqual(report["contact_sheet_frame_indices"], [0, 1, 2])

    def native_fixture(self, *, transparent=False, unused_transparency=False):
        """Full requested profile with cheap flat-color synthetic drawings."""
        frames = []
        palette = [0, 0, 0, 230, 30, 100, 40, 80, 200] + [0] * (768 - 9)
        for index in range(16):
            frame = Image.new("P", (512, 512), 1 + index % 2)
            frame.putpalette(palette)
            if transparent:
                frame.putpixel((0, 0), 0)
            frames.append(frame)
        stream = io.BytesIO()
        options = {"transparency": 0} if transparent or unused_transparency else {}
        frames[0].save(stream, format="GIF", save_all=True,
                       append_images=frames[1:], duration=200, loop=0,
                       optimize=False, disposal=2, **options)
        return stream.getvalue()

    def inspect_fixture(self, raw, name):
        plan = self.root / "openai-direct-16"
        if not plan.exists():
            self.compile()
        source = self.root / (name + ".gif")
        source.write_bytes(raw)
        target = self.root / (name + "-review")
        self.run_cmd("inspect", source, "--request", plan / "chrome-trefoil.request.json", "--out", target)
        self.assertEqual(source.read_bytes(), raw)
        return json.loads((target / "inspection.json").read_text())

    def test_composited_transparency_prevents_opaque_match(self):
        report = self.inspect_fixture(self.native_fixture(transparent=True), "transparent")
        self.assertEqual(report["technical_status"], "decoded-with-warnings")
        self.assertEqual(report["visual_status"], "human-review-required")
        self.assertFalse(report["actual"]["all_frames_opaque"])
        self.assertEqual(report["actual"]["transparent_frame_indices"], list(range(16)))
        self.assertEqual(len(report["warnings"]), 1)
        self.assertIn("transparent pixels", report["warnings"][0])

    def test_later_canvas_expansion_prevents_dimension_match(self):
        raw = bytearray(self.native_fixture())
        # Full-frame descriptors in this controlled fixture: move frame two down
        # one pixel without changing its compressed image or the logical screen.
        descriptor = b"\x2c\x00\x00\x00\x00\x00\x02\x00\x02"
        offsets = [i for i in range(len(raw)) if raw[i:i + len(descriptor)] == descriptor]
        self.assertEqual(len(offsets), 16)
        raw[offsets[1] + 3] = 1
        report = self.inspect_fixture(bytes(raw), "expanded")
        self.assertEqual(report["actual"]["frame_dimensions"][0], [512, 512])
        self.assertEqual(report["actual"]["frame_dimensions"][1], [512, 513])
        self.assertEqual(report["technical_status"], "decoded-with-warnings")
        self.assertEqual(report["visual_status"], "human-review-required")
        self.assertTrue(any("dimensions" in warning for warning in report["warnings"]))

    def test_unused_transparency_metadata_does_not_reject_opaque_pixels(self):
        report = self.inspect_fixture(self.native_fixture(unused_transparency=True), "opaque")
        self.assertEqual(report["technical_status"], "requested-format-matched")
        self.assertTrue(report["actual"]["all_frames_opaque"])
        self.assertEqual(report["actual"]["transparent_frame_indices"], [])

    def test_malformed_metadata_is_a_validation_error(self):
        for value in ([], {}, None, 7):
            with self.assertRaises(ValueError):
                motion.compile_request(value, motion.ROUTES[0])
            with self.assertRaises(ValueError):
                motion.compile_request("chrome-trefoil", value)
        path = self.root / "bad.json"
        path.write_text(json.dumps({"preset": [], "route": motion.ROUTES[0]}))
        with self.assertRaises(ValueError):
            motion.read_request(path)

    def test_invalid_media_and_tampered_request_rejected_before_output(self):
        out = self.compile()
        request = out / "chrome-trefoil.request.json"
        source = self.root / "fake.gif"
        source.write_bytes(b"not a gif")
        target = self.root / "review"
        with self.assertRaises(ValueError):
            self.run_cmd("inspect", source, "--request", request, "--out", target)
        self.assertFalse(target.exists())
        data = json.loads(request.read_text())
        data["parameters"]["frame_count"] = 8
        request.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "differs"):
            motion.read_request(request)


if __name__ == "__main__":
    unittest.main()
