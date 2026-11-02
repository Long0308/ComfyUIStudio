"""Timeline coverage: pure range logic, reads from review configs, tail maps, and the ``plan`` hook."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from engine.config import loader
from engine.core.errors import Refused, exit_code_for
from engine.core.io import sha256_file
from engine.seedvr2 import coverage as cv
from engine.seedvr2.cli_cut import coverage_inputs
from engine.seedvr2.plan import build_plan
from test_seedvr2_segments_support import make_world

SHA = "ab" * 32


def review(**changes) -> dict:
    doc = {"fps": 30,
           "dialogue": [{"id": "S01_A", "segments": [{"source_id": "S01_A", "native_frames": 40}]},
                        {"id": "S06_B", "segments": [{"source_id": "S06_B1", "native_frames": 20, "relative_start_frame": 0},
                                                     {"source_id": "S06_B2", "native_frames": 30, "relative_start_frame": 25}]}],
           "motion": {"transitions": [
               {"id": "T40", "frames": 9, "outgoing_tail": {
                   "shot": "S01_A", "native_path": "n/S01_A-native.mp4", "native_sha256": SHA, "native_frames": 47,
                   "editorial_frames": 40, "last_native_index_used": 42, "tail_output_frames": 3,
                   "start_from_frame": 50}},
               {"id": "T7", "frames": 4, "type": "none"}]}}
    doc.update(changes)
    return doc


# ---- range arithmetic -------------------------------------------------------------------------
def test_merge_and_uncovered() -> None:
    assert cv.merge_ranges([(5, 9), (0, 3), (3, 4), (8, 12), (20, 20)]) == [(0, 4), (5, 12)]
    assert cv.uncovered(0, 20, [(2, 5), (8, 10)]) == [(0, 2), (5, 8), (10, 20)]
    assert cv.uncovered(3, 4, [(0, 10)]) == []
    assert cv.uncovered(10, 12, [(0, 10)]) == [(10, 12)]


def test_find_gaps_merges_reads_and_names_them() -> None:
    reads = [cv.Read("A", 0, 10, "dialogue"), cv.Read("A", 10, 13, "T1 tail"), cv.Read("A", 12, 15, "T2 tail"),
             cv.Read("B", 0, 5, "dialogue")]
    gaps = cv.find_gaps(reads, {"A": [(0, 10)], "B": [(0, 5)]})
    assert [(g.shot, g.start, g.end, g.reasons()) for g in gaps] == [("A", 10, 15, ["T1 tail", "T2 tail"])]


def test_read_of_an_unknown_shot_is_refused() -> None:
    with pytest.raises(Refused, match="not a shot of the plan"):
        cv.find_gaps([cv.Read("Z", 0, 1, "x")], {"A": [(0, 1)]})


def test_add_scope_never_mutates_and_rejects_unknown_shot() -> None:
    base = {"A": [(0, 10)]}
    grown = cv.add_scope(base, [("A", 10, 12)])
    assert grown == {"A": [(0, 12)]} and base == {"A": [(0, 10)]}
    with pytest.raises(Refused):
        cv.add_scope(base, [("Q", 0, 1)])


def test_check_coverage_refuses_with_evidence_and_ok_returns_a_record() -> None:
    scope = {"A": [(0, 10)]}
    with pytest.raises(Refused, match=r"A f10\.\.f12") as caught:
        cv.check_coverage([cv.Read("A", 0, 13, "T tail")], scope)
    assert caught.value.evidence["missing"][0] == {
        "shot": "A", "start_frame": 10, "end_frame_exclusive": 13, "frames": 3, "reasons": ["T tail"]}
    assert exit_code_for(caught.value) == 1
    record = cv.check_coverage([cv.Read("A", 2, 10, "d")], scope)
    assert record["ok"] and record["read_count"] == 1 and record["scope"] == {"A": [[0, 10]]}


# ---- reads from documents ---------------------------------------------------------------------
def test_reads_from_a_review_config() -> None:
    reads = cv.reads_from_review_config(review())
    assert [(r.shot, r.start, r.end) for r in reads] == [
        ("S01_A", 0, 40), ("S06_B1", 0, 20), ("S06_B2", 0, 30), ("S01_A", 40, 43)]
    tail = reads[-1]
    assert tail.source == {"path": "n/S01_A-native.mp4", "sha256": SHA, "frames": 47}
    assert tail.transition == {"id": "T40", "delivery_start_frame": 50, "output_frames": 3, "delivery_fps": 30}


def test_a_tail_needing_no_frame_past_the_cut_is_not_a_read() -> None:
    doc = review()
    doc["motion"]["transitions"][0]["outgoing_tail"]["last_native_index_used"] = 39
    assert [r.reason for r in cv.reads_from_review_config(doc)] == ["dialogue S01_A", "dialogue S06_B", "dialogue S06_B"]


@pytest.mark.parametrize("edit,match", [
    (lambda d: d["dialogue"][0]["segments"][0].update(native_frames=0), "native_frames"),
    (lambda d: d["dialogue"][0]["segments"][0].update(source_id=""), "source_id"),
    (lambda d: d["motion"]["transitions"][0]["outgoing_tail"].update(last_native_index_used=47), "past the native clip"),
    (lambda d: d["motion"]["transitions"][0]["outgoing_tail"].update(native_sha256="zz"), "native_sha256"),
    (lambda d: d["motion"]["transitions"][0]["outgoing_tail"].update(start_from_frame=True), "start_from_frame"),
])
def test_malformed_reads_are_refused(edit, match) -> None:
    doc = review()
    edit(doc)
    with pytest.raises(Refused, match=match):
        cv.reads_from_review_config(doc)


def test_a_document_without_reads_is_refused() -> None:
    with pytest.raises(Refused, match="no timeline reads"):
        cv.reads_from_review_config({"fps": 30})


def test_load_reads_review_config_with_bom_and_explicit_document(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(review()).encode())
    reads, digest = cv.load_reads(path)
    assert len(reads) == 4 and digest == sha256_file(path)
    explicit = tmp_path / "reads.json"
    explicit.write_text(json.dumps({"schema": cv.READS_SCHEMA, "reads": [
        {"shot": "A", "start_frame": 3, "end_frame_exclusive": 9, "reason": "manual"}]}))
    assert cv.load_reads(explicit)[0] == [cv.Read("A", 3, 9, "manual", None, None)]
    explicit.write_text(json.dumps({"schema": cv.READS_SCHEMA, "reads": [
        {"shot": "A", "start_frame": 9, "end_frame_exclusive": 9}]}))
    with pytest.raises(Refused, match="end_frame_exclusive"):
        cv.load_reads(explicit)


# ---- tail maps --------------------------------------------------------------------------------
def tail_map(tmp_path: Path, schema: str = "jjv/master-tail-map/v1") -> Path:
    clip = tmp_path / "master-tails" / "A-tail.mp4"
    clip.parent.mkdir()
    clip.write_bytes(b"clip")
    path = tmp_path / "MASTER-TAIL-MAP.json"
    path.write_text(json.dumps({"schema": schema, "tails": [
        {"shot": "A", "clip": "master-tails/A-tail.mp4", "clip_sha256": sha256_file(clip), "frames": 7,
         "native_first": 100}]}))
    return path


@pytest.mark.parametrize("schema", ["jjv/master-tail-map/v1", "mam-r27-master-tail-map/v1"])
def test_tail_map_gives_ranges_for_both_schemas(tmp_path: Path, schema: str) -> None:
    assert cv.load_tail_map(tail_map(tmp_path, schema)) == [("A", 100, 107)]


def test_tail_map_with_missing_or_changed_clip_covers_nothing(tmp_path: Path) -> None:
    path = tail_map(tmp_path)
    (tmp_path / "master-tails" / "A-tail.mp4").write_bytes(b"other")
    with pytest.raises(Refused, match="sha256 differs"):
        cv.load_tail_map(path)
    (tmp_path / "master-tails" / "A-tail.mp4").unlink()
    with pytest.raises(Refused, match="missing"):
        cv.load_tail_map(path)
    assert cv.load_tail_map(path, verify_files=False) == [("A", 100, 107)]


def test_tail_map_schema_and_content_are_checked(tmp_path: Path) -> None:
    bad = tmp_path / "m.json"
    bad.write_text(json.dumps({"schema": "nope", "tails": []}))
    with pytest.raises(Refused, match="not a master tail map"):
        cv.load_tail_map(bad)
    bad.write_text(json.dumps({"schema": "jjv/master-tail-map/v1", "tails": []}))
    with pytest.raises(Refused, match="lists no tails"):
        cv.load_tail_map(bad)


def test_cli_coverage_inputs(tmp_path: Path) -> None:
    reads_path = tmp_path / "r.json"
    reads_path.write_text(json.dumps(review()))
    assert coverage_inputs(Namespace(reads=None, tail_map=[])) == (None, [])
    with pytest.raises(Refused, match="--tail-map needs --reads"):
        coverage_inputs(Namespace(reads=None, tail_map=["x"]))
    reads, extra = coverage_inputs(Namespace(reads=str(reads_path), tail_map=[str(tail_map(tmp_path))]))
    assert len(reads) == 4 and extra == [("A", 100, 107)]


# ---- the plan hook ----------------------------------------------------------------------------
def test_plan_refuses_uncovered_reads_before_binding_any_source(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    for clip in (world.root / "clips").glob("*.mp4"):
        clip.unlink()  # sources are gone: a refusal that names the gap proves no source was touched first
    with pytest.raises(Refused, match=r"S01_A f40\.\.f42") as caught:
        build_plan(world.config, repo_root=loader.REPO_ROOT, reads=world.reads)
    assert caught.value.evidence["stage"] == "coverage_gap"


def test_plan_with_covered_reads_records_the_coverage(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    reads = world.reads[:2]
    from test_seedvr2_segments_support import fake_probe
    result = build_plan(world.config, repo_root=loader.REPO_ROOT, reads=reads, probe=fake_probe)
    assert result.plan["coverage"]["ok"] and result.plan["coverage"]["scope"]["S01_A"] == [[0, 40]]
    plain = build_plan(world.config, repo_root=loader.REPO_ROOT, probe=fake_probe).plan
    assert "coverage" not in plain, "a plan without --reads is byte-for-byte what it was before this gate"


def test_plan_accepts_the_tail_scope_and_refuses_once_it_is_dropped(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    from test_seedvr2_segments_support import fake_probe
    ok = build_plan(world.config, repo_root=loader.REPO_ROOT, reads=world.reads, extra_scope=[("S01_A", 36, 43)],
                    probe=fake_probe)
    assert ok.plan["coverage"]["scope"]["S01_A"] == [[0, 43]]
    with pytest.raises(Refused, match="S01_A") as caught:
        build_plan(world.config, repo_root=loader.REPO_ROOT, reads=world.reads, extra_scope=[("S01_A", 36, 42)],
                   probe=fake_probe)  # one tail frame short
    assert caught.value.evidence["missing"][0]["start_frame"] == 42


def test_a_read_past_the_clip_without_a_tail_is_a_gap(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    reads = [cv.Read("S02_A", 0, 33, "dialogue S02_A (editor says 33 frames, clip has 30)")]
    with pytest.raises(Refused, match=r"S02_A f30\.\.f32"):
        build_plan(world.config, repo_root=loader.REPO_ROOT, reads=reads)
