"""Transition rules and placement (G-CUT): pure functions over declared boundary rows.

The effects themselves are data: ``schemas/transition-presets.json`` (loaded by :mod:`presets`).  A row
picks a preset by ``type``; this module applies the rules that every preset shares (all ``Refused``):

* ``cut`` is a designed hard cut (frames 0), ``none`` is a pixel-continuous carry; a hard cut may not
  use ``none`` and a carry may use nothing else;
* frames, direction and params must satisfy the preset's rule (``frames`` may be omitted: the preset
  default is used);
* a preset that shows both sides in one frame (``shows_both``) is forbidden when a PICTURE SHOT is on
  either side unless continuity is ``agree``; between two graphics it is allowed;
* a preset that is only for graphics is refused between two picture shots, and a picture-only preset
  between two graphics (a hard cut or carry is always fine);
* a preset with a tail runs on the outgoing clip's native TAIL frames (``ceil(0.8 * N)`` of them beyond
  what the editorial cut uses).  A missing or short handle is refused: **no GPU work is ever requested
  by the build** (the message says so);
* every row has a written motivation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..core.errors import Refused, Uncertain
from . import presets

TYPES = presets.ready_names()
# shows_both: one frame can show the outgoing AND the incoming side at once.  tail_only: starts on the
# boundary and runs on the outgoing native tail frames.  (Both are catalog fields; the tail an actual
# row needs comes from the preset's ``tail_frames`` rule.)
TYPE_PROPERTIES = {name: {"shows_both": data["shows_both"], "tail_only": data["tail_only"]}
                   for name, data in presets.catalog()["presets"].items() if data["status"] == "ready"}
BOTH_SHOTS_TYPES = frozenset(k for k, v in TYPE_PROPERTIES.items() if v["shows_both"])
TAIL_ONLY_TYPES = frozenset(k for k, v in TYPE_PROPERTIES.items() if v["tail_only"])
SAFE_CONTINUITY = "agree"
TAIL_NUM, TAIL_DEN = 4, 5          # ceil(0.8 * N) native tail frames
DIP_WHITE_COLOUR = "#FFF8EC"       # warm white, engine default (editorial style, not domain data)
# The first build's 9-row schedule (preset dip_white_legacy): peak at B+3, one shot visible per frame.
DIP_WHITE_SCHEDULE = tuple(dict(row) for row in presets.catalog()["presets"][presets.LEGACY_DIP]["schedule"])
NO_GPU = "no GPU work is requested; choose a preset without a tail or restore the tail separately"
HARD_CUT_ONLY = ("none", "cut")    # always allowed between any kind of boundary (subject to the class rule)
NOT_VISIBLE = ("cut", "cut_push", "none")  # no visible effect: the framing warning does not apply


def tail_frames_needed(count: int) -> int:
    """ceil(0.8 * count) in integer arithmetic."""
    return -(-count * TAIL_NUM // TAIL_DEN)


@dataclass(frozen=True)
class OutgoingShot:
    """What the tail rule needs to know about the outgoing physical shot."""
    shot: str
    editorial_frames: int      # native frames the editorial cut uses
    delivery_frames: int       # delivery frames the editorial cut shows


Probe = Callable[[Path], int]  # native clip -> number of frames


def _label(row: dict) -> str:
    frame = row.get("frame", "?")
    return f"boundary f{frame} {row['from_shot']} -> {row['to_shot']} ({row['type']})"


# ---- row normalisation ----------------------------------------------------------------------------
def resolve_row(row: dict) -> dict:
    """A copy of ``row`` with the preset resolved (legacy alias) and frames/direction/params filled in.

    Lenient on purpose: the rules live in :func:`check_row`, so every refusal keeps its own message.
    """
    name = presets.resolve_name(row["type"], row.get("frames"))
    preset = presets.get(name, label=_label(row))
    written = row.get("params")
    return {**row, "preset": name,
            "frames": row["frames"] if row.get("frames") is not None else presets.default_frames(preset),
            "direction": row.get("direction", 0),
            "params": presets.resolve_params(preset, written if isinstance(written, dict) else None)}


def row_kind(row: dict, picture_shots: frozenset) -> str:
    """``picture`` (both sides picture shots), ``graphic`` (neither) or ``mixed``."""
    pictures = {row["from_shot"], row["to_shot"]} & picture_shots
    return "picture" if len(pictures) == 2 else "graphic" if not pictures else "mixed"


def check_row(row: dict, picture_shots: frozenset = frozenset()) -> None:
    """Row-local rules; ``picture_shots`` are the names that are picture shots (not graphics)."""
    if "preset" not in row:
        row = resolve_row(row)
    label = _label(row)
    preset = presets.get(row["preset"], label=label)
    kind = row["preset"]
    if not str(row["motivation"]).strip():
        raise Refused(f"{label}: a motivation is required")
    if row["class"] == "cut" and kind == "none":
        raise Refused(f"{label}: a hard cut must have a designed transition type, not 'none' (use 'cut')")
    if row["class"] == "carry" and kind != "none":
        raise Refused(f"{label}: a carry is pixel-continuous and takes no transition (type must be 'none')")
    pictures = {row["from_shot"], row["to_shot"]} & picture_shots
    if preset.shows_both and pictures and row["continuity"] != SAFE_CONTINUITY:
        raise Refused(f"{label}: this type shows both sides in one frame (shows_both) and a picture shot "
                      f"({', '.join(sorted(pictures))}) is on one side; forbidden when continuity is "
                      f"{row['continuity']!r} (only 'agree' allows it); use dip_white, whip, cut_push or "
                      "card_flip_3d")
    _check_shape(row, preset, label)
    _check_suitability(row, preset, label, picture_shots)
    presets.check_params(preset, row["params"], label)
    if preset.window == "iris" and row["frames"] > row["frame"]:
        raise Refused(f"{label}: the iris would start before frame 0")


def _check_shape(row: dict, preset: presets.Preset, label: str) -> None:
    message = presets.direction_message(preset, row["direction"], label)
    if message:
        raise Refused(message)
    message = presets.frames_message(preset, row["frames"], label)
    if message is None:
        return
    if "needs an even frame count" in message and preset.renders_as == "whip":
        message = f"{label}: a whip needs direction -1 or +1 and an even frame count"
    elif "needs an even frame count" in message and preset.renders_as == "bloom":
        message = f"{label}: a bloom is centred on the boundary and needs an even frame count"
    raise Refused(message)


def _check_suitability(row: dict, preset: presets.Preset, label: str, picture_shots: frozenset) -> None:
    if preset.name in HARD_CUT_ONLY:
        return
    kind = row_kind(row, picture_shots)
    if kind == "picture" and "picture" not in preset.safe_for:
        raise Refused(f"{label}: {preset.name} is for graphic boundaries only (cards, end plate, intro/outro), "
                      "not between two picture shots")
    if kind == "graphic" and "graphic" not in preset.safe_for:
        raise Refused(f"{label}: {preset.name} is for picture shots only, not between two graphics "
                      "(cards, end plate, intro/outro); use card_slide, plate_in, iris, bloom or cut")


def row_warnings(row: dict, picture_shots: frozenset = frozenset()) -> list[str]:
    """Build warnings for one resolved row (never refusals)."""
    label = _label(row)
    warnings: list[str] = []
    if row["preset"] == presets.LEGACY_DIP:
        how = ("resolved from type dip_white with 9 frames; write type dip_white_legacy to keep it explicitly"
               if row["type"] == presets.APPROVED_DIP else "kept only to reproduce the first build")
        warnings.append(f"{label}: legacy 9-frame dip_white schedule in use (preset {presets.LEGACY_DIP}, {how}); "
                        "drop frames (or write dip_white) for the approved 8-row schedule")
    if (row.get("framing") == "same_framing" and row_kind(row, picture_shots) == "picture"
            and presets.get(row["preset"]).renders_as not in NOT_VISIBLE):
        warnings.append(f"{label}: framing is same_framing but {row['preset']} is a visible transition; "
                        "same seat/angle: use cut_push, flash or camera move only when angle/scene changes")
    return warnings


def eligibility(row: dict, name: str, picture_shots: frozenset) -> str | None:
    """Why preset ``name`` could not replace the row's preset here (class / continuity / kind), else None.

    Frames, direction and params are not judged: the author chooses them with the preset."""
    preset = presets.get(name)
    candidate = {**row, "type": name, "preset": name, "frames": presets.default_frames(preset),
                 "direction": 1 if preset.direction == "required" else 0,
                 "params": {key: spec["default"] for key, spec in preset.params.items() if not spec.get("optional")}}
    candidate.pop("framing", None)
    try:
        check_row(candidate, picture_shots)
    except Refused as error:
        return str(error)
    return None


# ---- tail ------------------------------------------------------------------------------------------
def _preset_of(row: dict) -> presets.Preset:
    name = row.get("preset") or presets.resolve_name(row["type"], row.get("frames"))
    return presets.get(name, label=_label(row))


def tail_output_frames(row: dict) -> int:
    """Output frames that come from the outgoing native tail (0 = the preset needs no tail)."""
    return presets.tail_frames(_preset_of(row), row["frames"])


def window(row: dict) -> tuple[int, int]:
    """(start, end_exclusive) of the transition in global delivery frames."""
    if "preset" not in row:
        row = resolve_row(row)
    return presets.window(_preset_of(row), row["frame"], row["frames"], row["params"])


def _tail_figures(count: int, outgoing: OutgoingShot, native: int, delivery_fps: int, native_fps: int) -> dict:
    available = native - outgoing.editorial_frames
    need = tail_frames_needed(count)
    last = math.ceil((outgoing.delivery_frames + count - 1) * native_fps / delivery_fps)
    return {"available": available, "need": need, "last": last, "ok": available >= need and last <= native - 1}


def check_tail(row: dict, outgoing: OutgoingShot | None, clip: Path | None, probe: Probe,
               delivery_fps: int, native_fps: int) -> dict | None:
    """The ``outgoing_tail`` record, or None when the preset needs no tail; Refused if too short."""
    count = tail_output_frames(row)
    if count == 0:
        return None
    label = _label(row)
    if outgoing is None:
        raise Refused(f"{label}: needs the native tail of its outgoing shot, but {row['from_shot']!r} is not a "
                      f"shot; {NO_GPU}")
    if clip is None:
        raise Refused(f"{label}: tail_clip is required (the outgoing shot's native clip); {NO_GPU}")
    if not clip.is_file():
        raise Uncertain(f"{label}: tail_clip not found: {clip.name}")
    native = probe(clip)
    figures = _tail_figures(count, outgoing, native, delivery_fps, native_fps)
    if not figures["ok"]:
        raise Refused(f"{label}: tail handle too short: {figures['available']} native tail frame(s) available, "
                      f"{figures['need']} needed (ceil(0.8 x {count})), last native index used "
                      f"{figures['last']}/{native - 1}; {NO_GPU}")
    return {"shot": outgoing.shot, "native_frames": native, "editorial_frames": outgoing.editorial_frames,
            "tail_frames_available": figures["available"], "tail_frames_needed": figures["need"],
            "tail_output_frames": count, "last_native_index_used": figures["last"],
            "start_from_frame": outgoing.delivery_frames}


def feasibility(row: dict, outgoing: OutgoingShot | None, clip: Path | None, probe: Probe,
                delivery_fps: int, native_fps: int) -> dict[str, dict]:
    """For EVERY ready preset: can it run on this boundary's existing tail handle (same rule as check_tail).

    ``{available, frames, needs_tail_frames, have_native_frames, max_frames, reason}``: ``frames`` is the
    row's own count for its current preset and the preset default otherwise; ``have_native_frames`` is the
    native tail available beyond the editorial cut (None without a handle); ``max_frames`` the largest legal
    frame count that still fits (None when none does).  Pure: nothing is rendered or requested.
    """
    native = probe(clip) if outgoing is not None and clip is not None and clip.is_file() else None
    have = None if native is None else native - outgoing.editorial_frames
    out: dict[str, dict] = {}
    for name in presets.ready_names():
        preset = presets.get(name)
        frames = row["frames"] if row.get("preset") == name else presets.default_frames(preset)
        count = presets.tail_frames(preset, frames)
        entry = {"available": True, "frames": frames, "needs_tail_frames": tail_frames_needed(count) if count else 0,
                 "have_native_frames": have, "max_frames": None, "reason": None}
        if count == 0:
            entry["max_frames"] = presets.candidate_frames(preset)[-1]
        elif native is None:
            entry.update(available=False, reason=_no_handle_reason(row, outgoing, clip))
        else:
            fits = [n for n in presets.candidate_frames(preset)
                    if _tail_figures(presets.tail_frames(preset, n), outgoing, native, delivery_fps, native_fps)["ok"]]
            entry["max_frames"] = fits[-1] if fits else None
            figures = _tail_figures(count, outgoing, native, delivery_fps, native_fps)
            if not figures["ok"]:
                entry.update(available=False, reason=(
                    f"tail handle too short: {figures['available']} native tail frame(s) available, "
                    f"{figures['need']} needed for {frames} frames (ceil(0.8 x {count})), last native index "
                    f"used {figures['last']}/{native - 1}"
                    + (f"; at most {entry['max_frames']} frames fit; " if fits else "; ") + NO_GPU))
        out[name] = entry
    return out


def _no_handle_reason(row: dict, outgoing: OutgoingShot | None, clip: Path | None) -> str:
    if outgoing is None:
        why = f"{row['from_shot']!r} is not a shot, so it has no native tail"
    elif clip is None:
        why = "no tail_clip is declared on this boundary"
    else:
        why = f"tail_clip {clip.name} was not found"
    return f"{why}; {NO_GPU}"


# ---- records ----------------------------------------------------------------------------------------
def placement_text(row: dict) -> str:
    if "preset" not in row:
        row = resolve_row(row)
    return presets.placement_text(_preset_of(row), row["frame"])


def build_transition(row: dict, tail: dict | None, tail_clip: dict | None) -> dict:
    """The events/config transition record for one validated (resolved) row."""
    if "preset" not in row:
        row = resolve_row(row)
    preset = _preset_of(row)
    start, end = window(row)
    record: dict[str, Any] = {
        "id": f"T{row['frame']}", "boundary": row["frame"], "from": row["from_shot"], "to": row["to_shot"],
        "class": row["class"], "type": row["type"], "preset": preset.name, "renders_as": preset.renders_as,
        "frames": row["frames"], "direction": row["direction"], "continuity": row["continuity"],
        "shows_both": preset.shows_both, "motivation": row["motivation"], "params": dict(row["params"]),
        "placement": presets.placement_text(preset, row["frame"]), "start": start, "end_exclusive": end}
    if "framing" in row:
        record["framing"] = row["framing"]
    if "g_bridge" in row:
        record["g_bridge"] = row["g_bridge"]
    if preset.renders_as == "whip":
        record.update({"out_frames": row["frames"] // 2, "in_frames": row["frames"] // 2})
    if preset.schedule is not None:
        overlay = dict(preset.data["overlay"])
        record.update({"schedule": preset.schedule, "overlay": overlay,
                       "incoming_hidden_frames": sum(1 for e in preset.schedule if e["t"] >= 0 and e["shot"] != "in")})
        if overlay["kind"] == "colour":
            record["white_colour"] = overlay["colour"]
    if preset.renders_as == "iris":
        record.update(dict(row["params"]))
    if tail is not None:
        record["outgoing_tail"] = {**tail, **(tail_clip or {})}
    return record


def audit_dip_schedule() -> None:
    """Every schedule preset: at most ONE shot per frame, exactly one pure-colour frame, and the shots
    sit on the right side of the boundary (asserted by the tests)."""
    for name in presets.ready_names():
        rows = presets.get(name).schedule
        if rows is None:
            continue
        if len([r for r in rows if r["white"] == 1.0]) != 1:
            raise Refused(f"{name}: the schedule must have exactly one pure-colour frame")
        times = [r["t"] for r in rows]
        if times != list(range(times[0], times[0] + len(times))):
            raise Refused(f"{name}: the schedule frames must be consecutive")
        for r in rows:
            if r["shot"] not in presets.SCHEDULE_SHOTS:
                raise Refused(f"{name}: schedule shot {r['shot']!r} is not one of {presets.SCHEDULE_SHOTS}")
            if (r["shot"] == "out" and r["t"] >= 0) or (r["shot"] in ("out_tail", "in") and r["t"] < 0):
                raise Refused(f"{name}: schedule shot {r['shot']!r} at t={r['t']} is on the wrong side of the boundary")
