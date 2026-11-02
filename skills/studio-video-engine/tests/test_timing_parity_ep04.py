"""Parity with the first episode's hand-run word timing: v003 recognised times + receipt WAVs -> v004, exactly.

The fixture ``engine/timing/fixtures/parity-words-v003-to-v004.json`` copies only the small JSON (v003 word
times, the v004 result, the v004 Q1 rows); the WAVs are read in place (read-only) and hash-bound.  The tests
skip when the episode's WAVs are not on this machine.  ``test_parity_goes_red_...`` proves the comparison can fail.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
from pathlib import Path

import pytest
from test_timing_support import FPS, RECIPE

from engine.config.loader import REPO_ROOT, SKILL_ROOT
from engine.core.io import sha256_file
from engine.timing.dialogue import parse_lines
from engine.timing.run import TIMING_FILE, run_words

FIXTURE = SKILL_ROOT / "engine" / "timing" / "fixtures" / "parity-words-v003-to-v004.json"
EP = REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom"
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
WAVS_HERE = all((EP / e["audio"]["path"]).is_file() for e in DATA["entries"])
needs_wavs = pytest.mark.skipif(not WAVS_HERE, reason="the first episode's receipt WAVs are not on this machine")
FIELDS = ("start_s", "start_frame", "end_s", "end_frame_exclusive")


def produce(tmp_path: Path, recipe=RECIPE, **over) -> tuple[dict, dict]:
    lines = parse_lines({"dialogue": [{k: e[k] for k in ("id", "start_frame", "end_frame_exclusive", "speech_text", "audio")}
                                      for e in DATA["entries"]]})
    summary = run_words(episode_id="parity", fps=FPS, root=EP, lines=lines, vocabulary=[], recipe=recipe, recognizer=None,
                        supplied={"schema": "fixture", "entries": copy.deepcopy(DATA["entries"])}, out=tmp_path / "out", **over)
    return summary, json.loads((tmp_path / "out" / TIMING_FILE).read_text(encoding="utf-8"))


def differences(document: dict) -> list[str]:
    produced = {(e["id"], w["index"]): w for e in document["entries"] for w in e["words"]}
    found = []
    for want in DATA["expected_v004"]:
        got = produced[(want["entry"], want["index"])]
        found += [f"{want['entry']}#{want['index']} {k}: engine {got[k]} v004 {want[k]}" for k in FIELDS if got[k] != want[k]]
    return found


def test_fixture_is_the_recorded_copy_of_the_hand_run_files() -> None:
    editorial = EP / "editorial"
    paths = {"v003_sha256": editorial / "word-timing-v003" / "WORD-TIMING-v003.json",
             "v004_sha256": editorial / "word-timing-v004" / "WORD-TIMING-v004.json"}
    if not all(p.is_file() for p in paths.values()):
        pytest.skip("hand-run word timing files are not on this machine")
    for key, path in paths.items():
        assert sha256_file(path) == DATA["source_files"][key], f"{path.name} changed: regenerate the fixture"
    assert len(DATA["expected_v004"]) == 108 and len(DATA["expected_moved"]) == 25


@needs_wavs
def test_engine_reproduces_v004_exactly_25_moved_words_zero_differences(tmp_path: Path) -> None:
    summary, document = produce(tmp_path)
    assert differences(document) == []  # 108 words x 4 fields
    assert summary["words"] == 108 and summary["words_moved"] == 25
    assert summary["moved"] == DATA["expected_moved"]  # same entries, words, old and new frames, same order


@needs_wavs
def test_line_first_rule_is_idempotent_on_the_v003_input(tmp_path: Path) -> None:
    _, with_rule = produce(tmp_path, first_word=True)
    _, without = produce(tmp_path / "x", first_word=False)
    assert [w for e in with_rule["entries"] for w in e["words"]] == [w for e in without["entries"] for w in e["words"]]


@needs_wavs
def test_the_stop_closure_in_liquid_does_not_move_on_the_real_audio(tmp_path: Path) -> None:
    _, document = produce(tmp_path)
    audit = json.loads((tmp_path / "out" / "WORD-TIMING-QA.json").read_text(encoding="utf-8"))["words"]
    liquid = next(r for r in audit if r["entry"] == "S01_B" and r["word"] == "liquid")
    assert not liquid["moved"] and liquid["new_start_frame"] == liquid["old_start_frame"] == 335


@needs_wavs
def test_q1_on_the_v004_reference_is_pinned_row_for_row(tmp_path: Path) -> None:
    """The reference itself does NOT pass Q1 at the recipe limits: 1 early ('liquid' = the closure above, a detector
    false positive) and 5 late (3-7 f).  The numbers are pinned so a change of the detector or the rules is seen."""
    summary, _ = produce(tmp_path)
    expected = DATA["expected_q1"]
    qa = json.loads((tmp_path / "out" / "WORD-TIMING-QA.json").read_text(encoding="utf-8"))["q1"]
    assert [{k: r[k] for k in ("entry", "index", "lit_frame", "onset_frame", "delta_f")} for r in qa["rows"]] == expected["rows"]
    assert qa["summary"]["early_words"] == expected["early_words"] == ["S01_B:liquid"]
    assert qa["summary"]["late_words"] == expected["late_words"] and len(expected["late_words"]) == 5
    assert qa["summary"]["words_tested"] == expected["words_tested"] == 44
    assert summary["verdict"] == "FAIL" and qa["negative_control"]["detected"] is True


@needs_wavs
def test_parity_goes_red_when_a_rule_threshold_is_tampered(tmp_path: Path) -> None:
    """With the far pause window cut to 0.05 s the closure inside 'liquid' (about 0.08 s) is taken for a gap and moves."""
    data = copy.deepcopy(RECIPE.data)
    data["all_words"]["pause"]["far_min_s"] = 0.05
    _, document = produce(tmp_path, recipe=dataclasses.replace(RECIPE, data=data))
    found = differences(document)
    assert found and any(line.startswith("S01_B#6 start_frame") for line in found), found


LIVE = pytest.mark.skipif(not (WAVS_HERE and os.environ.get("JJV_TIMING_PYTHON") and os.environ.get("JJV_TIMING_MODEL")),
                          reason="set JJV_TIMING_PYTHON (a Python with faster_whisper) and JJV_TIMING_MODEL to run real recognition")


@LIVE
def test_live_recognition_reproduces_every_v004_word_start(tmp_path: Path) -> None:
    """Opt-in, CPU only: faster-whisper from scratch on the 12 receipt WAVs gives the same 108 start frames and the same
    25 new frames as the hand-run chain (last-word ends may differ by one frame: the hand-run chain calibrated them to a
    different RMS measure; S06_B's segment boundary is not modelled)."""
    from engine.timing.recognise import find_model_dir, subprocess_recognizer
    recognizer = subprocess_recognizer(os.environ["JJV_TIMING_PYTHON"], find_model_dir(os.environ["JJV_TIMING_MODEL"]),
                                       RECIPE.block("recognition"), RECIPE.data["language"])
    lines = parse_lines({"dialogue": [{k: e[k] for k in ("id", "start_frame", "end_frame_exclusive", "speech_text", "audio")}
                                      for e in DATA["entries"]]})
    summary = run_words(episode_id="live", fps=FPS, root=EP, lines=lines, vocabulary=[], recipe=RECIPE, recognizer=recognizer,
                        supplied=None, out=tmp_path / "out")
    document = json.loads((tmp_path / "out" / TIMING_FILE).read_text(encoding="utf-8"))
    assert [d for d in differences(document) if " start_frame:" in d] == []
    assert [m["new_start_frame"] for m in summary["moved"]] == [m["new_start_frame"] for m in DATA["expected_moved"]]
