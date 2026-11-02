"""Word timing for dialogue rows: bind an engine WORD-TIMING receipt to a row, and the first-word snap rule.

A dialogue row carries ``timing = {receipt, sha256, entry_id, qa: {receipt, sha256}}``.  The receipt is the
``jjv timing words`` document (words with raw_text/start_s/end_s, relative to the WAV start); the optional ``qa``
is its WORD-TIMING-QA.json.  The engine receipt is never modified: the snap works on a copy of the words.

Refusals: ``EDL_TIMING_MISSING`` (non-placeholder row without timing, or a receipt that does not exist) and
``EDL_TIMING_MISMATCH`` (receipt sha, entry, WAV sha or words differ from the EDL).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..core.io import sha256_file
from .edl import abs_path, refuse

EDL_TIMING_MISSING = "EDL_TIMING_MISSING"
EDL_TIMING_MISMATCH = "EDL_TIMING_MISMATCH"
SNAP_RULE = "first-word-onset-snap-v1"
SNAP_MIN_LATE_FRAMES = 4


def load_timing_entry(row: Mapping[str, Any], base: Path) -> dict | None:
    """The WORD-TIMING entry bound to dialogue row ``row`` (receipt path + sha + entry id); None when the row has no timing."""
    timing = row.get("timing")
    if not isinstance(timing, Mapping):
        return None
    label = row.get("id")
    receipt = timing.get("receipt")
    path = abs_path(receipt, base) if isinstance(receipt, str) and receipt else None
    if path is None or not path.is_file():
        refuse(EDL_TIMING_MISSING, f"{label}: timing receipt {receipt!r} does not exist")
    if sha256_file(path) != timing.get("sha256"):
        refuse(EDL_TIMING_MISMATCH, f"{label}: timing receipt sha does not match {path.name}")
    document = json.loads(path.read_text(encoding="utf-8"))
    wanted = timing.get("entry_id", label)
    entry = next((item for item in document.get("entries", []) if item.get("id") == wanted), None)
    if entry is None or not entry.get("words"):
        refuse(EDL_TIMING_MISMATCH, f"{label}: entry {wanted!r} has no words in {path.name}")
    if row.get("wav") and (entry.get("audio") or {}).get("sha256") != row.get("sha256"):
        refuse(EDL_TIMING_MISMATCH, f"{label}: timing was measured on another WAV "
               f"({str((entry.get('audio') or {}).get('sha256'))[:12]} != {str(row.get('sha256'))[:12]})")
    return entry


def check_dialogue_timing(row: Mapping[str, Any], base: Path) -> None:
    """Refuse a spoken row whose timing is absent (unless placeholder) or does not match the EDL text."""
    if not row.get("text"):
        return
    if row.get("timing") is None:
        if not row.get("placeholder"):
            refuse(EDL_TIMING_MISSING, f"{row.get('id')}: a non-placeholder dialogue row needs a word-timing receipt "
                   "(estimates are allowed only with placeholder=true)")
        return
    entry = load_timing_entry(row, base)
    # the engine drops pure-punctuation tokens (a dash), so the comparison does too
    spoken = [token for token in str(row["text"]).split() if any(char.isalnum() for char in token)]
    if [word.get("raw_text", word["text"]) for word in entry["words"]] != spoken:
        refuse(EDL_TIMING_MISMATCH, f"{row.get('id')}: timing words differ from the EDL text")


def first_word_snap(words: Sequence[Mapping[str, Any]], entry_id: str, qa_doc: Mapping[str, Any],
                    qa_sha: str) -> tuple[list[dict], list[dict]]:
    """Rule ``first-word-onset-snap-v1``: only the FIRST word of a line, only when the engine Q1 row for it is LATE by
    more than 4 frames; its start becomes the Q1-measured onset (end kept).  Returns (new words, snap records)."""
    row = next((item for item in (qa_doc.get("q1") or {}).get("rows", [])
                if item.get("entry") == entry_id and item.get("index") == 1), None)
    if not row or not str(row.get("status", "")).startswith("LATE") \
            or (row.get("delta_f") or 0) <= SNAP_MIN_LATE_FRAMES or row.get("onset_s") is None:
        return [dict(word) for word in words], []
    old, new = words[0]["start_s"], float(row["onset_s"])
    if new >= old or new >= words[0]["end_s"]:
        return [dict(word) for word in words], []
    out = [dict(words[0], start_s=new)] + [dict(word) for word in words[1:]]
    record = {"rule": SNAP_RULE, "entry": entry_id, "word": words[0]["text"], "original_start_s": old,
              "new_start_s": new, "end_s_kept": words[0]["end_s"], "late_frames_before": row["delta_f"],
              "measurement_source": f"WORD-TIMING-QA.json q1.rows[entry={entry_id},index=1].onset_s "
                                    f"(sha256 {qa_sha[:12]})"}
    return out, [record]
