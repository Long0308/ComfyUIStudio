"""Q3 flash scan: per-frame mean luma; a spike or jump is allowed only where the boundary's transition says so.

* spike  = a frame whose luma differs from BOTH frames ``baseline_frames`` before and after it by at least
  ``spike_excess_min`` (a one-/few-frame white or black flash; ramps and shot changes do not trigger).
* A spike is allowed only inside a boundary window whose type is in ``spike_allowed_types`` (flash/dip/whip/...).
  A spike at a cut/push/none/iris/card boundary, or outside every boundary, FAILS with the frame list.
* A white-flash type (``needs_layout_change_types``) is allowed only when the picture really changes layout
  (user rule: same seat and angle, only props change -> hard cut + push-in, never a flash).  Layout change is
  measured: normalised correlation of the frame before the window and the frame after it must be BELOW
  ``same_framing_ncc_min``.  A config row may declare ``layout_change: false`` (or list the boundary in
  ``qa.review.layout_change_boundaries`` as a NON-change) to tighten; it can never turn a measured same-framing
  pair into a change.
* Non-flash boundaries also fail on a luma step above ``step_max_at_cut`` between consecutive frames.
"""

from __future__ import annotations

from typing import Any

from ..review_media import numpy_module
from ..review_model import Model, Transition
from . import FAIL, PASS, UNCERTAIN, roll_up


def luma_series(gray: Any) -> Any:
    np = numpy_module()
    return gray.reshape(gray.shape[0], -1).mean(axis=1, dtype=np.float64)


def spike_deviation(luma: Any, baseline: int) -> Any:
    """Per frame: how far it stands out from the frames ``baseline`` before and after it (either direction)."""
    np = numpy_module()
    n = len(luma)
    index = np.arange(n)
    left, right = luma[np.clip(index - baseline, 0, n - 1)], luma[np.clip(index + baseline, 0, n - 1)]
    return np.maximum(luma - np.maximum(left, right), np.minimum(left, right) - luma)


def window_of(t: Transition, margin: int) -> tuple[int, int]:
    """Inclusive global frame range a transition may disturb."""
    if t.frames == 0:
        return t.boundary - margin, t.boundary + margin
    return t.start - margin, max(t.end_exclusive, t.start + 1) - 1 + margin


def _small(frame: Any, cell: int = 4) -> Any:
    np = numpy_module()
    h, w = frame.shape
    return frame[: h // cell * cell, : w // cell * cell].astype(np.float64).reshape(h // cell, cell, w // cell, cell).mean((1, 3))


def ncc(a: Any, b: Any) -> float:
    np = numpy_module()
    x, y = a - a.mean(), b - b.mean()
    denom = float(np.sqrt((x * x).sum() * (y * y).sum()))
    return float((x * y).sum() / denom) if denom > 0 else 0.0


def same_framing_ncc(t: Transition, gray: Any, origin: int) -> float | None:
    """NCC of the last clean frame before the window and the first clean frame after it (None: not in file)."""
    before, after = t.start - 1, max(t.end_exclusive, t.boundary + 1)
    n = gray.shape[0]
    if not (0 <= before - origin < n and 0 <= after - origin < n):
        return None
    return ncc(_small(gray[before - origin]), _small(gray[after - origin]))


def _boundary_row(t: Transition, lo: int, hi: int, dev: Any, step: Any, origin: int, p: dict) -> dict:
    cut = slice(lo - origin, hi - origin + 1)
    spikes = [lo + int(i) for i in (dev[cut] >= p["spike_excess_min"]).nonzero()[0]]
    steps = step[max(lo - origin - 1, 0): hi - origin]
    return {"id": t.id, "boundary": t.boundary, "type": t.type, "window": [lo, hi], "spike_frames": spikes,
            "max_excess": round(float(dev[cut].max()), 1), "max_step": round(float(steps.max()) if len(steps) else 0.0, 1),
            "status": PASS, "reasons": []}


def _judge(row: dict, t: Transition, gray: Any, origin: int, p: dict, declared_false: frozenset[int]) -> None:
    allowed = t.type in p["spike_allowed_types"]
    if row["spike_frames"] and not allowed:
        row["status"] = FAIL
        row["reasons"].append(f"luma spike at a '{t.type}' boundary (allowed only at "
                              f"{'/'.join(p['spike_allowed_types'])}), frames {row['spike_frames']}")
    elif row["spike_frames"] and t.type in p["needs_layout_change_types"]:
        measured = same_framing_ncc(t, gray, origin)
        row["same_framing_ncc"] = None if measured is None else round(measured, 3)
        if t.layout_change is False or t.boundary in declared_false:
            row["status"] = FAIL
            row["reasons"].append(f"flash at '{t.type}' but the boundary is declared a non-layout-change, "
                                  f"frames {row['spike_frames']}")
        elif measured is None:
            row["status"] = UNCERTAIN
            row["reasons"].append("flash boundary: the frames before/after the window are not in the file, "
                                  "layout change cannot be measured")
        elif measured >= p["same_framing_ncc_min"]:
            row["status"] = FAIL
            row["reasons"].append(f"white flash between same-framing shots (ncc {measured:.2f} >= "
                                  f"{p['same_framing_ncc_min']}): use hard cut + push-in; flash frames {row['spike_frames']}")
    if not allowed and row["max_step"] > p["step_max_at_cut"]:
        row["status"] = FAIL
        row["reasons"].append(f"luma step {row['max_step']} at a '{t.type}' boundary exceeds {p['step_max_at_cut']}")


def run(model: Model, gray: Any, recipe: dict, origin: int = 0, layout_declared_false: frozenset[int] = frozenset()) -> dict:
    """Scan ``gray`` (frames, h, w) whose first frame is global frame ``origin``."""
    np = numpy_module()
    p = recipe["q3_flash"]
    n = gray.shape[0]
    luma = luma_series(gray)
    dev = spike_deviation(luma, p["baseline_frames"])
    step = np.abs(np.diff(luma)) if n > 1 else np.zeros(0)
    rows, covered = [], np.zeros(n, dtype=bool)
    for t in model.transitions:
        lo, hi = window_of(t, p["window_margin_frames"])
        if lo - origin < 0 or hi - origin >= n:
            continue  # window not (fully) in this file: not judged
        covered[lo - origin: hi - origin + 1] = True
        row = _boundary_row(t, lo, hi, dev, step, origin, p)
        _judge(row, t, gray, origin, p, layout_declared_false)
        rows.append(row)
    stray = [origin + int(i) for i in ((dev >= p["spike_excess_min"]) & ~covered).nonzero()[0]]
    failures = [f"{r['id']}: {reason}" for r in rows if r["status"] != PASS for reason in r["reasons"]]
    if stray:
        failures.append(f"luma spike outside every boundary window, frames {stray}")
    status = roll_up([r["status"] for r in rows] + ([FAIL] if stray else []))
    return {"gate": "Q3", "status": status, "frames_scanned": n, "origin": origin,
            "params": {k: p[k] for k in ("baseline_frames", "spike_excess_min", "step_max_at_cut", "same_framing_ncc_min")},
            "spikes_total": int((dev >= p["spike_excess_min"]).sum()), "stray_spike_frames": stray,
            "boundaries": rows, "failures": failures}
