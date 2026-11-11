"""The cutout study's contact constraints and real, offline delivered frames."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

from PIL import Image
from gif_cinema import render

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('handoff',ROOT/'tools/build_handoff_prototype.py')
handoff=importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


class HandoffPrototypeTests(unittest.TestCase):
    def states(self):
        return [handoff.state(s,i) for s,(_,n,*_) in enumerate(handoff.SCENES) for i in range(n)]

    def test_one_prop_always_has_the_declared_support(self):
        for item in self.states():
            self.assertEqual(item['prop_count'],1)
            if item['owner'] in ('courier','shared'):
                self.assertEqual(item['courier_palm'],item['courier_grasp'])
            if item['owner'] in ('keeper','shared'):
                self.assertEqual(item['keeper_palm'],item['keeper_grasp'])
            if item['owner']=='hook':
                self.assertEqual(item['lantern_anchor'],item['hook_anchor'])

    def test_shared_grip_precedes_release_and_owner_never_reverts(self):
        owners=[s['owner'] for s in self.states()]
        order={'courier':0,'shared':1,'keeper':2,'hook':3}
        self.assertEqual([order[o] for o in owners],sorted(order[o] for o in owners))
        self.assertEqual(owners.count('shared'),5)
        first_keeper=owners.index('keeper')
        state=self.states()[first_keeper]
        self.assertEqual(state['courier_palm'],state['courier_grasp'])
        self.assertEqual(state['keeper_palm'],state['keeper_grasp'])

    def test_release_moves_outside_lantern_before_lowering(self):
        for state in self.states():
            if state['owner']=='hook':
                x,y=state['keeper_palm']
                lx,ly=state['lantern_anchor']
                # A 7px palm must not cross the 46px-wide glass enclosure.
                intersects_body=(lx-23-7<x<lx+23+7 and ly+28-7<y<ly+78+7)
                self.assertFalse(intersects_body,(state['frame'],x,y))

    def test_both_cut_endpoints_are_identical_before_encoding(self):
        for scene in (0,1):
            left=handoff.render_frame(handoff.state(scene,handoff.SCENES[scene][1]-1))
            right=handoff.render_frame(handoff.state(scene+1,0))
            self.assertEqual(left.tobytes(),right.tobytes())

    def test_lantern_has_no_teleport_or_unplanned_reverse(self):
        points=[s['lantern_anchor'] for s in self.states()]
        self.assertTrue(all(math.dist(a,b)<9 for a,b in zip(points,points[1:])))
        self.assertEqual([p[0] for p in points],sorted(p[0] for p in points))
        self.assertEqual([p[1] for p in points],sorted((p[1] for p in points),reverse=True))

    def test_published_sources_and_original_frames_match_their_hashes(self):
        example=ROOT/'examples/handoff'
        receipt=json.loads((example/'verification.json').read_text(encoding='utf-8'))
        for name,expected in receipt['files'].items():
            self.assertEqual(handoff.sha(ROOT/name),expected,name)
        ledger=json.loads((example/'anchor-ledger.json').read_text(encoding='utf-8'))['frames']
        with zipfile.ZipFile(example/'source-frames.zip') as archive:
            self.assertIsNone(archive.testzip())
            expected_names={item['file'] for item in ledger}|{
                'layers/background.png','layers/courier.png','layers/keeper.png'}
            self.assertEqual(set(archive.namelist()),expected_names)
            for item in ledger:
                self.assertEqual(handoff.hashlib.sha256(archive.read(item['file'])).hexdigest(),item['sha256'])
        all_frames,delays=handoff.decoded(ROOT/'docs/assets/handoff/one-small-light.gif')
        full=handoff.expand(all_frames,delays)
        self.assertEqual(len(full),80)
        self.assertEqual(sum(delays),8000)
        offset=0
        for source in receipt['source_scenes']:
            frames,durations=handoff.decoded(example/source['file'])
            expanded=handoff.expand(frames,durations)
            self.assertEqual(sum(durations),source['duration_ms'])
            self.assertEqual([f.tobytes() for f in expanded],
                             [f.tobytes() for f in full[offset:offset+len(expanded)]])
            offset+=len(expanded)
        self.assertEqual(offset,80)
        for left,right in [(23,24),(47,48)]:
            self.assertEqual(full[left].tobytes(),full[right].tobytes())

    def test_repeated_build_target_is_refused(self):
        with self.assertRaisesRegex(ValueError,'new directory'):
            handoff.build(ROOT/'tools')

    def test_invalid_frame_indices_are_rejected(self):
        for frame in (-1,24):
            with self.assertRaises(ValueError): handoff.state(0,frame)

    def test_unsupported_pillow_fails_clearly(self):
        handoff.font.cache_clear()
        with mock.patch.object(handoff.ImageFont,'load_default',side_effect=TypeError('old Pillow')):
            with self.assertRaisesRegex(ValueError,'Pillow >= 10.1'): handoff.font(12)
        handoff.font.cache_clear()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'Real FFmpeg/ffprobe required')
    def test_real_zero_call_export_preserves_every_authored_frame(self):
        base=ROOT/'output/tmp';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='handoff-test-',dir=base) as temporary:
            out=Path(temporary)/'film'
            report=handoff.build(out)
            self.assertEqual(report['provider_calls'],0)
            receipt=json.loads((out/'receipt.json').read_text())
            self.assertEqual(receipt['duration_ms'],8000)
            self.assertEqual(receipt['authoring_ticks'],80)
            self.assertTrue(receipt['source_frames_preserved'])
            self.assertTrue(receipt['source_gifs_unchanged'])
            for name,expected in receipt['files'].items():
                self.assertEqual(handoff.sha(out/name),expected,name)
            ledger=json.loads((out/'anchor-ledger.json').read_text())['frames']
            self.assertEqual([s['global_frame'] for s in ledger],list(range(80)))
            for item in ledger:
                self.assertEqual(handoff.sha(out/item['file']),item['sha256'])
            frames,delays=handoff.decoded(out/'one-small-light.gif')
            self.assertEqual(sum(delays),8000)
            self.assertEqual(len(handoff.expand(frames,delays)),80)
            with Image.open(out/'one-small-light.gif') as gif:
                self.assertNotIn('loop',gif.info)
            self.assertTrue(all(j['png_pixels_identical'] and j['gif_pixels_identical'] for j in receipt['joins']))
            script=render.load_script(out/'film.json',argparse.Namespace(width=None,height=None,fps=None))
            self.assertTrue(all('source_path' in shot and 'prompt' not in shot for shot in script['shots']))
            runtime_receipt=json.loads((out/'render/receipt.json').read_text())
            self.assertEqual(runtime_receipt['api_calls'],0)
            self.assertEqual(runtime_receipt['max_api_calls'],0)
            self.assertEqual(runtime_receipt['skipped'],3)
            self.assertEqual(runtime_receipt['generated'],0)
            self.assertEqual(receipt['export_verification']['streams'][0]['nb_read_frames'],'80')
            self.assertEqual(len(list((out/'frames').glob('*.png'))),80)
            self.assertEqual(len(list((out/'decoded-mp4').glob('*.png'))),80)


if __name__=='__main__':
    unittest.main()
