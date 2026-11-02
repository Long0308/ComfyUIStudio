"""Verified-hash cache for Python callers (the same idea and trust boundary as ``remotion-kit/lib/hashcache.cjs``).

``sha256(path)`` is remembered under the file's stat identity ``{absolute path, size, mtime_ns, inode}``; an unchanged file costs one ``stat()``
instead of a read.  A master config build that verifies hundreds of chunk cores, finals and seam variants (several checks hash the same file)
re-reads gigabytes on every run; with this cache only a file whose identity changed is read again.

Declared trust boundary (tested): content changed while size, mtime and inode are all restored is NOT detected; ``rehash_all=True`` (the audit
path) ignores every entry and reads every byte.  A file hashed within ``RACY_SECONDS`` of its last write is not trusted on the next lookup
(the racy-timestamp rule).  The cache file is a separate JSON document from the node cache (inode numbers are not guaranteed to be
comparable across the two runtimes).

    cache = HashCache(Path("out/hash-cache-py.json"))
    digest = cache.sha256(path)       # hit: no read
    cache.save()
    cache.stats()                     # hits / misses / racy / bytes_read / bytes_not_read
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

SCHEMA = "jjk-engine/hash-cache-py/v1"
RACY_SECONDS = 2.0
CHUNK = 4 << 20


def sha256_stream(path: Path) -> str:
    """sha256 of a file by streaming (never holds the file in memory)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict:
    stat = os.stat(path)
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ino": stat.st_ino}


class HashCache:
    """Stat-identity keyed sha256 cache; ``save()`` writes atomically and only when something changed."""

    def __init__(self, file: Path | None = None, *, rehash_all: bool = False) -> None:
        self.file = Path(file).resolve() if file else None
        self.rehash_all = rehash_all
        self.entries: dict[str, dict] = {}
        self.dirty = False
        self.load_error: str | None = None
        self.counts = {"hits": 0, "misses": 0, "racy": 0, "bytes_read": 0, "bytes_not_read": 0}
        if self.file and self.file.exists():
            try:
                document = json.loads(self.file.read_text(encoding="utf-8-sig"))
                if document.get("schema") != SCHEMA or not isinstance(document.get("entries"), dict):
                    raise ValueError(f"not a {SCHEMA} document")
                self.entries = document["entries"]
            except (OSError, ValueError) as error:  # an unreadable cache is an empty cache, never a source of truth
                self.load_error = str(error)
                self.entries = {}
                self.dirty = True

    def sha256(self, path: Path | str) -> str:
        absolute = Path(path).resolve()
        if not absolute.exists():
            raise FileNotFoundError(f"cannot hash {absolute}: the file is missing")
        key = str(absolute)
        before = _identity(absolute)
        entry = self.entries.get(key)
        if not self.rehash_all and entry and all(entry.get(k) == before[k] for k in before):
            if entry.get("racy"):
                self.counts["racy"] += 1
            else:
                self.counts["hits"] += 1
                self.counts["bytes_not_read"] += before["size"]
                return entry["sha256"]
        hashed_at = time.time()
        digest = sha256_stream(absolute)
        self.counts["misses"] += 1
        self.counts["bytes_read"] += before["size"]
        if _identity(absolute) == before:  # the file changed while it was read: remember nothing
            racy = hashed_at - before["mtime_ns"] / 1e9 < RACY_SECONDS
            self.entries[key] = {**before, "sha256": digest, **({"racy": True} if racy else {})}
            self.dirty = True
        elif key in self.entries:
            del self.entries[key]
            self.dirty = True
        return digest

    def stats(self) -> dict:
        return {**self.counts, "files": len(self.entries), "rehash_all": self.rehash_all, **({"load_error": self.load_error} if self.load_error else {})}

    def save(self) -> bool:
        if self.file is None or not self.dirty:
            return False
        self.file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.file.with_name(f"{self.file.name}.tmp-{os.getpid()}")
        temporary.write_text(json.dumps({"schema": SCHEMA, "entries": self.entries}), encoding="utf-8")
        os.replace(temporary, self.file)
        self.dirty = False
        return True
