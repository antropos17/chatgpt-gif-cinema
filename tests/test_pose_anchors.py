"""Authored per-drawing anchor geometry, not automatic hand/identity inference."""
import copy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from gif_cinema import attachments, layers, pose_tracks, sequence
from tools.build_pose_anchor_proof import build_proof, color_center, HAND, make_inputs, measure, PROP


class PoseAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.path=make_inputs(self.root/'named',named=True)
        self.stage_path=self.path.parent/'stage.json'
        self.stage=json.loads(self.stage_path.read_text())

    def prepare(self, value=None):
        self.stage_path.write_text(json.dumps(self.stage if value is None else value))
        return layers.prepare_scene(self.stage_path)

    def animated(self):
        value=copy.deepcopy(self.stage);value['duration_ms']=160
        for layer in value['layers']:
            for segment in layer.get('attachments',[]):segment['end_ms']=160
        value['layers'][0]['pose_keys']=[{'at':0,'frame':0},{'at':.5,'frame':1},{'at':1,'frame':0}]
        return value

    def test_normalize_roundtrip_no_input_mutation_and_strict_reference(self):
        original=copy.deepcopy(self.stage)
        value=layers.normalize_scene(self.stage)
        self.assertEqual(value,layers.parse_scene(layers.serialize_scene(value)))
        self.assertEqual(self.stage,original)
        self.assertEqual(value['layers'][0]['frames'][1]['anchors']['hand'],[.75,.5])
        value['layers'][0]['frames'][1]['anchors']['hand'][0]=0
        self.assertEqual(self.stage,original)

    def test_actual_marker_and_prop_pixels_follow_selected_drawing(self):
        prepared=self.prepare(self.animated())
        for time,index,x in ((0,0,28),(40,0,28),(80,1,36),(120,1,36),(160,0,28)):
            frame,states=layers.render_at(prepared,time)
            actor,_=layers.render_at(prepared,time,only_layer='carrier')
            self.assertEqual(color_center(actor,HAND),color_center(frame,PROP))
            self.assertEqual(color_center(frame,PROP),(x,32))
            self.assertEqual(states['carrier']['source_index'],index)
            self.assertEqual(states['prop']['attachment']['source_index'],index)

    def test_outgoing_incoming_and_conceptual_endpoint_are_distinct(self):
        prepared=self.prepare(self.animated());parent=prepared['scene']['layers'][0]
        for t,previous,current in ((0,0,0),(79.999,0,0),(80,0,1),(80.001,1,1),(160,1,0)):
            self.assertEqual(pose_tracks.index_at(parent,t,before=True),previous)
            self.assertEqual(pose_tracks.index_at(parent,t),current)
        self.assertEqual(attachments.resolve(prepared,80,before=True)['prop']['x']*64,28)
        self.assertEqual(attachments.resolve(prepared,80)['prop']['x']*64,36)
        self.assertEqual(attachments.resolve(prepared,160,before=True)['prop']['x']*64,36)
        self.assertEqual(attachments.resolve(prepared,160)['prop']['x']*64,28)
        review=attachments.review(prepared)
        self.assertEqual([r['time_ms'] for r in review['switches']],[80])
        self.assertFalse(review['switches'][0]['own_schedule_switch'])
        self.assertEqual(review['max_switch_gap_px'],8)
        self.assertIn('not exported',review['named_anchor_scope'])

    def test_fifty_fps_keeps_exact_source_key_boundary(self):
        value=self.animated();value['fps']=50
        value['layers'][0]['pose_keys']=[{'at':0,'frame':0},{'at':.125,'frame':1},{'at':1,'frame':1}]
        prepared=self.prepare(value)
        self.assertEqual(attachments.resolve(prepared,20,before=True)['prop']['x']*64,28)
        for time in range(20,160,20):
            frame,states=layers.render_at(prepared,time)
            self.assertEqual(states['carrier']['source_index'],1)
            self.assertEqual(color_center(frame,PROP),(36,32))
        self.assertEqual(attachments.review(prepared)['switches'][0]['time_ms'],20)

    def test_layer_relative_clock_and_inactive_intervals(self):
        value=self.animated();value['duration_ms']=240
        for layer in value['layers']:
            layer.update(in_ms=40,out_ms=200)
            for segment in layer.get('attachments',[]):segment.update(start_ms=40,end_ms=200)
        prepared=self.prepare(value)
        self.assertIsNone(attachments.resolve(prepared,0)['prop'])
        self.assertEqual(attachments.resolve(prepared,80)['prop']['x']*64,28)
        self.assertEqual(attachments.resolve(prepared,120,before=True)['prop']['x']*64,28)
        self.assertEqual(attachments.resolve(prepared,120)['prop']['x']*64,36)
        self.assertIsNone(attachments.resolve(prepared,200)['prop'])
        self.assertEqual(attachments.resolve(prepared,200,before=True)['prop']['x']*64,36)

    def test_fitted_raster_rotation_zoom_and_child_anchor_remain_local(self):
        value=self.animated();parent=value['layers'][0];child=value['layers'][2]
        parent['size']=[32,40]
        parent['keyframes']=[{'at':0,'rotation':90,'zoom':2},{'at':1}]
        child['anchor']=[0,0]
        prepared=self.prepare(value)
        self.assertEqual(prepared['rasters']['carrier'].size,(32,32))
        for t,y in ((0,16),(80,48)):
            state=attachments.resolve(prepared,t)['prop']
            self.assertAlmostEqual(state['x']*64,32)
            self.assertAlmostEqual(state['y']*64,y)
            self.assertEqual((state['rotation'],state['zoom']),(0,1))

    def test_nested_fixed_child_follows_named_parent_and_paint_order(self):
        value=self.animated()
        value['layers'].append({'id':'spark','type':'rect','size':[2,2],'fill':'#ffffff',
             'attachments':[{'start_ms':0,'end_ms':160,'parent':'prop','point':[.5,.5]}]})
        prepared=self.prepare(value);first,states=layers.render_at(prepared,80,only_layer='spark')
        self.assertEqual(states['spark']['x']*64,36)
        review=attachments.review(prepared)
        self.assertEqual({r['layer'] for r in review['switches']},{'prop','spark'})
        self.assertTrue(all(not r['own_schedule_switch'] for r in review['switches']))
        value['layers'].reverse();other=self.prepare(value)
        second,other_states=layers.render_at(other,80,only_layer='spark')
        self.assertEqual(first.tobytes(),second.tobytes());self.assertEqual(states,other_states)

    def test_named_switch_uses_outgoing_parent_pose_not_incoming_one(self):
        value=self.animated()
        value['layers'][2]['attachments']=[{'start_ms':0,'end_ms':80,'parent':'carrier','anchor':'hand'},
            {'start_ms':80,'end_ms':160,'parent':'receiver','anchor':'hand'}]
        prepared=self.prepare(value);row=attachments.review(prepared)['switches'][0]
        self.assertEqual(row['before_anchor_px'],[28,32]);self.assertEqual(row['after_anchor_px'],[36,32])
        self.assertEqual(row['anchor_gap_px'],8);self.assertTrue(row['own_schedule_switch'])

    def test_missing_anchors_including_unselected_drawing_fail_before_asset_read(self):
        for unused in (False,True):
            value=copy.deepcopy(self.stage)
            if unused:value['layers'][0]['frames'].append({'rect':[0,0,16,16],'duration_ms':40})
            else:del value['layers'][0]['frames'][1]['anchors']['hand']
            with patch.object(layers,'read_assets',side_effect=AssertionError('must validate first')):
                with self.assertRaises(ValueError):self.prepare(value)

    def test_invalid_anchor_maps_names_and_coordinates(self):
        bad=[None,{},[],{'hand':[1]}, {'hand':[True,0]}, {'hand':[float('nan'),0]},
             {'hand':[float('inf'),0]}, {'hand':[-.01,0]}, {'hand':[0,1.01]},
             {'not a name':[0,0]}, {'рука':[0,0]}, {'x'*41:[0,0]}, {'':[0,0]},
             {str(n):[0,0] for n in range(33)}]
        for anchors in bad:
            with self.subTest(anchors=anchors):
                value=copy.deepcopy(self.stage);value['layers'][0]['frames'][0]['anchors']=anchors
                with self.assertRaises(ValueError):layers.normalize_scene(value)

    def test_named_binding_is_exclusive_and_requires_sprite_parent(self):
        for edit in ('both','none','badname','missing','wrongcase','nonsprite'):
            value=copy.deepcopy(self.stage);parent=value['layers'][0];segment=value['layers'][2]['attachments'][0]
            if edit=='both':segment['point']=[.5,.5]
            if edit=='none':del segment['anchor']
            if edit=='badname':segment['anchor']=['hand']
            if edit=='missing':segment['anchor']='missing'
            if edit=='wrongcase':segment['anchor']='HAND'
            if edit=='nonsprite':value['layers'][0]={'id':'carrier','type':'rect','size':[16,16]}
            with self.subTest(edit=edit),self.assertRaises(ValueError):layers.normalize_scene(value)

    def test_cycles_and_parent_visibility_still_rejected(self):
        value=copy.deepcopy(self.stage)
        value['layers'][0]['attachments']=[{'start_ms':0,'end_ms':80,'parent':'prop','point':[.5,.5]}]
        with self.assertRaisesRegex(ValueError,'acyclic'):layers.normalize_scene(value)
        value=copy.deepcopy(self.stage);value['layers'][0]['out_ms']=40
        with self.assertRaisesRegex(ValueError,'active'):layers.normalize_scene(value)

    def test_legacy_fixed_point_ignores_optional_anchor_metadata(self):
        value=self.animated();value['layers'][2]['attachments'][0].pop('anchor')
        value['layers'][2]['attachments'][0]['point']=[.75,.5]
        with_anchors=self.prepare(value)
        for layer in value['layers']:
            for frame in layer.get('frames',[]):frame.pop('anchors',None)
        without=self.prepare(value)
        for t in (0,40,80,120,160):
            a,sa=layers.render_at(with_anchors,t);b,sb=layers.render_at(without,t)
            self.assertEqual(a.tobytes(),b.tobytes());self.assertEqual(sa,sb)
        self.assertEqual(attachments.review(with_anchors),attachments.review(without))
        self.assertNotIn('named_anchor_scope',attachments.review(without))

    def test_bundle_roundtrip_preserves_sources_drawings_and_anchors(self):
        prepared=self.prepare(self.animated());before=self.stage_path.read_bytes();atlas=(self.path.parent/'poses.png').read_bytes()
        saved=layers.prepare_scene(layers.save_bundle(prepared,self.root/'bundle'))
        for t in (0,40,80,120,160):
            a,sa=layers.render_at(prepared,t);b,sb=layers.render_at(saved,t)
            self.assertEqual(a.tobytes(),b.tobytes());self.assertEqual(sa,sb)
        self.assertEqual(self.stage_path.read_bytes(),before);self.assertEqual((self.path.parent/'poses.png').read_bytes(),atlas)

    def test_sequence_handoff_and_source_drawing_indices_are_carried(self):
        compiled=sequence.compile_sequence(self.path);rows=measure(compiled)
        self.assertTrue(all(row['marker_gap_px']==0 for row in rows))
        self.assertEqual([row['prop_px'][0] for row in rows],[28,28,36,36,36,36,44,44])
        timeline=compiled['report']['timeline']
        self.assertEqual(timeline[0]['end_state']['prop']['x'],timeline[1]['start_state']['prop']['x'])
        self.assertEqual(timeline[1]['start_state']['prop']['attachment']['parent'],'receiver')
        self.assertTrue(sequence.render_join(*compiled['compiled'])['endpoint_pixels_equal'])
        self.assertEqual(compiled['report']['visual_acceptance'],'not-established')

    def test_boundary_pose_endpoint_is_carried_but_not_repeated(self):
        project=json.loads(self.path.read_text())
        project['shots'][0]['tracks']['carrier']['pose_keys']=[{'at':0},{'at':1,'frame':1}]
        self.path.write_text(json.dumps(project));compiled=sequence.compile_sequence(self.path)
        first=compiled['compiled'][0]
        self.assertEqual(attachments.resolve(first,120)['prop']['x']*64,28)
        self.assertEqual(attachments.resolve(first,160)['prop']['x']*64,36)
        self.assertEqual(compiled['report']['timeline'][1]['start_state']['prop']['x']*64,36)
        join=sequence.render_join(*compiled['compiled']);self.assertTrue(join['endpoint_pixels_equal']);self.assertFalse(join['last_stored_pixels_equal'])

    def test_dry_run_and_missing_landmark_do_not_publish_or_call_network(self):
        with patch.object(socket,'socket',side_effect=AssertionError('network forbidden')):
            result=sequence.build_sequence(self.path,self.root/'dry',dry_run=True)
        self.assertEqual(result['provider_calls'],0);self.assertFalse((self.root/'dry').exists())
        self.stage['layers'][0]['frames'][1]['anchors']={'other':[.5,.5]};self.prepare_failure_stage()
        with self.assertRaises(ValueError):sequence.build_sequence(self.path,self.root/'bad')
        self.assertFalse((self.root/'bad').exists())

    def prepare_failure_stage(self):
        self.stage_path.write_text(json.dumps(self.stage))

    def test_proof_geometry_and_unchanged_actor_samples(self):
        report=build_proof(self.root/'proof',shot_ms=160)
        self.assertEqual(report['max_marker_gap_px'],{'fixed':8.0,'named':0.0})
        self.assertTrue(report['actor_samples_and_clock_unchanged'])
        self.assertEqual((report['frames'],report['duration_ms']),(8,320))

    @unittest.skipUnless(importlib.util.find_spec('av') and shutil.which('ffmpeg') and shutil.which('ffprobe'),'PyAV and FFmpeg required')
    def test_actual_sequence_exports_and_lossless_master_reopen_all_samples(self):
        with patch.object(socket,'create_connection',side_effect=AssertionError('network forbidden')):
            report=build_proof(self.root/'rendered-proof',render=True,shot_ms=160)
        for value in report['exports'].values():
            self.assertEqual((value['frames'],value['duration_ms']),(8,320))
            for key in ('rgba_mismatches','pts_mismatches','hold_mismatches','decoded_marker_mismatches'):
                self.assertEqual(value[key],0)
