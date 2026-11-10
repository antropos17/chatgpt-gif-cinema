"""Build a reproducible resource ZIP; the separately pinned Python runtime is not bundled."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.agents/skills/gif-cinema'
FILES = (
    'assets/example/motion-loop.json',
    'references/motion.md',
    'scripts/smoke_motion.py',
    'assets/example/gif-layer.json',
    'scripts/verify_layers.py',
    'scripts/smoke_layers.py',
    'references/layers.md',
    'assets/example/stroke-reveal.json',
    'assets/example/layered-shapes.json',
    'SKILL.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'agents/openai.yaml', 'runtime.json',
    'scripts/check_install.py', 'scripts/smoke_test.py', 'scripts/smoke_media.py',
    'scripts/review_gif.py', 'scripts/story_project.py', 'scripts/story_chapters.py', 'scripts/story_pages.py',
    'references/generation.md', 'references/review.md', 'references/full-frame-review.md',
    'references/sprites.md', 'references/storytelling.md', 'references/story-project.md', 'references/story-pages.md',
    'assets/example/film.json', 'assets/example/storyboard.json', 'assets/example/storybook.json',
    'assets/example/storyboard.pending.json', 'assets/example/takes.example.json',
    'assets/example/long-story.plan.json', 'assets/example/shot-01.gif',
    'assets/example/shot-02.gif', 'assets/example/shot-03.gif',
)


def package(target):
    target = Path(target).absolute()
    if target.exists() or target.is_symlink():
        raise ValueError('Package target already exists')
    files = {}
    for name in sorted(FILES):
        path = SKILL / name
        if SKILL.is_symlink() or any((SKILL / Path(*Path(name).parts[:i])).is_symlink()
                                    for i in range(1, len(Path(name).parts) + 1)):
            raise ValueError(f'Symlinked package input: {name}')
        if not path.is_file():
            raise ValueError(f'Missing or nonregular package input: {name}')
        if not path.resolve().is_relative_to(SKILL.resolve()):
            raise ValueError('Package input escapes the maintained skill folder')
        files[name] = path.read_bytes()
    runtime = json.loads(files['runtime.json'])
    if (runtime.get('schema_version') != 1 or
            not re.fullmatch(r'[0-9a-f]{40}', runtime.get('runtime_commit', ''))):
        raise ValueError('runtime.json needs an immutable runtime commit')
    manifest = {'schema_version': 1, 'skill_version': runtime['skill_version'],
                'runtime_commit': runtime['runtime_commit'], 'runtime_bundled': False,
                'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in files.items()},
                'notice': 'Hashes detect changed files, not publisher identity or visual acceptance.'}
    files['package-manifest.json'] = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode('utf-8')
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(f'gif-cinema/{name}', (2026, 1, 1, 0, 0, 0))
            # Stored entries avoid platform/zlib-version-dependent compression output.
            entry.compress_type = zipfile.ZIP_STORED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError('Package ZIP failed integrity check')
    return len(files)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(f'Packaged {package(args.out)} files into {args.out}')
