"""Negative and positive controls from the real episode (skipped without the production folder): the preflight must
fail the configs the user rejected BEFORE a render and pass the accepted one.  Whole-gate runs use the real exports."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

from test_qa_review_support import (EP, FFMPEG, ep_config, ep_video, needs_ep, needs_ffmpeg,
                                    review_clip, review_config_path, sha_of)
from engine.qa import gate_cli, preflight_cli

pytestmark = [needs_ep, needs_ffmpeg]
EPISODE = EP.parent
CONTRACT = EPISODE / "DELIVERY-CONTRACT.json"


def cfg_path(version: str) -> Path:
    """The production config as shipped: its absolute source paths name the retired ``D:`` root, which the engine reads
    where the tree lives now (``machine.legacy_roots``); the file is never edited or copied."""
    return EP / f"review-hd-v{version}" / "config" / f"review-config-v{version}.json"


def preflight(capsys, *argv: str) -> tuple[int, dict]:
    code = preflight_cli.main(["--json", "--contract", str(CONTRACT), *argv])
    return code, json.loads(capsys.readouterr().out)


def failing(report: dict) -> set[str]:
    return {name for name, gate in report["gates"].items() if gate["status"] == "FAIL"}


def test_v015_passes_in_seconds(capsys) -> None:
    started = time.perf_counter()
    code, report = preflight(capsys, "--config", str(cfg_path("015")))
    assert code == 0 and report["verdict"] == "PASS" and report["render_allowed"], {k: g["failures"] for k, g in report["gates"].items()}
    assert time.perf_counter() - started < 30
    assert report["gates"]["Q1"]["negative_control"]["detected"] is True
    assert report["gates"]["TRANSITIONS"]["flash_boundaries_measured"] >= 1  # T1610 is measured, not skipped
    assert report["skipped"] == ["AUDIO"]


def test_v012_is_refused_before_render_on_the_white_flashes(capsys) -> None:
    code, report = preflight(capsys, "--config", str(cfg_path("012")))
    rows = {r["id"]: r for r in report["gates"]["TRANSITIONS"]["rows"]}
    assert code == 1 and report["render_allowed"] is False
    assert rows["T1010"]["status"] == "FAIL" and rows["T1310"]["status"] == "FAIL" and rows["T1610"]["status"] == "PASS"
    assert rows["T1010"]["source_ncc"] > rows["T1610"]["source_ncc"] + 0.3
    assert {"TRANSITIONS", "PACING", "ICONS"} <= failing(report)


def test_v013_identical_warm_cold_png_fails_icons(capsys) -> None:
    code, report = preflight(capsys, "--config", str(cfg_path("013")))
    icons = report["gates"]["ICONS"]
    assert code == 1 and icons["status"] == "FAIL" and icons["pairs"][0]["delta_e_file"] == 0.0
    assert any("identical icon image" in f for f in icons["failures"])


def test_v015_distinct_warm_cold_passes_the_file_level_pair(capsys) -> None:
    _, report = preflight(capsys, "--config", str(cfg_path("015")), "--checks", "ICONS")
    pair = report["gates"]["ICONS"]["pairs"][0]
    assert report["gates"]["ICONS"]["status"] == "PASS" and pair["delta_e_file"] > 30 and pair["hue_distance_deg"] > 100


def test_a_24_frame_card_config_fails(tmp_path: Path, capsys) -> None:
    config = copy.deepcopy(ep_config("015"))
    config["outro_cards"][3]["duration_frames"] = 24
    path = tmp_path / "review-config-card24.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    code, report = preflight(capsys, "--config", str(path), "--checks", "PACING")
    assert code == 1 and any("24" in f and "card_length_every_card" in f for f in report["gates"]["PACING"]["failures"])


def test_declared_90_with_a_24_frame_gap_between_starts_fails(tmp_path: Path, capsys) -> None:
    config = copy.deepcopy(ep_config("015"))
    config["outro_cards"][4]["start_frame"] = config["outro_cards"][3]["start_frame"] + 24
    path = tmp_path / "review-config-gap.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    code, report = preflight(capsys, "--config", str(path), "--checks", "PACING")
    assert code == 1 and any("derived 24" in f for f in report["gates"]["PACING"]["failures"])


def test_v003_era_timing_fails_q1(capsys) -> None:
    v003 = EP / "word-timing-v003" / "WORD-TIMING-v003.json"
    code, report = preflight(capsys, "--config", str(cfg_path("015")), "--timing", str(v003), "--checks", "Q1")
    q1 = report["gates"]["Q1"]
    assert code == 1 and q1["verdict"] == "FAIL" and q1["summary"]["early"] > 0 and q1["negative_control"]["detected"]
    assert q1["binding"]["match"] is False  # the config was not built from this timing either


def test_v004_timing_passes_q1_and_a_wrong_contract_fails(capsys, tmp_path: Path) -> None:
    code, report = preflight(capsys, "--config", str(cfg_path("015")), "--checks", "Q1,PACING")
    assert code == 0, report["gates"]
    code, report = preflight(capsys, "--config", str(cfg_path("015")), "--checks", "PACING", "--expect-frames", "3374")
    assert code == 1 and any("disagrees with the contract" in f for f in report["gates"]["PACING"]["failures"])
    code = preflight_cli.main(["--json", "--config", str(cfg_path("015")), "--checks", "PACING", "--expect-frames", "3374"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1 and any("contract_frames" in f for f in report["gates"]["PACING"]["failures"])


def test_missing_timing_is_uncertain_exit_2(tmp_path: Path, capsys) -> None:
    config = copy.deepcopy(ep_config("015"))
    config.pop("word_timing")
    path = tmp_path / "review-config-notiming.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    code, report = preflight(capsys, "--config", str(path), "--checks", "Q1")
    assert code == 2 and report["gates"]["Q1"]["status"] == "UNCERTAIN"


def test_gate_pre_render_and_post_render(capsys, tmp_path: Path) -> None:
    code = gate_cli.main(["--json", "--contract", str(CONTRACT), "--config", str(cfg_path("015"))])
    pre = json.loads(capsys.readouterr().out)
    assert code == 0 and pre["mode"] == "pre-render" and pre["review"] is None and pre["stages"]["review"] == "NOT_RUN"
    code = gate_cli.main(["--json", "--contract", str(CONTRACT), "--config", str(cfg_path("015")), "--video", str(ep_video("015")),
                          "--gates", "Q3,Q5", "--sheets-dir", str(tmp_path)])
    post = json.loads(capsys.readouterr().out)
    assert code == 0 and post["stages"] == {"preflight": "PASS", "review": "PASS", "words": "PASS"}, post["stages"]


@pytest.mark.parametrize("first,boundary", [(995, "T1010"), (1290, "T1310")])
def test_gate_rejects_v012_fixture_after_render(capsys, tmp_path: Path, first: int, boundary: str) -> None:
    video = review_clip("012", tmp_path, first, 60)
    config = review_config_path("012")
    code = gate_cli.main(["--json", "--contract", str(CONTRACT), "--config", str(config), "--root", str(EPISODE), "--video", str(video),
                          "--frame-origin", str(first), "--gates", "Q3", "--sheets-dir", str(tmp_path)])
    bad = json.loads(capsys.readouterr().out)
    assert code == 1 and bad["stages"]["preflight"] == "FAIL" and bad["stages"]["review"] == "FAIL" and bad["render_allowed"] is False
    q3 = bad["review"]["gates"]["Q3"]
    row = next(r for r in q3["boundaries"] if r["id"] == boundary)
    assert row["status"] == "FAIL" and row["spike_frames"]
    assert bad["review"]["video"]["origin_frame"] == first
    assert bad["review"]["config_sha256"] == sha_of(config)


def test_gate_pre_render_refuses_on_icons_alone(capsys) -> None:
    """One failing pixel-free check (v013 warm == cold PNG) refuses the render: exit 1, render_allowed false."""
    code = gate_cli.main(["--json", "--contract", str(CONTRACT), "--config", str(cfg_path("013")), "--checks", "ICONS"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1 and report["render_allowed"] is False and report["mode"] == "pre-render"


def test_episode_flag_reads_floors_and_the_contract_total_from_the_domain_and_episode(capsys) -> None:
    code = preflight_cli.main(["--json", "--episode", str(EPISODE), "--config", str(cfg_path("015")), "--checks", "PACING"])
    good = json.loads(capsys.readouterr().out)["gates"]["PACING"]
    assert code == 0 and good["contract_frames"] == 3444 and good["contract_source"].startswith("episode contract")
    code = preflight_cli.main(["--json", "--episode", str(EPISODE), "--config", str(cfg_path("013")), "--checks", "PACING"])
    bad = json.loads(capsys.readouterr().out)["gates"]["PACING"]
    assert code == 1 and any("3374" in f and "3444" in f for f in bad["failures"])
