"""Source review must show every selected drawing without accepting or editing it."""
import copy
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin
from gif_cinema import layers
from tools import review_layer_sources as review


class NativeLayerReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name).resolve()
        frames = [Image.new('RGBA', (4, 4), color) for color in ('red', 'green', 'blue')]
        frames[0].save(cls.root / 'source.gif', save_all=True, append_images=frames[1:], duration=[20, 20, 20], loop=0)
        atlas = Image.new('RGBA', (36, 4))
        for i in range(9):
            atlas.paste(Image.new('RGBA', (4, 4), (17 + i, 33, 49, 64)), (i * 4, 0))
        atlas.save(cls.root / 'atlas.png')
        scene = {'format': layers.FORMAT, 'schema_version': 1, 'title': 'Native drawings',
                 'width': 16, 'height': 16, 'duration_ms': 160, 'fps': 25, 'loop': False,
                 'layers': [
                     {'id': 'gif', 'type': 'gif', 'source': 'source.gif', 'size': [4, 4]},
                     {'id': 'sprite', 'type': 'sprites', 'source': 'atlas.png', 'size': [4, 4], 'sampling': 'pixel',
                      'frames': [{'rect': [i * 4, 0, 4, 4], 'duration_ms': 20} for i in range(9)]}]}
        (cls.root / 'scene.json').write_text(json.dumps(scene), encoding='utf-8')
        cls.render = cls.root / 'render'
        layers.render_scene(cls.root / 'scene.json', cls.render)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve(); self.render = self.root / 'render'
        shutil.copytree(type(self).render, self.render)
        self.out = self.root / 'review'
        for target in ('urllib.request.OpenerDirector.open', 'socket.create_connection'):
            guard = patch(target, side_effect=AssertionError('Network forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def hashes(self, root):
        return {str(p.relative_to(root)): layers.digest(p.read_bytes()) for p in root.rglob('*') if p.is_file()}

    def manifest(self):
        return json.loads((self.out / 'manifest.json').read_text(encoding='utf-8'))

    def save_manifest(self, value):
        (self.out / 'manifest.json').write_text(json.dumps(value), encoding='utf-8')

    def test_every_native_drawing_including_unsampled_poses_and_soft_alpha_is_exported(self):
        before = self.hashes(self.render)
        with patch.object(layers, 'run_command', side_effect=AssertionError('No media tools')):
            result = review.extract(self.render, self.out)
            verified = review.check(self.render, self.out)
        self.assertEqual(self.hashes(self.render), before)
        self.assertEqual(result['drawing_count'], 12)
        self.assertEqual(verified['drawings_verified'], 12)
        self.assertEqual(verified['artifacts_verified'], 16)
        self.assertEqual(verified['visual_review'], 'pending')
        self.assertEqual(verified['user_acceptance'], 'pending')
        sprite = result['layers'][1]
        self.assertEqual(sprite['selected_source_indices'], list(range(9)))
        self.assertEqual(sprite['sampled_source_indices'], [0, 2, 4, 6])
        with Image.open(self.out / 'drawings/0003.png') as image:
            self.assertEqual(image.getpixel((0, 0)), (17, 33, 49, 64))
        for name, expected_size in [('sprite-000.png', (816, 928)), ('sprite-001.png', (816, 232))]:
            with Image.open(self.out / 'sheets' / name) as sheet:
                self.assertEqual(sheet.size, expected_size)
                self.assertEqual(sheet.getpixel((6, 31)), (255, 255, 255))
                self.assertEqual(sheet.getpixel((204, 31)), (17, 24, 39))

    def test_plan_writes_nothing_and_native_budgets_precede_review_crop_allocation(self):
        with patch.object(layers, 'run_command', side_effect=AssertionError('No encoder')):
            plan = review.extract(self.render, self.out, dry_run=True)
        self.assertEqual(plan['status'], 'planned'); self.assertFalse(self.out.exists())
        for constant in ('MAX_DRAWINGS', 'MAX_NATIVE_PIXELS'):
            with patch.object(review, constant, 1), patch.object(review, 'drawing', side_effect=AssertionError('No review crops')):
                with self.assertRaisesRegex(ValueError, '512 drawings'):
                    review.extract(self.render, self.out)
            self.assertFalse(self.out.exists())

    def test_existing_output_and_symlink_parent_fail_before_verifying_export(self):
        self.out.mkdir(); sentinel = self.out / 'keep'; sentinel.write_text('untouched')
        with patch.object(review, 'verify', side_effect=AssertionError('No verifier call')):
            with self.assertRaisesRegex(ValueError, 'new directory'):
                review.extract(self.render, self.out)
        self.assertEqual(sentinel.read_text(), 'untouched')
        alias = self.root / 'alias'
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('Directory symlinks unavailable')
        with self.assertRaisesRegex(ValueError, 'without symlinks'):
            review.extract(self.render, alias / 'new-review')

    def test_incomplete_final_export_is_not_treated_as_verified_source(self):
        (self.render / 'preview.mp4').unlink()
        with self.assertRaises((ValueError, OSError)):
            review.extract(self.render, self.out)
        self.assertFalse(self.out.exists())

    def test_empty_animated_source_selection_is_rejected(self):
        path = self.root / 'still.json'
        scene = {'format': layers.FORMAT, 'schema_version': 1, 'width': 8, 'height': 8,
                 'duration_ms': 40, 'layers': [{'id': 'still', 'type': 'rect', 'size': [4, 4]}]}
        path.write_text(json.dumps(scene)); out = self.root / 'still-render'; layers.render_scene(path, out)
        with self.assertRaisesRegex(ValueError, 'at least one GIF or sprite'):
            review.extract(out, self.out)
        self.assertFalse(self.out.exists())

    def test_changed_source_during_extraction_leaves_only_incomplete_output(self):
        original = review.player
        def mutate(facts):
            source = next((self.render / 'editable/assets').iterdir())
            source.write_bytes(b'changed during review')
            return original(facts)
        with patch.object(review, 'player', side_effect=mutate):
            with self.assertRaises(ValueError):
                review.extract(self.render, self.out)
        self.assertTrue((self.out / 'drawings/0000.png').exists())
        self.assertFalse((self.out / 'manifest.json').exists())

    def test_directory_replacement_is_detected_without_deleting_either_directory(self):
        original = review.sheet_image; old = self.root / 'original-review'
        def replace(*args):
            if not old.exists():
                self.out.rename(old); self.out.mkdir(); (self.out / 'unrelated.txt').write_text('keep')
            return original(*args)
        with patch.object(review, 'sheet_image', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'directory changed'):
                review.extract(self.render, self.out)
        self.assertEqual((self.out / 'unrelated.txt').read_text(), 'keep')
        self.assertTrue((old / 'drawings/0000.png').exists())
        self.assertFalse((self.out / 'manifest.json').exists())

    def test_ancestor_replacement_during_long_verification_cannot_redirect_publication(self):
        parent = self.root / 'parent'; parent.mkdir(); outside = self.root / 'other'; outside.mkdir()
        out = parent / 'new-review'; original = review.load_export
        def swap(*args):
            result = original(*args)
            parent.rename(self.root / 'old-parent')
            try:
                parent.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest('Directory symlinks unavailable')
            return result
        with patch.object(review, 'load_export', side_effect=swap):
            with self.assertRaisesRegex(ValueError, 'changed'):
                review.extract(self.render, out)
        self.assertEqual(list(outside.iterdir()), [])

    def test_ordinary_parent_replacement_and_unexpected_new_parent_are_not_adopted(self):
        original = review.load_export
        for existed in (False, True):
            parent = self.root / f'parent-{existed}'
            if existed:
                parent.mkdir()
            def replace(*args):
                result = original(*args)
                if existed:
                    parent.rename(self.root / 'old-parent')
                parent.mkdir(); (parent / 'sentinel').write_text('keep')
                return result
            with patch.object(review, 'load_export', side_effect=replace):
                with self.assertRaisesRegex(ValueError, 'ancestor changed'):
                    review.extract(self.render, parent / 'review')
            self.assertEqual([p.name for p in parent.iterdir()], ['sentinel'])

    def test_unexpected_existing_output_filename_is_not_overwritten(self):
        original = review.player
        def collide(facts):
            (self.out / 'index.html').write_text('unrelated content')
            return original(facts)
        with patch.object(review, 'player', side_effect=collide):
            with self.assertRaises(FileExistsError):
                review.extract(self.render, self.out)
        self.assertEqual((self.out / 'index.html').read_text(), 'unrelated content')
        self.assertFalse((self.out / 'manifest.json').exists())

    def test_output_byte_limit_retains_partial_files_without_completion_manifest(self):
        with patch.object(review, 'MAX_OUTPUT_BYTES', 100):
            with self.assertRaisesRegex(ValueError, '512 MiB'):
                review.extract(self.render, self.out)
        self.assertTrue(self.out.exists()); self.assertFalse((self.out / 'manifest.json').exists())

    def test_inventory_facts_and_pending_status_cannot_be_forged(self):
        review.extract(self.render, self.out); original = self.manifest()
        for mutate in [lambda v: v.update(artifacts={}), lambda v: v['artifacts'].pop('drawings/0000.png'),
                       lambda v: v['artifacts'].update({'../outside.png': '0' * 64}),
                       lambda v: v.update(visual_review='passed'), lambda v: v.update(user_acceptance='accepted'),
                       lambda v: v['drawings'][0].update(source_index=9),
                       lambda v: v.update(export_receipt_sha256='0' * 64)]:
            changed = copy.deepcopy(original); mutate(changed); self.save_manifest(changed)
            with self.assertRaises(ValueError):
                review.check(self.render, self.out)

    def test_rehashed_native_png_still_must_match_original_rgba(self):
        review.extract(self.render, self.out)
        path = self.out / 'drawings/0003.png'; Image.new('RGBA', (4, 4), 'yellow').save(path)
        manifest = self.manifest(); manifest['artifacts']['drawings/0003.png'] = layers.digest(path.read_bytes()); self.save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, 'pixels differ from source'):
            review.check(self.render, self.out)

    def test_rehashed_png_cannot_change_display_orientation_or_color_metadata(self):
        review.extract(self.render, self.out); original = self.manifest()
        path = self.out / 'drawings/0003.png'; raw = path.read_bytes()
        exif = Image.Exif(); exif[274] = 6
        gamma = PngImagePlugin.PngInfo(); gamma.add(b'gAMA', struct.pack('>I', 100000))
        for options in ({'exif': exif}, {'pnginfo': gamma}, {'icc_profile': b'changed color profile'}):
            with Image.open(io.BytesIO(raw)) as image:
                before = image.tobytes(); image.save(path, **options)
            with Image.open(path) as image:
                self.assertEqual(image.tobytes(), before)
            manifest = copy.deepcopy(original); manifest['artifacts']['drawings/0003.png'] = layers.digest(path.read_bytes()); self.save_manifest(manifest)
            with self.assertRaisesRegex(ValueError, 'unexpected display metadata'):
                review.check(self.render, self.out)

    def test_manifest_facts_keep_json_types_and_count_manifest_in_output_budget(self):
        review.extract(self.render, self.out); original = self.manifest()
        for mutate in (lambda v: v.update(schema_version=True), lambda v: v.update(api_calls=False),
                       lambda v: v.update(drawing_count=12.0), lambda v: v['drawings'][0].update(width=4.0)):
            changed = copy.deepcopy(original); mutate(changed); self.save_manifest(changed)
            with self.assertRaisesRegex(ValueError, 'facts differ'):
                review.check(self.render, self.out)
        self.save_manifest(original)
        artifact_bytes = sum((self.out / name).stat().st_size for name in original['artifacts'])
        with patch.object(review, 'MAX_OUTPUT_BYTES', artifact_bytes):
            with self.assertRaisesRegex(ValueError, 'output byte budget'):
                review.check(self.render, self.out)

    def test_rehashed_sheet_and_html_cannot_hide_changed_content(self):
        review.extract(self.render, self.out); original = self.manifest()
        for name in ('index.html', 'sheets/gif-000.png'):
            path = self.out / name; raw = path.read_bytes()
            if name.endswith('.html'):
                path.write_bytes(raw + b' changed')
            else:
                with Image.open(io.BytesIO(raw)) as image:
                    image.putpixel((0, 0), (255, 0, 0)); image.save(path)
            manifest = copy.deepcopy(original); manifest['artifacts'][name] = layers.digest(path.read_bytes()); self.save_manifest(manifest)
            with self.assertRaises(ValueError):
                review.check(self.render, self.out)
            path.write_bytes(raw)

    def test_current_export_and_renderer_revision_are_bound(self):
        review.extract(self.render, self.out)
        original = self.manifest(); changed = copy.deepcopy(original); changed['review_renderer']['pillow'] = '0.0'; self.save_manifest(changed)
        with self.assertRaisesRegex(ValueError, 'original Pillow version'):
            review.check(self.render, self.out)
        self.save_manifest(original)
        path = self.render / 'receipt.json'; receipt = json.loads(path.read_text()); receipt['new_note'] = 'new revision'; path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'facts differ'):
            review.check(self.render, self.out)

    def test_player_author_text_is_escaped_once_and_cannot_break_script(self):
        facts, _, _ = review.load_export(self.render)
        facts['title'] = '<script>alert("TITLE DATA")</script>'
        facts['layers'][0]['name'] = '</script> TITLE SHEETS DATA NOTICE'
        page = review.player(facts).decode()
        self.assertEqual(page.count('</script>'), 1)
        embedded = page.split('const data=', 1)[1].split(';const el=', 1)[0]
        self.assertEqual(json.loads(embedded)['layers'][0]['name'], facts['layers'][0]['name'])
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('src="http', page)

    def test_cli_plan_requires_no_media_encoder_and_writes_nothing(self):
        command = [sys.executable, 'tools/review_layer_sources.py', 'extract', str(self.render), str(self.out), '--dry-run']
        completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['drawing_count'], 12)
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
