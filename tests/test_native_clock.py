"""Real native container clocks: quantization, final holds and audio coverage."""
import copy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from gif_cinema import shots
from test_native_shots import fixture


def video(pts=0, duration=40, tick=Fraction(1,1000)):
    return NS(width=16,height=16,pts=pts,duration=duration,time_base=tick)


def audio_stream(duration=2560,rate=8000):
    return NS(codec_context=NS(sample_rate=rate,frame_size=1024,name='aac'),channels=2,start_time=0,duration=duration,time_base=Fraction(1,rate))


def audio_frame(pts,samples=1024,rate=8000):
    return NS(pts=pts,time_base=Fraction(1,rate),samples=samples,sample_rate=rate,layout=NS(channels=[0,1]))


class NativeClockUnitTests(unittest.TestCase):
    def test_rational_clock_all_rates_at_long_indices(self):
        for fps in range(1,61):
            for tick in (Fraction(1,1000),Fraction(1,12800),Fraction(1,fps)):
                ticks=Fraction(1,fps)/tick
                for index in (0,1,2,3,17999):
                    at=index*ticks;pts=(2*at.numerator+at.denominator)//(2*at.denominator)
                    for hold in {ticks.numerator//ticks.denominator,-(-ticks.numerator//ticks.denominator)}:
                        shots.verify_video_clock(video(pts,hold,tick),index,fps,(16,16),'test')

    def test_bad_video_times_holds_geometry_and_coarse_fractional_clock(self):
        for field,bad in (('pts',None),('pts',1),('pts',True),('duration',None),('duration',0),
            ('duration',-1),('duration',41),('duration',140),('duration',True),('time_base',None),
            ('time_base',Fraction(0)),('time_base',Fraction(-1,1000)),('time_base',Fraction(1,2)),('width',15)):
            frame=video();setattr(frame,field,bad)
            with self.subTest(field=field,bad=bad),self.assertRaises(ValueError):shots.verify_video_clock(frame,0,25,(16,16),'test')

    def test_one_tick_pts_error_rejected_and_nondivisor_hold_bounded(self):
        for fps in (24,30,32,59,60):
            for hold in (1000//fps, -(-1000//fps)):
                shots.verify_video_clock(video(0,hold),0,fps,(16,16),'test')
            for duration in (1000//fps-1,-(-1000//fps)+1):
                with self.assertRaises(ValueError):shots.verify_video_clock(video(0,duration),0,fps,(16,16),'test')
        with self.assertRaises(ValueError):shots.verify_video_clock(video(34,33),1,30,(16,16),'test')
        shots.verify_video_clock(video(63,31),2,32,(16,16),'test')

    def test_aac_padding_is_not_source_duration_and_input_rate_can_resample(self):
        frames=[audio_frame(i) for i in (0,1024,2048)]
        shots.verify_audio_clock(audio_stream(),iter(frames),Fraction(8,25),8001)
        shots.verify_audio_clock(audio_stream(2136),iter(frames),Fraction(8,30),8000)
        with self.assertRaisesRegex(ValueError,'effective timeline'):
            shots.verify_audio_clock(audio_stream(320),iter(frames[:1]),Fraction(8,25),8000)

    def test_missing_truncated_gapped_overlapped_and_excess_audio_rejected(self):
        for frames in ([],[audio_frame(0)],[audio_frame(0),audio_frame(2048),audio_frame(3072)],
                       [audio_frame(0),audio_frame(1000),audio_frame(2024)],
                       [audio_frame(i*1024) for i in range(5)]):
            with self.assertRaises(ValueError):shots.verify_audio_clock(audio_stream(),iter(frames),Fraction(8,25),8000)
        for field,bad in (('pts',None),('time_base',None),('samples',0),('samples',True),('sample_rate',16000)):
            frame=audio_frame(0);setattr(frame,field,bad)
            with self.subTest(field=field),self.assertRaises(ValueError):shots.verify_audio_clock(audio_stream(),iter([frame]),Fraction(8,25),8000)

    def test_extra_complete_block_and_oversized_block_cannot_define_padding_budget(self):
        with self.assertRaisesRegex(ValueError,'coverage or padding'):
            shots.verify_audio_clock(audio_stream(2048),iter([audio_frame(i) for i in (0,1024,2048)]),Fraction(256,1000),8000)
        with self.assertRaisesRegex(ValueError,'Decoded audio clock'):
            shots.verify_audio_clock(audio_stream(),iter([audio_frame(0,samples=8000)]),Fraction(8,25),8000)
        stream=audio_stream();stream.codec_context.name='pcm_s16le'
        with self.assertRaisesRegex(ValueError,'metadata'):
            shots.verify_audio_clock(stream,iter([]),Fraction(8,25),8000)

    def test_effective_audio_offset_or_unbounded_clock_rejected(self):
        for field,bad in (('start_time',800),('duration',None),('time_base',Fraction(1,10)),('channels',1)):
            stream=audio_stream();setattr(stream,field,bad)
            with self.assertRaises(ValueError):shots.verify_audio_clock(stream,iter([]),Fraction(8,25),8000)


@unittest.skipUnless(importlib.util.find_spec('av') and shutil.which('ffmpeg'),'PyAV and FFmpeg required')
class NativeClockIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def make(self,fps=25,rate=8000,frames=8):
        path=self.root/f'p-{fps}-{rate}-{frames}';path.mkdir()
        value=fixture(path);value['fps']=fps;value['audio']['rate']=rate;value['audio']['duration']=max(1,frames/fps)
        value['scenes'][-1]['end_frame']=frames
        file=path/'project.json';file.write_text(json.dumps(value))
        out=path/'build';shots.build_project(file,out)
        return shots.BuildContext(file),out

    def test_real_build_verify_and_resume_at_allowed_nondivisor_rates(self):
        from gif_cinema.shot_renderer import Renderer
        for fps in (1,7,24,25,29,30,32,50,59,60):
            with self.subTest(fps=fps):
                ctx,out=self.make(fps);rec=shots.read_json(out/'build-receipt.json');renderer=Renderer(ctx.value,ctx.paths)
                for scene in ctx.value['scenes']:
                    hashes=[shots.sha(renderer.frame(i/fps,scene).tobytes()) for i in range(scene['start_frame'],scene['end_frame'])]
                    self.assertEqual(rec['completed'][scene['id']]['rgb_sha256'],hashes)
                self.assertEqual(shots.verify_project(out)['status'],'verified')
                self.assertTrue(shots.build_project(ctx.path,out,resume=True)['already_complete'])

    def test_real_encoded_audio_rates_with_padding_and_resampling(self):
        import av
        for rate in (8001,11025,22050,44100,48000):
            ctx,out=self.make(30,rate)
            self.assertEqual(shots.verify_project(out)['status'],'verified')
            if rate==8001:
                with av.open(str(out/'film.mp4')) as c:self.assertEqual(c.streams.audio[0].codec_context.sample_rate,8000)

    def test_actual_long_last_hold_preserves_pixels_but_is_rejected(self):
        import av
        ctx,out=self.make();rec=shots.read_json(out/'build-receipt.json');record=copy.deepcopy(rec['completed']['first'])
        original=list(shots.video_frames(out/record['file']));target=out/'bad-hold.mkv'
        with av.open(str(target),'w') as dst:
            stream=dst.add_stream('ffv1',rate=25);stream.width=stream.height=16;stream.pix_fmt='bgr0'
            stream.time_base=stream.codec_context.time_base=Fraction(1,1000)
            def mux(p):
                hold=Fraction(140 if p.pts*p.time_base==Fraction(3,25) else 40,1000)
                p.duration=int(hold/p.time_base);dst.mux(p)
            for i,f in enumerate(original):
                frame=av.VideoFrame.from_image(f.to_image());frame.pts=i*40;frame.time_base=Fraction(1,1000)
                for p in stream.encode(frame):mux(p)
            for p in stream.encode():mux(p)
        altered=list(shots.video_frames(target));self.assertEqual(altered[-1].duration,140)
        self.assertEqual([shots.sha(f.to_image().tobytes()) for f in original],[shots.sha(f.to_image().tobytes()) for f in altered])
        record.update(file=target.name,sha256=shots.sha(target.read_bytes()))
        with self.assertRaisesRegex(ValueError,'holds'):ctx.verify_scene(out,record,record['key'])

    def test_actual_truncated_aac_not_hidden_by_padding(self):
        ctx,out=self.make();bad=out/'short-audio.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(out/'film.mp4'),'-c:v','copy',
                        '-af','atrim=duration=0.04','-c:a','aac',str(bad)],check=True)
        with self.assertRaisesRegex(ValueError,'effective timeline'):ctx.verify_movie(bad)

    def test_actual_audio_gap_even_with_exact_effective_start_and_end(self):
        import av
        ctx,out=self.make(frames=50);bad=out/'gap-audio.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(out/'film.mp4'),'-c:v','copy',
              '-af',r'aselect=not(between(t\,0.5\,0.7)),atrim=duration=2','-c:a','aac',str(bad)],check=True)
        with av.open(str(bad)) as c:
            stream=c.streams.audio[0];self.assertEqual(stream.start_time,0);self.assertEqual(stream.duration*stream.time_base,2)
        with self.assertRaisesRegex(ValueError,'gap or overlap'):ctx.verify_movie(bad)

    def test_bad_hold_during_assembly_keeps_atomic_publication_and_resumes(self):
        path=self.root/'project.json';path.write_text(json.dumps(fixture(self.root)));out=self.root/'out'
        real_decode,real_encode=shots.video_frames,shots.encode;active=[False]
        def encode(command,images):
            active[0]='libx264' in command
            try:return real_encode(command,images)
            finally:active[0]=False
        def decode(path):
            frames=list(real_decode(path))
            if active[0] and path.name.startswith('second-'):frames[-1].duration=140
            yield from frames
        with patch.object(shots,'encode',encode),patch.object(shots,'video_frames',decode):
            with self.assertRaisesRegex(ValueError,'holds'):shots.build_project(path,out)
        self.assertFalse((out/'film.mp4').exists());self.assertFalse((out/'build-receipt.json').exists())
        result=shots.build_project(path,out,resume=True)
        self.assertEqual(result['scene_exports'],dict(rendered=0,reused=0,resumed=2))
        self.assertEqual(shots.verify_project(out)['status'],'verified')
