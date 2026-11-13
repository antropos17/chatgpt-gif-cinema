"""Fast behavioral checks for the real-film checkpoint adapter; no generation."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('lantern_example_build', ROOT / 'examples/lantern-echo/build.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class LanternBuildTests(unittest.TestCase):
    def test_one_effect_edit_requires_one_render_and_two_boundary_reviews(self):
        original = BUILD.recipe(BUILD.ROOT / 'timeline.json')
        manifest = BUILD.read_json(BUILD.ROOT / 'assets/manifest.json')
        keys = BUILD.identities(original, manifest, 'fixed-test-engine')
        revised = copy.deepcopy(original)
        revised['scenes'][4]['effects']['canopy_gain'] = .6
        plan = BUILD.review(revised, BUILD.identities(revised, manifest, 'fixed-test-engine'), {'keys': keys})
        self.assertEqual(plan['changed_scenes'], ['05-release'])
        self.assertEqual(sum(d['encoding'] == 'reuse' for d in plan['scenes']), 9)
        self.assertEqual(plan['neighbor_scenes_for_review'], ['04-catch', '06-greeting'])
        self.assertEqual(plan['cuts_for_review'], [
            {'previous': '04-catch', 'next': '05-release', 'at_ms': 7520},
            {'previous': '05-release', 'next': '06-greeting', 'at_ms': 10400}])

    def test_only_bow_users_are_invalidated_by_a_bow_asset_revision(self):
        timeline = BUILD.recipe(BUILD.ROOT / 'timeline.json')
        manifest = BUILD.read_json(BUILD.ROOT / 'assets/manifest.json')
        keys = BUILD.identities(timeline, manifest, 'fixed-test-engine')
        changed = copy.deepcopy(manifest)
        changed['files']['assets/motion/bow.png']['sha256'] = 'a' * 64
        plan = BUILD.review(timeline, BUILD.identities(timeline, changed, 'fixed-test-engine'), {'keys': keys})
        self.assertEqual(plan['changed_scenes'], ['07-bow'])

    def test_corrupt_checkpoint_is_rejected_before_decoder_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'scene.mkv').write_bytes(b'changed')
            record = {'file': 'scene.mkv', 'key': 'scene-key', 'sha256': BUILD.sha(b'original')}
            with mock.patch.object(BUILD, 'video_frames') as decoder:
                with self.assertRaisesRegex(ValueError, 'Completed scene changed'):
                    BUILD.verify_scene(root, record, 'scene-key')
                decoder.assert_not_called()
            self.assertEqual((root / 'scene.mkv').read_bytes(), b'changed')

    def test_timeline_cannot_drop_a_frame_between_scenes(self):
        value = BUILD.read_json(BUILD.ROOT / 'timeline.json')
        value['scenes'][4]['start_frame'] += 1
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'timeline.json'
            path.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'partition'):
                BUILD.recipe(path)

    def test_checkpoint_paths_cannot_escape_the_output(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                BUILD.local(Path(temp), '../other/scene.mkv')


if __name__ == '__main__':
    unittest.main()
