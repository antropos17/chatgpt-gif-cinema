"""The benchmark must not leak hidden drawings or silently shift timestamps."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import contextlib
import io

from PIL import Image, ImageDraw
from tools.benchmark_interpolation import clean_rgb, decode_opaque, interpolate_known, motion_mask, run, score, split_indices


class BenchmarkTests(unittest.TestCase):
    def test_split_hides_all_bracketed_odd_drawings(self):
        known, hidden = split_indices(16)
        self.assertEqual(known, list(range(0, 16, 2)))
        self.assertEqual(hidden, list(range(1, 14, 2)))
        self.assertFalse(set(known) & set(hidden))
        self.assertNotIn(15, hidden)

    def test_transparency_metadata_is_removed_without_changing_pixels(self):
        source = Image.new("RGB", (16, 16), "red")
        source.info["transparency"] = (199, 141, 130)
        result = clean_rgb(source)
        self.assertEqual(result.info, {})
        self.assertEqual(result.tobytes(), source.tobytes())
        self.assertIn("transparency", source.info)

    def test_static_exact_match_has_finite_json_and_no_motion_score(self):
        image = Image.new("RGB", (16, 16), "red")
        scores = score(image, image, motion_mask(image, image))
        self.assertEqual(scores["mae_0_255"], 0)
        self.assertEqual(scores["mse"], 0)
        self.assertIsNone(scores["psnr_db"])
        self.assertIsNone(scores["motion_mae_0_255"])
        json.dumps(scores, allow_nan=False)

    def test_genuinely_transparent_gif_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            frames = []
            for x in (2, 5):
                image = Image.new("RGBA", (16, 16), (255, 0, 0, 0))
                ImageDraw.Draw(image).rectangle((x, 4, x + 4, 8), fill=(255, 255, 255, 255))
                frames.append(image)
            path = Path(directory) / "transparent.gif"
            frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, disposal=2)
            with self.assertRaisesRegex(ValueError, "opaque GIF"):
                decode_opaque(path)

    @unittest.skipUnless(shutil.which("ffmpeg"), "Installed FFmpeg required")
    def test_variable_timing_is_rejected_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [Image.new("RGB", (16, 16), color) for color in ("red", "blue", "white", "green", "black")]
            source = root / "variable.gif"
            frames[0].save(source, save_all=True, append_images=frames[1:], duration=[100, 200, 100, 200, 100])
            with self.assertRaisesRegex(ValueError, "uniform delays"):
                run([source], root / "results")
            self.assertFalse((root / "results").exists())

    @unittest.skipUnless(shutil.which("ffmpeg"), "Installed FFmpeg required")
    def test_real_ffmpeg_keeps_known_drawings_at_their_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            # Only five even-index drawings exist. No hidden truth is supplied.
            known = []
            for i in range(5):
                image = Image.new("RGB", (64, 64), "#303030")
                ImageDraw.Draw(image).rectangle((6 + i * 6, 20, 18 + i * 6, 38), fill="white")
                known.append(image)
            known[0].info["transparency"] = (20, 30, 40)
            frames, receipt = interpolate_known(known, 160, Path(directory))
            self.assertEqual(len(frames), 9)
            self.assertEqual(len(list((Path(directory) / "visible-inputs").glob("*.png"))), 5)
            self.assertLessEqual(max(receipt["known_frame_mae"]), 1)
            for path in (Path(directory) / "visible-inputs").glob("*.png"):
                with Image.open(path) as image:
                    self.assertNotIn("transparency", image.info)

    @unittest.skipUnless(shutil.which("ffmpeg"), "Installed FFmpeg required")
    def test_receipt_uses_custom_source_delay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = []
            for i in range(5):
                image = Image.new("RGB", (64, 64), "#303030")
                ImageDraw.Draw(image).rectangle((6 + i * 6, 20, 18 + i * 6, 38), fill="white")
                frames.append(image)
            source = root / "100ms.gif"
            frames[0].save(source, save_all=True, append_images=frames[1:], duration=100)
            with contextlib.redirect_stdout(io.StringIO()):
                result = run([source], root / "results")
            self.assertEqual(result["sources"][0]["native_delay_ms"], 100)
            self.assertEqual(result["sources"][0]["visible_gap_ms"], 200)
            self.assertNotIn("320 ms", " ".join(result["limitations"]))
            self.assertEqual([x["time_ms"] for x in result["samples"]], [100, 300])


if __name__ == "__main__":
    unittest.main()
