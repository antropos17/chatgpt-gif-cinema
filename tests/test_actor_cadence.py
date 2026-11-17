"""Exact authored pose boundaries, separate from the codec/container clock."""
import copy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from gif_cinema import shots, shot_renderer
from gif_cinema.shot_project import load_project
from test_native_shots import fixture


class ActorCadenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.value=fixture(self.root)
        self.path=self.root/'project.json'

    def renderer(self,fps=30,duration=.2,origin=0):
        self.value['fps']=fps
        self.value['actors'][0]['tracks'][0].update(loop=True,duration=duration,origin=origin)
        self.path.write_text(json.dumps(self.value));value,paths=load_project(self.path)
        return shot_renderer.Renderer(value,paths)

    def test_decimal_loop_boundary_never_selects_previous_last_pose(self):
        renderer=self.renderer(fps=30)
        for i in range(30):
            expected=(255,0,0) if i%6<=3 else (0,0,255)
            self.assertEqual(renderer.frame(Fraction(i,30),renderer.project['scenes'][0]).getpixel((2,2)),expected,i)
        renderer=self.renderer(fps=10,duration=.1)
        for i in range(10):self.assertEqual(renderer.frame(i/10,renderer.project['scenes'][0]).getpixel((2,2)),(255,0,0),i)

    def test_genuinely_adjacent_times_are_not_epsilon_snapped(self):
        renderer=self.renderer();scene=renderer.project['scenes'][0]
        for t,color in ((Fraction(599999999999,10**12),(0,0,255)),(Fraction(3,5),(255,0,0)),(Fraction(600000000001,10**12),(255,0,0))):
            self.assertEqual(renderer.frame(t,scene).getpixel((2,2)),color)

    def test_all_native_rates_match_rational_authored_reference(self):
        renderer=self.renderer();track=renderer.project['actors'][0]['tracks'][0]
        colors=[(255,0,0),(0,0,255)]
        for fps in range(1,61):
            for origin,duration,first,last,loop in ((-.1,.2,0,1,True),(.1,.3,1,0,True),(-.2,.1,1,1,True),(.1,.2,0,1,False)):
                track.update(origin=origin,duration=duration,first=first,last=last,loop=loop)
                for i in range(fps):
                    t=Fraction(i,fps);phase=t-Fraction(str(origin));period=Fraction(str(duration))
                    if loop:phase-=phase//period*period
                    u=min(Fraction(1),max(Fraction(0),phase/period))
                    # Independent nearest-even integer rounding, not float math.
                    number=first+u*(last-first);q,r=divmod(number.numerator,number.denominator)
                    index=q+(2*r>number.denominator or (2*r==number.denominator and q%2==1))
                    image=Image.new('RGB',(16,16));renderer.actors(image,t)
                    self.assertEqual(image.getpixel((2,2)),colors[index],(fps,origin,duration,i))

    def test_half_open_track_cut_exactly_selects_next_track(self):
        renderer=self.renderer();original=renderer.project['actors'][0]['tracks'][0]
        first={**original,'end':.6,'first':1,'last':1}
        second={**original,'start':.6,'first':0,'last':0}
        renderer.project['actors'][0]['tracks']=[first,second]
        for t,color in ((Fraction(599999999999,10**12),(0,0,255)),(Fraction(3,5),(255,0,0)),(Fraction(1),(0,0,0))):
            image=Image.new('RGB',(16,16));renderer.actors(image,t);self.assertEqual(image.getpixel((2,2)),color)

    def test_float_neighbors_remain_distinct_without_epsilon(self):
        import math
        renderer=self.renderer()
        for t,color in ((math.nextafter(.6,0),(0,0,255)),(.6,(255,0,0)),(math.nextafter(.6,1),(255,0,0))):
            image=Image.new('RGB',(16,16));renderer.actors(image,t);self.assertEqual(image.getpixel((2,2)),color)

    def test_authored_mutations_are_visible_without_a_stale_clock_cache(self):
        renderer=self.renderer();scene=renderer.project['scenes'][0];before=copy.deepcopy(renderer.project)
        self.assertEqual(renderer.frame(Fraction(3,5),scene).getpixel((2,2)),(255,0,0))
        self.assertEqual(renderer.project,before)
        renderer.project['actors'][0]['tracks'][0]['origin']=.05
        self.assertEqual(renderer.frame(Fraction(3,5),scene).getpixel((2,2)),(0,0,255))

    def test_camera_effects_keep_the_previous_float_sampling_clock(self):
        renderer=self.renderer();renderer.project['actors']=[];scene=renderer.project['scenes'][0]
        renderer.project['camera_push']={'amplitude':.02,'speed':1.3}
        actual=renderer.lights;seen=[]
        def lights(effects,t):seen.append(t);self.assertIs(type(t),float);return actual(effects,t)
        with patch.object(renderer,'lights',lights):
            for fps in (3,7,30,60):
                for i in (1,2,17):
                    expected=renderer.frame(i/fps,scene)
                    got=renderer.frame(Fraction(i,fps),scene)
                    self.assertEqual(got.tobytes(),expected.tobytes())
                    self.assertEqual(seen[-1],i/fps)


@unittest.skipUnless(importlib.util.find_spec('av') and shutil.which('ffmpeg'),'PyAV/FFmpeg required')
class ActorCadenceExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()

    def build(self,fps,duration):
        root=self.root/str(fps);root.mkdir();value=fixture(root);value['fps']=fps
        value['actors'][0]['tracks'][0].update(loop=True,duration=duration)
        value['scenes'][0].update(start_frame=0,end_frame=fps//2)
        value['scenes'][1].update(start_frame=fps//2,end_frame=fps)
        path=root/'project.json';path.write_text(json.dumps(value));out=root/'out'
        before={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
        result=shots.build_project(path,out);self.assertEqual(result['status'],'complete')
        rec=shots.read_json(out/'build-receipt.json');colors=[]
        for scene in value['scenes']:
            for i,f in enumerate(shots.video_frames(out/rec['completed'][scene['id']]['file'])):
                shots.verify_video_clock(f,i,fps,(16,16),'Scene')
                image=f.to_image();colors.append(image.getpixel((2,2)))
                # Every non-actor pixel remains the unchanged opaque black stage.
                self.assertEqual(image.crop((8,0,16,16)).getbbox(),None)
        expected=[(255,0,0) if fps==10 or i%6<=3 else (0,0,255) for i in range(fps)]
        self.assertEqual(colors,expected)
        import av
        with av.open(str(out/'film.mp4')) as movie:
            frames=list(movie.decode(video=0))
        self.assertEqual(len(frames),fps)
        for i,(frame,color) in enumerate(zip(frames,expected)):
            shots.verify_video_clock(frame,i,fps,(16,16),'Movie')
            self.assertLessEqual(max(abs(a-b) for a,b in zip(frame.to_image().getpixel((2,2)),color)),8)
        self.assertEqual(shots.verify_project(out)['status'],'verified')
        self.assertTrue(shots.build_project(path,out,resume=True)['already_complete'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir() if p.is_file()})

    def test_real_loop_30fps_crosses_scene_boundary_without_old_pose_hold(self):self.build(30,.2)
    def test_real_10fps_exact_loop_boundary_has_no_spurious_pose(self):self.build(10,.1)


if __name__=='__main__':unittest.main()
