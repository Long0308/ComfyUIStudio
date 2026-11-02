"""The film-mix QA gate of ``jjv audio mix`` (the solver itself is ``bedsolve``).

``evaluate`` turns the measurements into the verdict.  Speech sections (dialogue, outro cards, end plate) and
the whole film sit in ``target +- tolerance`` LUFS, the brand voice alone in its own band, a bed-only section in
``-22 +- 3`` and under its quietest speech neighbour by ``below_speech_lu``; true peak under the ceiling; no
level jump above the limit between adjacent SPEECH sections; the bed never above its recipe gain and never more
than ``max_bed_step_db`` from a neighbour; no pumping; dialogue samples exact.  A ``legacy`` recipe is measured but
never judged (``UNGATED``).
"""

from __future__ import annotations

import numpy as np

from . import dsp
from .bedsolve import bed_only_upper, limit_steps, measure_sections, roles_of, target_gains  # noqa: F401  (re-exported)


def _section_of(sample: int, sections: list[dict]) -> int:
    for index, section in enumerate(sections):
        if section["start_sample"] <= sample < section["end_sample"]:
            return index
    return -1


def pumping(music: np.ndarray, duck_rows: list[dict], cfg: dict, rate: int, sections: list[dict], duck_cfg: dict) -> dict:
    """Duck depth per speech window >= ``min_window_s``: the bed's RMS in the ``gap_s`` just outside the window's attack /
    release ramps (where no other window reaches) minus its RMS inside the window.  Pumping = the swing of that depth
    between consecutive windows of the SAME section; the musical dynamics of the bed itself cancel out of the depth."""
    attack, release, gap = int(round(duck_cfg["attack_s"] * rate)), int(round(duck_cfg["release_s"] * rate)), int(round(cfg["gap_s"] * rate))
    total, depths = music.shape[0], []
    for index, row in enumerate(duck_rows):
        start, end = row["start_sample"], row["end_sample_exclusive"]
        if (end - start) / rate < cfg["min_window_s"]:
            continue
        free = lambda lo, hi: lo >= 0 and hi <= total and not any(  # noqa: E731
            o is not row and o["start_sample"] - attack < hi and o["end_sample_exclusive"] + release > lo for o in duck_rows)
        regions = [(start - attack - gap, start - attack), (end + release, end + release + gap)]
        outside = [dsp.rms_dbfs(music[lo:hi]) for lo, hi in regions if free(lo, hi)]
        if outside:
            inside = dsp.rms_dbfs(music[start:end])
            depths.append({"id": row["id"], "section": _section_of(start, sections), "inside_rms_dbfs": inside,
                           "outside_rms_dbfs": round(sum(outside) / len(outside), 3),
                           "depth_db": round(sum(outside) / len(outside) - inside, 3)})
    swings = [{"between": [a["id"], b["id"]], "swing_db": round(abs(a["depth_db"] - b["depth_db"]), 3)}
              for a, b in zip(depths, depths[1:]) if a["section"] == b["section"]]
    worst = max(swings, key=lambda w: w["swing_db"], default=None)
    return {"windows_measured": len(depths), "pairs_compared": len(swings),
            "max_swing_db": worst["swing_db"] if worst else 0.0, "worst_pair": worst["between"] if worst else None,
            "limit_db": cfg["max_swing_db"], "depths": depths, "swings": swings}


def _bus_limit_note(row: dict, value: float, buses: dict, high: float, low: float) -> str:
    """Name the class buses of a section that are already at the limit that would have helped."""
    pinned = []
    for name in row.get("classes", []):
        bus = buses.get(name)
        if bus is None:
            continue
        if bus["mode"] == "fixed":
            pinned.append(f"{name} bus pinned at {bus['gain_db']} dB")
        elif value > high and bus["gain_db"] <= bus.get("min_db", -3.0) + 0.01:
            pinned.append(f"{name} bus already at its floor {bus.get('min_db', -3.0)} dB")
        elif value < low and bus["gain_db"] >= bus.get("max_db", 3.0) - 0.01:
            pinned.append(f"{name} bus already at its ceiling {bus.get('max_db', 3.0)} dB")
    return f" ({'; '.join(pinned)})" if pinned else ""


def evaluate(profile: str, loud_cfg: dict, pump_cfg: dict, whole: dict, rows: list[dict], pump: dict,
             dialogue_exact: bool, gains_db: list[float] | None = None, buses: dict | None = None,
             caps_db: list[float] | None = None) -> dict:
    """``{verdict, failures[], unmeasured[]}``; ``rows[i]["role"]`` (default ``speech``) selects the band."""
    failures: list[str] = []
    if not dialogue_exact:
        failures.append("dialogue samples in the stem differ from the receipt WAVs")
    unmeasured = [r["name"] for r in rows if not r["measurable"]]
    if profile != "cinema":
        return {"verdict": "FAIL" if failures else "UNGATED", "failures": failures, "unmeasured": unmeasured}
    roles = [r.get("role", "speech") for r in rows]
    low, high = loud_cfg["target_lufs"] - loud_cfg["tolerance_lu"], loud_cfg["target_lufs"] + loud_cfg["tolerance_lu"]
    if whole["integrated_lufs"] is None or not low <= whole["integrated_lufs"] <= high:
        failures.append(f"whole film {whole['integrated_lufs']} LUFS outside [{low}, {high}]")
    brand = loud_cfg["brand_voice"]
    for index, row in enumerate(rows):
        if not row["measurable"]:
            continue
        value, role = row["integrated_lufs"], roles[index]
        if role == "brand_voice":
            if abs(value - brand["target_lufs"]) > brand["tolerance_lu"]:
                failures.append(f"brand voice {value} LUFS outside {brand['target_lufs']} +- {brand['tolerance_lu']}")
        elif role == "bed_only":
            lower, upper = loud_cfg["bed_only"]["target_lufs"] - loud_cfg["bed_only"]["tolerance_lu"], bed_only_upper(index, rows, roles, loud_cfg)
            if not lower <= value <= upper:
                failures.append(f"bed-only section {row['name']} {value} LUFS outside [{lower}, {round(upper, 2)}]")
        elif not low <= value <= high:
            note = _bus_limit_note(row, value, buses or {}, high, low)
            failures.append(f"section {row['name']} {value} LUFS outside [{low}, {high}]{note}")
    if whole["true_peak_dbtp"] is not None and whole["true_peak_dbtp"] > loud_cfg["true_peak_max_dbtp"]:
        failures.append(f"true peak {whole['true_peak_dbtp']} dBTP above {loud_cfg['true_peak_max_dbtp']}")
    for a, b, ra, rb in zip(rows, rows[1:], roles, roles[1:]):
        if ra == rb == "speech" and a["measurable"] and b["measurable"] and \
                abs(a["integrated_lufs"] - b["integrated_lufs"]) > loud_cfg["max_section_jump_lu"]:
            failures.append(f"jump {a['name']} -> {b['name']}: "
                            f"{abs(a['integrated_lufs'] - b['integrated_lufs']):.2f} LU > {loud_cfg['max_section_jump_lu']}")
    for index, (a, b) in enumerate(zip(gains_db or [], (gains_db or [])[1:])):
        if abs(a - b) > loud_cfg["max_bed_step_db"] + 1e-6:
            failures.append(f"bed step {rows[index]['name']} -> {rows[index + 1]['name']}: {abs(a - b):.2f} dB > {loud_cfg['max_bed_step_db']}")
    for index, (gain, cap) in enumerate(zip(gains_db or [], caps_db or [])):
        if gain > cap + 1e-6:
            failures.append(f"bed of section {rows[index]['name']} is {gain - cap:.2f} dB above its recipe gain")
    if pump["max_swing_db"] > pump_cfg["max_swing_db"]:
        failures.append(f"pumping: music RMS swings {pump['max_swing_db']} dB between {pump['worst_pair']} > {pump_cfg['max_swing_db']}")
    return {"verdict": "FAIL" if failures else "PASS", "failures": failures, "unmeasured": unmeasured}
