"""Export a Browser Studio GFC1 working project, never original GIF assets."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import tempfile

from PIL import Image
from . import cli, factory, master

MAX_BYTES = 64_000_000
FRAME_BYTES = 256 * 256 * 4
NOTICE = ('Exactness applies only to the saved 256x256 RGBA working project and its declared holds. '
          'Earlier browser scaling, black compositing and source decoding cannot be undone. '
          'No original-GIF fidelity, new poses, interpolation, face lock or artistic acceptance is claimed.')


def parse_project(raw):
    """Validate the complete bounded snapshot before any pixel allocation or codec work."""
    if type(raw) is not bytes or not 8 <= len(raw) <= MAX_BYTES or raw[:4] != b'GFC1':
        raise ValueError('Expected a bounded GFC1 project byte snapshot')
    length = int.from_bytes(raw[4:8], 'little')
    if not 1 <= length <= 100_000 or 8 + length > len(raw):
        raise ValueError('Invalid GFC1 header length')
    try:
        meta = factory.parse_json(raw[8:8 + length])
    except RecursionError:
        raise ValueError('GFC1 header nesting exceeds the parser limit') from None
    if set(meta) != {'version', 'width', 'height', 'scenes'}:
        raise ValueError('Unexpected GFC1 header fields')
    if any(type(meta[key]) is not int or meta[key] != value for key, value in
           [('version', 1), ('width', 256), ('height', 256)]):
        raise ValueError('Expected GFC1 version 1 and 256x256 canvas')
    scenes = meta['scenes']
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 8:
        raise ValueError('Project requires 1..8 scenes')
    count, duration, parsed = 0, 0, []
    for scene in scenes:
        if not isinstance(scene, dict) or set(scene) != {'name', 'delays'}:
            raise ValueError('Unexpected scene fields')
        name, delays = scene['name'], scene['delays']
        if not isinstance(name, str) or len(name) > 300:
            raise ValueError('Scene name must be text of at most 300 characters')
        try:
            name.encode('utf-8')
        except UnicodeError:
            raise ValueError('Scene name contains invalid Unicode') from None
        if not isinstance(delays, list) or not 1 <= len(delays) <= 240:
            raise ValueError('Scene requires 1..240 frame delays')
        if any(type(d) is not int or not 10 <= d <= 30000 or d % 10 for d in delays):
            raise ValueError('Frame delays must be integer 10..30000 ms multiples of 10')
        parsed.append({'name': name, 'delays': delays, 'start_frame': count,
                       'frame_count': len(delays), 'start_ms': duration, 'duration_ms': sum(delays)})
        count += len(delays); duration += sum(delays)
        if count > 240 or duration > 30000:
            raise ValueError('Project exceeds 240 frames or 30 seconds')
    offset = 8 + length
    if len(raw) != offset + count * FRAME_BYTES:
        raise ValueError('Project pixel payload is truncated or contains extra bytes')
    return {'width': 256, 'height': 256, 'frame_count': count, 'duration_ms': duration,
            'scenes': parsed, 'data_offset': offset, 'project_sha256': factory.digest(raw)}


def encode_project(raw, target, report):
    av = master.require_av()
    report.update(decoder='GFC1 straight RGBA8 working frames', encoder=f'PyAV {av.__version__}',
                  av_libraries={k: list(v) for k, v in av.library_versions.items()})
    sink = master.LimitedFile(target)
    timing, emitted, cursor = {}, set(), 0
    try:
        with av.open(sink, 'w', format='matroska') as container:
            stream = container.add_stream('ffv1', rate=100)
            stream.width = stream.height = 256
            stream.pix_fmt = 'bgra'
            stream.time_base = stream.codec_context.time_base = Fraction(1, 100)
            stream.codec_context.thread_count = 1
            stream.options = {'level': '3', 'slicecrc': '1'}
            def mux(packet):
                if packet.pts is None or packet.time_base is None:
                    raise ValueError('Master encoder omitted a timestamp')
                key = packet.pts * packet.time_base
                if key not in timing or key in emitted:
                    raise ValueError('Master encoder duplicated or changed a timestamp')
                ticks = timing[key] / packet.time_base
                if ticks.denominator != 1:
                    raise ValueError('Master hold is not exactly representable')
                packet.duration = int(ticks)
                container.mux(packet); emitted.add(key)
            for scene_index, scene in enumerate(report['scenes']):
                for source_frame, delay in enumerate(scene['delays']):
                    index = scene['start_frame'] + source_frame
                    offset = report['data_offset'] + index * FRAME_BYTES
                    pixels = raw[offset:offset + FRAME_BYTES]
                    image = Image.frombytes('RGBA', (256, 256), pixels)
                    digest = factory.digest(pixels)
                    hold = delay // 10
                    report['frames'].append({'index': index, 'scene': scene_index,
                        'source_frame': source_frame, 'pts_cs': cursor, 'duration_cs': hold,
                        'roi': [0, 0, 256, 256], 'source_rgba_sha256': digest,
                        'canvas_rgba_sha256': digest})
                    frame = master.video_frame(av, image)
                    frame.pts, frame.time_base, frame.duration = cursor, Fraction(1, 100), hold
                    timing[Fraction(cursor, 100)] = Fraction(hold, 100)
                    for packet in stream.encode(frame): mux(packet)
                    cursor += hold
            for packet in stream.encode(): mux(packet)
        if len(emitted) != report['frame_count'] or cursor != report['duration_cs']:
            raise ValueError('Master omitted frames or their holds')
    finally:
        sink.close()


def build(source_path, out, preview=True):
    """Publish only verified results; names never become paths or commands."""
    source, out = Path(source_path).absolute(), Path(out).absolute()
    if type(preview) is not bool:
        raise ValueError('preview must be boolean')
    if any(p.is_symlink() for p in (source, *source.parents, out, *out.parents)):
        raise ValueError('Project and output paths must not use symlinks')
    if out.exists() or source == out or out in source.parents:
        raise ValueError('Output must be a new directory outside the source project')
    raw = cli.read_local_bytes(source, MAX_BYTES, 'GFC1 project')
    spec = parse_project(raw)
    master.require_av()
    report = {'format': 'gif-cinema-editor-master', 'schema_version': 1,
              **spec, 'duration_cs': spec['duration_ms'] // 10, 'frames': [],
              'provider_calls': 0, 'notice': NOTICE, 'visual_review': 'pending',
              'pixel_format': 'RGBA8', 'audio': 'not-requested', 'preview': preview}
    out.parent.mkdir(parents=True, exist_ok=True)
    with cli.output_lock(out), tempfile.TemporaryDirectory(prefix='.editor-master-', dir=out.parent) as temporary:
        stage = Path(temporary)
        (stage / 'project.gfc').write_bytes(raw)
        try:
            encode_project(raw, stage / 'master.mkv', report)
            report['verification'] = master.verify_master(stage / 'master.mkv', report)
        except master.require_av().FFmpegError:
            raise ValueError('Master codec failed; no result published') from None
        if preview:
            report['viewing_copy'] = master.viewing_copy(stage / 'master.mkv', stage / 'preview.mp4', report, None)
        if cli.read_local_bytes(source, MAX_BYTES, 'GFC1 project') != raw:
            raise ValueError('Source project changed during export; no result published')
        report['status'] = 'verified-master'
        report['files'] = {p.name: {'bytes': p.stat().st_size, 'sha256': master.file_sha(p)} for p in stage.iterdir()}
        (stage / 'manifest.json').write_bytes(factory.json_bytes(report))
        # A manifest is the completion marker, published last. Exclusive mkdir and
        # hard-link publication never replace a raced target or accepted output.
        out.mkdir(exist_ok=False)
        created = []
        try:
            for path in sorted(stage.iterdir(), key=lambda p: p.name == 'manifest.json'):
                destination = out / path.name
                cli.publish_file(path, destination); created.append(destination)
        except Exception:
            for path in created:
                if path.is_file() and not path.is_symlink(): path.unlink()
            try: out.rmdir()
            except OSError: pass
            raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--no-preview', action='store_true', help='Only the exact silent master')
    args = parser.parse_args()
    report = build(args.project, args.out, preview=not args.no_preview)
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
