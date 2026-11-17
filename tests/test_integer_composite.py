"""Exact integer translation bypasses resampling, not authored pixels or clocks."""
import copy
import hashlib
import json
from pathlib import Path
import random
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from gif_cinema import layers
from tools.build_native_anchor_proof import make_scene


class IntegerCompositeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()

    def test_random_crop_and_composite_matches_full_affine_rgba_and_previews(self):
        rng=random.Random(4261)
        for i in range(600):
            size=(rng.randrange(2,45),rng.randrange(2,45));wh=(rng.randrange(1,64),rng.randrange(1,64))
            raster=Image.frombytes('RGBA',wh,rng.randbytes(wh[0]*wh[1]*4))
            mode,method=(('RGBa',Image.Resampling.BICUBIC),('RGBA',Image.Resampling.NEAREST),('RGBa',Image.Resampling.NEAREST))[i%3]
            raster=raster.convert(mode);source=raster.tobytes();x,y=rng.randrange(-75,75),rng.randrange(-75,75)
            matrix=(1,0,-x,0,1,-y);opacity=rng.choice([1,.5,.001,.73])
            a=Image.frombytes('RGBA',size,rng.randbytes(size[0]*size[1]*4));b=a.copy()
            old=raster.transform(size,Image.Transform.AFFINE,matrix,resample=method).convert('RGBA')
            old.putalpha(old.getchannel('A').point(lambda v:round(v*opacity)));a.alpha_composite(old)
            crop,destination=layers._integer_translation(raster,matrix,size,method);new=Image.new('RGBA',size)
            if crop is not None:
                crop.putalpha(crop.getchannel('A').point(lambda v:round(v*opacity)))
                b.alpha_composite(crop,destination);new.paste(crop,destination)
            self.assertEqual(a.tobytes(),b.tobytes(),i);self.assertEqual(old.tobytes(),new.tobytes(),i)
            self.assertEqual(raster.tobytes(),source)

    def test_rgba_bicubic_and_unknown_modes_keep_pillow_conversion_semantics(self):
        for mode in ('RGBA','RGB','L'):
            raster=Image.new(mode,(3,3))
            self.assertIsNone(layers._integer_translation(raster,(1,0,0,0,1,0),(4,4),Image.Resampling.BICUBIC))
        raster=Image.new('RGBA',(3,3),(1,77,201,1))
        old=raster.transform((3,3),Image.Transform.AFFINE,(1,0,0,0,1,0),resample=Image.Resampling.BICUBIC)
        self.assertNotEqual(old.tobytes(),raster.tobytes(),'Bicubic RGBA implicitly premultiplies; never bypass it')

    def test_no_approximate_guard_for_subpixels_scale_shear_or_rotation(self):
        raster=Image.new('RGBa',(8,8))
        for matrix in ((1,0,.001,0,1,0),(1,0,0,0,1,-.5),(1+1e-12,0,0,0,1,0),
                       (1,1e-15,0,0,1,0),(1,0,0,-1e-15,1,0),(0,1,0,-1,0,0)):
            self.assertIsNone(layers._integer_translation(raster,matrix,(32,32),Image.Resampling.BICUBIC))

    def test_invisible_integer_translation_skips_allocations(self):
        raster=Image.new('RGBa',(8,8))
        for x,y in ((32,0),(-8,0),(0,32),(0,-8),(1000000,1000000)):
            with patch.object(raster,'crop',side_effect=AssertionError('No invisible crop')):
                self.assertEqual(layers._integer_translation(raster,(1,0,-x,0,1,-y),(32,32),Image.Resampling.BICUBIC),(None,None))

    def test_large_source_only_converts_visible_intersection(self):
        raster=Image.new('RGBa',(1024,1024),(10,20,30,127))
        crop,offset=layers._integer_translation(raster,(1,0,500,0,1,500),(32,24),Image.Resampling.BICUBIC)
        self.assertEqual(crop.size,(32,24));self.assertEqual(offset,(0,0))

    def prepared(self):
        return layers.prepare_scene(make_scene(self.root/'source'))

    def compare(self,prepared,time,only=None,previews=False):
        left,right={},{}
        with patch.object(layers,'_integer_translation',return_value=None):
            before,bs=layers.render_at(prepared,time,only_layer=only,_layer_previews=left if previews else None)
        after,ast=layers.render_at(prepared,time,only_layer=only,_layer_previews=right if previews else None)
        self.assertEqual(before.tobytes(),after.tobytes());self.assertEqual(bs,ast)
        self.assertEqual(set(left),set(right))
        for key in left:
            self.assertEqual(left[key]['image'].tobytes(),right[key]['image'].tobytes())
            self.assertEqual({k:v for k,v in left[key].items() if k!='image'},{k:v for k,v in right[key].items() if k!='image'})
        return after

    def test_native_pose_attachments_and_isolated_layers_keep_pixels_states_clocks(self):
        prepared=self.prepared();before=copy.deepcopy(prepared['scene'])
        for time in (0,10,20,40,70,80,240,250,440,480):
            self.compare(prepared,time,previews=True)
            for key in ('actor','prop'):self.compare(prepared,time,key,True)
        self.assertEqual(prepared['scene'],before)

    def test_live_raster_and_recipe_edits_are_not_cached(self):
        prepared=self.prepared();first=self.compare(prepared,0)
        prepared['gif_rasters']['actor'][0].putpixel((1,1),(242,5,80,255))
        second=self.compare(prepared,0);self.assertNotEqual(first.tobytes(),second.tobytes())
        prepared['scene']['layers'][0]['keyframes'][0]['opacity']=.7
        self.compare(prepared,0,previews=True)
        prepared['scene']['layers'][0]['keyframes'][0]['x']=.25
        self.compare(prepared,0,previews=True)

    def test_fractional_motion_rotation_zoom_and_mode_edit_keep_fallback(self):
        prepared=self.prepared();parent=prepared['scene']['layers'][0]
        for field,value in (('x',.502),('rotation',17),('zoom',1.2)):
            original=copy.deepcopy(parent['keyframes']);parent['keyframes'][0][field]=value
            self.compare(prepared,0,previews=True);parent['keyframes']=original
        parent['sampling']='smooth' # A live unsupported mode change still uses legacy semantics.
        self.compare(prepared,0,previews=True)

    def test_all_translated_layers_avoid_affine_transform(self):
        prepared=self.prepared()
        with patch.object(Image.Image,'transform',side_effect=AssertionError('Integer translation must not resample')):
            layers.render_at(prepared,0,_layer_previews={})

    def test_preview_candidates_keep_midpoint_ties_and_invisible_intervals(self):
        prepared=self.prepared();before,after={},{}
        for time in range(0,480,40):
            with patch.object(layers,'_integer_translation',return_value=None):layers.render_at(prepared,time,_layer_previews=before)
            layers.render_at(prepared,time,_layer_previews=after)
        for name,candidates in (('before',before),('after',after)):
            out=self.root/name;out.mkdir();metadata=layers._write_layer_previews(candidates,prepared['scene'],out)
            (out/'metadata.json').write_text(json.dumps(metadata,sort_keys=True))
        for p in (self.root/'before').iterdir():self.assertEqual(p.read_bytes(),(self.root/'after'/p.name).read_bytes())

    def test_benchmark_rejects_untrusted_reference_before_execution(self):
        from tools.benchmark_integer_composite import reference
        path=self.root/'not-reference.py';path.write_text("raise RuntimeError('must not execute')")
        with self.assertRaisesRegex(ValueError,'exact layers.py'):reference(path)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_real_export_keeps_every_png_preview_and_encoded_bytes(self):
        path=make_scene(self.root/'source');inputs={p.name:p.read_bytes() for p in path.parent.iterdir()}
        with patch.object(layers,'_integer_translation',return_value=None):before=layers.render_scene(path,self.root/'before')
        after=layers.render_scene(path,self.root/'after')
        for key in ('samples','sprite_timing','attachment_review','gif_delays_ms','layer_previews','loop_review'):
            self.assertEqual(before[key],after[key],key)
        for name in before['outputs']:
            self.assertEqual((self.root/'before'/name).read_bytes(),(self.root/'after'/name).read_bytes(),name)
        self.assertEqual(inputs,{p.name:p.read_bytes() for p in path.parent.iterdir()})
