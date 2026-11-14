"""Opt-in native film migration proof: all frames, one-scene reuse and owned hard kill.

Keeps originals and all evidence. No generation, interpolation inference or CI workload.
"""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gif_cinema import shots

BOOTSTRAP = '''import runpy,socket,sys
def denied(*args,**kwargs):
    raise RuntimeError("Python socket connections blocked during native qualification")
socket.socket.connect=denied
socket.socket.connect_ex=denied
socket.create_connection=denied
sys.argv=['gif_cinema',*sys.argv[1:]]
runpy.run_module('gif_cinema',run_name='__main__')
'''


def snapshot(root):
    return {p.relative_to(root).as_posix(): [p.stat().st_size, p.stat().st_mtime_ns, shots.sha(shots.regular(p))]
            for p in root.rglob('*') if p.is_file() and p.name != '.build.lock'}


def kill_owned(process):
    if process.poll() is None:
        if os.name == 'nt':
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--baseline', type=Path, help='Reuse a verified native baseline from the same project and engine')
    args = parser.parse_args()
    out = Path(os.path.abspath(args.out))
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Use a new non-symlink qualification directory')
    out.mkdir(parents=True)
    (out/'tmp').mkdir()
    env = {**os.environ, 'TEMP': str(out/'tmp'), 'TMP': str(out/'tmp'),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(ROOT)}
    project = ROOT/'examples/native-shots/project.json'
    original = ROOT/'docs/assets/lantern-echo/lantern-echo.mp4'
    original_stamp = [original.stat().st_mtime_ns, shots.sha(shots.regular(original))]

    def command(source, target, *extra):
        return [sys.executable, '-c', BOOTSTRAP, 'sequence', 'build', str(source), '--out', str(target),
                '--ffmpeg', args.ffmpeg, *map(str, extra)]

    def run(cmd, name):
        if sum(p.stat().st_size for p in out.rglob('*') if p.is_file()) > 1024**3:
            raise ValueError('Qualification output exceeds 1 GiB; no additional batch started')
        with (out/name).open('xb') as log:
            result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=ROOT, timeout=900)
        if result.returncode:
            raise RuntimeError(f'Failed native command; preserved {out/name}')

    context = shots.BuildContext(project)
    baseline = Path(os.path.abspath(args.baseline)) if args.baseline else out/'baseline'
    if not args.baseline:
        print('Building the native five-scene baseline.', flush=True)
        run(command(project, baseline), 'baseline.log')
    base = context.completed(baseline)
    if base['engine'] != shots.engine_identity(args.ffmpeg):
        raise ValueError('Qualification baseline must use the current engine')
    before = snapshot(baseline)
    spec = importlib.util.spec_from_file_location('accepted_compositor', ROOT/'examples/lantern-echo/compositor.py')
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    reference.load_assets(ROOT/'examples/lantern-echo')
    compared = 0
    for scene in context.value['scenes']:
        for source_index, expected in zip(range(scene['start_frame'], scene['end_frame']), base['completed'][scene['id']]['rgb_sha256']):
            image = reference.frame(source_index/context.value['fps'], {**scene, 'effects': {'canopy_gain': 1}})
            if shots.sha(image.tobytes()) != expected:
                raise ValueError(f'First source-pixel mismatch at frame {source_index}; baseline retained')
            compared += 1
    if compared != 290:
        raise ValueError('Expected all 290 fragment frames')
    reference.sound(out/'reference-full.wav')
    with wave.open(str(out/'reference-full.wav'), 'rb') as sound:
        sound.setpos(134400)
        pcm = sound.readframes(278400)
    with wave.open(str(baseline/base['ready']['audio']), 'rb') as sound:
        if sound.readframes(sound.getnframes()) != pcm:
            raise ValueError('PCM differs from the exact original interval')
    print('All 290 pre-encode frames and the complete PCM interval match the accepted source.', flush=True)

    # Measure the delivered viewing copies independently. Different H.264 GOP
    # context is expected when exporting a fragment instead of a whole film.
    import av
    from PIL import ImageChops
    count, squared, absolute = 0, 0, 0
    minimum_psnr = float('inf')
    native_frames = shots.video_frames(baseline/'film.mp4')
    with av.open(str(original)) as container:
        for source_index, frame in enumerate(container.decode(video=0)):
            if not 140 <= source_index < 430:
                continue
            actual = next(native_frames).to_image().convert('RGB')
            expected = frame.to_image().convert('RGB')
            histogram = ImageChops.difference(actual, expected).histogram()
            frame_squared = sum((i % 256)**2*n for i, n in enumerate(histogram))
            squared += frame_squared
            absolute += sum((i % 256)*n for i, n in enumerate(histogram))
            minimum_psnr = min(minimum_psnr, 10*math.log10(255**2/(frame_squared/(actual.width*actual.height*3)))) if frame_squared else minimum_psnr
            count += 1
    samples = count*960*540*3
    if count != 290 or minimum_psnr < 35:
        raise ValueError(f'Delivery comparison needs investigation: frames={count}, minimum PSNR={minimum_psnr}')
    shots.save(out/'source-comparison.json', {'frames_pixel_exact': compared, 'pcm_interval_byte_exact': True,
               'delivered_frames_compared': count, 'delivered_rgb_mae': absolute/samples,
               'delivered_psnr': 10*math.log10(255**2/(squared/samples)), 'minimum_frame_psnr': minimum_psnr})
    run([args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-ss', '5.6', '-t', '11.6', '-i', str(original),
         '-i', str(baseline/'film.mp4'), '-filter_complex',
         '[0:v]scale=480:270,setsar=1[a];[1:v]scale=480:270,setsar=1[b];[a][b]hstack=inputs=2[v]',
         '-map', '[v]', '-map', '1:a:0', '-c:v', 'libx264', '-crf', '18', '-threads', '2', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-movflags', '+faststart', str(out/'comparison.mp4')], 'comparison.log')
    (out/'cuts').mkdir()
    for index, seconds in enumerate([1.92, 4.8, 7.2, 9.12], 1):
        run([args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-n', '-ss', str(seconds-.48), '-t', '0.96', '-i', str(baseline/'film.mp4'),
             '-vf', 'setpts=2*(PTS-STARTPTS)', '-an', '-c:v', 'libx264', '-crf', '18', '-threads', '2',
             '-movflags', '+faststart', str(out/f'cuts/cut-{index}.mp4')], f'cut-{index}.log')

    revised_value = json.loads(project.read_text(encoding='utf-8'))
    # Keep source asset paths relative to the relocated revision recipe.
    for name, fact in revised_value['files'].items():
        fact['path'] = Path(os.path.relpath(context.paths[name], out)).as_posix()
    revised_value['scenes'][1]['effects']['gain'] = .6
    revised_source = out/'revised-project.json'
    shots.save(revised_source, revised_value)
    uninterrupted = out/'uninterrupted'
    run(command(revised_source, uninterrupted, '--reuse-from', baseline), 'uninterrupted.log')
    uninterrupted_context = shots.BuildContext(revised_source)
    regular = uninterrupted_context.completed(uninterrupted)
    if regular['scene_exports'] != {'rendered': 1, 'reused': 4, 'resumed': 0}:
        raise ValueError('One-scene revision did not reuse the other four scenes')

    revised = out/'resumed'
    cmd = command(revised_source, revised, '--reuse-from', baseline)
    flags = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    saved = None
    print('Hard-interrupting the owned native CLI process while scene 05 is encoding.', flush=True)
    with (out/'interrupted.log').open('xb') as log:
        process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=ROOT, **flags)
        deadline = time.monotonic()+240
        try:
            while process.poll() is None and time.monotonic() < deadline:
                events = []
                for line in shots.regular(out/'interrupted.log').splitlines():
                    try:
                        events.append(json.loads(line))
                    except (ValueError, UnicodeDecodeError):
                        pass
                attempts = list((revised/'scenes').glob('05-release-*.mkv'))
                if (events and events[-1].get('event') == 'scene-start' and events[-1].get('id') == '05-release'
                        and any(p.stat().st_size > 4096 for p in attempts)):
                    state = shots.read_json(revised/'checkpoint.json')
                    if set(state['completed']) == {'04-catch'} and state.get('active_scene') == '05-release':
                        rec = state['completed']['04-catch']; path = revised/rec['file']
                        saved = [rec['file'], path.stat().st_mtime_ns, shots.sha(shots.regular(path))]
                        kill_owned(process)
                        break
                time.sleep(.05)
            if saved is None:
                raise RuntimeError('Intended live encoder interruption was not observed; no proof claimed')
        finally:
            kill_owned(process)
    if (revised/'build-receipt.json').exists():
        raise ValueError('Interrupted result unexpectedly completed')
    run(cmd+['--resume'], 'resumed.log')
    resumed = uninterrupted_context.completed(revised)
    if resumed['scene_exports'] != {'rendered': 1, 'reused': 3, 'resumed': 1}:
        raise ValueError('Incorrect native resume decisions')
    first = resumed['completed']['04-catch']; path = revised/first['file']
    if saved != [first['file'], path.stat().st_mtime_ns, shots.sha(shots.regular(path))]:
        raise ValueError('Completed checkpoint changed')
    unchanged = [sid for sid in base['completed'] if sid != '05-release']
    if any(base['completed'][sid]['sha256'] != resumed['completed'][sid]['sha256'] for sid in unchanged):
        raise ValueError('An unchanged scene export was modified')
    if resumed['movie_sha256'] != regular['movie_sha256']:
        raise ValueError('Resumed movie differs from uninterrupted revision')
    after = snapshot(revised)
    run(cmd+['--resume'], 'completed-resume.log')
    if snapshot(revised) != after or snapshot(baseline) != before:
        raise ValueError('Completed resume or baseline result changed')
    if original_stamp != [original.stat().st_mtime_ns, shots.sha(shots.regular(original))]:
        raise ValueError('Published original changed')
    result = dict(status='passed', scope='Native CLI, source pixel comparison and owned hard interruption; visual playback review recorded separately',
                  source_range=[140, 430], source_interval_seconds=[5.6, 17.2], frames_pixel_exact=compared,
                  pcm_interval_byte_exact=True, delivered_frames_compared=count,
                  delivered_rgb_mae=absolute/samples, delivered_psnr=10*math.log10(255**2/(squared/samples)),
                  minimum_frame_psnr=minimum_psnr, baseline_movie_sha256=base['movie_sha256'],
                  original_movie_sha256=original_stamp[1], original_bytes_and_mtime_preserved=True,
                  uninterrupted_revision=regular['scene_exports'], hard_kill_resume=resumed['scene_exports'],
                  unchanged_scene_exports=len(unchanged), checkpoint_file_and_mtime_preserved=True,
                  baseline_files_and_mtimes_preserved=True, completed_resume_writes_no_result_files=True,
                  resumed_movie_matches_uninterrupted_bytes=True, revised_movie_sha256=resumed['movie_sha256'],
                  review=resumed['review'], provider_calls=0, interpolation_inference_runs=0,
                  network_scope='Python socket connects blocked; FFmpeg inputs are local files and raw pipes')
    shots.save(out/'verification.json', result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
