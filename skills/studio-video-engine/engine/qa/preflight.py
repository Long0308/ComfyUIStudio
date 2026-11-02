"""``jjv qa preflight``: every check that needs NO rendered pixels, run before a render is allowed.

Q1 word timing (the existing gate), pacing arithmetic, transitions (source clips), icons (files), audio contract
(receipts).  Verdict / exit code like ``qa review``: any FAIL -> ``FAIL`` (exit 1); else any UNCERTAIN -> ``UNCERTAIN``
(exit 2); else ``PASS`` (exit 0).  A check that cannot read an input is UNCERTAIN, a rule violation inside a check is a
FAIL of THAT check (the other checks still run and the report is complete).  ``SKIPPED`` (an optional input was not
given, listed in ``warnings``) never counts as a pass of that check.  The report carries no timestamp.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from ..core.errors import Refused, Uncertain
from . import preflight_audio, preflight_icons, preflight_pacing, preflight_q1, preflight_transitions
from .gates import FAIL, PASS, UNCERTAIN, roll_up
from .preflight_segments import pieces
from .review_model import build_model
from .review_recipe import effective_recipe

REPORT_SCHEMA = "jjv/qa-preflight-report/v1"
ALL_CHECKS = ("Q1", "PACING", "TRANSITIONS", "ICONS", "AUDIO")
EXIT = {PASS: 0, FAIL: 1, UNCERTAIN: 2}


def _guard(name: str, call: Callable[[], dict]) -> dict:
    """Uncertain -> this check UNCERTAIN; Refused (a rule) -> this check FAIL; the others still run."""
    try:
        return call()
    except Uncertain as error:
        return {"gate": name, "status": UNCERTAIN, "failures": [f"unreadable input: {error}"]}
    except Refused as error:
        return {"gate": name, "status": FAIL, "failures": [f"rule violation: {error}"]}


def apply_floors(recipe: dict, limits: dict | None, overrides: dict) -> dict:
    """The domain's section floors may only RAISE the review-recipe floors (never lower them)."""
    if not limits:
        return recipe
    pace = recipe["q5_pacing"]
    for key, floor in (("card_min_frames", limits.get("card_min")), ("logo_still_min_frames", limits.get("logo_hold_min"))):
        if isinstance(floor, int) and floor > pace[key]:
            pace[key] = floor
            overrides[f"q5_pacing.{key}"] = "domain"
    return recipe


def first_speech_s(config: dict, fps: float) -> float | None:
    starts = [w["startF"] for d in config.get("dialogue") or [] for w in d.get("words") or []
              if isinstance(w.get("startF"), (int, float)) and not isinstance(w.get("startF"), bool)]
    return min(starts) / fps if starts else None


def run_preflight(*, config: dict, config_sha256: str, root: Path, recipe: dict, recipe_sha256: str, pre: dict,
                  pre_sha256: str, timing_recipe: Any, ffmpeg: str, timing: Path | None = None, events: dict | None = None,
                  icons_dir: Path | None = None, contract: dict | None = None, expect_frames: int | None = None,
                  music_receipt: Path | None = None, mix_receipt: Path | None = None, with_sfx: bool = False,
                  allow_ungated: bool = False, require_audio: bool = False, allow: tuple = (),
                  declared_same_framing: frozenset[int] = frozenset(), checks: tuple[str, ...] = ALL_CHECKS,
                  limits: dict | None = None, episode_total: int | None = None) -> dict:
    """Run the selected checks on one review config and return the report (see module doc)."""
    unknown = sorted(set(checks) - set(ALL_CHECKS))
    if unknown:
        raise Refused(f"unknown preflight check(s) {unknown}; choose from {list(ALL_CHECKS)}")
    started = time.perf_counter()
    recipe, overrides = effective_recipe(recipe, config)
    recipe = apply_floors(recipe, limits, overrides)
    block = (config.get("qa") or {}).get("review") or {}
    declared = declared_same_framing | frozenset(block.get("layout_change_boundaries") or [])
    model = build_model(config, recipe, events)
    pcs = pieces(config, root)
    timing_path, timing_source = preflight_q1.timing_path_of(config, timing, root)
    steps: dict[str, Callable[[], dict]] = {
        "Q1": lambda: preflight_q1.run(config, root, timing_path, timing_source, timing_recipe, model.fps, allow),
        "PACING": lambda: preflight_pacing.run(config, model, recipe, pcs, expect_frames, contract, episode_total, limits),
        "TRANSITIONS": lambda: preflight_transitions.run(config, model, recipe, pre, pcs, ffmpeg, declared),
        "ICONS": lambda: preflight_icons.run(model, recipe, pre, root, ffmpeg, icons_dir),
        "AUDIO": lambda: preflight_audio.run(config, pre, music_path=music_receipt, mix_path=mix_receipt, with_sfx=with_sfx,
                                             allow_ungated=allow_ungated, require=require_audio,
                                             speech_start_s=first_speech_s(config, model.fps))}
    results, timing_s = {}, {}
    for name in ALL_CHECKS:
        if name in checks:
            mark = time.perf_counter()
            results[name] = _guard(name, steps[name])
            timing_s[name] = round(time.perf_counter() - mark, 2)
    timing_s["total"] = round(time.perf_counter() - started, 2)
    verdict = roll_up(r["status"] for r in results.values())
    warnings = [w for r in results.values() for w in r.get("warnings", [])]
    skipped = [n for n, r in results.items() if r["status"] == "SKIPPED"]
    return {"schema": REPORT_SCHEMA, "verdict": verdict, "ok": verdict == PASS, "exit_code": EXIT[verdict],
            "render_allowed": verdict == PASS, "gates": results, "skipped": skipped, "warnings": warnings,
            "config_sha256": config_sha256,
            "recipes": {"preflight": {"id": pre["id"], "sha256": pre_sha256},
                        "review": {"id": recipe["id"], "sha256": recipe_sha256, "overrides": overrides},
                        "timing": timing_recipe.recipe_id},
            "timing_s": timing_s,
            "caveats": ["no pixel of any render was read: Q2 on-screen tiles, Q3 flash scan, Q4 ghost and Q5 loudness run "
                        "after the render (`jjv qa review`)",
                        "a green preflight is necessary, not sufficient"]}
