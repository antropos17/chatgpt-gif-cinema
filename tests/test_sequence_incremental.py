"""Behavioral regressions for immutable revisions, dependency propagation and recovery."""
import json
import shutil
import unittest
from unittest.mock import patch

from test_sequence import SequenceFixture
from gif_cinema import sequence as seq, layers
from gif_cinema import sequence_incremental as inc


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe required')
class IncrementalTests(SequenceFixture, unittest.TestCase):
    def baseline(self):
        out = self.root / 'v1'
        seq.build_sequence(self.path, out)
        return out

    def files(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_no_change_reuses_every_scene_and_preserves_original(self):
        old = self.baseline(); before = self.files(old)
        with patch.object(layers, 'render_scene', side_effect=AssertionError('Must reuse')):
            r = seq.build_sequence(self.path, self.root / 'v2', reuse_from=old)
        self.assertEqual(r['scene_exports'], {'rendered': 0, 'reused': 3, 'resumed': 0})
        self.assertEqual(r['incremental']['joins_for_review'], [])
        self.assertEqual(before, self.files(old))
        for sid in ('01-carry', '02-release', '03-result'):
            self.assertEqual(self.files(old / 'shots' / sid), self.files(self.root / 'v2/shots' / sid))

    def test_edit_middle_motion_without_endpoint_change_only_renders_middle(self):
        old = self.baseline()
        self.value['shots'][1]['tracks']['hand']['keyframes'][1]['rotation'] = 0
        self.value['shots'][1]['tracks']['hand']['keyframes'][-1]['rotation'] = 0
        self.value['shots'][1]['tracks']['hand']['keyframes'].insert(1, {'at': .25, 'rotation': 15})
        self.save()
        with patch.object(layers, 'render_scene', wraps=layers.render_scene) as render:
            r = seq.build_sequence(self.path, self.root / 'v2', reuse_from=old)
        self.assertEqual(render.call_count, 1)
        self.assertEqual([x['id'] for x in r['incremental']['scenes'] if x['review_required']], ['02-release'])
        self.assertEqual([(x['previous'], x['next']) for x in r['incremental']['joins_for_review']],
                         [('01-carry', '02-release'), ('02-release', '03-result')])

    def test_changed_carried_endpoint_rebuilds_dependent_scene(self):
        old = self.baseline()
        self.value['shots'][1]['tracks']['hand']['keyframes'][1]['x'] = .5
        self.save()
        r = seq.build_sequence(self.path, self.root / 'v2', reuse_from=old)
        self.assertEqual(r['scene_exports']['rendered'], 2)
        self.assertEqual(r['incremental']['scenes'][2]['reason'], 'carried-state-or-stage-change')

    def test_interrupt_after_completed_scene_resumes_and_does_not_touch_old(self):
        out = self.root / 'v1'; calls = []; real = layers.render_scene
        def interrupted(source, target):
            calls.append(str(target))
            if len(calls) == 2:
                raise KeyboardInterrupt()
            return real(source, target)
        with patch.object(layers, 'render_scene', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                seq.build_sequence(self.path, out, resume=True)
        work = out.with_name(out.name + '.sequence-work')
        state = inc.read_state(work)
        first = inc.cached_scene(work, state['completed']['01-carry'], state['completed']['01-carry']['key'])
        before = self.files(first)
        with patch.object(layers, 'render_scene', wraps=real) as render:
            r = seq.build_sequence(self.path, out, resume=True)
        self.assertEqual(render.call_count, 2)
        self.assertEqual(r['scene_exports']['resumed'], 1)
        self.assertEqual(before, self.files(first))
        with patch.object(layers, 'render_scene', side_effect=AssertionError('Already done')):
            self.assertEqual(seq.build_sequence(self.path, out, resume=True)['status'], 'verified')

    def test_changed_input_or_tampered_checkpoint_fails_without_overwrite(self):
        out = self.root / 'v1'
        real = layers.render_scene; calls = []
        def interrupted(source, target):
            calls.append(1)
            if len(calls) == 2: raise KeyboardInterrupt()
            return real(source, target)
        with patch.object(layers, 'render_scene', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt): seq.build_sequence(self.path, out, resume=True)
        work = out.with_name(out.name + '.sequence-work'); before = self.files(work)
        self.value['title'] = 'Changed'; self.save()
        with self.assertRaisesRegex(ValueError, 'input or engine changed'):
            seq.build_sequence(self.path, out, resume=True)
        self.assertEqual(before, self.files(work))
        self.value['title'] = 'Carry, release, leave'; self.save()
        state = inc.read_state(work); entry = state['completed']['01-carry']
        p = work / 'cache' / entry['directory'] / 'preview.gif'; p.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'files changed'):
            seq.build_sequence(self.path, out, resume=True)
        self.assertEqual(p.read_bytes(), b'changed')

    def test_partial_publication_resumes_without_reencoding(self):
        out = self.root / 'v1'; real = cli_publish = inc.cli.publish_file
        def interrupted(source, target, *args, **kwargs):
            if target == out / 'sequence-receipt.json':
                raise KeyboardInterrupt()
            return real(source, target, *args, **kwargs)
        with patch.object(inc.cli, 'publish_file', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt): seq.build_sequence(self.path, out, resume=True)
        before = self.files(out)
        with patch.object(layers, 'render_scene', side_effect=AssertionError('Completed exports survive')):
            r = seq.build_sequence(self.path, out, resume=True)
        self.assertEqual(r['scene_exports']['resumed'], 3)
        self.assertTrue(all((out / name).read_bytes() == data for name, data in before.items()))

    def test_dry_run_writes_nothing_and_completed_outputs_never_replaced(self):
        out = self.root / 'plan'
        self.assertEqual(seq.build_sequence(self.path, out, resume=True, dry_run=True)['provider_calls'], 0)
        self.assertFalse(out.exists()); self.assertFalse(out.with_name('plan.sequence-work').exists())
        old = self.baseline(); before = self.files(old)
        with self.assertRaises(ValueError): seq.build_sequence(self.path, old, reuse_from=old)
        self.assertEqual(before, self.files(old))


class PlanningTests(SequenceFixture, unittest.TestCase):
    def test_removed_scene_and_join_are_reported(self):
        old = seq.compile_sequence(self.path)
        self.value['shots'].pop(); self.save()
        plan = inc.review_plan(seq.compile_sequence(self.path), old)
        self.assertEqual(plan['removed_scenes'], ['03-result'])
        self.assertEqual(plan['removed_joins'], [{'previous': '02-release', 'next': '03-result'}])
        self.assertEqual(plan['joins_for_review'], [])

    def test_dry_run_reuse_does_not_need_encoder_or_write(self):
        old = self.root / 'old'; old.mkdir()
        shutil.copy2(self.path, old / 'sequence.json'); shutil.copy2(self.stage, old / 'stage.json')
        with patch.object(seq, 'verify_sequence', side_effect=AssertionError('No encoder preflight')):
            result = seq.build_sequence(self.path, self.root / 'new', reuse_from=old, dry_run=True)
        self.assertEqual(result['reuse_validation'], 'pending execution verification')
        self.assertFalse((self.root / 'new.sequence-work').exists())

    def test_conflicting_partial_publication_is_never_overwritten(self):
        stage = self.root / 'candidate'; stage.mkdir(); (stage / 'film.mp4').write_bytes(b'new')
        out = self.root / 'existing'; out.mkdir(); (out / 'film.mp4').write_bytes(b'accepted')
        with self.assertRaisesRegex(ValueError, 'Partial publication changed'):
            inc.publish_revision(stage, out)
        self.assertEqual((out / 'film.mp4').read_bytes(), b'accepted')


    def test_published_files_do_not_share_recovery_snapshot_storage(self):
        stage = self.root / 'ready'; stage.mkdir(); (stage / 'film.mp4').write_bytes(b'original')
        out = self.root / 'published'
        inc.publish_revision(stage, out)
        (out / 'film.mp4').write_bytes(b'user edit')
        self.assertEqual((stage / 'film.mp4').read_bytes(), b'original')
