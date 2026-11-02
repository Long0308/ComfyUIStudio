"""``jjv qa av``: decoded-audio check of a review export.

For every WAV bound to the timeline (the WAV named in the shot's receipt, see ``shots.json``
``wav_binding``) the export's decoded mono 48 kHz audio is cross-correlated around the WAV's
configured start; the lag of the normalised correlation peak must stay within the tolerance
(default half a frame).  A binding has no fail-open path: it must carry a sha256, and the WAV on
disk must hash to it.  A silent WAV cannot be located by correlation, so it must be declared with an
``expect_silent`` window; the EXPORT's RMS in that window is measured, reported and bounded.
Optionally the first N seconds of the export are compared sample-by-sample with a reference export.

The config may only TIGHTEN the engine's thresholds (``params_from_config``): a looser or non-finite
value is ``Refused``, so a config cannot declare its own way to a PASS.

The receipt is timestamp-free (``write_once`` stays idempotent) and echoes no absolute path.
numpy is an optional, lazily imported dependency (``Uncertain`` when missing).
"""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file
from .bindings import (BOUNDARIES_SCHEMA, SILENT_MAX_RMS_CEILING, Binding, bindings_from_config,  # noqa: F401
                       check_silent_window, resolve_bindings)
from .scope import require_scoped, shown_path

SAMPLE_RATE = 48000
RECEIPT_SCHEMA = "jjv/qa-av-receipt/v2"
DEFAULT_TOLERANCE_FRAMES = 0.5   # lag tolerance when the config names none: half a delivery frame
DEFAULT_NCC_MIN = 0.3
DEFAULT_SEARCH_S = 0.5
MIN_SEARCH_S = 0.1               # floor: a smaller window cannot expose a late WAV (round 5)
DEFAULT_PCM_MAX_ABS = 1e-3
DEFAULT_SLACK_SAMPLES = 2048     # one AAC frame of encoder padding
DEFAULT_SILENT_PEAK_MAX = 1e-3   # a WAV whose peak is below this cannot be located by correlation
_KEYS = ("tolerance_ms", "ncc_min", "search_s", "pcm_max_abs", "slack_samples", "reference_seconds",
         "silent_peak_max")
Runner = Callable[..., "subprocess.CompletedProcess[bytes]"]


def _numpy():
    try:
        import numpy  # noqa: PLC0415 - optional dependency, imported on demand
    except ImportError as error:
        raise Uncertain("qa av needs numpy (pip install numpy)") from error
    return numpy


@dataclass(frozen=True)
class AvParams:
    tolerance_ms: float
    ncc_min: float = DEFAULT_NCC_MIN
    search_s: float = DEFAULT_SEARCH_S
    pcm_max_abs: float = DEFAULT_PCM_MAX_ABS
    slack_samples: int = DEFAULT_SLACK_SAMPLES
    silent_peak_max: float = DEFAULT_SILENT_PEAK_MAX
    reference_seconds: float | None = None


def default_tolerance_ms(fps: float) -> float:
    return DEFAULT_TOLERANCE_FRAMES * 1000.0 / fps


def engine_defaults(fps: float) -> dict[str, float]:
    return {"tolerance_ms": default_tolerance_ms(fps), "ncc_min": DEFAULT_NCC_MIN, "search_s": DEFAULT_SEARCH_S,
            "silent_peak_max": DEFAULT_SILENT_PEAK_MAX, "pcm_max_abs": DEFAULT_PCM_MAX_ABS,
            "slack_samples": DEFAULT_SLACK_SAMPLES}


_AT_MOST = ("tolerance_ms", "silent_peak_max", "pcm_max_abs", "slack_samples",
            "search_s")  # a larger value loosens the check (search_s: bounded below as well, MIN_SEARCH_S)
_AT_LEAST = ("ncc_min",)                                                         # a smaller value loosens it


def params_from_config(config: dict, fps: float) -> tuple[AvParams, dict]:
    """``config.qa.av`` over the engine defaults; returns (params, where each value came from).

    Every value must be finite and non-negative, and the config may only TIGHTEN a threshold relative
    to the engine default (tolerance_ms, silent_peak_max, pcm_max_abs, slack_samples at most the
    default; ncc_min at least the default; search_s within [MIN_SEARCH_S, default]; reference_seconds > 0
    and, at run time, no shorter than the compared overlap), otherwise ``Refused``."""
    block = ((config.get("qa") or {}).get("av")) or {}
    unknown = sorted(set(block) - set(_KEYS))
    if unknown:
        raise Refused(f"config.qa.av has unknown key(s) {unknown}")
    defaults = engine_defaults(fps)
    values: dict[str, Any] = {}
    for key in _KEYS:
        if key in block:
            value = block[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    or value < 0):
                raise Refused(f"config.qa.av.{key} must be a finite non-negative number, got {value!r}")
            if (key in _AT_MOST and value > defaults[key]) or (key in _AT_LEAST and value < defaults[key]):
                raise Refused(f"config.qa.av.{key} {value} is looser than the engine default {defaults[key]}: "
                              "the config may only tighten the thresholds")
            if key == "search_s" and value < MIN_SEARCH_S:
                raise Refused(f"config.qa.av.search_s {value} is below the floor {MIN_SEARCH_S} s: a window that "
                              "small cannot expose a misplaced WAV")
            values[key] = value
    if "reference_seconds" in values and values["reference_seconds"] <= 0:
        raise Refused("config.qa.av.reference_seconds must be > 0")
    if "tolerance_ms" in values and values["tolerance_ms"] <= 0:
        raise Refused("config.qa.av.tolerance_ms must be > 0")
    if "slack_samples" in values:
        values["slack_samples"] = int(values["slack_samples"])
    values.setdefault("tolerance_ms", defaults["tolerance_ms"])
    sources = {key: ("config" if key in block else "engine default") for key in _KEYS}
    return AvParams(**values), sources


def decode_mono(path: Path, *, ffmpeg: str = "ffmpeg", sample_rate: int = SAMPLE_RATE,
                runner: Runner = subprocess.run):
    """Decode the first audio stream to a float32 mono array (ffmpeg, no filters)."""
    np = _numpy()
    command = [ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
               "-ar", str(sample_rate), "-f", "f32le", "-"]
    try:
        result = runner(command, capture_output=True, check=False)
    except OSError as error:
        raise Uncertain(f"cannot run ffmpeg for {Path(path).name}: {error}") from error
    if result.returncode != 0 or not result.stdout:
        text = (result.stderr or b"").decode(errors="replace").strip()[:300]
        raise Uncertain(f"ffmpeg could not decode audio of {Path(path).name}: {text or 'no audio'}")
    return np.frombuffer(result.stdout, dtype="<f4")


def normalised_xcorr(segment, template):
    """NCC of ``template`` against every offset of ``segment`` (valid mode), via FFT."""
    np = _numpy()
    seg = np.asarray(segment, dtype=np.float64)
    tpl = np.asarray(template, dtype=np.float64)
    n, m = len(seg), len(tpl)
    size = 1 << (n + m).bit_length()
    corr = np.fft.irfft(np.fft.rfft(seg, size) * np.conj(np.fft.rfft(tpl, size)), size)[: n - m + 1]
    cumulative = np.concatenate(([0.0], np.cumsum(seg * seg)))
    energy = np.sqrt(cumulative[m:] - cumulative[:-m] + 1e-9)
    return corr / (energy * np.sqrt(float((tpl * tpl).sum())) + 1e-9)


def locate_ex(mix, wav, start_frame: int, *, fps: float, search_s: float,
              sample_rate: int = SAMPLE_RATE) -> tuple[int, float, bool] | None:
    """(lag in samples, ncc, edge) of the correlation peak around the expected start; None when the
    export is too short to contain the WAV at the searched positions.  ``edge`` is True when the peak sits
    on a window boundary that is a real search limit (not merely the start/end of the export): the best
    match may lie beyond the window, so the lag is not trustworthy and must fail."""
    np = _numpy()
    expected = int(round(start_frame / fps * sample_rate))
    reach = int(search_s * sample_rate)
    low = max(0, expected - reach)
    high = min(len(mix), expected + reach + len(wav))
    if len(wav) == 0 or high - low < len(wav):
        return None
    ncc = normalised_xcorr(mix[low:high], wav)
    peak = int(np.argmax(ncc))
    clipped_low = low > 0 and peak == 0
    clipped_high = high < len(mix) and peak == len(ncc) - 1
    return low + peak - expected, float(ncc[peak]), clipped_low or clipped_high


def locate(mix, wav, start_frame: int, *, fps: float, search_s: float,
           sample_rate: int = SAMPLE_RATE) -> tuple[int, float] | None:
    """(lag in samples, ncc) of the correlation peak around the expected start (see ``locate_ex``)."""
    found = locate_ex(mix, wav, start_frame, fps=fps, search_s=search_s, sample_rate=sample_rate)
    return None if found is None else (found[0], found[1])


def window_rms(mix, start_frame: int, end_frame: int, fps: float) -> float | None:
    """RMS of the export over [start, end) frames; None if the export does not reach the end."""
    np = _numpy()
    first, last = int(round(start_frame / fps * SAMPLE_RATE)), int(round(end_frame / fps * SAMPLE_RATE))
    if last > len(mix) or last <= first:
        return None
    return float(np.sqrt(np.mean(np.asarray(mix[first:last], dtype=np.float64) ** 2)))


def _base_row(binding: Binding, shown: str, actual_sha256: str | None) -> dict:
    return {"name": binding.name, "wav": shown, "start_frame": binding.start_frame,
            "wav_sha256": actual_sha256, "bound_sha256": binding.sha256,
            "sha_ok": actual_sha256 == binding.sha256}


def _silent_row(mix, binding: Binding, row: dict, fps: float, peak: float) -> dict:
    """A silent WAV: placement is unprovable by correlation, so say so and bound the export instead."""
    spec = binding.expect_silent
    row = {**row, "lag_samples": None, "lag_ms": None, "lag_frames": None, "ncc": None, "peak": peak,
           "placement_proven": False}
    if spec is None:
        return {**row, "status": "silent-undeclared", "ok": False,
                "reason": "silent WAV without an expect_silent window: its placement cannot be verified"}
    measured = window_rms(mix, spec["start_frame"], spec["end_frame_exclusive"], fps)
    row["expect_silent"] = {"start_frame": spec["start_frame"], "end_frame_exclusive": spec["end_frame_exclusive"],
                            "max_rms": spec["max_rms"], "export_rms": measured}
    if binding.start_frame != spec["start_frame"]:
        return {**row, "status": "silent-misplaced", "ok": False,
                "reason": (f"silent WAV is bound at f{binding.start_frame} but its expect_silent window starts at "
                           f"f{spec['start_frame']}: the binding is not where the declared silence is")}
    if measured is None:
        return {**row, "status": "silent-declared", "ok": False, "reason": "export audio ends inside the window"}
    ok = row["sha_ok"] and measured <= spec["max_rms"]
    return {**row, "status": "silent-declared", "ok": ok,
            "reason": ("placement unprovable by correlation (silent WAV); only the sha256 binding and the "
                       f"export level in the declared window are checked: export RMS {measured:.4f} "
                       f"{'<=' if ok else '>'} max {spec['max_rms']}")}


def check_binding(mix, wav, binding: Binding, *, fps: float, params: AvParams,
                  actual_sha256: str | None, shown: str | None = None) -> dict:
    np = _numpy()
    row = _base_row(binding, shown or binding.path, actual_sha256)
    peak = float(np.max(np.abs(wav))) if len(wav) else 0.0
    if peak < params.silent_peak_max:
        return _silent_row(mix, binding, row, fps, peak)
    if binding.expect_silent is not None:
        return {**row, "lag_samples": None, "lag_ms": None, "lag_frames": None, "ncc": None, "peak": peak,
                "status": "silent-contradiction", "ok": False,
                "reason": "expect_silent is declared but the bound WAV carries signal"}
    found = locate_ex(mix, wav, binding.start_frame, fps=fps, search_s=params.search_s)
    if found is None:
        return {**row, "lag_samples": None, "lag_ms": None, "lag_frames": None, "ncc": None,
                "status": "too-short", "ok": False, "reason": "export audio too short to contain the WAV"}
    lag, ncc, edge = found
    lag_ms = lag / SAMPLE_RATE * 1000.0
    located = {**row, "lag_samples": lag, "lag_ms": round(lag_ms, 2),
               "lag_frames": round(lag / SAMPLE_RATE * fps, 3), "ncc": round(ncc, 3)}
    if edge:
        return {**located, "status": "edge-hit", "ok": False,
                "reason": (f"the correlation peak sits on the edge of the +/-{params.search_s} s search window: "
                           "the WAV is not within the window of its start (or the match is ambiguous), so the "
                           "measured lag cannot be trusted")}
    ok = row["sha_ok"] and abs(lag_ms) <= params.tolerance_ms and ncc >= params.ncc_min
    return {**located, "status": "located", "ok": ok}


def pcm_identity(mix, reference, *, seconds: float, params: AvParams) -> dict:
    """First ``seconds`` of both exports, minus the slack, compared sample by sample."""
    np = _numpy()
    count = int(round(seconds * SAMPLE_RATE)) - params.slack_samples
    if count <= 0:
        raise Refused(f"reference window of {seconds} s leaves no samples after the slack")
    if len(mix) < count or len(reference) < count:
        return {"seconds": seconds, "compared_samples": count, "samples_export": len(mix),
                "samples_reference": len(reference), "max_abs": None, "rms": None, "reference_rms": None,
                "max_abs_allowed": params.pcm_max_abs, "ok": False,
                "reason": "an export is shorter than the compared window"}
    diff = mix[:count].astype(np.float64) - reference[:count].astype(np.float64)
    max_abs = float(np.max(np.abs(diff)))
    return {"seconds": seconds, "compared_samples": count, "samples_export": len(mix),
            "samples_reference": len(reference), "max_abs": max_abs,
            "rms": float(np.sqrt(np.mean(diff * diff))),
            "reference_rms": float(np.sqrt(np.mean(reference[:count].astype(np.float64) ** 2))),
            "max_abs_allowed": params.pcm_max_abs, "ok": max_abs <= params.pcm_max_abs}


def _caveats(rows: list[dict]) -> list[str]:
    return [f"{row['name']}: {row['reason']}" for row in rows if row["status"] == "silent-declared" and row["ok"]]


def reference_window(cli_seconds: float | None, params: AvParams, main_frames: int | None, fps: float, mix,
                     reference) -> tuple[float, str, bool]:
    """(seconds, where they came from, partial) of the PCM identity window.

    The floor is derived independently of the config being checked: the episode's main film
    (``main_frames`` from ``rules.timeline_frames`` of the episode config, passed by the caller) or, when the
    caller has none, the whole overlap of the two exports.  It is never read from a field of the review config.
    No margin is allowed here: ``pcm_identity`` already drops the last ``slack_samples`` once, so the
    compared span is ``floor - slack`` at the very least (a second margin would hide twice the slack).

    * no window given -> the whole overlap;
    * ``config.qa.av.reference_seconds`` shorter than the floor -> ``Refused`` (a prefix would hide a later
      divergence); otherwise used;
    * explicit ``--reference-seconds`` -> used as given (the operator's choice) but when it is shorter than the
      floor the verdict can only be ``PASS_PARTIAL`` (partial=True), never ``PASS``."""
    overlap = min(len(mix), len(reference)) / SAMPLE_RATE
    floor = main_frames / fps if main_frames else overlap
    if cli_seconds is not None:
        return float(cli_seconds), "cli", float(cli_seconds) < floor
    declared = params.reference_seconds
    if declared is None:
        return overlap, "full overlap", False
    if declared < floor:
        what = "the episode's main film" if main_frames else "the overlap of the two exports"
        raise Refused(f"config.qa.av.reference_seconds {declared} is shorter than {what} ({floor:.3f} s): a shorter "
                      "window could hide a divergence; pass --reference-seconds to choose one explicitly "
                      "(that yields at most PASS_PARTIAL)")
    return float(declared), "config", False


def run_av(*, video: Path, config: dict, config_sha256: str, episode_root: Path, fps: float,
           reference: Path | None = None, reference_seconds: float | None = None,
           allow_outside: Iterable[Path] = (), ffmpeg: str = "ffmpeg",
           runner: Runner = subprocess.run, main_frames: int | None = None) -> dict:
    """Build the (timestamp-free) receipt.  ``Refused`` for a rule violation (unbound WAV, path outside
    the episode root); ``Uncertain`` for an input that cannot be found or decoded.  ``main_frames`` is the
    episode timeline's main film length (never read from ``config``): it floors the reference window."""
    config_fps = config.get("fps")
    if config_fps is not None and float(config_fps) != float(fps):
        raise Refused(f"config fps {config_fps} != domain delivery fps {fps}")
    params, sources = params_from_config(config, fps)
    bindings, binding_source = resolve_bindings(config)
    if reference_seconds is not None and (isinstance(reference_seconds, bool)
                                          or not math.isfinite(reference_seconds) or reference_seconds <= 0):
        raise Refused(f"--reference-seconds must be a finite number > 0, got {reference_seconds!r}")
    root, allow = Path(episode_root), tuple(allow_outside)
    video_path = require_scoped(video, root, allow, "video")
    reference_path = require_scoped(reference, root, allow, "reference") if reference is not None else None
    wav_paths = [require_scoped(root / binding.path, root, allow, f"WAV of {binding.name}")
                 for binding in bindings]
    for path, label in [(video_path, "video"), (reference_path, "reference")]:
        if path is not None and not path.is_file():
            raise Uncertain(f"{label} not found: {path.name}")
    mix = decode_mono(video_path, ffmpeg=ffmpeg, runner=runner)
    rows = []
    for binding, wav_path in zip(bindings, wav_paths):
        if not wav_path.is_file():
            raise Uncertain(f"bound WAV not found: {wav_path.name}")
        wav = decode_mono(wav_path, ffmpeg=ffmpeg, runner=runner)
        rows.append(check_binding(mix, wav, binding, fps=fps, params=params, actual_sha256=sha256_file(wav_path),
                                  shown=shown_path(wav_path, root)))
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA, "sample_rate": SAMPLE_RATE, "fps": fps,
        "binding_source": binding_source, "binding_count": len(bindings),
        "video": {"path": shown_path(video_path, root), "sha256": sha256_file(video_path),
                  "decoded_s": len(mix) / SAMPLE_RATE},
        "config_sha256": config_sha256,
        "params": {"tolerance_ms": params.tolerance_ms, "ncc_min": params.ncc_min,
                   "search_s": params.search_s, "sources": sources},
        "wav_starts": rows,
        "unverifiable_silent_wavs": [row["name"] for row in rows if row["status"].startswith("silent")],
        "caveats": _caveats(rows), "pcm_identity": None}
    if reference_path is not None:
        ref = decode_mono(reference_path, ffmpeg=ffmpeg, runner=runner)
        seconds, window_source, partial = reference_window(reference_seconds, params, main_frames, fps, mix, ref)
        identity = pcm_identity(mix, ref, seconds=seconds, params=params)
        receipt["pcm_identity"] = {"reference": {"path": shown_path(reference_path, root),
                                                 "sha256": sha256_file(reference_path)},
                                   "window_source": window_source, "partial": partial, **identity}
    ok = all(row["ok"] for row in rows) and (
        receipt["pcm_identity"] is None or receipt["pcm_identity"]["ok"])
    partial = bool(receipt["pcm_identity"] and receipt["pcm_identity"]["partial"])
    receipt["partial"] = partial
    receipt["ok"] = ok and not partial  # a partial pass fails closed for anything that only checks `ok`/exit code
    receipt["verdict"] = ("PASS_PARTIAL" if partial else "PASS") if ok else "FAIL"
    return receipt
