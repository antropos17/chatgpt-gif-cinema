"""Decode the published gallery rather than trusting descriptive metadata."""
import hashlib
import json
from pathlib import Path
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / "examples" / "anime-pixel"


class AnimeGalleryTests(unittest.TestCase):
    def test_draft_film_export(self):
        receipt = json.loads((GALLERY / "film-verification.json").read_text())
        for extension, entry in receipt.items():
            raw = (GALLERY / ("lantern-festival-15s." + extension)).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])
            self.assertEqual(len(raw), entry["bytes"])
        with Image.open(GALLERY / "lantern-festival-15s.gif") as image:
            self.assertEqual(image.size, (480, 270))
            self.assertEqual(image.n_frames, 128)
            self.assertIsNone(image.info.get("loop"))
            frames, delays = [], []
            for index in range(image.n_frames):
                image.seek(index)
                frames.append(image.convert("RGBA").tobytes())
                delays.append(image.info["duration"])
            self.assertEqual(len(set(frames)), 128)
            self.assertEqual(delays, [120] * 128)
            self.assertEqual(sum(delays), receipt["gif"]["duration_ms"])

    def test_published_media_matches_receipt(self):
        receipt = json.loads((GALLERY / "verification.json").read_text())
        self.assertEqual(len(receipt["files"]), 6)
        for entry in receipt["files"]:
            with self.subTest(file=entry["file"]):
                path = GALLERY / entry["file"]
                raw = path.read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])
                self.assertEqual(len(raw), entry["bytes"])
                with Image.open(path) as image:
                    self.assertEqual(image.format, "GIF")
                    self.assertEqual(list(image.size), [entry["width"], entry["height"]])
                    self.assertEqual(image.n_frames, entry["frames"])
                    self.assertEqual(image.info.get("loop"), 0)
                    frames, delays = [], []
                    for index in range(image.n_frames):
                        image.seek(index)
                        frames.append(image.convert("RGBA").tobytes())
                        delays.append(image.info["duration"])
                    self.assertEqual(delays, entry["frame_delays_ms"])
                    self.assertEqual(delays, [120] * entry["frames"])
                    self.assertEqual(sum(delays), entry["duration_ms"])
                    self.assertEqual(len(set(frames)), entry["unique_frames"])
                    self.assertEqual(frames[0] == frames[-1], entry["first_equals_last"])
                    if "top_140_background_rows_identical" in entry:
                        self.assertTrue(entry["top_140_background_rows_identical"])
                        self.assertEqual(len({f[:image.width * 140 * 4] for f in frames}), 1)

    def test_posters_are_first_decoded_frames(self):
        for poster in GALLERY.glob("*-poster.png"):
            with self.subTest(file=poster.name):
                with Image.open(poster) as still, Image.open(
                    GALLERY / (poster.stem.removesuffix("-poster") + ".gif")
                ) as source:
                    self.assertEqual(still.convert("RGBA").tobytes(), source.convert("RGBA").tobytes())


if __name__ == "__main__":
    unittest.main()
