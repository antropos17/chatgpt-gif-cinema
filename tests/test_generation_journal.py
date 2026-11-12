import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from gif_cinema import cli, generation_journal as journal


class GenerationJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / 'shot.gif'
        b = io.BytesIO()
        Image.new('RGB', (16, 16), 'red').save(b, format='GIF', save_all=True,
            append_images=[Image.new('RGB', (16, 16), 'blue')], duration=120)
        self.raw = b.getvalue()

    def run_generate(self, *flags):
        args = cli.build_parser().parse_args(['generate', 'private prompt', '-o', str(self.out), *flags])
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'secret-key'}), contextlib.redirect_stdout(io.StringIO()):
            return cli.generate(args)

    def test_timeout_blocks_repeat_even_with_resume_or_different_parameters(self):
        with patch.object(cli, 'request_gif', side_effect=TimeoutError('secret-key')) as request:
            with self.assertRaises(TimeoutError):
                self.run_generate()
            for flags in ((), ('--resume',), ('--dry-run',), ('--frames', '8')):
                with self.assertRaisesRegex(ValueError, 'Review provider history'):
                    self.run_generate(*flags)
            self.assertEqual(request.call_count, 1)
        saved = journal.journal_path(self.out).read_text()
        self.assertNotIn('secret-key', saved)
        self.assertNotIn('private prompt', saved)
        self.assertEqual(json.loads(saved)['attempts'][-1]['status'], 'unknown')

    def test_started_receipt_precedes_request_and_interruption_blocks_retry(self):
        def interrupted(*args):
            self.assertEqual(journal.load(self.out)['attempts'][-1]['status'], 'started')
            raise KeyboardInterrupt()
        with patch.object(cli, 'request_gif', side_effect=interrupted) as request:
            with self.assertRaises(KeyboardInterrupt):
                self.run_generate()
            with self.assertRaises(ValueError):
                self.run_generate()
            self.assertEqual(request.call_count, 1)

    def test_failure_to_record_never_sends(self):
        with patch.object(journal, 'durable_write', side_effect=OSError('disk full')), patch.object(cli, 'request_gif') as request:
            with self.assertRaises(OSError):
                self.run_generate()
            request.assert_not_called()

    def test_force_explicitly_authorizes_new_attempt_and_resume_reuses(self):
        with patch.object(cli, 'request_gif', side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):
                self.run_generate()
        with patch.object(cli, 'request_gif', return_value=(self.raw, None)) as request:
            self.run_generate('--force')
            self.run_generate('--resume')
            self.assertEqual(request.call_count, 1)
        self.assertEqual([a['status'] for a in journal.load(self.out)['attempts']], ['unknown', 'succeeded'])

    def test_partial_publication_and_malformed_response_block_new_payment(self):
        for malformed in (False, True):
            with self.subTest(malformed=malformed):
                self.out = self.out.with_name(f'{malformed}.gif')
                with patch.object(cli, 'request_gif', return_value=(b'bad' if malformed else self.raw, None)), \
                        patch.object(cli, 'write_result', side_effect=OSError('full')):
                    with self.assertRaises((ValueError, OSError)):
                        self.run_generate()
                with patch.object(cli, 'request_gif') as request:
                    with self.assertRaises(ValueError):
                        self.run_generate()
                    request.assert_not_called()

    def test_unknown_update_failure_leaves_started_guard(self):
        real_save = journal.save
        def save_once(output, data):
            if data['attempts'][-1]['status'] != 'started':
                raise OSError('disk full')
            return real_save(output, data)
        with patch.object(journal, 'save', side_effect=save_once), patch.object(cli, 'request_gif', side_effect=TimeoutError()) as request:
            with self.assertRaises(OSError):
                self.run_generate()
            with self.assertRaises(ValueError):
                self.run_generate()
            self.assertEqual(request.call_count, 1)
        self.assertEqual(journal.load(self.out)['attempts'][-1]['status'], 'started')

    def test_deleted_successful_outputs_still_require_new_payment_authorization(self):
        with patch.object(cli, 'request_gif', return_value=(self.raw, None)) as request:
            self.run_generate()
            self.out.unlink()
            self.out.with_suffix('.json').unlink()
            with self.assertRaises(ValueError):
                self.run_generate('--resume')
            self.assertEqual(request.call_count, 1)

    def test_corrupt_journal_fails_closed_even_force(self):
        journal.journal_path(self.out).write_text('{bad')
        with patch.object(cli, 'request_gif') as request:
            with self.assertRaisesRegex(ValueError, 'journal'):
                self.run_generate('--force')
            request.assert_not_called()

    def test_missing_key_does_not_record_attempt(self):
        args = cli.build_parser().parse_args(['generate', 'wave', '-o', str(self.out)])
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                cli.generate(args)
        self.assertFalse(journal.journal_path(self.out).exists())

    def test_dry_run_with_force_does_not_modify_uncertain_record(self):
        journal.start(self.out, {'prompt': 'private prompt'})
        before = journal.journal_path(self.out).read_bytes()
        self.assertEqual(self.run_generate('--force', '--dry-run')['would_send_api_calls'], 1)
        self.assertEqual(before, journal.journal_path(self.out).read_bytes())

if __name__ == '__main__':
    unittest.main()
