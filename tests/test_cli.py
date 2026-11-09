import unittest
import io
import json
import base64
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from PIL import Image
from gif_cinema.cli import request_gif, generate
from gif_cinema.cli import make_payload, build_parser, default_model

class APIPayloadTests(unittest.TestCase):
    def test_gif_payload(self):
        p=make_payload("A waving astronaut")
        self.assertEqual(p["output_format"],"gif")
        self.assertEqual(p["frame_count"],9)

    def test_frames_range(self):
        with self.assertRaises(ValueError):
            make_payload("x",frames=1)
        with self.assertRaises(ValueError):
            make_payload("x",frames=65)

    def test_model(self):
        with self.assertRaises(ValueError):
            make_payload("x",model="invalid")

    def test_size(self):
        with self.assertRaises(ValueError):
            make_payload("x",size="123x70")

    def test_cli(self):
        args=build_parser().parse_args(["generate","A moving leaf","-o","output/a.gif"])
        self.assertEqual(args.output,"output/a.gif")

    def test_default_model_reads_environment(self):
        with patch.dict("os.environ", {"GIF_CINEMA_MODEL": "gpt-image-2.6-sunburst"}):
            self.assertEqual(default_model(), "gpt-image-2.6-sunburst")
        with patch.dict("os.environ", {"GIF_CINEMA_MODEL": ""}):
            self.assertEqual(default_model(), "gpt-image-2.6-flare")
        with patch.dict("os.environ", {"GIF_CINEMA_MODEL": "unknown-model"}):
            with self.assertRaisesRegex(ValueError, "GIF_CINEMA_MODEL"):
                default_model()

    def test_dry_run_sends_nothing_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new" / "a.gif"
            args = build_parser().parse_args(["generate", "x", "-o", str(output),
                                              "--model", "gpt-image-2.6-flare", "--dry-run"])
            with patch.dict("os.environ", {"GIF_CINEMA_MODEL": "gpt-image-2.6-sunburst"}, clear=True), \
                    patch("gif_cinema.cli.request_gif") as request, \
                    patch("sys.stdout", new_callable=io.StringIO) as out:
                generate(args)
            request.assert_not_called()
            plan = json.loads(out.getvalue())
            self.assertEqual(plan["api_calls"], 0)
            self.assertEqual(plan["payload"]["model"], "gpt-image-2.6-flare")  # --model beats env
            self.assertFalse(output.parent.exists())



class LiveSafetyTests(unittest.TestCase):
    def response(self, raw):
        return io.BytesIO(json.dumps({"data": [{"b64_json": base64.b64encode(raw).decode()}]}).encode())

    def test_real_animation_decode(self):
        data = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(data, format="GIF", save_all=True,
            append_images=[Image.new("RGB", (8, 8), "blue")], duration=200, loop=0)
        raw, _ = request_gif({}, "fake-key", transport=lambda *a, **kw: self.response(data.getvalue()))
        self.assertEqual(raw, data.getvalue())

    def test_static_gif_is_rejected(self):
        data = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(data, format="GIF", duration=200)
        with self.assertRaisesRegex(ValueError, "at least two frames"):
            request_gif({}, "fake-key", transport=lambda *a, **kw: self.response(data.getvalue()))

    def test_error_body_is_not_exposed(self):
        def fail(*a, **kw):
            raise HTTPError("https://example.invalid", 401, "error", {}, io.BytesIO(b"private-value"))
        with self.assertRaises(RuntimeError) as result:
            request_gif({}, "fake-key", transport=fail)
        self.assertNotIn("private-value", str(result.exception))
        self.assertIn("401", str(result.exception))

    def test_existing_output_prevents_paid_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "existing.gif"
            output.write_bytes(b"keep")
            args = build_parser().parse_args(["generate", "test", "-o", str(output)])
            with patch.dict("os.environ", {"OPENAI_API_KEY": "fake-key"}), patch("gif_cinema.cli.request_gif") as request:
                with self.assertRaisesRegex(ValueError, "already exists"):
                    generate(args)
                request.assert_not_called()
            self.assertEqual(output.read_bytes(), b"keep")

if __name__ == "__main__":
    unittest.main()
