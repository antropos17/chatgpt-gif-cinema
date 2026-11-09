"""Authored state checks are offline and cannot certify the visual performance."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gif_cinema import cli, story_state as state

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / '.agents/skills/gif-cinema/assets/example'


class StoryStateTests(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT / "output" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.story = self.root / 'story.json'
        self.ledger = self.root / 'state.json'
        self.data = {'schema_version': 1, 'title': 'A lantern journey', 'shots': [
            {'id': '01-lift', 'action': 'Lift the lantern', 'generate': {}},
            {'id': '02-walk', 'action': 'Walk to the tree', 'generate': {}},
            {'id': '03-place', 'action': 'Put it down', 'generate': {}},
            {'id': '04-wave', 'action': 'Wave goodbye', 'generate': {}}]}
        self.write(self.story, self.data)
        self.value = state.make_template(self.story)
        self.value['facts'] = [{'id': 'lantern.holder', 'initial': 'crate'},
                               {'id': 'fox.scarf', 'initial': 'teal', 'fixed': True}]
        for shot in self.value['shots']:
            shot['requires'] = {'fox.scarf': 'teal'}
        self.value['shots'][0]['requires']['lantern.holder'] = 'crate'
        self.value['shots'][0]['changes'] = [self.change('crate', 'fox')]
        self.value['shots'][1]['requires']['lantern.holder'] = 'fox'
        self.value['shots'][2]['requires']['lantern.holder'] = 'fox'
        self.value['shots'][2]['changes'] = [self.change('fox', 'ground')]
        self.value['shots'][3]['requires']['lantern.holder'] = 'ground'
        self.write(self.ledger, self.value)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    @staticmethod
    def change(before, after, fact='lantern.holder'):
        return {'fact': fact, 'from': before, 'to': after, 'reason': 'An explicit author action.'}

    def check(self):
        self.write(self.ledger, self.value)
        return state.check_story(self.story, self.ledger)

    def test_tracks_sparse_persistent_facts_with_origins(self):
        result = self.check()
        self.assertEqual(result['status'], 'declared-facts-consistent')
        self.assertEqual(result['final_state']['lantern.holder'], 'ground')
        self.assertEqual(result['timeline'][1]['before']['lantern.holder'], 'fox')
        self.assertEqual(result['timeline'][3]['last_set_by']['lantern.holder'], '03-place:changes')
        self.assertEqual(result['valid_change_count'], 2)
        self.assertEqual(result['visual_acceptance'], 'not-established')

    def test_reports_prop_teleportation_to_last_actual_setter(self):
        self.value['shots'][3]['requires']['lantern.holder'] = 'fox'
        report = self.check()
        self.assertEqual(report['status'], 'conflicts')
        self.assertEqual(report['issues'], [{'shot_id': '04-wave', 'phase': 'requires',
            'fact': 'lantern.holder', 'code': 'requirement-mismatch', 'carried': 'ground',
            'required': 'fox', 'last_set_by': '03-place:changes'}])
        self.assertEqual(report['final_state']['lantern.holder'], 'ground')

    def test_fixed_costume_cannot_change(self):
        self.value['shots'][1]['changes'] = [self.change('teal', 'red', 'fox.scarf')]
        result = self.check()
        self.assertEqual(result['issues'][0]['code'], 'fixed-fact-change')
        self.assertEqual(result['final_state']['fox.scarf'], 'teal')

    def test_bad_from_does_not_silently_repair_or_propagate(self):
        self.value['shots'][0]['changes'][0]['from'] = 'ground'
        result = self.check()
        self.assertEqual(result['issues'][0]['code'], 'change-from-mismatch')
        self.assertEqual(result['timeline'][0]['after']['lantern.holder'], 'crate')
        self.assertEqual(result['final_state']['lantern.holder'], 'crate')
        self.assertGreater(len(result['issues']), 1)

    def test_offscreen_change_is_explicit_before_requirements(self):
        self.value['shots'][3]['handoff_changes'] = [self.change('ground', 'fox')]
        self.value['shots'][3]['requires']['lantern.holder'] = 'fox'
        result = self.check()
        self.assertEqual(result['status'], 'declared-facts-consistent')
        self.assertEqual(result['timeline'][3]['carried_in']['lantern.holder'], 'ground')
        self.assertEqual(result['timeline'][3]['before']['lantern.holder'], 'fox')
        self.assertEqual(result['timeline'][3]['last_set_by']['lantern.holder'], '04-wave:handoff_changes')

    def test_fixed_facts_cannot_use_offscreen_escape_hatch(self):
        self.value['shots'][1]['handoff_changes'] = [self.change('teal', 'red', 'fox.scarf')]
        self.assertEqual(self.check()['issues'][0]['code'], 'fixed-fact-change')

    def test_missing_requirements_are_visible_and_empty_template_not_pass(self):
        self.value['shots'][1]['requires'] = {}
        self.assertEqual(self.check()['shots_without_requirements'], ['02-walk'])
        self.value = state.make_template(self.story)
        self.assertEqual(self.check()['status'], 'untracked')

    def test_facts_without_any_requirements_not_pass(self):
        for shot in self.value['shots']:
            shot['requires'] = {}
        self.assertEqual(self.check()['status'], 'untracked')

    def test_stale_story_fields_and_order_rejected(self):
        for modify in (lambda x: x['shots'][1].update(action='A different action'),
                       lambda x: x['shots'].reverse(),
                       lambda x: x.update(title='A different title')):
            data = copy.deepcopy(self.data)
            modify(data)
            self.write(self.story, data)
            with self.assertRaisesRegex(ValueError, 'Storyboard changed'):
                self.check()

    def test_json_whitespace_key_order_and_crlf_do_not_stale_ledger(self):
        self.story.write_bytes(json.dumps(self.data, sort_keys=True, indent=4).replace('\n', '\r\n').encode())
        self.assertEqual(self.check()['status'], 'declared-facts-consistent')

    def test_source_retake_invalidates_pin_without_modifying_inputs(self):
        source = self.root / 'shot.gif'
        source.write_bytes((ASSETS / 'shot-01.gif').read_bytes())
        self.data['shots'][0].pop('generate')
        self.data['shots'][0]['source'] = 'shot.gif'
        self.write(self.story, self.data)
        fresh = state.make_template(self.story)
        self.value['story_sha256'] = fresh['story_sha256']
        self.value['source_hashes'] = fresh['source_hashes']
        self.assertEqual(self.check()['status'], 'declared-facts-consistent')
        replacement = (ASSETS / 'shot-02.gif').read_bytes()
        source.write_bytes(replacement)
        before = {p: p.read_bytes() for p in (source, self.story, self.ledger)}
        with self.assertRaisesRegex(ValueError, 'Source hashes changed'):
            state.check_story(self.story, self.ledger)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_storyboard_existing_media_pin_is_respected(self):
        self.data['shots'][0] = {'id': '01-lift', 'source': str(ASSETS / 'shot-01.gif'),
                                 'source_sha256': '0' * 64}
        self.write(self.story, self.data)
        with self.assertRaisesRegex(ValueError, 'storyboard source SHA-256 mismatch'):
            state.make_template(self.story)

    def test_incomplete_or_added_source_hashes_rejected(self):
        self.value['source_hashes'] = {'missing': '0' * 64}
        with self.assertRaisesRegex(ValueError, 'Source hashes changed'):
            self.check()

    def test_ledger_has_exact_shot_coverage_and_order(self):
        original = copy.deepcopy(self.value)
        for change in (lambda x: x['shots'].pop(), lambda x: x['shots'].reverse(),
                       lambda x: x['shots'][0].update(shot_id='MISSING'),
                       lambda x: x['shots'].append(x['shots'][0]),
                       lambda x: x['shots'].__setitem__(0, None)):
            self.value = copy.deepcopy(original)
            change(self.value)
            with self.assertRaisesRegex(ValueError, 'every story shot exactly once'):
                self.check()

    def test_undeclared_and_wrong_case_facts_rejected(self):
        for key in ('ghost.owner', 'Lantern.holder'):
            self.value['shots'][0]['requires'] = {key: 'crate'}
            with self.assertRaisesRegex(ValueError, 'Undeclared fact'):
                self.check()

    def test_duplicate_casefolded_fact_ids_rejected(self):
        self.value['facts'].append({'id': 'Fox.scarf', 'initial': 'red'})
        with self.assertRaisesRegex(ValueError, 'Fact IDs must be unique'):
            self.check()

    def test_duplicate_change_and_unknown_fields_rejected(self):
        original = copy.deepcopy(self.value)
        for modify in (lambda x: x['shots'][0]['changes'].append(x['shots'][0]['changes'][0]),
                       lambda x: x['facts'][0].update(extra=True),
                       lambda x: x['shots'][0].update(extra=True),
                       lambda x: x.update(extra=True),
                       lambda x: x['shots'][0]['changes'][0].update(extra=True)):
            self.value = copy.deepcopy(original)
            modify(self.value)
            with self.assertRaises(ValueError):
                self.check()

    def test_wrong_values_empty_reasons_and_bad_types_rejected(self):
        original = copy.deepcopy(self.value)
        for modify in (lambda x: x.update(schema_version=True),
                       lambda x: x['facts'][0].update(initial=None),
                       lambda x: x['facts'][0].update(fixed=1),
                       lambda x: x['shots'][0].update(requires=[]),
                       lambda x: x['shots'][0].update(changes={}),
                       lambda x: x['shots'][0]['requires'].update({'fox.scarf': 1}),
                       lambda x: x['shots'][0]['changes'][0].update(reason=' '),
                       lambda x: x['shots'][0]['changes'][0].update(to='x'*257)):
            self.value = copy.deepcopy(original)
            modify(self.value)
            with self.assertRaises(ValueError):
                self.check()

    def test_limits_for_json_and_facts(self):
        self.ledger.write_bytes(b'x' * (state.MAX_JSON_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            state.check_story(self.story, self.ledger)
        self.value['facts'] = [{'id': f'x.f{i}', 'initial': 'value'} for i in range(129)]
        with self.assertRaisesRegex(ValueError, 'at most 128'):
            self.check()

    def test_nonfinite_and_duplicate_json_keys_rejected(self):
        for raw in ('{"x": 1, "x": 2}', '{"x": NaN}', '{"x": 1e999}'):
            self.story.write_text(raw, encoding='utf-8')
            with self.assertRaises(ValueError):
                state.make_template(self.story)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO requires POSIX')
    def test_fifo_input_fails_without_blocking(self):
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, 'regular local'):
            state.load_json(fifo)

    def test_invalid_story_ids_modes_and_bounds_rejected(self):
        for data in ({'schema_version': 1, 'shots': []},
                     {'schema_version': True, 'shots': self.data['shots']},
                     {'schema_version': 1, 'shots': [{'id': 'a', 'source': 'a', 'prompt': 'b'}]},
                     {'schema_version': 1, 'shots': [{'id': '../a', 'prompt': 'x'}]},
                     {'schema_version': 1, 'shots': [{'id': 'a', 'prompt': 'x'}, {'id': 'A', 'prompt': 'x'}]}):
            self.write(self.story, data)
            with self.assertRaises(ValueError):
                state.make_template(self.story)

    def test_no_network_credentials_processes_or_decode_required(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No network')), \
                patch('socket.socket', side_effect=AssertionError('No sockets')), \
                patch('subprocess.run', side_effect=AssertionError('No processes')), \
                patch('gif_cinema.cli.gif_frames', side_effect=AssertionError('No decoding')):
            result = self.check()
        self.assertEqual(result['provider_calls'], 0)

    def test_sources_have_per_file_and_aggregate_bounds(self):
        source = self.root / 'clip.gif'
        source.write_bytes(b'0123456789')
        self.data['shots'] = [{'id': str(i), 'source': 'clip.gif'} for i in range(4)]
        self.write(self.story, self.data)
        with patch.object(state, 'MAX_SOURCE_BYTES', 9):
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                state.make_template(self.story)
        with patch.object(state, 'MAX_TOTAL_SOURCE_BYTES', 39):
            with self.assertRaisesRegex(ValueError, 'combined'):
                state.make_template(self.story)

    def test_urls_rejected(self):
        self.data['shots'] = [{'id': 'a', 'source': 'https://example.org/clip.gif'}]
        self.write(self.story, self.data)
        with self.assertRaisesRegex(ValueError, 'local file paths'):
            state.make_template(self.story)

    def test_cli_exit_status_and_optional_report(self):
        args = cli.build_parser().parse_args(['story-state', 'check', str(self.story), str(self.ledger)])
        before = set(self.root.iterdir())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            args.func(args)
        self.assertEqual(json.loads(output.getvalue())['status'], 'declared-facts-consistent')
        self.assertEqual(set(self.root.iterdir()), before)
        self.value['shots'][3]['requires']['lantern.holder'] = 'fox'
        self.write(self.ledger, self.value)
        args.output = self.root / 'report.json'
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ex:
            args.func(args)
        self.assertEqual(ex.exception.code, 2)
        self.assertEqual(json.loads(args.output.read_text())['status'], 'conflicts')

    def test_init_no_inferred_facts_and_no_clobber(self):
        out = self.root / 'new.json'
        args = cli.build_parser().parse_args(['story-state', 'init', str(self.story), '-o', str(out)])
        with contextlib.redirect_stdout(io.StringIO()):
            args.func(args)
        self.assertEqual(state.load_json(out)['facts'], [])
        self.assertEqual(state.check_story(self.story, out)['status'], 'untracked')
        original = out.read_bytes()
        with self.assertRaisesRegex(ValueError, 'new file'):
            args.func(args)
        self.assertEqual(out.read_bytes(), original)

    def test_source_story_ledger_symlink_and_hardlink_outputs_preserved(self):
        candidates = [self.story, self.ledger]
        alias = self.root / 'hardlink'
        os.link(self.story, alias)
        candidates.append(alias)
        try:
            link = self.root / 'symlink'
            link.symlink_to(self.story)
            candidates.append(link)
        except (OSError, NotImplementedError):
            pass
        for path in candidates:
            original = path.read_bytes()
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'new file'):
                state.write_new(path, {'replaced': True})
            self.assertEqual(path.read_bytes(), original)

    def test_dangling_symlink_not_replaced(self):
        path = self.root / 'dangling'
        try:
            path.symlink_to(self.root / 'missing')
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks not supported')
        with self.assertRaisesRegex(ValueError, 'new file'):
            state.write_new(path, {})
        self.assertTrue(path.is_symlink())
        self.assertFalse((self.root / 'missing').exists())

    def test_publication_race_never_clobbers(self):
        destination = self.root / 'report.json'
        real_publish = cli.publish_file
        def race(stage, target, force=False):
            target.write_bytes(b'other writer')
            real_publish(stage, target, force)
        with patch.object(cli, 'publish_file', side_effect=race):
            with self.assertRaises(FileExistsError):
                state.write_new(destination, {})
        self.assertEqual(destination.read_bytes(), b'other writer')
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_real_astronaut_and_fourteen_action_plan(self):
        for story, name, facts, shots in (('storyboard.json', 'astronaut', 3, 4),
                                         ('long-story.plan.json', 'lantern', 8, 14)):
            with self.subTest(name=name):
                path = ASSETS / story
                hashes = {x: hashlib.sha256(x.read_bytes()).hexdigest() for x in ASSETS.glob('shot-*.gif')}
                result = state.check_story(path, ROOT / f'examples/story-state-{name}.json')
                self.assertEqual(result['status'], 'declared-facts-consistent')
                self.assertEqual(result['fact_count'], facts)
                self.assertEqual(len(result['timeline']), shots)
                self.assertFalse(result['shots_without_requirements'])
                self.assertEqual(result['provider_calls'], 0)
                self.assertEqual(hashes, {x: hashlib.sha256(x.read_bytes()).hexdigest() for x in hashes})
                self.assertEqual(len(result['source_hashes']), 3 if name == 'astronaut' else 0)

    def test_maximum_shot_and_fact_counts_preserve_long_handoffs(self):
        self.data['shots'] = [{'id': f's{i:02}', 'prompt': 'Unrendered action'} for i in range(64)]
        self.write(self.story, self.data)
        self.value = state.make_template(self.story)
        self.value['facts'] = [{'id': f'prop{i}.holder', 'initial': 'fox'} for i in range(128)]
        self.value['shots'][0]['changes'] = [self.change('fox', 'ground', 'prop127.holder')]
        self.value['shots'][-1]['requires'] = {'prop127.holder': 'ground'}
        result = self.check()
        self.assertEqual(result['status'], 'declared-facts-consistent')
        self.assertEqual(len(result['timeline']), 64)
        self.assertEqual(result['fact_count'], 128)
        self.assertEqual(result['timeline'][-1]['last_set_by']['prop127.holder'], 's00:changes')
        self.assertEqual(len(result['shots_without_requirements']), 63)

    def test_module_cli_invalid_input_exit_one(self):
        self.ledger.write_text('{}', encoding='utf-8')
        run = subprocess.run([sys.executable, '-m', 'gif_cinema', 'story-state', 'check',
                              str(self.story), str(self.ledger)], cwd=ROOT, text=True,
                             capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 1)
        self.assertIn('schema_version', run.stderr)
        self.assertNotIn('Traceback', run.stderr)


if __name__ == '__main__':
    unittest.main()
