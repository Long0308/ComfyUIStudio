"""Film-mix standard (user rule 2026-10-27): the limits a ``cinema`` mix recipe may TIGHTEN but never loosen.

A recipe states its own numbers; ``check_cinema`` refuses any value outside these ranges, exactly like the
QA thresholds of ``jjv qa av``.  The ``legacy`` profile exists only to reproduce a historical stem and is
never gated (its receipt says ``UNGATED``).
"""

from __future__ import annotations

from ..core.errors import Refused

LUFS_TARGET = -17.0
LUFS_TOLERANCE_MAX = 1.0
TRUE_PEAK_CEILING_DBTP = -1.0
SECTION_JUMP_MAX_LU = 2.0
DUCK_DEPTH_RANGE_DB = (-8.0, -6.0)
DUCK_ATTACK_RANGE_S = (0.1, 0.2)
DUCK_RELEASE_RANGE_S = (0.5, 1.0)
DUCK_MERGE_GAP_RANGE_S = (1.0, 3.0)
PUMP_SWING_MAX_DB = 3.0
BUS_SOLVE_RANGE_DB = (-3.0, 3.0)    # a speech class BUS (one recorded scalar per class) the solver may set
BUS_FIXED_RANGE_DB = (-6.0, 3.0)    # a bus pinned by an episode recipe (an approved hand mix)
PUMP_MIN_WINDOW_S = 1.0             # pumping is judged on speech windows at least this long
BED_STEP_MAX_DB = 3.0               # bed gain change between adjacent sections
RAMP_MIN_S = 1.0                    # the bed gain moves over at least this long
VOCAL_WINDOW_DBFS_MAX = -40.0      # no 1 s window of the vocal stem above this (RMS dBFS)
VOCAL_REL_DB_MAX = -35.0            # a music bed's vocal stem, relative to the bed, may not exceed this
BED_GAIN_STORY_MAX_DB = -6.0        # the bed under speech: 3 dB under the v014 mix (story -3.0 -> -6.0)
BED_GAIN_OUTRO_MAX_DB = -4.5        # ... and for the outro sections (v014 -1.5 -> -4.5)
BED_ONLY_TARGET = (-22.0, 3.0)      # a bed-only section sits at -22 +- 3 LUFS (a recipe may only tighten the tolerance)
BED_BELOW_SPEECH_MIN_LU = 3.0       # and at least this far under its quietest neighbouring speech section
BRAND_VOICE_TARGET = (-16.0, 1.5)   # the brand voice measured alone


def _inside(value: float, bounds: tuple[float, float], label: str) -> str | None:
    low, high = bounds
    return None if low <= value <= high else f"{label} {value} outside the film-mix range [{low}, {high}]"


def cinema_problems(recipe: dict, *, sfx_default_on_allowed: bool = False) -> list[str]:
    duck, loud, pump = recipe["duck"], recipe["loudness"], recipe["pumping"]
    found = [
        _inside(duck["depth_db"], DUCK_DEPTH_RANGE_DB, "duck.depth_db"),
        _inside(duck["attack_s"], DUCK_ATTACK_RANGE_S, "duck.attack_s"),
        _inside(duck["release_s"], DUCK_RELEASE_RANGE_S, "duck.release_s"),
        _inside(duck["merge_gap_s"], DUCK_MERGE_GAP_RANGE_S, "duck.merge_gap_s"),
    ]
    if not (loud["enabled"] and pump["enabled"]):
        found.append("a cinema recipe may not disable the loudness or pumping gate")
    if loud["target_lufs"] != LUFS_TARGET:
        found.append(f"loudness.target_lufs {loud['target_lufs']} must be {LUFS_TARGET}")
    if loud["tolerance_lu"] > LUFS_TOLERANCE_MAX:
        found.append(f"loudness.tolerance_lu {loud['tolerance_lu']} exceeds {LUFS_TOLERANCE_MAX}")
    if loud["true_peak_max_dbtp"] > TRUE_PEAK_CEILING_DBTP:
        found.append(f"loudness.true_peak_max_dbtp {loud['true_peak_max_dbtp']} exceeds {TRUE_PEAK_CEILING_DBTP}")
    if loud["max_section_jump_lu"] > SECTION_JUMP_MAX_LU:
        found.append(f"loudness.max_section_jump_lu {loud['max_section_jump_lu']} exceeds {SECTION_JUMP_MAX_LU}")
    if pump["max_swing_db"] > PUMP_SWING_MAX_DB:
        found.append(f"pumping.max_swing_db {pump['max_swing_db']} exceeds {PUMP_SWING_MAX_DB}")
    music = recipe["music"]
    if music["gain_db"] > BED_GAIN_STORY_MAX_DB:
        found.append(f"music.gain_db {music['gain_db']} is louder than {BED_GAIN_STORY_MAX_DB}")
    for name, gain in music["section_gains_db"].items():
        if gain > BED_GAIN_OUTRO_MAX_DB:
            found.append(f"music.section_gains_db[{name}] {gain} is louder than {BED_GAIN_OUTRO_MAX_DB}")
    if loud["bed_gain_max_db"] > 0:
        found.append("loudness.bed_gain_max_db must be <= 0: the solver may lower the bed, never raise it above the recipe gain")
    bed_only, brand = loud["bed_only"], loud["brand_voice"]
    if bed_only["target_lufs"] != BED_ONLY_TARGET[0] or bed_only["tolerance_lu"] > BED_ONLY_TARGET[1]:
        found.append(f"loudness.bed_only must be {BED_ONLY_TARGET[0]} +- at most {BED_ONLY_TARGET[1]} LUFS")
    if bed_only["below_speech_lu"] < BED_BELOW_SPEECH_MIN_LU:
        found.append(f"loudness.bed_only.below_speech_lu {bed_only['below_speech_lu']} is under {BED_BELOW_SPEECH_MIN_LU}")
    if brand["target_lufs"] != BRAND_VOICE_TARGET[0] or brand["tolerance_lu"] > BRAND_VOICE_TARGET[1]:
        found.append(f"loudness.brand_voice must be {BRAND_VOICE_TARGET[0]} +- at most {BRAND_VOICE_TARGET[1]} LUFS")
    if loud["max_bed_step_db"] > BED_STEP_MAX_DB:
        found.append(f"loudness.max_bed_step_db {loud['max_bed_step_db']} exceeds {BED_STEP_MAX_DB}")
    if loud["ramp_s"] < RAMP_MIN_S:
        found.append(f"loudness.ramp_s {loud['ramp_s']} is below {RAMP_MIN_S}")
    if pump["min_window_s"] < PUMP_MIN_WINDOW_S:
        found.append(f"pumping.min_window_s {pump['min_window_s']} is below {PUMP_MIN_WINDOW_S}")
    for name, bus in recipe["speech_buses"].items():
        if bus["mode"] == "fixed":
            if not BUS_FIXED_RANGE_DB[0] <= bus.get("gain_db", 0.0) <= BUS_FIXED_RANGE_DB[1]:
                found.append(f"speech_buses[{name}] fixed gain {bus.get('gain_db')} outside {BUS_FIXED_RANGE_DB}")
        elif bus.get("min_db", BUS_SOLVE_RANGE_DB[0]) < BUS_SOLVE_RANGE_DB[0] or bus.get("max_db", BUS_SOLVE_RANGE_DB[1]) > BUS_SOLVE_RANGE_DB[1]:
            found.append(f"speech_buses[{name}] solve range outside {BUS_SOLVE_RANGE_DB}")
    if recipe["sfx"]["default_enabled"] and not sfx_default_on_allowed:
        found.append("sfx.default_enabled must be false unless the domain grants audio.sfx_default_on "
                     "(SFX/ambience are opt-in per episode otherwise; sfx.default_on_decision is provenance, not permission)")
    return [item for item in found if item]


def music_problems(recipe: dict) -> list[str]:
    gate = recipe["vocal_gate"]
    found = [] if gate["limit_db"] <= VOCAL_REL_DB_MAX else [f"vocal_gate.limit_db {gate['limit_db']} is looser than {VOCAL_REL_DB_MAX}"]
    if gate.get("window_limit_dbfs", VOCAL_WINDOW_DBFS_MAX) > VOCAL_WINDOW_DBFS_MAX:
        found.append(f"vocal_gate.window_limit_dbfs {gate['window_limit_dbfs']} is looser than {VOCAL_WINDOW_DBFS_MAX}")
    return found


def require_music(recipe: dict) -> None:
    problems = music_problems(recipe)
    if problems:
        raise Refused(f"music recipe {recipe['recipe_id']!r} loosens the vocal-free standard: " + "; ".join(problems))


def require_cinema(recipe: dict, *, sfx_default_on_allowed: bool = False) -> None:
    problems = cinema_problems(recipe, sfx_default_on_allowed=sfx_default_on_allowed)
    if problems:
        raise Refused(f"mix recipe {recipe['recipe_id']!r} loosens the film-mix standard: " + "; ".join(problems))
