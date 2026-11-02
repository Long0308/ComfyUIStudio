"""Pinned negative clips survive historical-export cleanup; retained v015 provides positive controls.
Global frame numbers are kept through ``origin``. Whole-film runs are opt-in: ``JJV_QA_REVIEW_FULL=1``.
Only tests using retained production assets skip without that folder.
"""

from __future__ import annotations

import os
import json
import shutil
from pathlib import Path

import pytest

from test_qa_review_support import (EP, FFMPEG, RECIPE_SHA, ep_config, ep_video, needs_ep, needs_ffmpeg, recipe, review_clip)
from engine.qa import review
from engine.qa.gates import FAIL, PASS, q5_loudness
from engine.qa.review_model import build_model
import test_qa_review_support as support

pytestmark = [needs_ffmpeg]


def test_retired_fixture_does_not_read_the_production_export(tmp_path: Path, monkeypatch) -> None:
    def forbidden_export(*args):
        pytest.fail("retired controls must not read the production export")

    monkeypatch.setattr(support, "ep_video", forbidden_export)
    assert review_clip("012", tmp_path, 995, 60).is_file()
    assert ep_config("012")["fps"] == 30


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_retired_fixture_missing_or_corrupt_is_a_failure(tmp_path: Path, monkeypatch, damage: str) -> None:
    original = support.NEGATIVE_CONTROLS
    manifest = json.loads((original / "MANIFEST.json").read_text("utf-8"))
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    if damage == "corrupt":
        entry = next(r for r in manifest["clips"] if r["version"] == "012" and r["first_frame"] == 995)
        target = tmp_path / entry["file"]
        shutil.copyfile(original / entry["file"], target)
        with target.open("ab") as handle:
            handle.write(b"corrupted")
    monkeypatch.setattr(support, "NEGATIVE_CONTROLS", tmp_path)
    expected = "file is missing" if damage == "missing" else "hash mismatch"
    with pytest.raises(AssertionError, match=expected):
        review_clip("012", tmp_path, 995, 60)


def run(version: str, video: Path, gates: tuple[str, ...], tmp_path: Path, origin: int = 0, **kw) -> dict:
    return review.run_review(config=ep_config(version), video=video, ffmpeg=FFMPEG, recipe=recipe(), recipe_sha256=RECIPE_SHA,
                             config_sha256="test", root=EP.parent, gates=gates, origin=origin, sheets_dir=tmp_path / "sheets", **kw)


def clip(version: str, tmp_path: Path, first: int, count: int) -> Path:
    return review_clip(version, tmp_path, first, count)


@pytest.mark.parametrize("first,boundary,flash", [(1290, "T1310", 1309), (995, "T1010", 1009)])
def test_v012_white_flash_between_same_seat_shots_fails_q3(tmp_path: Path, first: int, boundary: str, flash: int) -> None:
    report = run("012", clip("012", tmp_path, first, 60), ("Q3",), tmp_path, origin=first)
    q3 = report["gates"]["Q3"]
    assert report["verdict"] == "FAIL" and report["exit_code"] == 1
    row = next(b for b in q3["boundaries"] if b["id"] == boundary)
    assert row["status"] == FAIL and row["type"] == "dip_white" and row["spike_frames"][0] == flash
    assert row["same_framing_ncc"] >= 0.35 and any(f.startswith(boundary) for f in q3["failures"])


@needs_ep
@pytest.mark.parametrize("first", [1290, 995])
def test_v014_hard_cut_with_push_passes_q3(tmp_path: Path, first: int) -> None:
    report = run("014", clip("014", tmp_path, first, 60), ("Q3",), tmp_path, origin=first)
    assert report["gates"]["Q3"]["status"] == PASS and report["exit_code"] == 0
    assert report["gates"]["Q3"]["boundaries"][0]["type"] == "cut_push"


@needs_ep
def test_v014_dip_at_a_real_layout_change_is_allowed(tmp_path: Path) -> None:
    report = run("014", clip("014", tmp_path, 1590, 50), ("Q3",), tmp_path, origin=1590)
    row = next(b for b in report["gates"]["Q3"]["boundaries"] if b["id"] == "T1610")
    assert row["type"] == "dip_white" and row["spike_frames"] and row["same_framing_ncc"] < 0.35
    assert report["gates"]["Q3"]["status"] == PASS


@needs_ep
def test_v013_identical_warm_and_cold_icons_fail_q2(tmp_path: Path) -> None:
    report = run("013", clip("013", tmp_path, 1078, 58), ("Q2",), tmp_path, origin=1078)
    q2 = report["gates"]["Q2"]
    pair = q2["pairs"][0]
    assert q2["status"] == FAIL and pair["pair"] == ["warm", "cold"] and pair["delta_e_file"] == 0.0
    assert pair["screen"][0]["delta_e_screen"] < 12
    assert any("identical icon image" in f for f in q2["failures"])


@needs_ep
def test_v015_distinct_warm_and_cold_icons_pass_q2(tmp_path: Path) -> None:
    report = run("015", clip("015", tmp_path, 1078, 58), ("Q2",), tmp_path, origin=1078)
    pair = report["gates"]["Q2"]["pairs"][0]
    assert report["gates"]["Q2"]["status"] == PASS and pair["delta_e_file"] > 30 and pair["screen"][0]["delta_e_screen"] > 20


@needs_ep
def test_v005_cross_dissolve_double_exposure_fails_q4_and_v014_push_passes(tmp_path: Path) -> None:
    bad = run("005", clip("005", tmp_path, 1295, 40), ("Q4",), tmp_path, origin=1295)
    window = bad["gates"]["Q4"]["windows"][0]
    assert bad["verdict"] == FAIL and bad["exit_code"] == 1
    assert bad["gates"]["Q4"]["status"] == FAIL and window["id"] == "T1310" and window["ghost_excess"] >= 0.15
    assert any("double exposure" in reason for reason in window["reasons"])
    assert Path(window["sheet"]["path"]).is_file()
    (tmp_path / "ok").mkdir()
    good = run("014", clip("014", tmp_path / "ok", 1295, 40), ("Q4",), tmp_path / "ok", origin=1295)
    assert good["gates"]["Q4"]["status"] == PASS and good["gates"]["Q4"]["windows"][0]["ghost_excess"] < 0.09


@needs_ep
def test_loudness_of_the_real_mixes_v014_passes_and_v013_fails() -> None:
    wav = EP / "review-hd-v014" / "milk-and-mom-REVIEW-mix-v014-48k.wav"
    ok = q5_loudness.run(build_model(ep_config("014"), recipe()), recipe(), wav, FFMPEG, 3444)
    assert ok["status"] == PASS, ok["failures"]
    bad = q5_loudness.run(build_model(ep_config("013"), recipe()), recipe(), ep_video("013"), FFMPEG, 3374)
    assert bad["status"] == FAIL and any("loudness jump" in f for f in bad["failures"])


@pytest.mark.skipif(os.environ.get("JJV_QA_REVIEW_FULL") != "1", reason="whole-film runs are opt-in (JJV_QA_REVIEW_FULL=1)")
@needs_ep
def test_whole_films(tmp_path: Path) -> None:
    v014 = run("014", ep_video("014"), ("Q2", "Q3", "Q4", "Q5"), tmp_path)
    assert v014["verdict"] == "PASS", {k: g["failures"] for k, g in v014["gates"].items()}
    v012 = run("012", ep_video("012"), ("Q3", "Q5"), tmp_path / "b")
    assert v012["gates"]["Q3"]["status"] == FAIL and v012["gates"]["Q5"]["status"] == FAIL
    v013 = run("013", ep_video("013"), ("Q2",), tmp_path / "c")
    assert v013["gates"]["Q2"]["status"] == FAIL
