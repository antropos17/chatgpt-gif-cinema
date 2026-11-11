"""Verify the separate, individually addressable outfit drawings."""
import hashlib
import json
from pathlib import Path
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / "examples/anime-pixel/outfit-poses"


class OutfitPoseGalleryTests(unittest.TestCase):
    def test_separate_drawings_and_gif_facts(self):
        records = json.loads((GALLERY / "verification.json").read_text())
        self.assertEqual({r["outfit"] for r in records}, {"casual", "traveler", "festival"})
        for record in records:
            with self.subTest(outfit=record["outfit"]):
                raw = (GALLERY / record["file"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])
                self.assertEqual(len(raw), record["bytes"])
                self.assertEqual(len(record["png_frames"]), 32)
                frames, pngs, delays, bottoms = [], [], [], []
                with Image.open(GALLERY / record["file"]) as gif:
                    self.assertEqual(gif.format, "GIF")
                    self.assertEqual(gif.size, (320, 320))
                    self.assertEqual(gif.n_frames, 32)
                    self.assertEqual(gif.info["loop"], 0)
                    for index, entry in enumerate(record["png_frames"]):
                        self.assertEqual(entry["file"], f'{record["outfit"]}/{index:02d}.png')
                        png_raw = (GALLERY / entry["file"]).read_bytes()
                        self.assertEqual(hashlib.sha256(png_raw).hexdigest(), entry["sha256"])
                        gif.seek(index)
                        frame = gif.convert("RGBA")
                        alpha = frame.getchannel("A")
                        frames.append(frame.tobytes())
                        delays.append(gif.info["duration"])
                        bottoms.append(alpha.getbbox()[3])
                        self.assertEqual(alpha.getextrema(), (0, 255))
                        with Image.open(GALLERY / entry["file"]) as png:
                            self.assertEqual(png.size, gif.size)
                            pngs.append(png.convert("RGBA").tobytes())
                            self.assertEqual(png.convert("RGBA").getchannel("A").tobytes(), alpha.tobytes())
                    self.assertEqual(delays, [80] * 32)
                    self.assertEqual(sum(delays), record["duration_ms"])
                    self.assertEqual(len(set(frames)), 32)
                    self.assertEqual(len(set(pngs)), 32)
                    self.assertEqual(len(set(bottoms)), 1)
                    with Image.open(GALLERY / (record["outfit"] + "-poster.png")) as poster:
                        self.assertEqual(poster.convert("RGBA").tobytes(), frames[0])


if __name__ == "__main__":
    unittest.main()
