"""Stall watchdog for a prompt the executor is waiting on (task T-E30).

The watchdog never decides to resubmit.  ``check`` is called after every empty history poll.  It
fingerprints "is anything moving" (queue state, output files with the chunk prefix, a coarse GPU
memory bucket from telemetry); when the fingerprint has not changed for ``stall_seconds``
(``stall_factor`` x the chunk's expected seconds) it re-runs the LOST classification:

* LOST -> raises :class:`engine.comfy.lost.LostPrompt` (the executor applies its bounded retry);
* UNCERTAIN (docker/ComfyUI/output folder unreadable) ``MAX_CONSECUTIVE_UNCERTAIN`` stalled windows in a row
  -> ``on_stop`` (incident record) and :class:`UncertainStall` (exit 2): doubt must stop the run, not wait
  out the hard timeout;
* otherwise -> records a stall alert (receipt + stderr) and keeps waiting; the alert re-arms after
  another ``stall_seconds``.  The hard timeout stays ``history_timeout_seconds``.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from ..core.errors import Uncertain
from .lost import UNCERTAIN, Classification, LostPrompt

FALLBACK_EXPECTED_SECONDS = 600.0  # only when neither machine config nor the plan gives an estimate
MAX_CONSECUTIVE_UNCERTAIN = 3  # stall windows in a row whose proof is UNCERTAIN before the run stops (exit 2)
GPU_BUCKET_MIB = 256  # GPU memory moves in model-sized steps; idle jitter must not look like progress


def expected_seconds(configured: float | None, chunk: dict) -> float:
    """Machine override, else the plan's per-chunk estimate, else :data:`FALLBACK_EXPECTED_SECONDS`."""
    if configured:
        return float(configured)
    estimate = (chunk.get("estimate") or {})
    for key in ("gpu_seconds_linear_by_padded_frames", "gpu_seconds_conservative"):
        value = estimate.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return FALLBACK_EXPECTED_SECONDS


def gpu_bucket(samples: Any) -> int | None:
    """Coarse GPU memory of the newest telemetry sample (None without telemetry)."""
    try:
        value = samples[-1].get("gpu_memory_used_mib")
    except (IndexError, TypeError, AttributeError):
        return None
    return int(value) // GPU_BUCKET_MIB if isinstance(value, int) else None


class UncertainStall(Uncertain):
    """Raised after ``MAX_CONSECUTIVE_UNCERTAIN`` stalled windows whose LOST proof could not be established."""


class StallWatchdog:
    def __init__(self, *, stall_seconds: float, fingerprint: Callable[[], Any],
                 classify: Callable[[], Classification], on_alert: Callable[[dict[str, Any]], None],
                 clock: Callable[[], float] = time.monotonic,
                 on_stop: Callable[[dict[str, Any]], None] | None = None,
                 max_uncertain: int = MAX_CONSECUTIVE_UNCERTAIN) -> None:
        if stall_seconds <= 0:
            raise ValueError("stall_seconds must be positive")
        self.stall_seconds, self.fingerprint, self.classify = stall_seconds, fingerprint, classify
        self.on_alert, self.clock = on_alert, clock
        self.alerts = 0
        self.on_stop, self.max_uncertain, self.uncertain = on_stop, max_uncertain, 0
        self._last: Any = object()
        self._since = clock()

    def _current(self) -> Any:
        try:
            return self.fingerprint()
        except Exception as error:  # noqa: BLE001 - an unreadable probe is one constant state, not progress
            return ("unreadable", type(error).__name__)

    def check(self) -> None:
        now, fp = self.clock(), self._current()
        if fp != self._last:
            self._last, self._since = fp, now
            return
        quiet = now - self._since
        if quiet < self.stall_seconds:
            return
        verdict = self.classify()
        if verdict.lost:
            raise LostPrompt("the awaited prompt is LOST (ComfyUI restarted; prompt absent from history and "
                             "queue; no output)", classification=verdict)
        self.alerts += 1
        body = {"kind": "stall", "alert_number": self.alerts, "quiet_seconds": round(quiet, 3),
                "stall_seconds": self.stall_seconds, "classification": verdict.as_dict()}
        self.uncertain = self.uncertain + 1 if verdict.verdict == UNCERTAIN else 0
        if self.uncertain >= self.max_uncertain:
            stop = {**body, "kind": "stall_uncertain", "consecutive_uncertain": self.uncertain}
            if self.on_stop is not None:
                self.on_stop(stop)
            raise UncertainStall(
                f"stalled {self.uncertain} windows in a row and the LOST proof stayed UNCERTAIN "
                f"({verdict.reasons[0] if verdict.reasons else 'no reason'}); stopping instead of waiting for the "
                "hard timeout. Nothing was resubmitted", evidence={"stage": "stall_uncertain", **stop})
        self.on_alert(body)
        self._since = now
