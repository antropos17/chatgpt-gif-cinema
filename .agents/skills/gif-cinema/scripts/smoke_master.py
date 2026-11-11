"""Verify the installed public lossless-master CLI offline with tiny synthetic media."""
import argparse
from contextlib import redirect_stdout
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import sys
from unittest.mock import patch
import wave

sys.dont_write_bytecode = True

from PIL import Image, ImageDraw
from gif_cinema import cli
import check_install


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def master_cli(*arguments):
    """Use the public parser and dispatcher, not the internal master builder."""
    output = io.StringIO()
    with patch.object(sys, 'argv', ['gif-cinema', 'master', *map(str, arguments)]), redirect_stdout(output):
        cli.main()
    return json.loads(output.getvalue())


def make_fixtures(root):
    drawings = []
    for index in range(3):
        drawing = Image.new('RGBA', (24, 24), (0, 0, 0, 0))
        ImageDraw.Draw(drawing).rectangle((2 + index * 5, 4, 7 + index * 5, 19),
                                         fill=((255, 0, 0), (0, 255, 0), (0, 0, 255))[index] + (255,))
        drawings.append(drawing)
    source, audio = root / 'source.gif', root / 'short.wav'
    drawings[0].save(source, save_all=True, append_images=drawings[1:],
                     duration=[10, 20, 150], disposal=2, loop=0, optimize=False)
    with wave.open(str(audio), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b''.join(struct.pack('<h', 4000 if i % 48 < 24 else -4000)
                                 for i in range(2400)))
    return source, audio


def rgba_bytes(frame):
    """Read PyAV's decoded padded plane independently of the master verifier."""
    rgba = frame.reformat(format='rgba')
    plane = rgba.planes[0]
    data = bytes(plane)
    return b''.join(data[y * plane.line_size:y * plane.line_size + rgba.width * 4]
                    for y in range(rgba.height))


def verify_export(output, source, audio, script, edits, receipt=None):
    """Verify this smoke's fixed fixture against reopened files and source pixels.

    This deliberately does not trust manifest hashes as the pixel/timing oracle.
    It is not a general verifier for arbitrary projects or untrusted manifests.
    """
    import av
    output, source, audio, script, edits = map(Path, (output, source, audio, script, edits))
    saved = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    if receipt is not None:
        require(saved == receipt, 'Saved manifest differs from CLI result')
    receipt = saved
    require({p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()} ==
            {'master.mkv', 'preview.mp4', 'manifest.json', 'captions.srt', 'timeline.json'}, 'Unexpected master output inventory')
    require(set(receipt['files']) == {'master.mkv', 'preview.mp4', 'captions.srt', 'timeline.json'},
            'Incorrect manifest file inventory')
    for name, facts in receipt['files'].items():
        require(facts == {'bytes': (output / name).stat().st_size, 'sha256': sha(output / name)},
                f'Output hash/size mismatch: {name}')
    require(receipt['status'] == 'verified-master' and type(receipt['provider_calls']) is int and receipt['provider_calls'] == 0 and
            receipt['visual_review'] == 'pending' and receipt['verification']['visual_review'] == 'pending',
            'Technical verification must leave visual acceptance pending')
    require(receipt['width'] == receipt['height'] == 24 and receipt['frame_count'] == 3 and
            receipt['duration_cs'] == 18 and len(receipt['frames']) == 3, 'Master dimensions/timing changed')
    require(len(receipt['sources']) == 2 and all(item['sha256'] == sha(source) for item in receipt['sources']),
            'Source identity changed')
    expected_timeline = []
    for index, (sid, start, stop, count, start_ms, end_ms, caption) in enumerate((
            ('first', 0, 2, 2, 0, 30, 'First two drawings.'),
            ('hold', 2, 3, 1, 30, 180, 'Final drawing hold.'))):
        item = receipt['sources'][index]
        require((item['index'], item['in_frame'], item['out_frame'], item['selected_frames'],
                 item['selected_duration_cs']) == (index, start, stop, count, (end_ms - start_ms) // 10),
                'Selected original drawing range changed')
        expected_timeline.append({'id': sid, 'source_index': index, 'source_sha256': sha(source),
                'in_frame': start, 'out_frame': stop, 'frames': count,
                'start_ms': start_ms, 'end_ms': end_ms, 'caption': caption})
    sequence = receipt['sequence']
    require(sequence['script_sha256'] == sha(script) and sequence['edits_sha256'] == sha(edits) and
            sequence['script_fps'] == 25 and sequence['requested_canvas'] == [24, 24] and
            sequence['timeline'] == expected_timeline,
            'Script/edit identity or exact timeline changed')
    require(json.loads((output / 'timeline.json').read_text(encoding='utf-8')) == {
                'format': 'gif-cinema-exact-timeline', 'schema_version': 1,
                'script_sha256': sha(script), 'duration_ms': 180, 'shots': expected_timeline},
            'Reopened timeline sidecar differs from exact selected ranges')
    expected_srt = ('1\n00:00:00,000 --> 00:00:00,030\nFirst two drawings.\n\n'
                    '2\n00:00:00,030 --> 00:00:00,180\nFinal drawing hold.\n').encode('utf-8')
    require((output / 'captions.srt').read_bytes() == expected_srt,
            'Reopened SRT must preserve exact 0/30/180ms cuts and LF bytes')
    expected = []
    with Image.open(source) as gif:
        require(gif.n_frames == 3 and gif.size == (24, 24), 'Fixture drawing count/size changed')
        for index, duration in enumerate((10, 20, 150)):
            gif.seek(index)
            require(gif.info.get('duration') == duration, 'Fixture delay changed')
            expected.append(gif.convert('RGBA').tobytes())
    with wave.open(str(audio), 'rb') as wav:
        require((wav.getnframes(), wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) ==
                (2400, 48000, 1, 2), 'Audio fixture must be 50ms mono 48k PCM')
    with av.open(str(output / 'master.mkv')) as container:
        require(len(container.streams) == 1 and container.streams.video[0].codec_context.name == 'ffv1',
                'Master must contain only FFV1 video')
        frames = list(container.decode(video=0))
        require(len(frames) == 3, 'Decoded master drawing count changed')
        for index, (frame, pts, duration) in enumerate(zip(frames, (0, 1, 3), (1, 2, 15))):
            raw = rgba_bytes(frame)
            digest = hashlib.sha256(raw).hexdigest()
            require((frame.width, frame.height) == (24, 24) and raw == expected[index],
                    f'Decoded RGBA differs from source drawing {index}')
            require(frame.pts is not None and frame.pts * frame.time_base == Fraction(pts, 100),
                    f'Decoded PTS mismatch at drawing {index}')
            require(frame.duration * frame.time_base == Fraction(duration, 100),
                    f'Decoded hold mismatch at drawing {index}')
            require(receipt['frames'][index] == {'index': index, 'source': 0 if index < 2 else 1, 'source_frame': index,
                    'pts_cs': pts, 'duration_cs': duration, 'roi': [0, 0, 24, 24],
                    'source_rgba_sha256': digest, 'canvas_rgba_sha256': digest},
                    f'Manifest pixel/timing trace mismatch at drawing {index}')
        require((frames[-1].pts + frames[-1].duration) * frames[-1].time_base == Fraction(18, 100),
                'Final 150ms hold missing')
    viewing = receipt['viewing_copy']
    require(viewing['frames'] == 18 and viewing['fps'] == 100 and viewing['duration_ms'] == 180,
            'Viewing copy timing changed')
    require(viewing['audio']['source_sha256'] == sha(audio) and
            viewing['audio']['target_samples'] == 8640 and viewing['audio']['sample_rate'] == 48000 and
            receipt['audio_validation'] == 'decoded-and-timed', 'Audio target/source mismatch')
    with av.open(str(output / 'preview.mp4')) as container:
        require(len(container.streams.video) == len(container.streams.audio) == 1,
                'Preview must contain video and audio')
        video, sound = container.streams.video[0], container.streams.audio[0]
        require(video.codec_context.name == 'h264' and sound.codec_context.name == 'aac' and
                sound.codec_context.sample_rate == 48000, 'Preview codecs/rate changed')
        require(sound.start_time == 0 and sound.duration is not None and
                abs(sound.duration * sound.time_base - Fraction(8640, 48000)) <= Fraction(22, 1000),
                'Preview audio duration differs from target (allowing AAC padding)')
        frames = list(container.decode(video=0))
        require(len(frames) == 18, 'Preview must decode to 18 repeated-drawing frames')
        for index, frame in enumerate(frames):
            require((frame.width, frame.height) == (24, 24) and
                    frame.pts * frame.time_base == Fraction(index, 100) and
                    frame.duration * frame.time_base == Fraction(1, 100),
                    f'Preview frame timing/dimensions changed at {index}')
    with av.open(str(output / 'preview.mp4')) as container:
        samples = sum(frame.samples for frame in container.decode(audio=0))
        require(8640 <= samples <= 8640 + 1024, 'Decoded AAC sample count exceeds codec-padding allowance')
    return {'frames_reopened_and_matched': 3, 'pts_cs': [0, 1, 3], 'durations_ms': [10, 20, 150],
            'duration_ms': 180, 'final_hold_ms': 150, 'preview_frames': 18,
            'audio_target_samples': 8640, 'decoded_aac_samples': samples,
            'output_hashes_verified': 4, 'script_ranges': [[0, 2], [2, 3]],
            'caption_ranges_ms': [[0, 30], [30, 180]], 'script_edit_checked': True,
            'visual_review': 'pending', 'user_acceptance': 'pending'}


def run(root):
    with patch('gif_cinema.cli.urlopen', side_effect=AssertionError('Network prohibited')), \
            patch('urllib.request.urlopen', side_effect=AssertionError('Network prohibited')), \
            patch('socket.socket', side_effect=AssertionError('Network prohibited')):
        return run_offline(root)


def run_offline(root):
    root = Path(root).resolve()
    skill = Path(__file__).resolve().parents[1]
    require(not root.is_relative_to(skill), 'Smoke output belongs outside the installed skill directory')
    require(not root.exists(), 'Smoke output must be a new directory')
    require(all(shutil.which(tool) for tool in ('ffmpeg', 'ffprobe')),
            'FFmpeg and ffprobe are required for master preview smoke; use smoke_media.py for a no-encoder check')
    installation = {'package': check_install.verify_files(),
                    'runtime': check_install.check_runtime(require_master=True)}
    # All dependency checks precede creation of the output root or any fixtures.
    root.mkdir(parents=True, exist_ok=False)
    source, audio = make_fixtures(root)
    script, edits = root / 'film.json', root / 'edits.json'
    script.write_text(json.dumps({'schema_version': 1, 'title': 'Exact selected native drawings',
        'style_bible': 'Synthetic technical fixture, not artwork.', 'ratio': '1:1',
        'width': 24, 'height': 24, 'fps': 25, 'audio': audio.name,
        'shots': [{'id': sid, 'source': source.name, 'first_frame_target': 'Original drawing.',
                   'last_frame_target': 'Original drawing.', 'caption': caption}
                  for sid, caption in (('first', 'First two drawings.'), ('hold', 'Final drawing hold.'))]}),
        encoding='utf-8')
    template_result = master_cli('--script', script, '--write-edits', edits)
    require(template_result['status'] == 'edit-template-written' and
            type(template_result['provider_calls']) is int and template_result['provider_calls'] == 0 and
            template_result['sha256'] == sha(edits), 'Public edit template was not written with zero calls')
    template = json.loads(edits.read_text(encoding='utf-8'))
    require(template == {'format': 'gif-cinema-exact-edit', 'schema_version': 1,
            'script_sha256': sha(script), 'shots': [
                {'id': sid, 'source_sha256': sha(source), 'in_frame': 0, 'out_frame': 3}
                for sid in ('first', 'hold')]}, 'Template must hash-pin script and both full source ranges')
    template['shots'][0]['out_frame'] = 2
    template['shots'][1]['in_frame'] = 2
    edits.write_text(json.dumps(template), encoding='utf-8')
    before = tuple(sha(path) for path in (source, audio, script, edits))
    planned_output = root / 'planned-only'
    plan = master_cli(source, '--out', planned_output, '--preview', '--audio', audio, '--dry-run')
    require(not planned_output.exists() and plan['status'] == 'planned' and
            type(plan['provider_calls']) is int and plan['provider_calls'] == 0 and
            plan['frame_count'] == 3 and plan['duration_cs'] == 18 and plan['audio_validation'] == 'pending',
            'Dry-run wrote output or returned an incorrect plan')
    # Only one real export: the script ranges collectively retain the same three drawings.
    selected_plan = master_cli('--script', script, '--edits', edits, '--out', planned_output, '--preview', '--dry-run')
    require(not planned_output.exists() and selected_plan['status'] == 'planned' and
            type(selected_plan['provider_calls']) is int and selected_plan['provider_calls'] == 0 and
            selected_plan['frame_count'] == 3 and selected_plan['duration_cs'] == 18 and
            selected_plan['audio_validation'] == 'pending' and
            [(shot['start_ms'], shot['end_ms']) for shot in selected_plan['sequence']['timeline']] == [(0, 30), (30, 180)],
            'Script dry-run wrote output or changed selected native timing')
    output = root / 'master'
    receipt = master_cli('--script', script, '--edits', edits, '--out', output, '--preview')
    checks = verify_export(output, source, audio, script, edits, receipt)
    require(before == tuple(sha(path) for path in (source, audio, script, edits)), 'Input GIF/audio/script/edits changed')
    report = {'status': 'passed', 'provider_calls': 0, 'network': 'blocked in Python process',
              'cli_entrypoint_checked': True, 'dry_run_checked': True, 'sources_unchanged': True,
              'source': 'synthetic three-drawing 24x24 GIF and 50ms 48kHz PCM audio',
              'installation': installation, **checks,
              'scope': 'Technical pixel/timing and export verification only; no artistic or continuity acceptance.'}
    (root / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.out), indent=2))


if __name__ == '__main__':
    main()
