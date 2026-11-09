"""Offline checks for README claims, local links, and original static identity."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parents[1]
DOCS = ('README.md', 'docs/RECIPES.md', 'docs/README-DESIGN.md')


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ('href', 'src', 'srcset') and value:
                self.urls.append(value)


def anchors(text):
    # These documents use plain Markdown headings, matching GitHub's slugs.
    result = set()
    duplicates = {}
    for heading in re.findall(r'^#{1,6}\s+(.+)$', text, re.M):
        slug = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        n = duplicates.get(slug, 0)
        duplicates[slug] = n + 1
        result.add(slug + (f'-{n}' if n else ''))
    return result


class ReadmeTests(unittest.TestCase):
    def test_local_files_and_anchors_exist(self):
        for name in DOCS:
            path = ROOT / name
            source = re.sub(r'```.*?```', '', path.read_text(), flags=re.S)
            parser = Links()
            parser.feed(source)
            urls = parser.urls + re.findall(r'\]\(([^\s)]+)\)', source)
            for url in urls:
                parsed = urlsplit(url)
                if parsed.scheme or parsed.netloc:
                    continue
                target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
                with self.subTest(document=name, url=url):
                    self.assertTrue(target.is_relative_to(ROOT))
                    self.assertTrue(target.is_file(), str(target))
                    if parsed.fragment and target.suffix == '.md':
                        self.assertIn(unquote(parsed.fragment), anchors(target.read_text()))

    def test_manifest_hashes_and_actual_gif_timing(self):
        manifest = json.loads((ROOT / 'docs/assets/identity/manifest.json').read_text())
        self.assertEqual(manifest['schema_version'], 1)
        self.assertEqual(len(manifest['assets']), 8)
        for asset in manifest['assets']:
            path = ROOT / asset['path']
            with self.subTest(path=asset['path']):
                self.assertEqual(path.stat().st_size, asset['bytes'])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), asset['sha256'])
                if path.suffix == '.gif':
                    with Image.open(path) as im:
                        self.assertEqual((im.width, im.height), (asset['width'], asset['height']))
                        self.assertEqual(im.n_frames, asset['frames'])
                        self.assertEqual(im.info.get('loop'), asset['loop'])
                        delays = [frame.info['duration'] for frame in ImageSequence.Iterator(im)]
                        self.assertEqual(delays, asset['frame_durations_ms'])
                        self.assertEqual(sum(delays), asset['duration_ms'])

    def test_identity_is_static_self_contained_and_accessible(self):
        expected = {'cover.svg': ('1200', '610'), 'cover-mobile.svg': ('600', '710'),
                    'story-strip.svg': ('1000', '270')}
        allowed = {'svg', 'title', 'desc', 'defs', 'radialGradient', 'linearGradient',
                   'stop', 'rect', 'g', 'circle', 'ellipse', 'path', 'text'}
        for name, size in expected.items():
            root = ET.parse(ROOT / 'docs/assets/identity' / name).getroot()
            with self.subTest(asset=name):
                self.assertEqual((root.attrib['width'], root.attrib['height']), size)
                self.assertEqual(root.attrib['viewBox'], f'0 0 {size[0]} {size[1]}')
                self.assertEqual(root.attrib['role'], 'img')
                self.assertIsNotNone(root.find('{http://www.w3.org/2000/svg}title'))
                self.assertIsNotNone(root.find('{http://www.w3.org/2000/svg}desc'))
                for node in root.iter():
                    self.assertIn(node.tag.rsplit('}', 1)[-1], allowed)
                    for key, value in node.attrib.items():
                        self.assertFalse(key.lower().startswith('on'))
                        self.assertNotIn('href', key.lower())
                        self.assertNotRegex(value, r'https?://|data:|javascript:')
