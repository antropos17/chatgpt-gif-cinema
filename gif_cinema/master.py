"""Lossless decoded-RGBA GIF master with exact centisecond timing.

Optional H.264/AAC viewing copy is explicitly lossy. No motion interpolation.
"""
from fractions import Fraction
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile

from PIL import Image, __version__ as PILLOW_VERSION
from . import cli, factory
from .audio import prepare_audio, input_options as audio_input_options

MAX_INPUT_BYTES = 256 * 1024 * 1024
MAX_PIXELS = 512 * 1024 * 1024
MAX_MASTER_BYTES = 512 * 1024 * 1024
MAX_PREVIEW_BYTES = 128 * 1024 * 1024
MAX_PREVIEW_PIXELS = 4 * 1024 * 1024 * 1024
MAX_DURATION_CS = 60000
NOTICE = ('The master preserves the named Pillow decoder\'s RGBA canvases and declared GIF delays, '
          'not the original compressed GIF bytes or every browser\'s playback policy. '
          'No new poses, interpolation, identity guarantee or automatic cut approval.')


def metadata(raw):
    """Strict semantic profile after the shared bounded block-framing scanner."""
    stats = cli.check_gif_limits(raw, fixed_canvas=True)
    if not stats['frames'] or stats['width'] > 4096 or stats['height'] > 4096:
        raise ValueError('Master GIF dimensions must fit 4096x4096 and contain frames')
    if raw[12] not in (0, 49):
        raise ValueError('Non-square GIF pixel aspect needs an explicit conversion policy')
    offset = 13 + ((3 << ((raw[10] & 7) + 1)) if raw[10] & 128 else 0)
    frames, control = [], None
    def blocks(pos):
        while raw[pos]: pos += 1 + raw[pos]
        return pos + 1
    while offset < len(raw):
        marker = raw[offset]; offset += 1
        if marker == 0x3b: break
        if marker == 0x21:
            label = raw[offset]; offset += 1
            if label == 0xf9:
                if control is not None: raise ValueError('Multiple GIF controls before a drawing are ambiguous')
                packed = raw[offset + 1]
                if packed & 0xe2 or ((packed >> 2) & 7) > 3:
                    raise ValueError('Interactive, reserved or undefined GIF disposal is unsupported')
                delay = int.from_bytes(raw[offset + 2:offset + 4], 'little')
                if not delay: raise ValueError('Missing/zero delay needs an explicit playback policy')
                control = {'duration_cs': delay, 'disposal': (packed >> 2) & 7}
                offset += 6
            elif label == 0x01:
                raise ValueError('GIF plain-text graphics are outside the strict master profile')
            else: offset = blocks(offset)
        elif marker == 0x2c:
            if control is None: raise ValueError('Every GIF drawing needs its own nonzero delay')
            flags = raw[offset + 8]
            offset += 9 + ((3 << ((flags & 7) + 1)) if flags & 128 else 0)
            offset = blocks(offset + 1)
            frames.append(control); control = None
    if len(frames) != stats['frames'] or control is not None:
        raise ValueError('GIF drawing/control counts disagree')
    return {**stats, 'timing': frames, 'duration_cs': sum(f['duration_cs'] for f in frames)}


def plan(paths, preview=False, audio=None):
    if not 1 <= len(paths) <= 64: raise ValueError('Master requires 1..64 ordered local GIFs')
    if audio and not preview: raise ValueError('Audio belongs to the viewing MP4; request --preview too')
    sources, total_bytes, duration = [], 0, 0
    for index, path in enumerate(paths):
        raw = cli.read_gif_bytes(path)
        item = metadata(raw)
        total_bytes += len(raw); duration += item['duration_cs']
        if total_bytes > MAX_INPUT_BYTES or duration > MAX_DURATION_CS:
            raise ValueError('Master inputs exceed 256 MiB or 10 minutes')
        sources.append({'index': index, 'name': Path(path).name, 'sha256': factory.digest(raw), **item})
    width, height = max(s['width'] for s in sources), max(s['height'] for s in sources)
    count = sum(s['frames'] for s in sources)
    if count > 6000 or count * width * height > MAX_PIXELS:
        raise ValueError('Master exceeds 6000 frames or 512 Mi padded pixel-frames')
    if preview and duration * (width + width % 2) * (height + height % 2) > MAX_PREVIEW_PIXELS:
        raise ValueError('100fps viewing copy exceeds 4 Gi pixel-frames; build only the VFR master')
    # Audio decoding remains explicitly pending in a read-only plan.
    if audio: cli.read_local_bytes(audio, 128 * 1024 * 1024, 'Audio')
    return {'format': 'gif-cinema-rgba-master', 'schema_version': 1, 'status': 'planned', 'provider_calls': 0,
            'width': width, 'height': height, 'frame_count': count, 'duration_cs': duration, 'sources': sources,
            'pixel_format': 'RGBA8', 'loop_policy': 'one iteration per input',
            'dimension_policy': 'center-pad transparent; no scale or crop', 'preview': bool(preview),
            'audio_validation': 'pending' if audio else 'not-requested', 'visual_review': 'pending', 'notice': NOTICE}


def file_sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while block := stream.read(1024 * 1024): digest.update(block)
    return digest.hexdigest()


def require_av():
    try: import av
    except ImportError:
        raise RuntimeError('Install the optional lossless dependency: python -m pip install ".[lossless]"') from None
    return av


def video_frame(av, image):
    frame = av.VideoFrame(image.width, image.height, 'bgra')
    plane = frame.planes[0]
    raw = image.tobytes('raw', 'BGRA')
    data = bytearray(plane.buffer_size)
    row = image.width * 4
    for y in range(image.height): data[y * plane.line_size:y * plane.line_size + row] = raw[y * row:(y + 1) * row]
    plane.update(data)
    return frame


def rgba_frame(frame):
    frame = frame.reformat(format='rgba')
    plane = frame.planes[0]
    return Image.frombytes('RGBA', (frame.width, frame.height), bytes(plane), 'raw', 'RGBA', plane.line_size)


class LimitedFile:
    """File-like mux sink: cap writes before they can grow the master past its budget."""
    def __init__(self, path): self.file = open(path, 'x+b')
    def write(self, data):
        if self.file.tell() + len(data) > MAX_MASTER_BYTES: raise ValueError('Master exceeds 512 MiB')
        return self.file.write(data)
    def seek(self, *args): return self.file.seek(*args)
    def tell(self): return self.file.tell()
    def flush(self): return self.file.flush()
    def close(self): self.file.close()
    def writable(self): return True
    def seekable(self): return True


def encode_master(snapshots, output, report):
    av = require_av()
    report.update(decoder=f'Pillow {PILLOW_VERSION}', encoder=f'PyAV {av.__version__}',
                  av_libraries={k: list(v) for k, v in av.library_versions.items()}, frames=[])
    timing, emitted, cursor = {}, set(), 0
    sink = LimitedFile(output)
    try:
        with av.open(sink, 'w', format='matroska') as container:
            stream = container.add_stream('ffv1', rate=100)
            stream.width, stream.height, stream.pix_fmt = report['width'], report['height'], 'bgra'
            stream.time_base = stream.codec_context.time_base = Fraction(1, 100)
            stream.codec_context.thread_count = 1
            options = ({'level': '1'} if min(report['width'], report['height']) == 1
                       else {'level': '3', 'slicecrc': '1'})
            stream.options = options
            report['ffv1_options'] = options
            def mux(packet):
                if packet.pts is None or packet.time_base is None: raise ValueError('Encoder omitted a timestamp')
                key = packet.pts * packet.time_base
                if key not in timing or key in emitted: raise ValueError('Encoder duplicated/changed a frame timestamp')
                ticks = timing[key] / packet.time_base
                if ticks.denominator != 1: raise ValueError('Packet delay is not exactly representable')
                # FFV1 does not propagate frame.duration; this explicit step preserves the last hold.
                packet.duration = int(ticks)
                container.mux(packet); emitted.add(key)
            for source, path in zip(report['sources'], snapshots):
                with Image.open(path) as image:
                    if image.n_frames != source['frames']: raise ValueError('Pillow/descriptor counts disagree')
                    source['loop_metadata'] = image.info.get('loop')
                    for index, spec in enumerate(source['timing']):
                        image.seek(index); rgba = image.convert('RGBA')
                        if rgba.size != (source['width'], source['height']): raise ValueError('GIF canvas changed during decode')
                        if image.info.get('duration') != spec['duration_cs'] * 10: raise ValueError('Decoder/GIF delays disagree')
                        x, y = (report['width'] - rgba.width) // 2, (report['height'] - rgba.height) // 2
                        canvas = Image.new('RGBA', (report['width'], report['height']), (0, 0, 0, 0))
                        canvas.paste(rgba, (x, y))  # No alpha compositing: preserve hidden RGB and alpha.
                        report['frames'].append({'index': len(report['frames']), 'source': source['index'], 'source_frame': index,
                            'pts_cs': cursor, 'duration_cs': spec['duration_cs'], 'roi': [x, y, rgba.width, rgba.height],
                            'source_rgba_sha256': factory.digest(rgba.tobytes()), 'canvas_rgba_sha256': factory.digest(canvas.tobytes())})
                        frame = video_frame(av, canvas)
                        frame.pts, frame.time_base, frame.duration = cursor, Fraction(1, 100), spec['duration_cs']
                        timing[Fraction(cursor, 100)] = Fraction(spec['duration_cs'], 100)
                        for packet in stream.encode(frame): mux(packet)
                        cursor += spec['duration_cs']
            for packet in stream.encode(): mux(packet)
        if len(emitted) != report['frame_count'] or cursor != report['duration_cs']:
            raise ValueError('Master encoder omitted frames or timing')
    finally: sink.close()


def verify_master(path, report):
    av = require_av()
    count, end = 0, Fraction(0)
    with av.open(str(path), 'r', format='matroska') as container:
        stream = container.streams.video[0]
        if stream.codec_context.name != 'ffv1': raise ValueError('Expected FFV1 master')
        for frame in container.decode(stream):
            if count >= len(report['frames']): raise ValueError('Extra master frame')
            expected = report['frames'][count]
            rgba = rgba_frame(frame)
            if rgba.size != (report['width'], report['height']) or factory.digest(rgba.tobytes()) != expected['canvas_rgba_sha256']:
                raise ValueError(f'Master RGBA mismatch at frame {count}')
            if frame.pts is None or frame.pts * frame.time_base != Fraction(expected['pts_cs'], 100):
                raise ValueError(f'Master PTS mismatch at frame {count}')
            if frame.duration * frame.time_base != Fraction(expected['duration_cs'], 100):
                raise ValueError(f'Master hold mismatch at frame {count}')
            x, y, w, h = expected['roi']
            if factory.digest(rgba.crop((x, y, x + w, y + h)).tobytes()) != expected['source_rgba_sha256']:
                raise ValueError('Source ROI pixels changed')
            end = (frame.pts + frame.duration) * frame.time_base; count += 1
    if count != report['frame_count'] or end != Fraction(report['duration_cs'], 100):
        raise ValueError('Master dropped a frame or its final hold')
    return {'status': 'verified', 'frames': count, 'duration_ms': report['duration_cs'] * 10,
            'rgba_mismatches': 0, 'pts_mismatches': 0, 'duration_mismatches': 0,
            'alpha_preserved': True, 'visual_review': 'pending'}


def probe_stream(path, selector, fields, count=False):
    raw = cli.run_media(['ffprobe', '-v', 'error', *(['-count_frames'] if count else []), '-select_streams', selector,
                         '-show_entries', 'stream=' + fields, '-of', 'json', str(path)]).stdout
    try:
        streams = json.loads(raw)['streams']
        if len(streams) != 1 or not isinstance(streams[0], dict): raise ValueError()
        if not set(fields.split(',')) <= set(streams[0]): raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError('Viewing MP4 has incomplete or invalid probe metadata') from None
    return streams[0]


def viewing_copy(master, output, report, audio):
    width, height = report['width'] + report['width'] % 2, report['height'] + report['height'] % 2
    # Composite transparency on black, pad odd dimensions, never enlarge source art.
    command = ['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-y', '-protocol_whitelist', 'file', '-f', 'matroska', '-i', str(master)]
    if audio: command += [*audio_input_options(), '-i', str(audio['path'])]
    filters = (f'tpad=stop_mode=clone:stop=-1,fps=100,trim=end_frame={report["duration_cs"]},'
               f'pad={width}:{height}:0:0:color=black,format=rgb24,scale=out_color_matrix=bt709:out_range=tv,'
               'format=yuv420p,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709,setpts=PTS-STARTPTS')
    # FFmpeg's format conversion drops alpha rather than compositing. An explicit
    # black background overlay below makes the visible-color policy unambiguous.
    graph = (f'color=black:s={width}x{height}:r=100[bg];[0:v]pad={width}:{height}:0:0:color=black[fg];'
             f'[bg][fg]overlay=shortest=1:format=rgb,{filters}[v]')
    command += ['-filter_complex', graph, '-map', '[v]', '-r', '100', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709']
    if audio:
        command += ['-map', '1:a:0', '-af', f'aresample=48000,apad,atrim=end_sample={report["duration_cs"] * 480},asetpts=N/SR/TB',
                    '-c:a', 'aac', '-ar', '48000']
    command += ['-fs', str(MAX_PREVIEW_BYTES), '-movflags', '+faststart', str(output)]
    cli.run_media(command)
    if output.stat().st_size > MAX_PREVIEW_BYTES:
        raise ValueError('Viewing MP4 exceeds 128 MiB output budget')
    result = probe_stream(output, 'v:0', 'codec_name,width,height,nb_read_frames,duration,avg_frame_rate', count=True)
    if (result['codec_name'] != 'h264' or int(result['nb_read_frames']) != report['duration_cs'] or
            result['width'] != width or result['height'] != height or Fraction(result['avg_frame_rate']) != 100 or
            abs(Fraction(result['duration']) - Fraction(report['duration_cs'], 100)) > Fraction(1, 1000000)):
        raise ValueError('Viewing MP4 failed frame count/duration verification')
    cli.run_media(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(output), '-f', 'null', '-'])
    facts = {'fps': 100, 'frames': report['duration_cs'], 'duration_ms': report['duration_cs'] * 10,
             'width': width, 'height': height, 'pixel_preservation': 'lossy H.264; alpha composited on black',
             'motion': 'original drawings repeated on a 10ms grid, no interpolation'}
    if audio:
        info = probe_stream(output, 'a:0', 'codec_name,sample_rate,duration,start_time')
        if info['codec_name'] != 'aac' or info['sample_rate'] != '48000' or abs(float(info['duration']) - report['duration_cs'] / 100) > .022:
            raise ValueError('Viewing AAC failed duration verification')
        facts['audio'] = {'source_sha256': audio['sha256'], 'sample_rate': 48000, 'target_samples': report['duration_cs'] * 480,
                          'probe': info, 'policy': 'start at zero; resample, pad or trim to film; lossy AAC with codec padding'}
    return facts


def build(paths, out, preview=False, audio=None, dry_run=False):
    out = Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Master output must be a new directory without symlinks')
    report = plan(paths, preview, audio)
    if dry_run: return report
    require_av()
    out.parent.mkdir(parents=True, exist_ok=True)
    with cli.output_lock(out), tempfile.TemporaryDirectory(prefix='.master-stage-', dir=out.parent) as tmp, prepare_audio(audio) as prepared:
        work = Path(tmp); stage = work / 'delivery'; stage.mkdir()
        snapshots = []
        for index, (path, source) in enumerate(zip(paths, report['sources'])):
            raw = cli.read_gif_bytes(path)
            if factory.digest(raw) != source['sha256']: raise ValueError('Source GIF changed after planning')
            snapshot = work / f'{index:02}.gif'; snapshot.write_bytes(raw); snapshots.append(snapshot)
        movie = stage / 'master.mkv'
        try:
            encode_master(snapshots, movie, report)
            report['verification'] = verify_master(movie, report)
        except require_av().FFmpegError:
            raise ValueError('Master codec failed; no output published') from None
        if preview: report['viewing_copy'] = viewing_copy(movie, stage / 'preview.mp4', report, prepared)
        report.update(status='verified-master', audio_validation='decoded-and-timed' if prepared else 'not-requested')
        report['files'] = {p.name: {'bytes': p.stat().st_size, 'sha256': file_sha(p)} for p in stage.iterdir()}
        (stage / 'manifest.json').write_bytes(factory.json_bytes(report))
        out.mkdir(exist_ok=False); created = []
        try:
            for path in sorted(stage.iterdir(), key=lambda p: p.name == 'manifest.json'):
                target = out / path.name; cli.publish_file(path, target); created.append(target)
        except Exception:
            for path in created:
                if path.is_file() and not path.is_symlink(): path.unlink()
            try: out.rmdir()
            except OSError: pass
            raise
    return report


def run(args):
    report = build(args.clips, args.out, args.preview, args.audio, args.dry_run)
    print(json.dumps(report, indent=2, allow_nan=False))
    return report


def add_parser(sub):
    parser = sub.add_parser('master', help='Build a verified lossless RGBA/VFR GIF master, optionally a viewing MP4')
    parser.add_argument('clips', nargs='+', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--audio', type=Path, help='Optional audio for the lossy viewing MP4, not the silent pixel master')
    parser.add_argument('--dry-run', action='store_true')
    parser.set_defaults(func=run)
