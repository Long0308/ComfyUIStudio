"""Step 1: script tokens, alignment, the recognition worker and the 'missing setup is Uncertain' contract."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from engine.core.errors import Refused, Uncertain
from engine.timing import whisper_worker
from engine.timing.dialogue import keyword_positions, parse_lines, parse_vocabulary, vocabulary_marks, word_rows
from engine.timing.recognise import Heard, align, find_model_dir, pair_words, script_tokens, subprocess_recognizer
from test_timing_support import RECIPE


def heard(*words: str) -> tuple[Heard, ...]:
    return tuple(Heard(w, w.strip(" ,.!?").lower(), i * 0.3, i * 0.3 + 0.25, 0.9) for i, w in enumerate(words))


def test_script_tokens_keep_the_text_authoritative() -> None:
    tokens = script_tokens("Milk is white, smooth, and liquid, Mommy! -- don't")
    assert [t["raw_text"] for t in tokens] == ["Milk", "is", "white,", "smooth,", "and", "liquid,", "Mommy!", "don't"]
    assert tokens[2]["text"] == "white" and tokens[2]["normalized"] == "white" and tokens[-1]["normalized"] == "don't"


def test_alignment_pairs_exact_words_and_drops_extras() -> None:
    assert align(["a", "b", "c"], ["a", "b", "c"]) == [(0, 0), (1, 1), (2, 2)]
    assert align(["milk", "is", "white"], ["uh", "milk", "is", "white", "uh"]) == [(0, 1), (1, 2), (2, 3)]
    assert (1, 1) in align(["milk", "colour"], ["milk", "color"])  # a similar word is a substitution, not a gap


def test_a_script_word_that_was_not_heard_is_uncertain_and_never_estimated() -> None:
    tokens = script_tokens("Milk is white")
    assert [h.raw for h in pair_words(tokens, heard("Milk", "is", "white"), 0.45, "S01")] == ["Milk", "is", "white"]
    with pytest.raises(Uncertain, match=r"did not find script word\(s\) \['white'\]") as caught:
        pair_words(tokens, heard("Milk", "is"), 0.45, "S01")
    assert caught.value.evidence["missing_script_words"] == ["white"]
    with pytest.raises(Uncertain):
        pair_words(tokens, heard("Milk", "is", "zebra"), 0.45, "S01")  # too dissimilar to count as heard


def test_word_rows_have_the_fields_captions_and_icon_events_read() -> None:
    line = {"id": "S01", "start_frame": 100, "end_frame_exclusive": 250, "speech_text": "Dairy cows love farm grass.",
            "target_keywords": ["farm"], "audio": {}}
    vocab = parse_vocabulary([{"term": "dairy cows", "icon": "dairy-cow.png"}, {"term": "farm", "icon": "farm.png"}])
    rows = word_rows(line, list(heard("Dairy", "cows", "love", "farm", "grass.")), vocab, 30, 4.0, "whisper-small.en")
    assert [r["raw_text"] for r in rows] == ["Dairy", "cows", "love", "farm", "grass."] and rows[4]["text"] == "grass"
    assert [r["vocab_anchor"] for r in rows] == [True, False, False, True, False]  # multi-word term anchors on its first word
    assert rows[1]["vocab_icon"] == "dairy-cow.png" and rows[3]["is_keyword"] and not rows[0]["is_keyword"]
    assert rows[0]["start_frame"] == 100 and rows[0]["raw_whisper_start_s"] == 0.0 and rows[1]["raw_whisper_start_s"] is None
    assert all(r["start_frame"] < r["end_frame_exclusive"] <= 250 for r in rows) and rows[0]["method"] == "whisper-small.en"


def test_word_times_are_made_monotonic_and_clamped_into_the_wav() -> None:
    line = {"id": "S01", "start_frame": 0, "end_frame_exclusive": 60, "speech_text": "a b", "audio": {}}
    odd = (Heard("a", "a", -0.2, 0.5, 0.9), Heard("b", "b", 0.3, 9.0, 0.9))  # starts before 0, overlaps, ends past the WAV
    rows = word_rows(line, list(odd), [], 30, 2.0, "whisper-x")
    assert rows[0]["start_s"] == 0.0 and rows[1]["start_s"] == 0.5 and rows[1]["end_s"] == 2.0


def test_vocabulary_pair_anchors_each_word_and_longest_term_wins() -> None:
    vocab = parse_vocabulary([{"term": "warm", "icon": "warm-cold.png"}, {"term": "cold", "icon": "warm-cold.png"},
                              {"term": "ice cream", "icon": "ice-cream.png"}, {"term": "ice", "icon": "ice.png"}])
    marks = vocabulary_marks(["warm", "and", "cold", "ice", "cream"], vocab)
    assert marks[0]["vocab_anchor"] and marks[2]["vocab_anchor"] and 1 not in marks
    assert marks[3]["vocab_icon"] == "ice-cream.png" and marks[3]["vocab_anchor"] and not marks[4]["vocab_anchor"]
    assert keyword_positions(["a", "ice", "cream"], ["ice cream"]) == {1, 2}


@pytest.mark.parametrize("change, message", [
    ({"id": ""}, "unique string id"), ({"start_frame": 1.5}, "must be an integer"), ({"end_frame_exclusive": 0}, "end_frame_exclusive > start_frame"),
    ({"audio": {"path": "a.wav"}}, "64-hex sha256"), ({"speech_text": 3}, "speech_text string")])
def test_dialogue_rows_are_validated(change: dict, message: str) -> None:
    row = {"id": "S01", "start_frame": 10, "end_frame_exclusive": 100, "speech_text": "Hi", "audio": {"path": "a.wav", "sha256": "0" * 64}}
    assert parse_lines({"dialogue": [row]})[0]["id"] == "S01"
    with pytest.raises(Refused, match=message):
        parse_lines({"dialogue": [{**row, **change}]})
    with pytest.raises(Refused, match="unique string id"):
        parse_lines({"dialogue": [row, row]})


# ---- the worker, in-process with a fake model --------------------------------------------------------
class FakeWord:
    def __init__(self, word: str, start: float, end: float) -> None:
        self.word, self.start, self.end, self.probability = word, start, end, 0.8


class FakeSegment:
    text = " Hi there"
    words = [FakeWord(" Hi", 0.1, 0.3), FakeWord(" there", 0.3, 0.7)]


class FakeModel:
    seen: dict = {}

    def __init__(self, model_dir: str, **kwargs: object) -> None:
        FakeModel.seen["init"] = {"model_dir": model_dir, **kwargs}

    def transcribe(self, wav: str, **kwargs: object):
        FakeModel.seen["transcribe"] = kwargs
        return [FakeSegment()], None


def request(**changes: object) -> dict:
    rec = RECIPE.block("recognition")
    base = {"model_dir": "m", "wav": "a.wav", "prompt": "Hi there", "language": "en", "device": rec["device"],
            "compute_type": rec["compute_type"], "params": {k: rec[k] for k in (
                "beam_size", "best_of", "patience", "temperature", "vad_filter", "condition_on_previous_text")}}
    return {**base, **changes}


def test_worker_returns_words_with_the_recipe_parameters_and_forces_cpu() -> None:
    reply = whisper_worker.run(request(), model_factory=FakeModel)
    assert reply["ok"] and [w["raw"] for w in reply["words"]] == [" Hi", " there"] and reply["transcript"] == "Hi there"
    assert FakeModel.seen["init"]["device"] == "cpu" and FakeModel.seen["transcribe"]["initial_prompt"] == "Hi there"
    assert FakeModel.seen["transcribe"]["beam_size"] == 5 and FakeModel.seen["transcribe"]["word_timestamps"] is True


def test_worker_refuses_a_gpu_device_and_reports_a_failing_model_as_data() -> None:
    assert not whisper_worker.run(request(device="cuda"), model_factory=FakeModel)["ok"]

    def broken(*args: object, **kwargs: object):
        raise RuntimeError("model.bin is corrupt")
    reply = whisper_worker.run(request(), model_factory=broken)
    assert not reply["ok"] and "model.bin is corrupt" in reply["error"]


def test_missing_python_model_or_package_is_uncertain_with_the_reason(tmp_path: Path) -> None:
    with pytest.raises(Uncertain, match="speech-recognition Python not found"):
        subprocess_recognizer(tmp_path / "nope" / "python.exe", tmp_path, RECIPE.block("recognition"), "en")
    with pytest.raises(Uncertain, match="model folder not found"):
        find_model_dir(tmp_path / "no-model")
    with pytest.raises(Uncertain, match="no model.bin"):
        find_model_dir(tmp_path)
    snapshot = tmp_path / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    (snapshot / "model.bin").write_bytes(b"x")
    assert find_model_dir(tmp_path) == snapshot


@pytest.mark.skipif(importlib.util.find_spec("faster_whisper") is not None, reason="this interpreter has faster_whisper")
def test_a_python_without_faster_whisper_is_uncertain_through_the_real_worker(tmp_path: Path) -> None:
    recognise = subprocess_recognizer(sys.executable, tmp_path, RECIPE.block("recognition"), "en")
    with pytest.raises(Uncertain, match="faster_whisper is not importable"):
        recognise(tmp_path / "a.wav", "Hi")
