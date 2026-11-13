"""Opt-in real-film reuse and hard-interruption qualification. Never runs in CI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import build

ROOT = Path(__file__).resolve().parent
BOOTSTRAP = '''import runpy,socket,sys
from pathlib import Path
def denied(*args, **kwargs):
    raise RuntimeError("Python network access is blocked during the offline qualification")
socket.socket.connect=denied
socket.socket.connect_ex=denied
socket.create_connection=denied
sys.argv=sys.argv[1:]
sys.path.insert(0,str(Path(sys.argv[0]).parent))
runpy.run_path(sys.argv[0],run_name="__main__")
'''


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns,
            hashlib.sha256(build.regular(p)).hexdigest()) for p in root.rglob('*')
            if p.is_file() and p.name != '.build.lock'}


def command(out, ffmpeg, *extra):
    return [sys.executable, '-c', BOOTSTRAP, str(ROOT / 'build.py'),
            '--out', str(out), '--ffmpeg', ffmpeg, *map(str, extra)]


def run(cmd, log, env):
    with log.open('wb') as stream:
        p = subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT, env=env, timeout=900)
    if p.returncode:
        raise RuntimeError(f'Build failed ({p.returncode}); preserved log: {log}')


def kill_owned(process):
    if process.poll() is not None:
        return
    # Only the process created by this script is targeted. Windows uses its
    # existing owned process handle, never a name/PID search or taskkill rights.
    # Its encoder receives EOF when the killed parent's pipe handles close.
    if os.name == 'nt':
        process.kill()
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True, help='New qualification directory')
    p.add_argument('--baseline', type=Path, help='Optional completed build to preserve and reuse')
    p.add_argument('--ffmpeg', default='ffmpeg')
    args = p.parse_args()
    root = args.out.absolute()
    if root.exists() or any(x.is_symlink() for x in (root, *root.parents)):
        raise ValueError('Qualification output must be new and non-symlinked')
    root.mkdir(parents=True)
    (root / 'tmp').mkdir()
    env = os.environ.copy()
    env.update(TEMP=str(root / 'tmp'), TMP=str(root / 'tmp'), PYTHONDONTWRITEBYTECODE='1')
    baseline = args.baseline.absolute() if args.baseline else root / 'base'
    if not args.baseline:
        print('Building the complete baseline with Python socket connections blocked.', flush=True)
        run(command(baseline, args.ffmpeg), root / 'base.log', env)
    base = build.completed(baseline)
    before = snapshot(baseline)
    published = ROOT.parents[1] / 'docs/assets/lantern-echo/lantern-echo.mp4'
    published_hash = build.sha(build.regular(published))
    timeline = build.read_json(ROOT / 'timeline.json')
    timeline['scenes'][4]['effects']['canopy_gain'] = .6
    revision_input = root / 'revised-timeline.json'
    build.save(revision_input, timeline)
    revised = root / 'revised'
    cmd = command(revised, args.ffmpeg, '--timeline', revision_input, '--reuse-from', baseline)
    flags = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    print('Starting the one-scene revision; interrupting during 05-release.', flush=True)
    with (root / 'interrupted.log').open('wb') as log:
        process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, **flags)
        deadline = time.monotonic() + 240
        interrupted = None
        try:
            while process.poll() is None and time.monotonic() < deadline:
                # Do not poll checkpoint.json while it is being atomically
                # replaced: Windows readers can deny delete-sharing. Observe
                # append-only events, then read the checkpoint once mid-encode.
                events = []
                for line in build.regular(root / 'interrupted.log').splitlines():
                    try:
                        events.append(json.loads(line))
                    except (ValueError, UnicodeDecodeError):
                        pass
                attempts = list((revised / 'scenes').glob('05-release-*.mkv'))
                if (events and events[-1].get('event') == 'scene-start' and events[-1].get('id') == '05-release'
                        and any(f.stat().st_size > 4096 for f in attempts)):
                    state = build.read_json(revised / 'checkpoint.json')
                    if (state.get('active_scene') == '05-release' and '05-release' not in state['completed']
                            and len(state['completed']) == 4):
                        saved = {sid: (rec['file'], *snapshot_file(revised / rec['file'])) for sid, rec in state['completed'].items()}
                        interrupted = {'pid': process.pid, 'active_scene': '05-release',
                                       'completed_scenes': sorted(state['completed']), 'partial_attempts': [f.name for f in attempts]}
                        kill_owned(process)
                        break
                time.sleep(.05)
            if interrupted is None:
                raise RuntimeError('Did not observe the intended in-progress encode; no interruption proof claimed')
        finally:
            kill_owned(process)
    if (revised / 'build-receipt.json').exists():
        raise RuntimeError('Interrupted attempt must not have a completion receipt')
    print('Killed the real builder during encoding. Resuming the same revision.', flush=True)
    run(cmd + ['--resume'], root / 'resumed.log', env)
    result = build.completed(revised)
    assert result['scene_exports'] == {'rendered': 1, 'reused': 5, 'resumed': 4}, result['scene_exports']
    assert result['review']['changed_scenes'] == ['05-release']
    assert result['review']['neighbor_scenes_for_review'] == ['04-catch', '06-greeting']
    assert result['review']['cuts_for_review'] == [
        {'previous': '04-catch', 'next': '05-release', 'at_ms': 7520},
        {'previous': '05-release', 'next': '06-greeting', 'at_ms': 10400}]
    for sid, record in result['completed'].items():
        assert (record['sha256'] == base['completed'][sid]['sha256']) == (sid != '05-release'), sid
        if sid in saved:
            assert (record['file'], *snapshot_file(revised / record['file'])) == saved[sid], sid
    assert snapshot(baseline) == before, 'Baseline bytes or modification times changed'
    assert build.sha(build.regular(published)) == published_hash, 'Published film changed'
    after = snapshot(revised)
    run(cmd + ['--resume'], root / 'completed-resume.log', env)
    assert snapshot(revised) == after, 'Completed resume rewrote an accepted result'
    report = {'status': 'passed', 'real_process_interruption': interrupted,
              'scene_exports_after_resume': result['scene_exports'], 'unchanged_scene_exports': 9,
              'baseline_bytes_and_mtimes_preserved': True, 'four_checkpoint_scene_files_and_mtimes_preserved': True,
              'completed_resume_writes_no_result_files': True, 'published_movie_preserved': published_hash,
              'baseline_movie_sha256': base['movie_sha256'], 'revised_movie_sha256': result['movie_sha256'],
              'review': result['review'], 'provider_calls': 0,
              'network_scope': 'Python socket connects blocked in child builds; external FFmpeg receives local files and raw pipes only'}
    build.save(root / 'verification.json', report)
    print(json.dumps(report, indent=2), flush=True)


def snapshot_file(path):
    return (path.stat().st_size, path.stat().st_mtime_ns, build.sha(build.regular(path)))


if __name__ == '__main__':
    main()
