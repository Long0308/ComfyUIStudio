"""``jjv qa review`` end to end on a synthetic film: report, exit codes 0/1/2, tighten-only config, module hygiene."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from test_qa_review_support import (H, W, gray_of, make_config, needs_ffmpeg, np, recipe, scene, write_video, write_wav)
from engine.qa import review_cli
from engine.qa.review_cli import main, register_review

SKILL = Path(__file__).resolve().parents[1]
LEVEL = 0.2


def world(tmp_path: Path, *, cards: int = 90) -> tuple[Path, Path, Path]:
    """570-frame film (one still picture), its config and a mix WAV at about -17 LUFS."""
    video = write_video(tmp_path / "film.mp4", np.stack([scene(1)] * 570))
    config = make_config([{"boundary": 5, "type": "none", "frames": 0}], main_frames=540, end_hold_frames=30, total_frames=540,
                         outro_cards=[{"term": "Alpha", "start_frame": 330, "duration_frames": cards},
                                      {"term": "Beta", "start_frame": 330 + cards, "duration_frames": cards}],
                         ending={"logo_disc": {"still_hold": "f100-f165 (66 f)"}, "end_plate": {"start": 330 + 2 * cards}})
    config["dialogue"] = [{"id": "S01_A", "start_frame": 90, "end_frame_exclusive": 300, "words": [], "segments": []}]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    wav = write_wav(tmp_path / "mix.wav", [(3, 0.03), (7, LEVEL), (1, LEVEL), (6, LEVEL), (2, LEVEL)])
    return video, path, wav


def invoke(capsys, *argv: str) -> tuple[int, dict]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, json.loads(captured.out)


@needs_ffmpeg
def test_all_green_film_exits_0_and_writes_the_report(tmp_path: Path, capsys) -> None:
    video, config, wav = world(tmp_path)
    out = tmp_path / "report.json"
    code, report = invoke(capsys, "--config", str(config), "--video", str(video), "--mix", str(wav), "--gates", "Q3,Q4,Q5",
                          "--sheets-dir", str(tmp_path / "sheets"), "--out", str(out), "--json")
    assert code == 0 and report["verdict"] == "PASS" and report["exit_code"] == 0 and report["ok"]
    assert json.loads(out.read_text(encoding="utf-8")) == report
    assert set(report["gates"]) == {"Q3", "Q4", "Q5"} and report["timing_s"]["total"] >= 0
    assert report["video"]["frames"] == 570 and report["recipe"]["id"] == "review-gates-v001" and report["mix"]["name"] == "mix.wav"
    assert report["gates"]["Q5"]["pacing"]["contract_frames"] == 570


@needs_ffmpeg
def test_a_gate_failure_exits_1_with_the_reason(tmp_path: Path, capsys) -> None:
    video, config, wav = world(tmp_path, cards=60)  # cards of 60 f: the pacing gate must catch it
    code, report = invoke(capsys, "--config", str(config), "--video", str(video), "--mix", str(wav), "--gates", "Q5", "--json")
    assert code == 1 and report["verdict"] == "FAIL" and any("card_length" in f for f in report["gates"]["Q5"]["failures"])


@needs_ffmpeg
def test_a_gate_that_cannot_decide_makes_the_run_uncertain_exit_2(tmp_path: Path, capsys) -> None:
    video, config, wav = world(tmp_path)
    code, report = invoke(capsys, "--config", str(config), "--video", str(video), "--gates", "Q2", "--json")
    assert code == 2 and report["verdict"] == "UNCERTAIN" and report["gates"]["Q2"]["status"] == "UNCERTAIN"


@needs_ffmpeg
def test_a_fail_beats_an_uncertain_gate(tmp_path: Path, capsys) -> None:
    video, config, wav = world(tmp_path, cards=60)
    code, report = invoke(capsys, "--config", str(config), "--video", str(video), "--mix", str(wav), "--gates", "Q2,Q5", "--json")
    assert code == 1 and report["gates"]["Q2"]["status"] == "UNCERTAIN" and report["gates"]["Q5"]["status"] == "FAIL"


@needs_ffmpeg
def test_a_missing_input_is_exit_2_and_a_rule_violation_exit_1(tmp_path: Path, capsys) -> None:
    video, config, wav = world(tmp_path)
    code, out = invoke(capsys, "--config", str(config), "--video", str(tmp_path / "nope.mp4"), "--json")
    assert code == 2 and not out["ok"] and "not found" in out["error"]
    code, out = invoke(capsys, "--config", str(tmp_path / "nope.json"), "--video", str(video), "--json")
    assert code == 2 and not out["ok"]
    code, out = invoke(capsys, "--config", str(config), "--video", str(video), "--gates", "Q9", "--json")
    assert code == 1 and "unknown gate" in out["error"]


@needs_ffmpeg
def test_a_config_cannot_loosen_a_threshold(tmp_path: Path, capsys) -> None:
    video, config, wav = world(tmp_path)
    document = json.loads(config.read_text(encoding="utf-8"))
    document["qa"] = {"review": {"q5_pacing": {"card_min_frames": 1}}}
    config.write_text(json.dumps(document), encoding="utf-8")
    code, out = invoke(capsys, "--config", str(config), "--video", str(video), "--gates", "Q5", "--json")
    assert code == 1 and "looser than the recipe value" in out["error"]
    document["qa"] = {"review": {"q5_pacing": {"card_min_frames": 120}}}  # tightening is allowed: 90 f cards now fail
    config.write_text(json.dumps(document), encoding="utf-8")
    code, report = invoke(capsys, "--config", str(config), "--video", str(video), "--mix", str(wav), "--gates", "Q5", "--json")
    assert code == 1 and report["recipe"]["overrides"] == {"q5_pacing.card_min_frames": "config"}


def test_the_verb_registers_on_a_qa_parser() -> None:
    parser = argparse.ArgumentParser(prog="jjv")
    verbs = parser.add_subparsers(dest="stage").add_parser("qa").add_subparsers(dest="verb")
    register_review(verbs)
    args = parser.parse_args(["qa", "review", "--config", "c.json", "--video", "v.mp4", "--frame-origin", "40"])
    assert (args.stage, args.verb, args.frame_origin, args.gates) == ("qa", "review", 40, "Q2,Q3,Q4,Q5")
    assert callable(review_cli.run_qa_review)


def test_modules_are_small_neutral_offline_and_gpu_free() -> None:
    files = sorted((SKILL / "engine" / "qa").glob("review*.py")) + sorted((SKILL / "engine" / "qa" / "gates").glob("*.py"))
    assert len(files) >= 10
    for source in files + sorted((SKILL / "tests").glob("test_qa_review_*.py")):
        assert len(source.read_text(encoding="utf-8").splitlines()) <= 400, source
    for source in files:
        text = source.read_text(encoding="utf-8").lower()
        for token in ("jenniejoy", "newtecons", "04-milk-and-mom", "ep04", "milk", "comfy", "urllib", "requests", "socket", "torch", ".post("):
            assert token not in text, (source.name, token)
    assert json.loads((SKILL / "recipes" / "qa" / "review-gates-v001.json").read_text(encoding="utf-8"))["id"] == "review-gates-v001"
    assert recipe()["q3_flash"]["spike_excess_min"] > 0 and (W, H) == (320, 180) and gray_of(scene(1)[None]).shape[0] == 1
