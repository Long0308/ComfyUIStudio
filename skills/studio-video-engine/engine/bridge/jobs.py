"""Job documents on disk (``<state>/jobs/<id>/job.json``), one writer lock per process, background threads."""

from __future__ import annotations

import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..core.errors import Refused
from ..core.io import read_json, write_json_atomic

JOB_ID = re.compile(r"[a-z]{2}[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}")
ACTIVE_STATES = ("queued", "running")
FINAL_STATES = ("done", "partial", "failed")


def secure_dir(path: Path) -> bool:
    """chmod 0700 where the OS honours POSIX modes; returns whether it was applied.

    Windows: ``os.chmod`` cannot change NTFS ACLs, so nothing is applied and False is returned; the folder keeps the ACL it
    inherits from ``<machine.json folder>/bridge`` (measured by the review: Authenticated Users Modify).  Tighten it
    by hand (``icacls <folder> /inheritance:r /grant:r %USERNAME%:(OI)(CI)F``) - the bridge does not call icacls itself.
    """
    if os.name == "nt":
        return False
    os.chmod(path, 0o700)
    return True


class BridgeBusy(Exception):
    """A second job of a one-at-a-time kind (video) was asked for while one runs: HTTP 409."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()
        self._active: set[str] = set()
        self.video_lock = threading.Lock()
        self.running_video: str | None = None

    def folder(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise Refused(f"not a bridge job id: {job_id!r}")
        return self.root / job_id

    def new(self, prefix: str, doc: dict[str, Any]) -> str:
        job_id = f"{prefix}{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
        self.root.mkdir(parents=True, exist_ok=True)
        secure_dir(self.root)
        self.folder(job_id).mkdir()  # never reused: an existing folder raises
        secure_dir(self.folder(job_id))
        with self._lock:
            self._active.add(job_id)
            self._write(job_id, {"job_id": job_id, "created_utc": now_utc(), **doc})
        return job_id

    def _write(self, job_id: str, doc: dict[str, Any]) -> None:
        write_json_atomic(self.folder(job_id) / "job.json", doc, mode="ascii")

    def read(self, job_id: str) -> dict[str, Any] | None:
        path = self.folder(job_id) / "job.json"
        with self._lock:  # Windows: never read while this process replaces the file
            return read_json(path) if path.is_file() else None

    def update(self, job_id: str, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with self._lock:
            doc = self.read(job_id) or {"job_id": job_id}
            mutate(doc)
            doc["updated_utc"] = now_utc()
            self._write(job_id, doc)
            return doc

    def finish(self, job_id: str) -> None:
        with self._lock:
            self._active.discard(job_id)

    def view(self, job_id: str) -> dict[str, Any] | None:
        """The job as a client sees it; an active state left by a bridge that is gone reads ``interrupted``."""
        try:
            doc = self.read(job_id)
        except Refused:
            return None
        if doc is not None and doc.get("state") in ACTIVE_STATES and job_id not in self._active:
            doc = {**doc, "state": "interrupted", "note": "the bridge process that ran this job is gone; read the receipts"}
        return doc

    def spawn(self, job_id: str, work: Callable[[], None]) -> threading.Thread:
        def run() -> None:
            try:
                work()
            finally:
                self.finish(job_id)

        thread = threading.Thread(target=run, name=f"bridge-{job_id}", daemon=True)
        thread.start()
        return thread
