"""Native-pixel, native-delay triage of a single outfit take. Never an art approval."""
import argparse
import json
from pathlib import Path
from statistics import median
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageStat

from . import cli, factory, layers, pixel, pixel_palette as codec

SCOPE = ('Review one outfit per invocation. Scores prioritize inspection, not artistic acceptance. '
         'No pose interpolation, retiming, rearrangement or automatic repair. '
         'Static opaque backgrounds can dilute full-frame scores: use an authored focus rectangle. '
         'Rates are pixel change per combined identical visible hold, not physical velocity. '
         'The baseline excludes unchanged adjacent edges and the loop seam. '
         'Loop seam is hypothetical for play-once sources.')


def rectangle(value, size):
    if value is None:
        return [0, 0, *size]
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(x) is not int for x in value)):
        raise ValueError('Focus must be four integer coordinates: left top right bottom')
    x, y, right, bottom = value
    if not (0 <= x < right <= size[0] and 0 <= y < bottom <= size[1]):
        raise ValueError('Focus must be a nonempty rectangle inside the source canvas')
    return list(value)


def change(left, right):
    """Exact native pixels; union alpha prevents transparent padding dilution.

    The maximum of the two whole-ROI mean errors on black/white handles
    both visibility and RGB changes (not a per-pixel maximum).
    GIF alpha is binary. Hidden RGB is canonicalized by the bounded decoder.
    """
    union = ImageChops.lighter(left.getchannel('A'), right.getchannel('A'))
    visible = union.histogram()[255]
    channels = ImageChops.difference(left, right).split()
    changed = channels[0]
    for channel in channels[1:]:
        changed = ImageChops.lighter(changed, channel)
    changed_count = sum(changed.histogram()[1:])
    errors = []
    for background in ('black', 'white'):
        a = Image.new('RGB', left.size, background)
        b = Image.new('RGB', right.size, background)
        a.paste(left, mask=left.getchannel('A'))
        b.paste(right, mask=right.getchannel('A'))
        errors.append(sum(ImageStat.Stat(ImageChops.difference(a, b)).sum) / 3)
    return {'visible_union_pixels': visible, 'changed_pixels': changed_count,
            'changed_visible_fraction': round(changed_count / visible, 8) if visible else 0.0,
            'visible_mae_0_255': round(max(errors) / visible, 8) if visible else 0.0}


def analyze(raw, focus=None):
    source = codec.decode(raw)
    box = rectangle(focus, source['size'])
    frames = [f.crop(box) for f in source['frames']]
    identities = [f.tobytes() for f in frames]
    rows, cursor = [], 0
    for index, (frame, delay) in enumerate(zip(frames, source['delays_ms'])):
        target = (index + 1) % len(frames)
        metric = change(frame, frames[target])
        cursor += delay
        # Consecutive identical drawings are one visible hold, even when a GIF
        # encoder divides it into several records. Preserve original indexes.
        effective_hold = delay
        prior = index - 1
        visited = 1
        while visited < len(frames):
            if prior < 0 and source['loop'] is None:
                break
            previous = prior % len(frames)
            if identities[previous] != identities[index]:
                break
            effective_hold += source['delays_ms'][previous]
            prior -= 1
            visited += 1
        rows.append({'from_frame': index, 'to_frame': target,
                     'kind': 'loop-seam' if target == 0 else 'adjacent',
                     'at_ms': cursor, 'source_hold_ms': delay, 'effective_visible_hold_ms': effective_hold, **metric,
                     'visible_mae_per_second': round(metric['visible_mae_0_255'] * 1000 / effective_hold, 8)})
    changing = [r['visible_mae_per_second'] for r in rows[:-1] if r['changed_pixels']]
    baseline = median(changing) if changing else 0
    for row in rows:
        row['rate_to_adjacent_median'] = round(row['visible_mae_per_second'] / baseline, 8) if baseline else None
    ranking = sorted(range(len(rows)), key=lambda i: (-rows[i]['visible_mae_per_second'], i))
    return {'format': 'gif-cinema-motion-review', 'schema_version': 1,
            'source_sha256': layers.digest(raw), 'size': list(source['size']), 'focus': box,
            'frames': len(frames), 'delays_ms': source['delays_ms'],
            'duration_ms': sum(source['delays_ms']), 'loop': source['loop'],
            'loop_seam_is_played': source['loop'] is not None,
            'adjacent_median_rate': baseline, 'edges': rows, 'ranked_edge_indexes': ranking,
            'visual_acceptance': 'not-established', 'provider_calls': 0, 'scope': SCOPE}


def sheet(source, report):
    # Always include the loop, even when an internal jump ranks above it.
    indexes = report['ranked_edge_indexes'][:5]
    seam = len(report['edges']) - 1
    if seam not in indexes:
        indexes.append(seam)
    result = Image.new('RGB', (640, len(indexes) * 200), '#dedbd4')
    draw = ImageDraw.Draw(result)
    for row_number, edge_index in enumerate(indexes):
        edge = report['edges'][edge_index]
        y = row_number * 200
        # Three-frame context exposes direction/hold changes that equal endpoints hide.
        before = edge['from_frame'] - 1
        before = before % report['frames'] if report['loop_seam_is_played'] else max(0, before)
        indexes_to_show = [before, edge['from_frame'], edge['to_frame']]
        for column, index in enumerate(indexes_to_show):
            frame = source['frames'][index].crop(report['focus'])
            frame.thumbnail((192, 152), Image.Resampling.NEAREST)
            x = column * 212 + 8
            result.paste(frame, (x, y + 24), frame)
            draw.text((x, y + 5), f"frame {index} | {report['delays_ms'][index]} ms", fill='black')
        draw.text((8, y + 179), f"{edge['kind']} {'(hypothetical)' if edge['kind'] == 'loop-seam' and not report['loop_seam_is_played'] else ''} {edge['from_frame']} -> {edge['to_frame']} | rate {edge['visible_mae_per_second']:.2f}", fill='black')
    return result


def build(path, out, focus=None):
    source_path, raw, decoded, _, _, _ = pixel.load(path, 1, None)
    report = analyze(raw, focus)
    out = pixel.local_path(out)
    if out.exists():
        raise ValueError('Motion review output must be a new directory')
    out.parent.mkdir(parents=True, exist_ok=True)
    with cli.output_lock(out), tempfile.TemporaryDirectory(prefix='.motion-review-', dir=out.parent) as temporary:
        stage = Path(temporary)
        (stage / 'frames').mkdir()
        (stage / 'source.gif').write_bytes(raw)
        for index, frame in enumerate(decoded['frames']):
            frame.save(stage / 'frames' / f'{index:04}.png')
        sheet(decoded, report).save(stage / 'priority-edges.png')
        report['files'] = pixel.file_inventory(stage)
        pixel.dump(stage / 'receipt.json', report)
        verify(stage)
        if layers.read_regular(source_path, codec.MAX_BYTES) != raw:
            raise ValueError('Source GIF changed during review')
        pixel.publish(stage, out)
    return report


def verify(directory):
    root = pixel.local_path(directory)
    report = factory.parse_json(layers.read_regular(root / 'receipt.json', pixel.MAX_RECEIPT_BYTES))
    if not isinstance(report, dict):
        raise ValueError('Invalid motion review receipt')
    raw = layers.read_regular(root / 'source.gif', codec.MAX_BYTES)
    expected = analyze(raw, report.get('focus'))
    source = codec.decode(raw)
    expected['files'] = pixel.file_inventory(root)
    required = {'source.gif', 'priority-edges.png'} | {f'frames/{i:04}.png' for i in range(len(source['frames']))}
    if set(expected['files']) != required or factory.json_bytes(report) != factory.json_bytes(expected):
        raise ValueError('Motion review receipt or inventory differs from source')
    for index, frame in enumerate(source['frames']):
        pixel.check_png(root / 'frames' / f'{index:04}.png', frame)
    pixel.check_png(root / 'priority-edges.png', sheet(source, expected))
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build_parser = commands.add_parser('build')
    build_parser.add_argument('source')
    build_parser.add_argument('--out', required=True)
    build_parser.add_argument('--focus', nargs=4, type=int, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'))
    commands.add_parser('verify').add_argument('directory')
    args = parser.parse_args()
    try:
        report = verify(args.directory) if args.command == 'verify' else build(args.source, args.out, args.focus)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
