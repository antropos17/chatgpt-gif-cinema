import importlib.util
import tempfile
import unittest
from pathlib import Path
from PIL import Image

spec = importlib.util.spec_from_file_location("character_grid", Path(__file__).resolve().parents[1] / "tools/build_character_grid.py")
grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid)


class CharacterGridTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        a, b = Image.new("RGB", (8, 8), "red"), Image.new("RGB", (8, 8), "blue")
        a.save(self.root / "motion.gif", save_all=True, append_images=[b], duration=[80, 120], loop=0)
        a.save(self.root / "still.png")
        (self.root / "source.md").write_text("Cutout study, not new drawing poses")
        self.item = dict(id="hero-01", name='Hero <one>', gif="motion.gif", source="source.md", method="cutout", poster="still.png", limitations="Not new poses.")

    def test_real_gif_measured_and_escaped(self):
        markup, facts = grid.build_grid(self.root, [self.item])
        self.assertIn("Hero &lt;one&gt;", markup)
        self.assertIn("Cutout animation", markup)
        self.assertIn("prefers-reduced-motion: reduce", markup)
        self.assertIn('srcset="still.png"', markup)
        self.assertIn("0.20 s", markup)
        self.assertEqual(facts[0]["unique_decoded_frames"], 2)
        self.assertEqual(facts[0]["duration_ms"], 200)

    def test_static_rejected(self):
        self.item["gif"] = "still.png"
        with self.assertRaises(ValueError):
            grid.build_grid(self.root, [self.item])

    def test_duplicate_id_and_gif_rejected(self):
        for second in [dict(self.item), dict(self.item, id="hero-02")]:
            with self.assertRaises(ValueError):
                grid.build_grid(self.root, [self.item, second])

    def test_escaping_repository_rejected(self):
        self.item["gif"] = "../motion.gif"
        with self.assertRaises(ValueError):
            grid.build_grid(self.root, [self.item])

    def test_empty_grid_rejected(self):
        with self.assertRaises(ValueError):
            grid.build_grid(self.root, [])


class CommittedCharacterGridTests(unittest.TestCase):
    def test_committed_assets_and_readme_match(self):
        import json
        root = Path(__file__).resolve().parents[1]
        folder = root / "examples/anime-pixel/character-previews"
        entries = json.loads((folder / "grid.json").read_text())
        markup, facts = grid.build_grid(root, entries, columns=3)
        self.assertEqual(facts, json.loads((folder / "verification.json").read_text()))
        self.assertIn(markup, (root / "README.md").read_text())
        self.assertEqual(len(entries), 9)
        for item in facts[:6]:
            self.assertEqual(item["frames"], 16)
            self.assertEqual(item["unique_decoded_frames"], 16)
            self.assertEqual(item["duration_ms"], 1920)
        for name in ("fox-knight", "dragon-chef"):
            self.assertEqual(len(list((folder / "frames" / name).glob("*.png"))), 16)
            self.assertTrue((folder / "sources" / (name + "-sheet.png")).is_file())
