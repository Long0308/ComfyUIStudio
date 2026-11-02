"""Stage files without overwriting anything (invariant I8).

Temp copy beside the target -> sha256 verify -> ``os.link`` into place.  ``os.link`` fails if
the target exists, so there is no overwrite and no race; an already-existing target is fine
only when it hashes to the expected value, otherwise ``Refused``.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from ..core.errors import Refused
from ..core.io import sha256_file
from ..core.paths import require_inside


def require_hash(path: Path, expected: str, label: str) -> str:
    path = Path(path)
    if not path.is_file():
        raise Refused(f"{label} is missing: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise Refused(f"{label} hash mismatch: expected {expected}, found {actual} ({path})")
    return actual


def input_target(input_dir: Path, name: str) -> Path:
    """Where ``name`` would live in the ComfyUI input folder (plain file names only)."""
    if not name or any(c in name for c in "/\\:") or Path(name).name != name or name in {".", ".."}:
        raise Refused(f"unsafe ComfyUI input name: {name!r}")
    return require_inside(Path(input_dir) / name, input_dir, "ComfyUI input")


def link_new_file(source: Path, target: Path, expected_sha256: str, label: str) -> Path:
    """Copy ``source`` to ``target`` without overwriting (temp -> verify -> link)."""
    target = Path(target)
    if target.exists():
        require_hash(target, expected_sha256, f"existing {label}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        require_hash(temporary, expected_sha256, f"temporary {label}")
        try:
            os.link(temporary, target)
        except FileExistsError:
            require_hash(target, expected_sha256, f"concurrent {label}")
    finally:
        temporary.unlink(missing_ok=True)
    require_hash(target, expected_sha256, f"staged {label}")
    return target


def stage_input(source: Path, input_dir: Path, name: str, expected_sha256: str) -> Path:
    """Stage a hash-verified input into the ComfyUI input folder."""
    require_hash(source, expected_sha256, "source for staging")
    return link_new_file(source, input_target(input_dir, name), expected_sha256, "ComfyUI input")


def input_state(input_dir: Path, name: str, expected_sha256: str) -> tuple[Path, str]:
    """``(target, "present"|"missing")``; a present file must hash-match (else ``Refused``)."""
    target = input_target(input_dir, name)
    if target.exists():
        require_hash(target, expected_sha256, "existing ComfyUI input")
        return target, "present"
    return target, "missing"
