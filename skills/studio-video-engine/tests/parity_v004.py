"""Golden parity: engine plan v2 (M3) against the frozen v004 PRODUCTION-PLAN.json, read-only.

Run as a script to write the diff summary:
    python -I tests/parity_v004.py <summary.json>
Reads the frozen plan, the 134 existing source segments (hash + ffprobe only, never re-cut)
and the 134 frozen API graph files; writes only the summary file you name.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from engine.config.loader import REPO_ROOT, resolve_episode  # noqa: E402
from engine.core.io import canonical_sha256, pretty_json, sha256_bytes  # noqa: E402
from engine.core.paths import resolve_data_path  # noqa: E402
from engine.seedvr2.plan import build_plan  # noqa: E402

EPISODE = REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom"
FROZEN_PLAN = EPISODE / "technical" / "seedvr2-production-v004" / "PRODUCTION-PLAN.json"
SEGMENTS_ROOT = EPISODE / "technical" / "seedvr2-production-v004"

# Fields compared 1:1 for every chunk.
SAME_FIELDS = (
    "index", "chunk_name", "core_start_frame", "core_end_frame_exclusive", "core_frames",
    "context_before_frames", "context_after_frames", "segment_start_frame",
    "segment_end_frame_exclusive", "segment_frames", "core_offset_in_segment",
    "seedvr2_padded_frames", "frame_range", "overlap", "segment_sha256",
    "comfy_input_name", "api_graph_canonical_sha256", "estimate",
)
ALLOWED_DIFFERENCES = {
    "schema": "plan schema name: milk-and-mom-seedvr2-production-plan/v004 -> jjv/seedvr2-plan/v2",
    "expected_output_frame_count": ("v004 stored the padded frame count as the expected raw output; v2 stores "
                                    "expected_raw_output_frames == segment_frames and keeps seedvr2_padded_frames "
                                    "informational"),
    "paths": "segment_path / api_graph_path are absolute in v004 and relative to their roots in v2",
    "renamed_fields": ("v004 chunk keys start/end (duplicates of segment_start_frame / "
                       "segment_end_frame_exclusive) are dropped; seam pair keys left/right_expected_core_output_frame "
                       "are renamed *_index; compared by value below"),
    "gui_graphs": "GUI graphs are not emitted by M3 (v004 emitted one per chunk)",
    "plan_envelope": ("plan-level keys (prepared_by, pilot_evidence, source_evidence, artifact_bindings, "
                      "object_info_validation, GUI paths, source absolute paths) differ by design"),
}


def _frozen_graph_path(chunk: dict) -> Path:
    """The frozen plan stores the graph path as it was on ``D:``; the engine reads the same file where the folder lives
    now (``machine.legacy_roots``).  The plan itself is hash-bound and never edited."""
    return resolve_data_path(chunk["api_graph_path"])


def compare(config, result, frozen: dict, frozen_graph_reader=None) -> dict:
    """Return the diff summary; ``differences`` holds only what is not in SAME_FIELDS equality."""
    frozen_shots = {s["shot_id"]: s for s in frozen["shots"]}
    mine = {s["shot_id"]: s for s in result.plan["shots"]}
    summary = {
        "shots": {"frozen": len(frozen_shots), "engine": len(mine),
                  "same_set": set(frozen_shots) == set(mine),
                  "same_order": [s["shot_id"] for s in frozen["shots"]] == [s["shot_id"] for s in result.plan["shots"]]},
        "chunks": {"frozen": 0, "engine": 0, "identical_core_ranges": 0, "identical_segment_ranges": 0,
                   "identical_segment_sha256": 0, "identical_input_names": 0,
                   "identical_api_canonical_sha256": 0, "identical_all_same_fields": 0,
                   "identical_emitted_graph_vs_frozen_graph_file": 0, "identical_graph_file_bytes": 0,
                   "start_end_equal_to_segment_range_and_dropped": 0},
        "seams": {"frozen": 0, "engine": 0, "identical_after_rename": 0},
        "differences": [],
        "allowed_differences": ALLOWED_DIFFERENCES,
        "expected_frames_difference": {"chunks_where_padded_differs_from_segment": 0, "examples": []},
    }
    diffs = summary["differences"]
    count = summary["chunks"]
    for shot_id, old in frozen_shots.items():
        new = mine.get(shot_id)
        if new is None:
            diffs.append({"shot": shot_id, "field": "shot", "frozen": "present", "engine": "missing"})
            continue
        for key, new_key in (("source_sha256", "source_sha256"), ("chunk_count", "chunk_count")):
            if old[key] != new[new_key]:
                diffs.append({"shot": shot_id, "field": key, "frozen": old[key], "engine": new[new_key]})
        if old["source_video"]["frames"] != new["source_video"]["frames"]:
            diffs.append({"shot": shot_id, "field": "source_video.frames"})
        _compare_chunks(shot_id, old, new, result, summary, frozen_graph_reader)
    return summary


def _compare_chunks(shot_id, old, new, result, summary, reader) -> None:
    count, diffs = summary["chunks"], summary["differences"]
    new_by_name = {c["chunk_name"]: c for c in new["chunks"]}
    for old_chunk in old["chunks"]:
        count["frozen"] += 1
        chunk = new_by_name.get(old_chunk["chunk_name"])
        if chunk is None:
            diffs.append({"shot": shot_id, "chunk": old_chunk["chunk_name"], "field": "chunk", "engine": "missing"})
            continue
        count["engine"] += 1
        mismatched = [k for k in SAME_FIELDS if old_chunk.get(k) != chunk.get(k)]
        for key in mismatched:
            diffs.append({"shot": shot_id, "chunk": chunk["chunk_name"], "field": key,
                          "frozen": old_chunk.get(key), "engine": chunk.get(key)})
        if not mismatched:
            count["identical_all_same_fields"] += 1
        if all(old_chunk[k] == chunk[k] for k in ("core_start_frame", "core_end_frame_exclusive", "core_frames", "core_offset_in_segment")):
            count["identical_core_ranges"] += 1
        if all(old_chunk[k] == chunk[k] for k in ("segment_start_frame", "segment_end_frame_exclusive", "segment_frames")):
            count["identical_segment_ranges"] += 1
        count["identical_segment_sha256"] += old_chunk["segment_sha256"] == chunk["segment_sha256"]
        count["identical_input_names"] += old_chunk["comfy_input_name"] == chunk["comfy_input_name"]
        count["identical_api_canonical_sha256"] += (
            old_chunk["api_graph_canonical_sha256"] == chunk["api_graph_canonical_sha256"])
        if old_chunk["pilot_diff"]["api_changed_keys"] != (chunk["pilot_diff"] or {}).get("api_changed_keys"):
            diffs.append({"shot": shot_id, "chunk": chunk["chunk_name"], "field": "pilot_diff.api_changed_keys"})
        if old_chunk["expected_core_output_frame_count"] != chunk["expected_core_output_frames"]:
            diffs.append({"shot": shot_id, "chunk": chunk["chunk_name"], "field": "expected_core_output_frames"})
        if chunk["expected_raw_output_frames"] != chunk["segment_frames"]:
            diffs.append({"shot": shot_id, "chunk": chunk["chunk_name"], "field": "expected_raw_output_frames != segment_frames"})
        if old_chunk["expected_output_frame_count"] != chunk["expected_raw_output_frames"]:
            info = summary["expected_frames_difference"]
            info["chunks_where_padded_differs_from_segment"] += 1
            if len(info["examples"]) < 3:
                info["examples"].append({"shot": shot_id, "chunk": chunk["chunk_name"],
                                         "v004_expected_output_frame_count": old_chunk["expected_output_frame_count"],
                                         "v2_expected_raw_output_frames": chunk["expected_raw_output_frames"]})
        _compare_graph(shot_id, old_chunk, chunk, result, summary, reader)
        _compare_renamed(shot_id, old_chunk, chunk, summary)
    _compare_seams(shot_id, old, new, summary)


def _compare_renamed(shot_id, old_chunk, chunk, summary) -> None:
    ok = (old_chunk["start"] == chunk["segment_start_frame"] and old_chunk["end"] == chunk["segment_end_frame_exclusive"]
          and "start" not in chunk and "end" not in chunk)
    summary["chunks"]["start_end_equal_to_segment_range_and_dropped"] += ok
    if not ok:
        summary["differences"].append({"shot": shot_id, "chunk": chunk["chunk_name"], "field": "start/end"})


def _compare_seams(shot_id, old, new, summary) -> None:
    renamed = {"left_expected_core_output_frame": "left_expected_core_output_frame_index",
               "right_expected_core_output_frame": "right_expected_core_output_frame_index"}
    pairs_old, pairs_new = old["seam_pairs_to_inspect"], new["seam_pairs_to_inspect"]
    summary["seams"]["frozen"] += len(pairs_old)
    summary["seams"]["engine"] += len(pairs_new)
    if len(pairs_old) != len(pairs_new):
        summary["differences"].append({"shot": shot_id, "field": "seam_pairs count"})
        return
    for left, right in zip(pairs_old, pairs_new):
        mapped = {renamed.get(key, key): value for key, value in left.items()}
        if mapped == right:
            summary["seams"]["identical_after_rename"] += 1
        else:
            summary["differences"].append({"shot": shot_id, "field": "seam_pair", "pair": left["left_chunk"]})


def _compare_graph(shot_id, old_chunk, chunk, result, summary, reader) -> None:
    count, diffs = summary["chunks"], summary["differences"]
    graph = result.graphs.get(chunk["api_graph_path"])
    frozen_path = _frozen_graph_path(old_chunk)
    frozen_graph = reader(frozen_path) if reader else json.loads(frozen_path.read_text(encoding="utf-8"))
    if graph is not None and canonical_sha256(graph, mode="ascii") == canonical_sha256(frozen_graph, mode="ascii"):
        count["identical_emitted_graph_vs_frozen_graph_file"] += 1
    else:
        diffs.append({"shot": shot_id, "chunk": chunk["chunk_name"], "field": "emitted graph vs frozen graph file"})
    if graph is not None and sha256_bytes(pretty_json(graph, mode="ascii")) == old_chunk["api_graph_file_sha256"]:
        count["identical_graph_file_bytes"] += 1
    else:
        diffs.append({"shot": shot_id, "chunk": chunk["chunk_name"], "field": "api_graph_file_sha256"})


def run(summary_path: Path | None = None) -> dict:
    config = resolve_episode("04-milk-and-mom")
    result = build_plan(config, repo_root=REPO_ROOT, segments_root=SEGMENTS_ROOT)
    frozen = json.loads(FROZEN_PLAN.read_text(encoding="utf-8"))
    summary = compare(config, result, frozen)
    summary["frozen_plan_sha256"] = sha256_bytes(FROZEN_PLAN.read_bytes())
    summary["engine_plan_status"] = result.plan["status"]
    summary["engine_totals"] = result.plan["totals"]
    summary["frozen_totals"] = frozen["totals"]
    summary["frozen_plan_schema"] = frozen["schema"]
    summary["engine_plan_schema"] = result.plan["schema"]
    summary["frozen_estimate"] = frozen["estimate"]
    summary["engine_estimate"] = result.plan["estimate"]
    if summary_path is not None:
        Path(summary_path).write_bytes(pretty_json(summary, mode="ascii"))
    return summary


if __name__ == "__main__":
    out = run(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(json.dumps({k: out[k] for k in ("shots", "chunks", "seams", "expected_frames_difference", "engine_totals")}, indent=2))
    print("differences:", len(out["differences"]))
    for item in out["differences"][:5]:
        print(" ", item)
    sys.exit(0 if not out["differences"] else 1)
