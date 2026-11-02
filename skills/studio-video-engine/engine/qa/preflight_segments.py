"""Picture pieces (source clips on the timeline) of a review config, for the pixel-free preflight.

Two config shapes exist and both are read: the engine-built one (``segments[]`` rows with a global
``start_frame``, ``duration_frames`` and ``clip{path}``) and the hand-built one (``source_id``, ``path``,
``delivery_frames``, ``relative_start_frame`` relative to the dialogue row).  A piece that cannot be read
cleanly is skipped here; the check that needs it then reports UNCERTAIN, it never guesses.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.paths import resolve_data_path


@dataclass(frozen=True)
class Piece:
    id: str
    logical: str
    start: int
    frames: int
    native_frames: int
    path: Path | None

    @property
    def end(self) -> int:
        return self.start + self.frames


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def resolve(raw: Any, root: Path) -> Path | None:
    """A declared file where it lives now: relative to ``root``, or absolute (a retired root is remapped)."""
    if not raw:
        return None
    path = Path(str(raw))
    return resolve_data_path(path if path.is_absolute() else Path(root) / path)


def _start(entry: dict, seg: dict) -> int | None:
    if _int(seg.get("start_frame")) is not None:
        return seg["start_frame"]
    base, rel = _int(entry.get("start_frame")), _int(seg.get("relative_start_frame", 0))
    return None if base is None or rel is None else base + rel


def pieces(config: dict, root: Path) -> tuple[Piece, ...]:
    out: list[Piece] = []
    for entry in config.get("dialogue") or []:
        for seg in entry.get("segments") or []:
            if not isinstance(seg, dict):
                continue
            clip = seg.get("clip") if isinstance(seg.get("clip"), dict) else {}
            start = _start(entry, seg)
            frames = _int(seg.get("delivery_frames", seg.get("duration_frames")))
            native = _int(seg.get("native_frames")) or frames
            if start is None or not frames or frames <= 0:
                continue
            out.append(Piece(id=str(seg.get("source_id") or seg.get("shot") or entry.get("id")),
                             logical=str(entry.get("id")), start=start, frames=frames, native_frames=native or frames,
                             path=resolve(seg.get("path") or clip.get("path"), root)))
    return tuple(sorted(out, key=lambda p: p.start))


def ending_at(items: tuple[Piece, ...], boundary: int) -> Piece | None:
    return next((p for p in items if p.end == boundary), None)


def starting_at(items: tuple[Piece, ...], boundary: int) -> Piece | None:
    return next((p for p in items if p.start == boundary), None)


def native_index(piece: Piece, frame: int) -> int:
    """Index into the SOURCE clip that delivery ``frame`` shows (native_frames / delivery frames ratio)."""
    index = int((frame - piece.start) * piece.native_frames / piece.frames)
    return max(0, min(piece.native_frames - 1, index))
