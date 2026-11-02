"""Hashing, canonical JSON and no-overwrite writes (domain-neutral).

``write_once`` is temp-file + ``os.link`` (never a half-written target); ``write_atomic`` is
temp-file + ``os.replace`` for mutable state.

Canonicalization is *explicit*: every caller names a mode.  ``"ascii"``
(``ensure_ascii=True``) is what the v004 plan hashes use; ``"utf8"``
(``ensure_ascii=False``) is what the v004 executor's own helper used.  The two
agree only for pure-ASCII documents, so receipts must record the mode.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Literal

from .errors import Refused, Uncertain

Mode = Literal["ascii", "utf8"]
_MODES = ("ascii", "utf8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _ensure_ascii(mode: str) -> bool:
    if mode not in _MODES:
        raise ValueError(f"canonical mode must be one of {_MODES}, got {mode!r}")
    return mode == "ascii"


def canonical_json(value: Any, *, mode: Mode) -> bytes:
    """Sorted-key, compact, UTF-8 encoded JSON bytes in the named mode."""
    text = json.dumps(
        value,
        ensure_ascii=_ensure_ascii(mode),
        sort_keys=True,
        separators=(",", ":"),
    )
    return text.encode("utf-8")


def canonical_sha256(value: Any, *, mode: Mode) -> str:
    return sha256_bytes(canonical_json(value, mode=mode))


def pretty_json(value: Any, *, mode: Mode) -> bytes:
    """Indented JSON with a trailing newline (receipt/file form)."""
    text = json.dumps(value, ensure_ascii=_ensure_ascii(mode), indent=2)
    return (text + "\n").encode("utf-8")


def _existing_matches(path: Path, payload: bytes, digest: str) -> str:
    """The target already exists: idempotent only for identical bytes."""
    if path.is_file() and path.read_bytes() == payload:
        return digest
    if path.is_dir():
        raise Refused(f"refusing to overwrite {path}: it is a directory")
    found = sha256_file(path) if path.is_file() else "not-a-file"
    raise Refused(f"refusing to overwrite {path}: expected {digest}, found {found}")


def _write_temporary(directory: Path, name: str, payload: bytes) -> Path:
    """Write ``payload`` to a fresh, fsynced sibling temp file (O_EXCL); return it."""
    temporary = directory / f".{name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # We created this temp file a moment ago with O_EXCL: it is ours to remove.
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def write_once(path: Path, payload: bytes) -> str:
    """Create ``path`` atomically (temp file + ``os.link``); return the payload sha256.

    The target never exists half-written: the bytes are written and fsynced to a
    sibling temp file first, then hard-linked into place, which fails if the
    target exists (no overwrite, no race).  Idempotent when the existing file
    holds identical bytes; a different existing file or a directory is never
    replaced: ``Refused`` is raised.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256_bytes(payload)
    if path.exists():
        return _existing_matches(path, payload, digest)
    temporary = _write_temporary(path.parent, path.name, payload)
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            return _existing_matches(path, payload, digest)
        except PermissionError:
            # Windows can report an existing directory as EACCES instead of EEXIST.
            if path.is_dir():
                raise Refused(f"refusing to overwrite {path}: it is a directory") from None
            raise
    finally:
        temporary.unlink(missing_ok=True)
    return digest


def write_atomic(path: Path, payload: bytes) -> str:
    """Replace ``path`` atomically (temp file + ``os.replace``): for MUTABLE state only
    (a job receipt that moves PREPARED -> SUBMITTED -> COMPLETED).  Immutable evidence
    uses :func:`write_once`.  Returns the payload sha256."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _write_temporary(path.parent, path.name, payload)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_bytes(payload)


def _stamped(value: Any, stamp: bool) -> Any:
    """Opt-in receipt header (``engine_tree_sha256``): only for evidence of a run, never for an artefact whose
    bytes must stay identical when the engine changes (write_once is idempotent only for identical bytes)."""
    if not stamp:
        return value
    from .provenance import stamp as add_header

    return add_header(value)


def write_json_atomic(path: Path, value: Any, *, mode: Mode, stamp: bool = False) -> str:
    return write_atomic(path, pretty_json(_stamped(value, stamp), mode=mode))


def write_json_once(path: Path, value: Any, *, mode: Mode, stamp: bool = False) -> str:
    return write_once(path, pretty_json(_stamped(value, stamp), mode=mode))


def _reject_constant(name: str) -> Any:
    """``NaN``/``Infinity`` are not JSON; Python accepts them by default and every ``<`` / ``>`` guard
    downstream then passes silently, so a non-finite number is an unreadable document."""
    raise ValueError(f"non-finite number {name} is not valid JSON")


def read_json(path: Path) -> Any:
    """Read JSON (BOM tolerant); malformed input is Uncertain, not Refused."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=_reject_constant)
    except (OSError, ValueError) as error:
        raise Uncertain(f"cannot read JSON {path}: {error}") from error
