"""Behavioral tests use independent miniature artwork, not the showcase renderer."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image
from gif_cinema import shots
from gif_cinema.shot_project import load_project, review
from gif_cinema.shot_renderer import Renderer, path_at


def fixture(root):
    Image.new('RGB', (16, 16), 'black').save(root/'back.png')
    atlas = Image.new('RGBA', (16, 8), 'red')
    atlas.paste((0, 0, 255, 255), (8, 0, 16, 8)); atlas.save(root/'actor.png')
    files = {name: {'path': name, 'sha256': hashlib.sha256((root/name).read_bytes()).hexdigest(),
                    'bytes': (root/name).stat().st_size} for name in ('back.png', 'actor.png')}
    return dict(format='gif-cinema-shot-project', schema_version=1, title='Independent colored cells',
                width=16, height=16, fps=25, background='back.png', files=files,
                clips={'cells': dict(source='actor.png', frames=2, columns=2, tile_size=[8, 8],
                                     xy=[0, 0], mask='alpha', threshold=0, blur=0)},
                actors=[{'id': 'actor', 'tracks': [dict(clip='cells', start=0, end=1, origin=0,
                           duration=.12, loop=False, first=0, last=1)]}],
                shadows=[], shadow_blur=0, occlusion_threshold=0, occlusion_blur=0,
                glow_blur=0, camera_push={'amplitude': 0, 'speed': 0}, effects=[], overlays=[],
                audio=dict(rate=8000, duration=1, fade_in=.1, fade_out=.1,
                           tones=[[0, .4, 440, .1, 0]], noise=[]),
                scenes=[dict(id=name, start_frame=lo, end_frame=hi, camera=[0, 0, 16, 16], effects={'gain': 1})
                        for name, lo, hi in [('first', 0, 4), ('second', 4, 8)]])


class NativeShotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root/'source.json'
        self.project = fixture(self.root)
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.project), encoding='utf-8')

    def test_generic_actor_clock_and_camera_do_not_depend_on_example(self):
        value, paths = load_project(self.path)
        renderer = Renderer(value, paths)
        before = copy.deepcopy(value)
        self.assertEqual(renderer.frame(0, value['scenes'][0]).getpixel((2, 2)), (255, 0, 0))
        self.assertEqual(renderer.frame(.12, value['scenes'][0]).getpixel((2, 2)), (0, 0, 255))
        self.assertEqual(renderer.frame(.16, value['scenes'][1]).getpixel((2, 2)), (0, 0, 255))
        self.assertEqual(renderer.frame(.16, value['scenes'][1]).getpixel((15, 15)), (0, 0, 0))
        self.assertEqual(value, before, 'Rendering must not mutate the source recipe')

    def test_one_scene_gain_edit_keeps_other_scene_key(self):
        old = shots.BuildContext(self.path).identities('engine')
        self.project['scenes'][1]['effects']['gain'] = .5; self.write()
        context = shots.BuildContext(self.path)
        plan = review(context.value, context.identities('engine'), {'keys': old})
        self.assertEqual(plan['changed_scenes'], ['second'])
        self.assertEqual(plan['neighbor_scenes_for_review'], ['first'])
        self.assertEqual(plan['cuts_for_review'][0]['at_ms'], 160)

    def test_audio_only_change_reuses_visual_scene_keys(self):
        old = shots.BuildContext(self.path).identities('engine')
        self.project['audio']['tones'][0][2] = 880; self.write()
        self.assertEqual(old, shots.BuildContext(self.path).identities('engine'))

    def test_unknown_project_and_scene_fields_are_rejected(self):
        for target in (self.project, self.project['scenes'][0]):
            target['typo'] = 1; self.write()
            with self.assertRaisesRegex(ValueError, 'expected fields'):
                load_project(self.path)
            del target['typo']

    def test_gap_and_invalid_camera_are_rejected(self):
        self.project['scenes'][1]['start_frame'] = 5; self.write()
        with self.assertRaisesRegex(ValueError, 'contiguous'):
            load_project(self.path)
        self.project['scenes'][1]['start_frame'] = 4
        self.project['scenes'][1]['camera'][2] = 17; self.write()
        with self.assertRaises(ValueError):
            load_project(self.path)

    def test_corrupt_art_is_rejected_before_renderer(self):
        (self.root/'actor.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash'):
            load_project(self.path)

    def test_dry_run_creates_no_output_and_needs_no_encoder(self):
        out = self.root/'dry'
        result = shots.build_project(self.path, out, dry_run=True, ffmpeg='missing-encoder')
        self.assertEqual(result['provider_calls'], 0)
        self.assertFalse(out.exists())

    def test_paths_are_authored_curves(self):
        self.assertEqual(path_at([{'start': 0, 'end': 2, 'kind': 'bezier',
                                  'points': [[0, 0], [2, 4], [4, 0]]}], 1), (2, 2))

    @unittest.skipUnless(shutil.which('ffmpeg') and __import__('importlib').util.find_spec('av'),
                         'native checkpoint test needs FFmpeg and PyAV')
    def test_native_checkpoint_resume_reuse_and_portable_verification(self):
        out = self.root/'base'
        original = shots.BuildContext.render_scene
        calls = []
        def interrupted(context, ffmpeg, directory, scene, key, renderer):
            calls.append(scene['id'])
            if scene['id'] == 'second':
                raise KeyboardInterrupt()
            return original(context, ffmpeg, directory, scene, key, renderer)
        with mock.patch.object(shots.BuildContext, 'render_scene', interrupted):
            with self.assertRaises(KeyboardInterrupt):
                shots.build_project(self.path, out)
        first = shots.read_json(out/'checkpoint.json')['completed']['first']
        before = (out/first['file']).stat().st_mtime_ns
        result = shots.build_project(self.path, out, resume=True)
        self.assertEqual(result['scene_exports'], {'rendered': 1, 'reused': 0, 'resumed': 1})
        self.assertEqual((out/first['file']).stat().st_mtime_ns, before)
        self.assertEqual(shots.verify_project(out)['status'], 'verified')
        self.project['scenes'][1]['effects']['gain'] = .5; self.write()
        revision = self.root/'revision'
        result = shots.build_project(self.path, revision, reuse_from=out)
        self.assertEqual(result['scene_exports'], {'rendered': 1, 'reused': 1, 'resumed': 0})
        stamp = (revision/'build-receipt.json').stat().st_mtime_ns
        self.assertTrue(shots.build_project(self.path, revision, reuse_from=out, resume=True)['already_complete'])
        self.assertEqual((revision/'build-receipt.json').stat().st_mtime_ns, stamp)
        # The portable project must verify after its original artwork is gone.
        (self.root/'actor.png').unlink()
        self.assertEqual(shots.verify_project(revision)['status'], 'verified')
        portable = shots.read_json(revision/'project.json')
        portable['audio']['tones'][0][2] = 880
        shots.save(revision/'project.json', portable)
        with self.assertRaisesRegex(ValueError, 'Completed project changed'):
            shots.verify_project(revision)
