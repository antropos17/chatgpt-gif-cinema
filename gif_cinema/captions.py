"""Preserve edited SRT files while keeping generated captions and timing traceable."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from . import cli

MAX_CAPTION_BYTES = 2 * 1024 * 1024


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def generated_captions(script, records):
    clock, subtitles, timeline = 0, [], []

    def stamp(ms):
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"

    for shot, record in zip(script["shots"], records):
        frames = max(1, round(record["duration_ms"] * script["fps"] / 1000))
        end = clock + frames * 1000 / script["fps"]
        timeline.append({"id": shot["id"], "start_ms": round(clock), "end_ms": round(end)})
        if shot.get("caption"):
            subtitles.append(f"{len(subtitles)+1}\n{stamp(round(clock))} --> {stamp(round(end))}\n{shot['caption']}\n")
        clock = end
    identity = json.dumps(timeline, sort_keys=True).encode()
    return "\n".join(subtitles).encode("utf-8"), digest(identity)


def read_existing(path):
    """None means unknown/unreadable; never follow a caption output symlink."""
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            return None
        flags = (os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
                 | getattr(os, "O_NOFOLLOW", 0))
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_CAPTION_BYTES
                    or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
                return None
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(MAX_CAPTION_BYTES + 1)
            return raw if len(raw) <= MAX_CAPTION_BYTES else None
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return None


def candidate(root, raw):
    """Publish a fresh suggestion without replacing an edited earlier suggestion."""
    name = f"captions-generated-{digest(raw)[:16]}"
    for number in range(32):
        path = root / f"{name}{'-' + str(number) if number else ''}.srt"
        if os.path.lexists(path):
            if read_existing(path) == raw:
                return path.name
            continue
        try:
            cli.write_result(path, raw)
            return path.name
        except FileExistsError:
            continue
    raise ValueError("No unused generated-caption filename; existing subtitles were preserved")


def refresh_managed(path, expected, raw):
    """Keep the displaced file, including an edit racing the initial hash check.

    Publication and restoration never clobber a file created by an editor during
    the short move. The saved inode remains available even to already-open editors.
    """
    fd, name = tempfile.mkstemp(dir=path.parent, prefix="captions-preserved-", suffix=".srt")
    placeholder = os.fstat(fd)
    os.close(fd)
    previous = Path(name)
    try:
        os.replace(path, previous)
    except BaseException:
        # An interrupted syscall may already have moved the real file. Never
        # delete previous on an uncertain outcome, even if it looks empty.
        # If its inode changed, restore the saved file without clobbering any
        # newer editor save. Failure to restore still leaves previous intact.
        try:
            saved = previous.lstat()
            if ((saved.st_dev, saved.st_ino) != (placeholder.st_dev, placeholder.st_ino)
                    and not os.path.lexists(path)):
                os.link(previous, path, follow_symlinks=False)
        except (OSError, NotImplementedError):
            pass
        raise
    try:
        if read_existing(previous) != expected:
            return False, previous.name
        try:
            cli.write_result(path, raw)  # No-clobber, including a raced editor save.
            return True, previous.name
        except FileExistsError:
            return False, previous.name
    finally:
        if not os.path.lexists(path):
            try:
                os.link(previous, path, follow_symlinks=False)
            except FileExistsError:
                pass


def publish(root, script, records, previous=None):
    """Update only verified generated SRT; preserve all other existing bytes."""
    previous = previous if isinstance(previous, dict) else {}
    path = root / "captions.srt"
    raw, timeline = generated_captions(script, records)
    generated_hash = digest(raw)
    saved_copy = None
    status = "unchanged"
    if not os.path.lexists(path):
        try:
            cli.write_result(path, raw)
            status = "created"
        except FileExistsError:
            pass
    current = read_existing(path)
    current_hash = digest(current) if current is not None else None
    if (current is not None and current != raw
            and current_hash == previous.get("generated_sha256")):
        updated, saved_copy = refresh_managed(path, current, raw)
        current = read_existing(path)
        current_hash = digest(current) if current is not None else None
        if updated:
            status = "updated"
    if current == raw:
        record = {"output": "captions.srt", "status": status, "sha256": generated_hash,
                  "generated_sha256": generated_hash, "timeline_sha256": timeline,
                  "current_timeline_sha256": timeline, "timing_review_required": False}
    else:
        baseline = previous.get("timeline_sha256")
        review = baseline != timeline
        record = {"output": "captions.srt", "status": "preserved-edits" if current is not None else "preserved-unreadable",
                  "sha256": current_hash, "generated_sha256": previous.get("generated_sha256"),
                  "timeline_sha256": baseline, "current_timeline_sha256": timeline,
                  "timing_review_required": review, "proposed_output": candidate(root, raw),
                  "proposed_sha256": generated_hash}
        if current is None:
            record["timing_review_required"] = True
            record["warning"] = "Existing captions.srt is unreadable or not a regular file; it was preserved. Review subtitles before delivery."
        elif baseline is None:
            record["warning"] = "Existing captions.srt has no verified timing history; it was preserved. Review subtitles before delivery."
        elif review:
            record["warning"] = "Edited captions.srt was preserved, but shot order or timing changed. Review subtitle synchronization before delivery."
    if saved_copy:
        record["preserved_copy"] = saved_copy
    return record
