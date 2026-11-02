"""Golden parity of engine plan v2 against the frozen v004 PRODUCTION-PLAN.json (read-only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import parity_v004
from engine import frozen


@pytest.fixture(scope="module")
def summary(tmp_path_factory) -> dict:
    target = tmp_path_factory.mktemp("parity") / "PARITY-SUMMARY.json"
    result = parity_v004.run(target)
    assert json.loads(target.read_text("utf-8"))["chunks"] == result["chunks"]
    return result


def test_same_14_shots_in_the_same_order(summary) -> None:
    assert summary["shots"] == {"frozen": 14, "engine": 14, "same_set": True, "same_order": True}


def test_134_chunk_ranges_and_segment_hashes_are_identical(summary) -> None:
    chunks = summary["chunks"]
    assert chunks["frozen"] == chunks["engine"] == 134
    for key in ("identical_core_ranges", "identical_segment_ranges", "identical_segment_sha256",
                "identical_input_names", "identical_api_canonical_sha256", "identical_all_same_fields"):
        assert chunks[key] == 134, key


def test_dropped_and_renamed_fields_equal_by_value(summary) -> None:
    assert summary["chunks"]["start_end_equal_to_segment_range_and_dropped"] == 134
    seams = summary["seams"]
    assert seams["frozen"] == seams["engine"] == seams["identical_after_rename"] == 120  # 134 chunks - 14 shots


def test_every_emitted_graph_equals_the_frozen_graph_file(summary) -> None:
    chunks = summary["chunks"]
    assert chunks["identical_emitted_graph_vs_frozen_graph_file"] == 134
    assert chunks["identical_graph_file_bytes"] == 134  # same pretty-ascii bytes, so same file sha


def test_no_unlisted_difference_exists(summary) -> None:
    assert summary["differences"] == []
    assert set(summary["allowed_differences"]) == {
        "schema", "expected_output_frame_count", "paths", "renamed_fields", "gui_graphs", "plan_envelope"}


def test_the_only_semantic_change_is_expected_frames(summary) -> None:
    info = summary["expected_frames_difference"]
    assert info["chunks_where_padded_differs_from_segment"] == 15
    assert all(e["v004_expected_output_frame_count"] > e["v2_expected_raw_output_frames"] for e in info["examples"])
    assert summary["engine_plan_schema"] == "jjv/seedvr2-plan/v2"
    assert summary["frozen_plan_schema"] == "milk-and-mom-seedvr2-production-plan/v004"


def test_totals_and_estimates_match(summary) -> None:
    assert summary["engine_totals"]["total_chunks"] == summary["frozen_totals"]["total_chunks"] == 134
    assert summary["engine_totals"]["total_source_frames"] == summary["frozen_totals"]["total_source_frames"] == 1656
    assert summary["engine_estimate"]["gpu_seconds_conservative"] == summary["frozen_estimate"]["gpu_seconds_conservative"]
    assert (summary["engine_estimate"]["gpu_seconds_linear_by_padded_frames"]
            == summary["frozen_estimate"]["gpu_seconds_linear_by_padded_frames"])


def test_the_comparison_detects_a_tampered_engine_plan(tmp_path: Path) -> None:
    """A parity gate that never fails proves nothing: break one hash and one range."""
    from engine.config.loader import REPO_ROOT, resolve_episode
    from engine.seedvr2.plan import PlanResult, build_plan
    config = resolve_episode("04-milk-and-mom")
    result = build_plan(config, repo_root=REPO_ROOT, segments_root=parity_v004.SEGMENTS_ROOT)
    plan = json.loads(json.dumps(result.plan))
    chunk = plan["shots"][2]["chunks"][3]
    chunk["segment_sha256"] = "0" * 64
    chunk["core_offset_in_segment"] += 1
    frozen_plan = json.loads(parity_v004.FROZEN_PLAN.read_text("utf-8"))
    out = parity_v004.compare(config, PlanResult(plan, result.graphs), frozen_plan)
    assert out["chunks"]["identical_segment_sha256"] == 133 and out["differences"]
    fields = {d["field"] for d in out["differences"]}
    assert {"segment_sha256", "core_offset_in_segment"} <= fields


def test_parity_reads_left_the_frozen_files_untouched() -> None:
    assert all(item.match for item in frozen.verify_files(frozen.load_manifest()))
