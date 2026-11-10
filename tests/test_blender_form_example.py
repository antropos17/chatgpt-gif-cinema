"""Verify the shipped standalone Blender example without installing Blender."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples' / 'blender-form-01'


class BlenderFormExampleTests(unittest.TestCase):
    def test_provenance_and_exact_shipped_bytes(self):
        manifest = json.loads((EXAMPLE / 'provenance.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['new_provider_calls'], 0)
        self.assertFalse(manifest['javascript_animation'])
        self.assertTrue(manifest['standalone_example'])
        self.assertFalse(manifest['runtime_backend_added'])
        self.assertIn('Blender EEVEE 4.3.2', manifest['production_method'])
        self.assertEqual(manifest['review']['full_frame_visual_review'], 'pending')
        self.assertEqual(manifest['review']['user_artistic_acceptance'], 'pending')
        for name, expected in manifest['files'].items():
            with self.subTest(file=name):
                path = (EXAMPLE / name).resolve()
                self.assertTrue(path.is_relative_to(EXAMPLE.resolve()))
                data = path.read_bytes()
                self.assertEqual(len(data), expected['bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected['sha256'])

    def test_actual_gif_has_exact_cadence_and_loop(self):
        with Image.open(EXAMPLE / 'deliverables/FORM-01.gif') as gif:
            self.assertEqual(gif.size, (640, 640))
            self.assertEqual(gif.n_frames, 120)
            self.assertEqual(gif.info.get('loop'), 0)
            durations = []
            for frame in ImageSequence.Iterator(gif):
                frame.convert('RGBA').load()
                durations.append(frame.info['duration'])
            self.assertEqual(durations, [50] * 120)
            self.assertEqual(sum(durations), 6000)

    def test_editable_blend_source_and_font_license_exist(self):
        self.assertEqual((EXAMPLE / 'form_01.blend').read_bytes()[:7], b'BLENDER')
        source = (EXAMPLE / 'form_study.py').read_text(encoding='utf-8')
        compile(source, 'form_study.py', 'exec')
        self.assertIn("sc.render.engine='BLENDER_EEVEE_NEXT'", source)
        self.assertIn('bpy.ops.file.make_paths_relative()', source)
        self.assertIn('range(1,146)', source)
        license_text = (EXAMPLE / 'assets/DejaVu-LICENSE.txt').read_text(encoding='utf-8')
        self.assertIn('Copyright (c) 2003 by Bitstream', license_text)
        self.assertIn('DejaVu changes are in public domain', license_text)
        readme = (EXAMPLE / 'README.md').read_text(encoding='utf-8')
        self.assertIn('not output from an AI image/video model', readme)
        self.assertIn('not a full-frame, real-time playback review', readme)
        self.assertIn('../../LICENSE', readme)

    def test_import_recipe_preserves_gif_cadence_without_prompts(self):
        film = json.loads((EXAMPLE / 'import-film.json').read_text(encoding='utf-8'))
        self.assertEqual((film['width'], film['height'], film['fps']), (640, 640, 20))
        self.assertEqual(len(film['shots']), 1)
        shot = film['shots'][0]
        self.assertEqual(shot['source'], 'deliverables/FORM-01.gif')
        self.assertNotIn('prompt', shot)
        self.assertTrue((EXAMPLE / shot['source']).is_file())

    def test_numerical_seam_receipt_is_not_visual_acceptance(self):
        receipt = json.loads((EXAMPLE / 'deliverables/validation.json').read_text(encoding='utf-8'))
        self.assertTrue(receipt['geometry_loop_closed'])
        self.assertLess(receipt['geometry_loop_max_transform_error'], 1e-6)
        self.assertEqual(receipt['unique_render_frames'], 144)
        self.assertEqual(receipt['gif']['frame_count'], 120)
        self.assertAlmostEqual(receipt['gif']['seconds'], 6)
        self.assertLess(abs(receipt['frame_seam_mean_abs_rgb_difference'] -
                            receipt['first_step_mean_abs_rgb_difference']), .01)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                         'FFmpeg and ffprobe required for actual video verification')
    def test_actual_mp4_probe_and_complete_decode(self):
        path = EXAMPLE / 'deliverables/FORM-01.mp4'
        result = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-count_frames',
                                 '-show_streams', '-show_format', '-of', 'json', str(path)],
                                capture_output=True, text=True, timeout=30, check=True)
        probe = json.loads(result.stdout)
        self.assertEqual(len(probe['streams']), 1)
        video = probe['streams'][0]
        self.assertEqual(video['codec_name'], 'h264')
        self.assertEqual((video['width'], video['height']), (800, 800))
        self.assertEqual(video['r_frame_rate'], '24/1')
        self.assertEqual(int(video['nb_read_frames']), 144)
        self.assertAlmostEqual(float(probe['format']['duration']), 6, places=3)
        subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-xerror', '-nostdin',
                        '-i', str(path), '-f', 'null', '-'],
                       capture_output=True, timeout=30, check=True)


if __name__ == '__main__':
    unittest.main()
