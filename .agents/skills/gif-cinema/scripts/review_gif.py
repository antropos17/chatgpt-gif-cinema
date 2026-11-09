"""Build an offline, revision-bound visual review pack from a delivered GIF.

No model calls, automatic aesthetic decisions, source edits or external web assets.
Install the repository first: python -m pip install -e .
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
from pathlib import Path
import stat
import sys

from PIL import Image, ImageChops, ImageDraw, ImageSequence, ImageStat
from gif_cinema import cli

MAX_BYTES = 32 * 1024 * 1024
MAX_FRAMES = 512
MAX_PIXELS = 64 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024 * 1024
DECISIONS = {'pending', 'pass', 'repair'}
NOTICE = ('Technical checks and pixel differences do not judge identity, anatomy, '
          'contact or artistic quality. Recorded review is not user acceptance.')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_local(path, limit):
    """Bound the actual read; reject devices/FIFOs without waiting for a writer."""
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Input must be a regular local file')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'Input exceeds its {limit}-byte limit')
    return raw


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def load_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON field: {key}')
            result[key] = value
        return result
    value = json.loads(read_local(path, MAX_JSON_BYTES).decode('utf-8'), object_pairs_hook=unique_pairs)
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def decode(raw):
    """The descriptor scan happens before any Pillow allocation."""
    cli.check_gif_limits(raw, max_frames=MAX_FRAMES, max_pixel_frames=MAX_PIXELS, fixed_canvas=True)
    frames, delays = [], []
    try:
        with Image.open(io.BytesIO(raw)) as image:
            size, loop = image.size, image.info.get('loop')
            for frame in ImageSequence.Iterator(image):
                delay = frame.info.get('duration')
                if type(delay) is not int or delay < 20:
                    raise ValueError('Every decoded frame needs a delay of at least 20 ms')
                if frame.size != size or len(frames) >= MAX_FRAMES:
                    raise ValueError('GIF canvas or frame count exceeds the review limit')
                if (len(frames) + 1) * size[0] * size[1] > MAX_PIXELS:
                    raise ValueError('GIF exceeds the review pixel budget')
                frames.append(frame.convert('RGBA').copy())
                delays.append(delay)
    except (OSError, EOFError, Image.DecompressionBombError) as error:
        raise ValueError('Invalid or unsafe GIF') from error
    if len(frames) < 2:
        raise ValueError('Review requires an animated GIF with at least two frames')
    return frames, delays, loop


def flatten(frame, color):
    background = Image.new('RGB', frame.size, color)
    background.paste(frame, mask=frame.getchannel('A'))
    return background


def changes(frames):
    # Both backgrounds expose alpha changes. Sampling is diagnostic only.
    samples = [[flatten(frame, color).resize((128, 128)) for color in ('white', 'black')]
               for frame in frames]
    result = []
    for index, current in enumerate(samples):
        previous = samples[index - 1]
        score = max(sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
                    for a, b in zip(previous, current))
        result.append({'from_frame': (index - 1) % len(frames), 'to_frame': index,
                       'loop_seam': index == 0, 'pixel_mae_0_255': round(score, 6)})
    return result


def facts(raw, frames, delays, loop, purpose):
    errors = []
    unique = len({digest(flatten(frame, 'white').tobytes() + flatten(frame, 'black').tobytes())
                  for frame in frames})
    if unique < 2:
        errors.append('No visible frame changes on light or dark backgrounds')
    if purpose == 'sticker':
        if loop != 0:
            errors.append('Sticker profile requires an infinite loop (loop=0)')
        for index, frame in enumerate(frames):
            alpha = frame.getchannel('A')
            box = alpha.getbbox()
            if alpha.getextrema() != (0, 255):
                errors.append(f'Frame {index}: sticker needs transparent and opaque pixels')
            if not box or not (0 < box[0] < box[2] < frame.width and 0 < box[1] < box[3] < frame.height):
                errors.append(f'Frame {index}: sticker is blank or touches the canvas edge')
    return {'sha256': digest(raw), 'bytes': len(raw), 'width': frames[0].width,
            'height': frames[0].height, 'frame_count': len(frames), 'durations_ms': delays,
            'duration_ms': sum(delays), 'loop': loop, 'unique_visible_frames': unique,
            'purpose': purpose, 'technical_status': 'failed' if errors else 'passed', 'errors': errors}


def player(source_name, delays, loop, focus=False):
    """Local, paused-by-default player with exact decoded delays and native links."""
    checked = ' checked' if loop == 0 else ''
    template = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GIF frame review</title><style>
body{max-width:1200px;margin:32px auto;padding:0 16px;font:16px system-ui;background:#111827;color:#f3f4f6}
button,select{font:inherit;padding:8px;margin:3px}a{color:#93c5fd}figure{margin:0;min-width:0}
.views{display:grid;grid-template-columns:1fr 1fr;gap:20px}.matte{background:repeating-conic-gradient(#ddd 0% 25%,#fff 0% 50%) 0/24px 24px;overflow:auto}
img{display:block;max-width:100%;height:auto}body.native img{max-width:none}.note{color:#cbd5e1}@media(max-width:700px){.views{grid-template-columns:1fr}}
</style><h1>GIF frame review</h1><p>SOURCE</p><p>SHEETLINKS</p>
<p class="note">NOTICE Review every face, hand, prop and transition. Frame sheets are thumbnails; use native size for defects. The source GIF at left plays according to your browser. The frame player at right starts paused.</p>
<p><button id="play">Play</button><button id="prev">Previous</button><button id="next">Next</button>
<label><input id="repeat" type="checkbox"CHECKED>Repeat frame preview</label>
<label><input id="native" type="checkbox">Native display size</label>
<label>Background <select id="matte"><option value="checker">Checkerboard</option><option value="white">White</option><option value="black">Black</option></select></label></p>
<p id="status" aria-live="polite"></p><div class="views"><figure><figcaption>Unchanged delivered GIF</figcaption><div class="matte"><img src="animation.gif" alt="Delivered GIF"></div></figure>
<figure><figcaption>Decoded frame <a id="original" target="_blank" rel="noopener">Open native PNG</a> FOCUSLINK</figcaption><div class="matte"><img id="frame" alt="Selected decoded frame"></div></figure></div>
<p>At the end of one pass, playback stops unless Repeat is selected. Manual stepping wraps to inspect the last/first seam. Slow devices may not display every scheduled frame; use normal GIF playback and frame stepping together.</p>
<script>
const delays=DELAYS;let index=0,timer=null,playing=false;
const el=id=>document.getElementById(id);
function draw(){const path='frames/'+String(index).padStart(4,'0')+'.png';el('frame').src=path;el('original').href=path;if(el('focus'))el('focus').href='focus/'+String(index).padStart(4,'0')+'.png';el('status').textContent='Frame '+index+' of '+(delays.length-1)+' | '+delays[index]+' ms | starts at '+delays.slice(0,index).reduce((a,b)=>a+b,0)+' ms';}
function stop(){clearTimeout(timer);timer=null;playing=false;el('play').textContent='Play';}
function schedule(){timer=setTimeout(()=>{if(index===delays.length-1&&!el('repeat').checked){stop();return;}index=(index+1)%delays.length;draw();schedule();},delays[index]);}
el('play').onclick=()=>{if(playing){stop();return;}playing=true;el('play').textContent='Pause';schedule();};
for(const [id,step] of [['prev',-1],['next',1]])el(id).onclick=()=>{stop();index=(index+step+delays.length)%delays.length;draw();};
el('native').onchange=()=>document.body.classList.toggle('native',el('native').checked);
el('matte').onchange=()=>document.querySelectorAll('.matte').forEach(node=>node.style.background=el('matte').value==='checker'?'':el('matte').value);
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});draw();
</script></html>'''
    links = 'Thumbnail sheets: ' + ' · '.join(f'<a href="sheets/{i:03}.png">{i + 1}</a>' for i in range((len(delays) + 15) // 16))
    focus_link = '<a id="focus" target="_blank" rel="noopener">Native focus crop</a>' if focus else ''
    return (template.replace('NOTICE', html.escape(NOTICE))
            .replace('SHEETLINKS', links).replace('FOCUSLINK', focus_link)
            .replace('CHECKED', checked).replace('DELAYS', json.dumps(delays))
            .replace('SOURCE', html.escape(source_name))).encode('utf-8')


def extract(gif, output, focus=None, purpose='general'):
    gif, output = Path(gif), Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Review output must be a new directory; keep earlier reviews unchanged')
    if not isinstance(purpose, str) or purpose not in {'general', 'sticker'}:
        raise ValueError('Unknown review purpose')
    raw = read_local(gif, MAX_BYTES)
    frames, delays, loop = decode(raw)
    if focus is not None:
        if (not isinstance(focus, (tuple, list)) or len(focus) != 4 or
                any(type(value) is not int for value in focus) or
                not (0 <= focus[0] < focus[2] <= frames[0].width and 0 <= focus[1] < focus[3] <= frames[0].height)):
            raise ValueError('Focus box must be integer left/top/right/bottom inside the GIF')
        focus = list(focus)
    report = {'schema_version': 1, 'source_name': gif.name, 'media': facts(raw, frames, delays, loop, purpose),
              'focus': focus, 'transitions': changes(frames), 'notice': NOTICE, 'artifacts': {}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()  # Never reuse or replace an existing review.
    created = output.lstat()
    directories = {output: (created.st_dev, created.st_ino)}
    total = 0
    def check_directory(path):
        current = path.lstat()
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != directories[path]:
            raise ValueError('Review output directory changed; existing data was retained')
    def prepare_parent(parent):
        check_directory(output)
        if parent not in directories:
            parent.mkdir()  # Never adopt an unexpectedly existing child directory.
            created = parent.lstat()
            directories[parent] = (created.st_dev, created.st_ino)
        check_directory(parent)
        check_directory(output)
    def save(name, data, track=True):
        nonlocal total
        total += len(data)
        if total > MAX_OUTPUT_BYTES:
            raise ValueError('Review output exceeds 512 MiB; use a shorter or smaller source')
        path = output / name
        prepare_parent(path.parent)
        with path.open('xb') as stream:
            stream.write(data)
        if track:
            report['artifacts'][name] = digest(data)
    def save_image(name, image):
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        save(name, stream.getvalue())
    # Retain partial output on failure. This path can be renamed/replaced by
    # another process, so recursive rollback could delete unrelated data.
    save('animation.gif', raw)
    save('index.html', player(gif.name, delays, loop, bool(focus)))
    for index, frame in enumerate(frames):
        save_image(f'frames/{index:04}.png', frame)
        if focus:
            save_image(f'focus/{index:04}.png', frame.crop(focus))
    # Bounded thumbnail sheets, never one enormous native-size contact sheet.
    for start in range(0, len(frames), 16):
        batch = frames[start:start + 16]
        sheet = Image.new('RGB', (4 * 208, ((len(batch) + 3) // 4) * 232), '#edf2f7')
        pen = ImageDraw.Draw(sheet)
        for offset, frame in enumerate(batch):
            thumb = flatten(frame, 'white')
            thumb.thumbnail((192, 192))
            x, y = (offset % 4) * 208 + 8, (offset // 4) * 232 + 8
            sheet.paste(thumb, (x, y + 24))
            pen.text((x, y), f'{start + offset:04} | {delays[start + offset]} ms', fill='#111827')
        save_image(f'sheets/{start // 16:03}.png', sheet)
    audit_raw = json_bytes(report)
    save('audit.json', audit_raw, track=False)
    review = {'schema_version': 1, 'audit_sha256': digest(audit_raw), 'gif_sha256': digest(raw),
              'reviewer': '', 'frames': [{'index': i, 'decision': 'pending', 'notes': ''} for i in range(len(frames))],
              'playback': 'pending', 'loop_seam': 'pending', 'user_acceptance': 'pending', 'notes': ''}
    save('review.json', json_bytes(review), track=False)
    for directory in directories:
        check_directory(directory)
    return report


def check(output, review_path=None, gif=None):
    output = Path(output)
    audit_path = output / 'audit.json'
    audit = load_json(audit_path)
    review = load_json(review_path or output / 'review.json')
    if type(audit.get('schema_version')) is not int or audit['schema_version'] != 1 or type(review.get('schema_version')) is not int or review['schema_version'] != 1:
        raise ValueError('Unsupported audit/review schema')
    if review.get('audit_sha256') != digest(read_local(audit_path, MAX_JSON_BYTES)):
        raise ValueError('Audit changed after review preparation; extract a fresh review pack')
    raw = read_local(gif or output / 'animation.gif', MAX_BYTES)
    if review.get('gif_sha256') != digest(raw):
        raise ValueError('GIF changed after extraction; review this revision again')
    frames, delays, loop = decode(raw)
    media = audit.get('media')
    if not isinstance(media, dict) or not isinstance(media.get('purpose'), str) or media.get('purpose') not in {'general', 'sticker'} or media != facts(raw, frames, delays, loop, media['purpose']):
        raise ValueError('Audit media facts do not match the actual GIF')
    artifacts = audit.get('artifacts')
    expected = {'animation.gif', 'index.html'} | {f'frames/{i:04}.png' for i in range(len(frames))} | {f'sheets/{i:03}.png' for i in range((len(frames) + 15) // 16)}
    if audit.get('focus') is not None:
        expected |= {f'focus/{i:04}.png' for i in range(len(frames))}
    if not isinstance(artifacts, dict) or set(artifacts) != expected:
        raise ValueError('Review artifact list is incomplete or unexpected')
    for name, expected_hash in artifacts.items():
        path = output / name
        if path.is_symlink() or not path.resolve().is_relative_to(output.resolve()):
            raise ValueError('Review artifact must stay inside its output directory')
        if digest(read_local(path, MAX_OUTPUT_BYTES)) != expected_hash:
            raise ValueError(f'Review artifact changed: {name}')
    if media['technical_status'] != 'passed':
        raise ValueError('Technical review failed: ' + '; '.join(media['errors']))
    reviewer = review.get('reviewer')
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 200:
        raise ValueError('Review needs a named reviewer')
    rows = review.get('frames')
    if not isinstance(rows, list) or len(rows) != len(frames):
        raise ValueError('Review must cover every decoded frame exactly once')
    indexes = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get('index')) is not int or not isinstance(row.get('decision'), str) or row.get('decision') not in DECISIONS or not isinstance(row.get('notes'), str):
            raise ValueError('Invalid frame review entry')
        indexes.append(row['index'])
        if row['decision'] != 'pass':
            raise ValueError(f"Frame {row['index']} is pending or needs repair")
    if sorted(indexes) != list(range(len(frames))):
        raise ValueError('Review must cover every decoded frame exactly once')
    if review.get('playback') != 'pass' or review.get('loop_seam') != 'pass':
        raise ValueError('Playback and last/first seam need explicit visual review')
    acceptance = review.get('user_acceptance')
    if not isinstance(acceptance, str) or acceptance not in {'pending', 'accepted', 'rejected'}:
        raise ValueError('User acceptance must be pending, accepted or rejected')
    return {'technical_status': 'passed', 'visual_review_record': 'complete', 'reviewer': reviewer,
            'user_acceptance_record': acceptance, 'gif_sha256': digest(raw), 'notice': NOTICE}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('extract', help='Extract every frame into a new local review directory')
    export.add_argument('gif', type=Path)
    export.add_argument('output', type=Path)
    export.add_argument('--focus', nargs=4, type=int, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'))
    export.add_argument('--purpose', choices=['general', 'sticker'], default='general')
    verify = commands.add_parser('check', help='Check recorded review completeness and exact artifact hashes')
    verify.add_argument('output', type=Path)
    verify.add_argument('--review', type=Path)
    verify.add_argument('--gif', type=Path, help='Also check the current delivered GIF, not only the saved copy')
    args = parser.parse_args(argv)
    try:
        if args.command == 'extract':
            report = extract(args.gif, args.output, args.focus, args.purpose)
            print(json.dumps(report['media'], indent=2))
            return 0 if report['media']['technical_status'] == 'passed' else 1
        print(json.dumps(check(args.output, args.review, args.gif), indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
