#!/usr/bin/env python3
"""Original geometric marker proof, not character generation or visual acceptance."""
import argparse
import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont
from gif_cinema import layers, master, sequence, sequence_master

HAND = (75, 190, 230, 255)
PROP = (255, 112, 67, 255)


def make_inputs(root, *, named=True, shot_ms=160):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    atlas = Image.new('RGBA', (32, 16))
    draw = ImageDraw.Draw(atlas)
    for n, hand_x in enumerate((4, 12)):
        draw.rectangle((n*16+6, 4, n*16+9, 6), fill=(130, 140, 155, 255))
        draw.rectangle((n*16+hand_x-1, 7, n*16+hand_x, 8), fill=HAND)
    atlas.save(root/'poses.png')
    frames = [{'rect': [n*16, 0, 16, 16], 'duration_ms': delay,
               **({'anchors': {'hand': [x/16, .5]}} if named else {})}
              for n, (x, delay) in enumerate(((4, 40), (12, 120)))]
    def actor(name, x):
        return {'id': name, 'type': 'sprites', 'source': 'poses.png', 'size': [16, 16],
                'sampling': 'pixel', 'frames': copy.deepcopy(frames),
                'keyframes': [{'at': 0, 'x': x}, {'at': 1}],
                'pose_keys': [{'at': 0, 'frame': 0}, {'at': 1, 'frame': 0}]}
    def binding(parent, duration):
        return {'start_ms': 0, 'end_ms': duration, 'parent': parent,
                **({'anchor': 'hand'} if named else {'point': [.75 if parent == 'carrier' else .25, .5]})}
    stage = {'format': layers.FORMAT, 'schema_version': 1, 'width': 64, 'height': 64,
             'fps': 25, 'duration_ms': 80, 'loop': False, 'layers': [actor('carrier', .5), actor('receiver', .625),
             {'id': 'prop', 'type': 'rect', 'size': [4, 4], 'fill': '#ff7043',
              'attachments': [binding('carrier', 80)]}]}
    project = {'format': sequence.FORMAT, 'schema_version': 1, 'title': 'Authored marker handoff proof',
               'stage': 'stage.json', 'shots': [
        {'id': 'move', 'action': 'Select the second carrier drawing.', 'duration_ms': shot_ms,
         'tracks': {'carrier': {'pose_keys': [{'at': 0}, {'at': .5, 'frame': 1}, {'at': 1, 'frame': 1}]}}},
        {'id': 'receive', 'action': 'Transfer at the shared point, then select the receiver drawing.', 'duration_ms': shot_ms,
         'tracks': {'prop': {'attachments': [binding('receiver', shot_ms)]},
                    'receiver': {'pose_keys': [{'at': 0}, {'at': .5, 'frame': 1}, {'at': 1, 'frame': 1}]}}}]}
    (root/'stage.json').write_text(json.dumps(stage, indent=2)+'\n')
    (root/'sequence.json').write_text(json.dumps(project, indent=2)+'\n')
    return root/'sequence.json'


def color_center(image, color):
    coords = [(x, y) for y in range(image.height) for x in range(image.width) if image.getpixel((x, y)) == color]
    if not coords: raise AssertionError('Expected exact original marker color missing')
    return ((min(x for x, _ in coords)+max(x for x, _ in coords)+1)/2,
            (min(y for _, y in coords)+max(y for _, y in coords)+1)/2)


def measure(compiled):
    rows = []
    for prepared, timeline in zip(compiled['compiled'], compiled['report']['timeline']):
        for time in range(0, prepared['scene']['duration_ms'], 40):
            frame, states = layers.render_at(prepared, time)
            holder = states['prop']['attachment']['parent']
            carrier, _ = layers.render_at(prepared, time, only_layer=holder)
            hand, prop = color_center(carrier, HAND), color_center(frame, PROP)
            rows.append({'time_ms': timeline['start_ms']+time, 'holder': holder,
                         'hand_px': list(hand), 'prop_px': list(prop), 'marker_gap_px': math.dist(hand, prop),
                         'source_indices': {key: states[key]['source_index'] for key in ('carrier', 'receiver')},
                         'actor_rgba_sha256': {key: hashlib.sha256(layers.render_at(prepared,time,only_layer=key)[0].tobytes()).hexdigest()
                                               for key in ('carrier','receiver')}})
    return rows


def build_proof(out, *, render=False, shot_ms=800):
    out = Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)):
        raise ValueError('Use a new non-symlink proof output directory')
    if type(shot_ms) is not int or not 80 <= shot_ms <= 2000 or shot_ms % 80:
        raise ValueError('shot_ms must be 80..2000 in 80ms units')
    paths = {name: make_inputs(out/name, named=name=='named', shot_ms=shot_ms) for name in ('fixed','named')}
    original = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
    compiled = {name: sequence.compile_sequence(path) for name,path in paths.items()}
    rows = {name: measure(value) for name,value in compiled.items()}
    for left,right in zip(rows['fixed'],rows['named']):
        for key in ('time_ms','holder','source_indices','actor_rgba_sha256'):
            if left[key]!=right[key]: raise AssertionError('Original actor samples/clock changed')
    report = {'format':'gif-cinema-authored-anchor-proof-v1','provider_calls':0,
              'frames':len(rows['named']),'duration_ms':shot_ms*2,'fps':25,'rows':rows,
              'max_marker_gap_px':{name:max(row['marker_gap_px'] for row in value) for name,value in rows.items()},
              'source_hashes':original,'actor_samples_and_clock_unchanged':True,
              'scope':'Pixel centers of original native-size markers versus the rendered prop. Authored coordinates, not detected hands, identity, smoothness or artistic acceptance. Fixed points could also be manually rescheduled; this avoids repeating their schedule per pose.'}
    if report['max_marker_gap_px']!={'fixed':8.0,'named':0.0}: raise AssertionError('Unexpected geometry')
    sheet = Image.new('RGB',(1024,636),(246,247,250)); draw=ImageDraw.Draw(sheet);font=ImageFont.load_default(size=17)
    draw.text((16,8),'Technical marker proof | original drawings, no generated poses',fill='#18212e',font=font)
    for row,name in enumerate(('fixed','named')):
        for col,global_time in enumerate((0,shot_ms//2,shot_ms,shot_ms+shot_ms//2)):
            scene_index = int(global_time>=shot_ms);time=global_time%shot_ms
            frame,_=layers.render_at(compiled[name]['compiled'][scene_index],time)
            cell=Image.new('RGBA',frame.size,(238,241,246,255));cell.alpha_composite(frame)
            sheet.paste(cell.convert('RGB').resize((256,256),Image.Resampling.NEAREST),(col*256,44+row*296))
            fact=rows[name][global_time//40]
            draw.text((col*256+10,304+row*296),f'{name} | {global_time}ms | gap {fact["marker_gap_px"]:g}px',fill='#18212e',font=font)
    sheet.save(out/'comparison.png')
    if render:
        report['exports']={}
        for name,path in paths.items():
            built=out/(name+'-build');sequence.build_sequence(path,built);sequence.verify_sequence(built)
            target=out/(name+'-master');result=sequence_master.build(built,target)
            receipt=json.loads((target/'master-receipt.json').read_text());verified=master.verify_master(target/'master.mkv',receipt)
            if result['frames']!=report['frames'] or result['duration_ms']!=report['duration_ms']:
                raise AssertionError('Master samples or duration changed')
            import av
            with av.open(str(target/'master.mkv')) as movie:
                frames=list(movie.decode(video=0))
            for i,frame in enumerate(frames):
                if frame.pts*frame.time_base!=Fraction(i,25) or frame.duration*frame.time_base!=Fraction(1,25):
                    raise AssertionError('Master PTS/hold changed')
                rgba=master.rgba_frame(frame); actual=color_center(rgba,PROP)
                if list(actual)!=rows[name][i]['prop_px']:raise AssertionError('Decoded master prop differs')
            report['exports'][name]={'frames':len(frames),'duration_ms':result['duration_ms'],
                'rgba_mismatches':verified['rgba_mismatches'],'pts_mismatches':0,'hold_mismatches':0,
                'decoded_marker_mismatches':0,'master_sha256':hashlib.sha256((target/'master.mkv').read_bytes()).hexdigest()}
    for name,digest in original.items():
        if hashlib.sha256((out/name).read_bytes()).hexdigest()!=digest:raise AssertionError('Original input changed')
    (out/'proof.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True)
    parser.add_argument('--render',action='store_true');parser.add_argument('--shot-ms',type=int,default=800)
    args=parser.parse_args(); result=build_proof(args.out,render=args.render,shot_ms=args.shot_ms)
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','source_hashes')},indent=2))


if __name__=='__main__':main()
