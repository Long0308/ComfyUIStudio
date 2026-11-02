"""Recipe of ``jjv qa preflight`` (``recipes/qa/preflight-v001.json``): only the numbers the review recipe has no key for.

Pacing floors and icon thresholds are read from the REVIEW recipe (``review_recipe.effective_recipe``), so
there is one number in one place and a config ``qa.review`` block can still only tighten it.  A malformed or
missing recipe is an unreadable input (``Uncertain``), like the review recipe.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..config.loader import SKILL_ROOT
from ..core.errors import Uncertain
from ..core.io import read_json, sha256_file

RECIPE_SCHEMA = "jjv/qa-preflight-recipe/v1"
DEFAULT_RECIPE = SKILL_ROOT / "recipes" / "qa" / "preflight-v001.json"
BLOCKS = ("timing", "transitions", "icons", "audio")


def _number(block: dict, key: str, label: str, low: float, high: float) -> None:
    value = block.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise Uncertain(f"{label}.{key} must be a number in [{low}, {high}], got {value!r}")


def _validate(recipe: Any, name: str) -> dict:
    if not isinstance(recipe, dict) or recipe.get("schema") != RECIPE_SCHEMA:
        raise Uncertain(f"{name}: not a {RECIPE_SCHEMA} document")
    for key in BLOCKS:
        if not isinstance(recipe.get(key), dict):
            raise Uncertain(f"{name}: block {key!r} is missing")
    if not isinstance(recipe["timing"].get("recipe_id"), str):
        raise Uncertain(f"{name}: timing.recipe_id must be a string")
    _number(recipe["transitions"], "same_framing_ncc_min_source", "transitions", 0.0, 1.0)
    renders = recipe["transitions"].get("flash_renders_as")
    if not isinstance(renders, list) or not all(isinstance(r, str) for r in renders):
        raise Uncertain(f"{name}: transitions.flash_renders_as must be a list of names")
    _number(recipe["audio"], "brand_voice_guard_s", "audio", 0.0, 5.0)
    return recipe


def load_recipe(path: Path | None = None) -> tuple[dict, str]:
    """(recipe, sha256 of the file)."""
    target = Path(path) if path else DEFAULT_RECIPE
    return _validate(read_json(target), target.name), sha256_file(target)
