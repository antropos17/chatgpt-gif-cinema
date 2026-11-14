"""Checkpointed native shot projects; preserves earlier results and reviewed source art."""
from __future__ import annotations
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from .durability import durable_write
from .shot_project import load_project, dependencies, review
MAX_BYTES = 512 * 1024 * 1024
MAX_FILE = 128 * 1024 * 1024
FORMAT = 'gif-cinema-shot-build-v1'

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


def video_frames(path):
    import av
    with av.open(str(path)) as container:
        for f in container.decode(video=0):
            yield f


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


def source_hashes():
    return {name: sha(regular(Path(__file__).with_name(name))) for name in
            ('shots.py', 'shot_renderer.py', 'shot_project.py', 'durability.py')}


def engine_identity(ffmpeg):
    import av
    import PIL
    version = subprocess.run([ffmpeg, '-version'], capture_output=True, check=True, timeout=15).stdout.decode().splitlines()[0]
    return sha(canonical({**source_hashes(), 'pillow': PIL.__version__, 'av': av.__version__,
                          'python': sys.version, 'ffmpeg': version}))


def project_identity(value):
    portable = copy.deepcopy(value)
    for fact in portable['files'].values():
        fact.pop('path')
    return sha(canonical(portable))


class BuildContext:
    def __init__(self, path):
        self.path = Path(path).absolute()
        self.value, self.paths = load_project(self.path)
        self.manifest = {'files': self.value['files']}
        self.frames = self.value['scenes'][-1]['end_frame'] - self.value['scenes'][0]['start_frame']

    def identities(self, engine):
        keys = {}
        common = {k: v for k, v in self.value.items() if k not in ('scenes', 'files', 'clips', 'actors', 'audio', 'title')}
        for scene in self.value['scenes']:
            tracks = dependencies(self.value, scene)
            names = sorted({track['clip'] for actor in tracks for track in actor['tracks']})
            clips = {n: self.value['clips'][n] for n in names}
            assets = {n: self.value['files'][n]['sha256'] for n in
                      [self.value['background'], *sorted({c['source'] for c in clips.values()})]}
            keys[scene['id']] = sha(canonical({'scene': scene, 'common': common, 'actors': tracks,
                                               'clips': clips, 'assets': assets, 'engine': engine}))
        return keys

    def verify_scene(self, root, record, key):
        path = local(root, record['file'])
        if record['key'] != key or sha(regular(path)) != record['sha256']:
            raise ValueError(f'Completed scene changed: {path.name}')
        count = 0
        for count, f in enumerate(video_frames(path), 1):
            if (f.width, f.height) != (self.value["width"], self.value["height"]) or abs(float(f.pts * f.time_base) - (count - 1) / self.value["fps"]) > 1e-6:
                raise ValueError('Scene geometry/timestamps differ')
            if count > len(record['rgb_sha256']) or sha(f.to_image().convert('RGB').tobytes()) != record['rgb_sha256'][count - 1]:
                raise ValueError('Lossless scene pixels differ')
        if count != record['frames']:
            raise ValueError('Incomplete scene')
        return path


    def raw_command(self, ffmpeg):
        return [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n', '-f', 'rawvideo',
                '-pix_fmt', 'rgb24', '-s', f'{self.value["width"]}x{self.value["height"]}', '-r', str(self.value['fps']), '-i', 'pipe:0']


    def render_scene(self, ffmpeg, out, s, key, compositor):
        name = f'scenes/{s["id"]}-{uuid.uuid4().hex}.mkv'
        path = local(out, name)
        hashes = []
        def images():
            for index in range(s['start_frame'], s['end_frame']):
                im = compositor.frame(index / self.value["fps"], s)
                hashes.append(sha(im.tobytes()))
                yield im
        encode(self.raw_command(ffmpeg) + ['-an', '-c:v', 'ffv1', '-level', '3', '-threads', '2', '-pix_fmt', 'bgr0', str(path)], images())
        record = {'file': name, 'key': key, 'frames': len(hashes), 'rgb_sha256': hashes, 'sha256': sha(regular(path))}
        self.verify_scene(out, record, key)
        return record


    def verify_movie(self, path):
        import av
        count = 0
        for count, f in enumerate(video_frames(path), 1):
            if (f.width, f.height) != (self.value["width"], self.value["height"]) or abs(float(f.pts * f.time_base) - (count - 1) / self.value["fps"]) > 1e-6:
                raise ValueError('Movie geometry/timestamps differ')
        with av.open(str(path)) as c:
            if len(c.streams.audio) != 1 or c.streams.audio[0].channels != 2 :
                raise ValueError('Expected stereo sound')
            samples = sum(f.samples for f in c.decode(audio=0))
            if not samples:
                raise ValueError('Expected completely decodable audio')
        if count != self.frames:
            raise ValueError('Movie frame count differs')
        return sha(regular(path))


    def completed(self, root):
        rec = read_json(root / 'build-receipt.json')
        if rec.get('format') != FORMAT or rec.get('status') != 'complete':
            raise ValueError('Not a completed shot project build')
        if project_identity(self.value) != project_identity(rec['timeline']):
            raise ValueError('Completed project changed')
        if rec['keys'] != self.identities(rec['engine']) or set(rec['completed']) != set(rec['keys']):
            raise ValueError('Completed project or scene set changed')
        for sid, record in rec['completed'].items():
            scene = next(s for s in self.value['scenes'] if s['id'] == sid)
            if record['frames'] != scene['end_frame']-scene['start_frame'] or len(record['rgb_sha256']) != record['frames']:
                raise ValueError('Completed scene frame count changed')
            self.verify_scene(root, record, rec['keys'][sid])
        if sha(regular(local(root, rec['ready']['audio']))) != rec['audio_sha256']:
            raise ValueError('Completed PCM audio changed')
        if self.verify_movie(root / 'film.mp4') != rec['movie_sha256']:
            raise ValueError('Completed movie changed')
        return rec


    def build(self, args):
        ffmpeg = shutil.which(args.ffmpeg)
        if not ffmpeg:
            raise ValueError('FFmpeg is required on PATH, or supply --ffmpeg /path/to/ffmpeg')
        sources = source_hashes()
        engine = engine_identity(ffmpeg)
        value, manifest = self.value, self.manifest
        keys = self.identities(engine)
        out = Path(os.path.abspath(args.out))
        if (any(out == p or out in p.parents for p in self.paths.values()) or out == self.path.parent
                or any(p.is_symlink() for p in (out, *out.parents))):
            raise ValueError('Use a separate non-symlink output directory outside the source assets')
        prior = Path(os.path.abspath(args.reuse_from)) if args.reuse_from else None
        if prior == out:
            raise ValueError('Revisions must use a new output directory')
        old = BuildContext(prior / 'project.json').completed(prior) if prior else None
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
            # A portable source snapshot is independent of the author's checkout.
            portable = copy.deepcopy(value)
            for name, fact in portable['files'].items():
                relative = f'assets/{fact["sha256"]}.png'
                target = out / relative
                target.parent.mkdir(exist_ok=True)
                if target.exists():
                    if sha(regular(target)) != fact['sha256']:
                        raise ValueError('Portable source changed; preserved')
                else:
                    # Publish only a fully synced source copy. A killed copy
                    # leaves an unselected temporary attempt, never a bad asset.
                    durable_write(target, regular(self.paths[name]))
                fact['path'] = relative
            if (out / 'project.json').exists():
                if read_json(out / 'project.json') != portable:
                    raise ValueError('Portable project changed; preserved')
            else:
                save(out / 'project.json', portable)
            budget(out)
            if (out / 'build-receipt.json').exists():
                rec = self.completed(out)
                return {'status': 'complete', 'already_complete': True, 'movie': str(out / 'film.mp4'), 'movie_sha256': rec['movie_sha256']}
            counts = {'rendered': 0, 'reused': 0, 'resumed': 0}
            compositor = None
            for s in value['scenes']:
                sid, key = s['id'], keys[s['id']]
                if sid in state['completed']:
                    self.verify_scene(out, state['completed'][sid], key)
                    counts['resumed'] += 1
                    continue
                state['active_scene'] = sid
                save(state_path, state)
                print(json.dumps({'event': 'scene-start', 'id': sid}), flush=True)
                if old and old['keys'].get(sid) == key:
                    source = self.verify_scene(prior, old['completed'][sid], key)
                    record = dict(old['completed'][sid])
                    record['file'] = f'scenes/{sid}-{uuid.uuid4().hex}.mkv'
                    shutil.copyfile(source, local(out, record['file']))
                    self.verify_scene(out, record, key)
                    counts['reused'] += 1
                else:
                    if compositor is None:
                        from .shot_renderer import Renderer
                        compositor = Renderer(value, self.paths)
                    record = self.render_scene(ffmpeg, out, s, key, compositor)
                    counts['rendered'] += 1
                budget(out)
                state['completed'][sid] = record
                state.pop('active_scene', None)
                save(state_path, state)
                print(json.dumps({'event': 'scene-complete', 'id': sid, 'counts': counts}), flush=True)
            movie = out / 'film.mp4'
            if 'ready' not in state:
                if movie.exists():
                    raise ValueError('Unrecorded existing movie is preserved; use a new destination')
                if compositor is None:
                    from .shot_renderer import Renderer
                    compositor = Renderer(value, self.paths)
                audio = out / f'sound-{uuid.uuid4().hex}.wav'
                compositor.sound(audio)
                partial = out / f'film-{uuid.uuid4().hex}.mp4'
                def images():
                    for s in value['scenes']:
                        record = state['completed'][s['id']]
                        path = self.verify_scene(out, record, keys[s['id']])
                        for index, f in enumerate(video_frames(path)):
                            im = f.to_image().convert('RGB')
                            if sha(im.tobytes()) != record['rgb_sha256'][index]:
                                raise ValueError('Scene changed during final assembly')
                            yield im
                encode(self.raw_command(ffmpeg) + ['-i', str(audio), '-t', str(self.frames / self.value['fps']), '-c:v', 'libx264', '-crf', '16',
                       '-preset', 'medium', '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
                       '-movflags', '+faststart', str(partial)], images())
                state['ready'] = {'file': partial.name, 'sha256': self.verify_movie(partial), 'audio': audio.name,
                                  'audio_sha256': sha(regular(audio))}
                save(state_path, state)
            ready = state['ready']
            if (load_project(self.path)[0] != value or source_hashes() != sources):
                raise ValueError('Inputs changed during build; completed scenes are preserved, publication refused')
            if movie.exists():
                if self.verify_movie(movie) != ready['sha256']:
                    raise ValueError('Existing movie changed; it has been preserved')
            else:
                partial = local(out, ready['file'])
                if self.verify_movie(partial) != ready['sha256']:
                    raise ValueError('Prepared movie changed')
                os.replace(partial, movie)
            budget(out)
            rec = {**state, 'status': 'complete', 'scene_exports': counts, 'movie_sha256': ready['sha256'],
                   'audio_sha256': ready['audio_sha256'], 'visual_acceptance': 'not inferred by build checks'}
            save(out / 'build-receipt.json', rec)
            return {'status': 'complete', 'movie': str(movie), 'movie_sha256': rec['movie_sha256'],
                    'scene_exports': counts, 'review': plan, 'provider_calls': 0}



def build_project(path, out, *, resume=False, reuse_from=None, ffmpeg='ffmpeg', dry_run=False):
    from argparse import Namespace
    context = BuildContext(path)
    if dry_run:
        # Planning needs no encoder or optional video decoder.
        old = BuildContext(Path(reuse_from) / 'project.json').completed(Path(reuse_from)) if reuse_from else None
        encoder = shutil.which(ffmpeg)
        if old and not encoder:
            raise ValueError('Reuse planning needs the encoder version to compare scene identities')
        return {'status': 'planned', 'provider_calls': 0,
                'review': review(context.value, context.identities(engine_identity(encoder) if old else 'planning'), old)}
    return context.build(Namespace(out=out, resume=resume, reuse_from=reuse_from,
                                   ffmpeg=ffmpeg, dry_run=False))


def verify_project(directory):
    root = Path(directory).absolute()
    context = BuildContext(root / 'project.json')
    receipt = context.completed(root)
    return {'status': 'verified', 'movie_sha256': receipt['movie_sha256'], 'provider_calls': 0}
