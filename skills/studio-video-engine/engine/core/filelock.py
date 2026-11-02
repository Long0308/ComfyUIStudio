"""Per-run executor lock: an OS-level exclusive file lock released at process death.

This is NOT the machine-wide GPU lock (that is the O_EXCL sentinel in ``engine.comfy.lock``,
which is never auto-removed).  A run lock only stops two executors from walking the same run
directory at once; if the process is killed the OS frees it, so no stale file can block a
legitimate resume.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import Refused


def _try_lock(descriptor: int) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(descriptor: int) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        pass  # closing the descriptor releases it anyway


@contextmanager
def run_lock(path: Path, *, timeout_seconds: float, poll_seconds: float = 0.05) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` (created if missing, never deleted)."""
    if timeout_seconds < 0:
        raise ValueError("lock timeout cannot be negative")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    deadline = time.monotonic() + timeout_seconds
    try:
        while not _try_lock(descriptor):
            if time.monotonic() >= deadline:
                raise Refused(f"another executor holds the run lock: {path}")
            time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
        try:
            yield
        finally:
            _unlock(descriptor)
    finally:
        os.close(descriptor)
