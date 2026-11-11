"""Integrity and lightweight media checks for the original offline sequence example.

No encoder build, generated artwork, network access or 250-frame rerender is needed.
The committed provenance describes viewing copies, not human visual acceptance.
"""
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from PIL import Image, ImageSequence

from gif_cinema import sequence


# Resolve checkout aliases (including macOS /var aliases) before passing strict
# no-symlink paths to the compiler. These tests never write inside the checkout.
ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = (ROOT / 'examples' / 'scene-sequence').resolve()
PREVIEWS = (ROOT / 'docs' / 'assets' / 'scene-sequence').resolve()
SHOT_IDS = ['01-offer', '02-receive', '03-release', '04-lift', '05-hang']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


class SceneSequenceExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provenance = read_json(EXAMPLE / 'preview-provenance.json')
        cls.stage = read_json(EXAMPLE / 'stage.json')
        cls.project = read_json(EXAMPLE / 'sequence.json')
        cls.compilation = sequence.compile_sequence(EXAMPLE / 'sequence.json')

    def test_raw_editable_sources_match_committed_provenance(self):
        # Intentionally hash bytes rather than normalized JSON: the exact authored
        # source snapshot is pinned. Git attributes keep these inputs LF on Windows.
        self.assertEqual(digest(EXAMPLE / 'sequence.json'),
                         self.provenance['original_project_sha256'])
        self.assertEqual(digest(EXAMPLE / 'stage.json'),
                         self.provenance['original_stage_sha256'])
        self.assertEqual(self.project['stage'], 'stage.json')
        report = self.compilation['report']
        self.assertEqual(report['project_sha256'], self.provenance['original_project_sha256'])
        self.assertEqual(report['stage_sha256'], self.provenance['original_stage_sha256'])

    def test_fixed_artwork_hashes_match_portable_asset_inventory(self):
        sources = {layer['source'] for layer in self.stage['layers'] if layer['type'] == 'image'}
        self.assertEqual(len(sources), 8)
        self.assertEqual(sources, {'assets/' + path.name for path in (EXAMPLE / 'assets').iterdir()
                                   if path.is_file()})
        authored = {name: digest(EXAMPLE / name) for name in sources}
        self.assertEqual(self.compilation['report']['asset_sha256'], authored)
        portable = self.provenance['asset_sha256']
        self.assertEqual(len(portable), 8)
        # The export content-addresses original assets, so filenames differ while
        # their exact byte digests (including multiplicity) must remain identical.
        self.assertEqual(Counter(authored.values()), Counter(portable.values()))
        for name, sha256 in portable.items():
            with self.subTest(asset=name):
                self.assertEqual(name, 'assets/' + sha256 + '.image')
        for name in sources:
            with self.subTest(source=name), Image.open(EXAMPLE / name) as artwork:
                self.assertEqual(artwork.format, 'PNG')
                self.assertEqual(artwork.mode, 'RGBA')
                self.assertEqual(getattr(artwork, 'n_frames', 1), 1)

    def test_viewing_files_match_complete_provenance_inventory(self):
        expected = {'preview.mp4', 'preview.gif', 'contact-sheet.png',
                    'join-01.png', 'join-02.png', 'join-03.png', 'join-04.png'}
        inventory = self.provenance['files']
        self.assertEqual(set(inventory), expected)
        self.assertEqual({path.name for path in PREVIEWS.iterdir() if path.is_file()}, expected)
        for name, sha256 in inventory.items():
            with self.subTest(preview=name):
                self.assertEqual(digest(PREVIEWS / name), sha256)
        with Image.open(PREVIEWS / 'contact-sheet.png') as sheet:
            self.assertEqual(sheet.size, (1920, 1800))
        for index in range(1, 5):
            with self.subTest(join=index), Image.open(PREVIEWS / f'join-{index:02}.png') as sheet:
                self.assertEqual(sheet.size, (1920, 388))

    def test_five_distinct_actions_carry_one_lantern_without_reset(self):
        report = self.compilation['report']
        timeline = report['timeline']
        self.assertEqual([shot['id'] for shot in timeline], SHOT_IDS)
        self.assertEqual(len({shot['action'] for shot in timeline}), 5)
        self.assertEqual([shot['start_ms'] for shot in timeline], [0, 2000, 4000, 5600, 8000])
        self.assertEqual([shot['duration_ms'] for shot in timeline], [2000, 2000, 1600, 2400, 2000])
        self.assertEqual([shot['frames'] for shot in timeline], [50, 50, 40, 60, 50])
        for key, expected in [('duration_ms', 10000), ('frames', 250), ('fps', 25),
                              ('provider_calls', 0)]:
            self.assertEqual(report[key], expected)
            self.assertEqual(self.provenance[key], expected)
        self.assertEqual((report['width'], report['height']), (640, 360))
        holders = ['courier-hand', 'courier-hand', 'keeper-hand', 'keeper-hand', 'hook']
        layer_ids = [layer['id'] for layer in self.stage['layers']]
        self.assertEqual(layer_ids.count('lantern'), 1)
        for shot, prepared, holder in zip(timeline, self.compilation['compiled'], holders):
            with self.subTest(shot=shot['id']):
                self.assertEqual([layer['id'] for layer in prepared['scene']['layers']], layer_ids)
                for endpoint in ('start_state', 'end_state'):
                    self.assertEqual(shot[endpoint]['lantern']['attachment']['parent'], holder)
                # Each action changes an actual arm pose, not only a caption.
                self.assertTrue(any(shot['start_state'][arm] != shot['end_state'][arm]
                                    for arm in ('courier-arm', 'keeper-arm')))
        for previous, following in zip(timeline, timeline[1:]):
            for layer_id, old in previous['end_state'].items():
                for property_name, value in old.items():
                    if property_name != 'attachment':
                        with self.subTest(join=following['id'], layer=layer_id, property=property_name):
                            self.assertAlmostEqual(value, following['start_state'][layer_id][property_name], places=7)
        for index, expected in [(2, (320, 225)), (4, (349.28932188134524, 154.28932188134524))]:
            lantern = timeline[index]['start_state']['lantern']
            self.assertAlmostEqual(lantern['x'] * 640, expected[0], places=7)
            self.assertAlmostEqual(lantern['y'] * 360, expected[1], places=7)

    def test_provenance_does_not_claim_visual_acceptance(self):
        self.assertEqual(self.provenance['visual_acceptance'], 'not-established')
        self.assertEqual(self.compilation['report']['visual_acceptance'], 'not-established')
        joins = self.provenance['joins']
        self.assertEqual([(join['previous'], join['next']) for join in joins],
                         list(zip(SHOT_IDS, SHOT_IDS[1:])))
        for join in joins:
            self.assertEqual(join['status'], 'human-review-required')
            self.assertTrue(join['endpoint_pixels_equal'])
            self.assertTrue(join['last_stored_pixels_equal'])
            self.assertEqual(join['previous_last_rgba_sha256'], join['next_first_rgba_sha256'])
            self.assertEqual(join['previous_endpoint_rgba_sha256'], join['next_first_rgba_sha256'])

    def test_actual_gif_is_play_once_with_coalesced_holds(self):
        with Image.open(PREVIEWS / 'preview.gif') as gif:
            self.assertEqual(gif.format, 'GIF')
            self.assertEqual(gif.size, (640, 360))
            self.assertNotIn('loop', gif.info)
            self.assertEqual(gif.n_frames, 206)
            durations = []
            for frame in ImageSequence.Iterator(gif):
                frame.load()
                durations.append(frame.info['duration'])
            self.assertEqual(sum(durations), 10000)
            self.assertTrue(all(duration > 0 and duration % 40 == 0 for duration in durations))
            self.assertGreater(max(durations), 40)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                         'FFmpeg and ffprobe required for actual video inspection')
    def test_actual_mp4_codec_dimensions_and_timing(self):
        result = subprocess.run(
            [shutil.which('ffprobe'), '-v', 'error', '-count_frames', '-show_streams',
             '-show_format', '-of', 'json', str(PREVIEWS / 'preview.mp4')],
            capture_output=True, text=True, timeout=30, check=True)
        probe = json.loads(result.stdout)
        self.assertEqual(len(probe['streams']), 1)
        video = probe['streams'][0]
        self.assertEqual(video['codec_type'], 'video')
        self.assertEqual(video['codec_name'], 'h264')
        self.assertEqual(video['pix_fmt'], 'yuv420p')
        self.assertEqual((video['width'], video['height']), (640, 360))
        self.assertEqual(Fraction(video['r_frame_rate']), 25)
        self.assertEqual(Fraction(video['avg_frame_rate']), 25)
        self.assertEqual(int(video['nb_read_frames']), 250)
        self.assertAlmostEqual(float(probe['format']['duration']), 10, places=3)


if __name__ == '__main__':
    unittest.main()
