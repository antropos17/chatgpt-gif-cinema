"""Exercise existing-image motion, reopen every output frame and leave reviews pending."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True

from PIL import Image, ImageSequence
from gif_cinema import cli, motion
import check_install
import review_gif


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def motion_cli(*arguments):
    """Exercise the public parser/dispatcher inside this process's network block."""
    output = io.StringIO()
    with patch.object(sys, 'argv', ['gif-cinema', 'motion', *map(str, arguments)]), redirect_stdout(output):
        cli.main()
    return json.loads(output.getvalue())


def check_export(output, source, receipt, expected_count, expected_duration):
    """Check this smoke's fresh export, not arbitrary untrusted project receipts."""
    require(json.loads((output / 'receipt.json').read_text(encoding='utf-8')) == receipt,
            'Saved receipt differs from the render result')
    outputs = {'take.gif', 'review.mp4', 'first.png', 'last.png',
               'contact-sheet.png', 'loop-seam.png', 'recipe.json'}
    require(set(receipt['outputs']) == outputs, 'Motion output inventory incomplete or unexpected')
    require({p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()} ==
            outputs | {'receipt.json'} | {f'frames/{i:04d}.png' for i in range(expected_count)},
            'Actual motion files incomplete or unexpected')
    for name in outputs:
        require(sha(output / name) == receipt['outputs'][name], f'Output hash mismatch: {name}')
    require(receipt['source_sha256'] == sha(source), 'Source hash mismatch')
    require(receipt['status'] == receipt['loop_review']['status'] == 'human-review-required',
            'Technical export must not approve visual quality')
    config = receipt['recipe']
    frames, delays, _ = motion.decode_source(source.read_bytes(), config['still_duration_ms'])
    timeline = motion.build_timeline(delays, config)
    require(timeline == receipt['timeline'], 'Timeline differs from decoded source and recipe')
    require(timeline['playback_frames'] == len(receipt['samples']) == expected_count,
            'Playback frame count changed')
    require(timeline['output_duration_ms'] == expected_duration, 'Output duration changed')
    for index, sample in enumerate(receipt['samples']):
        source_index = motion.sample_timeline(timeline, index)
        transform = motion.evaluate_keyframes(config['keyframes'], index / (expected_count - 1))
        require(sample['frame'] == index and sample['time_ms'] == index * (1000 // config['fps'])
                and sample['source_index'] == source_index and sample['transform'] == transform,
                f'Incorrect source/transform trace at frame {index}')
        path = output / 'frames' / f'{index:04d}.png'
        require(sha(path) == sample['png_sha256'], f'PNG hash mismatch at frame {index}')
        with Image.open(path) as image:
            require(image.mode == 'RGBA' and image.size == (config['width'], config['height']),
                    f'PNG mode/size changed at frame {index}')
            actual = image.tobytes()
        expected = motion.render_frame(frames[source_index], config, transform).tobytes()
        require(actual == expected and hashlib.sha256(actual).hexdigest() == sample['rgba_sha256'],
                f'Reopened frame pixels differ at frame {index}')
    with Image.open(output / 'take.gif') as gif:
        require(gif.info.get('loop') == 0, 'Pinned motion delivery must declare infinite GIF looping')
        encoded_delays = [frame.info.get('duration', 0) for frame in ImageSequence.Iterator(gif)]
    require(sum(encoded_delays) == expected_duration and encoded_delays == receipt['candidate_delays_ms'],
            'Encoded GIF duration differs from timeline')
    return {'frames_reopened_and_matched': expected_count, 'output_hashes_verified': len(outputs),
            'duration_ms': expected_duration, 'encoded_gif_drawings': len(encoded_delays),
            'gif_loop': 'infinite', 'visual_review': 'pending', 'user_acceptance': 'pending'}


def run(root):
    root = Path(root).resolve()
    skill = Path(__file__).resolve().parents[1]
    if root.is_relative_to(skill):
        raise ValueError('Smoke output belongs outside the installed skill directory')
    if not all(shutil.which(tool) for tool in ('ffmpeg', 'ffprobe')):
        raise ValueError('FFmpeg and ffprobe are required for motion smoke; use smoke_media.py for a no-encoder check')
    installation = {'package': check_install.verify_files(), 'runtime': check_install.check_runtime()}
    source = skill / 'assets/example/shot-01.gif'
    recipe_path = skill / 'assets/example/motion-loop.json'
    before = [sha(source), sha(recipe_path)]
    recipe = motion.load_recipe(recipe_path)
    plans = {}
    for preset in ('identity', 'push-in', 'pan-left', 'pop-in'):
        plan_output = root / f'plan-{preset}'
        plan = motion_cli(source, '--out', plan_output, '--preset', preset, '--dry-run')
        require(not plan_output.exists() and plan['api_calls'] == 0, 'Dry-run wrote output or used a provider')
        require(plan['timeline']['playback_frames'] == 64 and plan['source_drawings'] == 16,
                'Bundled source/preset plan changed')
        plans[preset] = {'frames': 64, 'duration_ms': plan['timeline']['output_duration_ms']}
    root.mkdir(parents=True, exist_ok=False)
    # Reuse a source drawing as the still fixture; do not create or claim new artwork.
    still = root / 'astronaut-first.png'
    with Image.open(source) as image:
        image.convert('RGBA').save(still)
    cases = {}
    for label, input_path, options, count, duration in (
            ('gif-push-in', source, ['--preset', 'push-in'], 64, 2560),
            ('still-pop-in', still, ['--preset', 'pop-in'], 50, 2000),
            ('returning-camera', source, ['--recipe', recipe_path], 120, 4800)):
        input_hash = sha(input_path)
        output = root / label
        summary = motion_cli(input_path, '--out', output, *options)
        require(summary['api_calls'] == 0 and summary['status'] == 'human-review-required'
                and summary['playback_frames'] == count and summary['duration_ms'] == duration,
                'Motion CLI summary differs from the expected export')
        receipt = json.loads((output / 'receipt.json').read_text(encoding='utf-8'))
        if label == 'returning-camera':
            require(receipt['recipe'] == motion.normalize_recipe(recipe, (512, 512)),
                    'CLI recipe option did not use the installed example')
        cases[label] = check_export(output, input_path, receipt, count, duration)
        review = root / f'review-{label}'
        audit = review_gif.extract(output / 'take.gif', review)
        require(audit['media']['technical_status'] == 'passed', f'{label} GIF is not reviewable')
        record = json.loads((review / 'review.json').read_text(encoding='utf-8'))
        require(all(frame['decision'] == 'pending' for frame in record['frames']) and
                record['playback'] == record['loop_seam'] == record['user_acceptance'] == 'pending',
                'Motion smoke must not approve frames, playback or user acceptance')
        require(sha(input_path) == input_hash, 'Input changed during motion export')
    require(before == [sha(source), sha(recipe_path)], 'Bundled input or recipe changed')
    report = {'status': 'passed', 'provider_calls': 0, 'network': 'blocked in Python process',
              'ffmpeg_required': True, 'cli_entrypoint_checked': True,
              'source': 'existing astronaut GIF and its first drawing',
              'sources_unchanged': True, 'presets': plans, 'cases': cases,
              'frames_reopened_and_matched': sum(case['frames_reopened_and_matched'] for case in cases.values()),
              'output_hashes_verified': sum(case['output_hashes_verified'] for case in cases.values()),
              'visual_review': 'pending', 'user_acceptance': 'pending', 'installation': installation,
              'scope': 'Technical export and deterministic rerender checks; no new poses, seamlessness or artistic acceptance.'}
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
