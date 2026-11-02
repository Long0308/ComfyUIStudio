"""The transition preset library: ``schemas/transition-presets.json`` is the one source of truth.

A boundary row picks a preset by name (``type``); everything that differs between presets (frame
rules, params, direction, tail, window, shows_both, safe_for, dip schedule) is data in the catalog,
so adding or switching an effect never edits engine code.  Presets are a COMPOSITING layer: they are
applied after the shot videos exist and never ask for new shot video.

Pure functions; every rule violation is a ``Refused``.  ``label`` is the boundary description the
caller wants in the message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..config.loader import SKILL_ROOT
from ..core.errors import Refused

CATALOG_PATH = SKILL_ROOT / "schemas" / "transition-presets.json"
LEGACY_DIP = "dip_white_legacy"
APPROVED_DIP = "dip_white"
LEGACY_DIP_FRAMES = 9
SCHEDULE_SHOTS = ("out", "out_tail", "none", "in")


@dataclass(frozen=True)
class Preset:
    """One catalog entry (read-only view over its JSON)."""
    name: str
    data: dict

    def __getattr__(self, key: str) -> Any:
        try:
            return self.data[key]
        except KeyError as error:
            raise AttributeError(key) from error

    @property
    def ready(self) -> bool:
        return self.data["status"] == "ready"

    @property
    def schedule(self) -> list[dict] | None:
        rows = self.data.get("schedule")
        return [dict(row) for row in rows] if rows is not None else None


@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def presets() -> dict[str, Preset]:
    return {name: Preset(name, data) for name, data in catalog()["presets"].items()}


def ready_names() -> tuple[str, ...]:
    return tuple(name for name, data in catalog()["presets"].items() if data["status"] == "ready")


def get(name: str, *, label: str = "") -> Preset:
    """The preset called ``name``; unknown and planned (not implemented) ones are refused."""
    data = catalog()["presets"].get(name)
    prefix = f"{label}: " if label else ""
    if data is None:
        raise Refused(f"{prefix}unknown transition preset {name!r}; known: {', '.join(ready_names())}")
    if data["status"] != "ready":
        note = data.get("kids_note") or "its renderer is not built yet"
        raise Refused(f"{prefix}preset '{name}' is planned, not implemented ({note}); "
                      f"choose a ready preset: {', '.join(ready_names())}")
    return Preset(name, data)


def resolve_name(type_name: str, frames: int | None) -> str:
    """The preset a row's ``type`` means.  ``dip_white`` with 9 frames is the first build's schedule."""
    if type_name == APPROVED_DIP and frames == LEGACY_DIP_FRAMES:
        return LEGACY_DIP
    return type_name


# ---- frames ------------------------------------------------------------------------------------
def default_frames(preset: Preset) -> int:
    rule = preset.frames
    return rule["fixed"] if "fixed" in rule else rule["default"]


def frames_message(preset: Preset, frames: Any, label: str) -> str | None:
    """Why ``frames`` is not allowed for this preset (None when it is)."""
    rule = preset.frames
    if isinstance(frames, bool) or not isinstance(frames, int):
        return f"{label}: frames must be an integer, got {frames!r}"
    if "fixed" in rule:
        if frames == rule["fixed"]:
            return None
        if rule["fixed"] == 0:
            return f"{label}: frames must be 0 for {preset.name}, got {frames}"
        extra = (f" (the legacy {LEGACY_DIP} schedule is {LEGACY_DIP_FRAMES} frames)"
                 if preset.name == APPROVED_DIP else "")
        return f"{label}: the {preset.name} schedule is {rule['fixed']} frames, got {frames}{extra}"
    if frames < rule["min"] or frames > rule["max"]:
        return f"{label}: frames {frames} is outside {preset.name}'s {rule['min']}..{rule['max']}"
    if rule.get("even") and frames % 2:
        return f"{label}: {preset.name} needs an even frame count (got {frames})"
    return None


def candidate_frames(preset: Preset) -> list[int]:
    """Every legal frame count, ascending."""
    rule = preset.frames
    if "fixed" in rule:
        return [rule["fixed"]]
    step = 2 if rule.get("even") else 1
    return list(range(rule["min"], rule["max"] + 1, step))


def tail_frames(preset: Preset, frames: int) -> int:
    """Output frames that must come from the outgoing native tail (0 = no tail needed)."""
    rule = preset.tail_frames
    if rule == "none":
        return 0
    if rule == "all":
        return frames
    if rule == "half":
        return -(-frames // 2)
    return sum(1 for row in preset.data["schedule"] if row["shot"] == "out_tail")


# ---- direction -----------------------------------------------------------------------------------
def direction_message(preset: Preset, direction: Any, label: str) -> str | None:
    if preset.direction != "required":
        return None
    if direction in (-1, 1) and not isinstance(direction, bool):
        return None
    if preset.renders_as == "whip":
        return f"{label}: a whip needs direction -1 or +1 and an even frame count"
    if preset.renders_as == "card_slide":
        return f"{label}: a card slide needs direction -1 or +1"
    return f"{label}: {preset.name} needs direction -1 or +1 (got {direction!r})"


# ---- params --------------------------------------------------------------------------------------
def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _param_message(preset: Preset, key: str, spec: dict, value: Any, label: str) -> str | None:
    where = f"{label}: {preset.name} param {key!r}"
    kind = spec["type"]
    if kind == "boolean":
        return None if isinstance(value, bool) else f"{where} must be true or false, got {value!r}"
    if kind == "enum":
        return None if value in spec["values"] else f"{where} must be one of {spec['values']}, got {value!r}"
    ok = (isinstance(value, int) and not isinstance(value, bool)) if kind == "integer" else _is_number(value)
    if not ok:
        return f"{where} must be {'an integer' if kind == 'integer' else 'a number'}, got {value!r}"
    if "min" in spec and value < spec["min"] or "max" in spec and value > spec["max"]:
        return f"{where} must be between {spec.get('min')} and {spec.get('max')}, got {value!r}"
    return None


def check_params(preset: Preset, written: dict | None, label: str) -> None:
    written = written or {}
    if not isinstance(written, dict):
        raise Refused(f"{label}: params must be an object")
    known = preset.params
    for key in written:
        if key not in known:
            allowed = ", ".join(known) or "none"
            raise Refused(f"{label}: unknown param {key!r} for {preset.name} (allowed: {allowed})")
    for key, spec in known.items():
        if spec.get("required") and key not in written:
            what = "integer >= 0" if spec["type"] == "integer" else spec["type"]
            raise Refused(f"{label}: {'an iris' if preset.name == 'iris' else preset.name} needs "
                          f"params.{key} ({what})")
    for key, value in written.items():
        message = _param_message(preset, key, known[key], value, label)
        if message:
            raise Refused(message)


def resolve_params(preset: Preset, written: dict | None) -> dict:
    """Defaults filled for every param that has one (optional layout numbers are kept only when written)."""
    out = {key: spec["default"] for key, spec in preset.params.items()
           if not spec.get("optional") and not spec.get("required")}
    out.update(written or {})
    order = list(preset.params)
    return {key: out[key] for key in sorted(out, key=lambda k: order.index(k) if k in order else len(order))}


# ---- schedule / window / placement ----------------------------------------------------------------
def _schedule_times(preset: Preset) -> list[int]:
    return [row["t"] for row in preset.data["schedule"]]


def window(preset: Preset, frame: int, frames: int, params: dict) -> tuple[int, int]:
    """(start, end_exclusive) in global delivery frames."""
    mode = preset.window
    if mode == "at_boundary":
        return frame, frame
    if mode == "centred":
        return frame - frames // 2, frame + frames // 2
    if mode == "from_boundary":
        return frame, frame + frames
    if mode == "iris":   # the logo still hold (optional hold_frames) lies between the iris and the disc shrink
        return frame - frames, frame + params.get("hold_frames", 0) + params["disc_fade_frames"]
    times = _schedule_times(preset)
    return frame + min(times), frame + max(times) + 1


def _span(start: int, end: int) -> str:
    return f"f{start}" if start == end else f"f{start}-f{end}"


def _dip_text(preset: Preset, frame: int) -> str:
    rows = preset.data["schedule"]
    out = [r["t"] for r in rows if r["shot"] in ("out", "out_tail")]
    tail = [r["t"] for r in rows if r["shot"] == "out_tail"]
    peak = [r["t"] for r in rows if r["white"] == 1.0]
    back = [r["t"] for r in rows if r["shot"] == "in"]
    colour = (preset.data.get("overlay") or {}).get("colour")
    noun = {"#FFF8EC": "white", "#000000": "black"}.get(colour, preset.data["overlay"]["kind"])
    tail_part = f" ({_span(frame + min(tail), frame + max(tail))} on tail frames)" if tail else ""
    return (f"dip-to-{noun} around the cut: out {_span(frame + min(out), frame + max(out))}{tail_part}, "
            f"pure {noun} f{frame + peak[0]}, in {_span(frame + min(back), frame + max(back))}")


def placement_text(preset: Preset, frame: int) -> str:
    kind = preset.renders_as
    if "schedule" in preset.data:
        return _dip_text(preset, frame)
    if preset.name == "none":
        return "n/a"
    if kind == "cut":
        return "hard cut"
    if kind == "card_slide":
        return "outgoing card lingers sliding out while the incoming card slides in over the same frames"
    if kind == "plate_in":
        return "starts on the boundary and keeps settling into the end card"
    if preset.window == "centred":
        return "centred"
    if preset.window == "iris":
        return "ends on boundary"
    if preset.tail_frames == "none":
        return "starts on the boundary (one shot visible, no tail)"
    if preset.tail_frames == "half":
        return "starts on the boundary and runs on the outgoing tail (half the frames)"
    return "tail-only (starts on boundary)"
