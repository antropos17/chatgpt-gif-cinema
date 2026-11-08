"""Small, shared atomic file and directory sync helpers for render manifests."""
import errno
import os
from pathlib import Path
import tempfile


def durable_write(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def sync_directory(path):
    """Sync directory entries on POSIX where supported; file fsync stays mandatory.

    Windows does not expose directory fsync through Python's os API. Unsupported
    directory operations are distinct from real permission, disk or I/O failures.
    """
    if os.name != "posix":
        return
    unsupported = {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError as exc:
        if exc.errno in unsupported:
            return
        raise
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in unsupported:
                raise
    finally:
        os.close(fd)
