#!/usr/bin/env python3
"""Reproduce dropped GIF drawings and compare real exports, without API calls.

Requires the optional lossless extra and FFmpeg/ffprobe. This is a colored timing
fixture, not newly commissioned animation or an automatic story-quality test.
"""
import argparse
from fractions import Fraction
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw, ImageFont
from gif_cinema import cli, master, factory

COLORS = ['red', 'yellow', 'blue', 'lime', 'magenta', 'cyan', 'black']
DELAYS = [30, 70, 20, 20, 30, 70, 20]


def decoded(path):
    info = json.loads(cli.run_media(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
        '-show_entries', 'frame=pts_time,duration_time,pkt_duration_time', '-of', 'json', str(path)]).stdout)['frames']
    raw = cli.run_media(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path), '-fps_mode', 'passthrough',
                         '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']).stdout
    stride = 48 * 48 * 3
    if len(raw) != len(info) * stride: raise ValueError('Unexpected comparison decode size')
    result = []
    for index, item in enumerate(info):
        image = Image.frombytes('RGB', (48, 48), raw[index * stride:(index + 1) * stride])
        delay = item.get('duration_time', item.get('pkt_duration_time'))
        if delay is None: raise ValueError('FFprobe omitted the decoded frame duration')
        result.append({'start_ms': int(Fraction(item['pts_time']) * 1000),
                       'duration_ms': int(Fraction(delay) * 1000),
                       'rgb': list(image.getpixel((24, 24)))})
    return result


def run(out):
    if out.exists(): raise ValueError('Use a new demo directory')
    out.mkdir(parents=True)
    paths = []
    for name, colors, delays in [('a', COLORS[:3], DELAYS[:3]), ('b', COLORS[3:], DELAYS[3:])]:
        path = out / (name + '.gif')
        frames = [Image.new('RGB', (48, 48), color) for color in colors]
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=delays, optimize=False)
        paths.append(path)
    proof = master.build(paths, out / 'preserved', preview=True)
    rows = []
    cursor = 0
    for color, delay in zip(COLORS, DELAYS):
        rows.append({'start_ms': cursor, 'duration_ms': delay, 'rgb': list(Image.new('RGB', (1, 1), color).getpixel((0, 0)))})
        cursor += delay
    cases = [('Declared GIF drawings', rows)]
    for fps in [25, 5]:
        target = out / f'current-{fps}fps.mp4'
        cli.film(argparse.Namespace(clips=paths, output=target, width=48, height=48, fps=fps, audio=None, force=False))
        cases.append((f'Current {fps} fps export', decoded(target)))
    cases.append(('New 100 Hz viewing copy', decoded(out / 'preserved/preview.mp4')))
    font_file = ROOT / 'gif_cinema/assets/fonts/NotoSans-Regular.ttf'
    font = ImageFont.truetype(str(font_file), 18)
    small = ImageFont.truetype(str(font_file), 13)
    canvas = Image.new('RGB', (1120, 520), '#131821'); draw = ImageDraw.Draw(canvas)
    draw.text((30, 20), 'Timing evidence from actual decoded exports', font=font, fill='white')
    draw.text((30, 52), 'Seven original drawings. Short blue / magenta phases must not disappear.', font=small, fill='#c4ccd7')
    for row, (label, frames) in enumerate(cases):
        y = 100 + row * 86
        end = max(f['start_ms'] + f['duration_ms'] for f in frames)
        draw.text((30, y), label, font=font, fill='white')
        draw.text((30, y + 28), f'{len(frames)} decoded frames / {end} ms', font=small, fill='#c4ccd7')
        for item in frames:
            x = 320 + item['start_ms'] * 1.8
            x2 = 320 + (item['start_ms'] + item['duration_ms']) * 1.8
            draw.rectangle((round(x), y, round(x2) - 1, y + 46), fill=tuple(item['rgb']))
        draw.rectangle((320, y, 1040, y + 46), outline='#677080')
    for t in (0, 100, 200, 260, 300, 400):
        draw.text((320 + t * 1.8 - 10, 450), str(t), font=small, fill='white')
    draw.text((30, 485), 'Verified master: 7 frames / 260 ms; zero RGBA, PTS or hold mismatches. MP4 is lossy and adds no new motion.', font=small, fill='#c4ccd7')
    canvas.save(out / 'comparison.png')
    evidence = {'master': proof['verification'], 'cases': [{'label': label, 'frames': frames} for label, frames in cases],
                'note': 'Diagnostic fixture only. Video RGB differs because H.264 is lossy; master comparison uses complete RGBA hashes.'}
    (out / 'comparison.json').write_bytes(factory.json_bytes(evidence))
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.out), indent=2))
