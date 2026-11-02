"""``jjv timing words`` / ``jjv qa words`` handlers (parsed by the same registration functions root wires in)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from config_fixtures import make_world
from test_timing_run import HEARD, LINE, make_lines, read
from test_timing_support import FPS, RECIPE, fake_recognizer, sound, write_wav

from engine.config.loader import resolve_episode
from engine.core.errors import EngineError, Refused, Uncertain, exit_code_for
from engine.timing import cli
from engine.timing.run import TIMING_FILE, run_words


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser()
    stages = top.add_subparsers(dest="stage", required=True)
    cli.register_cli(stages)
    qa = stages.add_parser("qa").add_subparsers(dest="verb", required=True)
    cli.register_qa_words(qa)
    return top


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    made = make_world(tmp_path)
    monkeypatch.setattr(cli, "resolve_episode_or_uncertain", lambda ref: resolve_episode(
        str(made.episode_file), skill_root=made.skill_root, machine_path=made.machine_path))
    root = made.engine_dir.parent
    lines = make_lines(root)
    dialogue = tmp_path / "dialogue.json"
    dialogue.write_text(json.dumps({"fps": FPS, "dialogue": [
        {**l, "audio": {"path": l["audio"]["path"], "sha256": l["audio"]["sha256"]}} for l in lines]}), encoding="utf-8")
    base = run_words(episode_id="ep", fps=FPS, root=root, lines=lines, vocabulary=[], recipe=RECIPE,
                     recognizer=fake_recognizer(HEARD), supplied=None, out=tmp_path / "base")
    return made, root, dialogue, tmp_path / "base" / TIMING_FILE, base


def call(capsys, *argv: str) -> tuple[int, dict]:
    args = parser().parse_args(argv)
    code = cli.run_timing(args) if args.stage == "timing" else cli.run_qa_words(args)
    return code, json.loads(capsys.readouterr().out)


def test_timing_words_from_supplied_times_writes_files_and_exits_zero(world, capsys, tmp_path: Path) -> None:
    _made, _root, dialogue, base_timing, _base = world
    code, out = call(capsys, "timing", "words", "--episode", "x", "--dialogue", str(dialogue), "--recognised", str(base_timing),
                     "--out", str(tmp_path / "out"))
    assert code == 0 and out["ok"] and out["verdict"] == "PASS" and out["source"] == "supplied"
    assert out["recipe"] == "timing/words-onset-v003" and set(out["files"]) == {TIMING_FILE, "WORD-TIMING-QA.json", "timing-receipt.json"}
    assert read(tmp_path / "out" / TIMING_FILE)["entries"][0]["words"] == read(base_timing)["entries"][0]["words"]


def test_dry_run_validates_inputs_and_writes_nothing(world, capsys, tmp_path: Path) -> None:
    _made, _root, dialogue, base_timing, _base = world
    code, out = call(capsys, "timing", "words", "--episode", "x", "--dialogue", str(dialogue), "--recognised", str(base_timing),
                     "--dry-run")
    assert code == 0 and out["dry_run"] and out["lines"] == 1 and out["wavs_bound"] == 1
    assert not (tmp_path / "out").exists()


def test_without_recognition_setup_the_stage_is_uncertain_and_says_what_to_set(world, tmp_path: Path) -> None:
    _made, _root, dialogue, _timing, _base = world
    argv = ["timing", "words", "--episode", "x", "--dialogue", str(dialogue), "--out", str(tmp_path / "out")]
    with pytest.raises(Uncertain, match="machine.timing.python") as caught:
        cli.run_timing(parser().parse_args(argv))
    assert exit_code_for(caught.value) == 2
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"x")
    with pytest.raises(Uncertain, match="Python not found"):
        cli.run_timing(parser().parse_args(argv + ["--python", str(tmp_path / "none.exe"), "--model", str(model)]))
    with pytest.raises(Uncertain, match="model folder not found"):
        cli.run_timing(parser().parse_args(argv + ["--python", str(tmp_path / "none.exe"), "--model", str(tmp_path / "nomodel")]))
    assert not (tmp_path / "out").exists()


def test_out_is_required_and_dialogue_fps_must_match(world, tmp_path: Path) -> None:
    _made, _root, dialogue, base_timing, _base = world
    argv = ["timing", "words", "--episode", "x", "--dialogue", str(dialogue), "--recognised", str(base_timing)]
    with pytest.raises(Refused, match="--out is required"):
        cli.run_timing(parser().parse_args(argv))
    document = json.loads(dialogue.read_text(encoding="utf-8"))
    document["fps"] = 24
    dialogue.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(Refused, match="differs from the episode delivery fps"):
        cli.run_timing(parser().parse_args(argv + ["--dry-run"]))


def test_qa_words_passes_the_good_document_and_fails_an_early_word(world, capsys, tmp_path: Path) -> None:
    _made, _root, _dialogue, base_timing, _base = world
    code, receipt = call(capsys, "qa", "words", "--episode", "x", "--timing", str(base_timing), "--out", str(tmp_path / "q1.json"))
    assert code == 0 and receipt["verdict"] == "PASS" and receipt["q1"]["negative_control"]["detected"]
    assert read(tmp_path / "q1.json")["timing"]["sha256"] == receipt["timing"]["sha256"]
    tampered = read(base_timing)
    word = tampered["entries"][0]["words"][1]
    word["start_frame"] -= 5  # 'job' lit five frames before its sound
    bad = tmp_path / "early.json"
    bad.write_text(json.dumps(tampered), encoding="utf-8")
    code, receipt = call(capsys, "qa", "words", "--episode", "x", "--timing", str(bad))
    assert code == 1 and receipt["verdict"] == "FAIL" and receipt["q1"]["summary"]["early_words"] == ["S01:job"]


def test_qa_words_refuses_a_wav_that_changed_and_a_document_with_nothing_to_test(world, capsys, tmp_path: Path) -> None:
    _made, root, _dialogue, base_timing, _base = world
    quiet = tmp_path / "continuous.json"
    document = read(base_timing)
    document["entries"][0]["audio"]["sha256"] = "3" * 64
    quiet.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(Refused, match="receipt-WAV rule"):
        cli.run_qa_words(parser().parse_args(["qa", "words", "--episode", "x", "--timing", str(quiet)]))
    # the WAV is replaced by a recording with no pause at all, and the document is re-bound to its new sha
    document["entries"][0]["audio"]["sha256"] = write_wav(root / "audio" / "S01.wav", sound(("tone", 1.8)))
    quiet.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(Uncertain, match="nothing to test") as caught:
        cli.run_qa_words(parser().parse_args(["qa", "words", "--episode", "x", "--timing", str(quiet)]))
    assert isinstance(caught.value, EngineError) and exit_code_for(caught.value) == 2
