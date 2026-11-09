"""Keep the documented first request offline and its local links usable."""
import contextlib
import io
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from gif_cinema import cli, render

ROOT = Path(__file__).resolve().parents[1]


class OnboardingTests(unittest.TestCase):
    def test_document_links_exist(self):
        for name in ('docs/GETTING-STARTED.md', 'docs/PRODUCTION.md'):
            path = ROOT / name
            source = re.sub(r'```.*?```', '', path.read_text(encoding='utf-8'), flags=re.S)
            for url in re.findall(r'\]\(([^\s)]+)\)', source):
                parts = urlsplit(url)
                if parts.scheme or parts.netloc:
                    continue
                target = (path.parent / unquote(parts.path)).resolve() if parts.path else path
                with self.subTest(document=name, url=url):
                    self.assertTrue(target.is_relative_to(ROOT))
                    self.assertTrue(target.is_file(), str(target))
                    if parts.fragment and target.suffix == '.md':
                        headings = re.findall(r'^#{1,6}\s+(.+)$', target.read_text(encoding='utf-8'), re.M)
                        anchors = {re.sub(r'[^\w\- ]', '', h.lower()).replace(' ', '-') for h in headings}
                        anchors.update(re.findall(r'id="([a-z0-9-]+)"', target.read_text(encoding='utf-8')))
                        self.assertIn(unquote(parts.fragment), anchors)

    def test_first_shot_plans_one_request_without_spending_or_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'new-project'
            args = cli.build_parser().parse_args(['render', str(ROOT / 'examples/first-shot.json'),
                '--dry-run', '--max-api-calls', '0', '--retries', '0', '--out', str(out)])
            with patch.dict('os.environ', {}, clear=True), \
                    patch('gif_cinema.cli.request_gif') as request, \
                    patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Network forbidden')), \
                    contextlib.redirect_stdout(io.StringIO()):
                plan = render.run(args)
            request.assert_not_called()
            self.assertFalse(out.exists())
            self.assertEqual(plan['minimum_new_api_calls'], 1)
            self.assertEqual(plan['shots'][0]['action'], 'generate')
            self.assertEqual(plan['shots'][0]['expected_duration_ms'], 2560)

    def test_first_shot_explicit_model_beats_environment_default(self):
        path = ROOT / 'examples/first-shot.json'
        args = cli.build_parser().parse_args(['render', str(path), '--dry-run'])
        with patch.dict('os.environ', {'GIF_CINEMA_MODEL': 'gpt-image-2.6-sunburst'}, clear=True):
            data = render.load_script(path, args)
        self.assertEqual(data['shots'][0]['payload']['model'], 'gpt-image-2.6-flare')
