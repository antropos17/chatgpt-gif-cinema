"""Bounded, offline audio validation before generation and after film encoding."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import tempfile

MAX_AUDIO_BYTES = 128 * 1024 * 1024
MAX_AUDIO_SECONDS = 3600
MAX_AUDIO_CHANNELS = 8
MAX_AUDIO_RATE = 192000
AUDIO_TIMEOUT_SECONDS = 30
MAX_PROCESS_OUTPUT = 64 * 1024
MAX_ALLOCATION = 64 * 1024 * 1024
# No playlists, device inputs, network protocols or external media fetches.
AUDIO_FORMATS = "aac,aiff,flac,matroska,webm,mov,mp3,ogg,wav"


def input_options():
    return ["-max_alloc", str(MAX_ALLOCATION), "-threads", "1",
            "-probesize", "8388608", "-analyzeduration", "10000000",
            "-max_streams", "32", "-protocol_whitelist", "file",
            "-format_whitelist", AUDIO_FORMATS]


def run_command(command, label):
    """Bound time and output reads; suppress arbitrary metadata/error payloads."""
    with tempfile.TemporaryFile() as output:
        try:
            subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                           stderr=subprocess.DEVNULL, check=True, timeout=AUDIO_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{label} timed out after {AUDIO_TIMEOUT_SECONDS} seconds") from None
        except subprocess.CalledProcessError:
            raise ValueError(f"{label} failed: audio is unreadable, corrupt, or unsupported. "
                             "Use a local WAV, MP3, FLAC, Ogg, AAC, AIFF, M4A/MP4 or Matroska/WebM file") from None
        except OSError:
            raise RuntimeError(f"{label} could not start; install working FFmpeg and ffprobe") from None
        output.seek(0)
        raw = output.read(MAX_PROCESS_OUTPUT + 1)
    if len(raw) > MAX_PROCESS_OUTPUT:
        raise ValueError(f"{label} exceeded the diagnostic output limit")
    return raw


def finite_number(value, label):
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"Audio {label} is missing or invalid") from None
    if not math.isfinite(number):
        raise ValueError(f"Audio {label} is not finite")
    return number


def inspect_audio(path, duration_limit=None):
    """Probe the first audio stream and strictly decode it, not just its header."""
    duration_limit = MAX_AUDIO_SECONDS if duration_limit is None else duration_limit
    raw = run_command(["ffprobe", "-v", "error", *input_options(), "-select_streams", "a:0",
                       "-show_entries", "stream=codec_name,codec_type,sample_rate,channels,start_time,duration:format=duration",
                       "-of", "json", str(path)], "Audio probe")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError()
        streams = data.get("streams", [])
        if len(streams) != 1 or streams[0].get("codec_type") != "audio":
            raise ValueError("Audio file must contain a decodable audio stream")
        stream = streams[0]
        codec = stream["codec_name"]
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ValueError("Audio probe returned invalid stream metadata") from None
    try:
        channels, rate = int(stream["channels"]), int(stream["sample_rate"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Audio probe returned invalid channel count or sample rate") from None
    if not isinstance(codec, str) or not codec or codec == "unknown":
        raise ValueError("Audio codec is unknown")
    if not 1 <= channels <= MAX_AUDIO_CHANNELS or not 1 <= rate <= MAX_AUDIO_RATE:
        raise ValueError("Audio exceeds the 8-channel or 192000 Hz input limit")
    # Metadata is a cheap early limit, not proof of a complete/correct file.
    duration = stream.get("duration", data.get("format", {}).get("duration"))
    if duration is not None:
        duration = finite_number(duration, "duration")
        if not 0 < duration <= duration_limit:
            raise ValueError(f"Audio must have a positive duration of at most {duration_limit} seconds")
    decoded = run_command(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror",
                           *input_options(), "-err_detect", "explode", "-i", str(path),
                           "-map", "0:a:0", "-vn", "-sn", "-dn", "-threads", "1",
                           "-filter_threads", "1", "-af", "asetpts=N/SR/TB",
                           "-ac", "1", "-ar", "48000", "-t", str(duration_limit + 1),
                           "-progress", "pipe:1", "-stats_period", "1", "-f", "null", "-"],
                          "Audio decode")
    progress = dict(line.split("=", 1) for line in decoded.decode("ascii", errors="replace").splitlines() if "=" in line)
    seconds = finite_number(progress.get("out_time_us"), "decoded duration") / 1000000
    if progress.get("progress") != "end" or not 0 < seconds <= duration_limit:
        raise ValueError(f"Audio must fully decode to a positive duration of at most {duration_limit} seconds")
    return {"codec_name": codec, "sample_rate": rate, "channels": channels,
            "duration_seconds": duration, "start_seconds": finite_number(stream.get("start_time", 0), "start time"),
            "decoded_seconds": seconds}


@contextmanager
def prepare_audio(source):
    """Freeze bounded input bytes, validate them, and keep the snapshot until export."""
    if source is None:
        yield None
        return
    source = Path(source)
    with tempfile.TemporaryDirectory(prefix="gif-cinema-audio-") as directory:
        snapshot = Path(directory) / "audio-source"
        digest, size = hashlib.sha256(), 0
        # O_NONBLOCK prevents a raced FIFO/device replacement from hanging open.
        fd = os.open(source, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as original, snapshot.open("wb") as output:
            before = os.fstat(original.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Audio input must be a regular local file")
            if before.st_size > MAX_AUDIO_BYTES:
                raise ValueError("Audio exceeds the 128 MiB input limit")
            while True:
                block = original.read(min(1024 * 1024, MAX_AUDIO_BYTES + 1 - size))
                if not block:
                    break
                size += len(block)
                if size > MAX_AUDIO_BYTES:
                    raise ValueError("Audio exceeds the 128 MiB input limit")
                digest.update(block)
                output.write(block)
            after = os.fstat(original.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Audio changed while taking its validation snapshot; rerun before generation")
        facts = inspect_audio(snapshot)
        yield {"path": snapshot, "sha256": digest.hexdigest(), "bytes": size, **facts}


def verify_film_audio(path, expected_seconds):
    # Permit codec padding at the source-duration ceiling; the tighter packet
    # coverage check below still decides whether the final track is acceptable.
    facts = inspect_audio(path, duration_limit=MAX_AUDIO_SECONDS + 1)
    # AAC frames contain 1024 samples; muxed duration and decoded padding may
    # differ by a packet. Two packets plus 1 ms cover rounding, not missing audio.
    tolerance = 2048 / facts["sample_rate"] + 0.001
    if (facts["codec_name"] != "aac" or facts["duration_seconds"] is None
            or abs(facts["start_seconds"]) > tolerance
            or abs(facts["duration_seconds"] - expected_seconds) > tolerance
            or abs(facts["decoded_seconds"] - expected_seconds) > tolerance):
        raise RuntimeError("Encoded film failed expected AAC audio coverage verification")
    return {**facts, "coverage_tolerance_seconds": tolerance, "status": "decoded-aac"}
