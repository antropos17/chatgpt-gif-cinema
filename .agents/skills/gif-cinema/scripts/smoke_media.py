"""Verify packaged review/sprite tools with synthetic drawings, no network and no FFmpeg."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch
import sys

# Keep the installed skill read-only even when the caller has not set an env flag.
sys.dont_write_bytecode = True

from PIL import Image, ImageDraw
from gif_cinema import cli
import check_install
import review_gif


def verify(condition, message):
    if not condition:
        raise ValueError(message)


def run(root):
    root = Path(root).resolve()
    skill = Path(__file__).resolve().parents[1]
    if root.is_relative_to(skill):
        raise ValueError('Smoke output belongs outside the installed skill directory')
    installation = {'package': check_install.verify_files(), 'runtime': check_install.check_runtime()}
    root.mkdir(parents=True, exist_ok=False)
    calls = []

    def command(*parts):
        parsed = cli.build_parser().parse_args(parts)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            parsed.func(parsed)
        calls.append(list(parts))
        return json.loads(buffer.getvalue())

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    frames = []
    for index in range(4):
        frame = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
        ImageDraw.Draw(frame).rectangle((4 + index * 2, 8, 12 + index * 2, 23), fill='#e49c3e')
        frames.append(frame)
    delays = [80, 120, 160, 240]
    source = root / 'synthetic.gif'
    frames[0].save(source, save_all=True, append_images=frames[1:], duration=delays,
                   loop=0, disposal=2, optimize=False)
    original_sha = sha(source)
    packed = root / 'packed'
    plan = command('sprites', 'pack', str(source), '--columns', '2', '--out', str(packed), '--dry-run')
    verify(not packed.exists(), 'Sprite dry-run wrote output')
    result = command('sprites', 'pack', str(source), '--columns', '2', '--out', str(packed))
    verify(plan['frame_layout'] == result['frame_layout'], 'Sprite layout changed after dry-run')
    verify(result['frame_count'] == 4 and result['duration_ms'] == 600, 'Incorrect sprite timing')
    verify(result['api_calls'] == 0 and result['preview']['durations_ms'] == delays, 'Preview timing or provider count changed')
    with Image.open(packed / 'atlas.png') as atlas:
        for row in result['frame_layout']:
            x, y, w, h = row['rect']
            with Image.open(packed / row['file']) as frame:
                verify(atlas.crop((x, y, x + w, y + h)).tobytes() == frame.tobytes(), 'Atlas pixels differ from PNG frame')
    spec = root / 'poses.json'
    spec.write_text(json.dumps({'schema_version': 1, 'atlas': 'packed/atlas.png',
                              'grid': [2, 2], 'duration_ms': delays, 'loop': 0,
                              'trim': True, 'scale': 2, 'columns': 4, 'require_margin': 1}), encoding='utf-8')
    sliced = root / 'sliced'
    command('sprites', 'slice', str(spec), '--out', str(sliced), '--dry-run')
    verify(not sliced.exists(), 'Slice dry-run wrote output')
    sliced_report = command('sprites', 'slice', str(spec), '--out', str(sliced))
    verify(sliced_report['frame_count'] == 4 and sliced_report['duration_ms'] == 600,
           'PNG grid slice lost drawings or timing')
    for label, gif in [('original', source), ('packed', packed / 'animation.gif'), ('sliced', sliced / 'animation.gif')]:
        review = root / f'review-{label}'
        audit = review_gif.extract(gif, review, focus=[2, 2, 20, 20],
                                   purpose='general' if label == 'sliced' else 'sticker')
        verify(audit['media']['technical_status'] == 'passed', f'{label} technical review failed')
        verify(audit['media']['durations_ms'] == delays, f'{label} review cadence changed')
        record = json.loads((review / 'review.json').read_text(encoding='utf-8'))
        verify(all(row['decision'] == 'pending' for row in record['frames']), 'Smoke test must not approve frames')
        verify(record['playback'] == record['loop_seam'] == record['user_acceptance'] == 'pending',
               'Smoke test must not approve playback or user acceptance')
        try:
            review_gif.check(review, gif=gif)
        except ValueError as error:
            verify('reviewer' in str(error).lower(), 'Pending review failed for an unexpected reason')
        else:
            raise ValueError('Unreviewed fixture was accepted')
    verify(sha(source) == original_sha, 'Source changed')
    report = {'status': 'passed', 'source': 'synthetic geometric fixtures', 'provider_calls': 0,
              'network': 'blocked in process', 'ffmpeg_required': False,
              'sources_unchanged': True, 'pack_and_slice_checked': True,
              'full_frame_review_checked': True, 'visual_review': 'pending', 'user_acceptance': 'pending',
              'scope': 'Technical behavior only. No new artwork, visual judgment or live provider test.',
              'installation': installation, 'commands': calls}
    (root / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    # A configured credential cannot turn a local test into a provider request.
    with patch('gif_cinema.cli.urlopen', side_effect=AssertionError('Network prohibited')), \
            patch('socket.socket', side_effect=AssertionError('Network prohibited')):
        report = run(args.out)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
