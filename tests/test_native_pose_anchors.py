"""Native sprite clock attachment points; no resampling or generated action."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from gif_cinema import attachments, layer_gifs, layer_sprites, layers, sequence
from tools.build_native_anchor_proof import build_proof, make_scene
from tools.build_pose_anchor_proof import color_center, HAND, PROP


class NativeAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve(); self.path=make_scene(self.root/'source')
        self.scene=json.loads(self.path.read_text())

    def prepare(self):
        self.path.write_text(json.dumps(self.scene)); return layers.prepare_scene(self.path)

    def test_exact_trim_loop_outgoing_and_first_sample(self):
        asset={'frames':[None]*3, 'ends_ms':[40,100,180], 'duration_ms':180}
        for t,left,right in ((0,0,0),(9.999,0,0),(10,0,1),(10.001,1,1),(70,1,2),(80,2,0),(160,2,0)):
            self.assertEqual(layer_gifs.frame_index(asset,t,'loop',[30,110],before=True),left)
            self.assertEqual(layer_gifs.frame_index(asset,t,'loop',[30,110]),right)
        for t in (80,81,160):
            for before in (True,False): self.assertEqual(layer_gifs.frame_index(asset,t,'once',[30,110],before=before),2)
        for before in (True,False): self.assertEqual(layer_gifs.frame_index(asset,0,'loop',[40,100],before=before),1)
        self.assertEqual(layer_gifs.frame_index(asset,60,'loop',[40,100],before=True),1)

    def test_once_end_excludes_next_drawing(self):
        layer=layers.normalize_scene(self.scene)['layers'][0]; layer['source_range_ms']=[0,100];layer['playback']='once'
        for t in (100,101,10000):
            for before in (True,False):self.assertEqual(layer_sprites.index_at(layer,t,before=before),1)

    def test_native_actor_and_prop_share_indices_at_all_samples(self):
        for fps in (25,50):
            self.scene['fps']=fps; prepared=self.prepare()
            for t in range(0,481,1000//fps):
                frame,state=layers.render_at(prepared,t); actor,_=layers.render_at(prepared,t,only_layer='actor')
                self.assertEqual(state['actor']['source_index'],state['prop']['attachment']['source_index'])
                self.assertEqual(color_center(frame,PROP),color_center(actor,HAND))

    def test_native_review_exposes_off_grid_and_loop_boundaries(self):
        prepared=self.prepare(); review=attachments.review(prepared)
        self.assertEqual([r['time_ms'] for r in review['switches']],[10,70,240,250,310])
        self.assertEqual(review['max_switch_gap_px'],8)
        self.assertEqual(review['switch_count'],5);self.assertEqual(review['omitted_switch_rows'],0)
        self.assertIn('off-grid',review['native_anchor_scope']); self.assertTrue(all(not x['own_schedule_switch'] for x in review['switches']))
        timing=layer_sprites.timing_report(prepared['scene'])['actor']
        self.assertEqual(timing['selected_delays_ms'],[10,60,170]);self.assertEqual(timing['source_delays_ms'],[40,60,180])

    def test_nonzero_origin_partial_child_interval_and_holder_switch(self):
        self.scene['duration_ms']=640
        self.scene['layers'][0].update(in_ms=40,out_ms=600)
        self.scene['layers'][1].update(in_ms=80,out_ms=560)
        self.scene['layers'][1]['attachments'][0].update(start_ms=80,end_ms=560)
        prepared=self.prepare()
        self.assertIsNone(attachments.resolve(prepared,40)['prop'])
        self.assertEqual(attachments.resolve(prepared,110,before=True)['prop']['attachment']['source_index'],1)
        self.assertEqual(attachments.resolve(prepared,110)['prop']['attachment']['source_index'],2)
        self.assertEqual([r['time_ms'] for r in attachments.review(prepared)['switches']],[110,280,290,350,520,530])

    def test_nested_descendant_inherits_native_jump(self):
        self.scene['layers'].append({'id':'tip','type':'rect','size':[2,2],
            'attachments':[{'start_ms':0,'end_ms':480,'parent':'prop','point':[.5,.5]}]})
        prepared=self.prepare(); review=attachments.review(prepared)
        self.assertEqual(review['switch_count'],10)
        self.assertEqual({r['layer'] for r in review['switches']},{'tip','prop'})

    def test_missing_native_landmark_rejected_before_read(self):
        del self.scene['layers'][0]['frames'][2]['anchors']
        with patch.object(layers,'read_assets',side_effect=AssertionError('must validate first')):
            with self.assertRaises(ValueError):self.prepare()

    def test_bad_native_trim_rejected_without_export(self):
        self.scene['layers'][0]['source_range_ms']=[30,300]
        self.path.write_text(json.dumps(self.scene))
        with self.assertRaises(ValueError):layers.render_scene(self.path,self.root/'bad')
        self.assertFalse((self.root/'bad').exists())

    def test_sequence_does_not_implicitly_reset_native_clock(self):
        project={'format':sequence.FORMAT,'schema_version':1,'title':'No reset','stage':'scene.json',
                 'shots':[{'id':'first','action':'Hold','duration_ms':480,'tracks':{}}]}
        path=self.path.parent/'sequence.json';path.write_text(json.dumps(project))
        with self.assertRaisesRegex(ValueError,'cannot implicitly reset'):sequence.compile_sequence(path)

    def test_roundtrip_and_dryrun_preserve_sources_and_metadata(self):
        before={p.name:p.read_bytes() for p in self.path.parent.iterdir()};prepared=layers.prepare_scene(self.path)
        reopened=layers.prepare_scene(layers.save_bundle(prepared,self.root/'saved'))
        for t in range(0,480,40):
            a,sa=layers.render_at(prepared,t);b,sb=layers.render_at(reopened,t)
            self.assertEqual(a.tobytes(),b.tobytes());self.assertEqual(sa,sb)
        with patch('socket.create_connection',side_effect=AssertionError('network forbidden')):
            plan=layers.render_scene(self.path,self.root/'dry',dry_run=True)
        self.assertEqual(plan['api_calls'],0);self.assertFalse((self.root/'dry').exists())
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.path.parent.iterdir()})

    def test_native_events_that_output_grid_never_samples_are_not_invented(self):
        parent=self.scene['layers'][0];parent['source_range_ms']=[30,70]; parent['playback']='once'
        self.scene['layers'][0]['frames'][0]['duration_ms']=20
        self.scene['layers'][0]['frames'][1]['duration_ms']=20
        prepared=self.prepare(); timing=layer_sprites.timing_report(prepared['scene'])['actor']
        self.assertEqual(timing['selected_delays_ms'],[10,30]); self.assertEqual(timing['sampled_source_indices'],[1,2])
        parent['source_range_ms']=[0,80]
        prepared=self.prepare(); timing=layer_sprites.timing_report(prepared['scene'])['actor']
        self.assertEqual(timing['unsampled_selected_drawings'],[1])
        self.assertNotIn(1,[layers.render_at(prepared,t)[1]['actor']['source_index'] for t in range(0,480,40)])

    def test_report_cap_retains_full_aggregate_and_late_worst(self):
        self.scene['duration_ms']=30000;parent=self.scene['layers'][0];parent['source_range_ms']=[0,40]
        for f in parent['frames']:f['duration_ms']=20
        parent['frames'][0]['anchors']['hand']=[.49,.5]; parent['frames'][1]['anchors']['hand']=[.51,.5]
        parent['keyframes']=[{'at':0,'zoom':1},{'at':1,'zoom':8}]
        self.scene['layers']=self.scene['layers'][:1]
        for i in range(15):
            self.scene['layers'].append({'id':f'p{i}','type':'rect','size':[2,2],
              'attachments':[{'start_ms':0,'end_ms':30000,'parent':'actor' if i==0 else f'p{i-1}',
                              **({'anchor':'hand'} if i==0 else {'point':[.5,.5]})}]})
        prepared=self.prepare(); review=attachments.review(prepared)
        self.assertEqual(review['switch_count'],1499*15)
        self.assertEqual(len(review['switches']),2048)
        self.assertEqual(review['omitted_switch_rows'],1499*15-2048)
        self.assertEqual(len(review['worst_switch_by_layer']),15)
        self.assertTrue(all(r['time_ms']==29980 for r in review['worst_switch_by_layer']))
        self.assertGreater(review['max_switch_gap_px'],max(r['anchor_gap_px'] for r in review['switches']))
        self.assertLess(len(json.dumps(review,indent=2).encode()),1024*1024)

    def test_proof_preserves_original_pixels_and_clocks(self):
        report=build_proof(self.root/'proof')
        self.assertTrue(report['actor_pixels_and_clock_unchanged'])
        self.assertEqual([x['max_marker_gap_px'] for x in report['cases'].values()],[8,0,8,0])

    @unittest.skipUnless(importlib.util.find_spec('av') and shutil.which('ffmpeg') and shutil.which('ffprobe'),'PyAV and FFmpeg required')
    def test_actual_four_exports_all_png_gif_pixels_and_mp4_pts_holds(self):
        with patch('socket.create_connection',side_effect=AssertionError('network forbidden')):
            report=build_proof(self.root/'render',render=True)
        for row in report['cases'].values():
            self.assertEqual(row['export']['png_rgba_mismatches'],0)
            self.assertEqual(row['export']['gif_flattened_rgb_mismatches'],0)
            self.assertEqual(row['export']['mp4_pts_mismatches'],0)
            self.assertEqual(row['export']['mp4_hold_mismatches'],0)
