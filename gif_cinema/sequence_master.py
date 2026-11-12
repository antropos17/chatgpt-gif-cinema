"""Lossless assembly of verified sequence PNGs, never GIF palette round-trips."""
from fractions import Fraction
import io
from pathlib import Path
import tempfile

from PIL import Image
from . import cli, factory, layers, master, sequence


def build(directory, out):
    root, out = Path(directory).absolute(), Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Master output must be a new directory without symlinks')
    if root == out or root in out.parents:
        raise ValueError('Master output must be outside the source sequence')
    av = master.require_av()
    receipt_raw = layers.read_regular(root / 'sequence-receipt.json', sequence.MAX_RECEIPT_BYTES)
    sequence.verify_sequence(root)
    if layers.read_regular(root / 'sequence-receipt.json', sequence.MAX_RECEIPT_BYTES) != receipt_raw:
        raise ValueError('Source receipt changed during verification')
    source = factory.parse_json(receipt_raw)
    report = {'format': 'gif-cinema-sequence-master', 'schema_version': 1,
              'provider_calls': 0, 'source_receipt_sha256': factory.digest(receipt_raw),
              'width': source['width'], 'height': source['height'],
              'frame_count': source['frames'], 'duration_cs': source['duration_ms'] // 10,
              'fps': source['fps'], 'frames': [], 'timeline': source['timeline'],
              'visual_acceptance': 'not-established',
              'scope': 'Exact original RGBA samples and holds, including every scene boundary. '
                       'No new drawings, interpolation, color grading or visual acceptance.'}
    out.parent.mkdir(parents=True, exist_ok=True)
    with cli.output_lock(out), tempfile.TemporaryDirectory(prefix='.sequence-master-', dir=out.parent) as tmp:
        stage = Path(tmp)
        target = stage / 'master.mkv'
        sink = master.LimitedFile(target)
        try:
            with av.open(sink, 'w', format='matroska') as container:
                stream = container.add_stream('ffv1', rate=source['fps'])
                stream.width, stream.height, stream.pix_fmt = source['width'], source['height'], 'bgra'
                stream.time_base = stream.codec_context.time_base = Fraction(1, 100)
                stream.codec_context.thread_count = 1
                stream.options = {'level': '3', 'slicecrc': '1'}
                duration = 100 // source['fps']
                cursor, emitted = 0, set()
                timing = {}
                def mux(packet):
                    if packet.pts is None or packet.time_base is None:
                        raise ValueError('Missing master packet timestamp')
                    key = packet.pts * packet.time_base
                    if key not in timing or key in emitted:
                        raise ValueError('Master packet timestamp changed or duplicated')
                    hold = timing[key] / packet.time_base
                    if hold.denominator != 1:
                        raise ValueError('Master hold is not exactly representable')
                    packet.duration = int(hold)
                    container.mux(packet)
                    emitted.add(key)
                for shot in source['timeline']:
                    for index in range(shot['frames']):
                        name = f'shots/{shot["id"]}/frames/{index:04}.png'
                        raw = layers.read_regular(root / name, 16 * 1024 * 1024)
                        if factory.digest(raw) != source['files'][name]['sha256']:
                            raise ValueError('Source PNG changed after sequence verification')
                        with Image.open(io.BytesIO(raw)) as png:
                            if png.mode != 'RGBA' or png.size != (source['width'], source['height']):
                                raise ValueError('Source PNG mode or canvas changed')
                            rgba = png.copy()
                        digest = factory.digest(rgba.tobytes())
                        report['frames'].append({'index': len(report['frames']), 'shot': shot['id'],
                            'source_frame': index, 'pts_cs': cursor, 'duration_cs': duration,
                            'roi': [0, 0, rgba.width, rgba.height],
                            'source_rgba_sha256': digest, 'canvas_rgba_sha256': digest})
                        frame = master.video_frame(av, rgba)
                        frame.pts, frame.time_base, frame.duration = cursor, Fraction(1, 100), duration
                        timing[Fraction(cursor, 100)] = Fraction(duration, 100)
                        for packet in stream.encode(frame): mux(packet)
                        cursor += duration
                for packet in stream.encode(): mux(packet)
                if len(emitted) != source['frames'] or cursor != report['duration_cs']:
                    raise ValueError('Master omitted frames or timing')
        finally:
            sink.close()
        report['verification'] = master.verify_master(target, report)
        if layers.read_regular(root / 'sequence-receipt.json', sequence.MAX_RECEIPT_BYTES) != receipt_raw:
            raise ValueError('Source receipt changed during assembly')
        if sequence.file_inventory(root) != source['files']:
            raise ValueError('Source sequence changed during assembly')
        report['master_sha256'] = master.file_sha(target)
        sequence.dump(stage / 'master-receipt.json', report)
        out.mkdir(exist_ok=False)
        cli.publish_file(target, out / 'master.mkv')
        cli.publish_file(stage / 'master-receipt.json', out / 'master-receipt.json')
    return {'status': 'verified', 'output': str(out), 'master': str(out / 'master.mkv'),
            'provider_calls': 0, **report['verification']}
