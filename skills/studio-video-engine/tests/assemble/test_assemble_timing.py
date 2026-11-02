"""Word-timing binding, EDL_TIMING_* refusals and the first-word-onset-snap-v1 rule (port of the R2/snap reference tests)."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from engine.assemble import edl as E
from engine.assemble.timing import SNAP_RULE, first_word_snap

SCHEMA = "demo/film-edl/v1"


def fake_probe(_path):
    return {"frames": 100, "fps": 24.0, "width": 2560, "height": 1440, "has_audio": False}


def validate(document, base):
    return E.validate_edl(document, base, schema=SCHEMA, fps=24, kinds=("clip", "card", "slate"),
                          transitions=("cut", "dissolve"), probe=fake_probe)


def code(document, base):
    with pytest.raises(E.Refused) as caught:
        validate(document, base)
    return E.code_of(caught.value)


@pytest.fixture
def document(tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"clip-a")
    digest = hashlib.sha256(b"clip-a").hexdigest()
    seg = {"id": "A", "kind": "clip", "source": str(clip), "sha256": digest, "in_frame": 0, "out_frame": 48}
    return {"schema": SCHEMA, "film_id": "demo-film", "fps": 24, "segments": [seg], "dialogue": [], "sfx": []}


def row(**extra):
    return {"id": "D", "segment": "A", "at_s": 0, "wav": None, "text": "xin chao", **extra}


def receipt(tmp_path, wav_sha, words=("xin", "chao")):
    doc = {"entries": [{"id": "D", "audio": {"sha256": wav_sha},
                        "words": [{"text": w, "start_s": i * 0.3, "end_s": i * 0.3 + 0.25} for i, w in enumerate(words)]}]}
    path = tmp_path / "t.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return {"receipt": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "entry_id": "D"}


def with_row(document, **extra):
    document = copy.deepcopy(document)
    document["dialogue"] = [row(**extra)]
    return document


def test_final_row_without_timing_refused(document, tmp_path):
    assert code(with_row(document, placeholder=False), tmp_path) == "EDL_TIMING_MISSING"


def test_placeholder_row_may_estimate(document, tmp_path):
    validate(with_row(document, placeholder=True), tmp_path)


def test_missing_timing_receipt_file(document, tmp_path):
    timing = {"receipt": str(tmp_path / "none.json"), "sha256": "0" * 64, "entry_id": "D"}
    assert code(with_row(document, timing=timing), tmp_path) == "EDL_TIMING_MISSING"


def test_timing_receipt_sha_mismatch(document, tmp_path):
    timing = receipt(tmp_path, "x")
    timing["sha256"] = "0" * 64
    assert code(with_row(document, timing=timing), tmp_path) == "EDL_TIMING_MISMATCH"


def test_timing_for_another_wav(document, tmp_path):
    wav = tmp_path / "d.wav"
    wav.write_bytes(b"wav")
    doc = with_row(document, wav=str(wav), sha256=hashlib.sha256(b"wav").hexdigest(), timing=receipt(tmp_path, "f" * 64))
    assert code(doc, tmp_path) == "EDL_TIMING_MISMATCH"


def test_timing_text_differs(document, tmp_path):
    assert code(with_row(document, timing=receipt(tmp_path, "x", words=("xin", "chào"))), tmp_path) == "EDL_TIMING_MISMATCH"


def test_timing_ok_and_dash_token_ignored(document, tmp_path):
    validate(with_row(document, timing=receipt(tmp_path, "x")), tmp_path)
    validate(with_row(document, text="xin - chao", timing=receipt(tmp_path, "x")), tmp_path)


WORDS = [{"text": "Mai", "start_s": 0.76, "end_s": 1.12}, {"text": "em", "start_s": 1.12, "end_s": 1.32}]


def qa(**changes):
    base = {"entry": "L", "index": 1, "onset_s": 0.11, "delta_f": 15, "status": "LATE>4f"}
    return {"q1": {"rows": [{**base, **changes}]}}


def test_snap_moves_late_first_word_keeps_end():
    out, records = first_word_snap(WORDS, "L", qa(), "a" * 64)
    assert (out[0]["start_s"], out[0]["end_s"], out[1]) == (0.11, 1.12, WORDS[1])
    assert (records[0]["rule"], records[0]["original_start_s"], records[0]["new_start_s"]) == (SNAP_RULE, 0.76, 0.11)
    assert WORDS[0]["start_s"] == 0.76   # the input is not mutated


@pytest.mark.parametrize("changes", [
    {"status": "PASS", "delta_f": 1}, {"status": "WARN", "delta_f": 3}, {"status": "LATE>4f", "delta_f": 4},
    {"onset_s": None}, {"onset_s": 2.0}, {"index": 2}])
def test_snap_leaves_the_words_alone(changes):
    out, records = first_word_snap(WORDS, "L", qa(**changes), "a" * 64)
    assert (out, records) == (WORDS, [])
