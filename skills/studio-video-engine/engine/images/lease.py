"""Locks of the images engine (codex label locks, pool-state lock, review-publish lock) backed by an OS-level lock.

N20-fix2: the file-exists lock (O_EXCL + "reclaim an orphan") had a gap when three or more processes fought over an
orphan: two could hold it. The decision "do I hold it?" is now made ONLY by ``core.filelock.run_lock`` (msvcrt /
fcntl, released by the OS when the process dies, however it dies). There is no orphan to reclaim.

``<lock>`` is the file the OS lock lives on (created if missing, never deleted). ``<lock>.holder`` is informational:
the holder writes ``{pid, host, created_unix, token}`` there after it has the lock so a refusal can name who held it
last. It never decides anything and is only ever the LAST RECORDED holder, not proof of a live one.
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..core.errors import Refused
from ..core.filelock import run_lock


def side_lock_path(anchor: Path, name: str) -> Path:
    """A lock file OUTSIDE the tree of ``anchor`` (per user, per resolved anchor), for trees whose content is compared
    or shipped: an OS-lock file is never deleted (deleting it races), so it must not sit among the data."""
    import hashlib
    import tempfile

    key = hashlib.sha256(str(Path(anchor).resolve()).lower().encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "jjv-locks" / f"{name}-{key}.lock"


def holder_path(path: Path) -> Path:
    return Path(path).with_name(Path(path).name + ".holder")


def read_holder(path: Path) -> dict[str, Any] | None:
    """Last recorded holder of ``path`` (informational); None when none/unreadable."""
    try:
        data = json.loads(holder_path(path).read_text(encoding="ascii", errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("pid"), int) else None


def _describe(path: Path) -> str:
    holder = read_holder(path)
    if not holder:
        return "no holder was recorded"
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(holder["created_unix"])) if holder.get("created_unix") else "unknown time"
    return f"last recorded holder: pid {holder['pid']} on host {holder.get('host') or 'unknown'} since {since}"


@contextmanager
def lease(path: Path, *, timeout_seconds: float, what: str = "lock", poll_seconds: float = 0.05) -> Iterator[dict[str, Any]]:
    """Hold ``path`` exclusively. ``what`` names the lock in messages (e.g. ``codex image label lock acct1``)."""
    path = Path(path)
    mine = {"pid": os.getpid(), "host": socket.gethostname(), "created_unix": time.time(), "token": uuid.uuid4().hex}
    with ExitStack() as stack:
        try:
            stack.enter_context(run_lock(path, timeout_seconds=max(0.0, timeout_seconds), poll_seconds=poll_seconds))
        except Refused:  # only the acquisition is caught here: the body's own errors pass through untouched
            raise Refused(f"{what} is held by another process (waited {timeout_seconds:g} s; {_describe(path)}; "
                          f"not verified live); the lock file {path} is released by the OS when its holder exits") from None
        try:
            holder_path(path).write_text(json.dumps(mine), encoding="ascii")
        except OSError:
            pass  # the holder note is evidence, never a reason to fail the lock
        try:
            yield mine
        finally:
            if (read_holder(path) or {}).get("token") == mine["token"]:
                holder_path(path).unlink(missing_ok=True)
