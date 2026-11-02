"""``jjv plan explain``: master target, pins, cut points, slice policy, the slice property test and its mutant, read-only."""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
from pathlib import Path

import pytest

import test_plan_support as S
from engine.core.errors import Refused
from engine.plan import graph, slices
from test_plan_support import base_config, mix_plan, mutate, record, rows, run, shot_of, sha, write_version

POLICY = json.loads((S.PLAN_DIR / "policy-v001.json").read_text("utf-8"))


def _pair(tmp_path: Path, new_config: dict, *, old_config: dict | None = None, old_rec=None, new_rec=None,
          old_desc=None, new_desc=None, **kw) -> dict:
    old = write_version(tmp_path, "old", old_config or base_config(), plan=mix_plan(), record=old_rec or record(), descriptor=old_desc)
    new = write_version(tmp_path, "new", new_config, plan=mix_plan(), record=new_rec or record(), descriptor=new_desc)
    return run(old, new, **kw)


def _changed(doc: dict, kind: str = "composite.segment") -> set[str]:
    return {n.split("[")[1][:-1] for n, r in rows(doc, kind=kind).items() if r["status"] != "UNCHANGED"}


def _core(config: dict) -> None:
    shot_of(config, "S01_B")["segments"][0]["sha256"] = sha("clip-S01_B-v2")


# ---- master target ----------------------------------------------------------------------------------------------------
def test_master_target_prices_4k_frames_from_the_audit_and_a_shot_core_adds_the_seedvr2_job(tmp_path: Path) -> None:
    doc = _pair(tmp_path, mutate(base_config(), _core), target="all")
    up = rows(doc, kind="upscale.chunks", status="CHANGED")
    assert list(up) == ["upscale.chunks[S01_B]"] and up["upscale.chunks[S01_B]"]["requires_approval"]
    assert up["upscale.chunks[S01_B]"]["est_seconds"] == pytest.approx(72 * 9.1)
    assert doc["summary"]["gpu_jobs_need_approval"] == ["motion.h3[S01_B]", "upscale.chunks[S01_B]"]
    assert doc["summary"]["est_seconds_gpu"] == pytest.approx(72 * 2.5 + 72 * 9.1)
    assert list(rows(doc, kind="master.verify", status="CHANGED")) == ["master.verify[S01_B]"]
    master = rows(doc, kind="composite.master", status="CHANGED")
    assert {n.split("[")[1][:-1] for n in master} == {"shot-S01_B-1", "tr-T270"}
    assert master["composite.master[shot-S01_B-1]"]["est_seconds"] == pytest.approx(116 * 0.305)    # shot frames
    assert rows(doc, kind="film.downscale.2k")["film.downscale.2k"]["est_seconds"] == 54.28
    assert rows(doc, kind="mux.master")["mux.master"]["est_basis"] == "derived"


def test_master_vector_segments_use_the_cheaper_ending_frame_rate(tmp_path: Path) -> None:
    def new_logo(config: dict) -> None:
        config["logo"]["sha256"] = sha("logo-2")

    doc = _pair(tmp_path, mutate(base_config(), new_logo), target="master")
    assert not rows(doc, kind="motion.h3", status="CHANGED") and not rows(doc, kind="master.verify", status="CHANGED")
    ending = rows(doc, kind="composite.master")["composite.master[ending]"]
    assert ending["status"] == "CHANGED" and ending["est_seconds"] == pytest.approx(30 * 0.083)
    assert "composite.master[intro]" in rows(doc, kind="composite.master", status="CHANGED")
    assert "composite.master[shot-S01_A-1]" not in rows(doc, kind="composite.master", status="CHANGED")


# ---- pins -------------------------------------------------------------------------------------------------------------
def test_a_new_compositor_pin_restales_every_segment_and_says_why(tmp_path: Path) -> None:
    doc = _pair(tmp_path, base_config(), new_rec=record("comp-2"))
    assert doc["summary"]["segments_recomposite"] == doc["summary"]["segments_total"] == 12
    row = rows(doc, kind="composite.segment")["composite.segment[ending]"]
    assert row["layers"] == ["pins"] and row["leaves"][0].startswith("pin.compositor_sha256")
    assert not rows(doc, kind="motion.h3", status="CHANGED") and rows(doc, kind="audio.mix")["audio.mix"]["status"] == "UNCHANGED"


def test_a_pin_declared_on_one_side_only_is_reported_not_compared(tmp_path: Path) -> None:
    old = write_version(tmp_path, "old", base_config(), plan=mix_plan())
    new = write_version(tmp_path, "new", base_config(), plan=mix_plan(), record=record())
    doc = run(old, new)
    assert doc["summary"]["nodes_changed"] == 0
    assert any("declared on one side only" in w for w in doc["warnings"]) and any("no pins declared" in w for w in doc["warnings"])


# ---- cut points -------------------------------------------------------------------------------------------------------
def test_a_boundary_that_stops_being_an_effect_removes_a_segment_and_moves_its_neighbours(tmp_path: Path) -> None:
    def hard_cut(config: dict) -> None:
        t = next(r for r in config["motion"]["transitions"] if r["id"] == "T270")
        t.update(type="none", start=270, end_exclusive=270)

    doc = _pair(tmp_path, mutate(base_config(), hard_cut))
    removed = rows(doc, status="REMOVED")
    assert list(removed) == ["composite.segment[tr-T270]"] and removed["composite.segment[tr-T270]"]["est_seconds"] == 0.0
    assert doc["summary"]["removed"] == ["composite.segment[tr-T270]"]
    moved = rows(doc, kind="composite.segment", status="CHANGED")
    assert set(moved) == {"composite.segment[shot-S01_B-1]", "composite.segment[shot-S02_A-1]"}
    assert all("cut-points" in r["layers"] or "transition" in r["layers"] for r in moved.values())
    assert rows(doc, kind="mux")["mux"]["status"] == "CHANGED"


def test_a_segments_json_in_the_inputs_wins_and_a_broken_cover_is_refused(tmp_path: Path) -> None:
    rows_ = [{"id": "head", "kind": "intro", "start": 0, "end_exclusive": 200, "frames": 200, "shots_visible": []},
             {"id": "tail", "kind": "shot_span", "start": 200, "end_exclusive": 510, "frames": 310, "shots_visible": []}]
    d = write_version(tmp_path, "a", base_config(), plan=mix_plan(), record=record(),
                      descriptor={"segments": "segments.json"})
    (d / "segments.json").write_text(json.dumps({"schema": "jjv/segments/v1", "segments": rows_}), encoding="utf-8")
    doc = run(d, d)
    assert {r["node"] for r in doc["rows"] if r["kind"] == "composite.segment"} == {"composite.segment[head]", "composite.segment[tail]"}
    (d / "segments.json").write_text(json.dumps({"schema": "jjv/segments/v1", "segments": rows_[:1]}), encoding="utf-8")
    with pytest.raises(Refused, match="covers f0..f200"):
        run(d, d)


# ---- policy: the word-window switch is a case where the two recipes SEPARATE ----------------------------------------
def test_a_mix_that_ducks_under_words_is_restaled_by_a_word_timing_fix_the_default_one_is_not(tmp_path: Path) -> None:
    def fix(config: dict) -> None:
        shot_of(config, "S01_B")["words"][1]["startF"] += 6

    new = mutate(base_config(), fix)
    default = _pair(tmp_path, new)
    assert rows(default, kind="audio.mix")["audio.mix"]["status"] == "UNCHANGED"
    ducks = tmp_path / "policy-words.json"
    ducks.write_text(json.dumps({**POLICY, "audio_slice": {**POLICY["audio_slice"], "include_word_windows": True}}), encoding="utf-8")
    strict = run(tmp_path / "old", tmp_path / "new", policy_path=ducks)
    mix = rows(strict, kind="audio.mix")["audio.mix"]
    assert mix["status"] == "CHANGED"
    assert any(x.startswith("words[1][1][1][0] 190 -> 196") for x in mix["leaves"])
    assert rows(strict, kind="mux")["mux"]["action_code"] == "rejoin_and_remux"


# ---- the slice property test and the mutant it must kill ----------------------------------------------------------------
EXPECTED = {   # shot -> the segments whose pixels can show its captions (derived by hand from the cut list, not by the code)
    "S01_A": {"tr-T30", "shot-S01_A-1"},
    "S01_B": {"shot-S01_B-1", "tr-T270"},
    "S02_A": {"tr-T270", "shot-S02_A-1", "tr-T390"},
}


def _stale_after_word_edit(tmp_path: Path, shot: str, index: int) -> set[str]:
    def edit(config: dict) -> None:
        shot_of(config, shot)["words"][index]["startF"] += 1

    return _changed(_pair(tmp_path, mutate(base_config(), edit)))


@pytest.mark.parametrize("shot", sorted(EXPECTED))
def test_every_word_of_a_shot_restales_exactly_the_segments_that_can_show_it(tmp_path: Path, shot: str) -> None:
    for index in range(3):
        sub = tmp_path / f"w{index}"
        sub.mkdir()
        assert _stale_after_word_edit(sub, shot, index) == EXPECTED[shot], (shot, index)


def test_a_slice_that_forgets_the_words_is_caught_by_the_property_test(tmp_path: Path, monkeypatch) -> None:
    """The gate must go red at least once: a mutant video slice without ``shot:*`` leaves says "nothing changed"."""
    real = slices.video_parts

    def forgetful(config, seg, policy, bind=None):
        return {k: v for k, v in real(config, seg, policy, bind).items() if not k.startswith("shot:")}

    monkeypatch.setattr(graph.slices, "video_parts", forgetful)
    assert _stale_after_word_edit(tmp_path, "S01_B", 1) != EXPECTED["S01_B"]


# ---- read-only, offline, no job ---------------------------------------------------------------------------------------
def _fingerprint(root: Path) -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def test_planning_touches_no_input_file_opens_no_socket_and_starts_no_process(tmp_path: Path, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("the planner must not use the network or start a process")

    new = mutate(base_config(), _core)
    old_dir = write_version(tmp_path, "old", base_config(), plan=mix_plan(), record=record())
    new_dir = write_version(tmp_path, "new", new, plan=mix_plan(), record=record())
    before = _fingerprint(tmp_path)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    doc = run(old_dir, new_dir, target="all")
    assert doc["summary"]["gpu_jobs_need_approval"] and _fingerprint(tmp_path) == before
