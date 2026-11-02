"""Timing recipe: every threshold of the word-timing rules and of the Q1 gate (no number is code).

``recipes/timing/<id>.json`` is validated against ``TIMING_RECIPE_SCHEMA`` and turned into frozen
parameter blocks.  The machine/domain/episode schemas are frozen, so the timing stage reads its
optional keys through :func:`optional_block` (absent = default, nothing re-hashed); see
``CLI-PATCH.md`` for the keys root adds later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.loader import SKILL_ROOT, ResolvedConfig
from ..config.schema import validate
from ..core.errors import Refused
from ..core.io import read_json, sha256_file

FAMILY = "timing"
TIMING_ID = re.compile(r"^timing/[a-z0-9][a-z0-9._-]*$")
RECIPE_SCHEMA_ID = "jjv/timing-recipe/v1"


def _block(required: dict[str, str]) -> dict:
    """A closed object whose every key is required; the value is a JSON type name."""
    return {"type": "object", "additionalProperties": False, "required": sorted(required),
            "properties": {key: {"type": kind} for key, kind in required.items()}}


_NUM = "number"
TIMING_RECIPE_SCHEMA: dict = {
    "type": "object", "additionalProperties": False,
    "required": ["schema", "recipe_id", "family", "domain", "language", "document_schema", "recognition", "first_word",
                 "all_words", "q1"],
    "properties": {
        "schema": {"const": RECIPE_SCHEMA_ID},
        "recipe_id": {"type": "string", "pattern": "^timing/[a-z0-9][a-z0-9._-]*$"},
        "family": {"const": FAMILY},
        "domain": {"type": "string", "minLength": 1},
        "language": {"type": "string", "minLength": 1},
        "document_schema": {"type": "string", "minLength": 1},  # the layout id the editorial stage reads (data, not engine source)
        "note": {"type": "string"},
        "recognition": _block({
            "engine": "string", "model_label": "string", "device": "string", "compute_type": "string",
            "beam_size": "integer", "best_of": "integer", "patience": _NUM, "temperature": _NUM,
            "vad_filter": "boolean", "condition_on_previous_text": "boolean", "prompt_from": "string",
            "accept_similarity": _NUM, "timeout_seconds": _NUM}),
        "first_word": {
            "type": "object", "additionalProperties": False,
            "required": ["hop_s", "threshold_dbfs", "merge_gap_s", "sustained_run_s", "isolated_gap_s",
                         "move_min_s", "unvoiced_preroll_s", "calibrate_last_end", "voiced"],
            "properties": {
                **{k: {"type": _NUM} for k in ("hop_s", "threshold_dbfs", "merge_gap_s", "sustained_run_s",
                                               "isolated_gap_s", "move_min_s", "unvoiced_preroll_s")},
                "calibrate_last_end": {"type": "boolean"},
                "voiced": _block({"window_s": _NUM, "hop_s": _NUM, "loud_dbfs": _NUM, "autocorr_min": _NUM,
                                  "pitch_min_hz": _NUM, "pitch_max_hz": _NUM, "centroid_max_hz": _NUM,
                                  "fft_size": "integer", "search_s": _NUM, "lead_back_s": _NUM})}},
        "all_words": {
            "type": "object", "additionalProperties": False,
            "required": ["window_s", "hop_s", "floor_dbfs", "floor_window_s", "voiced_dbfs", "sustain_s",
                         "edge_dbfs", "end_margin_frames", "search_past_end_s", "pause"],
            "properties": {
                **{k: {"type": _NUM} for k in ("window_s", "hop_s", "floor_dbfs", "floor_window_s",
                                               "voiced_dbfs", "sustain_s", "edge_dbfs", "search_past_end_s")},
                "end_margin_frames": {"type": "integer", "minimum": 0},
                "pause": _block({"near_s": _NUM, "mid_s": _NUM, "near_min_s": _NUM, "far_min_s": _NUM,
                                 "max_shift_s": _NUM, "search_extra_s": _NUM})}},
        "q1": _block({"window_s": _NUM, "silence_dbfs": _NUM, "edge_dbfs": _NUM, "pause_min_s": _NUM,
                      "pause_start_max_s": _NUM, "lookback_s": _NUM, "word_end_margin_s": _NUM,
                      "search_after_start_s": _NUM, "max_early_frames": "integer", "max_late_frames": "integer",
                      "control_shift_frames": "integer"}),
    },
}


Q1_OPTIONAL = {"onset_voiced_dbfs": {"type": _NUM}, "onset_sustain_s": {"type": _NUM},
               "warn_late_frames": {"type": "integer", "minimum": 0},
               "extra_control_shift_frames": {"type": "array", "items": {"type": "integer", "minimum": 1}}}
TIMING_RECIPE_SCHEMA["properties"]["q1"]["properties"].update(Q1_OPTIONAL)
TIMING_RECIPE_SCHEMA["properties"]["default_for_domain"] = {"type": "boolean"}


@dataclass(frozen=True)
class TimingRecipe:
    recipe_id: str
    path: Path
    sha256: str
    data: dict

    def block(self, name: str) -> dict:
        return self.data[name]


def optional_block(document: Any, key: str) -> dict:
    """An optional object-valued key; absent or non-object reads as ``{}`` (never raises)."""
    value = document.get(key) if isinstance(document, dict) else None
    return value if isinstance(value, dict) else {}


def load_timing_recipe(recipe_id: str, *, skill_root: Path = SKILL_ROOT) -> TimingRecipe:
    """Read and schema-check ``recipes/timing/<id>.json``; a bad or missing recipe is Refused."""
    if "/" not in recipe_id or recipe_id.split("/", 1)[0] != FAMILY:
        raise Refused(f"timing recipe id must be 'timing/<name>', got {recipe_id!r}")
    path = skill_root / "recipes" / f"{recipe_id}.json"
    if not path.is_file():
        raise Refused(f"timing recipe not found: {path}")
    data = read_json(path)
    errors = validate(data, TIMING_RECIPE_SCHEMA, label=f"recipe[{recipe_id}]")
    if errors:
        raise Refused("; ".join(errors))
    q = data["q1"]
    if ("onset_voiced_dbfs" in q) != ("onset_sustain_s" in q):
        raise Refused(f"recipe {recipe_id}: q1.onset_voiced_dbfs and q1.onset_sustain_s go together")
    if q.get("warn_late_frames", q["max_late_frames"]) < q["max_late_frames"]:
        raise Refused(f"recipe {recipe_id}: q1.warn_late_frames is below max_late_frames")
    if data["recipe_id"] != recipe_id:
        raise Refused(f"recipe file {path.name} declares recipe_id {data['recipe_id']!r}, expected {recipe_id!r}")
    return TimingRecipe(recipe_id=recipe_id, path=path, sha256=sha256_file(path), data=data)


def select_recipe_id(config: ResolvedConfig, explicit: str | None, *, skill_root: Path = SKILL_ROOT) -> tuple[str, str]:
    """``--recipe`` > ``episode.timing.recipe`` > the domain's default: the one recipe of the domain with
    ``default_for_domain: true`` (or, with no default flagged, the only recipe of the domain)."""
    if explicit:
        return explicit, "cli"
    declared = optional_block(config.episode, "timing").get("recipe")
    if isinstance(declared, str) and declared:
        return declared, "episode.timing.recipe"
    domain_id = config.domain["domain_id"]
    found, defaults = [], []
    for path in sorted((skill_root / "recipes" / FAMILY).glob("*.json")):
        data = read_json(path)
        if isinstance(data, dict) and data.get("domain") == domain_id and data.get("family") == FAMILY:
            found.append(str(data.get("recipe_id")))
            if data.get("default_for_domain") is True:
                defaults.append(str(data.get("recipe_id")))
    if len(defaults) == 1:
        return defaults[0], "default recipe for the domain"
    if not defaults and len(found) == 1:
        return found[0], "unique recipe for the domain"
    raise Refused(f"no timing recipe selected for domain {domain_id!r}: pass --recipe or set episode.timing.recipe "
                  f"(candidates: {found})")


def domain_allowed_ids(domain: dict) -> list[str]:
    """``domain.timing.allowed_recipes`` as a list of unique ``timing/<name>`` ids.

    A missing block/key means timing is disabled (never "allow all"); a malformed one is Refused.
    """
    domain_id = domain.get("domain_id")
    block = domain.get("timing")
    if block is None or (isinstance(block, dict) and "allowed_recipes" not in block):
        raise Refused(f"domain {domain_id!r} is missing timing.allowed_recipes; timing is disabled")
    allowed = block.get("allowed_recipes") if isinstance(block, dict) else None
    if (not isinstance(allowed, list) or len(set(map(str, allowed))) != len(allowed)
            or not all(isinstance(i, str) and TIMING_ID.match(i) for i in allowed)):
        raise Refused(f"domain {domain_id!r} has invalid timing.allowed_recipes; expected unique timing/<name> IDs")
    return allowed


def resolve_recipe(config: ResolvedConfig, explicit: str | None, *, skill_root: Path = SKILL_ROOT) -> tuple[TimingRecipe, str]:
    """The recipe for an episode plus where the choice came from.

    Authorization: the selected id must be listed in ``domain.timing.allowed_recipes`` (exact match; the empty list
    refuses everything and the selector never switches to another listed recipe).  A recipe of another domain is Refused.
    """
    allowed = domain_allowed_ids(config.domain)
    recipe_id, origin = select_recipe_id(config, explicit, skill_root=skill_root)
    if recipe_id not in allowed:
        raise Refused(f"domain {config.domain['domain_id']!r} does not list timing recipe {recipe_id!r} "
                      f"in timing.allowed_recipes")
    recipe = load_timing_recipe(recipe_id, skill_root=skill_root)
    if recipe.data["domain"] != config.domain["domain_id"]:
        raise Refused(f"recipe {recipe_id!r} belongs to domain {recipe.data['domain']!r}, "
                      f"episode domain is {config.domain['domain_id']!r}")
    return recipe, origin
