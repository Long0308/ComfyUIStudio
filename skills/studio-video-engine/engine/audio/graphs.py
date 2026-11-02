"""Fill the named slots of a recipe graph template and prove nothing else changed.

A recipe carries one API graph (the one that actually ran) and a ``slots`` table
``{name: [[node, input], ...]}``.  :func:`fill_slots` writes the values into a COPY, and
:func:`require_only_slots_differ` re-derives the diff against the template: any path that differs but is
not a slot is ``Refused`` (the SeedVR2 ``allowed_api_diff_paths`` idea).  Graph identity is the canonical
ascii sha, the same one ``engine.comfy.dispatch`` records.
"""

from __future__ import annotations

import copy
from typing import Any

from ..core.errors import Refused
from ..core.io import canonical_sha256

MIN_LATENT_SECONDS = 1.0
SLOT_TYPES = {"style": str, "lyrics": str, "prompt": str, "negative": str, "filename_prefix": str,
              "seed": int, "seconds": (int, float)}


def _check_value(name: str, value: Any) -> None:
    expected = SLOT_TYPES.get(name)
    if expected is None:
        raise Refused(f"unknown slot {name!r}")
    if isinstance(value, bool) or not isinstance(value, expected):
        raise Refused(f"slot {name!r} needs {expected}, got {value!r}")
    if name == "seconds" and not value >= MIN_LATENT_SECONDS:
        raise Refused(f"slot 'seconds' must be >= {MIN_LATENT_SECONDS} (ComfyUI rejects a shorter audio latent)")
    if isinstance(value, str) and name != "lyrics" and not value.strip():
        raise Refused(f"slot {name!r} is blank")


def fill_slots(recipe: dict, values: dict[str, Any]) -> dict[str, Any]:
    """A new graph: the recipe template with every slot set; the template itself is never mutated."""
    slots = recipe["slots"]
    if set(values) != set(slots):
        raise Refused(f"slot values {sorted(values)} do not match the recipe slots {sorted(slots)}")
    graph = copy.deepcopy(recipe["graph"])
    for name, pairs in slots.items():
        _check_value(name, values[name])
        for node, field in pairs:
            graph[node]["inputs"][field] = float(values[name]) if name == "seconds" else values[name]
    require_only_slots_differ(recipe, graph)
    return graph


def slot_paths(recipe: dict) -> set[tuple[str, str]]:
    return {(node, field) for pairs in recipe["slots"].values() for node, field in pairs}


def require_only_slots_differ(recipe: dict, graph: dict) -> None:
    template = recipe["graph"]
    if set(graph) != set(template):
        raise Refused("filled graph has other node ids than the recipe template")
    allowed = slot_paths(recipe)
    for node_id, node in template.items():
        filled = graph[node_id]
        if filled.get("class_type") != node.get("class_type") or set(filled["inputs"]) != set(node["inputs"]):
            raise Refused(f"node {node_id}: class or input names differ from the recipe template")
        for field, value in node["inputs"].items():
            if filled["inputs"][field] != value and (node_id, field) not in allowed:
                raise Refused(f"node {node_id}.{field} differs from the recipe template and is not a slot")


def graph_sha256(graph: dict) -> str:
    return canonical_sha256(graph, mode="ascii")
