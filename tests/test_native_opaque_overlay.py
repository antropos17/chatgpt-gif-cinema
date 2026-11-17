"""Opaque RGB source-over equivalence; transparent canvases keep the old path."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import random
import shutil
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from gif_cinema import shot_renderer, shots
from gif_cinema.shot_project import load_project
from test_native_shots import fixture


def original(image, overlay):
    return Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')


class OpaqueOverlayTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def test_every_channel_source_destination_alpha_combination(self):
        # All 256^3 channel cases, not just a tolerance or perceptual score.
        dst = Image.frombytes('L', (256, 256), bytes(range(256))*256)
        src = Image.frombytes('L', (256, 256), bytes(y for y in range(256) for _ in range(256)))
        background = Image.merge('RGB', (dst, dst, dst))
        for alpha in range(256):
            overlay = Image.merge('RGBA', (src, src, src, Image.new('L', src.size, alpha)))
            with self.subTest(alpha=alpha):
                self.assertEqual(shot_renderer._composite_overlay(background.copy(), overlay).tobytes(),
                                 original(background, overlay).tobytes())

    def test_random_rgb_channels_hidden_colors_and_alpha_edges(self):
        rng = random.Random(3816)
        for size in ((1, 1), (1, 257), (257, 1), (63, 97), (256, 256)):
            background = Image.frombytes('RGB', size, rng.randbytes(size[0]*size[1]*3))
            overlay = Image.frombytes('RGBA', size, rng.randbytes(size[0]*size[1]*4))
            for alpha in (None, 0, 1, 127, 128, 254, 255):
                if alpha is not None: overlay.putalpha(alpha)
                before = overlay.tobytes()
                actual = shot_renderer._composite_overlay(background.copy(), overlay)
                self.assertEqual(actual.tobytes(), original(background, overlay).tobytes())
                self.assertEqual(overlay.tobytes(), before)

    def test_owned_frame_only_is_mutated_and_metadata_is_kept(self):
        frame = Image.new('RGB', (9, 7), (20, 90, 110)); frame.info['label'] = 'owned'
        overlay = Image.new('RGBA', frame.size, (90, 20, 100, 127)); before = overlay.tobytes()
        expected = original(frame, overlay)
        actual = shot_renderer._composite_overlay(frame, overlay)
        self.assertIs(actual, frame); self.assertEqual(actual.tobytes(), expected.tobytes())
        self.assertEqual(actual.info, expected.info); self.assertEqual(overlay.tobytes(), before)

    def test_transparent_destinations_and_rgb_color_key_use_original_path(self):
        for mode in ('RGBA', 'RGB', 'P', 'L'):
            frame = Image.new(mode, (9, 7)); overlay = Image.new('RGBA', frame.size, (200, 100, 40, 128))
            if mode == 'RGB':
                frame.paste((100, 20, 30), (0, 0, *frame.size)); frame.info['transparency'] = (100, 20, 30)
            before = frame.tobytes(); actual = shot_renderer._composite_overlay(frame, overlay)
            self.assertEqual(actual.tobytes(), original(frame, overlay).tobytes())
            self.assertEqual(frame.tobytes(), before); self.assertIsNot(actual, frame)

    def test_size_mismatch_retains_the_original_error(self):
        with self.assertRaises(ValueError):
            shot_renderer._composite_overlay(Image.new('RGB', (8, 8)), Image.new('RGBA', (7, 8)))

    def scene(self, *, color_key=False):
        value = fixture(self.root)
        background = Image.new('RGB', (64, 48), (30, 50, 70))
        background.save(self.root/'back.png', **({'transparency': (30, 50, 70)} if color_key else {}))
        raw = (self.root/'back.png').read_bytes()
        value['files']['back.png'].update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        value['width'], value['height'] = 64, 48
        value['shadows'] = [dict(xy=[20, 20], radius=[7, 5], color=[30, 10, 90, 127])]
        value['shadow_blur'] = 1
        value['camera_push'] = dict(amplitude=.015, speed=.7)
        value['effects'] = [dict(type='ambient', plane=plane, particles=[[25, 20, 2, .3]],
            drift=2, speed=[1, 2], color=[130, 160, 190], strength=[.6, .2], flicker=2)
            for plane in ('front', 'behind')]
        value['overlays'] = [dict(type='petals', particles=[[4, 7, 5, .2], [7, 7, 4, .1], [61, 47, 3, .5], [-20, 90, 3, .1]],
            wrap=80, offset=8, speed=.9, amplitude=3, radius=[3, 18], aspect=.4, color=[245, 155, 183, 120])]
        for scene in value['scenes']: scene['camera'] = [0, 0, 64, 48]
        path = self.root/'project.json'; path.write_text(json.dumps(value)); return path

    def test_real_renderer_camera_gain_live_edits_and_source_ownership(self):
        value, paths = load_project(self.scene()); renderer = shot_renderer.Renderer(value, paths)
        back = renderer.background.tobytes()
        tiles = {k: [(a.tobytes(), b.tobytes()) for a, b in frames] for k, frames in renderer.clips.items()}
        for alpha in (0, 1, 128, 255):
            value['overlays'][0]['color'][3] = alpha
            for t in (0, .04, .28, .12, .04):
                for gain in (0, .5, 1, 2):
                    scene = {**value['scenes'][0], 'effects': {'gain': gain}, 'camera': [1, 1, 63, 47]}
                    before = copy.deepcopy(value)
                    actual = renderer.frame(t, scene)
                    with patch.object(shot_renderer, '_composite_overlay', original): expected = renderer.frame(t, scene)
                    self.assertEqual(actual.tobytes(), expected.tobytes()); self.assertEqual(value, before)
                    actual.paste('magenta', (0, 0, *actual.size))
        self.assertEqual(renderer.background.tobytes(), back)
        self.assertEqual({k: [(a.tobytes(), b.tobytes()) for a, b in frames] for k, frames in renderer.clips.items()}, tiles)
        value['overlays'] = []
        actual = renderer.frame(.12, value['scenes'][0])
        with patch.object(shot_renderer, '_composite_overlay', original): expected = renderer.frame(.12, value['scenes'][0])
        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_no_overlays_allocates_no_rgba_plane_and_keeps_camera_output(self):
        for color_key in (False, True):
            value, paths = load_project(self.scene(color_key=color_key)); value['overlays'] = []
            renderer = shot_renderer.Renderer(value, paths)
            ordinary = Image.new; modes = []
            def created(mode, *args, **kwargs):
                modes.append(mode); return ordinary(mode, *args, **kwargs)
            with patch.object(Image, 'new', created), patch.object(shot_renderer, '_composite_overlay', side_effect=AssertionError('no overlay operation')):
                actual = renderer.frame(.12, value['scenes'][0])
            self.assertNotIn('RGBA', modes)
            # A zero-particle overlay still exercises the original compositing path.
            value['overlays'] = [dict(type='petals', particles=[], wrap=80, offset=8,
                speed=.9, amplitude=3, radius=[3,18], aspect=.4, color=[245,155,183,120])]
            with patch.object(shot_renderer, '_composite_overlay', original):
                expected = renderer.frame(.12, value['scenes'][0])
            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_color_key_source_background_is_not_mistaken_for_opaque_input(self):
        value, paths = load_project(self.scene(color_key=True)); renderer = shot_renderer.Renderer(value, paths)
        for t in (0, .12, .28):
            actual = renderer.frame(t, value['scenes'][0])
            with patch.object(shot_renderer, '_composite_overlay', original): expected = renderer.frame(t, value['scenes'][0])
            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_benchmark_rejects_unpinned_code_before_execution(self):
        path = Path(__file__).resolve().parents[1]/'tools/benchmark_opaque_overlay.py'
        spec = importlib.util.spec_from_file_location('overlay_benchmark', path)
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        bad = self.root/'bad.py'; bad.write_text('raise AssertionError("must not run")')
        with self.assertRaisesRegex(ValueError, 'exact 3ace165'): tool.reference(bad)

    @unittest.skipUnless(shutil.which('ffmpeg') and importlib.util.find_spec('av'), 'FFmpeg and PyAV required')
    def test_real_export_keeps_all_rgb_pts_holds_pcm_and_movie_bytes(self):
        source = self.scene()
        for label, optimized in (('before', False), ('after', True)):
            with contextlib.ExitStack() as stack:
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                if not optimized: stack.enter_context(patch.object(shot_renderer, '_composite_overlay', original))
                shots.build_project(source, self.root/label)
        from tools.benchmark_opaque_overlay import decoded
        a = shots.read_json(self.root/'before/build-receipt.json'); b = shots.read_json(self.root/'after/build-receipt.json')
        self.assertEqual(decoded(self.root/'before', a), decoded(self.root/'after', b))
        self.assertEqual((self.root/'before'/a['ready']['audio']).read_bytes(), (self.root/'after'/b['ready']['audio']).read_bytes())
        self.assertEqual((self.root/'before/film.mp4').read_bytes(), (self.root/'after/film.mp4').read_bytes())
        self.assertEqual(shots.verify_project(self.root/'after')['status'], 'verified')
