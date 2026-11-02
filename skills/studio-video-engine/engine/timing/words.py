"""Step 2 on a whole document: first-word rule, then the all-words rule, with the v004 integrity checks.

``correct_entry`` takes the words of one line (recognised just now, or supplied) and the line's WAV and
returns the corrected words plus the audit rows; only ``start_s`` / ``start_frame`` of words may differ
from the input once the first-word step is done, never earlier, ends untouched.
"""

from __future__ import annotations

import copy

from ..core.errors import Refused
from .firstword import calibrate_first_word
from .onset import correct_word
from .sound import Sound

MOVABLE = ("start_s", "start_frame")
FIRST_WORD_MOVABLE = MOVABLE + ("end_s", "end_frame", "end_frame_exclusive", "boundary_calibrated_start")


def correct_entry(entry_id: str, window: tuple[int, int], words: list[dict], sound: Sound, recipe: dict, fps: float,
                  *, first_word: bool = True) -> tuple[list[dict], dict]:
    """``(words, audit)``: the line-first rule (optional) then the rule on EVERY word, integrity-checked.

    ``window = (start_frame, end_frame_exclusive)`` of the line; ``audit = {"first_word": report | None,
    "rows": [per-word rows with entry id]}``.  A contract violation is Refused (nothing is returned)."""
    start_frame = window[0]
    current, first_report = (copy.deepcopy(words), None)
    if first_word and words:
        current, first_report = calibrate_first_word(sound, words, start_frame, recipe["first_word"], fps, label=entry_id)
        if first_report["moved"]:
            current[0]["boundary_calibrated_start"] = True
        require_integrity(integrity_errors(entry_id, window, words, current, FIRST_WORD_MOVABLE, order=False))
    corrected = copy.deepcopy(current)
    rows = []
    for word, target in zip(current, corrected):
        row = {"entry": entry_id, **correct_word(sound, word, start_frame, recipe["all_words"], fps)}
        rows.append(row)
        if row["moved"]:
            target["start_s"], target["start_frame"] = row["new_start_s"], row["new_start_frame"]
    require_integrity(integrity_errors(entry_id, window, current, corrected, MOVABLE))
    return corrected, {"first_word": first_report, "rows": rows}


def integrity_errors(entry_id: str, window: tuple[int, int], before: list[dict], after: list[dict],
                     movable: tuple[str, ...], *, order: bool = True) -> list[str]:
    """Violations of the v004 contract between the words that went in and the words that came out."""
    errors, (first, end) = [], window
    for old, new in zip(before, after):
        label = f"{entry_id} {old['text']}"
        for key in old:
            if old[key] != new[key] and key not in movable:
                errors.append(f"{label}: field {key} changed")
        if new["start_frame"] < old["start_frame"]:
            errors.append(f"{label}: moved earlier")
        if new["start_frame"] >= new["end_frame_exclusive"]:
            errors.append(f"{label}: start >= end")
    if not order:
        return errors
    previous = first - 1
    for word in after:
        if word["start_frame"] < previous:
            errors.append(f"{entry_id}: non-monotonic at {word['text']}")
        if not first <= word["start_frame"] < end or word["end_frame_exclusive"] > end:
            errors.append(f"{entry_id}: {word['text']} outside its window f{first}-f{end}")
        previous = word["start_frame"]
    return errors


def require_integrity(errors: list[str]) -> None:
    if errors:
        raise Refused("word timing integrity: " + "; ".join(errors), evidence={"errors": errors})


def moved_summary(rows: list[dict]) -> list[dict]:
    return [{"entry": r["entry"], "word": r["word"], "old_start_frame": r["old_start_frame"],
             "new_start_frame": r["new_start_frame"]} for r in rows if r["moved"]]


def rule_block(recipe: dict) -> dict:
    """The recorded rule: the recipe numbers the document was produced with."""
    return {"first_word": recipe["first_word"], "all_words": recipe["all_words"],
            "text": "line-first word: first sustained speech run (bursts skipped, unvoiced pre-roll -> first voiced window); "
                    "every word: start in silence -> rising edge of the first sustained voiced run; pause inside the "
                    "first 0.40 s -> edge after the pause; never earlier, ends kept"}
