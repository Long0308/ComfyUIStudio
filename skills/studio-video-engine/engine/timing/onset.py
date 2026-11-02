"""The all-words onset rule: a word that follows a pause must not light before the sound.

Port of the verified ``word-timing-v004`` tool; every threshold is a recipe value (``all_words``).
Whisper fills the silence before a word, so a word after a pause gets a start inside the gap
(error-db ``word-timing-inner-word-starts-at-gap-start-lights-early``).  Per word, on the bound WAV:

* floor test: RMS of the ``floor_window_s`` window at the start >= ``floor_dbfs`` = already on sound.
* rule A (start in silence): the first window in ``[start, end - margin)`` that opens a SUSTAINED
  voiced run (``voiced_dbfs`` for ``sustain_s``); the onset is the rising edge of that run (walk back
  while the window stays >= ``edge_dbfs``, never before the old start).
* rule B (pause inside the word): a pause in the first ``mid_s`` (``near_min_s`` when it starts within
  ``near_s`` of the start, ``far_min_s`` within ``mid_s``; a stop closure inside a word is shorter)
  followed by a sustained voiced run moves the start to the edge after the pause, repeated, total
  shift capped at ``max_shift_s``.
* never earlier than the old start, never later than ``end - margin`` frames, ends are kept.

Pure functions on a :class:`Sound`; the caller owns document handling (``words.py``).
"""

from __future__ import annotations

from typing import Any

from .sound import Sound, frame_of, rms_db

RULE_A = "A: start in silence -> rising edge of the first sustained voiced run"
RULE_B = "B: pause inside the word start -> rising edge after the pause"


def find_onset(sound: Sound, start_s: float, end_s: float, p: dict, fps: float) -> tuple[float | None, dict]:
    """Onset of the first sustained voiced run opening before ``end - margin``, else ``(None, reason)``.

    The run itself may extend past ``end - margin``; only its start must lie before it."""
    hop, win = p["hop_s"], p["window_s"]
    last = end_s - p["end_margin_frames"] / fps
    steps: list[float] = []
    t = start_s
    while t < end_s + p["search_past_end_s"]:
        steps.append(t)
        t = round(t + hop, 6)
    n_sus = max(1, int(round(p["sustain_s"] / hop)))
    db = [rms_db(sound, t, win) for t in steps]
    for i in range(len(steps)):
        if steps[i] >= last:
            break
        if all(i + k < len(db) and db[i + k] >= p["voiced_dbfs"] for k in range(n_sus)):
            j = i
            while j > 0 and db[j - 1] >= p["edge_dbfs"]:
                j -= 1
            return steps[j] + win / 2, {
                "voiced_run_start_s": steps[i], "voiced_run_db": round(db[i], 1), "edge_window_start_s": steps[j],
                "note": "onset = centre of the 20 ms edge window (never before the sound)"}
    return None, {"reason": "no sustained voiced run inside [start, end-2f)"}


def find_pause_edge(sound: Sound, start_s: float, end_s: float, p: dict, fps: float) -> tuple[float | None, dict]:
    """Rule B: the start is on sound; the edge after a pause near the start, if voiced speech follows it."""
    pause, hop, win = p["pause"], p["hop_s"], p["window_s"]
    last = end_s - p["end_margin_frames"] / fps
    stop = min(last, start_s + pause["mid_s"] + pause["far_min_s"] + pause["search_extra_s"])
    ts: list[float] = []
    t = start_s
    while t < stop:
        ts.append(round(t, 6))
        t = round(t + hop, 6)
    db = [rms_db(sound, t, win) for t in ts]
    i = 0
    while i < len(ts):
        if db[i] >= p["floor_dbfs"]:
            i += 1
            continue
        j = i
        while j < len(ts) and db[j] < p["floor_dbfs"]:
            j += 1
        off = ts[i] - start_s
        need = pause["near_min_s"] if off <= pause["near_s"] else (pause["far_min_s"] if off <= pause["mid_s"] else None)
        if need is not None and (j - i) * hop >= need - 1e-9 and j < len(ts):
            edge, info = find_onset(sound, ts[j] - hop, end_s, p, fps)
            if edge is not None:
                return max(edge, ts[j] + win / 2), {
                    "pause_start_s": ts[i], "pause_s": round((j - i) * hop, 2),
                    "pause_offset_in_word_s": round(off, 2), **info}
        i = j
    return None, {}


def _unchanged(row: dict, why: str, old_s: float, old_f: int) -> dict:
    return {**row, "rule": "unchanged: " + why, "new_start_s": old_s, "new_start_frame": old_f, "moved": False}


def correct_word(sound: Sound, word: dict, entry_start_frame: int, p: dict, fps: float) -> dict:
    """The audit row of one word: old/new start, the rule steps and whether the start moved.

    ``word`` needs ``index, text, start_s, end_s, start_frame, end_frame_exclusive``; it is not changed."""
    old_s, old_f, end_s = word["start_s"], word["start_frame"], word["end_s"]
    db0 = rms_db(sound, old_s, p["floor_window_s"])  # a 20 ms window would already hold 10 ms of a soft onset
    row: dict[str, Any] = {
        "index": word["index"], "word": word["text"], "old_start_s": old_s, "old_start_frame": old_f,
        "rms_at_old_start_dbfs": round(db0, 1), "end_s": end_s, "end_frame_exclusive": word["end_frame_exclusive"]}
    cur, steps = old_s, []
    if db0 < p["floor_dbfs"]:
        on, info = find_onset(sound, old_s, end_s, p, fps)
        row["search"] = info
        if on is None:
            return _unchanged(row, info["reason"], old_s, old_f)
        cur = on
        steps.append({"rule": RULE_A, "from_s": old_s, "to_s": round(on, 3), **info})
    while True:  # rule B, repeated (also after A: the run found there can be the tail of the previous word)
        edge, info = find_pause_edge(sound, cur, end_s, p, fps)
        if edge is None or edge - old_s > p["pause"]["max_shift_s"] or edge <= cur:
            break
        steps.append({"rule": RULE_B, "from_s": round(cur, 3), "to_s": round(edge, 3), **info})
        cur = edge
    if not steps:
        return _unchanged(row, f"start already on sound (>= {p['floor_dbfs']:g} dBFS), no pause inside the first "
                          f"{p['pause']['mid_s']:.2f} s", old_s, old_f)
    new_f = entry_start_frame + frame_of(cur, fps)
    cap = word["end_frame_exclusive"] - p["end_margin_frames"]
    capped = new_f > cap
    new_f = max(min(new_f, cap), old_f)
    letters = " + ".join(sorted({step["rule"][0] for step in steps})).replace("A", "rule A").replace("B", "rule B")
    row.update({
        "measured_onset_s": round(cur, 3), "rule": letters + (" (capped at end-2f)" if capped else ""), "steps": steps,
        "new_start_s": round(cur, 6) if not capped else round((new_f - entry_start_frame) / fps, 6),
        "new_start_frame": new_f, "moved": new_f != old_f})
    return row
