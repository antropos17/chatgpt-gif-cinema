"""Build the bundled film offline, with immutable revisions and scene checkpoints."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))
from gif_cinema.durability import durable_write

MAX_BYTES = 512 * 1024 * 1024
MAX_FILE = 128 * 1024 * 1024
FORMAT = 'lantern-echo-build-v1'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def regular(path, limit=MAX_FILE):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError(f'Expected a regular non-symlink file: {path}')
    if path.stat().st_size > limit:
        raise ValueError(f'Input exceeds byte budget: {path}')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'Input exceeds byte budget: {path}')
    return raw


def read_json(path):
    return json.loads(regular(path, 1024 * 1024))


def save(path, value):
    durable_write(path, json.dumps(value, indent=2, allow_nan=False).encode() + b'\n')


def local(root, name):
    if not isinstance(name, str) or '\\' in name or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('Invalid relative asset/checkpoint path')
    path = root / name
    if not path.absolute().is_relative_to(root.absolute()):
        raise ValueError('Path escapes its bundle')
    return path


def budget(root):
    total = count = 0
    for p in root.rglob('*'):
        if p.is_symlink():
            raise ValueError('Output must not contain symlinks')
        if p.is_file():
            total += p.stat().st_size
            count += 1
    if total > MAX_BYTES or count > 256:
        raise ValueError('Output exceeds 512 MiB / 256-file budget; preserve it and use a new destination')


@contextlib.contextmanager
def lock(out):
    """OS lock is released even after a killed process; no stale PID guessing."""
    path = out / '.build.lock'
    if path.is_symlink():
        raise ValueError('Lock must not be a symlink')
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def recipe(path):
    value = read_json(path)
    if (value.get('schema_version'), value.get('width'), value.get('height'), value.get('fps'), value.get('frames')) != (1, 960, 540, 25, 520):
        raise ValueError('Expected the 960x540 / 25 fps / 520-frame Lantern Echo timeline')
    end, seen = 0, set()
    for s in value['scenes']:
        sid = s['id']
        if not isinstance(sid, str) or not sid.replace('-', '').isalnum() or sid in seen:
            raise ValueError('Scene IDs must be unique portable alphanumeric names')
        if type(s['start_frame']) is not int or type(s['end_frame']) is not int or s['start_frame'] != end or not end < s['end_frame'] <= 520:
            raise ValueError('Scene intervals must partition the original 520-frame source clock')
        camera = s['camera']
        if (len(camera) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in camera)
                or not 0 <= camera[0] < camera[2] <= 960 or not 0 <= camera[1] < camera[3] <= 540):
            raise ValueError('Camera must be a bounded crop')
        gain = s['effects']['canopy_gain']
        if type(gain) not in (int, float) or not math.isfinite(gain) or not 0 <= gain <= 2:
            raise ValueError('canopy_gain must be in 0..2')
        seen.add(sid)
        end = s['end_frame']
    if end != 520 or not 1 <= len(seen) <= 32:
        raise ValueError('Timeline must cover the entire film')
    return value


def assets():
    manifest = read_json(ROOT / 'assets/manifest.json')
    for name, fact in manifest['files'].items():
        raw = regular(local(ROOT, name))
        if len(raw) != fact['bytes'] or sha(raw) != fact['sha256']:
            raise ValueError(f'Asset differs from its authored manifest: {name}')
    return manifest


def dependencies(s):
    lo, hi = s['start_frame'] / 25, s['end_frame'] / 25
    ranges = [(0, .64, 'idle-girl'), (.64, 4.32, 'cast'), (4.32, 7.52, 'catch'),
              (7.52, 10.4, 'release'), (10.4, 12.8, 'idle-girl'), (12.8, 14.72, 'bow'),
              (14.72, 20.8, 'idle-girl'), (0, 3.2, 'idle-boy'), (3.2, 5.6, 'boy'),
              (5.6, 10.4, 'idle-boy'), (10.4, 12.8, 'boy'), (12.8, 20.8, 'idle-boy')]
    return sorted({name for a, b, name in ranges if lo < b and hi > a})


def identities(value, manifest, engine):
    keys = {}
    for s in value['scenes']:
        names = ['assets/garden.png'] + [manifest['clips'][n]['path'] for n in dependencies(s)]
        keys[s['id']] = sha(canonical({'scene': s, 'assets': {n: manifest['files'][n]['sha256'] for n in names}, 'engine': engine}))
    return keys


def review(value, keys, old):
    decisions = [{'id': s['id'], 'key': keys[s['id']],
                  'encoding': 'reuse' if old and old['keys'].get(s['id']) == keys[s['id']] else 'render',
                  'assets': dependencies(s)} for s in value['scenes']]
    changed = {d['id'] for d in decisions if d['encoding'] == 'render'}
    cuts, neighbors = [], set()
    for a, b in zip(value['scenes'], value['scenes'][1:]):
        if a['id'] in changed or b['id'] in changed:
            cuts.append({'previous': a['id'], 'next': b['id'], 'at_ms': b['start_frame'] * 40})
            neighbors.update([a['id'], b['id']])
    return {'scenes': decisions, 'changed_scenes': sorted(changed),
            'neighbor_scenes_for_review': sorted(neighbors - changed), 'cuts_for_review': cuts,
            'note': 'Neighbors require boundary review, not automatic re-encoding. Independent scene effects do not carry into later scenes.'}


def video_frames(path):
    import av
    with av.open(str(path)) as container:
        for f in container.decode(video=0):
            yield f


def verify_scene(root, record, key):
    path = local(root, record['file'])
    if record['key'] != key or sha(regular(path)) != record['sha256']:
        raise ValueError(f'Completed scene changed: {path.name}')
    count = 0
    for count, f in enumerate(video_frames(path), 1):
        if (f.width, f.height) != (960, 540) or abs(float(f.pts * f.time_base) - (count - 1) / 25) > 1e-6:
            raise ValueError('Scene geometry/timestamps differ')
        if count > len(record['rgb_sha256']) or sha(f.to_image().convert('RGB').tobytes()) != record['rgb_sha256'][count - 1]:
            raise ValueError('Lossless scene pixels differ')
    if count != record['frames']:
        raise ValueError('Incomplete scene')
    return path


def encode(command, images):
    """Bound encoder logs; keep partial output after interruption for diagnosis."""
    import tempfile
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
        try:
            for image in images:
                process.stdin.write(image.tobytes())
            process.stdin.close()
            if process.wait(timeout=180) != 0:
                log.seek(0)
                raise RuntimeError(log.read(65536).decode(errors='replace'))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def raw_command(ffmpeg):
    return [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n', '-f', 'rawvideo',
            '-pix_fmt', 'rgb24', '-s', '960x540', '-r', '25', '-i', 'pipe:0']


def render_scene(ffmpeg, out, s, key, compositor):
    name = f'scenes/{s["id"]}-{uuid.uuid4().hex}.mkv'
    path = local(out, name)
    hashes = []
    def images():
        for index in range(s['start_frame'], s['end_frame']):
            im = compositor.frame(index / 25, s)
            hashes.append(sha(im.tobytes()))
            yield im
    encode(raw_command(ffmpeg) + ['-an', '-c:v', 'ffv1', '-level', '3', '-threads', '2', '-pix_fmt', 'bgr0', str(path)], images())
    record = {'file': name, 'key': key, 'frames': len(hashes), 'rgb_sha256': hashes, 'sha256': sha(regular(path))}
    verify_scene(out, record, key)
    return record


def verify_movie(path):
    import av
    count = 0
    for count, f in enumerate(video_frames(path), 1):
        if (f.width, f.height) != (960, 540) or abs(float(f.pts * f.time_base) - (count - 1) / 25) > 1e-6:
            raise ValueError('Movie geometry/timestamps differ')
    with av.open(str(path)) as c:
        if len(c.streams.audio) != 1 or c.streams.audio[0].channels != 2 or not any(c.decode(audio=0)):
            raise ValueError('Expected decodable stereo sound')
    if count != 520:
        raise ValueError('Movie must have 520 decoded frames')
    return sha(regular(path))


def completed(root):
    rec = read_json(root / 'build-receipt.json')
    if rec.get('format') != FORMAT or rec.get('status') != 'complete':
        raise ValueError('Not a completed Lantern Echo build')
    for sid, record in rec['completed'].items():
        verify_scene(root, record, rec['keys'][sid])
    if verify_movie(root / 'Lantern-Echo.mp4') != rec['movie_sha256']:
        raise ValueError('Completed movie changed')
    return rec


def build(args):
    import av
    import PIL
    ffmpeg = shutil.which(args.ffmpeg)
    if not ffmpeg:
        raise ValueError('FFmpeg is required on PATH, or supply --ffmpeg /path/to/ffmpeg')
    version = subprocess.run([ffmpeg, '-version'], capture_output=True, check=True, timeout=15).stdout.decode().splitlines()[0]
    sources = {'builder': sha(regular(Path(__file__))), 'compositor': sha(regular(ROOT / 'compositor.py'))}
    engine = sha(canonical({**sources,
                            'pillow': PIL.__version__, 'av': av.__version__, 'python': sys.version, 'ffmpeg': version}))
    value, manifest = recipe(args.timeline), assets()
    keys = identities(value, manifest, engine)
    out = Path(args.out).absolute()
    if (out == ROOT or out.is_relative_to(ROOT) or ROOT.is_relative_to(out)
            or any(p.is_symlink() for p in (out, *out.parents))):
        raise ValueError('Use a separate non-symlink output directory outside the example source')
    prior = Path(args.reuse_from).absolute() if args.reuse_from else None
    if prior == out:
        raise ValueError('Revisions must use a new output directory')
    old = completed(prior) if prior else None
    reuse_identity = sha(regular(prior / 'build-receipt.json', 1024 * 1024)) if prior else None
    identity = sha(canonical({'recipe': value, 'assets': manifest['files'], 'engine': engine, 'reuse_receipt': reuse_identity}))
    plan = review(value, keys, old)
    if args.dry_run:
        return {'status': 'planned', 'provider_calls': 0, 'review': plan}
    if out.exists() and not args.resume:
        raise ValueError('Output exists; use a new revision or --resume with unchanged inputs')
    out.mkdir(parents=True, exist_ok=True)
    with lock(out):
        state_path = out / 'checkpoint.json'
        if state_path.exists():
            state = read_json(state_path)
            if state.get('format') != FORMAT or state.get('input') != identity:
                raise ValueError('Resume input or engine changed; use a new revision')
        else:
            if args.resume:
                raise ValueError('Resume needs its original checkpoint')
            (out / 'scenes').mkdir()
            state = {'format': FORMAT, 'input': identity, 'engine': engine, 'timeline': value,
                     'keys': keys, 'completed': {}, 'review': plan, 'provider_calls': 0}
            save(state_path, state)
        budget(out)
        if (out / 'build-receipt.json').exists():
            rec = completed(out)
            return {'status': 'complete', 'already_complete': True, 'movie': str(out / 'Lantern-Echo.mp4'), 'movie_sha256': rec['movie_sha256']}
        counts = {'rendered': 0, 'reused': 0, 'resumed': 0}
        compositor = None
        for s in value['scenes']:
            sid, key = s['id'], keys[s['id']]
            if sid in state['completed']:
                verify_scene(out, state['completed'][sid], key)
                counts['resumed'] += 1
                continue
            state['active_scene'] = sid
            save(state_path, state)
            print(json.dumps({'event': 'scene-start', 'id': sid}), flush=True)
            if old and old['keys'].get(sid) == key:
                source = verify_scene(prior, old['completed'][sid], key)
                record = dict(old['completed'][sid])
                record['file'] = f'scenes/{sid}-{uuid.uuid4().hex}.mkv'
                shutil.copyfile(source, local(out, record['file']))
                verify_scene(out, record, key)
                counts['reused'] += 1
            else:
                if compositor is None:
                    import compositor
                    compositor.load_assets(ROOT)
                record = render_scene(ffmpeg, out, s, key, compositor)
                counts['rendered'] += 1
            budget(out)
            state['completed'][sid] = record
            state.pop('active_scene', None)
            save(state_path, state)
            print(json.dumps({'event': 'scene-complete', 'id': sid, 'counts': counts}), flush=True)
        movie = out / 'Lantern-Echo.mp4'
        if 'ready' not in state:
            if movie.exists():
                raise ValueError('Unrecorded existing movie is preserved; use a new destination')
            if compositor is None:
                import compositor
                compositor.load_assets(ROOT)
            audio = out / f'sound-{uuid.uuid4().hex}.wav'
            compositor.sound(audio)
            partial = out / f'film-{uuid.uuid4().hex}.mp4'
            def images():
                for s in value['scenes']:
                    record = state['completed'][s['id']]
                    path = verify_scene(out, record, keys[s['id']])
                    for index, f in enumerate(video_frames(path)):
                        im = f.to_image().convert('RGB')
                        if sha(im.tobytes()) != record['rgb_sha256'][index]:
                            raise ValueError('Scene changed during final assembly')
                        yield im
            encode(raw_command(ffmpeg) + ['-i', str(audio), '-t', '20.8', '-c:v', 'libx264', '-crf', '16',
                   '-preset', 'medium', '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
                   '-movflags', '+faststart', str(partial)], images())
            state['ready'] = {'file': partial.name, 'sha256': verify_movie(partial), 'audio': audio.name,
                              'audio_sha256': sha(regular(audio))}
            save(state_path, state)
        ready = state['ready']
        if (recipe(args.timeline) != value or assets() != manifest
                or sha(regular(Path(__file__))) != sources['builder']
                or sha(regular(ROOT / 'compositor.py')) != sources['compositor']):
            raise ValueError('Inputs changed during build; completed scenes are preserved, publication refused')
        if movie.exists():
            if verify_movie(movie) != ready['sha256']:
                raise ValueError('Existing movie changed; it has been preserved')
        else:
            partial = local(out, ready['file'])
            if verify_movie(partial) != ready['sha256']:
                raise ValueError('Prepared movie changed')
            os.replace(partial, movie)
        budget(out)
        rec = {**state, 'status': 'complete', 'scene_exports': counts, 'movie_sha256': ready['sha256'],
               'audio_sha256': ready['audio_sha256'], 'visual_acceptance': 'not inferred by build checks'}
        save(out / 'build-receipt.json', rec)
        return {'status': 'complete', 'movie': str(movie), 'movie_sha256': rec['movie_sha256'],
                'scene_exports': counts, 'review': plan, 'provider_calls': 0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=Path('output/lantern-echo'))
    p.add_argument('--timeline', type=Path, default=ROOT / 'timeline.json')
    p.add_argument('--ffmpeg', default='ffmpeg')
    p.add_argument('--reuse-from', type=Path)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    try:
        print(json.dumps(build(args), indent=2), flush=True)
    except KeyboardInterrupt:
        print('Interrupted. Completed scenes are preserved; repeat with --resume.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'Build failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
