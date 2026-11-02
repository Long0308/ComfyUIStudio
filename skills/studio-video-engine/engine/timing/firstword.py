"""The line-first onset rule (port of the verified ``word-timing-v003`` tool; thresholds = recipe ``first_word``).

The first word of a dialogue line must start at the first SUSTAINED speech of the WAV, never at a
breath/click burst that precedes it (error-db ``word-timing-onset-latched-on-breath-burst``).
House style, the same as ``voice/trim.py``: runs of 10 ms windows above ``threshold_dbfs`` separated
by <= ``merge_gap_s`` are merged; walking them in time order a run >= ``sustained_run_s`` is speech, a
shorter run followed by a gap >= ``isolated_gap_s`` (or by nothing) is a burst and is skipped, a
shorter run inside a cluster counts.  If that run starts with unvoiced noise lasting >=
``unvoiced_preroll_s`` the onset is the first voiced window (loud, pitched, low centroid).  The first
word moves only when the onset is later than its start by more than ``move_min_s``.
"""

from __future__ import annotations

import copy

import numpy as np

from ..core.errors import Uncertain
from .sound import Sound, frame_of


def rms_runs(sound: Sound, p: dict) -> list[tuple[float, float]]:
    """Merged speech runs ``[(start_s, end_s)]`` from non-overlapping ``hop_s`` RMS windows."""
    hop = int(round(sound.rate * p["hop_s"]))
    n = len(sound.samples) // hop
    if n == 0:
        return []
    rms = np.sqrt((sound.samples[: n * hop].reshape(n, hop) ** 2).mean(1))
    mask = 20 * np.log10(rms + 1e-12) > p["threshold_dbfs"]
    runs: list[list[int]] = []
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            runs.append([i, j])
            i = j
        else:
            i += 1
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and (a - merged[-1][1]) * p["hop_s"] <= p["merge_gap_s"] + 1e-9:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(round(a * p["hop_s"], 2), round(b * p["hop_s"], 2)) for a, b in merged]


def first_voiced_s(sound: Sound, from_s: float, p: dict) -> float | None:
    """First window at/after ``from_s - lead_back_s`` that is loud, pitched (autocorrelation) and low-centroid."""
    v, rate, x = p["voiced"], sound.rate, sound.samples
    freqs = np.fft.rfftfreq(v["fft_size"], 1 / rate)
    for t in np.arange(max(0.0, from_s - v["lead_back_s"]), from_s + v["search_s"], v["hop_s"]):
        seg = x[int(t * rate): int((t + v["window_s"]) * rate)]
        seg = seg - seg.mean() if len(seg) else seg
        if len(seg) < 64:
            break
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), v["fft_size"])) + 1e-12
        ac = np.correlate(seg, seg, "full")[len(seg) - 1:]
        ac = ac / (ac[0] + 1e-12)
        loud = 20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-12) > v["loud_dbfs"]
        pitched = ac[int(rate / v["pitch_max_hz"]): int(rate / v["pitch_min_hz"])].max() >= v["autocorr_min"]
        if loud and pitched and (spec * freqs).sum() / spec.sum() < v["centroid_max_hz"]:
            return round(float(t), 2)
    return None


def choose_run_onset(runs: list[tuple[float, float]], p: dict) -> tuple[float | None, list[dict]]:
    """Start of the first run that counts as speech and the decision log (bursts skipped before it)."""
    log: list[dict] = []
    for k, (a, b) in enumerate(runs):
        dur = round(b - a, 2)
        gap = round(runs[k + 1][0] - b, 2) if k + 1 < len(runs) else None
        row = {"run": [a, b], "dur_s": dur, "gap_to_next_s": gap}
        if dur >= p["sustained_run_s"]:
            log.append({**row, "verdict": "sustained -> onset"})
            return a, log
        if gap is None or gap >= p["isolated_gap_s"]:
            log.append({**row, "verdict": "isolated short burst -> skipped (not speech)"})
            continue
        log.append({**row, "verdict": "short run inside speech cluster -> onset"})
        return a, log
    return None, log


def measure_line_onset(sound: Sound, p: dict) -> dict:
    """The audible start of a line: RMS onset, first voiced window, step-3 decision, final onset."""
    runs = rms_runs(sound, p)
    rms_onset, log = choose_run_onset(runs, p)
    voiced = first_voiced_s(sound, rms_onset, p) if rms_onset is not None else None
    lead = None if voiced is None else round(voiced - rms_onset, 2)
    step3 = lead is not None and lead >= p["unvoiced_preroll_s"] - 1e-9
    return {"rms_onset_s": rms_onset, "first_voiced_s": voiced, "unvoiced_preroll_s": lead,
            "step3_voiced_onset_applied": step3, "onset_s": voiced if step3 else rms_onset, "decision_log": log}


def calibrate_first_word(sound: Sound, words: list[dict], entry_start_frame: int, p: dict, fps: float,
                         *, label: str = "entry") -> tuple[list[dict], dict]:
    """Copies of ``words`` with only the first word's start (and, on collapse, end) changed, plus the audit row.

    No speech found in a WAV that carries words is Uncertain (a script line with no audible speech)."""
    measured = measure_line_onset(sound, p)
    onset = measured["onset_s"]
    out = copy.deepcopy(words)
    if not out:
        return out, {**measured, "moved": False, "note": "no words"}
    if onset is None:
        raise Uncertain(f"{label}: no speech onset found in the WAV although the line has words")
    first, second = out[0], (out[1] if len(out) > 1 else None)
    old_s, old_f = first["start_s"], first["start_frame"]
    moved = onset - old_s > p["move_min_s"]
    report = {**measured, "old_start_s": old_s, "old_start_frame": old_f, "moved": moved,
              "new_start_s": old_s, "new_start_frame": old_f}
    if moved:
        end_s, end_f = first["end_s"], first["end_frame_exclusive"]
        if onset >= end_s or (second is not None and onset >= second["start_s"]):
            end_s = second["start_s"] if second else end_s
            end_f = second["start_frame"] if second else end_f
            report["end_collapsed_to_word2_start"] = True
        first.update({"start_s": round(onset, 6), "start_frame": entry_start_frame + frame_of(onset, fps),
                      "end_s": end_s, "end_frame": end_f, "end_frame_exclusive": end_f})
        report.update({"new_start_s": first["start_s"], "new_start_frame": first["start_frame"]})
    return out, report


def calibrate_last_end(sound: Sound, words: list[dict], entry_start_frame: int, window_end: int, p: dict,
                       fps: float) -> tuple[list[dict], dict]:
    """Copies of ``words`` whose last word ends where the speech of the line ends (end of the last RMS run).

    Whisper ends the last word early (0.2-0.45 s on measured lines).  Fresh recognition only: a supplied
    document keeps its ends.  The recognised end stays in ``raw_whisper_end_s``."""
    out = copy.deepcopy(words)
    runs = rms_runs(sound, p)
    if not out or not runs or not p["calibrate_last_end"]:
        return out, {"moved": False}
    last, offset = out[-1], min(runs[-1][1], sound.duration_s)
    if offset <= last["start_s"]:
        return out, {"moved": False, "note": "speech ends before the last word starts; end kept"}
    end_f = min(max(entry_start_frame + frame_of(offset, fps), last["start_frame"] + 1), window_end)
    report = {"moved": True, "old_end_s": last["end_s"], "new_end_s": offset, "old_end_frame": last["end_frame_exclusive"],
              "new_end_frame": end_f}
    last.update({"end_s": offset, "end_frame": end_f, "end_frame_exclusive": end_f, "boundary_calibrated_end": True})
    return out, report
