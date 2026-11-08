"""Compile an author-written storyboard into portable GIF Cinema inputs, offline.

No provider requests, credential reads, interpolation, or invented character poses.
"""
import argparse
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageDraw, ImageFont
from gif_cinema import cli, render

MAX_INPUT = 1024 * 1024
MAX_PROJECT_BYTES = 512 * 1024 * 1024
MAX_TITLE_PIXELS = 32 * 1024 * 1024


def read_json(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError('Storyboard exceeds 1 MiB')
    return json.loads(raw.decode('utf-8-sig'))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def check_text(value, label, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{label} must be nonempty text, at most {limit} characters')
    return value


def only(value, keys, label):
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ValueError(f'{label}: invalid object or unknown fields')


def integer(value, label, low, high):
    return render.integer(value, label, low, high)


def font_at(size, font_path=None):
    if font_path:
        return ImageFont.truetype(str(font_path), size)
    try:
        return ImageFont.truetype('DejaVuSans.ttf', size)
    except OSError:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            # Pillow 10.0 has only the fixed-size bitmap default. Keep the
            # runtime's Pillow>=10 compatibility rather than requiring a font.
            return ImageFont.load_default()


def title_frames(spec, width, height, font_path=None):
    """Text enters once, with an accent rule, then holds. Never loops/reverses."""
    only(spec, {'text', 'subtitle', 'duration_ms', 'background', 'foreground', 'accent'}, 'title')
    text = check_text(spec.get('text'), 'title.text', 100)
    subtitle = spec.get('subtitle', '')
    if not isinstance(subtitle, str):
        raise ValueError('title.subtitle must be text')
    if subtitle:
        check_text(subtitle, 'title.subtitle', 140)
    duration = integer(spec.get('duration_ms', 2000), 'title.duration_ms', 800, 6000)
    if duration % 100:
        raise ValueError('Title duration must be a multiple of 100 ms (10 fps)')
    count = duration // 100
    if count * width * height > MAX_TITLE_PIXELS:
        raise ValueError('Title exceeds the 32-megapixel drawing budget; lower dimensions or duration')
    size = max(12, round(min(width, height) * .085))
    probe = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    font = font_at(size, font_path)
    while probe.textlength(text, font=font) > width * .82 and size > 12:
        size -= 1
        font = font_at(size, font_path)
    small = font_at(max(12, round(min(width, height) * .04)), font_path)
    if (probe.textlength(text, font=font) > width * .82 or
            probe.textlength(subtitle, font=small) > width * .84):
        raise ValueError('Title/subtitle does not fit; shorten the text or use a wider canvas')
    result = []
    for i in range(count):
        image = Image.new('RGB', (width, height), spec.get('background', '#111827'))
        draw = ImageDraw.Draw(image)
        phase = min(1., i / 5.)
        ease = 1. - (1. - phase) ** 3
        x = width * .09 - (1. - ease) * width * .06
        y = height * .42
        draw.text((x, y), text, font=font, fill=spec.get('foreground', '#F9FAFB'))
        rule_y = y + size * 1.5
        draw.rectangle((width * .09, rule_y, width * .09 + max(1, width * .3 * ease),
                        rule_y + max(2, height * .008)), fill=spec.get('accent', '#FBBF24'))
        if subtitle and phase >= .6:
            draw.text((width * .09, rule_y + size * .55), subtitle, font=small,
                      fill=spec.get('foreground', '#F9FAFB'))
        result.append(image)
    return result, [100] * count


def check_sha256(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError(f'{label} must be a lowercase SHA-256 digest')
    return value


def load_takes(path):
    """Read explicit caller-reviewed selections; never choose a candidate."""
    data = read_json(path)
    only(data, {'schema_version', 'takes'}, 'takes manifest')
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('takes schema_version must be 1')
    values = data.get('takes')
    if not isinstance(values, list) or not 1 <= len(values) <= 64:
        raise ValueError('takes must contain 1..64 entries')
    result = {}
    for entry in values:
        only(entry, {'shot_id', 'source', 'sha256', 'review_notes'}, 'take')
        sid = check_text(entry.get('shot_id'), 'take.shot_id', 40)
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}', sid):
            raise ValueError('Take shot ids must be safe ASCII identifiers')
        if sid.lower() in {key.lower() for key in result}:
            raise ValueError('Duplicate take shot id')
        check_text(entry.get('source'), 'take.source')
        check_text(entry.get('review_notes'), 'take.review_notes')
        check_sha256(entry.get('sha256'), 'take.sha256')
        result[sid] = entry
    return result


def compile_story(path, out, font_path=None, takes_path=None):
    path, out = path.resolve(), out.resolve()
    if out.exists():
        raise ValueError('Output must be a new directory; previous projects are never overwritten')
    data = read_json(path)
    takes_path = Path(takes_path).resolve() if takes_path else None
    takes = load_takes(takes_path) if takes_path else {}
    portable = copy.deepcopy(data)
    only(data, {'schema_version', 'title', 'premise', 'ending', 'style_bible', 'characters',
                'props', 'width', 'height', 'fps', 'shots'}, 'story')
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('story schema_version must be 1')
    for key in ('title', 'premise', 'ending', 'style_bible'):
        check_text(data.get(key), key)
    width = integer(data.get('width', 512), 'width', 64, 1280)
    height = integer(data.get('height', 512), 'height', 64, 1280)
    fps = integer(data.get('fps', 25), 'fps', 1, 60)
    if width % 2 or height % 2:
        raise ValueError('Dimensions must be even')
    divisor = math.gcd(width, height)
    if max(width // divisor, height // divisor) > 99:
        raise ValueError('Reduced ratio terms must fit the runtime range 1..99')
    bible = data['style_bible']
    for collection in ('characters', 'props'):
        values = data.get(collection, [])
        if not isinstance(values, list) or len(values) > 32:
            raise ValueError(f'{collection} must contain at most 32 entries')
        identifiers = set()
        for value in values:
            only(value, {'id', 'description', 'initial_state'}, collection)
            for key in ('id', 'description'):
                check_text(value.get(key), f'{collection}.{key}')
            if value['id'] in identifiers:
                raise ValueError(f'Duplicate {collection} id')
            identifiers.add(value['id'])
            if 'initial_state' in value:
                check_text(value['initial_state'], f'{collection}.initial_state')
            bible += f"\n{collection}: {value['id']}: {value['description']}"
    shots = data.get('shots')
    if not isinstance(shots, list) or not 1 <= len(shots) <= 64:
        raise ValueError('shots must contain 1..64 entries')
    for sid in takes:
        matches = [shot for shot in shots if isinstance(shot, dict) and shot.get('id') == sid]
        if not matches:
            raise ValueError(f'Take references an unknown shot id: {sid}; ids are case-sensitive')
        if len(matches) != 1 or set(matches[0]) & {'source', 'generate', 'title'} != {'generate'}:
            raise ValueError(f'{sid}: takes can fill generated shots only; existing sources and titles are preserved')
    base = {'schema_version': 1, 'title': data['title'], 'style_bible': bible,
            'ratio': f'{width // divisor}:{height // divisor}', 'width': width, 'height': height, 'fps': fps}
    # Stage only in a new project-specific directory. Failure cannot alter an existing project.
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.story-stage-', dir=out.parent) as temporary:
        root = Path(temporary)
        for folder in ('media', 'generation', 'references'):
            (root / folder).mkdir()
        assembled, timeline, warnings, generation, selections = [], [], [], [], []
        seen, hashes, total_bytes, cursor = set(), {}, 0, 0.
        def copy_input(source, target, limit):
            nonlocal total_bytes
            with source.open('rb') as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('Input exceeds its file size budget')
            total_bytes += len(raw)
            if total_bytes > MAX_PROJECT_BYTES:
                raise ValueError('Project exceeds 512 MiB of copied inputs')
            target.write_bytes(raw)
            return raw
        for shot, portable_shot in zip(shots, portable['shots']):
            only(shot, {'id', 'beat', 'action', 'start', 'end', 'camera', 'state', 'source',
                        'generate', 'title', 'caption', 'source_sha256'}, 'shot')
            sid = shot.get('id')
            if (not isinstance(sid, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}', sid)
                    or sid.lower() in seen):
                raise ValueError('Shot ids must be unique safe ASCII identifiers')
            seen.add(sid.lower())
            for key in ('beat', 'action', 'start', 'end', 'camera'):
                check_text(shot.get(key), f'{sid}.{key}')
            for key in ('state', 'caption'):
                if key in shot:
                    check_text(shot[key], f'{sid}.{key}')
            kinds = set(shot) & {'source', 'generate', 'title'}
            if len(kinds) != 1:
                raise ValueError('Every shot needs exactly one of source, generate, title')
            kind = next(iter(kinds))
            if 'source_sha256' in shot:
                if kind != 'source':
                    raise ValueError('source_sha256 is only valid for a source shot')
                check_sha256(shot['source_sha256'], f'{sid}.source_sha256')
            compiled = {'id': sid, 'first_frame_target': shot['start'], 'last_frame_target': shot['end'], 'transition': 'cut'}
            if 'caption' in shot:
                compiled['caption'] = shot['caption']
            status = 'visual-review-required'
            source_hash = None
            requested_ms = None
            if kind == 'source':
                name = check_text(shot['source'], 'source')
                raw = copy_input(path.parent / name, root / 'media' / f'{sid}.gif', cli.MAX_GIF_BYTES)
                frames, delays, _ = cli.validate_gif(io.BytesIO(raw))
                source_hash = hashlib.sha256(raw).hexdigest()
                if 'source_sha256' in shot and source_hash != shot['source_sha256']:
                    raise ValueError(f'{sid}: source SHA-256 mismatch; reviewed media changed')
                if source_hash in hashes:
                    warnings.append(f'{sid}: same footage as {hashes[source_hash]}; repetition is not a new story action')
                hashes[source_hash] = sid
                duration = sum(delays)
                compiled['source'] = f'media/{sid}.gif'
                portable_shot['source'] = compiled['source']
                if max(delays) > 1000:
                    warnings.append(f'{sid}: contains a drawing held over 1 second; inspect pacing')
                drawing_count = len(frames)
                del frames
            elif kind == 'title':
                frames, delays = title_frames(shot['title'], width, height, font_path)
                destination = root / 'media' / f'{sid}.gif'
                frames[0].save(destination, save_all=True, append_images=frames[1:], duration=delays, disposal=2)
                decoded, saved_delays, _ = cli.validate_gif(destination)
                if sum(saved_delays) != sum(delays):
                    raise ValueError('Title encoding changed its duration')
                duration, drawing_count = sum(saved_delays), len(decoded)
                source_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
                compiled['source'] = f'media/{sid}.gif'
                portable_shot.pop('title')
                portable_shot['source'] = compiled['source']
                del frames, decoded
            else:
                settings = shot['generate']
                only(settings, {'frames', 'duration_ms', 'model', 'size', 'quality', 'complexity', 'references'}, 'generate')
                generated = {**compiled, **{k: v for k, v in settings.items() if k != 'references'},
                             'prompt': f"Action: {shot['action']}\nCamera: {shot['camera']}\n"
                                       f"Continuity state: {shot.get('state', 'See the start and end targets.')}"}
                if 'references' in settings:
                    names = settings['references']
                    if not isinstance(names, list) or not 1 <= len(names) <= 16:
                        raise ValueError('generate.references must contain 1..16 existing still-image paths')
                    references = []
                    for index, name in enumerate(names):
                        source = path.parent / check_text(name, 'reference')
                        if source.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                            raise ValueError('Reference extension must be PNG, JPEG, or WebP')
                        name = f'{sid}-{index:02}{source.suffix.lower()}'
                        copy_input(source, root / 'references' / name, 20 * 1024 * 1024)
                        references.append(f'../references/{name}')
                    generated['references'] = references
                    portable_shot['generate']['references'] = [name.removeprefix('../') for name in references]
                candidate = root / 'generation' / f'{sid}.json'
                write_json(candidate, {**base, 'shots': [generated]})
                validated = render.load_script(candidate, argparse.Namespace(width=None, height=None, fps=None))
                duration = validated['shots'][0]['expected_ms']
                drawing_count = generated.get('frames', 9)
                if sid in takes:
                    selection = takes[sid]
                    raw = copy_input(takes_path.parent / selection['source'],
                                     root / 'media' / f'{sid}.gif', cli.MAX_GIF_BYTES)
                    source_hash = hashlib.sha256(raw).hexdigest()
                    if source_hash != selection['sha256']:
                        raise ValueError(f'{sid}: selected take SHA-256 mismatch; review the actual file again')
                    frames, delays, _ = cli.validate_gif(io.BytesIO(raw))
                    requested_ms, duration, drawing_count = duration, sum(delays), len(frames)
                    del frames
                    if source_hash in hashes:
                        warnings.append(f'{sid}: same footage as {hashes[source_hash]}; repetition is not a new story action')
                    hashes[source_hash] = sid
                    if max(delays) > 1000:
                        warnings.append(f'{sid}: contains a drawing held over 1 second; inspect pacing')
                    if duration != requested_ms:
                        warnings.append(f'{sid}: selected take is {duration} ms, planned {requested_ms} ms; timeline uses actual timing')
                    compiled['source'] = f'media/{sid}.gif'
                    portable_shot.pop('generate')
                    portable_shot['source'] = compiled['source']
                    kind, status = 'selected-take', 'caller-review-recorded'
                    selections.append({'shot_id': sid, 'source': compiled['source'],
                                       'sha256': source_hash, 'review_notes': selection['review_notes'],
                                       'generation_script': f'generation/{sid}.json',
                                       'requested_duration_ms': requested_ms, 'source_duration_ms': duration})
                else:
                    generation.append(f'generation/{sid}.json')
                    compiled['source'] = f'accepted/{sid}.gif'
                    status = 'not-generated'
            if source_hash is not None:
                portable_shot['source_sha256'] = source_hash
            playback_ms = max(1, round(duration / 1000 * fps)) / fps * 1000
            timeline.append({'id': sid, 'kind': kind, 'beat': shot['beat'], 'action': shot['action'],
                             'state': shot.get('state', ''), 'start_ms': cursor, 'end_ms': cursor + playback_ms,
                             'source_duration_ms': duration, 'requested_duration_ms': requested_ms,
                             'drawings': drawing_count,
                             'source_sha256': source_hash, 'status': status})
            cursor += playback_ms
            assembled.append(compiled)
        filename = 'assembly-template.json' if generation else 'film.json'
        write_json(root / filename, {**base, 'shots': assembled})
        if not generation:
            render.load_script(root / filename, argparse.Namespace(width=None, height=None, fps=None))
        # Retain the author's editable source document. Paths still refer to original inputs;
        # the compiled film and generation scripts use copied, portable project inputs.
        write_json(root / 'storyboard.original.json', data)
        write_json(root / 'storyboard.json', portable)
        if selections:
            write_json(root / 'take-selections.json', {'schema_version': 1, 'takes': selections,
                       'visual_acceptance': 'Caller review notes are recorded, not independently verified.'})
        notes = [f"# {data['title']}", '', data['premise'], '', f"Ending: {data['ending']}", '',
                 '## Visual bible', bible, '', '## Shots and handoffs']
        for collection in ('characters', 'props'):
            for item in data.get(collection, []):
                if 'initial_state' in item:
                    notes.append(f"Initial {item['id']} state: {item['initial_state']}")
        for shot in shots:
            notes.extend(['', f"### {shot['id']}: {shot['beat']}", f"Action: {shot['action']}",
                          f"Start: {shot['start']}", f"End: {shot['end']}", f"Camera: {shot['camera']}",
                          f"State: {shot.get('state', 'Review prop ownership and contacts visually.')}"])
        (root / 'storyboard.md').write_text('\n'.join(notes) + '\n', encoding='utf-8')
        report = {'provider_calls': 0, 'ready_to_assemble': not generation, 'assembly_script': filename,
                  'generation_scripts': generation, 'minimum_new_requests_for_missing_shots': len(generation),
                  'selected_take_count': len(selections),
                  'planned_playback_ms': cursor, 'timeline': timeline, 'warnings': warnings,
                  'visual_acceptance': 'not-established',
                  'scope': 'Offline planning, caller-selected source copying and local title animation only. Missing generated durations are targets, not observations.'}
        write_json(root / 'story-report.json', report)
        # rename refuses a competing nonempty directory; do not merge into old projects.
        if out.exists():
            raise ValueError('Output appeared during compilation; refusing to overwrite')
        root.rename(out)
    return report


def export_gif(source, out, width=320, fps=10, repeat=False):
    source, out = source.resolve(), out.resolve()
    if out.suffix.lower() != '.gif' or out.exists():
        raise ValueError('Choose a new .gif output path')
    integer(width, 'GIF width', 64, 640)
    if fps not in {5, 10, 20, 25}:
        raise ValueError('GIF fps must be 5, 10, 20 or 25 for exact 10 ms timing')
    info = json.loads(cli.run_media(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                   '-show_entries', 'stream=width,height,duration', '-of', 'json', str(source)]).stdout)['streams'][0]
    duration = float(info['duration'])
    height = max(2, round(width * int(info['height']) / int(info['width']) / 2) * 2)
    count = math.ceil(duration * fps)
    if (not math.isfinite(duration) or duration <= 0 or count > cli.MAX_GIF_FRAMES
            or width * height * count > cli.MAX_GIF_PIXEL_FRAMES):
        raise ValueError('Long GIF exceeds decoded-media budget; lower width/FPS or export chapters')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.gif-export-', dir=out.parent) as folder:
        staged = Path(folder) / 'film.gif'
        filters = (f'fps={fps},scale={width}:{height}:flags=lanczos,split[a][b];'
                   '[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=sierra2_4a')
        cli.run_media(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(source), '-filter_complex', filters,
                       '-an', '-loop', '0' if repeat else '-1', str(staged)])
        frames, delays, loop = cli.validate_gif(staged)
        if abs(sum(delays) / 1000 - duration) > 1 / fps + .001:
            raise ValueError('Exported GIF timing does not match the MP4 within one GIF frame')
        if (frames[0].size != (width, height) or (repeat and loop != 0) or (not repeat and loop is not None)):
            raise ValueError('Exported GIF dimensions or loop flag do not match the request')
        receipt = {'provider_calls': 0, 'width': width, 'height': height, 'frames': len(frames),
                   'duration_ms': sum(delays), 'loop': loop, 'gif_sha256': hashlib.sha256(staged.read_bytes()).hexdigest(),
                   'note': 'GIF is silent; output FPS resamples existing motion, not new character poses.'}
        cli.publish_file(staged, out)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('compile', help='Prepare storyboard, prompts and portable montage inputs; no network calls')
    build.add_argument('story', type=Path)
    build.add_argument('--out', required=True, type=Path)
    build.add_argument('--takes', type=Path, help='Manifest of reviewed GIF takes, hashes and notes for generated slots')
    build.add_argument('--font', type=Path, help='Optional local licensed font for title cards')
    export = sub.add_parser('export-gif', help='Convert a verified local MP4 to a bounded silent GIF')
    export.add_argument('source', type=Path)
    export.add_argument('--out', required=True, type=Path)
    export.add_argument('--width', type=int, default=320)
    export.add_argument('--fps', type=int, default=10)
    export.add_argument('--repeat', action='store_true', help='Loop the whole story forever; default plays once')
    args = parser.parse_args()
    try:
        result = (compile_story(args.story, args.out, args.font, args.takes) if args.command == 'compile'
                  else export_gif(args.source, args.out, args.width, args.fps, args.repeat))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, RuntimeError, KeyError, IndexError) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
