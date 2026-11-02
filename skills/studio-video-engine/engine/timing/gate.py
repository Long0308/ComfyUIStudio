"""``jjv qa words``: the Q1 gate over a finished WORD-TIMING document (plus the shared ``run_q1``).

PASS needs ALL of: every tested word lit 0..``max_late_frames`` frames after its audible onset (none early
by even one frame, none later than the limit), AND the built-in negative control detected (one passing
word shifted ``control_shift_frames`` earlier must be flagged), AND at least one word was tested.  A
document with no word after a pause has nothing to test: ``UNTESTABLE`` (Uncertain, exit 2), never PASS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file
from ..qa.scope import shown_path
from .q1 import negative_control, q1_rows, summarize
from .sound import Sound
from .wavs import BoundWav, bind_wavs

RECEIPT_SCHEMA = "jjv/qa-words-receipt/v1"


def run_q1(entries: list[dict], sound_of: Callable[[dict], Sound], q: dict, fps: float) -> dict:
    """Rows, summary, negative control and verdict (PASS | FAIL | UNTESTABLE) for one document."""
    rows = q1_rows(entries, sound_of, q, fps)
    summary = summarize(rows)
    control = negative_control(entries, rows, sound_of, q, fps)
    if summary["words_tested"] == 0:
        verdict = "UNTESTABLE"
    elif summary["early"] or summary["late"]:
        verdict = "FAIL"
    elif control["status"] != "run" or not control["detected"]:
        verdict = "FAIL"  # a clean document whose gate could not be shown to catch an early word proves nothing
    else:
        verdict = "PASS"
    return {"verdict": verdict, "limits": {"max_early_frames": q["max_early_frames"], "max_late_frames": q["max_late_frames"]},
            "summary": summary, "negative_control": control, "rows": rows}


def sound_lookup(bound: dict[str, BoundWav]) -> Callable[[dict], Sound]:
    return lambda entry: bound[entry["id"]].sound


def check_document(timing: dict, root: Path, q: dict, fps: float, allow: Iterable[Path | str] = ()) -> tuple[dict, dict[str, BoundWav]]:
    """Q1 over a WORD-TIMING document; every entry's WAV is hash-bound first."""
    entries = timing.get("entries")
    if not isinstance(entries, list) or not entries:
        raise Refused("word timing has no entries")
    if isinstance(timing.get("fps"), (int, float)) and float(timing["fps"]) != float(fps):
        raise Refused(f"word timing fps {timing['fps']} differs from the episode delivery fps {fps}")
    bound = bind_wavs(entries, root, allow)
    return run_q1(entries, sound_lookup(bound), q, fps), bound


def build_receipt(timing_path: Path, root: Path, recipe_id: str, recipe_sha: str, result: dict,
                  bound: dict[str, BoundWav]) -> dict:
    """The write-once ``qa words`` receipt (no timestamp; paths episode-relative)."""
    if result["verdict"] == "UNTESTABLE":
        raise Uncertain("Q1 has nothing to test: no word follows a pause in this document, so a PASS would prove nothing",
                        evidence={"summary": result["summary"]})
    return {"schema": RECEIPT_SCHEMA, "ok": result["verdict"] == "PASS", "verdict": result["verdict"],
            "warnings": result["summary"]["warn_words"],
            "timing": {"path": shown_path(timing_path, root), "sha256": sha256_file(timing_path)},
            "recipe": {"id": recipe_id, "sha256": recipe_sha},
            "wavs": [{"id": name, "path": b.shown, "sha256": b.sha256} for name, b in bound.items()],
            "q1": result}
