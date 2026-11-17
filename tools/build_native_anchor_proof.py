#!/usr/bin/env python3
"""Original native-clock marker proof; no new drawings or perceptual acceptance."""
import argparse
import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat
from gif_cinema import attachments, layers, motion
from tools.build_pose_anchor_proof import color_center, HAND, PROP


def make_scene(root, *, named=True, fps=25, playback='loop'):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    atlas = Image.new('RGBA', (48, 16))
    draw = ImageDraw.Draw(atlas)
    frames = []
    for n, (x, delay) in enumerate(zip((4, 8, 12), (40, 60, 180))):
        draw.rectangle((n*16+6, 3, n*16+9, 5), fill=(130, 140, 155, 255))
        draw.rectangle((n*16+x-1, 7, n*16+x, 8), fill=HAND)
        frames.append({'rect': [n*16, 0, 16, 16], 'duration_ms': delay,
                       'anchors': {'hand': [x/16, .5]}})
    atlas.save(root/'poses.png')
    scene = {'format': layers.FORMAT, 'schema_version': 1, 'title': 'Native clock marker proof',
        'width': 64, 'height': 64, 'duration_ms': 480, 'fps': fps, 'loop': False,
        'layers': [{'id': 'actor', 'type': 'sprites', 'source': 'poses.png', 'size': [16, 16],
                    'frames': frames, 'sampling': 'pixel', 'playback': playback, 'source_range_ms': [30, 270]},
                   {'id': 'prop', 'type': 'rect', 'size': [4, 4], 'fill': '#ff7043',
                    'attachments': [{'start_ms': 0, 'end_ms': 480, 'parent': 'actor',
                                     **({'anchor': 'hand'} if named else {'point': [.25, .5]})}]}]}
    path = root/'scene.json'; path.write_text(json.dumps(scene, indent=2)+'\n')
    return path


def build_proof(out, *, render=False):
    out = Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Use a new non-symlink proof output directory')
    report = {'format': 'gif-cinema-native-anchor-proof-v1', 'provider_calls': 0, 'cases': {},
        'scope': 'Original technical markers, not a cartoon. Anchors follow the selected source drawing, '\
                 'without changing actor pixels or its sampling clock. 25/50fps may omit short drawings. '\
                 'No optical flow, face lock, hand detection or new poses. PNG retains RGBA; GIF/MP4 flatten it.'}
    sheet = Image.new('RGB', (960, 568), '#f5f7fa'); draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=16)
    draw.text((12, 8), 'Native delays 40/60/180ms | trim [30,270) | existing 25fps sampler', fill='#18212e', font=font)
    for fps, playback in ((25, 'loop'), (50, 'once')):
        pair = {}
        for name in ('fixed', 'named'):
            case = f'{fps}-{playback}-{name}'; path = make_scene(out/case, named=name=='named', fps=fps, playback=playback)
            sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in path.parent.iterdir()}
            prepared = layers.prepare_scene(path); period = 1000//fps
            rows, expected = [], []
            for t in range(0, 480, period):
                frame, states = layers.render_at(prepared, t); actor, _ = layers.render_at(prepared, t, only_layer='actor')
                hand, prop = color_center(actor, HAND), color_center(frame, PROP)
                rows.append({'time_ms': t, 'source_index': states['actor']['source_index'],
                    'actor_rgba_sha256': hashlib.sha256(actor.tobytes()).hexdigest(),
                    'frame_rgba_sha256': hashlib.sha256(frame.tobytes()).hexdigest(),
                    'marker_gap_px': math.dist(hand, prop)})
                expected.append(frame)
            pair[name] = rows
            fact = {'fps': fps, 'playback': playback, 'frames': len(rows), 'duration_ms': 480,
                'source_delays_ms': [40, 60, 180], 'source_range_ms': [30, 270],
                'max_marker_gap_px': max(r['marker_gap_px'] for r in rows), 'rows': rows,
                'source_hashes': sources, 'attachment_review': attachments.review(prepared)}
            if fps == 25:
                for col, i in enumerate((0, 1, 2, 6, 11)):
                    y = 36 + (0 if name == 'fixed' else 1)*264
                    display = motion.flatten(expected[i], '#eef1f6').resize((192, 192), Image.Resampling.NEAREST)
                    sheet.paste(display, (col*192, y))
                    draw.text((col*192+6, y+198), f'{name} {rows[i]["time_ms"]}ms', fill='#18212e', font=font)
                    draw.text((col*192+6, y+220), f'gap {rows[i]["marker_gap_px"]:g}px', fill='#18212e', font=font)
            if render:
                built = out/(case+'-build'); receipt = layers.render_scene(path, built)
                for i, image in enumerate(expected):
                    with Image.open(built/'frames'/f'{i:04}.png') as png:
                        if png.convert('RGBA').tobytes() != image.tobytes(): raise AssertionError('PNG RGBA differs')
                with Image.open(built/'preview.gif') as gif:
                    # Seek by output timestamp, not descriptor count: equal frames may merge.
                    decoded, elapsed = [], 0
                    for i in range(gif.n_frames):
                        gif.seek(i); delay = gif.info['duration']; decoded.append((elapsed, elapsed+delay, gif.convert('RGB'))); elapsed += delay
                    if elapsed != 480: raise AssertionError('GIF duration differs')
                    for row, image in zip(rows, expected):
                        actual = next(image for start,end,image in decoded if start<=row['time_ms']<end)
                        if actual.tobytes() != motion.flatten(image, prepared['scene']['matte']).tobytes(): raise AssertionError('Marker GIF pixels differ')
                import av
                maes = []
                with av.open(str(built/'preview.mp4')) as movie:
                    for i, frame in enumerate(movie.decode(video=0)):
                        if i >= len(expected) or frame.pts*frame.time_base != Fraction(i, fps) or frame.duration*frame.time_base != Fraction(1, fps):
                            raise AssertionError('MP4 frame clock differs')
                        delta = ImageChops.difference(frame.to_image().convert('RGB'), motion.flatten(expected[i], prepared['scene']['matte']))
                        maes.append(sum(ImageStat.Stat(delta).mean)/3)
                if len(maes)!=len(expected): raise AssertionError('MP4 frame count differs')
                fact['export'] = {'png_rgba_mismatches': 0, 'gif_flattened_rgb_mismatches': 0,
                    'mp4_frames': len(maes), 'mp4_pts_mismatches': 0, 'mp4_hold_mismatches': 0,
                    'mp4_max_frame_rgb_mae': max(maes), 'mp4_is_lossy': True, 'audio': 'none'}
            for name, digest in sources.items():
                if hashlib.sha256((path.parent/name).read_bytes()).hexdigest()!=digest: raise AssertionError('Input changed')
            report['cases'][case] = fact
        for left, right in zip(pair['fixed'], pair['named']):
            for key in ('time_ms', 'source_index', 'actor_rgba_sha256'):
                if left[key]!=right[key]: raise AssertionError('Actor pixels/clock changed')
        if max(r['marker_gap_px'] for r in pair['fixed']) != 8 or any(r['marker_gap_px'] for r in pair['named']):
            raise AssertionError('Unexpected marker geometry')
    report['actor_pixels_and_clock_unchanged'] = True
    sheet.save(out/'comparison.png'); (out/'proof.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--out', required=True); parser.add_argument('--render', action='store_true')
    args=parser.parse_args(); result=build_proof(args.out, render=args.render)
    print(json.dumps({'provider_calls': result['provider_calls'], 'actor_pixels_and_clock_unchanged': result['actor_pixels_and_clock_unchanged'],
        'cases': {k: {x:v for x,v in row.items() if x not in ('rows','source_hashes','attachment_review')} for k,row in result['cases'].items()}}, indent=2))
