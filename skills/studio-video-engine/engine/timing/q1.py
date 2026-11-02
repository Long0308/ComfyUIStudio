"""Q1 gate: every word that follows a pause lights at (not before) the sound that opens it.

Port of the independent check of ``word-timing-v004`` (thresholds = recipe ``q1``).  The detector is
deliberately NOT the correction rule of ``onset.py`` (10 ms windows, silence below ``silence_dbfs``,
edge at ``edge_dbfs``), so a word the correction got wrong is seen by a different instrument.

Per word the audible onset is the first window >= ``edge_dbfs`` after a pause (>= ``pause_min_s`` of
silence beginning no later than ``pause_start_max_s`` after the word's start) searched from
``lookback_s`` before the previous word's end to ``search_after_start_s`` after the start.  A word
with no such pause is ``n/a`` (continuous speech has no onset to test).  ``delta_f = lit - onset``:
FAIL-early when ``delta_f < -max_early_frames``; PASS up to ``max_late_frames``; with ``warn_late_frames`` set,
``WARN-late`` up to that many frames (listed, does not block) and LATE (FAIL) beyond it, else LATE beyond
``max_late_frames``.

Onset (recipe ``onset_voiced_dbfs`` / ``onset_sustain_s`` set, recipe v002): the first window after the pause that
opens a SUSTAINED VOICED run (>= ``onset_sustain_s`` above ``onset_voiced_dbfs``), the same idea as the trim rule,
so a quiet breath before the word is not an onset.  Without them (recipe v001): the first window >= ``edge_dbfs``.

The receipt carries a NEGATIVE CONTROL: one passing word is shifted ``control_shift_frames`` earlier
and the gate must flag exactly that word; a gate that cannot do that proves nothing.
"""

from __future__ import annotations

import copy
from typing import Callable

import numpy as np

from .sound import Sound, frame_of, rms_db


def _opens_onset(sound: Sound, t: float, level: float, q: dict) -> bool:
    voiced = q.get("onset_voiced_dbfs")
    if voiced is None:
        return level >= q["edge_dbfs"]
    count = max(1, int(round(q["onset_sustain_s"] / q["window_s"])))
    return all(rms_db(sound, t + i * q["window_s"], q["window_s"]) >= voiced for i in range(count))


def audible_onset(sound: Sound, prev_end_s: float, start_s: float, end_s: float, q: dict) -> float | None:
    """Audible onset after a pause around ``start_s``, or None when the word follows no pause."""
    win = q["window_s"]
    first = max(0.0, prev_end_s - q["lookback_s"])
    stop = min(end_s - q["word_end_margin_s"], start_s + q["search_after_start_s"])
    ts = list(np.arange(first, stop, win))
    if not ts:
        return None
    db = [rms_db(sound, t, win) for t in ts]
    onset = None
    i = 0
    while i < len(ts):
        if db[i] >= q["silence_dbfs"]:
            i += 1
            continue
        j = i
        while j < len(ts) and db[j] < q["silence_dbfs"]:
            j += 1
        if (j - i) * win >= q["pause_min_s"] - 1e-9 and ts[i] <= start_s + q["pause_start_max_s"]:
            for k in range(j, len(ts)):
                if _opens_onset(sound, ts[k], db[k], q):
                    onset = float(ts[k])
                    break
        i = j
    return onset


def _status(delta: int, q: dict) -> str:
    if delta < -q["max_early_frames"]:
        return "FAIL-early"
    if delta <= q["max_late_frames"]:
        return "PASS"
    warn = q.get("warn_late_frames")
    if warn is not None and delta <= warn:
        return "WARN-late"
    return f"LATE>{q['max_late_frames'] if warn is None else warn}f"


def q1_rows(entries: list[dict], sound_of: Callable[[dict], Sound], q: dict, fps: float) -> list[dict]:
    """One row per word of every entry, in document order."""
    rows: list[dict] = []
    for entry in entries:
        sound = sound_of(entry)
        prev_end = 0.0
        for word in entry["words"]:
            onset = audible_onset(sound, prev_end, word["start_s"], word["end_s"], q)
            prev_end = word["end_s"]
            row = {"entry": entry["id"], "word": word["text"], "index": word["index"], "lit_frame": word["start_frame"]}
            if onset is None:
                rows.append({**row, "onset_s": None, "onset_frame": None, "delta_f": None,
                             "status": "n/a (no pause before the word)"})
                continue
            onset_frame = entry["start_frame"] + frame_of(onset, fps)
            delta = word["start_frame"] - onset_frame
            rows.append({**row, "onset_s": round(onset, 3), "onset_frame": onset_frame, "delta_f": delta,
                         "status": _status(delta, q)})
    return rows


def summarize(rows: list[dict]) -> dict:
    tested = [r for r in rows if r["delta_f"] is not None]
    early = [r for r in tested if r["status"] == "FAIL-early"]
    late = [r for r in tested if r["status"].startswith("LATE")]
    warn = [r for r in tested if r["status"] == "WARN-late"]
    worst = sorted(tested, key=lambda r: -abs(r["delta_f"]) if r["delta_f"] < 0 else -r["delta_f"])[:10]
    return {"words_total": len(rows), "words_tested": len(tested),
            "pass": sum(1 for r in tested if r["status"] == "PASS"), "early": len(early), "late": len(late),
            "warn": len(warn), "warn_words": [f"{r['entry']}:{r['word']}(+{r['delta_f']}f)" for r in warn],
            "early_words": [f"{r['entry']}:{r['word']}" for r in early],
            "late_words": [f"{r['entry']}:{r['word']}" for r in late],
            "worst_10": [{k: r[k] for k in ("entry", "word", "lit_frame", "onset_frame", "delta_f", "status")}
                         for r in worst]}


def _one_control(entries: list[dict], rows: list[dict], sound_of: Callable[[dict], Sound], q: dict, fps: float,
                 shift: int) -> dict:
    """Shift one passing word ``shift`` frames earlier; it must then be flagged early (a word whose margin is so large
    that the shift stays inside the tolerance cannot prove anything and is not chosen)."""
    target = next((r for r in rows if r["status"] == "PASS" and r["delta_f"] - shift < -q["max_early_frames"]), None)
    if target is None:
        return {"status": "not_run", "detected": False, "shift_frames": shift,
                "why": f"no passing word would be early by more than the tolerance after a {shift} f shift "
                       "(the gate already fails, tests nothing, or tolerates that much)"}
    shifted = copy.deepcopy(entries)
    word = next(w for e in shifted if e["id"] == target["entry"] for w in e["words"] if w["index"] == target["index"])
    word["start_frame"] -= shift
    word["start_s"] = round(word["start_s"] - shift / fps, 6)
    control_rows = q1_rows(shifted, sound_of, q, fps)
    hit = next(r for r in control_rows if r["entry"] == target["entry"] and r["index"] == target["index"])
    return {"status": "run", "detected": hit["status"] == "FAIL-early", "shift_frames": shift,
            "what": f"word {target['word']!r} of {target['entry']} shifted {shift} f earlier; the gate must flag it",
            "before": {k: target[k] for k in ("lit_frame", "onset_frame", "delta_f", "status")},
            "after": {k: hit[k] for k in ("lit_frame", "onset_frame", "delta_f", "status")},
            "summary": summarize(control_rows)}


def negative_control(entries: list[dict], rows: list[dict], sound_of: Callable[[dict], Sound], q: dict,
                     fps: float) -> dict:
    """The controls of the recipe: ``control_shift_frames`` plus every ``extra_control_shift_frames``.

    The first control's fields are the top level (``before``/``after``/``summary``); ``controls`` lists all of them
    and ``detected`` is true only if every control ran and was flagged."""
    shifts = [q["control_shift_frames"], *q.get("extra_control_shift_frames", [])]
    results = [_one_control(entries, rows, sound_of, q, fps, shift) for shift in shifts]
    top = dict(results[0])
    top["controls"] = [{k: r.get(k) for k in ("shift_frames", "status", "detected", "what")} for r in results]
    top["status"] = "run" if all(r["status"] == "run" for r in results) else "not_run"
    top["detected"] = all(r["detected"] for r in results)
    return top
