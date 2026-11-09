"""Export a completed GIF Cinema film as shot-aligned, bounded GIF chapters.

Offline only. A render manifest links the exact script, shot timing and movie.
Dry-run checks the inputs and plan without invoking FFmpeg or writing outputs.
"""
import argparse
from contextlib import contextmanager
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile

from gif_cinema import cli, render

MAX_JSON_BYTES = 1024 * 1024
MAX_MOVIE_BYTES = 512 * 1024 * 1024
MAX_FILM_SECONDS = 3600
MAX_EXPORT_BYTES = 512 * 1024 * 1024


@contextmanager
def regular_input(path, limit):
    # O_NONBLOCK allows fstat to reject a FIFO without waiting for its writer.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Inputs must be regular local files')
        if info.st_size > limit:
            raise ValueError(f'Input exceeds its {limit}-byte limit')
        yield stream


def read_bytes(path, limit):
    with regular_input(path, limit) as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'Input exceeds its {limit}-byte limit')
    return raw


def movie_digest(path, target=None):
    digest, total = hashlib.sha256(), 0
    with regular_input(path, MAX_MOVIE_BYTES) as stream:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_MOVIE_BYTES:
                raise ValueError('Movie exceeds 512 MiB')
            digest.update(chunk)
            if target is not None:
                target.write(chunk)
    return digest.hexdigest()


def load_json(path):
    raw = read_bytes(path, MAX_JSON_BYTES)
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value, hashlib.sha256(raw).hexdigest()


def plan_chapters(script_path, render_dir, width=320, fps=10, max_seconds=15, repeat=False):
    """Use completed render records, not a storyboard's estimated timeline."""
    script_path, render_dir = Path(script_path).resolve(), Path(render_dir).resolve()
    render.integer(width, 'GIF width', 64, 640)
    if type(fps) is not int or fps not in {5, 10, 20, 25}:
        raise ValueError('GIF fps must be 5, 10, 20 or 25 for exact 10 ms timing')
    render.integer(max_seconds, 'Chapter seconds', 1, 120)
    if type(repeat) is not bool:
        raise ValueError('repeat must be a boolean')
    script, script_hash = load_json(script_path)
    manifest, manifest_hash = load_json(render_dir / 'render-manifest.json')
    if (type(script.get('schema_version')) is not int or script['schema_version'] != 1
            or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1):
        raise ValueError('Only version 1 scripts and render manifests are supported')
    if manifest.get('script_sha256') != script_hash:
        raise ValueError('Script does not match the completed render; render it again first')
    runs = manifest.get('runs')
    if not isinstance(runs, list) or not runs or not isinstance(runs[-1], dict) or runs[-1].get('status') != 'complete':
        raise ValueError('The latest render must be complete before chapter export')
    film = manifest.get('film')
    if not isinstance(film, dict) or film.get('output') != 'film.mp4' or not isinstance(film.get('probe'), dict):
        raise ValueError('Expected the completed render film.mp4 and its probe record')
    probe = film['probe']
    source_width = render.integer(probe.get('width'), 'Film width', 2, 4096)
    source_height = render.integer(probe.get('height'), 'Film height', 2, 4096)
    # The renderer permits CLI overrides without rewriting film.json. Its saved
    # probe has the effective dimensions, count and microsecond-rounded duration.
    recorded_count = int(probe.get('nb_read_frames', 0))
    recorded_duration = Fraction(str(probe.get('duration', 0)))
    if recorded_count < 1 or recorded_duration <= 0:
        raise ValueError('Invalid completed movie count/duration')
    source_fps = render.integer(round(recorded_count / recorded_duration), 'Film fps', 1, 120)
    if abs(recorded_duration - Fraction(recorded_count, source_fps)) > Fraction(1, 1000000):
        raise ValueError('Completed movie must have an integer constant frame rate')
    ratio = script.get('ratio')
    if not isinstance(ratio, str) or not re.fullmatch(r'[1-9][0-9]?:[1-9][0-9]?', ratio):
        raise ValueError('Invalid film ratio')
    rw, rh = map(int, ratio.split(':'))
    if source_width % 2 or source_height % 2 or abs(source_width / source_height - rw / rh) > .01:
        raise ValueError('Film dimensions must be even and match its ratio')
    height = max(2, round(width * source_height / source_width / 2) * 2)
    capacity = min(cli.MAX_GIF_FRAMES, cli.MAX_GIF_PIXEL_FRAMES // (width * height), max_seconds * fps)
    if capacity < 2 or width * height > cli.MAX_GIF_FRAME_PIXELS:
        raise ValueError('Chapter dimensions exceed the GIF budget; lower width')
    shots, records = script.get('shots'), manifest.get('shots')
    if not isinstance(shots, list) or not 1 <= len(shots) <= 64 or not isinstance(records, dict):
        raise ValueError('Expected 1..64 completed shots')
    timeline, seen, cursor = [], set(), 0
    for shot in shots:
        if not isinstance(shot, dict):
            raise ValueError('Invalid shot')
        sid = shot.get('id')
        if not isinstance(sid, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}', sid) or sid.lower() in seen:
            raise ValueError('Shot IDs must be unique safe identifiers')
        seen.add(sid.lower())
        if shot.get('transition', 'cut') != 'cut':
            raise ValueError('Chapter export currently supports hard cuts only')
        record = records.get(sid)
        if not isinstance(record, dict) or record.get('status') != 'verified-gif':
            raise ValueError(f'{sid}: missing verified render record')
        output = record.get('output')
        if not isinstance(output, str) or not output:
            raise ValueError(f'{sid}: missing rendered shot path')
        raw = read_bytes(render.local_path(render_dir, output), cli.MAX_GIF_BYTES)
        if hashlib.sha256(raw).hexdigest() != record.get('sha256'):
            raise ValueError(f'{sid}: saved shot hash mismatch')
        frames, delays, _ = cli.validate_gif(io.BytesIO(raw))
        count = len(frames)
        del frames, raw
        if (record.get('duration_ms') != sum(delays) or record.get('frame_durations_ms') != delays
                or record.get('frames') != count):
            raise ValueError(f'{sid}: saved shot timing mismatch')
        playback_frames = max(1, round(sum(delays) * source_fps / 1000))
        gif_frames = math.ceil(Fraction(playback_frames * fps, source_fps))
        if gif_frames > capacity:
            raise ValueError(f'{sid}: one whole shot exceeds the chapter budget; lower width/FPS or increase --max-seconds')
        timeline.append({'id': sid, 'start_frame': cursor, 'end_frame': cursor + playback_frames})
        cursor += playback_frames
        if cursor > MAX_FILM_SECONDS * source_fps:
            raise ValueError('Chapter export is limited to a one-hour film')
    if recorded_count != cursor:
        raise ValueError('Completed movie frame count does not match measured shot timing')
    if movie_digest(render_dir / 'film.mp4') != film.get('sha256'):
        raise ValueError('Movie hash does not match the completed render')
    groups = []
    for shot in timeline:
        if not groups or math.ceil(Fraction((shot['end_frame'] - groups[-1]['start_frame']) * fps, source_fps)) > capacity:
            groups.append({'shot_ids': [], 'start_frame': shot['start_frame'], 'end_frame': shot['end_frame']})
        groups[-1]['shot_ids'].append(shot['id'])
        groups[-1]['end_frame'] = shot['end_frame']
    for index, group in enumerate(groups, 1):
        source_frames = group['end_frame'] - group['start_frame']
        output_frames = math.ceil(Fraction(source_frames * fps, source_fps))
        # The runtime GIF validator requires at least two encoded frames.
        if output_frames < 2:
            raise ValueError('A chapter is shorter than two GIF frames; raise GIF FPS or group more shots')
        group.update(file=f'chapter-{index:02}.gif', playback_frames=output_frames,
                     source_duration_ms=source_frames * 1000 / source_fps,
                     duration_ms=output_frames * (1000 // fps))
    return {'schema_version': 1, 'provider_calls': 0, 'script_sha256': script_hash,
            'manifest_sha256': manifest_hash, 'film_sha256': film['sha256'],
            'source_width': source_width, 'source_height': source_height, 'source_fps': source_fps,
            'source_frames': cursor, 'source_duration_ms': cursor * 1000 / source_fps,
            'width': width, 'height': height, 'fps': fps, 'max_seconds': max_seconds, 'repeat': repeat,
            'chapters': groups, 'verification': 'inputs-hashed; movie-decode-pending',
            'note': 'Whole shots in order, no new poses. GIFs are silent. Each chapter may gain less than one GIF frame of hold from timing quantization; visual review remains required.'}


def verify_movie(source, plan):
    # Force the MP4 demuxer and restrict protocols, including for an untrusted input.
    inputs = ['-protocol_whitelist', 'file', '-f', 'mov', '-i', str(source)]
    result = cli.run_media(['ffprobe', '-v', 'error', *inputs, '-select_streams', 'v:0', '-count_frames',
                            '-show_entries', 'stream=codec_name,width,height,duration,nb_read_frames,avg_frame_rate,r_frame_rate', '-of', 'json'])
    info = json.loads(result.stdout)['streams'][0]
    duration = float(info['duration'])
    if (info['codec_name'] != 'h264' or info['width'] != plan['source_width'] or info['height'] != plan['source_height']
            or int(info['nb_read_frames']) != plan['source_frames'] or not math.isfinite(duration)
            or abs(duration - plan['source_frames'] / plan['source_fps']) > .5 / plan['source_fps']
            or Fraction(info['avg_frame_rate']) != plan['source_fps'] or Fraction(info['r_frame_rate']) != plan['source_fps']):
        raise ValueError('Movie does not match the completed film dimensions, frame rate or timing')
    cli.run_media(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', *inputs, '-map', '0:v:0', '-an', '-f', 'null', '-'])


def export_chapters(script_path, render_dir, out, width=320, fps=10, max_seconds=15, repeat=False, dry_run=False):
    out, render_dir = Path(out).absolute(), Path(render_dir).resolve()
    if os.path.lexists(out):
        raise ValueError('Output must be a new directory; existing chapters are never overwritten')
    plan = plan_chapters(script_path, render_dir, width, fps, max_seconds, repeat)
    if dry_run:
        return plan
    out.parent.mkdir(parents=True, exist_ok=True)
    with cli.output_lock(out), tempfile.TemporaryDirectory(prefix='.chapters-stage-', dir=out.parent) as folder:
        stage = Path(folder)
        source = stage / 'source.mp4'
        with source.open('xb') as target:
            if movie_digest(render_dir / 'film.mp4', target) != plan['film_sha256']:
                raise ValueError('Movie changed since planning; no chapters published')
        verify_movie(source, plan)
        total_bytes = 0
        for chapter in plan['chapters']:
            target = stage / chapter['file']
            # Trim by source frame, not keyframe seeking. Pad only the final hold,
            # before resetting timestamps (FFmpeg EOF timestamps matter), then cap
            # the exact GIF playback count. No adjacent chapter bleeds in.
            filters = (f"trim=start_frame={chapter['start_frame']}:end_frame={chapter['end_frame']},"
                       f"tpad=stop_mode=clone:stop={plan['source_fps']},setpts=N/({plan['source_fps']}*TB),"
                       f"fps={fps},trim=end_frame={chapter['playback_frames']},"
                       f"scale={width}:{plan['height']}:flags=lanczos,split[a][b];"
                       '[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=sierra2_4a')
            cli.run_media(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-protocol_whitelist', 'file', '-f', 'mov',
                           '-i', str(source), '-filter_complex', filters, '-an', '-loop', '0' if repeat else '-1',
                           '-fs', str(cli.MAX_GIF_BYTES + 1), str(target)])
            total_bytes += target.stat().st_size
            if total_bytes > MAX_EXPORT_BYTES:
                raise ValueError('Combined GIF chapters exceed 512 MiB; lower width/FPS')
            frames, delays, loop = cli.validate_gif(target)
            if (any(frame.size != (width, plan['height']) for frame in frames)
                    or sum(delays) != chapter['duration_ms'] or loop != (0 if repeat else None)):
                raise ValueError('Encoded chapter dimensions, timing or loop flag failed verification')
            chapter.update(encoded_frames=len(frames), gif_sha256=hashlib.sha256(read_bytes(target, cli.MAX_GIF_BYTES)).hexdigest())
            del frames
        source.unlink()
        plan['verification'] = 'decoded-h264-and-all-gif-frames; visual-review-required'
        (stage / 'chapters.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
        if os.path.lexists(out):
            raise ValueError('Output appeared during export; refusing to overwrite')
        stage.rename(out)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('script', type=Path, help='Exact film.json used for the completed render')
    parser.add_argument('--render', type=Path, required=True, help='Completed render directory, including its manifest and saved shots')
    parser.add_argument('--out', type=Path, required=True, help='New directory for all GIF chapters and chapters.json')
    parser.add_argument('--width', type=int, default=320)
    parser.add_argument('--fps', type=int, default=10)
    parser.add_argument('--max-seconds', type=int, default=15, help='Upper bound per chapter, 1..120; whole shots are never split')
    parser.add_argument('--repeat', action='store_true', help='Loop each chapter; default plays each once')
    parser.add_argument('--dry-run', action='store_true', help='Check hashes and plan only, without FFmpeg or output writes')
    args = parser.parse_args()
    try:
        result = export_chapters(args.script, args.render, args.out, args.width, args.fps, args.max_seconds, args.repeat, args.dry_run)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, RuntimeError, KeyError, IndexError, TypeError, ZeroDivisionError) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
