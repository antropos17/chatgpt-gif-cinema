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
            self.assertEqual(manifest['skill_version'], '0.4.1')
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
        shutil.copy2(ROOT / 'LICENSE', repository / 'LICENSE')
        def git(*parts):
            return subprocess.run(['git', *parts], cwd=repository, check=True,
                                  capture_output=True, timeout=30)
        git('init', '-q')
        git('config', 'core.autocrlf', 'true')
        git('add', '.gitattributes', 'LICENSE', str(relative))
        checked = self.root / 'autocrlf-worktree'
        checked.mkdir()
        git('checkout-index', '--all', '--force', '--prefix=' + checked.as_posix() + '/')
        self.assertEqual((checked / 'LICENSE').read_bytes(), (ROOT / 'LICENSE').read_bytes())
        self.assertEqual((checked / relative / 'LICENSE').read_bytes(),
                         (checked / 'LICENSE').read_bytes())
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
        for script in ('smoke_layers.py', 'smoke_motion.py', 'smoke_factory.py', 'smoke_master.py', 'smoke_test.py'):
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
        self.assertTrue(report['packaged_factory_checked'])
        self.assertTrue(report['packaged_master_checked'])
        self.assertEqual(set(report['components']), {'media', 'layers', 'motion', 'factory', 'master'})
        for component in report['components']:
            raw = (out / component / 'verification.json').read_bytes()
            receipt = json.loads(raw)
            self.assertEqual(receipt['status'], 'passed')
            self.assertIs(type(receipt['provider_calls']), int)
            self.assertEqual(receipt['provider_calls'], 0)
            self.assertEqual(report['components'][component]['receipt_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(report['components'][component]['receipt_bytes'], len(raw))
        motion = json.loads((out / 'motion/verification.json').read_text())
        self.assertEqual(motion['frames_reopened_and_matched'], 234)
        self.assertEqual(motion['visual_review'], 'pending')
        layers = json.loads((out / 'layers/verification.json').read_text())
        self.assertEqual(layers['frames_reopened_and_matched'], 200)
        self.assertEqual(layers['visual_review'], 'pending')
        self.assertEqual(json.loads((out / 'media/verification.json').read_text())['visual_review'], 'pending')

    def load_smoke(self, name, installed=SKILL):
        checker = module('isolated_checker_' + name, installed / 'scripts/check_install.py')
        # Earlier extracted-smoke tests may leave a module from an already-cleaned
        # temporary installation in sys.modules. Bind each helper to its own root.
        with patch.object(sys, 'path', [str(installed / 'scripts'), *sys.path]), \
                patch.dict(sys.modules, {'check_install': checker}):
            return module('test_' + name, installed / 'scripts' / name)

    def test_factory_manifest_pins_unchanged_bundled_inputs(self):
        manifest = json.loads((SKILL / 'assets/example/factory.json').read_text())
        self.assertEqual([('gif' if 'gif' in item else 'scene') for item in manifest['items']], ['gif', 'scene'])
        for item in manifest['items']:
            path = SKILL / 'assets/example' / item.get('gif', item.get('scene'))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item['sha256'])

    def test_checker_requires_factory_and_master_interfaces_and_dispatch(self):
        from gif_cinema import factory, master
        for component, label, name in ((factory, 'factory', 'build_factory'), (master, 'master', 'verify_master')):
            with self.subTest(label=label), patch.object(component, name, None):
                with self.assertRaisesRegex(ValueError, label + ' interfaces'):
                    check.check_runtime()
        for component, label in ((factory, 'factory'), (master, 'master')):
            with self.subTest(label=label), patch.object(component, 'add_parser', return_value=None):
                with self.assertRaisesRegex(ValueError, label + ' CLI commands'):
                    check.check_runtime()
        from gif_cinema import cli
        original = cli.build_parser
        def wrong_dispatch():
            parser = original()
            original_parse = parser.parse_args
            def parse(*args, **kwargs):
                result = original_parse(*args, **kwargs)
                if result.command == 'master':
                    result.func = factory.run
                return result
            parser.parse_args = parse
            return parser
        with patch.object(cli, 'build_parser', side_effect=wrong_dispatch):
            with self.assertRaisesRegex(ValueError, 'master CLI dispatch'):
                check.check_runtime()

    def test_checker_requires_script_master_interfaces_and_cli_options(self):
        from gif_cinema import master, master_script
        with patch.object(master_script, 'write_template', None):
            with self.assertRaisesRegex(ValueError, 'script master interfaces'):
                check.check_runtime()
        with patch.object(master_script, 'build', lambda *args, **kwargs: None):
            with self.assertRaisesRegex(ValueError, 'script editing interfaces'):
                check.check_runtime()
        def legacy_parser(sub):
            parser = sub.add_parser('master')
            parser.add_argument('clips', nargs='+')
            parser.add_argument('--out', required=True)
            parser.add_argument('--preview', action='store_true')
            parser.add_argument('--audio')
            parser.add_argument('--dry-run', action='store_true')
            parser.set_defaults(func=master.run)
        with patch.object(master, 'add_parser', side_effect=legacy_parser):
            with self.assertRaisesRegex(ValueError, 'script master CLI commands'):
                check.check_runtime()

    def test_missing_lossless_is_explicit_optional_or_required(self):
        check.check_runtime()  # Load lazy CLI modules before patch.dict snapshots sys.modules.
        with patch.dict(sys.modules, {'av': None}):
            report = check.check_runtime()
            lossless = report['optional_dependencies']['lossless']
            self.assertEqual(lossless['status'], 'unavailable')
            self.assertFalse(lossless['required'])
            with self.assertRaisesRegex(ValueError, 'Lossless master requires'):
                check.check_runtime(require_master=True)

    def test_lossless_checker_rejects_unsupported_versions_and_missing_codec(self):
        from types import SimpleNamespace
        for version in ('16.0.0', '17.0.0', 'not-a-version'):
            with self.subTest(version=version), patch.dict(sys.modules, {'av': SimpleNamespace(__version__=version)}):
                self.assertEqual(check.check_lossless()['status'], 'unavailable')
                with self.assertRaisesRegex(ValueError, 'Lossless master requires'):
                    check.check_lossless(required=True)
        try:
            import av
        except ImportError:
            return
        with patch.object(av, 'Codec', side_effect=RuntimeError('FFV1 decoder unavailable')):
            report = check.check_lossless()
            self.assertEqual(report['status'], 'unavailable')
            self.assertTrue(report['ffv1_encoder'])
            self.assertFalse(report['ffv1_decoder'])
            with self.assertRaisesRegex(ValueError, 'Lossless master requires'):
                check.check_lossless(required=True)

    def test_missing_lossless_fails_master_and_full_smokes_before_output(self):
        check.check_runtime()  # Preserve module identity across simulated missing-dependency cases.
        for filename in ('smoke_master.py', 'smoke_test.py'):
            smoke = self.load_smoke(filename)
            out = self.root / filename
            with self.subTest(filename=filename), patch.dict(sys.modules, {'av': None}), \
                    patch.object(smoke.shutil, 'which', return_value='present'), \
                    patch.object(sys, 'argv', [filename, '--out', str(out)]):
                with self.assertRaisesRegex(ValueError, 'Lossless master requires'):
                    smoke.main()
                self.assertFalse(out.exists())

    def test_full_smoke_requires_verified_exact_zero_call_component_receipts(self):
        smoke = self.load_smoke('smoke_test.py')
        self.assertEqual(smoke.COMPONENTS, ('media', 'layers', 'motion', 'factory', 'master'))
        path = self.root / 'verification.json'
        for data in ({}, [], {'status': 'passed'}, {'status': 'failed', 'provider_calls': 0},
                     *({'status': 'passed', 'provider_calls': value}
                       for value in (False, True, 0.0, '0', None, 1, -1))):
            with self.subTest(data=data):
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, 'component receipt'):
                    smoke.verify_component_receipt(path)
        raw = b'{"status":"passed","provider_calls":0}\n'
        path.write_bytes(raw)
        result = smoke.verify_component_receipt(path)
        self.assertEqual(result['receipt_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['receipt_bytes'], len(raw))
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            smoke.verify_component_receipt(path)
        path.write_text('{')
        with self.assertRaises(ValueError):
            smoke.verify_component_receipt(path)

    def test_factory_and_master_smokes_exercise_public_dispatch(self):
        from gif_cinema import factory, master
        for filename, component, call, args in (
                ('smoke_factory.py', factory, 'factory_cli', ('build', 'unused.json', '--out', 'unused', '--dry-run')),
                ('smoke_master.py', master, 'master_cli', ('unused.gif', '--out', 'unused', '--dry-run'))):
            smoke = self.load_smoke(filename)
            with self.subTest(filename=filename), patch.object(component, 'run', side_effect=RuntimeError('dispatcher injected')) as dispatch:
                with self.assertRaises(SystemExit):
                    getattr(smoke, call)(*args)
                dispatch.assert_called_once()

    def test_new_smokes_refuse_installed_output_without_bytecode(self):
        installed = self.unpack()
        for filename in ('smoke_factory.py', 'smoke_master.py', 'smoke_test.py'):
            out = installed / filename
            with self.subTest(filename=filename):
                result = self.command(installed, filename, '--out', str(out), success=False, allow_bytecode=True)
                self.assertIn('outside the installed skill', result.stderr)
                self.assertFalse(out.exists())
                self.assertEqual(list(installed.rglob('__pycache__')), [])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_extracted_factory_smoke_rejects_tampered_collection(self):
        installed = self.unpack()
        out = self.root / 'factory smoke'
        report = json.loads(self.command(installed, 'smoke_factory.py', '--out', str(out), allow_bytecode=True).stdout)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['collection']['output_hashes_verified'], 9)
        self.assertEqual(report['collection']['zip_members_matched'], 8)
        self.assertEqual(report['installation']['package']['status'], 'passed')
        self.assertEqual(report['visual_review'], report['user_acceptance'])
        self.assertEqual(report['visual_review'], 'pending')
        smoke = self.load_smoke('smoke_factory.py', installed)
        manifest, collection = installed / 'assets/example/factory.json', out / 'collection'
        plan = smoke.factory_cli('build', manifest, '--out', self.root / 'unused', '--dry-run')
        verified = smoke.factory_cli('verify', collection)
        smoke.check_collection(collection, manifest, plan, verified)
        imported = collection / 'gifs/astronaut.gif'
        original = imported.read_bytes()
        imported.write_bytes(original + b'changed')
        with self.assertRaisesRegex(ValueError, 'Imported GIF bytes changed'):
            smoke.check_collection(collection, manifest, plan, verified)
        imported.write_bytes(original)
        (collection / 'unexpected.txt').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            smoke.check_collection(collection, manifest, plan, verified)
        (collection / 'unexpected.txt').unlink()
        with zipfile.ZipFile(collection / 'collection.zip', 'a') as archive:
            archive.writestr('collection/injected.txt', 'changed')
        verified['zip_sha256'] = hashlib.sha256((collection / 'collection.zip').read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'ZIP inventory'):
            smoke.check_collection(collection, manifest, plan, verified)
        self.assertEqual(list(installed.rglob('__pycache__')), [])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and ffprobe required')
    def test_extracted_master_smoke_reopens_all_pixels_and_final_hold(self):
        try:
            import av
        except ImportError:
            self.skipTest('Optional av lossless extra required')
        installed = self.unpack()
        out = self.root / 'master smoke'
        report = json.loads(self.command(installed, 'smoke_master.py', '--out', str(out), allow_bytecode=True).stdout)
        self.assertEqual(report['frames_reopened_and_matched'], 3)
        self.assertEqual(report['durations_ms'], [10, 20, 150])
        self.assertEqual(report['pts_cs'], [0, 1, 3])
        self.assertEqual(report['final_hold_ms'], 150)
        self.assertEqual(report['preview_frames'], 18)
        self.assertEqual(report['audio_target_samples'], 8640)
        self.assertEqual(report['script_ranges'], [[0, 2], [2, 3]])
        self.assertEqual(report['caption_ranges_ms'], [[0, 30], [30, 180]])
        self.assertTrue(report['script_edit_checked'])
        self.assertEqual(report['output_hashes_verified'], 4)
        self.assertEqual(report['installation']['package']['status'], 'passed')
        self.assertEqual(report['visual_review'], 'pending')
        self.assertEqual(report['user_acceptance'], 'pending')
        smoke = self.load_smoke('smoke_master.py', installed)
        output, source, audio = out / 'master', out / 'source.gif', out / 'short.wav'
        path = output / 'manifest.json'
        original = path.read_bytes()
        data = json.loads(original)
        data['frames'][-1]['duration_cs'] = 14
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'trace mismatch'):
            smoke.verify_export(output, source, audio, out / 'film.json', out / 'edits.json')
        path.write_bytes(original)
        # Updating a tampered sidecar's recorded checksum must not hide wrong cut timing.
        for name, expected_error in (('captions.srt', 'Reopened SRT'), ('timeline.json', 'Reopened timeline')):
            sidecar = output / name
            saved_sidecar = sidecar.read_bytes()
            if name == 'captions.srt':
                sidecar.write_bytes(saved_sidecar.replace(b'00:00:00,030', b'00:00:00,040'))
            else:
                broken = json.loads(saved_sidecar)
                broken['shots'][0]['end_ms'] = 40
                sidecar.write_text(json.dumps(broken))
            data = json.loads(original)
            data['files'][name] = {'bytes': sidecar.stat().st_size,
                                   'sha256': hashlib.sha256(sidecar.read_bytes()).hexdigest()}
            path.write_text(json.dumps(data))
            with self.subTest(sidecar=name), self.assertRaisesRegex(ValueError, expected_error):
                smoke.verify_export(output, source, audio, out / 'film.json', out / 'edits.json')
            sidecar.write_bytes(saved_sidecar)
            path.write_bytes(original)
        movie = output / 'master.mkv'
        movie.write_bytes(movie.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'Output hash/size mismatch'):
            smoke.verify_export(output, source, audio, out / 'film.json', out / 'edits.json')
        self.assertEqual(list(installed.rglob('__pycache__')), [])


if __name__ == '__main__':
    unittest.main()
