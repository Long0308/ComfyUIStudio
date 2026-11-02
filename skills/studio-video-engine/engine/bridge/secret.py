"""The bridge's shared secret: a random token in a local file (folder gitignored), compared in constant time.

The value is never printed, logged or returned by any route; only the file path is reported.
"""

from __future__ import annotations

import hmac
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from ..core.errors import Refused

MIN_LENGTH = 32
GITIGNORE = "*\n"


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="\n") as handle:
            handle.write(text)
        if os.name != "nt":
            os.chmod(tmp, 0o600)  # POSIX only; on Windows the folder ACL applies (see jobs.secure_dir)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def ensure_private_dir(folder: Path) -> Path:
    """Create ``folder`` with a ``.gitignore`` of ``*`` so nothing in it (secret, jobs) is ever committed."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / ".gitignore"
    if not marker.exists():
        _atomic_write(marker, GITIGNORE)
    return folder


def load_or_create(path: Path) -> str:
    """The secret in ``path``; created once (``secrets.token_urlsafe(32)``) when the file does not exist."""
    path = Path(path)
    ensure_private_dir(path.parent)
    if path.is_file():
        value = path.read_text(encoding="ascii").strip()
        if len(value) < MIN_LENGTH:
            raise Refused(f"{path} holds a secret shorter than {MIN_LENGTH} characters: delete it to regenerate")
        return value
    value = secrets.token_urlsafe(MIN_LENGTH)
    _atomic_write(path, value + "\n")
    return value


def authorized(headers: Any, secret: str) -> bool:
    """``Authorization: Bearer <secret>`` (or ``X-Bridge-Secret``), constant-time compare; empty never matches."""
    raw = str(headers.get("Authorization") or "")
    given = raw[len("Bearer "):].strip() if raw.startswith("Bearer ") else str(headers.get("X-Bridge-Secret") or "").strip()
    return bool(given) and bool(secret) and hmac.compare_digest(given.encode("utf-8"), secret.encode("utf-8"))
