"""Graph identity for ComfyUI prompt graphs as ComfyUI records them.

ComfyUI 0.41 stores some integer widget values as floats in ``/history`` (measured
2026-10-27 on a SeedVR2 tails run: SaveVideo ``format.codec.encoding.crf`` 16 -> 16.0).  The
identity form maps every finite integral float to ``int`` before canonicalising;
booleans stay booleans, so ``true``/``1`` are still different graphs and so are
``16``/``16.5``.
"""

from __future__ import annotations

import math
from typing import Any

from ..core.io import canonical_json, canonical_sha256


def normalize_numbers(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: normalize_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_numbers(item) for item in value]
    return value


def same_graph(left: object, right: object) -> bool:
    return canonical_json(normalize_numbers(left), mode="utf8") == canonical_json(
        normalize_numbers(right), mode="utf8")


def graph_shas(graph: object) -> frozenset[str]:
    """The canonical ascii sha of the graph as given and of its identity form.

    Compare SETS: our graph names a recorded graph when ``graph_shas(ours)`` and
    ``graph_shas(recorded)`` intersect (identity form against identity form).  A bare
    submitted sha only matches the recorded graph if no float was rewritten.
    """
    return frozenset({canonical_sha256(graph, mode="ascii"),
                      canonical_sha256(normalize_numbers(graph), mode="ascii")})


def as_sha_set(value: str | frozenset[str] | set[str]) -> frozenset[str]:
    """A sha or a set of acceptable shas for OUR graph, as a frozenset."""
    return frozenset({value}) if isinstance(value, str) else frozenset(value)


def wanted_shas(graph: object, *also: str) -> frozenset[str]:
    """Every sha that names our graph: as given, its identity form, plus any recorded receipt sha."""
    return graph_shas(graph) | frozenset(also)
