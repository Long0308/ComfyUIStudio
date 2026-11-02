"""Recipe of ``jjv qa review``: thresholds live in ``recipes/qa/review-gates-*.json``, never in code.

A review config may carry a ``qa.review`` block, but it can only TIGHTEN a threshold (like ``qa.av``):
a looser, non-finite or unknown value is ``Refused``, so a config cannot declare its own way to a PASS.
Allowed non-numeric additions: ``opposite_pairs`` (more pairs), ``layout_change_boundaries``
(see ``q3_flash``: only a declared NON-change counts), ``expect_total_frames``.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

from ..config.loader import SKILL_ROOT
from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file

RECIPE_SCHEMA = "jjv/qa-review-recipe/v1"
DEFAULT_RECIPE = SKILL_ROOT / "recipes" / "qa" / "review-gates-v001.json"
GATE_KEYS = ("q2_icons", "q3_flash", "q4_ghost", "q5_pacing")
# A smaller value is the stricter one ...
LOWER_TIGHTER = {"q2_icons": ("frame_tolerance",),
                 "q3_flash": ("spike_excess_min", "step_max_at_cut"),
                 "q4_ghost": ("ghost_fail", "ghost_warn", "mirror_rise_warn"),
                 "q5_pacing": ("tolerance_lu", "max_section_jump_lu", "still_diff_max")}
# ... and here a larger one.
HIGHER_TIGHTER = {"q2_icons": ("min_delta_e_file", "min_delta_e_screen", "min_hue_distance_deg"),
                  "q3_flash": ("same_framing_ncc_min",),
                  "q5_pacing": ("logo_still_min_frames", "card_min_frames")}
EXTRA_KEYS = ("opposite_pairs", "layout_change_boundaries", "expect_total_frames")


def load_recipe(path: Path | None = None) -> tuple[dict, str]:
    """(recipe, sha256 of the file).  A missing or malformed recipe is an unreadable input."""
    target = Path(path) if path else DEFAULT_RECIPE
    recipe = read_json(target)
    if not isinstance(recipe, dict) or recipe.get("schema") != RECIPE_SCHEMA:
        raise Uncertain(f"{target.name}: not a {RECIPE_SCHEMA} document")
    for key in GATE_KEYS:
        if not isinstance(recipe.get(key), dict):
            raise Uncertain(f"{target.name}: block {key!r} is missing")
    return recipe, sha256_file(target)


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Refused(f"config.qa.review.{label} must be a finite number, got {value!r}")
    return float(value)


def _tighten_gate(base: dict, gate: str, block: Any, sources: dict[str, str]) -> None:
    if not isinstance(block, dict):
        raise Refused(f"config.qa.review.{gate} must be an object")
    for key, value in block.items():
        lower, higher = key in LOWER_TIGHTER.get(gate, ()), key in HIGHER_TIGHTER.get(gate, ())
        if not (lower or higher):
            raise Refused(f"config.qa.review.{gate}.{key} is not a tightenable threshold")
        number = _finite(value, f"{gate}.{key}")
        if (lower and number > base[gate][key]) or (higher and number < base[gate][key]):
            raise Refused(f"config.qa.review.{gate}.{key} {number} is looser than the recipe value "
                          f"{base[gate][key]}: the config may only tighten the thresholds")
        base[gate][key] = number
        sources[f"{gate}.{key}"] = "config"


def _extras(base: dict, block: dict, sources: dict[str, str]) -> None:
    pairs = block.get("opposite_pairs")
    if pairs is not None:
        if not isinstance(pairs, list) or any(not (isinstance(p, list) and len(p) == 2 and all(
                isinstance(t, str) and t.strip() for t in p)) for p in pairs):
            raise Refused("config.qa.review.opposite_pairs must be a list of [term, term]")
        known = {tuple(sorted(p)) for p in base["q2_icons"]["opposite_pairs"]}
        base["q2_icons"]["opposite_pairs"] += [p for p in pairs if tuple(sorted(p)) not in known]
        sources["q2_icons.opposite_pairs"] = "recipe + config"
    frames = block.get("layout_change_boundaries")
    if frames is not None:
        if not isinstance(frames, list) or any(isinstance(f, bool) or not isinstance(f, int) for f in frames):
            raise Refused("config.qa.review.layout_change_boundaries must be a list of integer frames")
    expect = block.get("expect_total_frames")
    if expect is not None and (isinstance(expect, bool) or not isinstance(expect, int) or expect <= 0):
        raise Refused("config.qa.review.expect_total_frames must be a positive integer")


def effective_recipe(recipe: dict, config: dict) -> tuple[dict, dict[str, str]]:
    """The recipe with the config's ``qa.review`` overrides applied (tighten-only); also returns the
    source of every overridden value."""
    block = ((config.get("qa") or {}).get("review")) or {}
    if not isinstance(block, dict):
        raise Refused("config.qa.review must be an object")
    allowed = set(GATE_KEYS) | set(EXTRA_KEYS)
    unknown = sorted(set(block) - allowed)
    if unknown:
        raise Refused(f"config.qa.review has unknown key(s) {unknown}")
    merged, sources = copy.deepcopy(recipe), {}
    for gate in GATE_KEYS:
        if gate in block:
            _tighten_gate(merged, gate, block[gate], sources)
    _extras(merged, block, sources)
    return merged, sources


def normalise_type(raw: Any, recipe: dict) -> str:
    """Canonical snake_case transition type: ``dip`` -> ``dip_white``, ``card-slide`` -> ``card_slide``."""
    text = str(raw or "none").strip().lower().replace("-", "_").replace(" ", "_")
    return recipe.get("type_aliases", {}).get(text, text)
