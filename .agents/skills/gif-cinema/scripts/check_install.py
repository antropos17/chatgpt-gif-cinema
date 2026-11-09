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


def check_runtime(root=SKILL):
    runtime = json.loads((Path(root) / 'runtime.json').read_text(encoding='utf-8'))
    import gif_cinema
    from gif_cinema import cli, sprites
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
            'note': 'Interface checks are not behavioral or visual acceptance. Run smoke_media.py and smoke_test.py. A local checkout may not expose VCS installation metadata.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--files-only', action='store_true', help='Check extracted resources without importing the runtime')
    args = parser.parse_args()
    try:
        report = {'package': verify_files()}
        if not args.files_only:
            report['runtime'] = check_runtime()
        print(json.dumps(report, indent=2))
    except (OSError, ValueError, ImportError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
