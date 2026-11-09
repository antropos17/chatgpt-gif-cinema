"""Offline source identity, timing and decoded-frame gallery regression checks."""
import copy
import hashlib
import errno
import io
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image
from gif_cinema import cli

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("example_gallery", ROOT / "tools/inspect_example_sources.py")
gallery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gallery)


class ExampleGalleryTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(gallery.CATALOG.read_text(encoding="utf-8"))

    def symlink_or_skip(self, link, target, **kwargs):
        try:
            link.symlink_to(target, **kwargs)
        except NotImplementedError:
            self.skipTest("This platform does not implement symlinks")
        except OSError as exc:
            unsupported = {errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}
            if getattr(exc, "winerror", None) in {1, 50, 1314} or exc.errno in unsupported:
                self.skipTest("Symlink creation is unsupported or requires Windows Developer Mode")
            raise

    def small_gif(self):
        data = io.BytesIO()
        Image.new("RGB", (16, 16), "red").save(
            data, format="GIF", save_all=True,
            append_images=[Image.new("RGB", (16, 16), "blue")],
            duration=100, loop=0, optimize=False, disposal=2)
        return data.getvalue()

    def expanded_canvas_gif(self):
        raw = bytearray(self.small_gif())
        descriptor = b"," + b"\0" * 4 + b"\x10\0\x10\0"
        self.assertEqual(raw.count(descriptor), 2)
        offset = raw.rindex(descriptor)
        raw[offset + 1:offset + 3] = (1000).to_bytes(2, "little")
        raw[offset + 3:offset + 5] = (1000).to_bytes(2, "little")
        return bytes(raw)

    def test_expanded_second_frame_is_rejected_before_any_decoder_dispatch(self):
        raw = self.expanded_canvas_gif()
        # Confirm the audit fixture really expands Pillow's composed canvas.
        frames, _, _ = cli.validate_gif(io.BytesIO(raw))
        self.assertEqual([frame.size for frame in frames], [(16, 16), (1016, 1016)])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "expanded.gif"
            path.write_bytes(raw)
            with mock.patch.object(gallery.Image, "open") as decoder:
                with self.assertRaisesRegex(ValueError, "fixed logical canvas"):
                    gallery.source_facts(path)
                decoder.assert_not_called()

    def test_example_caps_are_checked_before_decoder_dispatch(self):
        raw = self.small_gif()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "small.gif"
            path.write_bytes(raw)
            limits = (("MAX_EXAMPLE_FRAMES", 1, "frame limit"),
                      ("MAX_EXAMPLE_PIXEL_FRAMES", 2 * 16 * 16 - 1, "pixel budget"),
                      ("MAX_EXAMPLE_BYTES", len(raw) - 1, "inspection budget"))
            for name, cap, message in limits:
                with self.subTest(limit=name), mock.patch.object(gallery, name, cap):
                    with mock.patch.object(gallery.Image, "open") as decoder:
                        with self.assertRaisesRegex(ValueError, message):
                            gallery.source_facts(path)
                        decoder.assert_not_called()
            with mock.patch.object(gallery, "MAX_EXAMPLE_FRAMES", 2), \
                    mock.patch.object(gallery, "MAX_EXAMPLE_PIXEL_FRAMES", 512), \
                    mock.patch.object(gallery, "MAX_EXAMPLE_BYTES", len(raw)):
                self.assertEqual(gallery.source_facts(path)["frames"], 2)

    def test_actual_read_is_bounded_without_trusting_stat(self):
        class GrowingSource(io.BytesIO):
            def read(self, amount=-1):
                self.amount = amount
                return b"x" * amount
        source = GrowingSource()
        with mock.patch.object(Path, "open", return_value=source), \
                mock.patch.object(gallery, "MAX_EXAMPLE_BYTES", 100), \
                self.assertRaisesRegex(ValueError, "inspection budget"):
            gallery.read_source_bytes(Path("growing.gif"))
        self.assertEqual(source.amount, 101)

    def test_catalog_hash_is_checked_before_decoder_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "changed.gif"
            path.write_bytes(self.small_gif())
            with mock.patch.object(gallery.Image, "open") as decoder:
                with self.assertRaisesRegex(ValueError, "sha256 differs"):
                    gallery.source_facts(path, "0" * 64)
                decoder.assert_not_called()

    def test_storyboard_also_uses_hashed_preflighted_bytes(self):
        raw = self.expanded_canvas_gif()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "expanded.gif").write_bytes(raw)
            source = copy.deepcopy(self.catalog["sources"][0])
            source.update(path="expanded.gif", sha256=hashlib.sha256(raw).hexdigest())
            with mock.patch.object(gallery.Image, "open") as decoder:
                with self.assertRaisesRegex(ValueError, "fixed logical canvas"):
                    gallery.storyboard({"sources": [source]}, root)
                decoder.assert_not_called()

    def test_shared_preflight_tighter_caps_cannot_expand_core_limits(self):
        raw = self.small_gif()
        with mock.patch.object(cli, "MAX_GIF_FRAMES", 1), \
                self.assertRaisesRegex(ValueError, "frame limit"):
            cli.check_gif_limits(raw, max_frames=1000)
        with mock.patch.object(cli, "MAX_GIF_PIXEL_FRAMES", 511), \
                self.assertRaisesRegex(ValueError, "pixel budget"):
            cli.check_gif_limits(raw, max_pixel_frames=1000000)
        for invalid in (0, -1, True, "256"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "positive integer"):
                cli.check_gif_limits(raw, max_frames=invalid)

    def test_real_sources_match_catalog_and_native_timing(self):
        report = gallery.verify_catalog(self.catalog)
        self.assertEqual(report["source_count"], 3)
        self.assertEqual(report["source_frames"], 48)
        self.assertEqual(report["native_action_ms"], 7680)
        self.assertEqual(report["provider_calls"], 0)
        for source in report["sources"]:
            self.assertEqual(source["durations_ms"], [160] * 16)
            self.assertEqual(source["unique_frames"], 16)
            self.assertEqual(source["loop"], 0)
            self.assertEqual((source["width"], source["height"]), (512, 512))

    def test_checked_in_storyboard_and_receipt_are_consistent(self):
        folder = ROOT / "docs/assets/example-gallery"
        report = json.loads((folder / "source-report.json").read_text())
        verified = gallery.verify_catalog(self.catalog)
        for key, value in verified.items():
            self.assertEqual(report[key], value)
        for name, digest in report["outputs"].items():
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest)

    def test_published_titled_gif_matches_source_and_output_receipt(self):
        folder = ROOT / "docs/assets/example-gallery"
        receipt = json.loads((folder / "titled-story-receipt.json").read_text())
        facts = gallery.source_facts(folder / "titled-story.gif")
        self.assertEqual(facts["sha256"], receipt["gif_sha256"])
        self.assertEqual(facts["total_duration_ms"], 9700)
        self.assertEqual(facts["frames"], 97)
        self.assertIsNone(facts["loop"])
        self.assertEqual((facts["width"], facts["height"]), (320, 320))
        self.assertEqual(receipt["provider_calls"], 0)
        self.assertEqual(receipt["new_character_drawings"], 0)
        self.assertEqual(receipt["sources"], [{"path": s["path"], "sha256": s["sha256"]}
                                              for s in self.catalog["sources"]])

    def test_changed_facts_are_rejected(self):
        for field in gallery.FACTS:
            with self.subTest(field=field):
                catalog = copy.deepcopy(self.catalog)
                catalog["sources"][0][field] = "wrong"
                with self.assertRaisesRegex(ValueError, field):
                    gallery.verify_catalog(catalog)

    def test_sources_cannot_escape_or_use_symlinks(self):
        for path in ("../outside.gif", "/tmp/outside.gif", "missing.gif", ""):
            with self.subTest(path=path), self.assertRaises(ValueError):
                gallery.safe_source(ROOT, path)
    def test_symlinked_source_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "source.gif"
            target.write_bytes(b"GIF89a")
            self.symlink_or_skip(root / "link.gif", target)
            with self.assertRaisesRegex(ValueError, "Symlinked"):
                gallery.safe_source(root, "link.gif")

    def test_duplicate_source_and_id_are_not_extra_actions(self):
        for field in ("id", "path"):
            catalog = copy.deepcopy(self.catalog)
            catalog["sources"][1][field] = catalog["sources"][0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                gallery.verify_catalog(catalog)

    def test_schema_and_source_budget(self):
        for invalid in (True, 2, "1"):
            catalog = copy.deepcopy(self.catalog)
            catalog["schema_version"] = invalid
            with self.assertRaises(ValueError):
                gallery.verify_catalog(catalog)
        for sources in ([], self.catalog["sources"] * 5):
            catalog = copy.deepcopy(self.catalog)
            catalog["sources"] = sources
            with self.assertRaises(ValueError):
                gallery.verify_catalog(catalog)

    def test_gallery_uses_actual_sample_indices_and_keeps_inputs(self):
        before = {s["path"]: hashlib.sha256((ROOT / s["path"]).read_bytes()).hexdigest()
                  for s in self.catalog["sources"]}
        with tempfile.TemporaryDirectory() as tmp, mock.patch("socket.socket", side_effect=AssertionError("Network forbidden")):
            out = Path(tmp) / "gallery"
            report = gallery.build(out, self.catalog)
            self.assertEqual([s["frame_index"] for s in report["sampled_frames"]], [0, 8, 15] * 3)
            self.assertEqual([s["start_ms"] for s in report["sampled_frames"]], [0, 1280, 2400] * 3)
            self.assertEqual(json.loads((out / "source-report.json").read_text()), report)
            sheet = out / "astronaut-storyboard.png"
            self.assertEqual(hashlib.sha256(sheet.read_bytes()).hexdigest(), report["outputs"][sheet.name])
            with Image.open(sheet) as image:
                self.assertEqual(image.size, (1040, 1372))
            self.assertEqual(report["visual_acceptance"], "human-review-required")
        self.assertEqual(before, {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in before})

    def test_existing_output_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "keep.txt"
            marker.write_text("original")
            with self.assertRaisesRegex(ValueError, "new directory"):
                gallery.build(root, self.catalog)
            self.assertEqual(marker.read_text(), "original")

    def test_symlinked_output_is_refused_when_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.symlink_or_skip(root / "link", root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                gallery.build(root / "link" / "new", self.catalog)

    def test_symlink_guard_only_skips_unsupported_creation(self):
        privilege_error = OSError("Windows symlink privilege unavailable")
        privilege_error.winerror = 1314
        with mock.patch.object(Path, "symlink_to", side_effect=privilege_error):
            with self.assertRaises(unittest.SkipTest):
                self.symlink_or_skip(Path("link"), Path("target"))
        with mock.patch.object(Path, "symlink_to", side_effect=PermissionError(errno.EACCES, "unrelated denial")):
            with self.assertRaises(PermissionError):
                self.symlink_or_skip(Path("link"), Path("target"))

    def test_old_pillow_font_remains_supported(self):
        real_font = gallery.ImageFont.load_default()
        with mock.patch.object(gallery.ImageFont, "load_default", side_effect=[TypeError("size"), real_font]):
            self.assertIs(gallery.font(18), real_font)

    def test_cli_check_works_outside_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, str(ROOT / "tools/inspect_example_sources.py"), "--check"],
                                    cwd=tmp, capture_output=True, text=True, check=True, timeout=30)
            self.assertEqual(json.loads(result.stdout)["native_action_ms"], 7680)
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
