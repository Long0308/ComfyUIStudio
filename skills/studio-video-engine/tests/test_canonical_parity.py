"""Golden parity: engine canonical hashing reproduces every v004 plan graph hash.

Read-only access to the frozen plan and graph files (no writes, no locks).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import frozen
from engine.core.io import canonical_sha256, read_json, sha256_file
from engine.core.paths import resolve_data_path

PLAN = frozen.REPO_ROOT / (
    "production-local/JennieJoyKids-Story/04-milk-and-mom/technical/"
    "seedvr2-production-v004/PRODUCTION-PLAN.json"
)


def _graph(chunk: dict) -> Path:
    """The frozen plan names each graph under the retired ``D:`` root; the engine reads the same file where it lives now
    (``machine.legacy_roots``).  The plan is hash-bound and never edited."""
    return resolve_data_path(chunk["api_graph_path"])


@pytest.fixture(scope="module")
def chunks() -> list[dict]:
    if not PLAN.is_file():
        pytest.skip("v004 plan not present on this machine")
    plan = read_json(PLAN)
    return [chunk for shot in plan["shots"] for chunk in shot["chunks"]]


def test_plan_lists_134_graphs(chunks: list[dict]) -> None:
    assert len(chunks) == 134


def test_ascii_canonical_hash_matches_all_134(chunks: list[dict]) -> None:
    mismatches = []
    for chunk in chunks:
        graph = read_json(_graph(chunk))
        if canonical_sha256(graph, mode="ascii") != chunk["api_graph_canonical_sha256"]:
            mismatches.append(chunk["api_graph_path"])
    assert mismatches == []


def test_graph_file_hashes_match_all_134(chunks: list[dict]) -> None:
    bad = [
        c["api_graph_path"]
        for c in chunks
        if sha256_file(_graph(c)) != c["api_graph_file_sha256"]
    ]
    assert bad == []


def test_utf8_mode_agrees_on_these_ascii_only_graphs(chunks: list[dict]) -> None:
    """Documents plan finding 0.2: the two modes coincide for ASCII graphs."""
    for chunk in chunks:
        graph = read_json(_graph(chunk))
        assert canonical_sha256(graph, mode="utf8") == chunk["api_graph_canonical_sha256"]
