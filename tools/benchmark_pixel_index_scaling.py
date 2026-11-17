#!/usr/bin/env python3
"""Measure verified palette encoding without dropping any validation.

Baseline: git show 5d26cd:gif_cinema/pixel_palette.py > BEFORE.py
Only that exact known source blob is executable. Timings are observations, not
performance assertions. Source GIF, frame pixels, delays, loop and GIF bytes must
remain identical; both implementations independently verify their encoded output.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time
import types
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, __version__ as pillow_version
from gif_cinema import pixel, pixel_palette as pp

BASELINE_BLOB = 'f5400e257c36eea6b2704b8eea90cb65b655a3df'


def baseline(path):
    raw = pixel.layers.read_regular(pixel.local_path(path), 64*1024)
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != BASELINE_BLOB:
        raise ValueError('Expected the exact pixel_palette.py from 5d26cd')
    module = types.ModuleType('gif_cinema._baseline_pixel_palette')
    module.__package__ = 'gif_cinema'
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def verify_gif(raw, source, scale):
    decoded = pp.decode(raw)
    if decoded['delays_ms'] != source['delays_ms'] or decoded['loop'] != source['loop']:
        raise AssertionError('Encoded frame holds/count or loop differ')
    hashes = []
    for original, actual in zip(source['frames'], decoded['frames']):
        expected = pp.canonical_rgba(original).resize((original.width*scale, original.height*scale), Image.Resampling.NEAREST)
        if actual.size != expected.size or actual.tobytes() != expected.tobytes():
            raise AssertionError('Decoded RGBA pixels differ')
        hashes.append(hashlib.sha256(actual.tobytes()).hexdigest())
    return {'frames': len(hashes), 'rgba_sha256': hashes, 'delays_ms': decoded['delays_ms'],
            'duration_ms': sum(decoded['delays_ms']), 'loop': decoded['loop'],
            'pixel_mismatches': 0, 'delay_mismatches': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('--baseline-source', required=True)
    parser.add_argument('--out', required=True, help='New report/output directory')
    parser.add_argument('--scales', nargs='+', type=int, default=[1, 2])
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--build-repeats', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10 or not 0 <= args.build_repeats <= 5:
        parser.error('Require 1..10 encoding repeats and 0..5 full-build repeats')
    if len(args.scales) != len(set(args.scales)) or not args.scales:
        parser.error('Scales must be distinct')
    reference = baseline(args.baseline_source)
    candidate = pp.encode
    source_path = pixel.local_path(args.source)
    source_raw = pixel.layers.read_regular(source_path, pp.MAX_BYTES)
    # Preserve normal scale/pixel/format preflight before any output allocation.
    for scale in args.scales:
        source = pp.decode(source_raw, scale)
    plan = pp.choose_palette(source['frames'])
    out = Path(args.out).absolute(); out.mkdir(parents=True, exist_ok=False)
    report = {'baseline_commit': '5d26cd72a61c783d1d04fdf77c64bde153849b47',
              'baseline_codec_git_blob': BASELINE_BLOB,
              'candidate_codec_sha256': hashlib.sha256(Path(pp.__file__).read_bytes()).hexdigest(),
              'source_sha256': hashlib.sha256(source_raw).hexdigest(),
              'python': platform.python_version(), 'pillow': pillow_version,
              'platform': platform.platform(), 'source_size': list(source['size']),
              'provider_calls': 0, 'audio': 'not applicable: GIF has no audio', 'scales': {}}
    for scale in args.scales:
        runs = {'before': [], 'after': []}; builds = {'before': [], 'after': []}
        directory = out/str(scale); directory.mkdir()
        expected = None
        for run in range(args.repeats):
            variants = [('before', reference.encode), ('after', candidate)]
            if run % 2:
                variants.reverse()
            for name, encode in variants:
                path = directory/f'{name}-{run+1}.gif'
                started = time.perf_counter()
                encode(source['frames'], source['delays_ms'], source['loop'], plan, path, scale)
                runs[name].append(time.perf_counter()-started)
                raw = path.read_bytes()
                if expected is None:
                    expected = raw
                if raw != expected:
                    raise AssertionError('Encoded GIF bytes differ')
                print(json.dumps({'scale': scale, 'run': run+1, 'variant': name, 'encode_seconds': runs[name][-1]}), flush=True)
        checked = verify_gif(expected, source, scale)
        for run in range(args.build_repeats):
            variants = [('before', reference.encode), ('after', candidate)]
            if run % 2:
                variants.reverse()
            for name, encode in variants:
                target = directory/f'{name}-build-{run+1}'
                started = time.perf_counter()
                with patch.object(pp, 'encode', encode):
                    pixel.build(source_path, target, scale)
                builds[name].append(time.perf_counter()-started)
                pixel.verify(target)  # Extra external verification is outside the timed build.
                if (target/'preview.gif').read_bytes() != expected or (target/'source.gif').read_bytes() != source_raw:
                    raise AssertionError('Complete build changed GIF or original source bytes')
                print(json.dumps({'scale': scale, 'full_build_run': run+1, 'variant': name, 'seconds': builds[name][-1]}), flush=True)
        report['scales'][str(scale)] = {'encode_seconds': runs,
            'encode_median_seconds': {name: statistics.median(values) for name, values in runs.items()},
            'build_seconds': builds,
            'build_median_seconds': {name: statistics.median(values) for name, values in builds.items()} if args.build_repeats else None,
            'output_bytes': len(expected), 'output_sha256': hashlib.sha256(expected).hexdigest(),
            'decoded_check': checked}
    if pixel.layers.read_regular(source_path, pp.MAX_BYTES) != source_raw:
        raise AssertionError('Source changed')
    report['source_unchanged'] = True
    report['timing_scope'] = 'Encode includes all original self-validation; full build includes normal PNG/export/verification/publication. Extra post-build verify is outside timing.'
    (out/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'report': str(out/'report.json'), 'source_unchanged': True}), flush=True)


if __name__ == '__main__':
    main()
