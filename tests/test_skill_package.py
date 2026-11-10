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
        self.root = Path(self.temp.name).resolve()

    def unpack(self):
        archive = self.root / 'skill.zip'
        packaging.package(archive)
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(self.root / 'installed')
        return self.root / 'installed/gif-cinema'

    def command(self, installed, script, *args, runtime=True, success=True, allow_bytecode=False, env_updates=None):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        env.pop('OPENAI_API_KEY', None)
        if allow_bytecode:
            env.pop('PYTHONDONTWRITEBYTECODE', None)
        env.update(env_updates or {})
        # Only the runtime uses the checkout. Helpers/assets must come from the ZIP.
        env['PYTHONPATH'] = str(ROOT) if runtime else ''
        result = subprocess.run([sys.executable, str(installed / 'scripts' / script), *args],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=300)
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
            self.assertEqual(manifest['skill_version'], '0.3.1')
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
                             'references/full-frame-review.md', 'references/sprites.md', 'runtime.json',
                             'scripts/verify_layers.py', 'scripts/smoke_layers.py',
                             'references/layers.md', 'assets/example/stroke-reveal.json'):
                self.assertIn('gif-cinema/' + required, archive.namelist())

    def test_published_metadata_matches_skill_version_and_license(self):
        installed = self.unpack()
        frontmatter = (installed / 'SKILL.md').read_text().split('---', 2)[1]
        # Our maintained metadata uses JSON flow syntax, which is valid YAML.
        # Parse it without adding a runtime/build dependency on a YAML package.
        metadata = json.loads(re.search(r'(?m)^metadata: (.+)$', frontmatter).group(1))
        runtime = json.loads((installed / 'runtime.json').read_text())
        manifest = json.loads((installed / 'package-manifest.json').read_text())
        self.assertEqual(metadata['version'], runtime['skill_version'])
        self.assertEqual(metadata['version'], manifest['skill_version'])
        self.assertRegex(metadata['version'], r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
        license_reference = json.loads(re.search(r'(?m)^license: (.+)$', frontmatter).group(1))
        self.assertEqual(license_reference,
                         'GIF Cinema Source-Available Evaluation License v1.0 (see LICENSE)')
        self.assertEqual((installed / 'LICENSE').read_bytes(), (ROOT / 'LICENSE').read_bytes())

    @unittest.skipUnless(shutil.which('git'), 'Git required for checkout conversion regression')
    def test_autocrlf_checkout_builds_byte_identical_resource_zip(self):
        repository = self.root / 'checkout-source'
        repository.mkdir()
        relative = Path('.agents/skills/gif-cinema')
        shutil.copytree(SKILL, repository / relative, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(ROOT / '.gitattributes', repository / '.gitattributes')
        def git(*parts):
            return subprocess.run(['git', *parts], cwd=repository, check=True,
                                  capture_output=True, timeout=30)
        git('init', '-q')
        git('config', 'core.autocrlf', 'true')
        git('add', '.gitattributes', str(relative))
        checked = self.root / 'autocrlf-worktree'
        checked.mkdir()
        git('checkout-index', '--all', '--force', '--prefix=' + checked.as_posix() + '/')
        first, second = self.root / 'native.zip', self.root / 'autocrlf.zip'
        packaging.package(first)
        with patch.object(packaging, 'SKILL', checked / relative):
            packaging.package(second)
        self.assertEqual(first.read_bytes(), second.read_bytes())

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

    def test_packaged_verifier_matches_repository_logic(self):
        source = (ROOT / 'tools/verify_layered_scene.py').read_text()
        expected = source.replace(
            'ROOT = Path(__file__).resolve().parents[1]\nsys.path.insert(0, str(ROOT))',
            '# The runtime is installed separately; never write bytecode into the skill.\n'
            'sys.dont_write_bytecode = True')
        self.assertEqual((SKILL / 'scripts/verify_layers.py').read_text(), expected)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_packaged_verifier_checks_sprite_inventory_with_newer_runtime(self):
        from PIL import Image
        from gif_cinema import layers
        installed = self.unpack()
        atlas = self.root / 'atlas.png'
        Image.new('RGBA', (16, 8), (255, 0, 0, 128)).save(atlas)
        scene = self.root / 'scene.json'
        scene.write_text(json.dumps({'format': layers.FORMAT, 'schema_version': 1,
            'width': 16, 'height': 16, 'fps': 25, 'duration_ms': 80,
            'layers': [{'id': 'actor', 'type': 'sprites', 'source': atlas.name,
                'size': [8, 8], 'frames': [{'rect': [0, 0, 8, 8], 'duration_ms': 40},
                                         {'rect': [8, 0, 8, 8], 'duration_ms': 40}]}]}), encoding='utf-8')
        out = self.root / 'sprite-render'
        receipt = layers.render_scene(scene, out)
        result = self.command(installed, 'verify_layers.py', str(out))
        self.assertEqual(json.loads(result.stdout)['frames_reopened_and_matched'], 2)
        asset = next(name for name in receipt['outputs'] if name.startswith('editable/assets/'))
        receipt['outputs'].pop(asset)
        (out / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        result = self.command(installed, 'verify_layers.py', str(out), success=False)
        self.assertIn('inventory is incomplete', result.stderr)
        self.assertIn(asset, result.stderr)

    def test_bundled_layer_examples_match_original_sources(self):
        for name in ('stroke-reveal.json', 'layered-shapes.json'):
            self.assertEqual(json.loads((SKILL / 'assets/example' / name).read_text()),
                             json.loads((ROOT / 'examples' / name).read_text()))

    def test_install_check_rejects_runtime_without_strokes(self):
        from gif_cinema import layers
        with patch.object(layers, 'normalize_scene', side_effect=ValueError('unsupported type')):
            with self.assertRaisesRegex(ValueError, 'stroke layer support'):
                check.check_runtime()

    def test_install_check_rejects_runtime_without_gif_layers(self):
        from gif_cinema import layers
        original = layers.normalize_scene
        def reject_gif(scene):
            if any(layer['type'] == 'gif' for layer in scene['layers']):
                raise ValueError('unsupported type')
            return original(scene)
        with patch.object(layers, 'normalize_scene', side_effect=reject_gif):
            with self.assertRaisesRegex(ValueError, 'animated GIF layers'):
                check.check_runtime()

    def test_bundled_gif_example_reuses_existing_hash_pinned_source(self):
        original = json.loads((ROOT / 'examples/gif-layer/scene.json').read_text())
        for layer in original['layers']:
            if layer['type'] == 'gif':
                layer['source'] = 'shot-01.gif'
                self.assertEqual(layer['sha256'], hashlib.sha256(
                    (SKILL / 'assets/example/shot-01.gif').read_bytes()).hexdigest())
        self.assertEqual(original, json.loads((SKILL / 'assets/example/gif-layer.json').read_text()))

    def test_install_check_rejects_runtime_without_motion_cli(self):
        from gif_cinema import motion
        with patch.object(motion, 'add_parser', return_value=None):
            with self.assertRaisesRegex(ValueError, 'motion CLI commands'):
                check.check_runtime()

    def test_install_check_rejects_runtime_without_motion_interfaces(self):
        from gif_cinema import motion
        with patch.object(motion, 'render_frame', None):
            with self.assertRaisesRegex(ValueError, 'whole-image motion interfaces'):
                check.check_runtime()

    def test_motion_example_is_bounded_installed_variant(self):
        from gif_cinema import motion
        original = json.loads((ROOT / 'examples/motion-loop.json').read_text())
        original.update(width=256, height=256, fit='contain')
        example = SKILL / 'assets/example/motion-loop.json'
        self.assertEqual(original, json.loads(example.read_text()))
        output = self.root / 'motion-plan'
        plan = motion.motion(SKILL / 'assets/example/shot-01.gif', output,
                             recipe=motion.load_recipe(example), dry_run=True)
        self.assertEqual(plan['timeline']['playback_frames'], 120)
        self.assertEqual(plan['timeline']['output_duration_ms'], 4800)
        self.assertEqual(plan['omitted_source_drawings'], [])
        self.assertFalse(output.exists())

    def test_motion_smoke_refuses_installation_output_without_bytecode(self):
        installed = self.unpack()
        result = self.command(installed, 'smoke_motion.py', '--out', str(installed / 'bad-output'),
                              success=False, allow_bytecode=True)
        self.assertIn('outside the installed skill', result.stderr)
        self.assertFalse((installed / 'bad-output').exists())
        self.assertEqual(list(installed.rglob('__pycache__')), [])

    def test_motion_smoke_exercises_public_cli_dispatch(self):
        from gif_cinema import motion
        with patch.object(sys, 'path', [str(SKILL / 'scripts'), *sys.path]):
            smoke = module('motion_dispatch_smoke', SKILL / 'scripts/smoke_motion.py')
        with patch.object(motion, 'run', side_effect=RuntimeError('injected broken dispatcher')) as dispatch:
            with self.assertRaises(SystemExit):
                smoke.motion_cli('unused.gif', '--out', self.root / 'unused', '--preset', 'push-in', '--dry-run')
        dispatch.assert_called_once()
        self.assertFalse((self.root / 'unused').exists())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_extracted_motion_smoke_checks_all_frames_and_leaves_review_pending(self):
        from PIL import Image
        installed = self.unpack()
        out = self.root / 'motion smoke'
        source = installed / 'assets/example/shot-01.gif'
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        result = self.command(installed, 'smoke_motion.py', '--out', str(out), allow_bytecode=True)
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['provider_calls'], 0)
        self.assertEqual(report['frames_reopened_and_matched'], 234)
        self.assertEqual(report['output_hashes_verified'], 21)
        self.assertTrue(report['cli_entrypoint_checked'])
        self.assertEqual(set(report['presets']), {'identity', 'push-in', 'pan-left', 'pop-in'})
        self.assertEqual(report['cases']['returning-camera']['duration_ms'], 4800)
        self.assertEqual(report['visual_review'], 'pending')
        self.assertEqual(report['user_acceptance'], 'pending')
        self.assertEqual(report['installation']['package']['status'], 'passed')
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
        self.assertEqual(list(installed.rglob('__pycache__')), [])
        self.command(installed, 'smoke_motion.py', '--out', str(out), success=False)
        self.assertEqual(json.loads((out / 'verification.json').read_text()), report)
        self.command(installed, 'review_gif.py', 'check', str(out / 'review-gif-push-in'),
                     '--gif', str(out / 'gif-push-in/take.gif'), success=False)
        with patch.object(sys, 'path', [str(installed / 'scripts'), *sys.path]):
            smoke = module('extracted_motion_smoke', installed / 'scripts/smoke_motion.py')
        candidate = out / 'gif-push-in'
        receipt_path = candidate / 'receipt.json'
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(smoke.check_export(candidate, source, receipt, 64, 2560)
                         ['frames_reopened_and_matched'], 64)
        broken = {**receipt, 'outputs': {}}
        receipt_path.write_text(json.dumps(broken))
        with self.assertRaisesRegex(ValueError, 'inventory'):
            smoke.check_export(candidate, source, broken, 64, 2560)
        receipt_path.write_text(json.dumps(receipt))
        missing = candidate / 'frames/0001.png'
        missing_bytes = missing.read_bytes()
        missing.unlink()
        with self.assertRaisesRegex(ValueError, 'Actual motion files'):
            smoke.check_export(candidate, source, receipt, 64, 2560)
        missing.write_bytes(missing_bytes)
        # Matching edited hashes cannot conceal different frame pixels.
        altered = Image.new('RGBA', (512, 512), 'red')
        altered.save(missing)
        receipt['samples'][1]['png_sha256'] = hashlib.sha256(missing.read_bytes()).hexdigest()
        receipt['samples'][1]['rgba_sha256'] = hashlib.sha256(altered.tobytes()).hexdigest()
        receipt_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'frame pixels differ'):
            smoke.check_export(candidate, source, receipt, 64, 2560)

    def test_layer_smoke_refuses_installation_output_without_bytecode(self):
        installed = self.unpack()
        result = self.command(installed, 'smoke_layers.py', '--out', str(installed / 'bad-output'),
                              success=False, allow_bytecode=True)
        self.assertIn('outside the installed skill', result.stderr)
        self.assertFalse((installed / 'bad-output').exists())
        self.assertEqual(list(installed.rglob('__pycache__')), [])

    def test_missing_encoders_fail_before_creating_smoke_output(self):
        installed = self.unpack()
        no_encoders = {'PATH': str(self.root / 'no-tools')}
        for script in ('smoke_layers.py', 'smoke_motion.py', 'smoke_test.py'):
            with self.subTest(script=script):
                out = self.root / script
                result = self.command(installed, script, '--out', str(out),
                                      env_updates=no_encoders, success=False)
                self.assertIn('FFmpeg and ffprobe are required', result.stderr)
                self.assertIn('smoke_media.py', result.stderr)
                self.assertFalse(out.exists())
        self.command(installed, 'smoke_media.py', '--out', str(self.root / 'no-encoder media'),
                     env_updates=no_encoders)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_extracted_layer_smoke_and_cli_verify_actual_stroke_export(self):
        installed = self.unpack()
        out = self.root / 'layer smoke'
        result = self.command(installed, 'smoke_layers.py', '--out', str(out), allow_bytecode=True)
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['provider_calls'], 0)
        self.assertEqual(report['frames_reopened_and_matched'], 200)
        self.assertEqual(report['output_hashes_verified'], 214)
        self.assertTrue(report['gif_layers_checked'])
        self.assertEqual(report['gif_timing']['source_drawings'], 16)
        self.assertEqual(report['cases']['gif-composition']['frames_reopened_and_matched'], 160)
        self.assertEqual(report['visual_review'], 'pending')
        self.assertEqual(report['user_acceptance'], 'pending')
        checked = self.command(installed, 'verify_layers.py', str(out / 'strokes'), allow_bytecode=True)
        self.assertEqual(json.loads(checked.stdout)['status'], 'verified')
        self.assertEqual(list(installed.rglob('__pycache__')), [])
        self.command(installed, 'smoke_layers.py', '--out', str(out), success=False)
        receipt = out / 'strokes/receipt.json'
        data = json.loads(receipt.read_text())
        data['outputs'] = {}
        receipt.write_text(json.dumps(data))
        (out / 'strokes/preview.gif').unlink()
        self.command(installed, 'verify_layers.py', str(out / 'strokes'), success=False)

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
        self.assertTrue(report['packaged_layers_and_strokes_checked'])
        self.assertTrue(report['packaged_gif_layers_checked'])
        self.assertTrue(report['packaged_motion_checked'])
        motion = json.loads((out / 'motion/verification.json').read_text())
        self.assertEqual(motion['frames_reopened_and_matched'], 234)
        self.assertEqual(motion['visual_review'], 'pending')
        layers = json.loads((out / 'layers/verification.json').read_text())
        self.assertEqual(layers['frames_reopened_and_matched'], 200)
        self.assertEqual(layers['visual_review'], 'pending')
        self.assertEqual(json.loads((out / 'media/verification.json').read_text())['visual_review'], 'pending')


if __name__ == '__main__':
    unittest.main()
