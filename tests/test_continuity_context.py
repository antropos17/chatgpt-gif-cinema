"""Cut diagnostics use actual decoded timing and never approve visual continuity."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import cli, render
from gif_cinema.continuity import cut_context, cut_sheet, pixel_mae


def drawings(values):
    return [Image.new("RGB", (24, 24), (value, value, value)) for value in values]


def gif(path, values, delays):
    frames = drawings(values)
    frames[0].save(path, format="GIF", save_all=True, append_images=frames[1:],
                   duration=delays, loop=0)


class CutContextTests(unittest.TestCase):
    def test_hidden_rgb_does_not_create_a_false_cut(self):
        a = Image.new("RGBA", (24, 24), (255, 0, 0, 0))
        b = Image.new("RGBA", (24, 24), (0, 255, 255, 0))
        before = (a.tobytes(), b.tobytes())
        self.assertEqual(pixel_mae(a, b), 0)
        self.assertEqual(before, (a.tobytes(), b.tobytes()))

    def test_alpha_only_changes_are_visible_on_either_matte(self):
        for color in ((0, 0, 0), (255, 255, 255)):
            opaque = Image.new("RGBA", (24, 24), (*color, 255))
            hidden = Image.new("RGBA", (24, 24), (*color, 0))
            half = Image.new("RGBA", (24, 24), (*color, 128))
            self.assertEqual(pixel_mae(opaque, hidden), 255)
            self.assertEqual(pixel_mae(opaque, half), 127)
            self.assertEqual(pixel_mae(hidden, opaque), 255)

    def test_palette_transparency_and_strip_do_not_show_hidden_color(self):
        frame = Image.new("P", (24, 24), 0)
        frame.putpalette([255, 0, 0] + [0, 0, 0] * 255)
        frame.info["transparency"] = 0
        clear = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        self.assertEqual(pixel_mae(frame, clear), 0)
        report = cut_context([frame], [100], [clear], [100])
        self.assertEqual(report["pixel_metric"], "max-black-white-composite-rgb-thumbnail-mae-v1")
        self.assertEqual(cut_sheet([frame], [clear], report).getpixel((8, 24)), (24, 24, 24))

    def test_variable_delays_and_original_indexes_survive_bounded_context(self):
        frames = drawings([0, 10, 20, 30, 40])
        result = cut_context(frames, [20, 40, 80, 160, 320], frames[:2], [60, 100])
        left = result["previous"]["frames"]
        self.assertEqual([row["frame"] for row in left], [2, 3, 4])
        self.assertEqual([row["start_ms_from_cut"] for row in left], [-560, -480, -320])
        self.assertEqual([row["end_ms_from_cut"] for row in left], [-480, -320, 0])
        self.assertEqual([row["start_ms_from_cut"] for row in result["next"]["frames"]], [0, 60])
        self.assertEqual(result["previous"]["adjacent_changes"][0]["pixel_mae_per_second"], 125)

    def test_jump_is_reported_relative_to_local_changes(self):
        result = cut_context(drawings([0, 10, 20]), [100] * 3,
                             drawings([120, 130, 140]), [100] * 3)
        self.assertEqual(result["cut_pixel_mae_0_255"], 100)
        self.assertEqual(result["local_change_median_0_255"], 10)
        self.assertEqual(result["cut_to_local_change_ratio"], 10)
        self.assertEqual(result["status"], "human-review-required")

    def test_identical_endpoints_do_not_approve_opposite_movement(self):
        result = cut_context(drawings([0, 20, 40]), [100] * 3,
                             drawings([40, 20, 0]), [100] * 3)
        self.assertEqual(result["cut_pixel_mae_0_255"], 0)
        self.assertEqual(result["status"], "human-review-required")
        self.assertIn("gaze and screen direction", result["review_checks"])

    def test_zero_baseline_is_null_and_never_infinite_or_a_pass(self):
        result = cut_context(drawings([0, 0]), [20, 2000],
                             drawings([255, 255]), [500, 20])
        self.assertIsNone(result["cut_to_local_change_ratio"])
        self.assertEqual(result["status"], "human-review-required")
        json.dumps(result, allow_nan=False)

    def test_tail_offset_keeps_true_frame_numbers_and_strip_drawings(self):
        previous, following = drawings([10, 20, 30]), drawings([40, 50])
        result = cut_context(previous, [100, 200, 300], following, [40, 60], 1497)
        self.assertEqual([row["frame"] for row in result["previous"]["frames"]], [1497, 1498, 1499])
        sheet = cut_sheet(previous, following, result)
        self.assertEqual(sheet.size, (1040, 232))
        self.assertEqual([sheet.getpixel((8 + 208 * i, 24))[0] for i in range(5)], [10, 20, 30, 40, 50])

    def test_invalid_timing_is_rejected(self):
        for delays in ([20], [20, 0], [20, True]):
            with self.subTest(delays=delays), self.assertRaises(ValueError):
                cut_context(drawings([0, 10]), delays, drawings([20, 30]), [20, 20])

    def test_cli_uses_real_delays_and_keeps_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = root / "a.gif", root / "b.gif"
            gif(a, [0, 10, 20, 30], [20, 40, 100, 500])
            gif(b, [100, 110], [200, 300])
            output = root / "report.json"
            args = cli.build_parser().parse_args(["continuity", str(a), str(b), "-o", str(output)])
            before = (a.read_bytes(), b.read_bytes())
            with patch("gif_cinema.cli.request_gif", side_effect=AssertionError("No API")), contextlib.redirect_stdout(io.StringIO()):
                cli.continuity(args)
                report = json.loads(output.read_text())
                self.assertEqual(report["cut_context"]["previous"]["frames"][-1]["duration_ms"], 500)
                self.assertEqual(report["cut_context"]["next"]["frames"][0]["duration_ms"], 200)
                with self.assertRaises((ValueError, FileExistsError)):
                    cli.continuity(args)
            self.assertEqual(before, (a.read_bytes(), b.read_bytes()))

    def test_render_emits_join_strips_and_context_without_changing_footage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shots, records = [], []
            for index, values in enumerate(([0, 10, 20, 30, 40], [120, 130], [20, 30])):
                name = f"shot-{index}"
                path = root / (name + ".gif")
                gif(path, values, [100] * (len(values) - 1) + [500])
                shots.append({"id": name, "first_frame_target": "instruction only", "last_frame_target": "instruction only"})
                records.append({"output": path.name})
            before = [hashlib.sha256((root / row["output"]).read_bytes()).hexdigest() for row in records]
            with patch("gif_cinema.cli.request_gif", side_effect=AssertionError("No API")):
                render.diagnostics(root, {"shots": shots}, records)
            report = json.loads((root / "continuity-report.json").read_text())
            self.assertEqual(report["status"], "human-review-required")
            self.assertEqual(len(report["joins"]), 2)
            for join in report["joins"]:
                self.assertTrue((root / join["context_sheet"]).is_file())
                self.assertEqual(join["cut_context"]["previous"]["frames"][-1]["end_ms_from_cut"], 0)
                self.assertEqual(join["cut_context"]["previous"]["frames"][-1]["duration_ms"], 500)
            self.assertEqual(report["joins"][0]["cut_context"]["previous"]["frames"][0]["frame"], 2)
            self.assertEqual(before, [hashlib.sha256((root / row["output"]).read_bytes()).hexdigest() for row in records])

    def test_single_shot_still_has_no_joins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gif(root / "source.gif", [0, 10], [100, 200])
            render.diagnostics(root, {"shots": [{"id": "one"}]}, [{"output": "source.gif"}])
            self.assertEqual(json.loads((root / "continuity-report.json").read_text())["joins"], [])
            self.assertEqual(list(root.glob("join-*.png")), [])
