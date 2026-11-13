"""Check packaged resource hashes and required runtime interfaces without network or writes."""
import argparse
from contextlib import redirect_stderr
import hashlib
from importlib import metadata
import inspect
import io
import json
from pathlib import Path, PurePosixPath
import sys

# Runtime imports must not create bytecode during a read-only install check.
sys.dont_write_bytecode = True

SKILL = Path(__file__).resolve().parents[1]
# Independent expected inventory, checked against the builder in regression tests.
RESOURCE_FILES = frozenset({
    'assets/example/factory.json', 'references/factory.md', 'references/master.md', 'references/sequences.md',
    'scripts/smoke_factory.py', 'scripts/smoke_master.py',
    'assets/example/motion-loop.json',
    'references/motion.md',
    'scripts/smoke_motion.py',
    'assets/example/gif-layer.json',
    'scripts/verify_layers.py',
    'scripts/smoke_layers.py',
    'references/layers.md',
    'assets/example/stroke-reveal.json',
    'assets/example/layered-shapes.json',
    'SKILL.md',
    'LICENSE',
    'THIRD_PARTY_NOTICES.md',
    'agents/openai.yaml',
    'runtime.json',
    'scripts/check_install.py',
    'scripts/smoke_test.py',
    'scripts/smoke_media.py',
    'scripts/review_gif.py',
    'scripts/story_project.py',
    'scripts/story_chapters.py',
    'scripts/story_pages.py',
    'references/generation.md',
    'references/review.md',
    'references/full-frame-review.md',
    'references/sprites.md',
    'references/storytelling.md',
    'references/story-project.md',
    'references/story-pages.md',
    'assets/example/film.json',
    'assets/example/storyboard.json',
    'assets/example/storybook.json',
    'assets/example/storyboard.pending.json',
    'assets/example/takes.example.json',
    'assets/example/long-story.plan.json',
    'assets/example/shot-01.gif',
    'assets/example/shot-02.gif',
    'assets/example/shot-03.gif',
})


def verify_files(root=SKILL):
    root = Path(root)
    path = root / 'package-manifest.json'
    if not path.is_file():
        return {'status': 'not-present', 'note': 'Source checkout; build and extract a ZIP to check its resource manifest.'}
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('Invalid package manifest')
    if set(manifest['files']) != RESOURCE_FILES:
        raise ValueError('Package manifest resource inventory is incomplete or unexpected')
    for name, expected in manifest['files'].items():
        parts = PurePosixPath(name).parts
        if (not parts or '\\' in name or ':' in name or name.startswith('/') or
                any(part in ('.', '..') for part in parts) or PurePosixPath(name).as_posix() != name):
            raise ValueError('Unsafe package manifest path')
        resource = root.joinpath(*parts)
        if (any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)) or
                not resource.is_file()):
            raise ValueError(f'Missing or symlinked resource: {name}')
        data = resource.read_bytes()
        if expected != {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}:
            raise ValueError(f'Package resource changed: {name}')
    runtime = json.loads((root / 'runtime.json').read_text(encoding='utf-8'))
    if (manifest.get('skill_version') != runtime.get('skill_version') or
            manifest.get('runtime_commit') != runtime.get('runtime_commit') or
            manifest.get('runtime_bundled') is not False):
        raise ValueError('Package/runtime manifest mismatch')
    return {'status': 'passed', 'resource_count': len(manifest['files']),
            'notice': 'Checksums detect revision mismatch; they are not a publisher signature.'}


def check_lossless(required=False):
    """Inspect the optional codec in memory; never create a media file."""
    report = {'status': 'unavailable', 'requirement': 'av>=16.1,<17',
              'required': bool(required), 'ffv1_encoder': False, 'ffv1_decoder': False}
    try:
        import av
        from fractions import Fraction
        version = tuple(int(part) for part in av.__version__.split('.')[:2])
        report['version'] = av.__version__
        if not (version >= (16, 1) and version < (17, 0)):
            raise ValueError('PyAV version is outside >=16.1,<17')
        encoder = av.CodecContext.create('ffv1', 'w')
        encoder.width = encoder.height = 24
        encoder.pix_fmt = 'bgra'
        encoder.time_base = Fraction(1, 100)
        encoder.open()
        report['ffv1_encoder'] = True
        # FFV1 decoder initialization needs stream extradata. Check codec
        # availability here; the smoke opens and decodes the real encoded master.
        av.Codec('ffv1', 'r')
        report['ffv1_decoder'] = True
        report['status'] = 'available'
    except Exception as error:
        report['reason'] = f'{type(error).__name__}: {error}'
        if required:
            raise ValueError('Lossless master requires av>=16.1,<17 with usable FFV1 encoder and decoder; '
                             'install the pinned runtime with [lossless]') from error
    return report


def check_runtime(root=SKILL, require_master=False):
    runtime = json.loads((Path(root) / 'runtime.json').read_text(encoding='utf-8'))
    import gif_cinema
    from gif_cinema import cli, factory, layers, master, master_script, motion, sprites, sequence, sequence_incremental, sequence_master
    if 'fixed_canvas' not in inspect.signature(cli.check_gif_limits).parameters:
        raise ValueError('Runtime lacks bounded review decoding; install the pinned runtime')
    if not all(callable(getattr(sprites, name, None)) for name in ('load_gif', 'load_sheet', 'export')):
        raise ValueError('Runtime lacks the required sprite interfaces')
    parser = cli.build_parser()
    for arguments in (['sprites', 'pack', 'input.gif', '--out', 'unused', '--dry-run'],
                      ['sprites', 'slice', 'input.json', '--out', 'unused', '--dry-run']):
        try:
            with redirect_stderr(io.StringIO()):
                parser.parse_args(arguments)
        except SystemExit as error:
            raise ValueError('Runtime lacks sprite CLI commands; install the pinned runtime') from error
    if not all(callable(getattr(layers, name, None)) for name in
               ('normalize_scene', 'prepare_scene', 'render_scene', 'render_at', 'read_regular')):
        raise ValueError('Runtime lacks required editable layer interfaces')
    try:
        layers.normalize_scene({'format': 'gif-cinema-layered-scene', 'schema_version': 1,
            'width': 32, 'height': 32, 'fps': 25, 'duration_ms': 160, 'layers': [
                {'id': 'line', 'type': 'stroke', 'size': [16, 16],
                 'points': [[2, 2], [12, 12]], 'keyframes': [
                    {'at': 0, 'reveal': 0}, {'at': 1, 'reveal': 1}]}]})
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError('Runtime lacks stroke layer support; install the pinned runtime') from error
    try:
        layers.normalize_scene({'format': 'gif-cinema-layered-scene', 'schema_version': 1,
            'width': 32, 'height': 32, 'fps': 50, 'duration_ms': 160, 'layers': [
                {'id': 'actor', 'type': 'gif', 'source': 'unused.gif',
                 'size': [16, 16], 'playback': 'once'}]})
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError('Runtime lacks animated GIF layers; install the pinned runtime') from error
    if not all(callable(getattr(motion, name, None)) for name in
               ('motion', 'load_recipe', 'normalize_recipe', 'decode_source', 'build_timeline', 'sample_timeline',
                'render_frame', 'evaluate_keyframes')):
        raise ValueError('Runtime lacks required whole-image motion interfaces')
    for arguments in (['motion', 'input.gif', '--preset', 'push-in', '--out', 'unused', '--dry-run'],
                      ['motion', 'input.gif', '--recipe', 'input.json', '--out', 'unused', '--dry-run']):
        try:
            with redirect_stderr(io.StringIO()):
                parser.parse_args(arguments)
        except SystemExit as error:
            raise ValueError('Runtime lacks motion CLI commands; install the pinned runtime') from error
    for label, component, names in (
            ('factory', factory, ('plan_factory', 'build_factory', 'verify_factory', 'run')),
            ('master', master, ('plan', 'build', 'verify_master', 'require_av', 'rgba_frame', 'run')),
            ('script master', master_script, ('load', 'edit_ranges', 'write_template', 'build', 'timeline', 'sidecars'))):
        if not all(callable(getattr(component, name, None)) for name in names):
            raise ValueError(f'Runtime lacks required {label} interfaces')
    if not {'frame_ranges', 'canvas', 'source_hashes', 'sequence'} <= set(inspect.signature(master.build).parameters):
        raise ValueError('Runtime lacks exact script master build interfaces')
    if not {'edits', 'native_canvas', 'preview', 'dry_run'} <= set(inspect.signature(master_script.build).parameters):
        raise ValueError('Runtime lacks exact script editing interfaces')
    for label, arguments, dispatch in (
            ('factory', ['factory', 'build', 'input.json', '--out', 'unused', '--dry-run'], factory.run),
            ('factory', ['factory', 'verify', 'unused'], factory.run),
            ('master', ['master', 'input.gif', '--out', 'unused', '--preview', '--audio', 'audio.wav', '--dry-run'], master.run),
            ('script master', ['master', '--script', 'film.json', '--edits', 'edits.json', '--out', 'unused',
                               '--preview', '--native-canvas', '--dry-run'], master.run),
            ('script master', ['master', '--script', 'film.json', '--write-edits', 'edits.json'], master.run)):
        try:
            with redirect_stderr(io.StringIO()):
                parsed = parser.parse_args(arguments)
        except SystemExit as error:
            raise ValueError(f'Runtime lacks {label} CLI commands') from error
        if getattr(parsed, 'func', None) is not dispatch:
            raise ValueError(f'Runtime lacks correct {label} CLI dispatch')
    if not callable(getattr(sequence_master, 'build', None)) or not callable(getattr(sequence_incremental, 'build', None)):
        raise ValueError('Runtime lacks sequence master or incremental build interfaces')
    if not {'resume', 'reuse_from'} <= set(inspect.signature(sequence.build_sequence).parameters):
        raise ValueError('Runtime lacks sequence revision interfaces')
    for arguments in (['sequence', 'master', 'unused', '--out', 'unused-master'],
                      ['sequence', 'build', 'input.json', '--out', 'unused', '--resume'],
                      ['sequence', 'build', 'input.json', '--out', 'unused', '--reuse-from', 'previous']):
        try:
            with redirect_stderr(io.StringIO()):
                parsed = parser.parse_args(arguments)
        except SystemExit as error:
            raise ValueError('Runtime lacks sequence master/revision CLI commands') from error
        if getattr(parsed, 'func', None) is not sequence.run:
            raise ValueError('Runtime lacks correct sequence CLI dispatch')
    lossless = check_lossless(required=require_master)
    installed_commit = None
    try:
        distribution = metadata.distribution('gif-cinema')
        direct_url = distribution.read_text('direct_url.json')
        imported_file = Path(gif_cinema.__file__).resolve()
        distribution_file = Path(distribution.locate_file('gif_cinema/__init__.py')).resolve()
        if direct_url and imported_file == distribution_file:
            installed_commit = json.loads(direct_url).get('vcs_info', {}).get('commit_id')
    except metadata.PackageNotFoundError:
        pass
    return {'status': 'interfaces-present', 'runtime_version': gif_cinema.__version__,
            'expected_commit': runtime['runtime_commit'], 'installed_commit': installed_commit,
            'pin_matches_metadata': installed_commit == runtime['runtime_commit'],
            'optional_dependencies': {'lossless': lossless},
            'note': 'Interface checks are not behavioral or visual acceptance. Run all five component smokes or smoke_test.py. A local checkout may not expose VCS installation metadata.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--files-only', action='store_true', help='Check extracted resources without importing the runtime')
    parser.add_argument('--require-master', action='store_true',
                        help='Require optional PyAV >=16.1,<17 and usable FFV1 encoder/decoder')
    args = parser.parse_args()
    if args.files_only and args.require_master:
        parser.error('--files-only cannot be combined with --require-master')
    try:
        report = {'package': verify_files()}
        if not args.files_only:
            report['runtime'] = check_runtime(require_master=args.require_master)
        print(json.dumps(report, indent=2))
    except (OSError, ValueError, ImportError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
