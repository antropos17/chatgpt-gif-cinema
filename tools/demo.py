#!/usr/bin/env python3
"""Build the bundled silent GIF edit locally. Never install, generate or overwrite."""
import argparse
import contextlib
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Always use this checkout, not another globally installed runtime.
sys.path.insert(0, str(ROOT))


class DemoError(RuntimeError):
    pass


def _report(message, *, file=None, flush=False):
    """Escape unsupported display characters without changing paths or the stream."""
    stream = sys.stdout if file is None else file
    encoding = getattr(stream, 'encoding', None)
    if encoding:
        message = message.encode(encoding, errors='backslashreplace').decode(encoding)
    print(message, file=stream, flush=flush)


def prerequisites():
    if sys.version_info < (3, 10):
        raise DemoError('Python 3.10+ is required. Activate a supported Python environment.')
    try:
        import PIL
        from PIL import Image  # Also check the compiled Pillow extension.
    except (ImportError, OSError) as exc:
        raise DemoError('Pillow is missing or broken. From this checkout, activate your virtual environment and run: python -m pip install .') from exc
    version = re.match(r'^(\d+)\.(\d+)', PIL.__version__)
    if not version or tuple(map(int, version.groups())) < (10, 1):
        raise DemoError('Pillow 10.1+ is required. In your virtual environment, run: python -m pip install .')
    from gif_cinema import doctor, render
    if Path(render.__file__).resolve().parent != ROOT/'gif_cinema':
        raise DemoError('A different GIF Cinema runtime is loaded. Run this script in a fresh Python process.')
    for name in ('ffmpeg', 'ffprobe'):
        if not doctor.inspect_tool(name)['available']:
            raise DemoError(f'{name} is missing or cannot run. Install FFmpeg with ffprobe, reopen the terminal, then check: {name} -version. See https://ffmpeg.org/download.html')
    doctor.require_film_capabilities(audio=False)
    return render


def reserve_output(requested):
    """Claim a fresh directory. Repeats get new folders, not mutable resume state."""
    base = Path(requested).absolute() if requested is not None else ROOT/'output/demo'
    if any(p.is_symlink() for p in base.parents):
        raise DemoError('Output parents must not be symbolic links. Choose a new local directory.')
    for number in range(1, 1001):
        target = base if number == 1 else base.with_name(f'{base.name}-{number}')
        try:
            target.mkdir(parents=True, exist_ok=False)
            return target
        except FileExistsError as exc:
            if requested is not None:
                raise DemoError(f'Output already exists and was not changed: {target}. Use --out with a new directory.') from exc
    raise DemoError('No free demo folder among demo through demo-1000. Choose --out NEW_DIRECTORY.')


def verify(render, script, result, output):
    cli = render.cli
    manifest = json.loads(cli.read_local_bytes(output/'render-manifest.json', 1024*1024, 'Demo manifest'))
    receipt = json.loads(cli.read_local_bytes(output/'receipt.json', 1024*1024, 'Demo receipt'))
    if (result != receipt or receipt.get('status') != 'complete' or receipt.get('api_calls') != 0
            or receipt.get('generated') != 0 or receipt.get('imported') != 3
            or manifest.get('attempts') != [] or manifest.get('script_sha256') != script['_script_sha256']):
        raise DemoError('Demo receipt does not confirm a complete zero-call import.')
    if set(manifest['shots']) != {s['id'] for s in script['shots']}:
        raise DemoError('Demo shot list differs from the bundled script.')
    for shot in script['shots']:
        record = manifest['shots'][shot['id']]
        if (record.get('origin') != 'imported' or record.get('frames') != 16
                or record.get('frame_durations_ms') != [160]*16
                or record.get('sha256') != shot['source_sha256']
                or not render.cached(output, record, shot)
                or render.digest(cli.read_gif_bytes(shot['source_path'])) != shot['source_sha256']):
            raise DemoError('Bundled or imported GIF bytes/timing changed; output was kept for inspection.')
    if render.digest(cli.read_local_bytes(ROOT/'examples/film.json', render.MAX_SCRIPT_BYTES, 'Demo script')) != script['_script_sha256']:
        raise DemoError('The bundled script changed during rendering.')
    movie = output/'film.mp4'
    info = render.probe(movie, 512, 512, 7.68, 25, 3)
    if render.digest(cli.read_local_bytes(movie, 128*1024*1024, 'Demo movie')) != manifest['film']['sha256']:
        raise DemoError('Demo movie bytes changed during verification.')
    # A silent demo must not accidentally gain an audio track.
    streams = json.loads(cli.run_media(['ffprobe', '-v', 'error', '-select_streams', 'a',
                                      '-show_entries', 'stream=index', '-of', 'json', str(movie)]).stdout)
    if streams.get('streams'):
        raise DemoError('Expected a silent demo; found an audio track.')
    return info


def run_demo(requested=None):
    print('Checking local prerequisites. Nothing will be installed.')
    render = prerequisites()
    args = render.cli.build_parser().parse_args(['render', str(ROOT/'examples/film.json'),
            '--execute', '--max-api-calls', '0', '--retries', '0'])
    script = render.load_script(Path(args.script), args, source_only=True)
    if (script['width'], script['height'], script['fps']) != (512, 512, 25) or len(script['shots']) != 3 or script.get('audio_path'):
        raise DemoError('Bundled demo settings changed; expected three silent 512x512 GIF shots at 25 fps.')
    if any(s['expected_ms'] != 2560 for s in script['shots']):
        raise DemoError('Bundled GIF timing changed; expected three 2.56-second shots.')
    output = reserve_output(requested)
    args.out = str(output)
    _report(f'Building three existing GIFs with zero API calls. Output: {output}', flush=True)
    # Keep the default experience short; the normal renderer still saves its
    # manifest, inspection reports and receipt inside this newly claimed folder.
    with contextlib.redirect_stdout(io.StringIO()):
        result = render.run(args)
    verify(render, script, result, output)
    movie = output/'film.mp4'
    _report(f'Ready: {movie}')
    print('Verified: 7.68 seconds | 192 frames | 512x512 | 25 fps | silent')
    print('Existing footage only: no new drawings, interpolation or soundtrack. Review the cuts yourself.')
    _report(f'Open the MP4 in your video player. Review sheet: {output / "contact-sheet.png"}')
    return movie


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Requires Python 3.10+, Pillow 10.1+, FFmpeg and ffprobe. No API key needed.
Windows (PowerShell): activate .venv\\Scripts\\Activate.ps1
macOS/Linux: source .venv/bin/activate
Then install dependencies yourself: python -m pip install .
Check tools: ffmpeg -version and ffprobe -version
No automatic install or browser launch. Existing outputs and failed attempts are kept.""")
    parser.add_argument('--out', metavar='NEW_DIRECTORY', help='new destination relative to your current directory; existing paths are refused. Default: checkout output/demo, demo-2, ...')
    args = parser.parse_args(argv)
    try:
        run_demo(args.out)
        return 0
    except KeyboardInterrupt:
        print('Demo interrupted. Any created output was kept; run again for a fresh directory.', file=sys.stderr)
        return 130
    except Exception as exc:
        _report(f'Demo failed: {exc}\nAny created output was kept. Check python -m gif_cinema doctor; choose a new output directory to retry.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
