"""``jjv plan explain`` on the synthetic film: the four required cases (word timing, music, shot core, unchanged) + GPU rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import test_plan_support as S
from test_plan_support import base_config, mix_plan, mutate, record, rows, run, shot_of, sha, write_version


def _changed(doc: dict, kind: str = "composite.segment") -> set[str]:
    return {n.split("[")[1][:-1] for n, r in rows(doc, kind=kind).items() if r["status"] != "UNCHANGED"}


def _pair(tmp_path: Path, new_config: dict, *, new_plan: dict | None = None, old_config: dict | None = None,
          old_desc: dict | None = None, new_desc: dict | None = None) -> dict:
    old = write_version(tmp_path, "old", old_config or base_config(), plan=mix_plan(), record=record(), descriptor=old_desc)
    new = write_version(tmp_path, "new", new_config, plan=new_plan or mix_plan(), record=record(), descriptor=new_desc)
    return run(old, new)


def _word_timing_fix(config: dict) -> None:
    """S01_B word 1 starts 6 f later, its icon follows, the word-timing document is a new one (v1 -> v2)."""
    shot_of(config, "S01_B")["words"][1]["startF"] += 6
    config["motion"]["icons"][0].update(frame=196, word_start_frame=196)
    config["word_timing"].update(sha256=sha("word-timing-2"), schema="wt/v2")


# ---- (d) nothing changed ----------------------------------------------------------------------------------------------
def test_unchanged_reuses_every_node_at_zero_seconds(tmp_path: Path) -> None:
    doc = _pair(tmp_path, base_config())
    assert doc["summary"]["nodes_changed"] == 0 and doc["summary"]["est_seconds_total"] == 0.0
    assert {r["status"] for r in doc["rows"]} == {"UNCHANGED"} and {r["action_code"] for r in doc["rows"]} == {"reuse"}
    assert doc["summary"]["gpu_jobs_need_approval"] == [] and doc["summary"]["unmeasured_nodes"] == []
    assert doc["headline"][0] == "picture: all segments reuse" and doc["schema"] == "jjv/plan-explain/v1"


# ---- (a) word timing only: captions / icons segments re-composite, NO GPU, audio unchanged -----------------------------
def test_word_timing_fix_recomposites_only_the_segments_that_draw_the_shot(tmp_path: Path) -> None:
    doc = _pair(tmp_path, mutate(base_config(), _word_timing_fix))
    assert _changed(doc) == {"shot-S01_B-1", "tr-T270"}
    for name, row in rows(doc, kind="composite.segment", status="CHANGED").items():
        assert row["action_code"] == "recomposite" and set(row["layers"]) <= {"captions", "icons"}, name
    assert rows(doc, kind="composite.segment")["composite.segment[shot-S01_B-1]"]["layers"] == ["icons", "captions"]
    assert not rows(doc, kind="motion.h3", status="CHANGED") and doc["summary"]["est_seconds_gpu"] == 0.0
    assert doc["summary"]["gpu_jobs_need_approval"] == []
    assert rows(doc, kind="audio.mix")["audio.mix"]["status"] == "UNCHANGED"
    mux = rows(doc, kind="mux")["mux"]
    assert mux["action_code"] == "rejoin" and "audio mix unchanged" in mux["action"]
    assert rows(doc, kind="timing.words")["timing.words"]["status"] == "CHANGED"
    assert rows(doc, kind="timing.words")["timing.words"]["action_code"] == "materialised"
    # price: (116 + 8) f x 0.04486 + 2 child renders x 4.769 + one mux 2.89; qa.av has no measured time
    assert doc["summary"]["est_seconds_total"] == pytest.approx(124 * 0.04486 + 2 * 4.769 + 2.89, abs=0.01)
    assert doc["summary"]["unmeasured_nodes"] == ["qa.av"]
    leaf = rows(doc, kind="composite.segment")["composite.segment[shot-S01_B-1]"]["leaves"]
    assert any(x.startswith("shot:S01_B.words[1].startF 190 -> 196") for x in leaf)
    assert any(x.startswith("icon:IC01.frame 190 -> 196") for x in leaf)


def test_a_new_word_timing_document_with_identical_words_moves_nothing(tmp_path: Path) -> None:
    """Content addressing (spec 2.3 step 3): the provenance sha changed, the words did not -> no segment, no cost."""
    def only_provenance(config: dict) -> None:
        config["word_timing"].update(sha256=sha("word-timing-2"), schema="wt/v2")

    doc = _pair(tmp_path, mutate(base_config(), only_provenance))
    tw = rows(doc, kind="timing.words")["timing.words"]
    assert tw["status"] == "CHANGED" and "identical" in tw["action"]
    assert doc["summary"]["segments_recomposite"] == 0 and doc["summary"]["est_seconds_total"] == 0.0
    assert rows(doc, kind="editorial.build")["editorial.build"]["status"] == "UNCHANGED"


# ---- (b) music change: remux only, picture reuse ----------------------------------------------------------------------
def _music_b(config: dict) -> None:
    config["mix"]["music"]["sha256"] = sha("music-B")
    config["mix"]["mix_wav"]["sha256"] = sha("mix-wav-B")


def test_music_change_remuxes_audio_and_reuses_the_whole_picture(tmp_path: Path) -> None:
    doc = _pair(tmp_path, mutate(base_config(), _music_b), new_plan=mix_plan("bed-B"))
    assert _changed(doc) == set() and doc["summary"]["segments_recomposite"] == 0
    mix = rows(doc, kind="audio.mix")["audio.mix"]
    assert mix["status"] == "CHANGED" and mix["action_code"] == "rebuild_mix" and mix["est_seconds"] is None
    assert any(x.startswith("plan.bed.sha256") for x in mix["leaves"]) and any(x.startswith("config.mix.music.sha256") for x in mix["leaves"])
    mux = rows(doc, kind="mux")["mux"]
    assert mux["action_code"] == "remux_audio_only" and mux["est_seconds"] == pytest.approx(2.89)
    assert doc["summary"]["picture_seconds_per_segment_bundle"] == 0.0 and doc["summary"]["est_seconds_gpu"] == 0.0
    assert set(doc["summary"]["unmeasured_nodes"]) == {"audio.mix", "qa.av"}      # `?`, never an invented number
    assert doc["headline"][0] == "picture: all segments reuse" and doc["headline"][2].startswith("audio: rebuild the mix")


# ---- (c) a changed shot core: the shot's segments + a GPU job that needs approval --------------------------------------
def _core_s01b(config: dict) -> None:
    shot_of(config, "S01_B")["segments"][0]["sha256"] = sha("clip-S01_B-v2")


def test_changed_shot_core_lists_a_gpu_job_that_needs_approval_and_never_runs_it(tmp_path: Path) -> None:
    doc = _pair(tmp_path, mutate(base_config(), _core_s01b))
    h3 = rows(doc, kind="motion.h3", status="CHANGED")
    assert list(h3) == ["motion.h3[S01_B]"]
    row = h3["motion.h3[S01_B]"]
    assert row["requires_approval"] is True and row["action_code"] == "gpu_job_needs_approval"
    assert row["est_seconds"] == pytest.approx(72 * 2.5) and row["est_basis"] == "derived"
    assert any(x.startswith("core.clips[0]") for x in row["leaves"])
    assert doc["summary"]["gpu_jobs_need_approval"] == ["motion.h3[S01_B]"] and doc["summary"]["est_seconds_gpu"] == 180.0
    assert _changed(doc) == {"shot-S01_B-1", "tr-T270"}
    seg = rows(doc, kind="composite.segment")["composite.segment[shot-S01_B-1]"]
    assert "after GPU job motion.h3[S01_B]" in seg["action"] and "picture" in seg["layers"]
    assert rows(doc, kind="audio.mix")["audio.mix"]["status"] == "UNCHANGED"
    assert doc["headline"][1].startswith("GPU: 1 job(s) need approval (motion.h3[S01_B])")


def test_a_gpu_input_that_changed_without_a_new_clip_still_needs_approval_and_holds_its_segments(tmp_path: Path) -> None:
    old = {"gpu_cores": {"S01_B": {"seed": 1, "prompt": "a calm cow"}}}
    new = {"gpu_cores": {"S01_B": {"seed": 2, "prompt": "a calm cow"}}}
    doc = _pair(tmp_path, base_config(), old_desc=old, new_desc=new)
    row = rows(doc, kind="motion.h3", status="CHANGED")["motion.h3[S01_B]"]
    assert row["requires_approval"] and row["leaves"] == ["input.seed 1 -> 2"]
    assert _changed(doc) == {"shot-S01_B-1", "tr-T270"}
    assert "upstream motion.h3[S01_B] changed" in rows(doc, kind="composite.segment")["composite.segment[shot-S01_B-1]"]["why"]


def test_a_receipt_that_names_the_new_core_sha_removes_the_gpu_job_but_not_the_recomposite(tmp_path: Path) -> None:
    receipt = tmp_path / "core-receipt.json"
    receipt.write_text(json.dumps({"outputs": [{"name": "clip", "sha256": sha("clip-S01_B-v2")}]}), encoding="utf-8")
    desc = {"gpu_cores": {"S01_B": {"core_receipt": str(receipt)}}}
    doc = _pair(tmp_path, mutate(base_config(), _core_s01b), new_desc=desc, old_desc={"gpu_cores": {"S01_B": {}}})
    row = rows(doc, kind="motion.h3")["motion.h3[S01_B]"]
    assert row["action_code"] == "core_present" and not row["requires_approval"] and row["est_seconds"] == 0.0
    assert doc["summary"]["gpu_jobs_need_approval"] == [] and _changed(doc) == {"shot-S01_B-1", "tr-T270"}
    receipt.write_text(json.dumps({"outputs": [{"sha256": sha("some-other-clip")}]}), encoding="utf-8")
    again = run(tmp_path / "old", tmp_path / "new")
    assert rows(again, kind="motion.h3")["motion.h3[S01_B]"]["requires_approval"] is True   # a receipt that does not vouch is no proof


def test_unknown_native_frames_make_the_gpu_estimate_unmeasured_not_zero(tmp_path: Path) -> None:
    def no_frames(config: dict) -> None:
        _core_s01b(config)
        del shot_of(config, "S01_B")["segments"][0]["native_frames"]

    doc = _pair(tmp_path, mutate(base_config(), no_frames), old_config=mutate(base_config(), lambda c: shot_of(c, "S01_B")["segments"][0].pop("native_frames")))
    row = rows(doc, kind="motion.h3", status="CHANGED")["motion.h3[S01_B]"]
    assert row["est_seconds"] is None and doc["summary"]["gpu_unmeasured"] == ["motion.h3[S01_B]"]
