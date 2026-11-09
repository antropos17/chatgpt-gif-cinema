"""Dependency-free static-site integrity checks; browser QA remains separate."""
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]
class Elements(HTMLParser):
    def __init__(self):
        super().__init__(); self.items = []
    def handle_starttag(self, tag, attrs): self.items.append((tag, dict(attrs)))
class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT/'docs/index.html').read_text(); self.dom = Elements(); self.dom.feed(self.html)
    def test_local_links_and_media_exist(self):
        for tag, attrs in self.dom.items:
            for key in ('src','poster','href'):
                value=attrs.get(key,'')
                if value and not value.startswith(('http:','https:','#','data:')):
                    self.assertTrue((ROOT/'docs'/value).is_file(), value)
    def test_anchor_targets_exist(self):
        ids = {attrs['id'] for _,attrs in self.dom.items if 'id' in attrs}
        self.assertEqual(len(ids),sum('id' in attrs for _,attrs in self.dom.items))
        for _,attrs in self.dom.items:
            link=attrs.get('href','')
            if link.startswith('#') and len(link)>1: self.assertIn(link[1:],ids)
    def test_media_and_disclosures_are_accurate(self):
        self.assertIn('7.68 SEC',self.html); self.assertIn('57.2 SEC',self.html)
        self.assertIn('not features included in the public CLI',self.html)
        self.assertIn('existing project films',self.html)
        self.assertNotIn('5.4-second',self.html)
        self.assertNotIn('®',self.html)
    def test_controls_have_names_and_safe_defaults(self):
        for tag,attrs in self.dom.items:
            if tag=='video' and 'data-loop' in attrs:
                self.assertIn('aria-label',attrs); self.assertIn('muted',attrs); self.assertIn('playsinline',attrs)
        js=(ROOT/'docs/site.js').read_text()
        self.assertIn('prefers-reduced-motion',js); self.assertIn('IntersectionObserver',js)
        self.assertIn("dialog.addEventListener('close'",js)
        self.assertIn('lastTrigger?.focus()',js)
    def test_palette_and_links_are_self_contained(self):
        css=(ROOT/'docs/site.css').read_text()
        self.assertNotIn('@import',css)
        self.assertNotIn('fonts.googleapis',self.html)
        self.assertNotRegex(css,r'#[0-9a-fA-F]{3,8}.*green')
if __name__=='__main__': unittest.main()
