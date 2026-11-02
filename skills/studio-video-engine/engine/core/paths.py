"""Path containment guard, and the read-side remap of absolute paths that hash-bound data still records.

Receipts, frozen plans and review configs record absolute paths as they were when written.  When a tree moves
(a drive is retired) those files are never edited: they are hash-bound evidence.  Instead ``machine.legacy_roots``
(``production-local/engine/machine.json``) names each retired root and where that tree lives now, and
:func:`resolve_data_path` tries that remap for a recorded path that is not on disk.  No drive letter lives in code.
"""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .errors import Refused

LEGACY_ROOTS_KEY = "legacy_roots"
_ROOTS_CACHE: dict[str, tuple[tuple[int, int], dict[str, str]]] = {}


def require_inside(path: Path, root: Path, label: str) -> Path:
    """Return ``path`` resolved, refusing anything that escapes ``root``."""
    resolved = Path(path).resolve()
    resolved_root = Path(root).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise Refused(f"{label} escaped {resolved_root}: {resolved}")
    return resolved


def is_absolute_path_text(value: Any) -> bool:
    """True for a string that is an absolute path on either platform (``C:\\x``, ``C:/x``, ``\\\\server\\s``, ``/x``)."""
    return isinstance(value, str) and bool(value) and (
        PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute())


def _default_machine_path() -> Path:
    from ..config.loader import DEFAULT_MACHINE_PATH  # lazy: the loader imports this module at import time

    return Path(DEFAULT_MACHINE_PATH)


def _roots_of(machine: Mapping[str, Any]) -> dict[str, str]:
    roots = machine.get(LEGACY_ROOTS_KEY) or {}
    if not isinstance(roots, Mapping):
        return {}
    return {str(old): str(new) for old, new in roots.items() if isinstance(old, str) and isinstance(new, str)}


def legacy_roots(machine: Mapping[str, Any] | None = None) -> dict[str, str]:
    """``machine.legacy_roots``: retired absolute root -> where that tree lives now.

    Without ``machine`` the default machine.json is read (re-read when its size or mtime changes).  A missing or
    unreadable file, or no key, is ``{}``: this helper never turns a read into an error."""
    if machine is not None:
        return _roots_of(machine)
    path = _default_machine_path()
    try:
        stat = path.stat()
    except OSError:
        return {}
    key, fresh = str(path), (stat.st_size, stat.st_mtime_ns)
    cached = _ROOTS_CACHE.get(key)
    if cached is not None and cached[0] == fresh:
        return dict(cached[1])
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    roots = _roots_of(data) if isinstance(data, Mapping) else {}
    _ROOTS_CACHE[key] = (fresh, roots)
    return dict(roots)


def _parts(text: str) -> list[str]:
    """Path components folded the way this OS compares them (drive letter and case on Windows, both separators)."""
    pure: PurePath = PureWindowsPath(text) if os.name == "nt" else PurePosixPath(text)
    return [os.path.normcase(part) for part in pure.parts]


def _under(text: str, root: str) -> tuple[str, ...] | None:
    """The components of ``text`` below ``root`` when ``root`` is a whole-component prefix of it, else None."""
    head, whole = _parts(root), _parts(text)
    if not head or len(whole) < len(head) or whole[: len(head)] != head:
        return None
    pure: PurePath = PureWindowsPath(text) if os.name == "nt" else PurePosixPath(text)
    return tuple(pure.parts[len(head):])


def _stays_inside(candidate: Path, root: Path) -> bool:
    """True when ``candidate`` resolves inside ``root``; symlinks, junctions and ``..`` are followed."""
    try:
        resolved = candidate.resolve(strict=False)
        resolved_root = root.resolve(strict=False)
    except OSError:
        return False
    return resolved == resolved_root or resolved_root in resolved.parents


def resolve_data_path(value: str | os.PathLike, machine: Mapping[str, Any] | None = None) -> Path:
    """Where a path recorded by data is read from now.

    A path that exists, a relative path, or one under no legacy root is returned as given (a caller's error then
    names the recorded path).  An absolute path that is not on disk and lies under a ``legacy_roots`` key is tried
    under that key's current root; the candidate is returned only when it exists and resolves inside that root."""
    given = Path(value)
    if given.exists() or not given.is_absolute():
        return given
    text = str(given)
    for old, new in legacy_roots(machine).items():
        below = _under(text, old)
        if below is None:
            continue
        if ".." in below:
            continue
        candidate = Path(new).joinpath(*below)
        if _stays_inside(candidate, Path(new)) and candidate.exists():
            return candidate
    return given
