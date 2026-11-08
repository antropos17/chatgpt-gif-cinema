#!/usr/bin/env python3
"""Offline, fixed three-shot editorial demo. No generation or take replacement.

This is a demonstrator, not a general story editor or core render API. All source
poses play once, at their original timing. Result holds and chapter transitions
are reported separately. Run from the repository root with --out a NEW path.
"""
from __future__ import annotations

import argparse
import io
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import PIL
from PIL import Image, ImageDraw, ImageFont
from gif_cinema.cli import read_gif_bytes, validate_gif

FPS, WIDTH, HEIGHT = 25, 1024, 576
START_HOLD, END_HOLD, TRANSITION = 400, 800, 480
ART = (524, 60, 980, 516)
BACKGROUND, INK, MUTED, ACCENT = '#13191d', '#f4eee4', '#a4afaF', '#e5bc87'
SHOTS = [
    {'file': 'shot-01.gif', 'label': 'SIGNAL', 'title': ['Hello,', 'out there.'],
     'caption': ['An astronaut sends a quiet', 'greeting into the dark.']},
    {'file': 'shot-02.gif', 'label': 'REPLY', 'title': ['A light', 'answers.'],
     'caption': ['Beyond the silence,', 'a small star responds.']},
    {'file': 'shot-03.gif', 'label': 'CONNECTION', 'title': ['Someone', 'heard.'],
     'caption': ['A hand comes to the heart.', 'The silence feels different now.']},
]
# Use only Pillow's own default font; no unpublished font loader or new font asset.
# The scalable default is available from Pillow 10.1. Core installation still
# permits Pillow 10.0; this optional demo reports its extra requirement explicitly.
@lru_cache(maxsize=16)
def load_font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError as exc:
        raise ValueError('This optional story demo requires Pillow >= 10.1 for scalable text') from exc



def smooth(x):
    x = min(1.0, max(0.0, x))
    return x*x*x*(x*(x*6-15)+10)


def source_index(delays, local_ms):
    """Never loop, reverse or skip native action. Holds clamp at both ends."""
    action_ms = max(0, local_ms - START_HOLD)
    cumulative = 0
    for index, delay in enumerate(delays):
        cumulative += delay
        if action_ms < cumulative:
            return index
    return len(delays) - 1


def timeline(sources):
    output, pages, cursor = [], [], 0
    for shot, (_, delays, _) in enumerate(sources):
        duration = START_HOLD + sum(delays) + END_HOLD
        if duration % 40:
            raise ValueError('This fixed example requires exact 40ms output timing')
        count = duration // 40
        pages.append({'shot': shot + 1, 'start_ms': cursor * 40, 'end_ms': (cursor + count) * 40,
                      'action_ms': sum(delays), 'start_hold_ms': START_HOLD, 'end_hold_ms': END_HOLD})
        for local in range(count):
            output.append({'kind': 'page', 'shot': shot, 'local_ms': local * 40,
                           'source_index': source_index(delays, local * 40),
                           'page_progress': local / (count - 1)})
        cursor += count
        if shot + 1 < len(sources):
            for step in range(TRANSITION // 40):
                output.append({'kind': 'transition', 'from': shot, 'to': shot + 1,
                               'progress': (step + 1) / (TRANSITION // 40 + 1),
                               'from_source_index': len(delays) - 1, 'to_source_index': 0})
            cursor += TRANSITION // 40
    return output, pages


def draw_text(im, at, text, size, color, opacity=1):
    layer = Image.new('RGBA', im.size)
    d = ImageDraw.Draw(layer)
    d.text(at, text, font=load_font(size), fill=color)
    if opacity < 1:
        layer.putalpha(layer.getchannel('A').point(lambda v: round(v * opacity)))
    im.alpha_composite(layer)


def render_page(number, source, local_ms, progress, still=False):
    page = SHOTS[number]
    canvas = Image.new('RGBA', (WIDTH, HEIGHT), BACKGROUND)
    draw_text(canvas, (56, 49), 'GIF CINEMA  /  A SHORT STORY', 12, MUTED)
    draw_text(canvas, (56, 133), f'{number + 1:02d}  /  {page["label"]}', 13, ACCENT)
    enter = 1 if still or number > 0 else smooth(local_ms / 360)
    for row, line in enumerate(page['title']):
        draw_text(canvas, (56, round(178 + row * 60 + 12*(1-enter))), line, 49, INK, enter)
    reveal = 1 if still or number > 0 else smooth((local_ms - 200) / 360)
    for row, line in enumerate(page['caption']):
        draw_text(canvas, (58, round(338 + row * 29 + 6*(1-reveal))), line, 18, MUTED, reveal)
    d = ImageDraw.Draw(canvas)
    d.line((58, 455, 438, 455), fill='#354147', width=1)
    for index in range(3):
        x = 58 + index * 35
        d.line((x, 479, x+23, 479), fill=ACCENT if index == number else '#435057', width=3)
    draw_text(canvas, (58, 500), 'A REPLY FROM THE STARS', 11, MUTED)
    draw_text(canvas, (915, 536), f'{number+1:02d} / 03', 11, MUTED)
    # The native source art stays intact. A very slight editorial push-in affects
    # the entire image, not the limbs, face, star, lighting, or native pose cadence.
    zoom = 1 + .025 * smooth(progress)
    scale = max(456 / source.width, 456 / source.height) * zoom
    matrix = (1/scale, 0, source.width/2 - 228/scale,
              0, 1/scale, source.height/2 - 228/scale)
    art = source.convert('RGB').transform((456, 456), Image.Transform.AFFINE,
                                         matrix, resample=Image.Resampling.BICUBIC)
    mask = Image.new('L', (456,456)); ImageDraw.Draw(mask).rounded_rectangle((0,0,455,455), radius=10, fill=255)
    canvas.paste(art, ART[:2], mask)
    ImageDraw.Draw(canvas).rounded_rectangle(ART, radius=10, outline='#384044', width=1)
    return canvas.convert('RGB')


def render_transition(old, new, progress):
    """Editorial card slide; old last and new first poses are frozen. No morph."""
    ease = smooth(progress)
    frame = Image.new('RGB', (WIDTH, HEIGHT), BACKGROUND)
    frame.paste(old, (-round(WIDTH * ease), 0))
    frame.paste(new, (WIDTH-round(WIDTH * ease), 0))
    return frame


def run(command):
    return subprocess.run(command, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=300).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(out):
    out = out.absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Output must be a new directory without symlinks')
    source_dir = ROOT / '.agents/skills/gif-cinema/assets/example'
    paths = [source_dir / shot['file'] for shot in SHOTS]
    before = {path.name: sha(path) for path in paths}
    load_font(12)  # Reject an unsupported Pillow before any output work.
    sources = [validate_gif(io.BytesIO(read_gif_bytes(path))) for path in paths]
    if any(len(frames) != 16 or delays != [160] * 16 or
           any(frame.size != (512, 512) for frame in frames) for frames, delays, _ in sources):
        raise ValueError('Fixed demo requires the three reviewed 16-frame, 160ms sources')
    samples, pages = timeline(sources)
    out.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(prefix='.story-stage-', dir=out.parent) as tmp:
        stage = Path(tmp)
        frames_dir = stage / 'frames'; frames_dir.mkdir()
        sheet = Image.new('RGB', (1024, 3 * 220), BACKGROUND)
        endpoint_pages = []
        for number, (frames, delays, _) in enumerate(sources):
            endpoint_pages.append((render_page(number, frames[0], 0, 0, True),
                                   render_page(number, frames[-1], 3760, 1, True)))
        saved_indices = [10, 42, 90, 105, 148, 196, 211, 250, len(samples)-1]
        for index, sample in enumerate(samples):
            if sample['kind'] == 'page':
                number = sample['shot']
                frame = render_page(number, sources[number][0][sample['source_index']],
                                    sample['local_ms'], sample['page_progress'])
            else:
                frame = render_transition(endpoint_pages[sample['from']][1],
                                          endpoint_pages[sample['to']][0], sample['progress'])
            frame.save(frames_dir / f'{index:04d}.png')
            if index in saved_indices:
                slot = saved_indices.index(index)
                thumb = frame.resize((341,192),Image.Resampling.LANCZOS)
                sheet.paste(thumb,((slot%3)*341,(slot//3)*220))
                ImageDraw.Draw(sheet).text(((slot%3)*341+6,(slot//3)*220+198),f'{index/FPS:.2f} s',fill=INK)
            if index == 148:
                frame.save(stage / 'poster.png')
        sheet.save(stage/'contact-sheet.png')
        candidate = stage / 'a-reply-from-the-stars.mp4'
        run(['ffmpeg','-v','error','-nostdin','-framerate',str(FPS),'-i',str(frames_dir/'%04d.png'),
             '-frames:v',str(len(samples)),'-c:v','libx264','-crf','18','-pix_fmt','yuv420p',
             '-movflags','+faststart','-map_metadata','-1',str(candidate)])
        result=json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-of','json',str(candidate)]))
        video=result['streams'][0]
        expected=len(samples)/FPS
        if (len(result['streams']) != 1 or video['codec_name'] != 'h264' or
            (video['width'],video['height']) != (WIDTH,HEIGHT) or
            int(video['nb_read_frames']) != len(samples) or video['avg_frame_rate'] != '25/1' or
            abs(float(video['duration'])-expected) > .001):
            raise ValueError('Export failed technical verification')
        run(['ffmpeg','-v','error','-xerror','-nostdin','-i',str(candidate),'-f','null','-'])
        if before != {path.name:sha(path) for path in paths}:
            raise ValueError('Source changed; no deliverable published')
        # Freeze full-size original endpoints for review of both actual source cuts.
        joins=Image.new('RGB',(1024,2*550),BACKGROUND)
        for join in range(2):
            joins.paste(sources[join][0][-1].convert('RGB'),(0,join*550+38))
            joins.paste(sources[join+1][0][0].convert('RGB'),(512,join*550+38))
            ImageDraw.Draw(joins).text((12,join*550+12),f'JOIN {join+1}: original last -> original first; human review required',fill=INK)
        joins.save(stage/'original-joins.png')
        receipt={
            'title':'A Reply from the Stars', 'builder':'tools/build_story_demo.py',
            'pillow_version':PIL.__version__,'font':'Pillow scalable default (no added font assets)',
            'new_provider_calls':0,'native_source_drawings':48,'native_action_seconds':7.68,
            'start_holds_seconds':1.2,'result_holds_seconds':2.4,'editorial_transitions_seconds':.96,
            'export_seconds':expected,'export_fps':FPS,'export_frames':len(samples),
            'audio':'silent','repeat_count_per_shot':1,'subject_interpolation':False,
            'editorial_design':'English titles/captions, 2.5% whole-image push, frozen-endpoint chapter slide',
            'sources_unchanged':True,'source_sha256':before,'pages':pages,'samples':samples,
            'visual_status':'human-review-required',
            'limitations':['Source poses retain native 6.25 drawings/s; 25fps describes export/design only.',
                           'The framing cuts and hand/suit details differ. Chapter design does not repair those differences.',
                           'Three actions are not enough for a genuinely longer story. No repetition or reverse padding.',
                           'This fixed example is not an automatic director, GUI, layered GIF editor, or generation pipeline.'],
            'verification':result,
            'outputs':{name:sha(stage/name) for name in ['a-reply-from-the-stars.mp4','poster.png','contact-sheet.png','original-joins.png']}}
        (stage/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        out.mkdir()
        for name in [*receipt['outputs'],'receipt.json']:
            (stage/name).replace(out/name)
    return {'out':str(out),'seconds':expected,'frames':len(samples),'provider_calls':0}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.out),indent=2))
