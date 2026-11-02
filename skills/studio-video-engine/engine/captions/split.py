"""GENERATOR_SPLIT_MISMATCH: mot bo cue da luu phai trung diem tach cua words_to_cues(); lech => tu choi."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..core.errors import Refused
from .ass import Cue

SPLIT_MISMATCH = "GENERATOR_SPLIT_MISMATCH"


def layout_of(cues: Sequence[Cue]) -> dict[str, Any]:
    """Cue layout in comparable form: per cue the entry id and the visible word texts."""
    return {"cues": [{"entry_id": cue.entry_id, "words": [word.text for word in cue.words]} for cue in cues]}


def check_split(cues: Sequence[Cue], saved: Mapping[str, Any]) -> None:
    """Return None when ``saved`` equals the generator split, else raise ``Refused`` (exit 1)."""
    expected = layout_of(cues)["cues"]
    actual = list(saved.get("cues", ()))
    if actual != expected:
        first = next((i for i, (a, b) in enumerate(zip(actual, expected)) if a != b), min(len(actual), len(expected)))
        raise Refused(f"{SPLIT_MISMATCH}: saved layout has {len(actual)} cues, generator {len(expected)}; "
                      f"first difference at cue index {first}; ASS/burn are blocked until the layout is regenerated",
                      evidence={"first_difference_index": first})
