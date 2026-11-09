import io
import json
import unittest
from unittest.mock import patch

from gif_cinema import doctor
from gif_cinema.cli import build_parser

READY_CAPS = {"h264_encoder": True, "core_filters": True, "motion_interpolation": True,
              "aac_encoder": True, "audio_padding": True}


def tool(available):
    return (lambda name: {"available": True, "version": f"{name} version test"}) if available \
        else (lambda name: {"available": False, "reason": f"{name} is not on PATH"})


class DoctorTests(unittest.TestCase):
    def run_doctor(self, env, available=True, caps=READY_CAPS):
        args = build_parser().parse_args(["doctor"])
        with patch.dict("os.environ", env, clear=True), \
                patch.object(doctor, "inspect_tool", side_effect=tool(available)), \
                patch.object(doctor, "inspect_ffmpeg_capabilities", return_value=caps), \
                patch("sys.stdout", new_callable=io.StringIO) as out:
            try:
                args.func(args)
                error = None
            except RuntimeError as exc:
                error = exc
        return json.loads(out.getvalue()), error

    def test_ready_without_key_and_secret_not_printed(self):
        report, error = self.run_doctor({})
        self.assertIsNone(error)
        self.assertTrue(report["ready"]["offline_film"])
        self.assertFalse(report["ready"]["generation"])
        self.assertFalse(report["openai_api_key_set"])
        report, _ = self.run_doctor({"OPENAI_API_KEY": "sk-secret-value"})
        self.assertTrue(report["ready"]["generation"])
        self.assertNotIn("sk-secret-value", json.dumps(report))

    def test_missing_ffmpeg_fails(self):
        report, error = self.run_doctor({}, available=False)
        self.assertFalse(report["ready"]["offline_film"])
        self.assertIsInstance(error, RuntimeError)

    def test_missing_h264_fails(self):
        report, error = self.run_doctor({}, caps={**READY_CAPS, "h264_encoder": False})
        self.assertFalse(report["ready"]["offline_film"])
        self.assertIsInstance(error, RuntimeError)

    def test_invalid_model_is_reported(self):
        report, error = self.run_doctor({"GIF_CINEMA_MODEL": "bad", "OPENAI_API_KEY": "k"})
        self.assertIsNone(error)
        self.assertFalse(report["default_model"]["ok"])
        self.assertFalse(report["ready"]["generation"])


if __name__ == "__main__":
    unittest.main()
