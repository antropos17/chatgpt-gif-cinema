"""Render the four original preset GIFs through GIF Cinema's actual layer engine.

Pillow-only gallery builder: no FFmpeg, providers, mock images or remote assets.
Run from the repository root with ``python tools/build_motion_presets.py --out
NEW_DIRECTORY``. Outputs are new; scene JSON is editable by the public compositor.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gif_cinema import layers, motion, presets, text_fonts


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(out):
    import PIL
    from PIL import Image, ImageDraw, ImageSequence
    out = Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Gallery output must be a new directory without symlinks')
    # All four scenes must fit before claiming the destination.
    scenes = {name: presets.make_scene(name) for name in presets.NAMES}
    out.mkdir(parents=True, exist_ok=False)
    records = {}
    overview = Image.new('RGB', (960, 640), '#151824')
    for position, (name, scene) in enumerate(scenes.items()):
        folder = out / name
        folder.mkdir()
        scene_path = folder / 'scene.json'
        scene_path.write_bytes(layers.serialize_scene(scene))
        prepared = layers.prepare_scene(scene_path)
        count, step = scene['duration_ms'] * scene['fps'] // 1000, 1000 // scene['fps']
        frames = [motion.flatten(layers.render_at(prepared, index * step)[0], scene['matte'])
                  for index in range(count)]
        palette_rows = Image.new('RGB', (256, count))
        for index, frame in enumerate(frames):
            palette_rows.paste(motion.palette_row(frame), (0, index))
        palette = palette_rows.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        indexed = [motion.quantize_shared(frame, palette) for frame in frames]
        gif = folder / 'preview.gif'
        indexed[0].save(gif, save_all=True, append_images=indexed[1:], duration=step,
                        loop=0, optimize=False, disposal=1)
        with Image.open(gif) as source:
            repeat = source.info.get('loop')
            decoded, delays = [], []
            for frame in ImageSequence.Iterator(source):
                decoded.append(frame.convert('RGB').copy())
                delays.append(frame.info['duration'])
        if sum(delays) != scene['duration_ms'] or repeat != 0:
            raise ValueError('Encoded GIF has incorrect timing or loop behavior')
        # Samples follow the actual decoded GIF delays, including merged holds.
        def at_time(timestamp):
            elapsed = 0
            for frame, delay in zip(decoded, delays):
                elapsed += delay
                if timestamp < elapsed:
                    return frame
            return decoded[-1]
        sample_times = [0, 480, 960, 1600, 2400, 3160]
        contact = Image.new('RGB', (480 * 3, 344 * 2), '#151824')
        draw = ImageDraw.Draw(contact)
        for i, timestamp in enumerate(sample_times):
            x, y = i % 3 * 480, i // 3 * 344
            contact.paste(at_time(timestamp), (x, y))
            draw.text((x + 10, y + 323), f'{timestamp} ms / decoded GIF', fill='white')
        contact.save(folder / 'decoded-phases.png')
        overview.paste(at_time(1600), (position % 2 * 480, position // 2 * 320))
        closing = motion.flatten(layers.render_at(prepared, scene['duration_ms'])[0], scene['matte'])
        records[name] = {'scene': name + '/scene.json', 'gif': name + '/preview.gif',
            'gif_sha256': sha(gif), 'scene_sha256': sha(scene_path), 'width': 480, 'height': 320,
            'fps': scene['fps'], 'duration_ms': sum(delays), 'sampled_frames': count,
            'gif_drawings': len(decoded), 'gif_delays_ms': delays, 'loop': 'infinite',
            'unique_decoded_drawings': len({frame.tobytes() for frame in decoded}),
            'endpoint_rgb_mae': layers.mean_rgb_difference(frames[0], closing),
            'decoded_seam_rgb_mae': layers.mean_rgb_difference(decoded[-1], decoded[0]),
            'font_assets': text_fonts.font_receipt(scene),
            'visual_review': 'pending', 'user_acceptance': 'pending'}
    overview.save(out / 'overview.png')
    receipt = {'format': 'gif-cinema-motion-preset-gallery', 'schema_version': 1,
        'api_calls': 0, 'renderer': 'gif_cinema.layers.render_at', 'pillow': PIL.__version__,
        'text_renderer': text_fonts.renderer_identity(), 'presets': records,
        'source': 'Original text and primitive shape recipes; no GIF Factory artwork or source code copied.',
        'limitations': ['Graphic animation only; no new character poses.',
            'GIFs are opaque and silent; infinitely repeating.',
            'GIF can merge identical holds and quantize antialiased edges.',
            'Equal endpoints and pixel metrics do not prove perceptual continuity.',
            'The builder exports GIF only; use the standard layer renderer for MP4 and editable bundles.']}
    (out / 'manifest.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = build(args.out)
    print(json.dumps({name: {key: row[key] for key in ('duration_ms', 'gif_drawings', 'unique_decoded_drawings')}
                      for name, row in result['presets'].items()}, indent=2))
