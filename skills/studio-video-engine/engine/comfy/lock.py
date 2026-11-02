"""Machine-wide ComfyUI submit lock: an O_EXCL existence sentinel.

Protocol (invariant I1): the lock is a file created with O_EXCL whose body is
``pid=<n> acquired_unix=<t> token=<hex>``.  Release only removes the file if it
still carries *our* token.  A stale or foreign sentinel is NEVER deleted by
this module, not even on timeout: reconcile ComfyUI queue/history by hand.

There is deliberately no default path.  The caller injects it (machine
config); tests inject temp paths.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ..core.errors import Refused

_TOKEN = re.compile(r"token=([0-9a-f]+)")
_PID = re.compile(r"pid=(\d+)")


@dataclass
class LockHandle:
    path: Path
    token: str
    pid: int
    released: bool | None = None  # None while held; True removed; False left in place
    release_note: str = ""


def read_lock_body(path: Path) -> dict[str, str | int | None] | None:
    """Parse a lock file; None if it does not exist."""
    try:
        body = Path(path).read_text(encoding="ascii", errors="replace")
    except FileNotFoundError:
        return None
    token, pid = _TOKEN.search(body), _PID.search(body)
    return {
        "pid": int(pid.group(1)) if pid else None,
        "token": token.group(1) if token else None,
        "body": body,
    }


@contextmanager
def existence_lock(
    path: Path,
    *,
    timeout_seconds: float,
    poll_seconds: float = 0.05,
) -> Iterator[LockHandle]:
    if timeout_seconds < 0:
        raise ValueError("lock timeout cannot be negative")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise Refused(
                    f"ComfyUI submit lock is held: {path}. The existing sentinel "
                    "was preserved; reconcile queue/history before any manual removal."
                ) from None
            time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
    handle = LockHandle(path=path, token=uuid.uuid4().hex, pid=os.getpid())
    try:
        line = f"pid={handle.pid} acquired_unix={time.time():.6f} token={handle.token}\n"
        os.write(descriptor, line.encode("ascii"))
    except BaseException:
        # Created by us a moment ago with O_EXCL, so it is ours to remove.
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    try:
        yield handle
    finally:
        os.close(descriptor)
        _release(handle)


def _carries_token(handle: LockHandle) -> bool:
    info = read_lock_body(handle.path)
    return info is not None and info["token"] == handle.token


def _release(handle: LockHandle) -> None:
    """Remove the lock only if it still carries our token.

    The token is checked, then re-read and re-checked immediately before the
    unlink.  Residual race: a foreign rewrite landing between that final read
    and the unlink is not detectable with plain files; the window is
    microseconds and requires another process to rewrite a lock we hold.
    """
    try:
        if _carries_token(handle) and _carries_token(handle):
            handle.path.unlink(missing_ok=True)
            handle.released = True
        else:
            handle.released = False
            handle.release_note = "lock no longer carries our token; left in place"
    except OSError as error:
        handle.released = False
        handle.release_note = f"could not release ({error!r}); may be stale, reconcile"
