"""Regular-file and byte-budget checks for film preflight. No provider calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from gif_cinema import cli, render
from test_reliability import animation


class LocalInputSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.gif"
        self.source.write_bytes(animation())
        self.script = self.root / "film.json"
        self.output = self.root / "project"
        self.reference = self.root / "hero.png"
        Image.new("RGB", (8, 8), "red").save(self.reference)
        self.data = {
            "schema_version": 1, "title": "Fixture", "ratio": "1:1",
            "style_bible": "A signal changes color", "shots": [{
                "id": "signal", "source": "source.gif",
                "first_frame_target": "red", "last_frame_target": "blue"}]}
        network = patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network forbidden"))
        network.start(); self.addCleanup(network.stop)
        provider = patch.object(cli, "request_gif", side_effect=AssertionError("Provider forbidden"))
        self.request = provider.start(); self.addCleanup(provider.stop)

    def args(self):
        self.script.write_text(json.dumps(self.data), encoding="utf-8")
        return cli.build_parser().parse_args([
            "render", str(self.script), "--dry-run", "--max-api-calls", "0",
            "--out", str(self.output)])

    def references(self, names=None):
        shot = self.data["shots"][0]
        del shot["source"]
        shot.update(prompt="A signal changes color", references=names or ["hero.png"])

    def test_regular_file_byte_limit_and_input_remain_unchanged(self):
        raw = self.source.read_bytes()
        self.assertEqual(cli.read_local_bytes(self.source, len(raw), "GIF"), raw)
        with self.assertRaisesRegex(ValueError, "input limit"):
            cli.read_local_bytes(self.source, len(raw) - 1, "GIF")
        self.assertEqual(self.source.read_bytes(), raw)

    def test_growth_after_fstat_is_still_bounded(self):
        real_fdopen = os.fdopen
        def grow_then_open(*args, **kwargs):
            self.source.write_bytes(b"x" * 101)
            return real_fdopen(*args, **kwargs)
        self.source.write_bytes(b"small")
        with patch.object(cli.os, "fdopen", side_effect=grow_then_open):
            with self.assertRaisesRegex(ValueError, "100 byte input limit"):
                cli.read_local_bytes(self.source, 100, "GIF")

    def test_directory_is_rejected_before_open(self):
        with patch.object(cli.os, "open") as opened:
            with self.assertRaisesRegex(ValueError, "regular local file"):
                cli.read_local_bytes(self.root, 100, "GIF")
        opened.assert_not_called()

    def test_descriptor_closes_after_fstat_failure(self):
        descriptor = os.open(self.source, os.O_RDONLY)
        with patch.object(cli.os, "open", return_value=descriptor), \
                patch.object(cli.os, "fstat", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                cli.read_local_bytes(self.source, 1000, "GIF")
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_regular_file_symlink_remains_supported(self):
        link = self.root / "linked.gif"
        try:
            link.symlink_to(self.source)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable")
        self.assertEqual(cli.read_gif_bytes(link), self.source.read_bytes())

    def test_script_limit_is_applied_to_actual_bytes_before_json(self):
        args = self.args()
        with patch.object(render, "MAX_SCRIPT_BYTES", self.script.stat().st_size - 1), \
                patch.object(render.json, "loads") as parse:
            with self.assertRaisesRegex(ValueError, "Script.*input limit"):
                render.load_script(self.script, args)
        parse.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_reference_budget_counts_combined_actual_bytes(self):
        self.references(["hero.png", "hero.png"])
        args = self.args()
        size = self.reference.stat().st_size
        with patch.object(render, "MAX_REFERENCE_BYTES", 2 * size):
            script = render.load_script(self.script, args)
            self.assertEqual(len(render.request_payload(script["shots"][0])["images"]), 2)
        with patch.object(render, "MAX_REFERENCE_BYTES", 2 * size - 1):
            with self.assertRaisesRegex(ValueError, "Shot references.*input limit"):
                render.load_script(self.script, args)
        self.request.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_reference_reread_enforces_byte_budget_before_request(self):
        self.references()
        args = self.args()
        size = self.reference.stat().st_size
        with patch.object(render, "MAX_REFERENCE_BYTES", size):
            script = render.load_script(self.script, args)
            self.reference.write_bytes(self.reference.read_bytes() + b"x")
            with self.assertRaisesRegex(ValueError, "Shot references.*input limit"):
                render.request_payload(script["shots"][0])
        self.request.assert_not_called()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs required")
    def test_fifo_gif_script_and_reference_fail_promptly_without_output(self):
        fifo = self.root / "waiting.fifo"
        os.mkfifo(fifo)
        # The deadline belongs to this regression harness. The application must
        # reject these inputs itself, before opening a FIFO or writing output.
        self.args()
        commands = [
            ["inspect", str(fifo)],
            ["render", str(fifo), "--out", str(self.output)],
        ]
        if shutil.which("ffmpeg"):
            commands.append(["film", str(fifo), "-o", str(self.output / "film.mp4")])
        for command in commands:
            with self.subTest(command=command[0]):
                result = subprocess.run([sys.executable, "-m", "gif_cinema", *command],
                                        capture_output=True, timeout=3)
                self.assertEqual(result.returncode, 1, result.stderr.decode())
                self.assertIn(b"regular local file", result.stderr)
                self.assertFalse(self.output.exists())
        for mode in ("source", "references"):
            with self.subTest(mode=mode):
                if mode == "source":
                    self.data["shots"][0]["source"] = fifo.name
                else:
                    self.references([fifo.name])
                self.args()
                result = subprocess.run([sys.executable, "-m", "gif_cinema", "render",
                    str(self.script), "--dry-run", "--max-api-calls", "0", "--out", str(self.output)],
                    capture_output=True, timeout=3)
                self.assertEqual(result.returncode, 1, result.stderr.decode())
                self.assertIn(b"regular local file", result.stderr)
                self.assertFalse(self.output.exists())

    @unittest.skipUnless(hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"), "POSIX race check")
    def test_fifo_replacement_between_stat_and_open_cannot_block(self):
        script = f'''
import os
from unittest.mock import patch
from gif_cinema import cli
source = {str(self.source)!r}
real_open = os.open
def replace_and_open(path, flags):
    assert flags & os.O_NONBLOCK
    os.unlink(path)
    os.mkfifo(path)
    return real_open(path, flags)
with patch.object(cli.os, "open", side_effect=replace_and_open):
    try:
        cli.read_gif_bytes(source)
    except ValueError as error:
        assert "regular local file" in str(error)
    else:
        raise AssertionError("FIFO accepted")
'''
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs required")
    def test_reference_replaced_after_planning_fails_before_request(self):
        self.references()
        args = self.args()
        script = render.load_script(self.script, args)
        self.reference.unlink()
        os.mkfifo(self.reference)
        with self.assertRaisesRegex(ValueError, "regular local file"):
            render.request_payload(script["shots"][0])
        self.request.assert_not_called()

    def test_valid_dry_run_needs_no_tools_key_or_output(self):
        args = self.args()
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(cli.subprocess, "run", side_effect=AssertionError("No media process")), \
                contextlib.redirect_stdout(io.StringIO()):
            plan = render.run(args)
        self.assertEqual(plan["minimum_new_api_calls"], 0)
        self.assertEqual(plan["shots"][0]["expected_duration_ms"], 600)
        self.request.assert_not_called()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
