"""Only synthetic files: preserve edited SRT and flag changed shot timing."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gif_cinema import captions, cli, render
from test_reliability import animation


class CaptionPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'captions.srt'
        self.script = {'fps': 25, 'shots': [{'id': 'red', 'caption': 'First cue'},
                                          {'id': 'blue', 'caption': 'Second cue'}]}
        self.records = [{'duration_ms': 600}, {'duration_ms': 600}]
        self.initial = captions.publish(self.root, self.script, self.records)
        self.original = self.path.read_bytes()
        self.custom = b'\xef\xbb\xbf1\r\n00:00:00,000 --> 00:00:01,000\r\nMy edited subtitle.\r\n'

    def publish(self, previous=None):
        return captions.publish(self.root, self.script, self.records,
                                self.initial if previous is None else previous)

    def test_initial_and_unchanged_generated_srt_keep_timing_and_do_not_rewrite(self):
        self.assertEqual(self.initial['status'], 'created')
        self.assertIn(b'00:00:00,600 --> 00:00:01,200', self.original)
        before = self.path.stat().st_mtime_ns
        with patch.object(cli, 'write_result', side_effect=AssertionError('Do not rewrite')):
            state = self.publish()
        self.assertEqual(state['status'], 'unchanged')
        self.assertFalse(state['timing_review_required'])
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_unedited_generated_captions_update_and_retain_previous_file(self):
        self.script['shots'][0]['caption'] = 'Updated from script'
        state = self.publish()
        self.assertEqual(state['status'], 'updated')
        self.assertIn(b'Updated from script', self.path.read_bytes())
        self.assertEqual((self.root / state['preserved_copy']).read_bytes(), self.original)
        self.assertFalse(state['timing_review_required'])

    def test_unedited_generated_captions_follow_new_timing(self):
        self.records[0]['duration_ms'] = 1000
        state = self.publish()
        self.assertEqual(state['status'], 'updated')
        self.assertIn(b'00:00:01,000 --> 00:00:01,600', self.path.read_bytes())
        self.assertFalse(state['timing_review_required'])

    def test_edited_bom_crlf_bytes_survive_repeated_resume_without_warning(self):
        self.path.write_bytes(self.custom)
        before = self.path.stat().st_mtime_ns
        state = self.publish()
        self.assertEqual(state['status'], 'preserved-edits')
        self.assertFalse(state['timing_review_required'])
        self.assertNotIn('warning', state)
        self.assertEqual(self.path.read_bytes(), self.custom)
        self.assertEqual((self.root / state['proposed_output']).read_bytes(), self.original)
        files = sorted(p.name for p in self.root.iterdir())
        state = self.publish(state)
        self.assertEqual(self.path.read_bytes(), self.custom)
        self.assertEqual(self.path.stat().st_mtime_ns, before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), files)
        self.assertNotEqual(state['sha256'], state['generated_sha256'])

    def test_timing_warning_persists_across_resume_until_generated_copy_is_adopted(self):
        self.path.write_bytes(self.custom)
        self.records[0]['duration_ms'] = 1000
        state = self.publish()
        for _ in range(2):
            self.assertTrue(state['timing_review_required'])
            self.assertIn('timing changed', state['warning'])
            self.assertEqual(self.path.read_bytes(), self.custom)
            state = self.publish(state)
        self.path.write_bytes((self.root / state['proposed_output']).read_bytes())
        state = self.publish(state)
        self.assertFalse(state['timing_review_required'])
        self.assertNotIn('warning', state)

    def test_equal_duration_shot_reordering_requires_timing_review(self):
        self.path.write_bytes(self.custom)
        self.script['shots'].reverse()
        state = self.publish()
        self.assertTrue(state['timing_review_required'])
        self.assertEqual(self.path.read_bytes(), self.custom)

    def test_fps_change_that_changes_quantized_timing_requires_review(self):
        self.path.write_bytes(self.custom)
        self.script['fps'] = 24
        state = self.publish()
        self.assertTrue(state['timing_review_required'])
        self.assertEqual(self.path.read_bytes(), self.custom)

    def test_fps_change_with_identical_srt_timestamps_does_not_warn(self):
        self.path.write_bytes(self.custom)
        self.script['fps'] = 50
        state = self.publish()
        self.assertFalse(state['timing_review_required'])
        self.assertNotIn('warning', state)

    def test_script_text_change_preserves_user_text_and_offers_new_candidate(self):
        self.path.write_bytes(self.custom)
        self.script['shots'][0]['caption'] = 'Different author text'
        state = self.publish()
        self.assertFalse(state['timing_review_required'])
        self.assertEqual(self.path.read_bytes(), self.custom)
        self.assertIn(b'Different author text', (self.root / state['proposed_output']).read_bytes())

    def test_deliberately_empty_manual_srt_is_preserved(self):
        self.path.write_bytes(b'')
        state = self.publish()
        self.assertEqual(state['status'], 'preserved-edits')
        self.assertEqual(self.path.read_bytes(), b'')

    def test_missing_srt_is_regenerated_from_current_script(self):
        self.path.unlink()
        state = self.publish()
        self.assertEqual(state['status'], 'created')
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_empty_generated_srt_remains_empty(self):
        for shot in self.script['shots']:
            shot.pop('caption')
        state = self.publish()
        self.assertEqual(self.path.read_bytes(), b'')
        self.assertEqual(state['status'], 'updated')
        self.assertEqual(self.publish(state)['status'], 'unchanged')

    def test_legacy_matching_srt_is_adopted_without_rewrite(self):
        with patch.object(cli, 'write_result', side_effect=AssertionError('No rewrite')):
            state = captions.publish(self.root, self.script, self.records)
        self.assertEqual(state['status'], 'unchanged')
        self.assertEqual(state['generated_sha256'], hashlib.sha256(self.original).hexdigest())

    def test_legacy_or_invalid_metadata_preserves_different_srt_and_warns(self):
        self.path.write_bytes(self.custom)
        for previous in (None, {}, [], 'invalid'):
            with self.subTest(previous=previous):
                state = captions.publish(self.root, self.script, self.records, previous)
                self.assertEqual(self.path.read_bytes(), self.custom)
                self.assertTrue(state['timing_review_required'])
                self.assertIn('no verified timing history', state['warning'])

    def test_edited_previous_candidate_is_not_overwritten(self):
        self.path.write_bytes(self.custom)
        first = self.publish()
        old_candidate = self.root / first['proposed_output']
        old_candidate.write_bytes(b'Manual edits in candidate too')
        second = self.publish(first)
        self.assertNotEqual(first['proposed_output'], second['proposed_output'])
        self.assertEqual(old_candidate.read_bytes(), b'Manual edits in candidate too')
        self.assertEqual((self.root / second['proposed_output']).read_bytes(), self.original)

    def test_nonregular_and_oversized_primary_are_preserved_without_reading(self):
        self.path.unlink()
        self.path.mkdir()
        state = self.publish()
        self.assertTrue(self.path.is_dir())
        self.assertEqual(state['status'], 'preserved-unreadable')
        self.path.rmdir()
        with self.path.open('wb') as stream:
            stream.truncate(captions.MAX_CAPTION_BYTES + 1)
        with patch.object(captions.os, 'fdopen', side_effect=AssertionError('Do not read oversized file')):
            self.assertIsNone(captions.read_existing(self.path))
        state = self.publish()
        self.assertEqual(self.path.stat().st_size, captions.MAX_CAPTION_BYTES + 1)
        self.assertTrue(state['timing_review_required'])

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO test')
    def test_fifo_primary_does_not_block_or_get_replaced(self):
        self.path.unlink()
        os.mkfifo(self.path)
        state = self.publish()
        self.assertEqual(state['status'], 'preserved-unreadable')
        self.assertTrue(state['timing_review_required'])

    def test_symlink_primary_does_not_read_or_change_target(self):
        target = self.root / 'my-subtitles.srt'
        target.write_bytes(self.custom)
        self.path.unlink()
        try:
            self.path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation unavailable')
        state = self.publish()
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_bytes(), self.custom)
        self.assertEqual(state['status'], 'preserved-unreadable')

    @unittest.skipUnless(hasattr(os, 'O_NOFOLLOW'), 'No-follow open requires POSIX')
    def test_symlink_replacement_between_stat_and_open_is_not_read(self):
        target = self.root / 'other.srt'
        target.write_bytes(self.custom)
        real_open = os.open
        def replace_then_open(path, flags):
            self.path.unlink()
            self.path.symlink_to(target)
            return real_open(path, flags)
        with patch.object(captions.os, 'open', side_effect=replace_then_open), \
                patch.object(captions.os, 'fdopen', side_effect=AssertionError('Do not read symlink')):
            self.assertIsNone(captions.read_existing(self.path))
        self.assertEqual(target.read_bytes(), self.custom)

    def test_edit_racing_managed_refresh_is_restored_and_saved(self):
        self.script['shots'][0]['caption'] = 'Updated author text'
        real_replace = os.replace
        def edit_then_move(source, target):
            if Path(source) == self.path:
                self.path.write_bytes(self.custom)
            return real_replace(source, target)
        with patch.object(captions.os, 'replace', side_effect=edit_then_move):
            state = self.publish()
        self.assertEqual(self.path.read_bytes(), self.custom)
        self.assertEqual((self.root / state['preserved_copy']).read_bytes(), self.custom)
        self.assertEqual(state['status'], 'preserved-edits')

    def test_editor_save_during_publication_is_never_clobbered(self):
        self.script['shots'][0]['caption'] = 'Updated author text'
        real_write = cli.write_result
        def editor_wins(path, raw, force=False):
            if path == self.path:
                self.path.write_bytes(self.custom)
            return real_write(path, raw, force)
        with patch.object(cli, 'write_result', side_effect=editor_wins):
            state = self.publish()
        self.assertEqual(self.path.read_bytes(), self.custom)
        self.assertEqual((self.root / state['preserved_copy']).read_bytes(), self.original)
        self.assertEqual(state['status'], 'preserved-edits')

    @unittest.skipUnless(os.name == 'posix', 'Requires POSIX replacement of an open file')
    def test_open_editor_descriptor_keeps_late_edits_in_preserved_copy(self):
        self.script['shots'][0]['caption'] = 'Updated author text'
        real_write = cli.write_result
        with self.path.open('r+b') as editor:
            def late_edit(path, raw, force=False):
                if path == self.path:
                    editor.seek(0)
                    editor.write(self.custom)
                    editor.truncate()
                    editor.flush()
                return real_write(path, raw, force)
            with patch.object(cli, 'write_result', side_effect=late_edit):
                state = self.publish()
        self.assertEqual(state['status'], 'updated')
        self.assertIn(b'Updated author text', self.path.read_bytes())
        self.assertEqual((self.root / state['preserved_copy']).read_bytes(), self.custom)

    def test_interrupt_after_successful_move_keeps_and_restores_latest_user_edit(self):
        self.script['shots'][0]['caption'] = 'Updated author text'
        real_replace = os.replace
        def move_then_interrupt(source, target):
            self.path.write_bytes(self.custom)
            real_replace(source, target)
            raise KeyboardInterrupt('Synthetic interruption after completed rename')
        with patch.object(captions.os, 'replace', side_effect=move_then_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.publish()
        self.assertEqual(self.path.read_bytes(), self.custom)
        backups = list(self.root.glob('captions-preserved-*.srt'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.custom)

    def test_failed_move_does_not_delete_primary_or_assume_placeholder_is_disposable(self):
        self.script['shots'][0]['caption'] = 'New text'
        with patch.object(captions.os, 'replace', side_effect=OSError('Synthetic move failure')):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(self.path.read_bytes(), self.original)
        # Conservatively retain even a placeholder when the syscall outcome is
        # uncertain; a small leftover file is preferable to losing subtitle edits.
        self.assertEqual(len(list(self.root.glob('captions-preserved-*.srt'))), 1)

    def test_failed_managed_refresh_restores_old_srt(self):
        self.script['shots'][0]['caption'] = 'New text'
        with patch.object(cli, 'write_result', side_effect=OSError('Synthetic disk failure')):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(self.path.read_bytes(), self.original)
        backups = list(self.root.glob('captions-preserved-*.srt'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
class RealCaptionResumeTests(unittest.TestCase):
    def test_render_updates_plain_srt_preserves_edits_and_warns_on_new_timing(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cli, 'request_gif', side_effect=AssertionError('No provider')), \
                patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No network')), \
                contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            source = root / 'source.gif'; source.write_bytes(animation((300, 300)))
            script = root / 'film.json'; out = root / 'render'
            data = {'schema_version': 1, 'title': 'SRT fixture', 'style_bible': 'Synthetic colors',
                    'ratio': '1:1', 'width': 32, 'height': 32, 'fps': 25, 'shots': [{
                    'id': 'signal', 'source': source.name, 'first_frame_target': 'red',
                    'last_frame_target': 'blue', 'caption': 'Original caption'}]}
            script.write_text(json.dumps(data))
            args = cli.build_parser().parse_args(['render', str(script), '--execute', '--max-api-calls', '0', '--out', str(out)])
            first = render.run(args)
            self.assertEqual(first['captions']['status'], 'created')
            movie = (out / 'film.mp4').read_bytes()
            data['shots'][0]['caption'] = 'Updated script caption'
            script.write_text(json.dumps(data))
            updated = render.run(args)
            self.assertEqual(updated['captions']['status'], 'updated')
            self.assertIn('Updated script caption', (out / 'captions.srt').read_text())
            custom = b'1\r\n00:00:00,000 --> 00:00:00,600\r\nHand-corrected subtitle.\r\n'
            (out / 'captions.srt').write_bytes(custom)
            resumed = render.run(args)
            self.assertEqual((resumed['api_calls'], resumed['skipped']), (0, 1))
            self.assertEqual((out / 'captions.srt').read_bytes(), custom)
            self.assertEqual((out / 'film.mp4').read_bytes(), movie)
            self.assertFalse(resumed['captions']['timing_review_required'])
            source.write_bytes(animation((500, 700)))
            warning = io.StringIO()
            with contextlib.redirect_stderr(warning):
                changed = render.run(args)
            self.assertEqual(changed['api_calls'], 0)
            self.assertTrue(changed['captions']['timing_review_required'])
            self.assertIn('timing changed', warning.getvalue())
            self.assertEqual((out / 'captions.srt').read_bytes(), custom)
            proposal = out / changed['captions']['proposed_output']
            self.assertIn('00:00:01,200', proposal.read_text())
            manifest = json.loads((out / 'render-manifest.json').read_text())
            self.assertEqual(manifest['captions'], changed['captions'])
            self.assertEqual(json.loads((out / 'receipt.json').read_text())['captions'], changed['captions'])
            self.assertEqual(list(out.glob('*.lock')), [])


if __name__ == '__main__':
    unittest.main()
