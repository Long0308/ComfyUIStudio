"""``jjv plan explain`` on the real ep04 inputs (read-only): the four cases the task names.

(a) review-hd v014 -> v015: word timing only.   (b) the v016 music change.   (c) a changed shot core.   (d) unchanged.
Skipped when the production folders are not on this machine; they are never written (stat fingerprint before/after).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import test_plan_support as S
from engine.plan import cli
from test_plan_support import rows, run

EP = S.EP04_EDITORIAL
V14, V15, MIX = EP / "review-hd-v014", EP / "review-hd-v015", EP / "audio-mix-v016"
PLAN14 = V14 / "mix-plan-v014.json"
CONFIG15 = V15 / "config" / "review-config-v015.json"
RECORD15 = V15 / "render-record-picture-v015.json"
pytestmark = pytest.mark.skipif(not (V14.is_dir() and V15.is_dir() and MIX.is_dir()), reason="ep04 production folders not present")
SKILL = Path(__file__).resolve().parents[1]


def _stat(*roots: Path) -> dict[str, tuple[int, int]]:
    out = {}
    for root in roots:
        for base, _dirs, files in os.walk(root):
            for name in files:
                st = os.stat(Path(base) / name)
                out[str(Path(base) / name)] = (st.st_size, st.st_mtime_ns)
    return out


@pytest.fixture(autouse=True)
def production_stays_untouched():
    before = _stat(V14, V15, MIX)
    yield
    assert _stat(V14, V15, MIX) == before


def _descriptor(tmp_path: Path, name: str, **pointers) -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "plan-inputs.json").write_text(json.dumps({"schema": "jjv/plan-inputs/v1", "render_record": str(RECORD15), **pointers}),
                                        encoding="utf-8")
    return d


def _changed(doc: dict, kind: str = "composite.segment") -> dict:
    return {n.split("[")[1][:-1]: r for n, r in rows(doc, kind=kind).items() if r["status"] != "UNCHANGED"}


# ---- (a) v014 -> v015: word timing only -------------------------------------------------------------------------------
def test_a_v014_to_v015_recomposites_captions_and_icons_with_no_gpu_and_unchanged_audio() -> None:
    doc = run(V14, V15)
    changed = _changed(doc)
    # ground truth: the shots whose word startF the builder's own diff file lists (word-changes-v014-v015.json)
    words = json.loads((V15 / "word-changes-v014-v015.json").read_text("utf-8-sig"))["words_changed"]
    shots = {w["shot"] for w in words}
    config = json.loads(CONFIG15.read_text("utf-8-sig"))
    windows = [t for t in config["motion"]["transitions"] if t["end_exclusive"] > t["start"]]
    spans = [(d["start_frame"], d["end_frame_exclusive"]) for d in config["dialogue"] if d["id"] in shots]
    # a window shows a changed shot when it names it, or when it lies on its frames (T2160: the iris over S06_B, "from" is clip S06_B3)
    expected_transitions = {f"tr-{t['id']}" for t in windows if {t["from"], t["to"]} & shots or
                            any(t["start"] < b and a < t["end_exclusive"] for a, b in spans)}
    assert {k for k in changed if k.startswith("shot-")} == {f"shot-{s}-1" for s in shots}
    assert {k for k in changed if k.startswith("tr-")} == expected_transitions
    for name, row in changed.items():
        assert set(row["layers"]) <= {"captions", "icons"} and row["segment_kind"] in ("shot_span", "transition"), name
    for untouched in ("intro", "logo-hold", "card-01", "card-12", "ending", "shot-S05_B-1"):
        assert untouched not in changed
    assert "icons" in changed["shot-S01_B-1"]["layers"] and "captions" in changed["shot-S01_A-1"]["layers"]
    s = doc["summary"]
    assert s["gpu_jobs_need_approval"] == [] and s["est_seconds_gpu"] == 0.0
    assert not rows(doc, kind="motion.h3", status="CHANGED")
    assert rows(doc, kind="audio.mix")["audio.mix"]["status"] == "UNCHANGED"
    mux = rows(doc, kind="mux")["mux"]
    assert mux["action_code"] == "rejoin" and "audio mix unchanged" in mux["action"]
    leaves = rows(doc, kind="timing.words")["timing.words"]["leaves"]
    assert "word_timing.sha256 871c7bd09445 -> 7598ddc0b3ca" in leaves
    assert 0 < s["segments_recomposite"] < s["segments_total"] and s["frames_recomposite"] < s["frames_total"]
    assert s["picture_seconds_shared_bundle"] < s["picture_seconds_full_rerender"]
    assert s["unmeasured_nodes"] == ["qa.av"]


def test_a_the_master_target_reprices_the_same_segments_at_4k_and_still_asks_for_no_gpu() -> None:
    doc = run(V14, V15, target="master")
    assert {k for k in _changed(doc, "composite.master")} == set(_changed(run(V14, V15)))
    assert not rows(doc, kind="master.verify", status="CHANGED") and doc["summary"]["gpu_jobs_need_approval"] == []
    assert rows(doc, kind="film.downscale.2k")["film.downscale.2k"]["est_seconds"] == 54.28


# ---- (b) v016: a music change is a remux, the picture is reused ---------------------------------------------------------
def test_b_v016_music_change_remuxes_audio_only_and_reuses_every_segment(tmp_path: Path) -> None:
    new = _descriptor(tmp_path, "v016", config=str(CONFIG15), mix_plan=str(MIX / "mix-plan-v016-final-giongC-nhacV2-4.json"))
    doc = run(V15, new)
    assert _changed(doc) == {} and doc["summary"]["segments_recomposite"] == 0
    assert doc["summary"]["picture_seconds_per_segment_bundle"] == 0.0 and doc["summary"]["gpu_jobs_need_approval"] == []
    mix = rows(doc, kind="audio.mix")["audio.mix"]
    assert mix["status"] == "CHANGED" and mix["action_code"] == "rebuild_mix" and mix["est_seconds"] is None
    assert "output:mix_wav.sha256 06bb24de6ebf -> af8b68149b17" in mix["leaves"]
    mux = rows(doc, kind="mux")["mux"]
    assert mux["action_code"] == "remux_audio_only" and mux["est_seconds"] == pytest.approx(2.89)
    assert doc["headline"][0] == "picture: all segments reuse"


def test_b_two_v016_mixes_that_differ_only_in_the_music_bed(tmp_path: Path) -> None:
    old = _descriptor(tmp_path, "nhac3", config=str(CONFIG15), mix_plan=str(MIX / "mix-plan-v016-final-giongC-nhac3.json"))
    new = _descriptor(tmp_path, "nhacV2", config=str(CONFIG15), mix_plan=str(MIX / "mix-plan-v016-final-giongC-nhacV2-4.json"))
    doc = run(old, new)
    mix = rows(doc, kind="audio.mix")["audio.mix"]
    assert mix["status"] == "CHANGED" and any(x.startswith("plan.bed.sha256") for x in mix["leaves"])
    assert _changed(doc) == {} and rows(doc, kind="mux")["mux"]["action_code"] == "remux_audio_only"


# ---- (c) a changed shot core ------------------------------------------------------------------------------------------
def test_c_a_changed_shot_core_names_its_segments_and_a_gpu_job_that_needs_approval(tmp_path: Path) -> None:
    config = json.loads(CONFIG15.read_text("utf-8-sig"))
    shot = next(d for d in config["dialogue"] if d["id"] == "S04_B")
    shot["segments"][0]["sha256"] = S.sha("a re-rendered S04_B core")
    new = _descriptor(tmp_path, "core", config=str(tmp_path / "config-core.json"))
    (tmp_path / "config-core.json").write_text(json.dumps(config), encoding="utf-8")
    new_old = _descriptor(tmp_path, "base", config=str(CONFIG15))
    doc = run(new_old, new, target="all")
    changed = _changed(doc)
    assert set(changed) == {"shot-S04_B-1", "tr-T1310"}
    assert all("picture" in r["layers"] for r in changed.values())
    h3 = rows(doc, kind="motion.h3", status="CHANGED")["motion.h3[S04_B]"]
    assert h3["requires_approval"] and h3["est_seconds"] == pytest.approx(128 * 2.5)
    up = rows(doc, kind="upscale.chunks", status="CHANGED")["upscale.chunks[S04_B]"]
    assert up["requires_approval"] and up["est_seconds"] == pytest.approx(128 * 9.1)
    assert doc["summary"]["gpu_jobs_need_approval"] == ["motion.h3[S04_B]", "upscale.chunks[S04_B]"]
    assert "after GPU job motion.h3[S04_B]" in changed["shot-S04_B-1"]["action"]
    assert rows(doc, kind="audio.mix")["audio.mix"]["status"] == "UNCHANGED"
    assert [n for n in rows(doc, kind="motion.h3", status="CHANGED")] == ["motion.h3[S04_B]"]    # no other shot is re-rendered


# ---- (d) unchanged ----------------------------------------------------------------------------------------------------
def test_d_unchanged_inputs_reuse_everything_even_from_a_different_directory(tmp_path: Path) -> None:
    # The v015 RECEIPT names its v014 mix plan under the retired D:\ root (the receipt is hash-bound, never edited); the
    # engine reads it where it lives now (machine.legacy_roots), so the old side has its plan and nothing reads "+plan".
    for old, new in ((V15, V15), (V15, _descriptor(tmp_path, "copy", config=str(CONFIG15), mix_plan=str(PLAN14)))):
        doc = run(old, new, target="all")
        assert Path(doc["old"]["sources"]["mix_plan"]) == PLAN14 and doc["summary"]["uncertain_nodes"] == []
        assert {r["status"] for r in doc["rows"]} == {"UNCHANGED"}
        assert doc["summary"]["est_seconds_total"] == 0.0 and doc["summary"]["nodes_changed"] == 0
        assert doc["headline"][0] == "picture: all segments reuse"


def test_the_cli_runs_the_real_pair_end_to_end_under_python_dash_i() -> None:
    done = subprocess.run([sys.executable, "-I", str(SKILL / "engine" / "plan" / "__main__.py"), "explain", "--old", str(V14),
                           "--new", str(V15)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    doc = json.loads(done.stdout)
    assert doc["summary"]["est_seconds_gpu"] == 0.0 and doc["headline"][2] == "audio: unchanged (reuse)"
    assert done.stderr.startswith("NODE") and "re-composite segment [captions]" in done.stderr
    assert cli.main(["explain", "--old", str(V15), "--new", str(V15), "--no-table"]) == 0
