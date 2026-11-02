"""Bind every dialogue WAV to its sha256 (receipt-WAV rule) and load it once.

A WAV outside the episode root needs ``--allow-outside``; a missing file is ``Uncertain`` (unreadable
input), a file whose bytes do not hash to the declared sha256 is ``Refused`` (the timing would describe
another recording).  Several lines may share one WAV: it is loaded once.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file
from ..core.paths import resolve_data_path
from ..qa.scope import require_scoped, shown_path
from .sound import Sound, load_sound


@dataclass(frozen=True)
class BoundWav:
    path: Path
    shown: str
    sha256: str
    sound: Sound


def resolve_path(declared: str, root: Path) -> Path:
    """The declared WAV where it lives now: relative to ``root``, or an absolute path (a retired root is remapped)."""
    path = Path(declared)
    return resolve_data_path(path if path.is_absolute() else Path(root) / path)


def bind_wavs(rows: Iterable[dict], root: Path, allow: Iterable[Path | str] = ()) -> dict[str, BoundWav]:
    """``{row id: BoundWav}`` for rows carrying ``id`` and ``audio{path, sha256}``."""
    allowed, cache, bound = tuple(allow), {}, {}
    for row in rows:
        name, audio = row["id"], row["audio"]
        path = require_scoped(resolve_path(audio["path"], root), root, allowed, f"{name} WAV")
        if not path.is_file():
            raise Uncertain(f"{name}: WAV not found: {shown_path(path, root)}")
        if path not in cache:
            digest = sha256_file(path)
            cache[path] = (digest, load_sound(path))
        digest, sound = cache[path]
        if digest != audio["sha256"]:
            raise Refused(f"{name}: WAV {shown_path(path, root)} hashes to {digest}, the input declares "
                          f"{audio['sha256']} (receipt-WAV rule)")
        bound[name] = BoundWav(path, shown_path(path, root), digest, sound)
    return bound
