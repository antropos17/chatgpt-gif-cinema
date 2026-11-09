#!/usr/bin/env python3
"""Build the static screening room without dependencies or provider calls."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'dist' / 'website'
FILES = ['index.html', 'site.css', 'site.js',
         'assets/site/favicon.svg', 'assets/site/astronaut-poster.jpg',
         'assets/site/cat-poster.jpg', 'assets/site/dog-poster.jpg',
         'assets/site/cat-preview.mp4', 'assets/site/dog-preview.mp4']
for character in ('astronaut', 'cat', 'dog'):
    FILES += [f'assets/showcase/{character}-{suffix}' for suffix in ('comparison.mp4', 'poster.png', 'frames.png')]
FILES += ['assets/showcase/astronaut-native-film.mp4', 'assets/showcase/cat-film.mp4']
for name in FILES:
    source, target = ROOT / 'docs' / name, DEST / name
    if not source.is_file():
        raise SystemExit(f'Missing site asset: {name}')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
print(f'Built {len(FILES)} files in {DEST}')
