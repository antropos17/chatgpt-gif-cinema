"""Verify every saved frame against a reopened scene, with no network access."""
import argparse
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from gif_cinema import layers, motion


def verify(directory):
    directory = Path(directory).resolve()
    receipt = json.loads(layers.read_regular(directory / 'receipt.json', layers.MAX_RECEIPT_BYTES))
    prepared = layers.prepare_scene(directory / 'editable' / 'scene.json')
    scene = prepared['scene']
    count = scene['duration_ms'] * scene['fps'] // 1000
    if receipt['frames'] != count or len(receipt['samples']) != count:
        raise ValueError('Receipt frame count does not match saved scene')
    hashes_verified = 0
    if len(receipt['outputs']) > 1600:
        raise ValueError('Receipt has too many outputs')
    for name, expected in receipt['outputs'].items():
        path = (directory / layers.source_name(name)).resolve()
        if not path.is_relative_to(directory):
            raise ValueError('Receipt path escapes output directory')
        if layers.digest(layers.read_regular(path, 64 * 1024 * 1024)) != expected:
            raise ValueError(f'Export hash changed: {name}')
        hashes_verified += 1
    for index, sample in enumerate(receipt['samples']):
        timestamp = index * (1000 // scene['fps'])
        if sample['frame'] != index or sample['time_ms'] != timestamp:
            raise ValueError('Receipt has a nonuniform or reordered timeline')
        actual, _ = layers.render_at(prepared, timestamp)
        if layers.digest(actual.tobytes()) != sample['rgba_sha256']:
            raise ValueError(f'Reopened scene differs at frame {index}')
        raw = layers.read_regular(directory / 'frames' / f'{index:04}.png', 16 * 1024 * 1024)
        with Image.open(io.BytesIO(raw)) as saved:
            if saved.mode != 'RGBA' or saved.size != actual.size or saved.tobytes() != actual.tobytes():
                raise ValueError(f'Saved PNG differs at frame {index}')
    return {'status': 'verified', 'api_calls': 0, 'frames_reopened_and_matched': count,
            'output_hashes_verified': hashes_verified, 'fps': scene['fps'],
            'duration_ms': scene['duration_ms'], 'loop_review': receipt['loop_review'],
            'scope': 'All exported PNG pixels rerendered from portable saved scene; all receipt output hashes matched.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = verify(args.directory)
    text = json.dumps(result, indent=2) + '\n'
    if args.report:
        with args.report.open('x', encoding='utf-8') as handle:
            handle.write(text)
    print(text)


if __name__ == '__main__':
    main()
