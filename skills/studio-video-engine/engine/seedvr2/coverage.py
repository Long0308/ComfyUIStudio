"""Timeline coverage: every source frame the timeline reads must lie inside the restored scope.

First-production lesson (error-db ``seedvr2-plan-editorial-only-no-tail-handles``): the 4K run restored only
the editorial clips, while the review cut read NATIVE tail frames past each outgoing shot's
out-point, so the master lacked them and nothing noticed.  This module is the gate that notices.

* A **read** is "the timeline shows frames ``[start, end)`` of shot X" (shot-clip frame index;
  the editorial clip is ``native[0:N]``, so index ``i`` is the same frame in both files).
* The **scope** is what a plan restores per shot (``[0, clip frames)`` for a normal plan, plus any
  assembled tail clips from a master tail map).
* A **gap** is a read frame outside the scope.  ``check_coverage`` refuses (``Refused``, exit 1)
  and names every missing range; ``plan`` runs it before binding anything.

Reads come from the review config the editor built (``dialogue[].segments[]`` windows and
``motion.transitions[].outgoing_tail``), or from an explicit ``jjv/timeline-reads/v1`` document.
Pure data in, pure data out; the only I/O is ``load_reads`` / ``load_tail_map``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..core.errors import Refused
from ..core.io import canonical_sha256, read_json, sha256_file

READS_SCHEMA = "jjv/timeline-reads/v1"
TAIL_MAP_SCHEMAS = ("jjv/master-tail-map/v1", "mam-r27-master-tail-map/v1")
Range = tuple[int, int]


@dataclass(frozen=True)
class Read:
    """Frames ``[start, end)`` of ``shot`` that the timeline displays."""

    shot: str
    start: int
    end: int  # exclusive
    reason: str
    source: dict | None = None  # {path, sha256, frames}: the file these frames come from, if not the shot clip
    transition: dict | None = None  # {id, delivery_start_frame, output_frames}: what reads them (tails only)

    def as_dict(self) -> dict:
        return {"shot": self.shot, "start_frame": self.start, "end_frame_exclusive": self.end,
                "reason": self.reason, "source": self.source, "transition": self.transition}


@dataclass(frozen=True)
class Gap:
    shot: str
    start: int
    end: int  # exclusive
    reads: tuple[Read, ...]

    @property
    def frames(self) -> int:
        return self.end - self.start

    def reasons(self) -> list[str]:
        return sorted({r.reason for r in self.reads})

    def as_dict(self) -> dict:
        return {"shot": self.shot, "start_frame": self.start, "end_frame_exclusive": self.end,
                "frames": self.frames, "reasons": self.reasons()}


def _int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise Refused(f"{label} must be an integer >= {minimum}, got {value!r}")
    return value


def merge_ranges(ranges: Iterable[Range]) -> list[Range]:
    """Sorted, with overlapping or touching ranges joined."""
    merged: list[Range] = []
    for start, end in sorted(r for r in ranges if r[1] > r[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def uncovered(start: int, end: int, covered: Sequence[Range]) -> list[Range]:
    """The parts of ``[start, end)`` not inside the merged ``covered`` ranges."""
    missing, cursor = [], start
    for a, b in covered:
        if b <= cursor:
            continue
        if a >= end:
            break
        if a > cursor:
            missing.append((cursor, min(a, end)))
        cursor = max(cursor, b)
    if cursor < end:
        missing.append((cursor, end))
    return missing


def scope_from_shots(shots: Iterable[Mapping[str, Any]]) -> dict[str, list[Range]]:
    """Normal plan scope: each config shot restores its whole clip ``[0, frames)``."""
    return {s["shot"]: [(0, s["clip"]["frames"])] for s in shots}


def add_scope(scope: Mapping[str, Sequence[Range]], extra: Iterable[tuple[str, int, int]]) -> dict[str, list[Range]]:
    """A new scope with ``extra`` ``(shot, start, end)`` ranges added (never mutates ``scope``)."""
    out = {shot: list(ranges) for shot, ranges in scope.items()}
    for shot, start, end in extra:
        if shot not in out:
            raise Refused(f"extra scope names shot {shot!r}, which the plan does not have")
        out[shot].append((start, end))
    return {shot: merge_ranges(ranges) for shot, ranges in out.items()}


def find_gaps(reads: Sequence[Read], scope: Mapping[str, Sequence[Range]]) -> list[Gap]:
    """Every read frame outside ``scope``, merged per shot.  A read of an unknown shot is ``Refused``."""
    merged = {shot: merge_ranges(ranges) for shot, ranges in scope.items()}
    order = list(merged)
    pieces: dict[str, list[tuple[Range, Read]]] = {}
    for read in reads:
        if read.shot not in merged:
            raise Refused(f"timeline reads shot {read.shot!r} ({read.reason}), which is not a shot of the plan "
                          f"(shots: {', '.join(order)})")
        for piece in uncovered(read.start, read.end, merged[read.shot]):
            pieces.setdefault(read.shot, []).append((piece, read))
    gaps: list[Gap] = []
    for shot in order:
        found = pieces.get(shot, [])
        for start, end in merge_ranges(piece for piece, _ in found):
            gaps.append(Gap(shot, start, end, tuple(
                r for (a, b), r in found if a < end and b > start)))
    return gaps


def describe_gaps(gaps: Sequence[Gap]) -> str:
    return "; ".join(f"{g.shot} f{g.start}..f{g.end - 1} ({g.frames} frame(s): {', '.join(g.reasons())})"
                     for g in gaps)


def check_coverage(reads: Sequence[Read], scope: Mapping[str, Sequence[Range]]) -> dict:
    """Refuse (exit 1) when a read frame is outside the scope; otherwise return the coverage record."""
    gaps = find_gaps(reads, scope)
    if gaps:
        raise Refused(
            f"the timeline reads {sum(g.frames for g in gaps)} frame(s) outside the restored scope: "
            f"{describe_gaps(gaps)}. Restore them (jjv seedvr2 tails plan) or pass the assembled tail map "
            "(--tail-map); nothing was planned",
            evidence={"stage": "coverage_gap", "missing": [g.as_dict() for g in gaps]})
    return coverage_record(reads, scope)


def coverage_record(reads: Sequence[Read], scope: Mapping[str, Sequence[Range]]) -> dict:
    return {"checked": True, "ok": True, "read_count": len(reads),
            "reads_sha256": canonical_sha256([r.as_dict() for r in reads], mode="ascii"),
            "scope": {shot: [list(r) for r in merge_ranges(ranges)] for shot, ranges in scope.items()}}


# ---- reads from documents ---------------------------------------------------------------------
def _source_of(tail: dict, label: str) -> dict:
    path, sha, frames = tail.get("native_path"), tail.get("native_sha256"), tail.get("native_frames")
    if not isinstance(path, str) or not path or not isinstance(sha, str) or len(sha) != 64:
        raise Refused(f"{label}: outgoing_tail needs native_path and a 64-hex native_sha256")
    return {"path": path, "sha256": sha, "frames": _int(frames, f"{label} native_frames", minimum=1)}


def _tail_read(transition: dict, delivery_fps: int | None) -> Read | None:
    tail = transition.get("outgoing_tail")
    if not tail:
        return None
    label = f"transition {transition.get('id')!r} outgoing_tail"
    first = _int(tail.get("editorial_frames"), f"{label} editorial_frames", minimum=1)
    last = _int(tail.get("last_native_index_used"), f"{label} last_native_index_used")
    if last < first:
        return None  # the preset needs no frame past the editorial out-point
    source = _source_of(tail, label)
    if last > source["frames"] - 1:
        raise Refused(f"{label}: last native index {last} is past the native clip ({source['frames']} frames)")
    count = tail.get("tail_output_frames", transition.get("frames"))
    return Read(shot=tail["shot"], start=first, end=last + 1, reason=f"{transition.get('id')} outgoing tail",
                source=source, transition={"id": transition.get("id"),
                                           "delivery_start_frame": _int(tail.get("start_from_frame"),
                                                                        f"{label} start_from_frame"),
                                           "output_frames": _int(count, f"{label} output frames", minimum=1),
                                           "delivery_fps": delivery_fps})


def reads_from_review_config(doc: Mapping[str, Any]) -> list[Read]:
    """Reads of a review config: each dialogue segment's window ``[source_start, +native_frames)`` and each
    transition's outgoing tail ``[editorial_frames, last_native_index_used]``."""
    reads: list[Read] = []
    for entry in doc.get("dialogue") or []:
        for segment in entry.get("segments") or []:
            label = f"dialogue {entry.get('id')!r} segment"
            shot = segment.get("source_id")
            if not isinstance(shot, str) or not shot:
                raise Refused(f"{label} has no source_id")
            start = _int(segment.get("source_start_frame", 0), f"{label} source_start_frame")
            frames = _int(segment.get("native_frames"), f"{label} native_frames", minimum=1)
            reads.append(Read(shot, start, start + frames, f"dialogue {entry.get('id', shot)}"))
    transitions = (doc.get("motion") or {}).get("transitions") or doc.get("transitions") or []
    fps = doc.get("fps")
    delivery_fps = _int(fps, "document fps", minimum=1) if fps is not None else None
    reads.extend(r for r in (_tail_read(t, delivery_fps) for t in transitions) if r is not None)
    if not reads:
        raise Refused("no timeline reads found: expected dialogue[].segments[] or motion.transitions[].outgoing_tail")
    return reads


def _explicit_reads(doc: Mapping[str, Any]) -> list[Read]:
    reads = []
    for index, row in enumerate(doc.get("reads") or []):
        label = f"reads[{index}]"
        start = _int(row.get("start_frame"), f"{label} start_frame")
        end = _int(row.get("end_frame_exclusive"), f"{label} end_frame_exclusive", minimum=start + 1)
        source = row.get("source")
        if source is not None:
            source = {"path": source.get("path"), "sha256": source.get("sha256"),
                      "frames": _int(source.get("frames"), f"{label} source.frames", minimum=1)}
        reads.append(Read(row["shot"], start, end, str(row.get("reason") or "declared read"), source,
                          row.get("transition")))
    if not reads:
        raise Refused(f"{READS_SCHEMA} document holds no reads")
    return reads


def load_reads(path: Path) -> tuple[list[Read], str]:
    """``(reads, sha256 of the file)`` from a ``jjv/timeline-reads/v1`` document or a review config."""
    doc = read_json(Path(path))
    if not isinstance(doc, dict):
        raise Refused(f"{path}: reads document must be a JSON object")
    reads = _explicit_reads(doc) if doc.get("schema") == READS_SCHEMA else reads_from_review_config(doc)
    return reads, sha256_file(Path(path))


# ---- tail maps (what an assembled tail run restored) -------------------------------------------
def load_tail_map(path: Path, *, verify_files: bool = True) -> list[tuple[str, int, int]]:
    """``(shot, native_first, native_first + frames)`` per tail clip of a master tail map.

    With ``verify_files`` each clip (path relative to the map's folder) must exist and match its sha256:
    a map whose clips are gone covers nothing."""
    path = Path(path)
    doc = read_json(path)
    if not isinstance(doc, dict) or doc.get("schema") not in TAIL_MAP_SCHEMAS:
        raise Refused(f"{path}: not a master tail map (schema must be one of {TAIL_MAP_SCHEMAS})")
    ranges = []
    for index, row in enumerate(doc.get("tails") or []):
        label = f"{path.name} tails[{index}]"
        first = _int(row.get("native_first"), f"{label} native_first")
        frames = _int(row.get("frames"), f"{label} frames", minimum=1)
        if verify_files:
            clip = path.parent / str(row.get("clip") or "")
            if not clip.is_file():
                raise Refused(f"{label}: tail clip is missing: {clip}")
            if sha256_file(clip) != row.get("clip_sha256"):
                raise Refused(f"{label}: tail clip sha256 differs from the map: {clip}")
        ranges.append((row["shot"], first, first + frames))
    if not ranges:
        raise Refused(f"{path}: the tail map lists no tails")
    return ranges
