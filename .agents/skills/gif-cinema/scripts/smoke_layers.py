"""Render bundled stroke/GIF-layer scenes, reopen all frames and prepare pending reviews."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True

from gif_cinema import layers
import check_install
import review_gif
import verify_layers


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(root):
    root = Path(root).resolve()
    skill = Path(__file__).resolve().parents[1]
    if root.is_relative_to(skill):
        raise ValueError('Smoke output belongs outside the installed skill directory')
    if not all(shutil.which(tool) for tool in ('ffmpeg', 'ffprobe')):
        raise ValueError('FFmpeg and ffprobe are required for layer smoke; use smoke_media.py for a no-encoder check')
    installation = {'package': check_install.verify_files(), 'runtime': check_install.check_runtime()}
    sources = [skill / 'assets/example' / name for name in
               ('stroke-reveal.json', 'gif-layer.json', 'shot-01.gif')]
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in sources]
    plans = {}
    for label, source, count in [('strokes', sources[0], 200), ('gif-composition', sources[1], 160)]:
        plans[label] = layers.render_scene(source, root / f'plan-{label}', dry_run=True)
        require(plans[label]['api_calls'] == 0 and plans[label]['frames'] == count,
                f'{label} dry-run contract changed')
        require(not (root / f'plan-{label}').exists(), 'Dry-run created output')
    timing = plans['gif-composition']['gif_timing']['astronaut']
    require(timing['source_drawings'] == 16 and timing['source_delays_ms'] == [160] * 16,
            'Native GIF drawing cadence changed')
    require(timing['omitted_source_drawings'] == [], 'Example omitted a source drawing')
    root.mkdir(parents=True, exist_ok=False)
    cases = {}
    for label, source, count in [('strokes', sources[0], 200), ('gif-composition', sources[1], 160)]:
        output = root / label
        receipt = layers.render_scene(source, output)
        verified = verify_layers.verify(output)
        require(verified['frames_reopened_and_matched'] == count, f'Not every {label} frame reopened')
        require(verified['output_hashes_verified'] == len(receipt['outputs']), 'Output inventory incomplete')
        require(verified['loop_review']['status'] == 'human-review-required', 'Technical check approved visual quality')
        review = root / f'review-{label}'
        audit = review_gif.extract(output / 'preview.gif', review)
        require(audit['media']['technical_status'] == 'passed', f'{label} GIF is not reviewable')
        record = json.loads((review / 'review.json').read_text(encoding='utf-8'))
        require(all(frame['decision'] == 'pending' for frame in record['frames']), 'Frames were automatically accepted')
        require(record['playback'] == record['loop_seam'] == record['user_acceptance'] == 'pending',
                'Smoke test must not approve playback or user acceptance')
        cases[label] = {'frames_reopened_and_matched': count,
                        'output_hashes_verified': verified['output_hashes_verified'],
                        'visual_review': 'pending', 'user_acceptance': 'pending'}
    require(before == [hashlib.sha256(path.read_bytes()).hexdigest() for path in sources],
            'Bundled sources changed')
    report = {'status': 'passed', 'provider_calls': 0, 'network': 'blocked in Python process',
              'ffmpeg_required': True, 'source': 'original stroke geometry and existing astronaut GIF with local graphics',
              'sources_unchanged': True, 'stroke_render_checked': True,
              'frames_reopened_and_matched': cases['strokes']['frames_reopened_and_matched'],
              'output_hashes_verified': cases['strokes']['output_hashes_verified'],
              'gif_layers_checked': True, 'gif_timing': timing, 'cases': cases,
              'full_frame_review_checked': True, 'visual_review': 'pending',
              'user_acceptance': 'pending', 'installation': installation,
              'scope': 'Technical export and reopen behavior, not visual judgment or new action synthesis.'}
    (root / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    with patch('gif_cinema.cli.urlopen', side_effect=AssertionError('Network prohibited')), \
            patch('socket.socket', side_effect=AssertionError('Network prohibited')):
        report = run(args.out)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
