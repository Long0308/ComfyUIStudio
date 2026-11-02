"""``run_words`` end to end on a synthetic line: recognition, both rules, Q1, write-once files, refusals."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from test_timing_support import FPS, RECIPE, fake_recognizer, sound, write_wav

from engine.core.errors import Refused, Uncertain
from engine.core.io import sha256_file
from engine.editorial.captions import caption_words
from engine.timing.dialogue import parse_lines
from engine.timing.run import QA_FILE, RECEIPT_FILE, TIMING_FILE, run_words

LINE = sound(("sil", 0.4), ("tone", 0.5), ("sil", 0.3), ("tone", 0.6))  # Good 0.4-0.9 s, job 1.2-1.8 s
HEARD = {"Good job": [("Good", 0.0, 0.9), ("job", 0.9, 1.8)]}  # Whisper fills the silences: both starts lie in silence


def make_lines(root: Path, *, sha: str | None = None) -> list[dict]:
    digest = write_wav(root / "audio" / "S01.wav", LINE)
    return parse_lines({"dialogue": [{"id": "S01", "start_frame": 100, "end_frame_exclusive": 160, "speech_text": "Good job",
                                      "audio": {"path": "audio/S01.wav", "sha256": sha or digest}}]})


def run(root: Path, out: Path | None, **over):
    args = dict(episode_id="ep", fps=FPS, root=root, lines=make_lines(root), vocabulary=[], recipe=RECIPE,
                recognizer=fake_recognizer(HEARD), supplied=None, out=out)
    return run_words(**{**args, **over})


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_recognised_line_is_corrected_on_every_word_and_gate_passes(tmp_path: Path) -> None:
    summary = run(tmp_path / "root", tmp_path / "out")
    timing = read(tmp_path / "out" / TIMING_FILE)
    first, second = timing["entries"][0]["words"]
    assert (first["start_frame"], second["start_frame"]) == (112, 136)  # 0.4 s and 1.2 s after f100
    assert first["raw_whisper_start_s"] == 0.0 and first["boundary_calibrated_start"] is True  # the raw value is kept
    assert (first["end_s"], second["end_s"]) == (0.9, 1.8)  # ends kept
    assert summary["verdict"] == "PASS" and summary["ok"] and summary["words_moved"] == 1  # 'job' by the all-words rule
    assert summary["q1"]["control_detected"] is True
    caption_words(timing["entries"][0])  # the editorial stage accepts the rows as they are


def test_last_word_ends_where_the_speech_ends_and_the_recognised_end_stays_on_record(tmp_path: Path) -> None:
    early = {"Good job": [("Good", 0.0, 0.9), ("job", 0.9, 1.5)]}  # Whisper ends the last word 0.3 s early
    run(tmp_path / "root", tmp_path / "out", recognizer=fake_recognizer(early))
    timing = read(tmp_path / "out" / TIMING_FILE)
    last = timing["entries"][0]["words"][1]
    assert last["end_s"] == 1.8 and last["end_frame_exclusive"] == 154 and last["boundary_calibrated_end"] is True
    assert last["raw_whisper_end_s"] == 1.5 and timing["entries"][0]["recognition"]["last_end_calibration"]["moved"]
    assert timing["schema"] == RECIPE.data["document_schema"] and timing["generator"] == "jjv timing words"
    off = {**RECIPE.data, "first_word": {**RECIPE.data["first_word"], "calibrate_last_end": False}}
    run(tmp_path / "root", tmp_path / "off", recognizer=fake_recognizer(early), recipe=dataclasses.replace(RECIPE, data=off))
    assert read(tmp_path / "off" / TIMING_FILE)["entries"][0]["words"][1]["end_s"] == 1.5


def test_files_are_write_once_deterministic_and_the_receipt_binds_inputs(tmp_path: Path) -> None:
    first = run(tmp_path / "root", tmp_path / "a")["files"]
    assert run(tmp_path / "root", tmp_path / "b")["files"] == first  # no timestamp anywhere
    receipt = read(tmp_path / "a" / RECEIPT_FILE)
    assert receipt["outputs"] == {TIMING_FILE: first[TIMING_FILE], QA_FILE: first[QA_FILE]}
    assert receipt["outputs"][TIMING_FILE] == sha256_file(tmp_path / "a" / TIMING_FILE)
    assert receipt["inputs"]["wavs"][0]["sha256"] == sha256_file(tmp_path / "root" / "audio" / "S01.wav")
    assert receipt["inputs"]["recipe"]["sha256"] == RECIPE.sha256 and receipt["source"] == "recognition"
    run(tmp_path / "root", tmp_path / "a")  # identical rerun is accepted
    (tmp_path / "a" / TIMING_FILE).write_text("{}", encoding="utf-8")
    with pytest.raises(Refused, match="refusing to overwrite"):
        run(tmp_path / "root", tmp_path / "a")


def test_qa_file_has_every_word_the_line_first_row_q1_rows_and_the_control(tmp_path: Path) -> None:
    run(tmp_path / "root", tmp_path / "out")
    qa = read(tmp_path / "out" / QA_FILE)
    assert [r["word"] for r in qa["words"]] == ["Good", "job"] and qa["words"][1]["rule"] == "rule A"
    assert qa["first_word_rows"][0]["moved"] and qa["first_word_rows"][0]["decision_log"]
    assert qa["q1"]["negative_control"]["after"]["status"] == "FAIL-early" and len(qa["q1"]["rows"]) == 2
    assert qa["rule"]["all_words"]["pause"]["max_shift_s"] == 0.60 and qa["timing"]["file"] == TIMING_FILE


def test_unheard_script_word_is_uncertain_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(Uncertain, match="did not find script word"):
        run(tmp_path / "root", tmp_path / "out", recognizer=fake_recognizer({"Good job": [("Good", 0.0, 0.9)]}))
    assert not (tmp_path / "out").exists()


def test_wav_must_hash_to_the_declared_sha_exist_and_stay_inside_the_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    lines = make_lines(root)
    with pytest.raises(Refused, match="receipt-WAV rule"):
        run(root, None, lines=make_lines(root, sha="0" * 64))
    lines[0]["audio"]["path"] = "audio/missing.wav"
    with pytest.raises(Uncertain, match="WAV not found"):
        run(root, None, lines=lines)
    lines[0]["audio"]["path"] = str(tmp_path / "elsewhere.wav")
    with pytest.raises(Refused, match="outside the episode root"):
        run(root, None, lines=lines)


def test_supplied_times_are_rechecked_and_the_rules_are_idempotent(tmp_path: Path) -> None:
    run(tmp_path / "root", tmp_path / "out")
    supplied = read(tmp_path / "out" / TIMING_FILE)
    again = run(tmp_path / "root", tmp_path / "again", recognizer=None, supplied=supplied)
    assert again["source"] == "supplied" and again["words_moved"] == 0  # nothing left to move
    assert read(tmp_path / "again" / TIMING_FILE)["entries"][0]["words"] == supplied["entries"][0]["words"]
    wrong_text = json.loads(json.dumps(supplied))
    wrong_text["entries"][0]["words"][0]["raw_text"] = "Great"
    with pytest.raises(Refused, match="supplied words spell"):
        run(tmp_path / "root", None, recognizer=None, supplied=wrong_text)
    wrong_wav = json.loads(json.dumps(supplied))
    wrong_wav["entries"][0]["audio"]["sha256"] = "1" * 64
    with pytest.raises(Refused, match="supplied timing was made on WAV"):
        run(tmp_path / "root", None, recognizer=None, supplied=wrong_wav)


def test_exactly_one_source_of_word_times(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="exactly one source"):
        run(tmp_path / "root", None, recognizer=None, supplied=None)
    with pytest.raises(Refused, match="exactly one source"):
        run(tmp_path / "root", None, supplied={"entries": []})


def test_silent_line_without_words_is_carried_and_not_recognised(tmp_path: Path) -> None:
    lines = make_lines(tmp_path / "root") + parse_lines({"dialogue": [{
        "id": "S02", "start_frame": 160, "end_frame_exclusive": 220, "speech_text": "",
        "audio": {"path": "audio/none.wav", "sha256": "2" * 64}}]})
    summary = run(tmp_path / "root", tmp_path / "out", lines=lines)
    entries = read(tmp_path / "out" / TIMING_FILE)["entries"]
    assert [e["id"] for e in entries] == ["S01", "S02"] and entries[1]["words"] == [] and summary["verdict"] == "PASS"
