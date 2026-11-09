"""Revision-bound full-frame review without model calls or source modification."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.agents/skills/gif-cinema/scripts/review_gif.py'
spec = importlib.util.spec_from_file_location('review_pack', SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def animation(path, transparent=False, loop=0, frames=3):
    images = []
    for index in range(frames):
        image = Image.new('RGBA', (48, 48), (0, 0, 0, 0) if transparent else 'white')
        ImageDraw.Draw(image).rectangle((4 + index, 8, 20 + index, 24), fill=(255, 0, 0, 255))
        images.append(image)
    options = {'loop': loop} if loop is not None else {}
    images[0].save(path, save_all=True, append_images=images[1:], duration=[80 + i * 20 for i in range(frames)],
                   disposal=2, optimize=False, **options)


class ReviewPackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gif = self.root / 'source.gif'
        self.output = self.root / 'review'
        animation(self.gif)
        self.original = self.gif.read_bytes()
        network = patch('gif_cinema.cli.urlopen', side_effect=AssertionError('No network calls'))
        network.start()
        self.addCleanup(network.stop)

    def extract(self, **kwargs):
        return review.extract(self.gif, self.output, **kwargs)

    def approve_fixture(self):
        path = self.output / 'review.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['reviewer'] = 'Test fixture, not a visual acceptance claim'
        for row in data['frames']:
            row['decision'] = 'pass'
        data['playback'] = data['loop_seam'] = 'pass'
        path.write_bytes(review.json_bytes(data))
        return data

    def write_review(self, data):
        (self.output / 'review.json').write_bytes(review.json_bytes(data))

    def test_extract_preserves_bytes_timing_and_native_rgba_pixels(self):
        report = self.extract(focus=[2, 3, 28, 30])
        self.assertEqual(report['media']['durations_ms'], [80, 100, 120])
        self.assertEqual(report['media']['duration_ms'], 300)
        self.assertEqual(report['media']['technical_status'], 'passed')
        self.assertEqual(self.original, self.gif.read_bytes())
        self.assertEqual(self.original, (self.output / 'animation.gif').read_bytes())
        frames, _, _ = review.decode(self.original)
        for index, frame in enumerate(frames):
            with Image.open(self.output / f'frames/{index:04}.png') as actual:
                self.assertEqual(actual.tobytes(), frame.tobytes())
            with Image.open(self.output / f'focus/{index:04}.png') as actual:
                self.assertEqual(actual.tobytes(), frame.crop((2, 3, 28, 30)).tobytes())
        self.assertTrue(report['transitions'][0]['loop_seam'])
        self.assertEqual(report['transitions'][0]['from_frame'], 2)
        self.assertEqual(report['transitions'][0]['to_frame'], 0)
        template = json.loads((self.output / 'review.json').read_text())
        self.assertEqual(template['playback'], 'pending')
        self.assertEqual(template['user_acceptance'], 'pending')
        self.assertTrue(all(row['decision'] == 'pending' for row in template['frames']))

    def test_sticker_profile_preserves_alpha(self):
        animation(self.gif, transparent=True)
        report = self.extract(purpose='sticker')
        self.assertEqual(report['media']['technical_status'], 'passed')
        with Image.open(self.output / 'frames/0001.png') as frame:
            self.assertEqual(frame.getchannel('A').getextrema(), (0, 255))
        self.approve_fixture()
        self.assertEqual(review.check(self.output)['visual_review_record'], 'complete')

    def test_general_accepts_play_once_and_opaque_edge_to_edge_art(self):
        animation(self.gif, loop=None)
        report = self.extract()
        self.assertIsNone(report['media']['loop'])
        self.assertEqual(report['media']['technical_status'], 'passed')
        self.assertNotIn('type="checkbox" checked', (self.output / 'index.html').read_text())

    def test_sticker_reports_failures_but_still_extracts_diagnostics(self):
        animation(self.gif, loop=None)
        report = self.extract(purpose='sticker')
        self.assertEqual(report['media']['technical_status'], 'failed')
        self.assertTrue((self.output / 'frames/0002.png').is_file())
        self.approve_fixture()
        with self.assertRaisesRegex(ValueError, 'Technical review failed'):
            review.check(self.output)

    def test_no_visual_acceptance_inferred_from_technical_pass(self):
        self.extract()
        with self.assertRaisesRegex(ValueError, 'named reviewer'):
            review.check(self.output)
        self.approve_fixture()
        result = review.check(self.output, gif=self.gif)
        self.assertEqual(result['user_acceptance_record'], 'pending')
        self.assertIn('not user acceptance', result['notice'])

    def test_user_rejection_remains_separate_from_complete_review(self):
        self.extract()
        data = self.approve_fixture()
        data['user_acceptance'] = 'rejected'
        self.write_review(data)
        self.assertEqual(review.check(self.output)['user_acceptance_record'], 'rejected')

    def test_reviewer_and_all_frames_playback_seam_required(self):
        self.extract()
        approved = self.approve_fixture()
        variants = []
        for key, value in [('reviewer', ' '), ('playback', 'pending'), ('loop_seam', 'repair'), ('user_acceptance', True), ('user_acceptance', [])]:
            item = copy.deepcopy(approved)
            item[key] = value
            variants.append(item)
        for update in [{'decision': []}, {'decision': 'repair'}, {'decision': 'pending'}, {'index': True}, {'index': 1}, {'notes': []}]:
            item = copy.deepcopy(approved)
            item['frames'][0].update(update)
            variants.append(item)
        for rows in [approved['frames'][:-1], 'invalid', [None] * 3]:
            item = copy.deepcopy(approved)
            item['frames'] = rows
            variants.append(item)
        for data in variants:
            with self.subTest(data=data):
                self.write_review(data)
                with self.assertRaises(ValueError):
                    review.check(self.output)

    def test_original_and_copy_revisions_are_checked(self):
        self.extract()
        self.approve_fixture()
        animation(self.gif, loop=2)
        with self.assertRaisesRegex(ValueError, 'GIF changed'):
            review.check(self.output, gif=self.gif)
        (self.output / 'animation.gif').write_bytes(self.gif.read_bytes())
        with self.assertRaisesRegex(ValueError, 'GIF changed'):
            review.check(self.output)

    def test_modified_frames_focus_sheets_player_are_rejected(self):
        self.extract(focus=[1, 1, 20, 20])
        self.approve_fixture()
        for name in ['frames/0001.png', 'focus/0001.png', 'sheets/000.png', 'index.html']:
            path = self.output / name
            original = path.read_bytes()
            path.write_bytes(b'changed')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'artifact changed'):
                review.check(self.output)
            path.write_bytes(original)

    def test_changed_audit_is_not_silently_trusted(self):
        self.extract()
        self.approve_fixture()
        path = self.output / 'audit.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'Audit changed'):
            review.check(self.output)

    def test_media_facts_recomputed_even_if_audit_hash_updated(self):
        self.extract()
        data = self.approve_fixture()
        path = self.output / 'audit.json'
        audit = json.loads(path.read_text())
        audit['media']['duration_ms'] = 999
        path.write_bytes(review.json_bytes(audit))
        data['audit_sha256'] = review.digest(path.read_bytes())
        self.write_review(data)
        with self.assertRaisesRegex(ValueError, 'facts do not match'):
            review.check(self.output)

    def test_artifact_traversal_rejected_even_if_audit_hash_updated(self):
        self.extract()
        data = self.approve_fixture()
        path = self.output / 'audit.json'
        audit = json.loads(path.read_text())
        audit['artifacts']['../../outside.png'] = 'a' * 64
        path.write_bytes(review.json_bytes(audit))
        data['audit_sha256'] = review.digest(path.read_bytes())
        self.write_review(data)
        with self.assertRaisesRegex(ValueError, 'artifact list'):
            review.check(self.output)

    def test_focus_validation_before_any_output(self):
        for focus in [[-1, 0, 2, 2], [0, 0, 99, 2], [2, 2, 2, 3], [0, 0, 2], [False, 0, 2, 2]]:
            with self.subTest(focus=focus), self.assertRaisesRegex(ValueError, 'Focus box'):
                self.extract(focus=focus)
            self.assertFalse(self.output.exists())

    def test_existing_output_preserved(self):
        self.extract()
        self.approve_fixture()
        old = (self.output / 'review.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'new directory'):
            self.extract()
        self.assertEqual((self.output / 'review.json').read_bytes(), old)

    def test_failed_write_removes_only_new_partial_output(self):
        with patch.object(review, 'MAX_OUTPUT_BYTES', 1), self.assertRaisesRegex(ValueError, 'output exceeds'):
            self.extract()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.gif.read_bytes(), self.original)

    def test_input_and_decoded_budgets_checked_before_output(self):
        for constant, limit in [('MAX_BYTES', 10), ('MAX_FRAMES', 2), ('MAX_PIXELS', 48 * 48)]:
            with self.subTest(constant=constant), patch.object(review, constant, limit), self.assertRaises(ValueError):
                self.extract()
            self.assertFalse(self.output.exists())

    def test_truncated_and_static_inputs_rejected(self):
        self.gif.write_bytes(self.original[:-5])
        with self.assertRaises(ValueError):
            self.extract()
        animation(self.gif, frames=1)
        with self.assertRaisesRegex(ValueError, 'at least two'):
            self.extract()
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO only')
    def test_fifo_rejected_without_waiting(self):
        fifo = self.root / 'input.fifo'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, 'regular local file'):
            review.extract(fifo, self.output)

    def test_json_duplicate_keys_rejected(self):
        path = self.root / 'bad.json'
        path.write_text('{"decision":"pending","decision":"pass"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
            review.load_json(path)

    def test_html_escapes_filename_and_contains_no_remote_assets(self):
        page = review.player('<script>alert(1)</script>.gif', [20, 300], 0, focus=True).decode()
        self.assertNotIn('<script>alert', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('const delays=[20, 300]', page)
        self.assertIn('playing=false', page)
        self.assertIn('Native focus crop', page)
        self.assertNotIn('https://', page)
        self.assertNotIn('http://', page)
        name = 'SOURCE-NOTICE-CHECKED-DELAYS-FOCUSLINK.gif'
        self.assertIn(name, review.player(name, [20, 300], 0).decode())

    def test_sheet_pagination_stays_bounded(self):
        animation(self.gif, frames=17)
        report = self.extract()
        for name in ['sheets/000.png', 'sheets/001.png']:
            self.assertIn(name, report['artifacts'])
            with Image.open(self.output / name) as sheet:
                self.assertLessEqual(sheet.width * sheet.height, 832 * 928)
        self.assertTrue((self.output / 'frames/0016.png').is_file())

    def test_cli_failure_status_for_pending_review_and_technical_failure(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(review.main(['extract', str(self.gif), str(self.output)]), 0)
            self.assertEqual(review.main(['check', str(self.output)]), 1)
            self.assertEqual(review.main(['extract', str(self.gif), str(self.root / 'sticker'), '--purpose', 'sticker']), 1)

    @unittest.skipUnless(shutil.which('node'), 'Optional JavaScript runtime is unavailable')
    def test_player_controls_with_fake_dom_and_clock(self):
        # Behavioral unit test, not a claim of browser rendering/playback QA.
        script = review.player('test.gif', [80, 100, 120], None, focus=True).decode().split('<script>')[1].split('</script>')[0]
        harness = r"""
const vm=require('node:vm'), assert=require('node:assert/strict');
const nodes=Object.fromEntries(['play','prev','next','repeat','native','matte','frame','focus','original','status'].map(id=>[id,{checked:false,value:'checker'}]));
let timers=new Map(), serial=0, listener, native=false;
const backgrounds=[{style:{}},{style:{}}];
const document={hidden:false,getElementById:id=>nodes[id],querySelectorAll:()=>backgrounds,
body:{classList:{toggle:(name,value)=>{native=value;}}},addEventListener:(name,cb)=>{listener=cb;}};
const context={document,setTimeout:(cb,ms)=>{const id=++serial;timers.set(id,{cb,ms});return id;},clearTimeout:id=>timers.delete(id)};
vm.runInNewContext(SOURCE, context);
const frame=n=>assert.ok(nodes.status.textContent.startsWith('Frame '+n+' of 2'));
function tick(ms){assert.equal(timers.size,1);const [id,item]=[...timers][0];assert.equal(item.ms,ms);timers.delete(id);item.cb();}
frame(0);assert.equal(timers.size,0);nodes.next.onclick();frame(1);nodes.prev.onclick();frame(0);
nodes.prev.onclick();frame(2);nodes.next.onclick();frame(0);nodes.play.onclick();tick(80);frame(1);tick(100);frame(2);tick(120);
assert.equal(nodes.play.textContent,'Play');assert.equal(timers.size,0);
nodes.repeat.checked=true;nodes.play.onclick();tick(120);frame(0);nodes.next.onclick();frame(1);assert.equal(timers.size,0);
assert.equal(nodes.original.href,'frames/0001.png');assert.equal(nodes.focus.href,'focus/0001.png');
nodes.play.onclick();nodes.play.onclick();assert.equal(timers.size,0);
nodes.native.checked=true;nodes.native.onchange();assert.equal(native,true);
nodes.matte.value='black';nodes.matte.onchange();assert.equal(backgrounds[0].style.background,'black');
nodes.matte.value='checker';nodes.matte.onchange();assert.equal(backgrounds[1].style.background,'');
nodes.play.onclick();document.hidden=true;listener();assert.equal(timers.size,0);assert.equal(nodes.play.textContent,'Play');
""".replace('SOURCE', json.dumps(script))
        result = subprocess.run([shutil.which('node'), '-e', harness], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_runs_from_unrelated_directory_with_runtime_on_import_path(self):
        # Subprocess import and relative-path isolation; not a package installation test.
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        result = subprocess.run([sys.executable, str(SCRIPT), 'extract', str(self.gif), str(self.output)],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.output / 'audit.json').is_file())


if __name__ == '__main__':
    unittest.main()
