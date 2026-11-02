"""Silence trim: THE only place a dialogue WAV is cut (rule E_TRIM_ONCE).

Window RMS over interleaved PCM16 samples (``window_ms`` non-overlapping windows), speech =
RMS >= ``threshold_dbfs``; the cut is ``[onset - pre_roll, offset + post_roll]`` clamped to the
file, rounded to whole samples with the same arithmetic as the verified trim tool so the
receipts stay byte-identical.

Onset rule (word-timing lesson): the TTS output can start with a short unvoiced burst.  Runs
of speech windows separated by <= ``merge_gap_s`` are merged; walking them in time order, a
run >= ``min_run_s`` is speech; a shorter run followed by a gap >= ``isolated_gap_s`` (or by
nothing) is NOT speech and is skipped; a shorter run inside a speech cluster counts.  The
offset stays the last speech window (bursts at the end are not reinterpreted).  Optional recipe key
``onset.quiet_burst_db``: a short leading run INSIDE a cluster whose peak is at least that many dB below the
loudest run's peak is a breath/click, not speech, and is skipped too (the end-line lesson: a 0.11-0.17 s
burst at -36 dBFS sat 0.11 s before the words, under ``isolated_gap_s``, and latched the onset).  Absent =
off, so existing recipes and receipts are unchanged.

Only ``engine/voice/finalize.py`` may import this module (asserted by a static test).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from ..core.errors import Refused
from .wavio import WavData


@dataclass(frozen=True)
class TrimParams:
    threshold_dbfs: float
    window_ms: int
    pre_roll_s: float
    post_roll_s: float
    merge_gap_s: float
    min_run_s: float
    isolated_gap_s: float
    quiet_burst_db: float | None = None

    @classmethod
    def from_recipe(cls, recipe: dict) -> "TrimParams":
        trim = recipe["trim"]
        onset = trim["onset"]
        return cls(float(trim["threshold_dbfs"]), int(trim["window_ms"]), float(trim["pre_roll_s"]),
                   float(trim["post_roll_s"]), float(onset["merge_gap_s"]), float(onset["min_run_s"]),
                   float(onset["isolated_gap_s"]),
                   None if onset.get("quiet_burst_db") is None else float(onset["quiet_burst_db"]))

    def as_dict(self) -> dict:
        data = asdict(self)
        if data["quiet_burst_db"] is None:
            del data["quiet_burst_db"]  # keeps receipts written before the key existed comparable
        return data


@dataclass(frozen=True)
class Window:
    index: int
    start_sample: int
    samples: int  # the last window may be shorter
    speech: bool


@dataclass(frozen=True)
class TrimBounds:
    start_sample: int
    end_sample: int
    voiced_start_sample: int | None
    voiced_end_sample: int | None
    onset: dict

    @property
    def samples(self) -> int:
        return self.end_sample - self.start_sample

    def as_dict(self) -> dict:
        return {"start_sample": self.start_sample, "end_sample": self.end_sample,
                "samples": self.samples, "voiced_start_sample": self.voiced_start_sample,
                "voiced_end_sample": self.voiced_end_sample, "onset": dict(self.onset)}


def threshold_linear(threshold_dbfs: float) -> float:
    return 32768.0 * (10.0 ** (threshold_dbfs / 20.0))


def window_frames(rate: int, window_ms: int) -> int:
    return max(1, round(rate * (window_ms / 1000.0)))


def speech_windows(data: WavData, params: TrimParams) -> list[Window]:
    """Window-by-window speech flags with the legacy windowing (interleaved RMS, last window short)."""
    values = data.samples()
    per_window = window_frames(data.rate, params.window_ms)
    thresh = threshold_linear(params.threshold_dbfs)
    out: list[Window] = []
    pos, index = 0, 0
    while pos < data.frames:
        req = min(per_window, data.frames - pos)
        chunk = values[pos * data.channels:(pos + req) * data.channels]
        rms = math.sqrt(sum(v * v for v in chunk) / len(chunk))
        out.append(Window(index, pos, req, rms >= thresh))
        pos += req
        index += 1
    return out


def speech_runs(windows: list[Window], merge_gap_windows: int) -> list[tuple[int, int]]:
    """Consecutive speech windows as ``[start, end)`` index runs; gaps <= merge_gap are merged."""
    runs: list[tuple[int, int]] = []
    for window in windows:
        if not window.speech:
            continue
        if runs and window.index - runs[-1][1] <= merge_gap_windows:
            runs[-1] = (runs[-1][0], window.index + 1)
        else:
            runs.append((window.index, window.index + 1))
    return runs


def run_peaks_db(data: WavData, windows: list[Window], runs: list[tuple[int, int]]) -> list[float]:
    """Peak dBFS of the samples inside each run (silence floor -200)."""
    values = data.samples()
    out = []
    for start, end in runs:
        first = windows[start].start_sample * data.channels
        last = (windows[end - 1].start_sample + windows[end - 1].samples) * data.channels
        peak = max((abs(v) for v in values[first:last]), default=0)
        out.append(20.0 * math.log10(peak / 32768.0) if peak else -200.0)
    return out


def choose_onset(runs: list[tuple[int, int]], *, min_run_windows: int, isolated_gap_windows: int,
                 peaks_db: list[float] | None = None, quiet_burst_db: float | None = None) -> tuple[int | None, list[dict]]:
    """First run that counts as speech (window index) and the bursts skipped before it."""
    skipped: list[dict] = []
    loudest = max(peaks_db) if peaks_db else None
    for position, (start, end) in enumerate(runs):
        if end - start >= min_run_windows:
            return start, skipped
        gap = (runs[position + 1][0] - end) if position + 1 < len(runs) else None
        if gap is None or gap >= isolated_gap_windows:
            skipped.append({"start_window": start, "end_window": end, "gap_windows_after": gap})
            continue
        if quiet_burst_db is not None and loudest is not None and loudest - peaks_db[position] >= quiet_burst_db:
            skipped.append({"start_window": start, "end_window": end, "gap_windows_after": gap,
                            "reason": "quiet_vs_loudest_run", "peak_dbfs": round(peaks_db[position], 1),
                            "loudest_run_peak_dbfs": round(loudest, 1)})
            continue
        return start, skipped
    return None, skipped


def _windows_of(seconds: float, rate: int, per_window: int) -> int:
    return int(round(seconds * rate / per_window))


def trim_bounds(data: WavData, params: TrimParams) -> TrimBounds:
    """Sample-exact cut bounds; the arithmetic mirrors the verified trim tool."""
    if data.frames <= 0:
        raise Refused("cannot trim an empty WAV")
    windows = speech_windows(data, params)
    per_window = window_frames(data.rate, params.window_ms)
    runs = speech_runs(windows, _windows_of(params.merge_gap_s, data.rate, per_window))
    quiet = params.quiet_burst_db
    onset_window, skipped = choose_onset(
        runs, min_run_windows=_windows_of(params.min_run_s, data.rate, per_window),
        isolated_gap_windows=_windows_of(params.isolated_gap_s, data.rate, per_window),
        peaks_db=run_peaks_db(data, windows, runs) if quiet is not None else None, quiet_burst_db=quiet)
    first_v = windows[onset_window].start_sample if onset_window is not None else None
    last_v = None
    for window in windows:
        if window.speech:
            last_v = window.start_sample + window.samples
    naive_first = next((w.start_sample for w in windows if w.speech), None)
    rate = data.rate
    v_start = (first_v or 0) / rate
    v_end = (last_v or data.frames) / rate
    t_start = max(0.0, v_start - params.pre_roll_s)
    t_end = min(data.duration_s, v_end + params.post_roll_s)
    s_start = max(0, round(t_start * rate))
    s_end = min(data.frames, round(t_end * rate))
    if s_end <= s_start:
        raise Refused("trim produced an empty range")
    return TrimBounds(
        start_sample=s_start, end_sample=s_end, voiced_start_sample=first_v, voiced_end_sample=last_v,
        onset={"rule": "merged-runs; short isolated burst skipped" + ("; quiet burst skipped" if quiet is not None else ""), "naive_first_speech_sample": naive_first,
               "chosen_first_speech_sample": first_v, "skipped_bursts": skipped,
               "differs_from_naive": naive_first != first_v})


def trim_pcm(data: WavData, bounds: TrimBounds) -> bytes:
    """The cut PCM bytes (a pure slice; no resampling, no gain)."""
    return data.pcm[bounds.start_sample * data.frame_bytes:bounds.end_sample * data.frame_bytes]


def has_speech(data: WavData, params: TrimParams) -> bool:
    return any(window.speech for window in speech_windows(data, params))
