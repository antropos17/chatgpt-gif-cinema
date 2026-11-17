"""Static-stage reuse must change cost, not pixels, clocks or live recipe edits."""
import copy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFilter
from gif_cinema import shots
from gif_cinema.shot_project import load_project
from gif_cinema.shot_renderer import Renderer
from test_native_shots import fixture


class UncachedRenderer(Renderer):
    """Independent original stage calculation; never uses the optimized cache."""
    def _background_with_shadows(self):
        stage = self.background.copy()
        shade = Image.new('RGBA', self.size)
        draw = ImageDraw.Draw(shade)
        for shadow in self.project['shadows']:
            x, y = shadow['xy']; rx, ry = shadow['radius']
            draw.ellipse((x-rx, y-ry, x+rx, y+ry), fill=tuple(shadow['color']))
        return Image.alpha_composite(stage.convert('RGBA'),
            shade.filter(ImageFilter.GaussianBlur(self.project['shadow_blur']))).convert('RGB')


class StaticStageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.project = fixture(self.root)
        self.project['shadows'] = [
            {'xy': [8, 10], 'radius': [6, 3], 'color': [190, 20, 60, 170]},
            {'xy': [10, 13], 'radius': [5, 2], 'color': [10, 90, 20, 90]}]
        self.project['shadow_blur'] = 1.25
        self.project['effects'] = [dict(type='ambient', plane=plane,
            particles=[[10, 11, 2, .3]], drift=.5, speed=[1, 2], color=[30, 70, 60],
            strength=[.4, .3], flicker=2) for plane in ('front', 'behind')]
        self.path = self.root/'project.json'

    def renderers(self):
        self.path.write_text(json.dumps(self.project), encoding='utf-8')
        value, paths = load_project(self.path)
        return value, Renderer(value, paths), UncachedRenderer(copy.deepcopy(value), paths)

    def test_exact_pixels_with_shadows_actors_occlusion_cuts_and_nonmonotonic_time(self):
        value, cached, original = self.renderers()
        before = copy.deepcopy(value)
        for time in (0, .04, .12, .16, .28, .08, .28):
            for scene in value['scenes']:
                for gain in (0, .5, 1, 2):
                    view = {**scene, 'effects': {'gain': gain}, 'camera': [2, 1, 14, 15]}
                    self.assertEqual(cached.frame(time, view).tobytes(), original.frame(time, view).tobytes())
        self.assertEqual(value, before)

    def test_cached_stage_and_original_background_are_not_painted_or_returned(self):
        value, renderer, original = self.renderers()
        stage = renderer._shadowed_background
        pixels, back = stage.tobytes(), renderer.background.tobytes()
        for t in (0, .12, .04):
            result = renderer.frame(t, value['scenes'][0])
            result.paste('white', (0, 0, *result.size))
            self.assertIs(stage, renderer._shadowed_background)
            self.assertEqual(stage.tobytes(), pixels)
            self.assertEqual(renderer.background.tobytes(), back)
        self.assertEqual(renderer.frame(0, value['scenes'][0]).tobytes(), original.frame(0, value['scenes'][0]).tobytes())

    def test_in_place_shadow_edits_invalidate_and_match_uncached(self):
        value, renderer, _ = self.renderers()
        changes = [lambda p: p['shadows'][0]['xy'].__setitem__(0, 3),
                   lambda p: p['shadows'][0]['radius'].__setitem__(0, 2),
                   lambda p: p['shadows'][0]['color'].__setitem__(3, 50),
                   lambda p: p.__setitem__('shadow_blur', 0),
                   lambda p: p['shadows'].reverse(),
                   lambda p: p['shadows'].clear()]
        paths = load_project(self.path)[1]
        for change in changes:
            previous = renderer._shadowed_background
            change(value)
            expected = UncachedRenderer(value, paths)
            self.assertEqual(renderer.frame(.12, value['scenes'][0]).tobytes(), expected.frame(.12, value['scenes'][0]).tobytes())
            self.assertIsNot(previous, renderer._shadowed_background)

    def test_empty_or_transparent_shadows_and_dynamic_recipe_change(self):
        for shadows in ([], [{'xy': [8, 8], 'radius': [6, 6], 'color': [255, 0, 0, 0]}]):
            self.project['shadows'] = shadows
            value, renderer, original = self.renderers()
            stage = renderer._shadowed_background
            self.assertEqual(stage.tobytes(), renderer.background.tobytes())
            for t in (0, .12):
                value['effects'][0]['strength'] = [1, 0]
                original.project['effects'][0]['strength'] = [1, 0]
                self.assertEqual(renderer.frame(t, value['scenes'][0]).tobytes(), original.frame(t, value['scenes'][0]).tobytes())
                self.assertIs(stage, renderer._shadowed_background)

    @unittest.skipUnless(shutil.which('ffmpeg') and importlib.util.find_spec('av'), 'FFmpeg/PyAV required')
    def test_real_lossless_export_pixels_pts_holds_audio_and_portable_verification(self):
        import av
        value, _, reference = self.renderers()
        source = self.path.read_bytes()
        with patch('socket.socket', side_effect=AssertionError('No network')):
            out = self.root/'output'
            shots.build_project(self.path, out)
            self.assertEqual(shots.verify_project(out)['status'], 'verified')
        receipt = shots.read_json(out/'build-receipt.json')
        for scene in value['scenes']:
            record = receipt['completed'][scene['id']]
            with av.open(str(out/record['file'])) as stream:
                decoded = list(stream.decode(video=0))
            self.assertEqual(len(decoded), scene['end_frame']-scene['start_frame'])
            for n, frame in enumerate(decoded):
                self.assertEqual(frame.pts*frame.time_base, Fraction(n, value['fps']))
                self.assertEqual(frame.duration*frame.time_base, Fraction(1, value['fps']))
                expected = reference.frame((scene['start_frame']+n)/value['fps'], scene)
                self.assertEqual(frame.to_image().convert('RGB').tobytes(), expected.tobytes())
        reference.sound(self.root/'reference.wav')
        self.assertEqual((self.root/'reference.wav').read_bytes(), (out/receipt['ready']['audio']).read_bytes())
        self.assertEqual(source, self.path.read_bytes())


if __name__ == '__main__':
    unittest.main()
