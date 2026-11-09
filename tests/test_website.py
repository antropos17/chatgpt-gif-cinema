"""Dependency-free static-site integrity checks; browser QA remains separate."""
from html.parser import HTMLParser
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
class Elements(HTMLParser):
    def __init__(self):
        super().__init__(); self.items = []
    def handle_starttag(self, tag, attrs): self.items.append((tag, dict(attrs)))
class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT/'docs/index.html').read_text(); self.dom = Elements(); self.dom.feed(self.html)
        self.js = (ROOT/'docs/site.js').read_text()
        self.css = (ROOT/'docs/site.css').read_text()
    def test_local_links_and_media_exist(self):
        for _, attrs in self.dom.items:
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
        for text in ('7.68s','57.2s','10.24s','not features included in the public CLI','existing footage'):
            self.assertIn(text,self.html)
        for text in ('5.4-second','®','LIVE PROOF'):
            self.assertNotIn(text,self.html)
    def test_previews_are_named_muted_and_reduced_motion_aware(self):
        previews = [a for t,a in self.dom.items if t=='video' and 'data-loop' in a]
        self.assertEqual(len(previews),3)
        for attrs in previews:
            self.assertIn('aria-label',attrs); self.assertIn('muted',attrs); self.assertIn('playsinline',attrs)
            self.assertNotIn('autoplay',attrs)
        self.assertIn('prefers-reduced-motion',self.js)
        self.assertIn('IntersectionObserver',self.js)
    def test_modal_and_comparison_block_background_previews(self):
        self.assertIn('!dialog.open && comparison.paused',self.js)
        self.assertIn("document.addEventListener('visibilitychange'",self.js)
        self.assertIn("dialog.addEventListener('close'",self.js)
        self.assertIn('lastTrigger?.focus()',self.js)
    def test_platform_commands_do_not_require_security_changes(self):
        self.assertIn('source .venv/bin/activate',self.html)
        self.assertIn('Scripts\\\\python.exe',self.js)
        self.assertNotIn('Set-ExecutionPolicy',self.js)
        self.assertIn('--max-api-calls 0',self.html)
        self.assertEqual(sum('data-platform' in a for _,a in self.dom.items),2)
    def test_no_media_masks_or_decorative_motion(self):
        self.assertIn('object-fit: contain',self.css)
        self.assertNotIn('object-fit: cover',self.css)
        self.assertNotIn('@keyframes',self.css)
        self.assertNotIn('clip-path:',self.css)
        self.assertNotIn('rotate(',self.css)
        self.assertNotIn('class="ticker"',self.html)
    def test_mobile_navigation_is_retained(self):
        self.assertIn('aria-label="Main navigation"',self.html)
        self.assertIn('.site-header nav { order: 3;',self.css)
        self.assertNotIn('.site-header nav{display:none}',self.css)
    def test_comparison_loads_metadata_before_user_playback(self):
        comparison = next(a for _,a in self.dom.items if a.get("id") == "compare-video")
        self.assertEqual(comparison.get("preload"), "metadata")
    def test_starter_contrast_has_margin(self):
        self.assertIn('--muted: #625e57; --accent: #805033;', self.css)
    def test_self_contained_assets_and_comparison_targets(self):
        self.assertNotIn('@import',self.css)
        self.assertNotIn('fonts.googleapis',self.html)
        self.assertEqual({a['data-compare'] for _,a in self.dom.items if 'data-compare' in a},{'cat','dog','astronaut'})
        self.assertEqual({a['data-film'] for _,a in self.dom.items if 'data-film' in a},{'cat','dog','astronaut'})
        for suffix in ('-comparison.mp4','-poster.png','-frames.png'):
            self.assertIn(suffix,self.js)
if __name__=='__main__': unittest.main()
