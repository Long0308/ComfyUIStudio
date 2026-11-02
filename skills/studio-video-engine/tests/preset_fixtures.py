"""Shared helpers of the preset tests (T-E42): the catalog read as plain JSON, plus independent restatements of
its rules, so a rule the engine forgets is a failing test.  Real ep04 boundary 1010 (S03_B -> S04_A, picture to
picture, 7 native tail frames) is switched to the preset under test."""

from __future__ import annotations

import json
from pathlib import Path

from editorial_fixtures import Inputs, probe_returning

SKILL = Path(__file__).resolve().parents[1]
CATALOG = json.loads((SKILL / "schemas" / "transition-presets.json").read_text("utf-8"))
PRESETS = CATALOG["presets"]
NEW_PRESETS = ["cut", "cut_push", "push_slide", "pan_motivated", "zoom_through", "zoom_out", "iris_circle",
               "iris_diamond", "clock_wipe", "wipe_linear", "blinds", "crossfade", "blur_crossfade", "focus_pull",
               "dip_white", "dip_white_legacy", "dip_black", "light_leak", "film_burn", "card_flip_3d"]
TAIL_PRESETS = [n for n in NEW_PRESETS if PRESETS[n]["tail_frames"] != "none"]
NO_TAIL_PRESETS = [n for n in NEW_PRESETS if PRESETS[n]["tail_frames"] == "none"]
FREE_FRAMES = [n for n in NEW_PRESETS if "fixed" not in PRESETS[n]["frames"]]
FIXED_FRAMES = [n for n in NEW_PRESETS if "fixed" in PRESETS[n]["frames"]]
WITH_PARAMS = [n for n in NEW_PRESETS if PRESETS[n]["params"]]
GENEROUS = probe_returning(140)   # S03_B: 100 native frames used -> 40 native tail frames


def default_frames(p: dict) -> int:
    rule = p["frames"]
    return rule["fixed"] if "fixed" in rule else rule["default"]


def tail_count(p: dict, frames: int) -> int:
    rule = p["tail_frames"]
    if rule == "none":
        return 0
    if rule == "all":
        return frames
    if rule == "half":
        return -(-frames // 2)
    return sum(1 for entry in p["schedule"] if entry["shot"] == "out_tail")


def window_of(p: dict, frame: int, frames: int) -> tuple[int, int]:
    mode = p["window"]
    if mode == "at_boundary":
        return frame, frame
    if mode == "centred":
        return frame - frames // 2, frame + frames // 2
    if mode == "from_boundary":
        return frame, frame + frames
    times = [entry["t"] for entry in p["schedule"]]
    return frame + min(times), frame + max(times) + 1


def default_params(p: dict) -> dict:
    return {key: spec["default"] for key, spec in p["params"].items() if not spec.get("optional")}


def use(inputs: Inputs, name: str, **extra) -> dict:
    """Boundary 1010 (S03_B -> S04_A, picture to picture, 7 native tail frames) switched to ``name``."""
    p, row = PRESETS[name], inputs.row(1010)
    row.pop("frames", None)
    row.update({"type": name, "continuity": "agree" if p["shows_both"] else "mismatch",
                "direction": 1 if p["direction"] == "required" else 0, **extra})
    return row


def record_at(built, frame: int = 1010) -> dict:
    return next(t for t in built.events["transitions"] if t["boundary"] == frame)



