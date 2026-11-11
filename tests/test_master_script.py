"""Exact script edits exercise real encoded frames, not just metadata reports."""
from contextlib import redirect_stdout
import io
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
from PIL import Image
from gif_cinema import cli, factory, master, master_script
try:
    import av
except ImportError:
    av = None


def gif(path, colors=('red', 'green', 'blue'), delays=(10, 20, 150), size=(24, 24), disposal=1):
    frames = [Image.new('RGBA', size, color) for color in colors]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=list(delays), disposal=disposal, optimize=False)


class ExactScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.out = self.root / 'out'
        self.a, self.b = self.root / 'a.gif', self.root / 'b.gif'
        gif(self.a); gif(self.b, ('yellow', 'magenta', 'cyan'), (70, 30, 90))
        self.script = self.root / 'film.json'
        self.data = {'schema_version': 1, 'title': 'Exact edit', 'ratio': '1:1', 'width': 24, 'height': 24,
                     'fps': 1, 'style_bible': 'Synthetic colors, not artwork.',
                     'shots': [{'id': name, 'source': name + '.gif', 'first_frame_target': 'Start',
                                'last_frame_target': 'End', 'caption': name.upper()} for name in ('a', 'b')]}
        self.save()
        self.net = patch('gif_cinema.cli.urlopen', side_effect=AssertionError('No provider calls'))
        self.net.start(); self.addCleanup(self.net.stop)

    def save(self): self.script.write_text(json.dumps(self.data), encoding='utf-8')

    def edits(self, ranges=((1, 3), (0, 2))):
        path = self.root / 'edits.json'
        master_script.write_template(self.script, path)
        data = json.loads(path.read_text())
        for shot, (first, stop) in zip(data['shots'], ranges): shot.update(in_frame=first, out_frame=stop)
        path.write_text(json.dumps(data)); return path

    def test_read_only_plan_uses_script_order_and_native_delays_not_fps(self):
        with patch.object(master, 'require_av', side_effect=AssertionError('No codec')), patch('subprocess.run', side_effect=AssertionError('No process')):
            result = master_script.build(self.script, self.out, dry_run=True)
        self.assertEqual(result['frame_count'], 6)
        self.assertEqual(result['duration_cs'], 37)
        self.assertEqual([(s['id'], s['start_ms'], s['end_ms']) for s in result['sequence']['timeline']], [('a', 0, 180), ('b', 180, 370)])
        self.assertFalse(self.out.exists())

    def test_template_pins_script_and_sources_and_preserves_existing_file(self):
        path = self.root / 'edit.json'; master_script.write_template(self.script, path)
        data = json.loads(path.read_text()); before = path.read_bytes()
        self.assertEqual(data['script_sha256'], factory.digest(self.script.read_bytes()))
        self.assertEqual(data['shots'][0], {'id': 'a', 'source_sha256': factory.digest(self.a.read_bytes()), 'in_frame': 0, 'out_frame': 3})
        with self.assertRaises(ValueError): master_script.write_template(self.script, path)
        self.assertEqual(path.read_bytes(), before)

    def test_changed_script_or_source_invalidates_edit_selection(self):
        path = self.edits(); original = self.script.read_bytes()
        self.script.write_bytes(original + b'\n')
        with self.assertRaisesRegex(ValueError, 'changed script'): master_script.build(self.script, self.out, edits=path, dry_run=True)
        self.script.write_bytes(original); gif(self.a, ('black', 'white', 'red'))
        with self.assertRaisesRegex(ValueError, 'source hash'): master_script.build(self.script, self.out, edits=path, dry_run=True)
        self.assertFalse(self.out.exists())

    def test_edits_cannot_reorder_omit_or_override_script_shots(self):
        path = self.edits(); data = json.loads(path.read_text())
        for shots in (list(reversed(data['shots'])), data['shots'][:1], [dict(data['shots'][0], source='b.gif'), data['shots'][1]]):
            path.write_text(json.dumps({**data, 'shots': shots}))
            with self.subTest(shots=shots), self.assertRaises(ValueError): master_script.build(self.script, self.out, edits=path, dry_run=True)

    def test_frame_ranges_reject_boolean_fraction_empty_negative_and_overflow(self):
        path = self.edits(); data = json.loads(path.read_text())
        for first, stop in ((True, 2), (0, 1.5), (0, 0), (-1, 2), (2, 1), (0, 4)):
            edited = json.loads(json.dumps(data)); edited['shots'][0].update(in_frame=first, out_frame=stop)
            path.write_text(json.dumps(edited))
            with self.subTest(first=first, stop=stop), self.assertRaises(ValueError): master_script.build(self.script, self.out, edits=path, dry_run=True)

    def test_duplicate_edit_fields_and_wrong_versions_are_rejected(self):
        path = self.edits(); raw = path.read_text()
        path.write_text(raw.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
        with self.assertRaisesRegex(ValueError, 'Duplicate'): master_script.build(self.script, self.out, edits=path, dry_run=True)
        data = json.loads(raw); data['schema_version'] = True; path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'format/version'): master_script.build(self.script, self.out, edits=path, dry_run=True)

    def test_source_only_rejects_generation_and_noncut_transitions(self):
        self.data['shots'][1].pop('source'); self.data['shots'][1]['prompt'] = 'Generate a scene'; self.save()
        with self.assertRaisesRegex(ValueError, 'existing source GIFs'): master_script.build(self.script, self.out, dry_run=True)
        self.data['shots'][1].pop('prompt'); self.data['shots'][1]['source'] = 'b.gif'; self.data['shots'][1]['transition'] = 'dissolve'; self.save()
        with self.assertRaisesRegex(ValueError, 'hard-cut'): master_script.build(self.script, self.out, dry_run=True)

    def test_caption_cue_injection_fails_before_output(self):
        for caption in ('Text\n\n2\n00:00:01,000 --> 00:00:02,000', 'Text\x00hidden', 'Text\n \nextra'):
            self.data['shots'][0]['caption'] = caption; self.save()
            with self.subTest(caption=caption), self.assertRaisesRegex(ValueError, 'Caption'): master_script.build(self.script, self.out, dry_run=True)
        self.assertFalse(self.out.exists())

    def test_small_script_canvas_fails_explicit_native_override_does_not_scale(self):
        gif(self.a, size=(26, 24))
        with self.assertRaisesRegex(ValueError, 'cannot scale/crop'): master_script.build(self.script, self.out, dry_run=True)
        result = master_script.build(self.script, self.out, native_canvas=True, dry_run=True)
        self.assertEqual((result['width'], result['height']), (26, 24))
        self.assertEqual(result['sequence']['canvas_policy'], 'native maximum')

    def test_trim_does_not_evade_prefix_pixel_or_frame_budget(self):
        path = self.edits(((2, 3), (2, 3)))
        with patch.object(master, 'MAX_PIXELS', 24 * 24 * 4), self.assertRaisesRegex(ValueError, 'prefix decoding'):
            master_script.build(self.script, self.out, edits=path, dry_run=True)
        self.data['shots'] = [dict(self.data['shots'][0], id=f'shot-{i}') for i in range(64)]; self.save()
        # 100 descriptors per GIF, only the final drawing selected, requires 6400 prefix decodes.
        gif(self.a, [(i, i, i) for i in range(100)], [10] * 100)
        path.unlink(); path = self.edits([(99, 100)] * 64)
        with self.assertRaisesRegex(ValueError, 'prefix decoding'): master_script.build(self.script, self.out, edits=path, dry_run=True)

    def test_script_source_hash_is_rechecked_before_master_snapshot(self):
        original = master.plan
        def mutate(*args, **kwargs):
            gif(self.a, ('white', 'black', 'orange'))
            return original(*args, **kwargs)
        with patch.object(master, 'plan', side_effect=mutate), self.assertRaisesRegex(ValueError, 'changed since script'):
            master_script.build(self.script, self.out, dry_run=True)

    def test_template_can_start_an_edit_whose_full_duration_exceeds_export_budget(self):
        with patch.object(master, 'MAX_DURATION_CS', 20):
            path = self.edits(((0, 1), (0, 1)))
            report = master_script.build(self.script, self.out, edits=path, dry_run=True)
        self.assertEqual(report['duration_cs'], 8)
        self.assertEqual(report['frame_count'], 2)

    def test_aggregate_import_bytes_are_checked_before_image_decode(self):
        limit = self.a.stat().st_size + self.b.stat().st_size - 1
        with patch.object(master, 'MAX_INPUT_BYTES', limit), \
                patch('PIL.Image.open', side_effect=AssertionError('No decode before budget')), \
                self.assertRaisesRegex(ValueError, 'encoded byte budget'):
            master_script.build(self.script, self.out, dry_run=True)
        self.assertFalse(self.out.exists())

    def test_script_snapshot_stays_authoritative_if_file_changes_during_source_read(self):
        raw = self.script.read_bytes(); read = cli.read_gif_bytes
        def mutate(*args, **kwargs):
            self.script.write_text('{}'); return read(*args, **kwargs)
        with patch.object(cli, 'read_gif_bytes', side_effect=mutate):
            result = master_script.build(self.script, self.out, dry_run=True)
        self.assertEqual(result['sequence']['script_sha256'], factory.digest(raw))
        self.assertEqual([s['id'] for s in result['sequence']['timeline']], ['a', 'b'])

    @unittest.skipUnless(av, 'PyAV required')
    def test_real_trim_preserves_exact_original_pixels_holds_and_srt(self):
        path = self.edits(); result = master_script.build(self.script, self.out, edits=path)
        self.assertEqual(result['verification']['frames'], 4)
        self.assertEqual(result['verification']['duration_ms'], 270)
        self.assertEqual([f['source_frame'] for f in result['frames']], [1, 2, 0, 1])
        self.assertEqual([f['pts_cs'] for f in result['frames']], [0, 2, 17, 24])
        originals = []
        for source, indices in ((self.a, (1, 2)), (self.b, (0, 1))):
            with Image.open(source) as image:
                for index in indices: image.seek(index); originals.append(image.convert('RGBA').tobytes())
        with av.open(str(self.out / 'master.mkv')) as container:
            self.assertEqual([master.rgba_frame(frame).tobytes() for frame in container.decode(video=0)], originals)
        self.assertEqual((self.out / 'captions.srt').read_text(), '1\n00:00:00,000 --> 00:00:00,170\nA\n\n2\n00:00:00,170 --> 00:00:00,270\nB\n')
        for name in ('timeline.json', 'captions.srt'):
            self.assertEqual(result['files'][name]['sha256'], master.file_sha(self.out / name))
        self.assertEqual(json.loads((self.out / 'timeline.json').read_text())['duration_ms'], 270)

    @unittest.skipUnless(av, 'PyAV required')
    def test_disposal_prefix_compositing_and_center_padding_keep_original_rgba(self):
        for disposal in (1, 2, 3):
            images = [Image.new('RGBA', (22, 20), (30, 40, 50, 0)) for _ in range(3)]
            for i, image in enumerate(images): image.putpixel((i + 5, 7), (255, 90, 0, 255))
            images[0].save(self.a, save_all=True, append_images=images[1:], duration=[10, 20, 150], disposal=disposal, transparency=0, optimize=False)
            self.data['shots'] = self.data['shots'][:1]; self.save()
            path = self.root / f'edits-{disposal}.json'; master_script.write_template(self.script, path)
            edits = json.loads(path.read_text()); edits['shots'][0]['in_frame'] = 2; path.write_text(json.dumps(edits))
            result = master_script.build(self.script, self.root / f'out-{disposal}', edits=path)
            with Image.open(self.a) as image:
                image.seek(2); expected = image.convert('RGBA').tobytes()
            self.assertEqual(result['frames'][0]['source_rgba_sha256'], factory.digest(expected))
            self.assertEqual(result['frames'][0]['roi'], [1, 2, 22, 20])
            self.assertEqual(result['frames'][0]['duration_cs'], 15)

    @unittest.skipUnless(av and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'PyAV and FFmpeg required')
    def test_real_preview_and_short_audio_follow_selected_duration(self):
        audio = self.root / 'short.wav'
        with wave.open(str(audio), 'wb') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(48000); f.writeframes(bytes(4800))
        self.data['audio'] = audio.name; self.save(); path = self.edits()
        with self.assertRaisesRegex(ValueError, 'request --preview'): master_script.build(self.script, self.out, edits=path, dry_run=True)
        result = master_script.build(self.script, self.out, edits=path, preview=True)
        self.assertEqual(result['viewing_copy']['frames'], 27)
        self.assertEqual(result['viewing_copy']['audio']['target_samples'], 12960)
        self.assertEqual(result['verification']['duration_ms'], 270)

    def test_cli_rejects_conflicting_inputs_and_template_render_options(self):
        bad = [(str(self.a), '--script', str(self.script)), ('--script', str(self.script), '--audio', str(self.a)),
               (str(self.a), '--edits', 'edit.json'), ('--script', str(self.script), '--write-edits', 'x.json', '--out', 'out')]
        for args in bad:
            with self.subTest(args=args), patch('sys.argv', ['gif-cinema', 'master', *args]), self.assertRaises(SystemExit): cli.main()

    def test_public_cli_dispatch_plans_script_and_writes_new_template(self):
        for args in (['--script', str(self.script), '--out', str(self.out), '--dry-run'],
                     ['--script', str(self.script), '--write-edits', str(self.root / 'cli-edit.json')]):
            text = io.StringIO()
            with patch('sys.argv', ['gif-cinema', 'master', *args]), redirect_stdout(text): cli.main()
            self.assertEqual(json.loads(text.getvalue())['provider_calls'], 0)

    @unittest.skipIf(__import__('os').name == 'nt', 'Windows symlink privileges vary')
    def test_symlinked_template_and_output_parent_are_rejected(self):
        real = self.root / 'real'; real.mkdir(); link = self.root / 'link'; link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(ValueError): master_script.write_template(self.script, link / 'edits.json')
        with self.assertRaises(ValueError): master_script.build(self.script, link / 'out', dry_run=True)

    @unittest.skipUnless(av, 'PyAV required')
    def test_publication_failure_leaves_no_partial_film_or_subtitles(self):
        publish = cli.publish_file
        def fail(staged, target, force=False):
            if target.name == 'timeline.json': raise OSError('injected')
            return publish(staged, target, force)
        with patch.object(cli, 'publish_file', side_effect=fail), self.assertRaises(OSError): master_script.build(self.script, self.out)
        self.assertFalse(self.out.exists())


if __name__ == '__main__': unittest.main()
