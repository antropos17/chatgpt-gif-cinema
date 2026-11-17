"""Exact RGB empty-plane fast path versus the prior unconditional frame method."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter
from gif_cinema.shot_project import load_project
from gif_cinema.shot_renderer import Renderer
from test_native_shots import fixture


class AlwaysFilterRenderer(Renderer):
    """Unchanged frame method from e4d9e7d, not the optimized implementation."""
    def frame(self, t, scene):
        p = self.project
        im = self._background_with_shadows().copy()
        self.actors(im, t)
        front_core, front_glow = self.lights([e for e in p['effects'] if e['plane'] == 'front'], t)
        core, glow = self.lights([e for e in p['effects'] if e['plane'] == 'behind'], t)
        gain = scene['effects']['gain']
        if gain != 1:
            core = ImageEnhance.Brightness(core).enhance(gain)
            glow = ImageEnhance.Brightness(glow).enhance(gain)
        occlusion = ImageChops.difference(im, self.background).convert('L').point(
            lambda v: 255 if v > p['occlusion_threshold'] else 0).filter(ImageFilter.GaussianBlur(p['occlusion_blur']))
        glow = glow.filter(ImageFilter.GaussianBlur(p['glow_blur']))
        glow.paste((0, 0, 0), (0, 0, *self.size), occlusion)
        core.paste((0, 0, 0), (0, 0, *self.size), occlusion)
        im = ImageChops.add(ImageChops.add(im, glow), core)
        im = ImageChops.add(ImageChops.add(im, front_glow.filter(ImageFilter.GaussianBlur(p['glow_blur']))), front_core)
        overlay = Image.new('RGBA', self.size); draw = ImageDraw.Draw(overlay)
        for e in p['overlays']:
            for x, y, speed, phase in e['particles']:
                xx = (x+t*speed) % e['wrap']-e['offset']; yy = y+math.sin(t*e['speed']+phase)*e['amplitude']
                r = e['radius'][0]+speed/e['radius'][1]
                draw.ellipse((xx-r, yy-r*e['aspect'], xx+r, yy+r*e['aspect']), fill=tuple(e['color']))
        im = Image.alpha_composite(im.convert('RGBA'), overlay).convert('RGB')
        box = scene['camera']; push = p['camera_push']
        z = 1+push['amplitude']*math.sin(t*push['speed'])
        cx, cy = (box[0]+box[2])/2, (box[1]+box[3])/2
        bw, bh = (box[2]-box[0])/z, (box[3]-box[1])/z
        return im.crop((cx-bw/2, cy-bh/2, cx+bw/2, cy+bh/2)).resize(self.size, Image.Resampling.LANCZOS)


class EmptyLightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.value = fixture(self.root)
        self.value['occlusion_blur'] = 1.25
        self.value['glow_blur'] = 1.5
        self.path = self.root/'source.json'

    def pair(self):
        self.path.write_text(json.dumps(self.value))
        value, paths = load_project(self.path)
        return Renderer(value, paths), AlwaysFilterRenderer(copy.deepcopy(value), paths)

    def ambient(self, plane='behind', color=(30, 80, 110), strength=1, radius=2, xy=(12, 12)):
        return dict(type='ambient', plane=plane, particles=[[*xy, radius, .3]],
                    drift=.5, speed=[1, 2], color=list(color), strength=[strength, 0], flicker=2)

    def test_no_effects_skips_all_dynamic_blurs_and_preserves_pixels(self):
        current, previous = self.pair()
        source_filter = Image.Image.filter
        counts = []
        for renderer in (previous, current):
            calls = []
            def count(image, filter):
                if isinstance(filter, ImageFilter.GaussianBlur): calls.append(image.mode)
                return source_filter(image, filter)
            with patch.object(Image.Image, 'filter', count):
                frame = renderer.frame(.12, renderer.project['scenes'][0])
            counts.append((calls, frame.tobytes()))
        self.assertEqual(counts[0][0], ['L', 'RGB', 'RGB'])
        self.assertEqual(counts[1][0], [])
        self.assertEqual(counts[0][1], counts[1][1])

    def test_nonblank_gain_occlusion_and_out_of_order_times_match(self):
        for planes in (('front',), ('behind',), ('front', 'behind')):
            self.value['effects'] = [self.ambient(plane) for plane in planes]
            self.value['shadows'] = [dict(xy=[9, 12], radius=[5, 3], color=[90, 20, 0, 130])]
            self.value['shadow_blur'] = 1
            current, previous = self.pair()
            for t in (0, .12, .04, .28, .12):
                for gain in (0, .001, .5, 1, 2):
                    scene = {**current.project['scenes'][0], 'effects': {'gain': gain}, 'camera': [1, 1, 15, 16]}
                    self.assertEqual(current.frame(t, scene).tobytes(), previous.frame(t, scene).tobytes())

    def test_all_independent_core_glow_channels_including_one_valued_blue(self):
        self.value['occlusion_blur'] = self.value['glow_blur'] = 0
        current, previous = self.pair()
        # front core/glow, behind core/glow, independently blank or nonblank.
        for bits in range(16):
            for color in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (255, 250, 254)):
                planes = []
                for i in range(4):
                    plane = Image.new('RGB', (16, 16))
                    if bits & (1<<i): plane.putpixel((12, 12), color)
                    planes.append(plane)
                results = []
                for renderer in (previous, current):
                    values = [(planes[0].copy(), planes[1].copy()), (planes[2].copy(), planes[3].copy())]
                    with patch.object(renderer, 'lights', side_effect=values):
                        results.append(renderer.frame(0, renderer.project['scenes'][0]))
                self.assertEqual(results[0].tobytes(), results[1].tobytes())
                if bits:
                    self.assertNotEqual(results[1].getpixel((12, 12)), (0, 0, 0))

    def test_black_color_is_not_an_activity_predicate_white_center_survives(self):
        self.value['effects'] = [self.ambient('front', color=(0, 0, 0), radius=4)]
        current, previous = self.pair()
        core, glow = current.lights(current.project['effects'], 0)
        self.assertIsNotNone(core.getbbox())
        self.assertIsNone(glow.getbbox())
        self.assertEqual(current.frame(0, current.project['scenes'][0]).tobytes(), previous.frame(0, previous.project['scenes'][0]).tobytes())

    def test_actual_off_canvas_and_quantized_blank_effects_match(self):
        for effect in (self.ambient(xy=(1000, 1000)), self.ambient(strength=0),
                       self.ambient(color=(1, 1, 1), strength=.001)):
            self.value['effects'] = [effect]
            current, previous = self.pair()
            core, glow = current.lights(current.project['effects'], 0)
            self.assertIsNone(core.getbbox()); self.assertIsNone(glow.getbbox())
            self.assertEqual(current.frame(0, current.project['scenes'][0]).tobytes(), previous.frame(0, previous.project['scenes'][0]).tobytes())

    def test_live_parameter_changes_have_no_stale_decision(self):
        self.value['effects'] = [self.ambient()]
        current, previous = self.pair()
        mutations = [lambda p: p['effects'][0].update(strength=[0, 0]),
                     lambda p: p['effects'][0].update(strength=[1, 0], plane='front'),
                     lambda p: p.update(glow_blur=0),
                     lambda p: p.update(occlusion_blur=0, occlusion_threshold=255),
                     lambda p: p['effects'][0].update(plane='behind'),
                     lambda p: p['shadows'].append(dict(xy=[8, 9],radius=[4, 2],color=[0,0,0,100])),
                     lambda p: p['effects'].clear()]
        for mutation in mutations:
            mutation(current.project); mutation(previous.project)
            self.assertEqual(current.frame(.12,current.project['scenes'][0]).tobytes(),previous.frame(.12,previous.project['scenes'][0]).tobytes())

    def test_burst_start_end_and_fractional_gain_rounding(self):
        self.value['effects'] = [dict(type='burst', plane='behind', start=.08, duration=.16,
            xy=[12,12],radius=1,speed=3,aspect=1,color=[100,200,90],width=1,count=3,
            angle=.2,scatter=[4,5],particle_radius=1)]
        current, previous = self.pair()
        for t in (0, .079999, .08, .080001, .12, .239999, .24, .240001, .08):
            for gain in (0, .0001, .5, 1, 2):
                scene={**current.project['scenes'][0],'effects':{'gain':gain}}
                self.assertEqual(current.frame(t,scene).tobytes(),previous.frame(t,scene).tobytes())
