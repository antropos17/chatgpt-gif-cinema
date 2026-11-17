"""Exact sparse Gaussian filtering, with full-image fallback as the oracle."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import random
import shutil
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw, ImageFilter
from gif_cinema import shot_renderer, shots
from gif_cinema.shot_renderer import Renderer, _bounded_blur
from gif_cinema.shot_project import load_project
from test_native_shots import fixture


def full(image,radius,bounds=None):
    return image.filter(ImageFilter.GaussianBlur(radius))


class BoundedBlurTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name).resolve()

    def equal(self,image,radius):
        before=image.tobytes();info=copy.deepcopy(image.info)
        expected=full(image,radius);actual=_bounded_blur(image,radius)
        self.assertEqual(actual.tobytes(),expected.tobytes())
        self.assertEqual(actual.mode,expected.mode);self.assertEqual(actual.size,expected.size)
        self.assertEqual(actual.info,expected.info)
        self.assertEqual(image.tobytes(),before);self.assertEqual(image.info,info)

    def test_randomized_sparse_planes_radii_edges_and_tiny_canvases(self):
        rng=random.Random(7254)
        for mode in ('RGB','L'):
            for radius in (0,.00001,.1,.5,.999999,1,1.000001,2.49,8,19.9,63.999999,64):
                for size in ((1,1),(1,400),(400,1),(39,17),(320,240)):
                    image=Image.new(mode,size)
                    for _ in range(6):
                        x=rng.randrange(min(20,size[0]));y=rng.randrange(min(20,size[1]))
                        image.putpixel((x,y),rng.randint(1,255) if mode=='L' else tuple(rng.randint(0,255) for _ in range(3)))
                    with self.subTest(mode=mode,radius=radius,size=size):self.equal(image,radius)

    def test_every_corner_edge_and_one_valued_blue_are_preserved(self):
        for xy in ((0,0),(399,0),(0,299),(399,299),(200,0),(200,299),(0,150),(399,150),(200,150)):
            for color in ((0,0,1),(1,0,0),(0,1,0),(255,250,254)):
                for radius in (.1,1.5,4.01,8):
                    image=Image.new('RGB',(400,300));image.putpixel(xy,color)
                    self.equal(image,radius)

    def test_actual_cropped_filter_and_metadata_remain_independent(self):
        image=Image.new('RGB',(400,300));ImageDraw.Draw(image).rectangle((190,140,210,160),fill='white')
        image.info={'test':{'kind':'original'}}
        # Unqualified Pillow releases deliberately retain the exact full filter.
        # Python 3.10 currently resolves Pillow 12.x rather than the 13.0 branch.
        for version in (shot_renderer.PIL.__version__,'12.3.0'):
            calls=[];original=Image.Image.filter
            def counted(im,op):calls.append(im.size);return original(im,op)
            with patch.object(shot_renderer.PIL,'__version__',version),patch.object(Image.Image,'filter',counted):
                actual=_bounded_blur(image,3)
            expected=(45,45) if version in ('10.1.0','13.0.0') else image.size
            self.assertEqual(calls,[expected],version)
            self.assertEqual(actual.tobytes(),full(image,3).tobytes())
            self.assertEqual(actual.info,image.info);self.assertIsNot(actual.info,image.info)

    def test_dense_opposite_edges_and_large_padding_use_full_filter(self):
        for mode in ('RGB','L'):
            for kind in ('dense','corners','padding'):
                image=Image.new(mode,(100,80), 120 if kind=='dense' else 0)
                if kind=='corners':
                    image.putpixel((0,0),255 if mode=='L' else (1,2,3))
                    image.putpixel((99,79),255 if mode=='L' else (1,2,3))
                elif kind=='padding':image.putpixel((50,40),255 if mode=='L' else (1,2,3))
                radius=64 if kind=='padding' else 2
                calls=[];original=Image.Image.filter
                def counted(im,op):calls.append(im.size);return original(im,op)
                with patch.object(Image.Image,'filter',counted):actual=_bounded_blur(image,radius)
                self.assertEqual(calls,[image.size]);self.assertEqual(actual.tobytes(),full(image,radius).tobytes())

    def test_unknown_versions_modes_and_radius_types_keep_original_path(self):
        for version in ('14.0.0','13.0.1','12.0.0','10.1.0.dev0'):
            image=Image.new('RGB',(100,100));image.putpixel((50,50),(1,2,3))
            calls=[];original=Image.Image.filter
            def counted(im,op):calls.append(im.size);return original(im,op)
            with patch.object(shot_renderer.PIL,'__version__',version),patch.object(Image.Image,'filter',counted):actual=_bounded_blur(image,2)
            self.assertEqual(calls,[image.size]);self.assertEqual(actual.tobytes(),full(image,2).tobytes())
        for mode in ('RGBA','RGBa','CMYK','LA'):
            image=Image.new(mode,(80,60));self.equal(image,2)
        image=Image.new('RGB',(80,60),'white')
        for radius in (65, (2,3), True):self.equal(image,radius)

    def test_empty_planes_return_fresh_exact_copies(self):
        for version in (shot_renderer.PIL.__version__,'12.3.0'):
            for mode in ('RGB','L'):
                image=Image.new(mode,(200,160));image.info={'key':'value'}
                calls=[];original=Image.Image.filter
                def counted(im,op):calls.append(im.size);return original(im,op)
                with patch.object(shot_renderer.PIL,'__version__',version),patch.object(Image.Image,'filter',counted):
                    actual=_bounded_blur(image,4)
                expected=[] if version in ('10.1.0','13.0.0') else [image.size]
                self.assertEqual(calls,expected,version)
                self.assertIsNot(actual,image);self.assertEqual(actual.tobytes(),image.tobytes());self.assertEqual(actual.info,image.info)
                actual.putpixel((0,0),255 if mode=='L' else (1,2,3));self.assertIsNone(image.getbbox())

    def test_live_source_edits_never_reuse_an_old_region(self):
        image=Image.new('RGB',(400,300))
        for xy in ((200,150),(0,0),(399,299),(100,20)):
            image.paste(0,(0,0,*image.size));image.putpixel(xy,(255,220,180));self.equal(image,2.5)

    def scene(self):
        value=fixture(self.root)
        Image.new('RGB',(256,192),'#182028').save(self.root/'back.png')
        raw=(self.root/'back.png').read_bytes();value['files']['back.png'].update(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
        value['width']=256;value['height']=192
        value['occlusion_blur']=2.5;value['glow_blur']=3.1
        value['shadows']=[dict(xy=[35,40],radius=[8,6],color=[0,0,0,130])];value['shadow_blur']=1
        value['effects']=[dict(type='ambient',plane=plane,particles=[[130,90,2,.3]],drift=2,speed=[1,2],color=[130,160,190],strength=[.6,.2],flicker=2) for plane in ('front','behind')]
        for scene in value['scenes']:scene['camera']=[0,0,256,192]
        path=self.root/'project.json';path.write_text(json.dumps(value));return path

    def test_native_renderer_gain_masks_camera_and_live_changes_match(self):
        value,paths=load_project(self.scene());renderer=Renderer(value,paths)
        for t in (0,.04,.12,.28,.04):
            for gain in (0,.0001,.5,1,2):
                scene={**value['scenes'][0],'effects':{'gain':gain},'camera':[1,1,255,191]}
                actual=renderer.frame(t,scene)
                with patch.object(shot_renderer,'_bounded_blur',full):expected=renderer.frame(t,scene)
                self.assertEqual(actual.tobytes(),expected.tobytes())
        for radius in (0,64,.5):
            value['glow_blur']=radius;value['occlusion_blur']=radius
            for xy in ((0,0),(255,191),(100,80)):
                value['effects'][0]['particles'][0][:2]=xy
                actual=renderer.frame(.12,value['scenes'][0])
                with patch.object(shot_renderer,'_bounded_blur',full):expected=renderer.frame(.12,value['scenes'][0])
                self.assertEqual(actual.tobytes(),expected.tobytes())

    def test_benchmark_rejects_unpinned_code_before_execution(self):
        path=Path(__file__).resolve().parents[1]/'tools/benchmark_bounded_blur.py'
        spec=importlib.util.spec_from_file_location('blur_benchmark',path);tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
        bad=self.root/'bad.py';bad.write_text('raise AssertionError("must not run")')
        with self.assertRaisesRegex(ValueError,'exact 4b193d7'):tool.reference(bad)

    @unittest.skipUnless(shutil.which('ffmpeg') and importlib.util.find_spec('av'),'FFmpeg and PyAV required')
    def test_real_movie_and_lossless_frames_keep_bytes_and_clock(self):
        source=self.scene()
        for label,optimized in (('before',False),('after',True)):
            with contextlib.ExitStack() as stack:
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                if not optimized:stack.enter_context(patch.object(shot_renderer,'_bounded_blur',full))
                shots.build_project(source,self.root/label)
        self.assertEqual((self.root/'before/film.mp4').read_bytes(),(self.root/'after/film.mp4').read_bytes())
        from tools.benchmark_bounded_blur import decoded
        a=shots.read_json(self.root/'before/build-receipt.json');b=shots.read_json(self.root/'after/build-receipt.json')
        self.assertEqual(a['audio_sha256'],b['audio_sha256'])
        self.assertEqual(decoded(self.root/'before',a),decoded(self.root/'after',b))
        self.assertEqual(shots.verify_project(self.root/'after')['status'],'verified')
