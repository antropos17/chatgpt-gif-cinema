"""Verify every saved frame against a reopened scene, with no network access."""
import argparse
import io
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from gif_cinema import layers


def expected_outputs(scene):
    """Derive the schema-1 export contract from the saved scene, not its receipt."""
    count = scene['duration_ms'] * scene['fps'] // 1000
    names = {'editable/scene.json', 'preview.gif', 'preview.mp4', 'contact-sheet.png',
             'first.png', 'last.png', 'closing-endpoint.png', 'loop-seam.png',
             'encoded-loop-seam.png'}
    names.update(f'frames/{index:04}.png' for index in range(count))
    names.update(f"layers/{layer['id']}.png" for layer in scene['layers'])
    names.update(layers.source_name(f"editable/{layer['source']}")
                 for layer in scene['layers'] if layer['type'] in ('image', 'gif', 'sprites'))
    return names


def unique_fields(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f'Duplicate receipt field: {name}')
        result[name] = value
    return result


def confined_path(directory, name):
    path = (directory / layers.source_name(name)).resolve()
    if not path.is_relative_to(directory):
        raise ValueError('Receipt path escapes output directory')
    return path


def verify(directory):
    directory = Path(directory).resolve()
    receipt = json.loads(layers.read_regular(confined_path(directory, 'receipt.json'),
                                           layers.MAX_RECEIPT_BYTES), object_pairs_hook=unique_fields)
    if not isinstance(receipt, dict):
        raise ValueError('Receipt must be an object')
    scene_path = confined_path(directory, 'editable/scene.json')
    scene = layers.parse_scene(layers.read_regular(scene_path, layers.MAX_SCENE_BYTES))
    count = scene['duration_ms'] * scene['fps'] // 1000
    if (type(receipt.get('frames')) is not int or receipt['frames'] != count
            or not isinstance(receipt.get('samples'), list) or len(receipt['samples']) != count):
        raise ValueError('Receipt frame count does not match saved scene')
    outputs = receipt.get('outputs')
    if not isinstance(outputs, dict) or len(outputs) > 1600:
        raise ValueError('Receipt outputs must be an object with at most 1600 entries')
    required = expected_outputs(scene)
    if set(outputs) != required:
        missing = sorted(required - set(outputs))
        unexpected = sorted(set(outputs) - required)
        raise ValueError(f'Receipt output inventory is incomplete or unexpected; '
                         f'missing: {missing}; unexpected: {unexpected}')
    for name, expected in outputs.items():
        if not isinstance(expected, str) or re.fullmatch(r'[0-9a-f]{64}', expected) is None:
            raise ValueError(f'Invalid SHA-256 in receipt: {name}')
        path = confined_path(directory, name)
        if layers.digest(layers.read_regular(path, 64 * 1024 * 1024)) != expected:
            raise ValueError(f'Export hash changed: {name}')
    prepared = layers.prepare_scene(scene_path)
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
            'output_hashes_verified': len(outputs), 'fps': scene['fps'],
            'duration_ms': scene['duration_ms'], 'loop_review': receipt['loop_review'],
            'scope': 'Complete schema-1 output inventory present and hash-matched; all timeline PNG pixels rerendered from portable saved scene. Media hashes do not replace visual review or authenticate an edited receipt.'}


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
