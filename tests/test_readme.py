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
DOCS = ('README.md', 'docs/RECIPES.md', 'docs/README-DESIGN.md', 'docs/MOTION-DESIGN.md', 'docs/GALLERY.md')


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
    result = set(re.findall(r'id="([a-z0-9-]+)"', text))
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
            source = re.sub(r'```.*?```', '', path.read_text(encoding='utf-8'), flags=re.S)
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
                        self.assertIn(unquote(parsed.fragment), anchors(target.read_text(encoding='utf-8')))

    def test_manifest_hashes_and_actual_gif_timing(self):
        manifest = json.loads((ROOT / 'docs/assets/identity/manifest.json').read_text(encoding='utf-8'))
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

    def test_finishing_previews_are_visible_before_setup(self):
        source = (ROOT / 'README.md').read_text(encoding='utf-8')
        # GitHub renders the source in order. Gallery media should not depend on
        # opening a disclosure or scrolling through the installation instructions.
        visible = re.sub(r'<details\b.*?</details>', '', source, flags=re.S)
        setup = visible.index('## Make your first film')
        for subject in ('cat', 'dog', 'astronaut'):
            path = f'docs/assets/showcase/{subject}-preview.gif'
            with self.subTest(subject=subject):
                embedded = re.findall(r'<img\b[^>]*src="([^"]+)"', visible)
                self.assertEqual(embedded.count(path), 2 if subject == 'cat' else 1)
                self.assertNotIn(f']({path})](', source)
                self.assertLess(visible.index(path), setup)
                self.assertIn('docs/SHOWCASE.md', visible)
        self.assertIn('not included in the\npublic CLI', visible)
        self.assertIn('2.24-second excerpt', visible)
        self.assertTrue({'see-it-in-motion', 'try-it-without-an-api-key',
                         'give-the-skill-to-your-agent'} <= anchors(source))

    def test_visible_previews_preserve_existing_media(self):
        base = ROOT / 'docs/assets/showcase'
        manifest = json.loads((base / 'asset-manifest.json').read_text(encoding='utf-8'))
        assets = {asset['file']: asset for asset in manifest['assets']}
        for subject in ('cat', 'dog', 'astronaut'):
            name = f'{subject}-preview.gif'
            asset = assets[name]
            path = base / name
            with self.subTest(asset=name):
                self.assertEqual(path.stat().st_size, asset['bytes'])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), asset['sha256'])
                with Image.open(path) as im:
                    delays = [frame.info['duration'] for frame in ImageSequence.Iterator(im)]
                    self.assertEqual(sum(delays), 2240)
                    self.assertEqual(im.info.get('loop'), 0)

    def test_identity_typography_is_outlined_and_documented(self):
        base = ROOT / 'docs/assets/identity'
        for name in ('cover.svg', 'cover-mobile.svg', 'story-strip.svg'):
            source = (base / name).read_text(encoding='utf-8')
            with self.subTest(asset=name):
                self.assertNotIn('<text', source)
                self.assertNotIn('font-family', source)
                self.assertIn('<path', source)
                self.assertIn('#f1ece4', source)
                self.assertIn('#282722', source)
        self.assertIn('Apache License', (base / 'FONT-LICENSE.txt').read_text(encoding='utf-8'))
        manifest = json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
        self.assertTrue(manifest['typography']['outlined'])
        self.assertEqual(manifest['typography']['family'], 'Open Sans')

    def test_catalog_puts_real_motion_before_explanation(self):
        source = (ROOT / 'README.md').read_text(encoding='utf-8')
        visible = re.sub(r'<details\b.*?</details>', '', source, flags=re.S)
        first_image = visible.index('<img ')
        self.assertLess(first_image, visible.index('## Character stories'))
        self.assertLess(len(visible[:first_image].split()), 80)
        self.assertNotIn('assets/identity/cover', visible)
        urls = re.findall(r'<img\b[^>]*src="([^"]+)"', visible)
        self.assertGreaterEqual(len(urls), 12)
        self.assertGreaterEqual(len({u for u in urls if u.endswith('.gif')}), 8)
        self.assertGreaterEqual(visible.count('<table>'), 5)
        self.assertNotIn('width="33%"', visible)
        self.assertIn('docs/SPRITES.md', visible)
        self.assertIn('docs/GIF-REVIEW.md', visible)

    def test_catalog_local_outputs_match_their_sources_and_facts(self):
        def git_blob(data):
            return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        manifest = json.loads((ROOT / 'docs/assets/catalog/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['new_provider_calls'], 0)
        for asset in manifest['assets']:
            path = ROOT / 'docs/assets/catalog' / asset['file']
            with self.subTest(asset=asset['file']):
                self.assertEqual(git_blob(path.read_bytes()), asset['git_blob_sha1'])
                # Git identities use repository LF text, independent of Windows checkout CRLF.
                source_text = (ROOT / asset['source']).read_text(encoding='utf-8').encode('utf-8')
                self.assertEqual(git_blob(source_text), asset['source_git_blob_sha1'])
                self.assertEqual(path.stat().st_size, asset['bytes'])
                self.assertEqual(asset['api_calls'], 0)
                with Image.open(path) as im:
                    self.assertEqual(im.size, (asset['width'], asset['height']))
                    self.assertEqual(im.n_frames, asset['frames'])
                    self.assertEqual(im.info.get('loop'), asset['loop'])
                    self.assertEqual(sum(f.info['duration'] for f in ImageSequence.Iterator(im)), asset['duration_ms'])

    def test_cover_text_colors_have_readable_contrast(self):
        def luminance(color):
            values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
                      for v in values]
            return sum(v * w for v, w in zip(linear, (.2126, .7152, .0722)))
        paper = luminance('#f1ece4')
        for color in ('#282722', '#68645d', '#8a583b'):
            with self.subTest(color=color):
                self.assertGreaterEqual((paper + .05) / (luminance(color) + .05), 4.5)

    def test_identity_is_static_self_contained_and_accessible(self):
        expected = {'cover.svg': ('1200', '354'), 'cover-mobile.svg': ('600', '342'),
                    'story-strip.svg': ('1000', '210')}
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
