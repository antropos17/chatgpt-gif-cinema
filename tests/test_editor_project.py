import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from gif_cinema import editor_project as ep, master
try: import av
except ImportError: av = None


def project(delays=(10, 30, 150), names=('First', 'Last')):
    # Duplicate drawing, fractional alpha and hidden RGB are intentional.
    pixel = bytes([241, 97, 123, 0, 33, 11, 211, 128, 9, 240, 71, 255, 0, 0, 0, 0])
    frame = pixel * (ep.FRAME_BYTES // len(pixel))
    frames = [frame if i < 2 else bytes(reversed(frame)) for i in range(len(delays))]
    scenes = [{'name': names[0], 'delays': list(delays[:-1])}, {'name': names[-1], 'delays': list(delays[-1:])}] if len(delays)>1 else [{'name': names[0], 'delays': list(delays)}]
    meta = {'version': 1, 'width': 256, 'height': 256, 'scenes': scenes}
    return pack(meta, b''.join(frames)), frames


def pack(meta, payload=b''):
    header = json.dumps(meta, ensure_ascii=True).encode()
    return b'GFC1' + len(header).to_bytes(4, 'little') + header + payload


class ParseTests(unittest.TestCase):
    def test_metadata_boundaries_and_unicode_are_not_paths(self):
        raw, _ = project(names=('../outside / 世界', 'Last\u0000Name'))
        result = ep.parse_project(raw)
        self.assertEqual(result['duration_ms'], 190)
        self.assertEqual(result['frame_count'], 3)
        self.assertEqual(result['scenes'][1]['start_ms'], 40)
        self.assertEqual(result['scenes'][1]['start_frame'], 2)
        self.assertEqual(result['scenes'][0]['name'], '../outside / 世界')

    def test_rejects_mutable_and_truncated_and_extra_payloads(self):
        raw, _ = project()
        for bad in [bytearray(raw), memoryview(raw), raw[:-1], raw+b'0', b'', b'GFC2'+raw[4:]]:
            with self.subTest(kind=type(bad),size=len(bad)), self.assertRaises(ValueError): ep.parse_project(bad)

    def test_strict_metadata(self):
        raw, frames = project(); length = int.from_bytes(raw[4:8],'little'); meta=json.loads(raw[8:8+length])
        variants=[]
        for key, values in [('version',[True,1.0,2]),('width',[True,255,256.0]),('height',[0,257])]:
            for value in values:
                m=dict(meta);m[key]=value;variants.append(m)
        variants += [{**meta,'extra':0},{**meta,'scenes':[]},{**meta,'scenes':[meta['scenes'][0]]*9}]
        for delay in [True,10.0,0,-10,11,30010,'10',None]:
            variants.append({**meta,'scenes':[{'name':'x','delays':[delay]}]})
        for scene in [{'name':'x','delays':[]},{'name':'x'*301,'delays':[10]}, {'name':'x','delays':[10],'source':'/etc/passwd'}, {'name':1,'delays':[10]}, {'name':'\ud800','delays':[10]}]:
            variants.append({**meta,'scenes':[scene]})
        for m in variants:
            with self.subTest(meta=m), self.assertRaises(ValueError): ep.parse_project(pack(m,b''.join(frames)))

    def test_aggregate_limits_before_pixel_allocation(self):
        for delays in [[10]*241,[30000,10]]:
            with self.assertRaises(ValueError): ep.parse_project(pack({'version':1,'width':256,'height':256,'scenes':[{'name':'x','delays':delays}]}))
        raw,_=project()
        with patch.object(ep,'MAX_BYTES',len(raw)-1),self.assertRaises(ValueError):ep.parse_project(raw)

    def test_duplicate_keys_and_header_budgets(self):
        for header in [b'{"version":1,"version":1}', b'[]', b'{"a":NaN}', b'\xff']:
            with self.assertRaises(ValueError):ep.parse_project(b'GFC1'+len(header).to_bytes(4,'little')+header)
        for length in [0,100001,99999]:
            with self.assertRaises(ValueError):ep.parse_project(b'GFC1'+length.to_bytes(4,'little'))


@unittest.skipUnless(av,'PyAV required')
class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'edit.gfc'
        self.raw,self.frames=project();self.source.write_bytes(self.raw);self.out=self.root/'film'
    def tearDown(self):self.tmp.cleanup()

    def test_every_rgba_and_vfr_packet_including_last_hold(self):
        report=ep.build(self.source,self.out,preview=False)
        self.assertEqual(self.source.read_bytes(),self.raw)
        self.assertEqual((self.out/'project.gfc').read_bytes(),self.raw)
        self.assertEqual(master.verify_master(self.out/'master.mkv',report)['frames'],3)
        with av.open(str(self.out/'master.mkv')) as movie:
            decoded=list(movie.decode(video=0))
        self.assertEqual([master.rgba_frame(f).tobytes() for f in decoded],self.frames)
        self.assertEqual([int(f.pts*f.time_base*1000) for f in decoded],[0,10,40])
        self.assertEqual([int(f.duration*f.time_base*1000) for f in decoded],[10,30,150])
        self.assertEqual(report['verification']['duration_ms'],190)
        self.assertEqual(report['notice'],ep.NOTICE)
        self.assertEqual(report['status'],'verified-master')
        self.assertEqual(set(report['files']),{'master.mkv','project.gfc'})
        for name,fact in report['files'].items():self.assertEqual(master.file_sha(self.out/name),fact['sha256'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_real_preview_count_and_duration(self):
        report=ep.build(self.source,self.out)
        self.assertEqual(report['viewing_copy']['frames'],19)
        self.assertEqual(report['viewing_copy']['duration_ms'],190)
        self.assertEqual(report['verification']['frames'],3)
        self.assertTrue((self.out/'preview.mp4').is_file())

    def test_single_long_hold_and_duplicate_frames_kept(self):
        for delays in [(30000,), (10,10,3000)]:
            raw,_=project(delays);self.source.write_bytes(raw)
            report=ep.build(self.source,self.root/str(sum(delays)),preview=False)
            self.assertEqual(report['verification']['frames'],len(delays))
            self.assertEqual(report['verification']['duration_ms'],sum(delays))

    def test_no_clobber_or_symlink(self):
        self.out.mkdir();(self.out/'accepted').write_text('safe')
        with self.assertRaises(ValueError):ep.build(self.source,self.out,False)
        self.assertEqual((self.out/'accepted').read_text(),'safe')
        link=self.root/'link.gfc'
        try:link.symlink_to(self.source)
        except OSError:self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError):ep.build(link,self.root/'new',False)
        with self.assertRaises(ValueError):ep.build(self.source,self.source,False)
        with self.assertRaises(ValueError):ep.build(self.source,self.root,False)

    def test_corrupt_encoder_prevents_publication(self):
        ordinary=master.video_frame
        def corrupt(av,image):return ordinary(av,Image.new('RGBA',image.size))
        with patch.object(master,'video_frame',side_effect=corrupt),self.assertRaisesRegex(ValueError,'RGBA mismatch'):
            ep.build(self.source,self.out,False)
        self.assertFalse(self.out.exists());self.assertEqual(self.source.read_bytes(),self.raw)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),['edit.gfc'])

    def test_source_mutation_prevents_publication(self):
        ordinary=master.verify_master
        def mutate(*args):
            result=ordinary(*args);self.source.write_bytes(self.raw+b'changed');return result
        with patch.object(master,'verify_master',side_effect=mutate),self.assertRaisesRegex(ValueError,'changed'):
            ep.build(self.source,self.out,False)
        self.assertFalse(self.out.exists())

    def test_preview_failure_leaves_no_completed_result(self):
        with patch.object(master,'viewing_copy',side_effect=RuntimeError('broken')),self.assertRaises(RuntimeError):
            ep.build(self.source,self.out)
        self.assertFalse(self.out.exists());self.assertEqual(self.source.read_bytes(),self.raw)

    def test_publication_failure_rolls_back_only_owned_files(self):
        ordinary=ep.cli.publish_file;calls=[]
        def fail(stage,target,*args):
            calls.append(target.name)
            if len(calls)==2:raise OSError('disk failure')
            return ordinary(stage,target,*args)
        with patch.object(ep.cli,'publish_file',side_effect=fail),self.assertRaises(OSError):ep.build(self.source,self.out,False)
        self.assertFalse(self.out.exists());self.assertEqual(self.source.read_bytes(),self.raw)

    def test_raced_output_is_not_replaced(self):
        ordinary=master.verify_master
        def race(*args):
            result=ordinary(*args);self.out.mkdir();(self.out/'accepted').write_text('safe');return result
        with patch.object(master,'verify_master',side_effect=race),self.assertRaises(FileExistsError):ep.build(self.source,self.out,False)
        self.assertEqual((self.out/'accepted').read_text(),'safe')

    def test_manifest_last_and_labels_not_paths(self):
        self.raw,self.frames=project(names=('../../outside','München'));self.source.write_bytes(self.raw)
        ordinary=ep.cli.publish_file;names=[]
        def record(a,b,*args):names.append(b.name);return ordinary(a,b,*args)
        with patch.object(ep.cli,'publish_file',side_effect=record):report=ep.build(self.source,self.out,False)
        self.assertEqual(names[-1],'manifest.json');self.assertEqual(report['scenes'][0]['name'],'../../outside')
        self.assertEqual(set(p.name for p in self.out.iterdir()),{'project.gfc','master.mkv','manifest.json'})
