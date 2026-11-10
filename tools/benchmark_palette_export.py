"""Offline encoder comparison on an original diagnostic and existing local graphics.

python tools/benchmark_palette_export.py --out output/palette-comparison

Reports decoded RGB error, timing and size, not aesthetic quality. No network,
generation, downloaded media, interpolation or third-party artwork is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import PIL
from PIL import Image, ImageChops, ImageDraw, ImageSequence, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gif_cinema import layers, motion


def gradient_frames():
    base = Image.new('RGB', (512, 256))
    base.putdata([(x // 2,) * 3 for _ in range(256) for x in range(512)])
    frames = []
    for index in range(40):
        frame = base.copy()
        ImageDraw.Draw(frame).ellipse((4 + index * 9, 100, 44 + index * 9, 140), fill=(255, 32, 80))
        frames.append(frame)
    return frames, 25


def shapes_frames():
    prepared = layers.prepare_scene(ROOT / 'examples' / 'layered-shapes.json')
    scene = prepared['scene']
    frames = [motion.flatten(layers.render_at(prepared, index * 1000 // scene['fps'])[0], scene['matte'])
              for index in range(scene['duration_ms'] * scene['fps'] // 1000)]
    return frames, scene['fps']


def baseline_quantize(frame, palette):
    """Reproduce the old 68cef9d selection, including its exact low-color route."""
    values = palette.getpalette()
    members = {tuple(values[index:index + 3]) for index in range(0, len(values), 3)}
    colors = frame.getcolors(256)
    if colors is not None and all(color in members for _, color in colors):
        return motion.quantize_shared(frame, palette)
    return frame.quantize(palette=palette, dither=Image.Dither.NONE)


def metrics(path, sources, fps):
    step = 1000 // fps
    source_index, total_error, decoded_count, durations, pixels = 0, 0.0, 0, [], []
    with Image.open(path) as gif:
        loop = gif.info.get('loop')
        for encoded in ImageSequence.Iterator(gif):
            rgb = encoded.convert('RGB')
            delay = encoded.info['duration']
            if delay % step:
                raise ValueError('Encoded delay is not aligned to the source cadence')
            for _ in range(delay // step):
                source = sources[source_index]
                if rgb.size != source.size:
                    raise ValueError('Encoded dimensions changed')
                stats = ImageStat.Stat(ImageChops.difference(rgb, source))
                total_error += sum(value * value for value in stats.rms) / 3
                pixels.append(hashlib.sha256(rgb.tobytes()).hexdigest())
                source_index += 1
            decoded_count += 1
            durations.append(delay)
        gif.seek(0)
        first = gif.convert('RGB').copy()
    if source_index != len(sources) or loop != 0:
        raise ValueError('Encoded timeline or loop policy changed')
    return {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'rgb_mse': total_error / len(sources), 'encoded_drawings': decoded_count,
            'duration_ms': sum(durations), 'delays_ms': durations, 'loop': loop,
            'decoded_timeline_sha256': hashlib.sha256(''.join(pixels).encode('ascii')).hexdigest()}, first


def run(command):
    subprocess.run(command, check=True, capture_output=True, timeout=300)


def benchmark(name, frames, fps, root):
    output = root / name; output.mkdir()
    inputs = output / 'frames'; inputs.mkdir()
    samples = Image.new('RGB', (256, len(frames)))
    for index, frame in enumerate(frames):
        frame.save(inputs / f'{index:04}.png')
        samples.paste(motion.palette_row(frame), (0, index))
    palette = samples.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    results, images = {}, {}
    for method in ('before', 'exact-colors-only', 'after'):
        started = time.monotonic()
        quantizer = baseline_quantize if method == 'before' else motion.quantize_shared
        indexed = [quantizer(frame, palette) for frame in frames]
        options = {'palette': palette.getpalette()} if method == 'after' else {}
        path = output / f'{method}.gif'
        delay = 1000 // fps if method == 'before' else [1000 // fps] * len(indexed)
        indexed[0].save(path, save_all=True, append_images=indexed[1:], duration=delay,
                        loop=0, optimize=False, disposal=1, **options)
        seconds = time.monotonic() - started
        results[method], images[method] = metrics(path, frames, fps)
        results[method]['encode_seconds'] = seconds
    if results['after']['decoded_timeline_sha256'] != results['exact-colors-only']['decoded_timeline_sha256']:
        raise ValueError('Global color table changed decoded pixels')
    # Independent FFmpeg comparison. Different palettes/dither are reported, not
    # claimed to be equivalent or adopted as a new runtime default.
    common = ['ffmpeg', '-v', 'error', '-nostdin', '-threads', '1', '-filter_threads', '1',
              '-framerate', str(fps), '-i', str(inputs / '%04d.png')]
    ff_palette = output / 'ffmpeg-palette.png'
    run(common + ['-vf', 'palettegen=stats_mode=full:reserve_transparent=0', '-frames:v', '1', str(ff_palette)])
    for method, dither in (('ffmpeg-none', 'none'), ('ffmpeg-bayer', 'bayer:bayer_scale=2')):
        started = time.monotonic()
        path = output / f'{method}.gif'
        run(common + ['-i', str(ff_palette), '-filter_complex_threads', '1', '-lavfi',
                      f'[0:v][1:v]paletteuse=dither={dither}:diff_mode=rectangle',
                      '-loop', '0', '-frames:v', str(len(frames)), str(path)])
        results[method], images[method] = metrics(path, frames, fps)
        results[method]['encode_seconds_excluding_palette_pass'] = time.monotonic() - started
    if name == 'gradient-accent':
        for method, image in images.items():
            results[method]['exact_gray_levels_of_256'] = sum(image.getpixel((level * 2, 0)) == (level,) * 3
                                                           for level in range(256))
        # Show final decoded pixels at native size. This is a diagnostic, not art.
        sheet = Image.new('RGB', (512 * 3, 300), '#181818')
        for column, (label, image) in enumerate((('Full-color source', frames[0]),
                                                ('Before: decoded GIF', images['before']),
                                                ('After: decoded GIF', images['after']))):
            sheet.paste(image, (column * 512, 44))
            ImageDraw.Draw(sheet).text((column * 512 + 12, 15), label, fill='white')
        sheet.save(output / 'comparison.png')
    return {'width': frames[0].width, 'height': frames[0].height, 'fps': fps,
            'source_frames': len(frames),
            'source_timeline_sha256': hashlib.sha256(''.join(
                hashlib.sha256(frame.tobytes()).hexdigest() for frame in frames).encode('ascii')).hexdigest(),
            'methods': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.absolute()
    if out.exists() or any(path.is_symlink() for path in (out, *out.parents)):
        raise ValueError('Output must be a new directory without symlinks')
    out.mkdir(parents=True, exist_ok=False)
    report = {'api_calls': 0, 'baseline_commit': '68cef9dee782632d33216a4f6c5821b207e66366',
              'python': platform.python_version(), 'pillow': PIL.__version__,
              'ffmpeg': subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True,
                                       check=True, timeout=30).stdout.splitlines()[0],
              'review': 'Technical diagnostics only; no user or general artwork-quality acceptance.',
              'cases': {}}
    for name, factory in (('gradient-accent', gradient_frames), ('layered-shapes', shapes_frames)):
        frames, fps = factory()
        report['cases'][name] = benchmark(name, frames, fps, out)
    (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
