"""Build a deterministic, self-contained GIF Cinema skill ZIP from its reviewed resource allowlist."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.agents/skills/gif-cinema'


def package(target):
    target = Path(target).resolve()
    if target.exists():
        raise ValueError('Package target already exists')
    names = [
        'SKILL.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'agents/openai.yaml',
        'scripts/smoke_test.py', 'scripts/story_project.py', 'scripts/story_chapters.py', 'scripts/story_pages.py',
        'references/generation.md', 'references/review.md',
        'references/storytelling.md', 'references/story-project.md', 'references/story-pages.md',
        'assets/example/film.json', 'assets/example/storyboard.json', 'assets/example/storybook.json',
        'assets/example/storyboard.pending.json', 'assets/example/takes.example.json',
        'assets/example/long-story.plan.json', 'assets/example/shot-01.gif',
        'assets/example/shot-02.gif', 'assets/example/shot-03.gif',
    ]
    files = []
    for name in sorted(names):
        path = SKILL / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing or symlinked package input: {name}')
        if not path.resolve().is_relative_to(SKILL.resolve()):
            raise ValueError('Package input escapes the maintained skill folder')
        files.append((path, f'gif-cinema/{name}'))
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path, name in files:
            entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, path.read_bytes())
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError('Package ZIP failed integrity check')
    return len(files)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(f'Packaged {package(args.out)} files into {args.out}')
