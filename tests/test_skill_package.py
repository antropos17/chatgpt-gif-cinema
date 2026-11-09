"""Exercise the resource ZIP as installed, including review and sprite entry points."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / '.agents/skills/gif-cinema'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


packaging = module('package_current_skill', ROOT / 'tools/package_skill.py')
check = module('check_skill_install', SKILL / 'scripts/check_install.py')


class SkillPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skill package ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def unpack(self):
        archive = self.root / 'skill.zip'
        packaging.package(archive)
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(self.root / 'installed')
        return self.root / 'installed/gif-cinema'

    def command(self, installed, script, *args, runtime=True, success=True, allow_bytecode=False):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        env.pop('OPENAI_API_KEY', None)
        if allow_bytecode:
            env.pop('PYTHONDONTWRITEBYTECODE', None)
        # Only the runtime uses the checkout. Helpers/assets must come from the ZIP.
        env['PYTHONPATH'] = str(ROOT) if runtime else ''
        result = subprocess.run([sys.executable, str(installed / 'scripts' / script), *args],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_reproducible_stored_archive_and_complete_hash_manifest(self):
        one, two = self.root / 'one.zip', self.root / 'two.zip'
        count = packaging.package(one)
        with patch('time.time', return_value=0):
            packaging.package(two)
        self.assertEqual(one.read_bytes(), two.read_bytes())
        with zipfile.ZipFile(one) as archive:
            self.assertEqual(len(archive.namelist()), count)
            self.assertEqual(archive.namelist(), sorted(archive.namelist()))
            manifest = json.loads(archive.read('gif-cinema/package-manifest.json'))
            self.assertEqual(manifest['skill_version'], '0.2.0')
            self.assertIs(manifest['runtime_bundled'], False)
            self.assertEqual(set(manifest['files']), set(packaging.FILES))
            self.assertEqual(len(manifest['files']) + 1, count)
            for info in archive.infolist():
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(info.date_time, (2026, 1, 1, 0, 0, 0))
                self.assertEqual(info.create_system, 3)
                self.assertEqual(info.external_attr, 0o100644 << 16)
                name = info.filename.removeprefix('gif-cinema/')
                if name in manifest['files']:
                    data = archive.read(info)
                    self.assertEqual(manifest['files'][name],
                                     {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            for required in ('scripts/review_gif.py', 'scripts/check_install.py', 'scripts/smoke_media.py',
                             'references/full-frame-review.md', 'references/sprites.md', 'runtime.json'):
                self.assertIn('gif-cinema/' + required, archive.namelist())

    def test_existing_archive_is_preserved(self):
        out = self.root / 'keep.zip'
        out.write_bytes(b'accepted')
        with self.assertRaises(ValueError):
            packaging.package(out)
        self.assertEqual(out.read_bytes(), b'accepted')

    def test_missing_resource_rejected_before_output(self):
        with patch.object(packaging, 'FILES', (*packaging.FILES, 'missing.txt')):
            with self.assertRaisesRegex(ValueError, 'Missing'):
                packaging.package(self.root / 'missing.zip')
        self.assertFalse((self.root / 'missing.zip').exists())

    @unittest.skipIf(os.name == 'nt', 'Symlink creation requires Windows developer mode')
    def test_symlinked_resource_directory_is_rejected(self):
        copied = self.root / 'copy'
        shutil.copytree(SKILL, copied)
        (copied / 'references').rename(copied / 'real-references')
        (copied / 'references').symlink_to('real-references', target_is_directory=True)
        with patch.object(packaging, 'SKILL', copied):
            with self.assertRaisesRegex(ValueError, 'Symlinked'):
                packaging.package(self.root / 'linked.zip')
        self.assertFalse((self.root / 'linked.zip').exists())

    def test_extracted_file_check_requires_no_runtime(self):
        installed = self.unpack()
        result = self.command(installed, 'check_install.py', '--files-only', runtime=False)
        report = json.loads(result.stdout)
        self.assertEqual(report['package']['status'], 'passed')
        self.assertEqual(report['package']['resource_count'], len(packaging.FILES))

    def test_resource_tampering_is_detected(self):
        installed = self.unpack()
        (installed / 'references/sprites.md').write_text('changed')
        result = self.command(installed, 'check_install.py', '--files-only', runtime=False, success=False)
        self.assertIn('resource changed', result.stderr)

    def test_manifest_path_traversal_is_rejected(self):
        installed = self.unpack()
        path = installed / 'package-manifest.json'
        data = json.loads(path.read_text())
        data['files']['../outside'] = {'bytes': 0, 'sha256': hashlib.sha256(b'').hexdigest()}
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'inventory|Unsafe'):
            check.verify_files(installed)

    def test_empty_or_incomplete_resource_inventory_is_rejected(self):
        installed = self.unpack()
        path = installed / 'package-manifest.json'
        data = json.loads(path.read_text())
        for names in ({}, {k: v for k, v in data['files'].items() if k != 'scripts/story_project.py'}):
            with self.subTest(resource_count=len(names)):
                path.write_text(json.dumps({**data, 'files': names}))
                with self.assertRaisesRegex(ValueError, 'inventory'):
                    check.verify_files(installed)
        (installed / 'scripts/story_project.py').unlink()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            check.verify_files(installed)

    def test_checker_inventory_matches_builder(self):
        self.assertEqual(check.RESOURCE_FILES, frozenset(packaging.FILES))

    def test_manifest_version_mismatch_is_rejected(self):
        installed = self.unpack()
        path = installed / 'package-manifest.json'
        data = json.loads(path.read_text())
        data['runtime_commit'] = '0' * 40
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            check.verify_files(installed)

    def test_source_checkout_does_not_claim_hash_verification(self):
        self.assertEqual(check.verify_files(SKILL)['status'], 'not-present')

    def test_local_markdown_links_resolve_inside_zip(self):
        installed = self.unpack()
        for markdown in installed.rglob('*.md'):
            for target in re.findall(r'\]\(([^)]+)\)', markdown.read_text(encoding='utf-8')):
                if target.startswith(('https://', 'http://', '#')):
                    continue
                self.assertTrue((markdown.parent / target.split('#')[0]).is_file(), (markdown, target))

    def test_runtime_pin_is_immutable_and_matches_install_instructions(self):
        info = json.loads((SKILL / 'runtime.json').read_text())
        self.assertRegex(info['runtime_commit'], r'^[0-9a-f]{40}$')
        self.assertIs(info['runtime_bundled'], False)
        self.assertIn(f"git+{info['runtime_repository']}@{info['runtime_commit']}",
                      (SKILL / 'SKILL.md').read_text())
        for name in ('generation.md', 'sprites.md'):
            self.assertIn(info['runtime_commit'], (SKILL / 'references' / name).read_text())

    def test_extracted_media_smoke_uses_pack_slice_and_pending_reviews(self):
        installed = self.unpack()
        out = self.root / 'media smoke'
        result = self.command(installed, 'smoke_media.py', '--out', str(out))
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['provider_calls'], 0)
        self.assertEqual(report['installation']['package']['status'], 'passed')
        self.assertEqual(report['visual_review'], 'pending')
        self.assertEqual(report['user_acceptance'], 'pending')
        self.assertFalse(report['ffmpeg_required'])
        self.command(installed, 'smoke_media.py', '--out', str(out), success=False)
        self.assertEqual(json.loads((out / 'verification.json').read_text()), report)

    def test_smoke_refuses_writing_inside_installed_skill(self):
        installed = self.unpack()
        out = installed / 'bad-output'
        result = self.command(installed, 'smoke_media.py', '--out', str(out), success=False)
        self.assertIn('outside the installed skill', result.stderr)
        self.assertFalse(out.exists())

    def test_smoke_does_not_write_bytecode_inside_installed_skill(self):
        installed = self.unpack()
        self.command(installed, 'smoke_media.py', '--out', str(installed / 'bad-output'),
                     success=False, allow_bytecode=True)
        self.assertEqual(list(installed.rglob('__pycache__')), [])
        self.command(installed, 'smoke_media.py', '--out', str(self.root / 'bytecode smoke'),
                     allow_bytecode=True)
        self.assertEqual(list(installed.rglob('__pycache__')), [])

    def test_extracted_review_cli_leaves_real_sample_pending(self):
        installed = self.unpack()
        out = self.root / 'sample review'
        source = installed / 'assets/example/shot-01.gif'
        result = self.command(installed, 'review_gif.py', 'extract', str(source), str(out))
        report = json.loads(result.stdout)
        self.assertEqual(report['frame_count'], 16)
        self.assertEqual(report['duration_ms'], 2560)
        self.assertEqual(source.read_bytes(), (out / 'animation.gif').read_bytes())
        result = self.command(installed, 'review_gif.py', 'check', str(out), '--gif', str(source), success=False)
        self.assertIn('named reviewer', result.stderr)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_extracted_full_smoke_includes_media_and_zero_call_resume(self):
        installed = self.unpack()
        out = self.root / 'full smoke'
        self.command(installed, 'smoke_test.py', '--out', str(out))
        report = json.loads((out / 'verification.json').read_text())
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['provider_calls'], 0)
        self.assertTrue(report['render_and_resume_checked'])
        self.assertTrue(report['packaged_review_and_sprites_checked'])
        self.assertEqual(json.loads((out / 'media/verification.json').read_text())['visual_review'], 'pending')


if __name__ == '__main__':
    unittest.main()
