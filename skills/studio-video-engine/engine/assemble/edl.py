"""EDL (edit decision list) validation for the assemble verb.  Pure CPU: no ffmpeg call of its own.

Every refusal carries a stable code as the message prefix:

    EDL_SCHEMA          wrong schema id, fps, empty segments, bad/duplicate id, unknown kind
    EDL_SOURCE_MISSING  clip source / card logo / dialogue wav / sfx source does not exist
    EDL_SHA_MISMATCH    declared sha256 differs from the file (or is absent on a clip)
    EDL_SOURCE_UNREADABLE  the probe found no audio/video stream (or no video on a clip)
    EDL_BAD_FRAME_RANGE clip out of 0..frames, or a card/slate with frames < 1
    EDL_BAD_TRANSITION  unknown transition type, or a dissolve on the first segment / a neighbour
    EDL_AUDIO_REF       a dialogue/sfx row names an unknown segment or starts outside the film
    EDL_TIMING_MISSING  a spoken, non-placeholder dialogue row has no word-timing receipt (see ``timing.py``)
    EDL_TIMING_MISMATCH the timing receipt/QA sha, entry, WAV sha or words differ from the EDL
    EDL_AUDIO_FORMAT    a dialogue wav is not a .wav PCM16 stereo file at the domain sample rate (see ``stems.py``)
    EDL_SFX_POSITION    an sfx cue does not have exactly one valid at_s/at_f position
    OUTPUT_EXISTS       the write-once output (or work folder) already exists

The schema id, fps, kinds and transitions are caller-supplied (they are domain data).  The media
probe is injected so tests never run ffprobe: ``probe(path) -> {"frames", "fps", "width", ...}``.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..core.errors import Refused
from ..core.io import sha256_file

EDL_SCHEMA = "EDL_SCHEMA"
EDL_SOURCE_MISSING = "EDL_SOURCE_MISSING"
EDL_SHA_MISMATCH = "EDL_SHA_MISMATCH"
EDL_SOURCE_UNREADABLE = "EDL_SOURCE_UNREADABLE"
EDL_BAD_FRAME_RANGE = "EDL_BAD_FRAME_RANGE"
EDL_BAD_TRANSITION = "EDL_BAD_TRANSITION"
EDL_AUDIO_REF = "EDL_AUDIO_REF"
EDL_SFX_POSITION = "EDL_SFX_POSITION"
OUTPUT_EXISTS = "OUTPUT_EXISTS"

_CODE = re.compile(r"^([A-Z][A-Z0-9_]+): ")

Probe = Callable[[Path], Mapping[str, Any]]

def refuse(code: str, message: str) -> None:
    """Raise one stable refusal (the code is the message prefix, like every ported assembler refusal)."""
    raise Refused(f"{code}: {message}")

def code_of(error: BaseException) -> str | None:
    """The refusal code of a caught ``Refused`` (``None`` when the message has no code prefix)."""
    match = _CODE.match(str(error))
    return match.group(1) if match else None

def abs_path(value: Any, base: Path) -> Path:
    """Resolve an EDL path: absolute stays put, relative is read from ``base``."""
    path = Path(value)
    return path if path.is_absolute() else Path(base) / path

def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None

def sfx_position_s(entry: Mapping[str, Any], fps: int) -> float:
    """Return one SFX cue's segment-relative position: exactly one of at_s or at_f is required.

    A negative or non-numeric at_s keeps its historical refusal, EDL_AUDIO_REF, raised here.
    validate_edl's range check still handles a negative finite at_s the same way.
    """
    has_seconds = "at_s" in entry
    has_frame = "at_f" in entry
    label = entry.get("id") or entry.get("cue_id") or "?"
    if has_seconds == has_frame:
        found = "both at_s and at_f" if has_seconds else "neither at_s nor at_f"
        refuse(EDL_SFX_POSITION, f"sfx/{label}: exactly one of at_s or at_f is required (found {found})")
    if has_frame:
        frame = _as_int(entry["at_f"])
        if frame is None or frame < 0:
            refuse(EDL_SFX_POSITION, f"sfx/{label}: at_f must be a non-negative integer frame")
        return frame / fps
    seconds = entry["at_s"]
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds):
        refuse(EDL_AUDIO_REF, f"sfx/{label}: starts outside the film")
    return float(seconds)

def sfx_offset_samples(entry: Mapping[str, Any], segment_start_f: int, rate: int, fps: int) -> int:
    """Resolve an SFX cue to an exact sample offset; at_f uses the integer frame grid without time rounding."""
    per_frame = rate // fps
    base = segment_start_f * per_frame
    if "at_f" in entry:
        frame = _as_int(entry["at_f"])
        if frame is None or frame < 0:
            sfx_position_s(entry, fps)  # raises the named refusal
        return base + int(frame) * per_frame
    return base + int(round(sfx_position_s(entry, fps) * rate))

def validate_edl(
    edl: Mapping[str, Any],
    base: Path,
    *,
    schema: str,
    fps: int,
    kinds: Sequence[str],
    transitions: Sequence[str],
    probe: Probe,
) -> dict:
    """Validate one EDL and return ``{"segments", "total_frames", "shas"}``; raise ``Refused`` otherwise.

    ``segments`` carry the normalised timeline (``start_f``, ``dur_f``, ``trans``) and, for clips,
    the resolved ``src_path``/``probe``; ``shas`` maps a segment id to the hash it bound.
    """
    if edl.get("schema") != schema:
        refuse(EDL_SCHEMA, f"schema must be {schema!r}, got {edl.get('schema')!r}")
    if _as_int(edl.get("fps")) != fps:
        refuse(EDL_SCHEMA, f"fps must be {fps}")
    if not edl.get("film_id") or not isinstance(edl.get("film_id"), str):
        refuse(EDL_SCHEMA, "film_id (a non-empty string) is required: it names the outputs")
    segments = edl.get("segments")
    if not isinstance(segments, list) or not segments:
        refuse(EDL_SCHEMA, "segments must be a non-empty list")

    seen: set[str] = set()
    rows: list[dict] = []
    shas: dict[str, str] = {}
    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping):
            refuse(EDL_SCHEMA, f"segment #{index} must be an object")
        sid = segment.get("id")
        if not isinstance(sid, str) or not sid or sid in seen:
            refuse(EDL_SCHEMA, f"segment #{index}: id missing or duplicated ({sid!r})")
        seen.add(sid)
        kind = segment.get("kind")
        if kind not in kinds:
            refuse(EDL_SCHEMA, f"{sid}: kind must be one of {tuple(kinds)}")
        row = dict(segment)
        if kind == "clip":
            source = segment.get("source")
            if not isinstance(source, str) or not source or not abs_path(source, base).is_file():
                refuse(EDL_SOURCE_MISSING, f"{sid}: source {source!r} does not exist")
            src = abs_path(source, base)
            declared = segment.get("sha256")
            if not isinstance(declared, str) or not declared:
                refuse(EDL_SHA_MISMATCH, f"{sid}: sha256 is required for a clip source")
            actual = sha256_file(src)
            if actual != declared:
                refuse(EDL_SHA_MISMATCH, f"{sid}: EDL sha {declared[:12]} != file sha {actual[:12]} ({src.name})")
            shas[sid] = actual
            info = probe(src)
            if "frames" not in info:
                refuse(EDL_SOURCE_UNREADABLE, f"{sid}: source has no video stream")
            first, last = _as_int(segment.get("in_frame")), _as_int(segment.get("out_frame"))
            if first is None or last is None or first < 0 or last <= first or last > int(info["frames"]):
                refuse(EDL_BAD_FRAME_RANGE, f"{sid}: frames [{segment.get('in_frame')},{segment.get('out_frame')}) "
                       f"outside 0..{info['frames']}")
            for field in ("fade_in_frames", "fade_out_frames"):
                if field not in segment:
                    continue
                frames = _as_int(segment[field])
                if frames is None or frames < 0 or frames > last - first:
                    refuse(EDL_BAD_FRAME_RANGE, f"{sid}: {field} must be an integer in 0..{last - first}")
            row.update(src_path=str(src), probe=dict(info), dur_f=last - first)
        else:
            frames = _as_int(segment.get("frames"))
            if frames is None or frames < 1:
                refuse(EDL_BAD_FRAME_RANGE, f"{sid}: {kind} needs integer frames >= 1")
            row.update(dur_f=frames, in_frame=0, out_frame=frames)
            if kind == "card":
                logo = segment.get("logo")
                if not isinstance(logo, str) or not logo or not abs_path(logo, base).is_file():
                    refuse(EDL_SOURCE_MISSING, f"{sid}: logo {logo!r} does not exist")
                logo_path = abs_path(logo, base)
                digest = sha256_file(logo_path)
                declared = segment.get("logo_sha256")
                if declared and digest != declared:
                    refuse(EDL_SHA_MISMATCH, f"{sid}: logo sha {digest[:12]} != declared {str(declared)[:12]}")
                shas[sid] = digest
                row["logo_path"] = str(logo_path)
        rows.append(row)

    total = 0
    for index, row in enumerate(rows):
        transition = row.get("transition_in") or {"type": "cut"}
        if not isinstance(transition, Mapping):
            refuse(EDL_BAD_TRANSITION, f"{row['id']}: transition_in must be an object")
        kind = transition.get("type", "cut")
        frames = _as_int(transition.get("frames", 0)) or 0
        if kind not in transitions:
            refuse(EDL_BAD_TRANSITION, f"{row['id']}: unknown transition {kind!r} (allowed: {tuple(transitions)})")
        if kind != "cut":
            if index == 0 or frames < 1 or frames >= row["dur_f"] or frames >= rows[index - 1]["dur_f"]:
                refuse(EDL_BAD_TRANSITION, f"{row['id']}: {kind} {frames} frames invalid (first segment or >= a neighbour)")
        else:
            frames = 0
        row["trans"] = (kind, frames)
        row["start_f"] = total - frames if index else 0
        total = row["start_f"] + row["dur_f"]
    if total <= 0:
        refuse(EDL_SCHEMA, "the timeline is empty")

    from .timing import check_dialogue_timing  # lazy: timing.py imports this module

    for key in ("dialogue", "sfx"):
        rows_by_id = {row["id"]: row for row in rows}
        entries = edl.get(key, [])
        if not isinstance(entries, list):
            refuse(EDL_SCHEMA, f"{key} must be a list")
        if key == "dialogue":
            for entry in entries:
                if isinstance(entry, Mapping):
                    check_dialogue_timing(entry, base)
        for entry in entries:
            if not isinstance(entry, Mapping):
                refuse(EDL_SCHEMA, f"{key}: every entry must be an object")
            label = entry.get("id") or entry.get("cue_id") or "?"
            target = rows_by_id.get(entry.get("segment"))
            if target is None:
                refuse(EDL_AUDIO_REF, f"{key}: unknown segment {entry.get('segment')!r}")
            start = sfx_position_s(entry, fps) if key == "sfx" else entry.get("at_s", 0)
            if not isinstance(start, (int, float)) or isinstance(start, bool) or not math.isfinite(start) or start < 0 \
                    or target["start_f"] / fps + start >= total / fps:
                refuse(EDL_AUDIO_REF, f"{key}/{label}: starts outside the film")
            if key == "sfx":
                for field in ("fade_in_s", "fade_out_s"):
                    if field not in entry:
                        continue
                    fade = entry[field]
                    if (not isinstance(fade, (int, float)) or isinstance(fade, bool)
                            or not math.isfinite(fade) or fade < 0):
                        refuse(EDL_SFX_POSITION, f"sfx/{label}: {field} must be a finite non-negative number")
            if key == "dialogue":
                if "text" in entry and not isinstance(entry["text"], str):
                    refuse(EDL_SCHEMA, f"dialogue/{label}: text must be a string")
                window = entry.get("speech_window_s")
                if window is not None:
                    if not isinstance(window, list) or len(window) != 2:
                        refuse(EDL_SCHEMA, f"dialogue/{label}: speech_window_s must be [start_s, end_s]")
                    first_s, last_s = window
                    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                               for value in window) or first_s < 0 or last_s <= first_s:
                        refuse(EDL_SCHEMA, f"dialogue/{label}: speech_window_s needs finite 0 <= start < end")
            for field in ("source", "wav"):
                value = entry.get(field)
                if not value:
                    continue
                path = abs_path(value, base)
                if not path.is_file():
                    refuse(EDL_SOURCE_MISSING, f"{key}: {field} {value!r} does not exist")
                declared = entry.get("sha256")
                if declared and sha256_file(path) != declared:
                    refuse(EDL_SHA_MISMATCH, f"{key}: sha mismatch for {path.name}")
    music = edl.get("music") or {}
    if not isinstance(music, Mapping):
        refuse(EDL_SCHEMA, "music must be an object")
    if music.get("source"):
        path = abs_path(music["source"], base)
        if not path.is_file():
            refuse(EDL_SOURCE_MISSING, f"music: source {music['source']!r} does not exist")
        declared = music.get("sha256")
        if declared and sha256_file(path) != declared:
            refuse(EDL_SHA_MISMATCH, f"music: sha mismatch for {path.name}")
    return {"segments": rows, "total_frames": total, "shas": shas}

def guard_outputs(paths: Iterable[Path]) -> None:
    """Write-once guard: any existing output or work folder refuses with ``OUTPUT_EXISTS``."""
    for path in paths:
        if Path(path).exists():
            refuse(OUTPUT_EXISTS, f"{Path(path).name} exists; use a new --tag (write-once)")
