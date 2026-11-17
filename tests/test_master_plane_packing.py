"""Straight BGRA, row padding, ownership and exact master timing stay unchanged."""
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
import wave
from PIL import Image, ImageFile
from gif_cinema import master
try: import av
except ImportError: av=None


def legacy(av,image):
    frame=av.VideoFrame(image.width,image.height,'bgra');plane=frame.planes[0]
    raw=image.tobytes('raw','BGRA');data=bytearray(plane.buffer_size);row=image.width*4
    for y in range(image.height):data[y*plane.line_size:y*plane.line_size+row]=raw[y*row:(y+1)*row]
    plane.update(data);return frame


def gif(path,size=(25,21),disposal=2):
    frames=[]
    for n in range(3):
        im=Image.new('RGBA',size,(19,71,129,0))
        for x in range(3):im.putpixel((n*3+x, min(10,size[1]-1)),(90+n*70,12+n,200,255))
        frames.append(im)
    frames[0].save(path,save_all=True,append_images=frames[1:],duration=[10,30,150],disposal=disposal,transparency=0,optimize=False)


@unittest.skipUnless(av,'PyAV required')
class PlanePackingTests(unittest.TestCase):
    def equal(self,image):
        original=image.tobytes();before=legacy(av,image);after=master.video_frame(av,image)
        self.assertEqual(bytes(after.planes[0]),bytes(before.planes[0]))
        self.assertEqual(master.rgba_frame(after).tobytes(),original)
        self.assertEqual(image.tobytes(),original);self.assertEqual(after.pts,before.pts)
        self.assertEqual(after.time_base,before.time_base);self.assertEqual(after.duration,before.duration)
        return after

    def test_randomized_sizes_all_channels_alpha_and_zero_padding(self):
        rng=random.Random(943)
        for w in (1,2,7,8,24,25,31,32,63,64,65,127,128,129,640,641):
            for h in (1,3,17):
                im=Image.frombytes('RGBA',(w,h),rng.randbytes(w*h*4))
                with self.subTest(size=im.size):
                    frame=self.equal(im);plane=frame.planes[0];raw=bytes(plane)
                    for y in range(h):self.assertEqual(raw[y*plane.line_size+w*4:(y+1)*plane.line_size],b'\0'*(plane.line_size-w*4))

    def test_every_alpha_and_hidden_rgb_are_not_premultiplied(self):
        im=Image.new('RGBA',(257,2))
        for a in range(256):im.putpixel((a,0),((a*7)%256,(a*11)%256,255-a,a))
        im.putpixel((256,1),(253,97,221,0));self.equal(im)

    def test_packed_frame_and_source_have_independent_ownership(self):
        im=Image.new('RGBA',(65,3),(2,47,199,123));original=im.tobytes();frame=self.equal(im)
        im.paste((255,0,0,0),(0,0,*im.size));self.assertEqual(master.rgba_frame(frame).tobytes(),original)
        snapshot=im.tobytes();frame.planes[0].update(b'\0'*frame.planes[0].buffer_size);self.assertEqual(im.tobytes(),snapshot)

    def test_unknown_pillow_strides_and_small_raw_buffers_use_legacy_fallback(self):
        im=Image.new('RGBA',(65,3),(1,99,231,128));expected=bytes(legacy(av,im).planes[0]);ordinary=Image.Image.tobytes
        for config in ('unknown','small-buffer'):
            calls=[]
            def count(image,*args,**kwargs):calls.append(args);return ordinary(image,*args,**kwargs)
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(Image.Image,'tobytes',count))
                stack.enter_context(patch.object(master,'PILLOW_VERSION','future') if config=='unknown' else patch.object(ImageFile,'MAXBLOCK',64))
                actual=master.video_frame(av,im)
            self.assertEqual(bytes(actual.planes[0]),expected);self.assertEqual(calls,[('raw','BGRA')])

    def test_eligible_packed_and_strided_paths_do_not_allocate_row_bytearray(self):
        for size in [(64,3),(65,3)]:
            im=Image.new('RGBA',size,(22,101,3,0));plane=legacy(av,im).planes[0];expected=bytes(plane)
            packed=plane.line_size==size[0]*4 and plane.buffer_size==size[0]*size[1]*4
            strided=(master.PILLOW_VERSION in ('10.1.0','13.0.0') and plane.line_size<=max(ImageFile.MAXBLOCK,size[0]*4))
            with contextlib.ExitStack() as stack:
                if packed or strided:stack.enter_context(patch.object(master,'bytearray',side_effect=AssertionError('unnecessary row buffer'),create=True))
                actual=master.video_frame(av,im)
            self.assertEqual(bytes(actual.planes[0]),expected)

    def test_nonstandard_extra_tail_allocations_keep_all_zero_filled_bytes(self):
        class Plane:
            def __init__(self,stride,size):self.line_size=stride;self.buffer_size=size
            def update(self,data):self.data=bytes(data);assert len(data)==self.buffer_size
        class Frame:
            def __init__(self,stride,size):self.planes=[Plane(stride,size)]
        class AV:
            def __init__(self,stride,size):self.stride,self.size=stride,size
            def VideoFrame(self,w,h,fmt):self.format=fmt;return Frame(self.stride,self.size)
        im=Image.new('RGBA',(25,3),(9,2,81,0))
        for stride in (100,128):
            api=AV(stride,stride*3+19);before=legacy(api,im);after=master.video_frame(api,im)
            self.assertEqual(after.planes[0].data,before.planes[0].data);self.assertEqual(after.planes[0].data[-19:],b'\0'*19)

    def test_same_canvas_hash_reuse_and_padding_still_match_source(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'a.gif';gif(source);ordinary=master.factory.digest
            for canvas,expected in ((None,3),((26,22),6)):
                report=master.plan([source],canvas=canvas);calls=[]
                def digest(raw):calls.append(len(raw));return ordinary(raw)
                target=root/('same.mkv' if canvas is None else 'padded.mkv')
                with patch.object(master.factory,'digest',digest):master.encode_master([source],target,report)
                self.assertEqual(len(calls),expected);self.assertEqual(master.verify_master(target,report)['frames'],3)
                self.assertEqual(report['frames'][-1]['duration_cs'],15)

    def test_changed_packed_pixels_still_fail_before_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'a.gif';gif(source);out=root/'out';ordinary=master.video_frame
            def bad(api,image):return ordinary(api,Image.new('RGBA',image.size,(0,0,0,0)))
            with patch.object(master,'video_frame',bad),self.assertRaisesRegex(ValueError,'RGBA mismatch'):master.build([source],out)
            self.assertFalse(out.exists())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_disposal_mixed_sizes_preview_audio_and_final_holds_match(self):
        from tools.benchmark_master_packing import signature
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);paths=[]
            for n,disposal in enumerate((1,2,3)):
                path=root/f'{n}.gif';gif(path,(24+n,21+n),disposal);paths.append(path)
            before=[p.read_bytes() for p in paths];audio=root/'sound.wav'
            with wave.open(str(audio),'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000);stream.writeframes(b'\0\0\1\0'*800)
            results=[]
            for label in ('before','after'):
                with contextlib.ExitStack() as stack:
                    if label=='before':stack.enter_context(patch.object(master,'video_frame',legacy))
                    report=master.build(paths,root/label,preview=True,audio=audio)
                self.assertEqual(report['verification']['duration_ms'],570);self.assertEqual(report['viewing_copy']['frames'],57)
                results.append((signature(root/label/'master.mkv'),(root/label/'preview.mp4').read_bytes(),report['frames']))
            self.assertEqual(results[0],results[1]);self.assertEqual(before,[p.read_bytes() for p in paths])

    def test_benchmark_refuses_unpinned_code(self):
        path=Path(__file__).resolve().parents[1]/'tools/benchmark_master_packing.py'
        spec=importlib.util.spec_from_file_location('packing_benchmark',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'bad.py';source.write_text('raise AssertionError("must not execute")')
            with self.assertRaisesRegex(ValueError,'exact e4853eb'):module.reference(source)
