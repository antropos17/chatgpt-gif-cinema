"""Offline tests for the manual pilot; no provider call is permitted."""
from datetime import date
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import manual_motion as motion
from PIL import Image


class ManualMotionTests(unittest.TestCase):
    def setUp(self):
        self.network = patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / "pilot"
        self.payload = motion.request()
        self.bound = {"schema_version": 1, "status": "reviewed-provider-upper-bound", "currency": "USD",
                      "request_sha256": motion.request_hash(self.payload), "maximum_total_usd": "0.50",
                      "includes_all_charges": True, "basis": "provider-guaranteed-request-maximum",
                      "source_url": "https://developers.openai.com/example-test-fixture-not-a-real-quote",
                      "valid_until": "2026-11-30"}

    def gate(self, **changes):
        args = dict(payload=self.payload, bound=self.bound, approved_usd="1.00", confirm_billing=True,
                    prior_attempts_reviewed=True, run_attempt="1", today=date(2026, 11, 9))
        args.update(changes)
        return motion.authorize(**args)

    def test_profile_is_exact_single_native_request(self):
        self.assertEqual(self.payload["model"], "gpt-image-2.6-flare")
        self.assertEqual(self.payload["output_format"], "gif")
        self.assertEqual(self.payload["frame_count"], 16)
        self.assertEqual(self.payload["frame_duration_ms"], 200)
        self.assertEqual(self.payload["size"], "512x512")
        self.assertEqual(self.payload["quality"], "max")

    def test_bundled_unknown_bound_blocks_even_positive_authorization(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            self.gate(bound=json.loads(motion.COST_BOUND.read_text()))

    def test_gate_accepts_well_formed_test_fixture_not_a_real_quote(self):
        self.assertEqual(self.gate()["reviewed_request_maximum_usd"], "0.50")

    def test_invalid_money_never_passes(self):
        for value in (None, 1, "", "0", "-1", "NaN", "Infinity", "1e4", " 1", "1.0000001"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.gate(approved_usd=value)

    def test_missing_authorization_reruns_and_over_budget_fail(self):
        for changes in ({"confirm_billing": False}, {"prior_attempts_reviewed": False},
                        {"run_attempt": "2"}, {"run_attempt": ""}, {"approved_usd": "0.49"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.gate(**changes)

    def test_bound_identity_evidence_and_expiry_fail_closed(self):
        for change in ({"request_sha256": "0" * 64}, {"currency": "EUR"}, {"includes_all_charges": False},
                       {"basis": "estimate"}, {"source_url": "https://example.com/quote"},
                       {"source_url": "https://developers.openai.com/quote?key=secret"},
                       {"source_url": "https://secret@developers.openai.com/quote"},
                       {"valid_until": "2026-11-08"}, {"valid_until": None}, {"maximum_total_usd": "NaN"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.gate(bound={**self.bound, **change})

    def test_prompt_change_invalidates_bound(self):
        payload = {**self.payload, "prompt": self.payload["prompt"] + " Changed."}
        with self.assertRaisesRegex(ValueError, "exact effective"):
            self.gate(payload=payload)

    def test_prepare_is_offline_unrendered_no_overwrite(self):
        with patch.object(motion, "OUT", self.out), patch("sys.stdout", new_callable=io.StringIO), \
                patch("gif_cinema.cli.request_gif") as paid:
            motion.prepare()
            self.assertEqual(json.loads((self.out / "request.json").read_text())["paid_calls"], 0)
            self.assertFalse(list(self.out.glob("*.gif")))
            with self.assertRaisesRegex(ValueError, "already exists"):
                motion.prepare()
            paid.assert_not_called()

    def test_unknown_gate_never_enters_paid_renderer(self):
        with patch.object(motion, "OUT", self.out), patch("sys.stdout", new_callable=io.StringIO), \
                patch.dict(os.environ, {"APPROVED_USD": "5", "CONFIRM_BILLING": "true",
                                       "PRIOR_ATTEMPTS_REVIEWED": "true", "GITHUB_RUN_ATTEMPT": "1"}), \
                patch("gif_cinema.render.run") as run:
            motion.prepare()
            with self.assertRaisesRegex(ValueError, "unknown"):
                motion.execute()
            run.assert_not_called()
            self.assertFalse((self.out / "authorization.json").exists())

    def test_authorized_fixture_enters_renderer_with_one_call_and_zero_retries(self):
        bound_path = Path(self.temp.name) / "cost.json"
        self.bound["valid_until"] = "9999-12-31"
        bound_path.write_text(json.dumps(self.bound))
        with patch.object(motion, "OUT", self.out), patch.object(motion, "COST_BOUND", bound_path), \
                patch("sys.stdout", new_callable=io.StringIO), \
                patch.dict(os.environ, {"APPROVED_USD": "1", "CONFIRM_BILLING": "true",
                                       "PRIOR_ATTEMPTS_REVIEWED": "true", "GITHUB_RUN_ATTEMPT": "1"}), \
                patch("gif_cinema.render.run") as run:
            motion.prepare()
            motion.execute()
            args = run.call_args.args[0]
            self.assertTrue(args.execute)
            self.assertEqual(args.max_api_calls, 1)
            self.assertEqual(args.retries, 0)
            self.assertEqual(args.force_shot, [])

    def test_review_preserves_original_and_marks_visual_acceptance_pending(self):
        source = self.out / "render"
        source.mkdir(parents=True)
        gif = source / "fixture.gif"
        frames = [Image.new("RGB", (512, 512), (i * 15, 20, 80)) for i in range(16)]
        frames[0].save(gif, save_all=True, append_images=frames[1:], duration=200, loop=0)
        raw = gif.read_bytes()
        sha = motion.hashlib.sha256(raw).hexdigest()
        (source / "render-manifest.json").write_text(json.dumps({"shots": {"chrome-trefoil": {"output": "fixture.gif", "sha256": sha}}}))
        with patch.object(motion, "OUT", self.out), patch("sys.stdout", new_callable=io.StringIO):
            motion.review_if_available()
        result = json.loads((self.out / "review/review.json").read_text())
        self.assertEqual(result["technical_status"], "requested-format-matched")
        self.assertEqual(result["visual_status"], "human-review-required")
        self.assertEqual(result["user_acceptance"], "pending")
        self.assertEqual(len(list((self.out / "review").glob("frame-*.png"))), 16)
        self.assertEqual(raw, gif.read_bytes())

    def test_workflow_has_no_automatic_paid_trigger(self):
        workflow = (motion.ROOT / ".github/workflows/manual-motion-pilot.yml").read_text()
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertNotIn("  push:", workflow)
        self.assertNotIn("  schedule:", workflow)
        self.assertNotIn("  pull_request:", workflow)
        self.assertIn("default: false", workflow)
        self.assertEqual(workflow.count("secrets.OPENAI_API_KEY"), 1)
        self.assertIn("python -m tools.manual_motion execute", workflow)
        self.assertIn("always() && inputs.execute && steps.generate.outcome != 'skipped'", workflow)
        self.assertIn("python -m tools.manual_motion review-if-available", workflow)

    def test_review_without_returned_media_never_claims_success(self):
        with patch.object(motion, "OUT", self.out), patch("sys.stdout", new_callable=io.StringIO) as output:
            motion.review_if_available()
            self.assertIn("no GIF is available", output.getvalue())
            self.assertFalse((self.out / "review").exists())


if __name__ == "__main__":
    unittest.main()
