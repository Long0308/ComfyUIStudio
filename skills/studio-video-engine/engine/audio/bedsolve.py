"""The cinema loudness solver: speech reaches -17 +-1 LUFS by its class BUS, never by lifting the bed.

Roles of a section: ``brand_voice`` (the brand voice alone, measured, never adjusted), ``speech`` (a dialogue,
vocabulary or end-line window overlaps it) and ``bed_only``.  Every speech WAV belongs to a class (dialogue,
vocabulary, end_line, any ``--extra-wav`` class); each class has ONE recorded bus gain (recipe ``speech_buses``:
``solve`` within ``[min_db, max_db]`` or ``fixed`` = pinned by an approved hand mix).  The bed gain of every
section starts at the RECIPE schedule (``music.gain_db`` story / ``music.section_gains_db`` outro, relative to the
base) and may only be LOWERED, never above it:

1. each solve class bus is set so the speech sections it appears in land in the band (most sections in band,
   then the smallest miss, then the nearest to the target); section loudness is ebur128 integrated over the whole
   section, bed included;
2. when a bus cannot do more and a speech section is still above the band, that section's bed is lowered, but only
   if the bed adds at least ``BED_AUTHORITY_LU`` to the speech alone;
3. bed-only sections are lowered until they sit at or below ``-22 + 3`` LUFS and at least ``below_speech_lu`` under
   their quietest neighbouring speech section (a bed-only section already under the band is not raised);
4. adjacent gains differ by at most ``max_bed_step_db``: the HIGHER one is lowered (never a raise).

A section too short to measure keeps its recipe gain (only the step limit can lower it).
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from . import loudness

Composer = Callable[[list[float], dict], dict]
PEAK_MARGIN_DB = 0.1
AIM_BELOW_LIMIT_DB = 0.5
BED_AUTHORITY_LU = 0.3   # a bed that adds less than this to its section's speech cannot lower the section
GRID_DB = 0.05


def measure_sections(final: np.ndarray, sections: list[dict], cfg: dict, rate: int, ffmpeg: str, runner,
                     roles: list[str] | None = None) -> list[dict]:
    """Per-section integrated loudness; a section shorter than ``min_measure_s`` (a bed-only one: ``bed_only.min_s``)
    is reported ``measurable: false``, never invented."""
    rows = []
    for index, section in enumerate(sections):
        floor = cfg["bed_only"]["min_s"] if roles is not None and roles[index] == "bed_only" else cfg["min_measure_s"]
        piece = final[section["start_sample"]:section["end_sample"]]
        row = {"name": section["name"], "start_frame": section["start_frame"],
               "end_frame_exclusive": section["end_frame_exclusive"], "duration_s": piece.shape[0] / rate,
               "integrated_lufs": None, "true_peak_dbtp": None, "measurable": False}
        if piece.shape[0] / rate >= floor:
            result = loudness.measure(piece, rate, ffmpeg, runner=runner)
            row.update(integrated_lufs=result.integrated_lufs, true_peak_dbtp=result.true_peak_dbtp,
                       measurable=result.measurable)
        rows.append(row)
    return rows


def roles_of(sections: list[dict], windows: list[dict]) -> list[str]:
    """``brand_voice`` by name, ``speech`` when a speech window overlaps the section, else ``bed_only``."""
    out = []
    for section in sections:
        if section["name"] == "brand_voice":
            out.append("brand_voice")
        elif any(w["start_sample"] < section["end_sample"] and w["end_sample"] > section["start_sample"] for w in windows):
            out.append("speech")
        else:
            out.append("bed_only")
    return out


def bus_spec(buses_cfg: dict, name: str) -> dict:
    return buses_cfg.get(name) or buses_cfg["*"]


def initial_buses(classes: list[str], buses_cfg: dict) -> dict[str, float]:
    """Pinned classes start (and stay) at their ``gain_db``; solve classes start at 0 dB inside their range."""
    out = {}
    for name in classes:
        spec = bus_spec(buses_cfg, name)
        if spec["mode"] == "fixed":
            out[name] = float(spec.get("gain_db", 0.0))
        else:
            out[name] = min(spec.get("max_db", 3.0), max(spec.get("min_db", -3.0), 0.0))
    return out


def limit_steps(gains: list[float], max_step: float) -> bool:
    """|g[i] - g[i+1]| <= max_step by LOWERING the higher of two neighbours (never raising); True if anything moved."""
    changed = False
    for _ in range(64):
        moved = False
        for i in range(len(gains) - 1):
            low, high = (i, i + 1) if gains[i] <= gains[i + 1] else (i + 1, i)
            if gains[high] - gains[low] > max_step + 1e-9:
                gains[high], moved, changed = gains[low] + max_step, True, True
        if not moved:
            break
    return changed


def choose_gain(levels: list[float], current: float, cfg: dict, low_db: float, high_db: float) -> float:
    """The bus gain in ``[low_db, high_db]`` that puts the MOST of ``levels`` in the band (ties: the smaller total miss,
    then the nearest to the target, then the smaller gain).  ``levels`` were measured at ``current``; a bus gain moves
    speech 1:1."""
    band_high, band_low, target = cfg["target_lufs"] + cfg["tolerance_lu"], cfg["target_lufs"] - cfg["tolerance_lu"], cfg["target_lufs"]
    best = None
    for step in range(int(round((high_db - low_db) / GRID_DB)) + 1):
        gain = round(low_db + step * GRID_DB, 4)
        shifted = [value + gain - current for value in levels]
        misses = [max(0.0, value - band_high, band_low - value) for value in shifted]
        key = (sum(m > 1e-9 for m in misses), round(sum(misses), 3), round(sum(abs(v - target) for v in shifted), 3), abs(gain))
        if best is None or key < best[0]:
            best = (key, gain)
    return best[1]


def bed_only_upper(index: int, rows: list[dict], roles: list[str], cfg: dict) -> float:
    """The loudest a bed-only section may be: ``-22 + 3`` and ``below_speech_lu`` under its quietest speech neighbour."""
    spec = cfg["bed_only"]
    upper = spec["target_lufs"] + spec["tolerance_lu"]
    near = [rows[j]["integrated_lufs"] for j in (index - 1, index + 1)
            if 0 <= j < len(rows) and roles[j] == "speech" and rows[j]["measurable"]]
    return min([upper] + [value - spec["below_speech_lu"] for value in near])


def target_gains(compose: Composer, sections: list[dict], roles: list[str], schedule_db: list[float], cfg: dict, rate: int,
                 ffmpeg: str, runner, emit: Callable[[str], None] = lambda m: None, *,
                 section_classes: list[set[str]] | None = None, buses_cfg: dict | None = None,
                 ) -> tuple[list[float], dict[str, float], list[dict], dict]:
    """``(bed gains per section, bus gain per speech class, history, last bundle)``; ``compose(gains, buses)`` returns the
    bundle with the int16 ``final`` and ``speech_bus``.  ``schedule_db`` = the recipe gain of every section re the base."""
    classes_in = section_classes or [{"dialogue"} if r == "speech" else set() for r in roles]
    spec = buses_cfg or {"*": {"mode": "solve", "min_db": -3.0, "max_db": 3.0}}
    names = sorted({c for group in classes_in for c in group})
    buses = initial_buses(names, spec)
    gains = list(schedule_db)
    history: list[dict] = []
    bundle = compose(gains, buses)
    high, low = cfg["target_lufs"] + cfg["tolerance_lu"], cfg["target_lufs"] - cfg["tolerance_lu"]
    for iteration in range(cfg["max_iterations"]):
        rows = measure_sections(bundle["final"], sections, cfg, rate, ffmpeg, runner, roles)
        whole = loudness.measure(bundle["final"], rate, ffmpeg, runner=runner)
        history.append({"iteration": iteration, "gains_db": [round(g, 3) for g in gains],
                        "buses_db": {k: round(v, 3) for k, v in buses.items()},
                        "section_lufs": [r["integrated_lufs"] for r in rows], "whole": whole.as_dict()})
        emit(f"loudness iteration {iteration}: {[r['integrated_lufs'] for r in rows]} whole {whole.integrated_lufs} buses {buses}")
        before, before_buses = list(gains), dict(buses)
        if whole.true_peak_dbtp is not None and whole.true_peak_dbtp > cfg["true_peak_max_dbtp"]:
            drop = whole.true_peak_dbtp - cfg["true_peak_max_dbtp"] + PEAK_MARGIN_DB
            gains = [max(cfg["bed_gain_min_db"], g - drop) for g in gains]
        speech = [(i, r["integrated_lufs"]) for i, r in enumerate(rows) if roles[i] == "speech" and r["measurable"]]
        for name in names:
            cls_spec = bus_spec(spec, name)
            levels = [v for i, v in speech if name in classes_in[i]]
            if cls_spec["mode"] == "solve" and levels and (max(levels) > high or min(levels) < low):
                buses[name] = choose_gain(levels, buses[name], cfg, cls_spec.get("min_db", -3.0), cls_spec.get("max_db", 3.0))
        stuck = max((v for _, v in speech), default=0.0) > high and all(abs(buses[n] - before_buses[n]) <= 0.01 for n in names)
        if stuck:  # no bus can do more: lower the loud sections' beds, but only where the bed counts
            alone = measure_sections(bundle["speech_bus"], sections, cfg, rate, ffmpeg, runner, roles)
            for i, value in speech:
                bed_adds = alone[i]["measurable"] and value - alone[i]["integrated_lufs"] >= BED_AUTHORITY_LU
                if value > high and bed_adds:
                    gains[i] = max(cfg["bed_gain_min_db"], gains[i] - (value - (high - AIM_BELOW_LIMIT_DB)))
        for i, row in enumerate(rows):
            if roles[i] == "bed_only" and row["measurable"]:
                upper = bed_only_upper(i, rows, roles, cfg)
                if row["integrated_lufs"] > upper:
                    gains[i] = max(cfg["bed_gain_min_db"], gains[i] - (row["integrated_lufs"] - (upper - AIM_BELOW_LIMIT_DB)))
        limit_steps(gains, cfg["max_bed_step_db"])
        gains = [min(g, cap) for g, cap in zip(gains, schedule_db)]  # never above the recipe gain
        moved = any(abs(a - b) > 0.01 for a, b in zip(gains, before)) or any(abs(buses[n] - before_buses[n]) > 0.01 for n in names)
        if not moved:
            break
        bundle = compose(gains, buses)
    return gains, buses, history, bundle
