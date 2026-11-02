"""``editorial boundaries suggest``: the RULE layer (pure functions, no file or process access).

User rule (2026-10-27, cartoon-domain remotion skill, review v012): match the transition to what CHANGES.

* same seat / same camera angle, only props or poses change  -> hard cut + gentle push-in on the incoming shot
  (``cut_push``: 1.04 -> 1.00 over 12 frames); NEVER a white flash or a pan;
* camera angle or scene/place changes                          -> dip / flash / light, or a pan / whip;
* a dissolve (or any preset that shows both shots in one frame) is forbidden when props or characters are
  placed differently, and without continuity ``agree`` (``transitions.check_row`` enforces it).

"Same framing" is MEASURED, the same way Q3 does it: normalised correlation of the last frame of the outgoing
clip against the first frame of the incoming clip (4x4 block means of a 320x180 gray frame).  Three zones:

* ``ncc >= SAME_FRAMING_NCC_MIN``  (the Q3 number, read from the QA recipe) -> same framing;
* ``LAYOUT_CHANGE_NCC_MAX <= ncc < SAME_FRAMING_NCC_MIN``                   -> near-same: treated like same framing
  (a flash is NOT suggested although Q3 would still accept one below its threshold);
* ``ncc < LAYOUT_CHANGE_NCC_MAX``                                           -> new framing (angle or scene changed).

``LAYOUT_CHANGE_NCC_MAX`` is calibrated, not derived: on the first user-approved reference cut (review v015) the push boundaries
measure 0.540 (T1010) and 0.334 (T1310), the whip / dip boundaries 0.018 .. 0.136; 0.25 sits in the empty gap.
"""

from __future__ import annotations

import re
from typing import Any

from . import presets, transitions

SAME_FRAMING, NEAR_SAME, NEW_FRAMING, UNMEASURED = "same_framing", "near_same", "new_framing", "unmeasured"
LAYOUT_CHANGE_NCC_MAX = 0.25
CARRY_NCC_MIN = 0.95          # a declared carry must be pixel-continuous (the reference episode's carries measure 1.000)
ALIAS_PRESETS = ("dissolve", "wipe")   # "same renderer as ..." names: never offered as a separate choice
MOTION_CUE = re.compile(r"\b(eyeline|pointing|follow[- ]?pan|pan|whip|moves?|turns?|walks?)\b", re.IGNORECASE)
SIDE_WORD = re.compile(r"\b(left|right)\b", re.IGNORECASE)
RULES = {
    "R1_carry": "the clip is a pixel-continuous carry (shots.json entry): it takes no transition",
    "R2_same_framing_push": ("same seat and angle (measured): hard cut + gentle push-in, one shot visible per frame; "
                             "no flash, no pan, no dissolve unless continuity agrees"),
    "R3_near_same_push": ("near-same framing (measured, below the Q3 same-framing number but above the layout-change "
                          "number): treated as same seat, hard cut + push-in; a flash is not suggested"),
    "R4_motivated_whip": ("camera angle / place changed (measured) and the move is motivated by the action "
                          "(declared bridge or motion words in the motivation): whip"),
    "R4b_whip_no_tail": ("camera angle / scene changed (measured), no motivated move declared, and no tail handle for "
                         "a dip: a whip needs no tail (direction is a default: check it)"),
    "R5_new_framing_dip": ("camera angle / scene changed (measured), no motivated move declared: dip to white, "
                           "one shot visible per frame"),
    "R6_unmeasured_safe_cut": "framing could not be measured (clip frames missing): only a designed hard cut is safe",
    "R7_graphic_keep": "graphic boundary (intro, cards, end plate, outro): structural, the declared row is kept",
    "R8_intro_bloom": "title -> first shot: a short warm bloom bridges the title exit",
}


def classify(ncc: float | None, declared: str | None, same_min: float,
             change_max: float = LAYOUT_CHANGE_NCC_MAX) -> dict[str, Any]:
    """``{framing, source, conflict}``.  A declared ``same_framing`` can tighten a measured change (Q3 allows
    that); a declared ``new_framing`` can never turn a measured same-framing pair into a change."""
    if ncc is None:
        framing = {"same_framing": SAME_FRAMING, "new_framing": NEW_FRAMING}.get(declared or "", UNMEASURED)
        return {"framing": framing, "source": "declared" if framing != UNMEASURED else "none", "conflict": None}
    measured = SAME_FRAMING if ncc >= same_min else NEAR_SAME if ncc >= change_max else NEW_FRAMING
    if declared == "same_framing" and measured == NEW_FRAMING:
        return {"framing": SAME_FRAMING, "source": "declared",
                "conflict": f"declared same_framing but measured ncc {ncc:.3f} < {change_max}: declaration wins (tightens)"}
    if declared == "new_framing" and measured == SAME_FRAMING:
        return {"framing": measured, "source": "measured",
                "conflict": f"declared new_framing but measured ncc {ncc:.3f} >= {same_min}: measurement wins"}
    if declared == "new_framing" and measured == NEAR_SAME:
        return {"framing": NEW_FRAMING, "source": "declared", "conflict": None}
    return {"framing": measured, "source": "measured", "conflict": None}


def motion_cue(row: dict) -> tuple[bool, str | None]:
    """Is a camera move declared as motivated?  A declared ``g_bridge`` or a motion word in the motivation."""
    if row.get("g_bridge"):
        return True, "declared g_bridge"
    found = MOTION_CUE.search(str(row.get("motivation") or ""))
    return (True, f"motivation says {found.group(0)!r}") if found else (False, None)


def infer_direction(text: str | None) -> tuple[int, str]:
    """Whip direction from the LAST ``left`` / ``right`` word of the motivation; +1 when none (a guess)."""
    sides = SIDE_WORD.findall(text or "")
    if not sides:
        return 1, "default"
    return (1 if sides[-1].lower() == "right" else -1), "motivation"


def preference(framing: str, motivated: bool) -> list[tuple[str, str]]:
    """Ordered ``(preset, rule id)``: the first one that is available becomes the choice."""
    if framing in (SAME_FRAMING, NEAR_SAME):
        rule = "R2_same_framing_push" if framing == SAME_FRAMING else "R3_near_same_push"
        return [("cut_push", rule), ("cut", "R6_unmeasured_safe_cut")]
    if framing == NEW_FRAMING:
        order = ([("whip", "R4_motivated_whip"), ("dip_white", "R5_new_framing_dip")] if motivated
                 else [("dip_white", "R5_new_framing_dip"), ("whip", "R4b_whip_no_tail")])
        return order + [("cut", "R6_unmeasured_safe_cut")]
    return [("cut", "R6_unmeasured_safe_cut")]


def candidate_names(framing: str, continuity: str) -> list[str]:
    """The presets the rule allows for this framing (before the engine's own row rules are applied)."""
    ready = [p for p in presets.presets().values()
             if p.ready and "picture" in p.safe_for and not p.legacy and p.name not in ALIAS_PRESETS]
    if framing in (SAME_FRAMING, NEAR_SAME):
        names = [p.name for p in ready if p.category == "cut" and p.name != "none"]
        if framing == SAME_FRAMING and continuity == transitions.SAFE_CONTINUITY:
            names += [p.name for p in ready if p.category == "dissolve"]
        return names
    if framing == NEW_FRAMING:
        return [p.name for p in ready if p.category in ("dip", "light", "camera")] + ["cut"]
    return ["cut"]


def allowed(framing: str, continuity: str, picture_shots: frozenset, from_shot: str, to_shot: str) -> list[str]:
    """``candidate_names`` filtered through the engine's own row rules (class, continuity, picture / graphic)."""
    probe = {"from_shot": from_shot, "to_shot": to_shot, "class": "cut", "continuity": continuity,
             "motivation": "rule probe", "frame": 0}
    return [n for n in candidate_names(framing, continuity) if transitions.eligibility(probe, n, picture_shots) is None]


def carry_check(entry_kind: str, ncc: float | None) -> str | None:
    """A warning when the shots.json entry kind and the measured pixels disagree."""
    if ncc is None:
        return None
    if entry_kind == "carry" and ncc < CARRY_NCC_MIN:
        return f"shots.json says carry but the boundary frames differ (ncc {ncc:.3f} < {CARRY_NCC_MIN})"
    if entry_kind == "cut" and ncc >= CARRY_NCC_MIN:
        return f"shots.json says cut but the boundary frames are almost identical (ncc {ncc:.3f}): a carry may do"
    return None
