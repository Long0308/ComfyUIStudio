"""EDL validation tests (fake probe, no ffmpeg): every refusal is named by its stable code."""

from __future__ import annotations

import copy
import hashlib

import pytest

from engine.assemble import edl as E

SCHEMA = "demo/film-edl/v1"
KINDS = ("clip", "card", "slate")
TRANSITIONS = ("cut", "dissolve")

def fake_probe(_path):
    return {"frames": 100, "fps": 24.0, "width": 2560, "height": 1440, "has_audio": False}

def validate(document, base):
    return E.validate_edl(document, base, schema=SCHEMA, fps=24, kinds=KINDS, transitions=TRANSITIONS,
                          probe=fake_probe)

def code(document, base):
    with pytest.raises(E.Refused) as caught:
        validate(document, base)
    return E.code_of(caught.value)

@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "a.mp4"
    path.write_bytes(b"clip-a")
    return path, hashlib.sha256(b"clip-a").hexdigest()

@pytest.fixture
def document(clip, tmp_path):
    path, digest = clip
    def segment(sid, **extra):
        return {"id": sid, "kind": "clip", "source": str(path), "sha256": digest, "in_frame": 0,
                "out_frame": 48, **extra}
    return {"schema": SCHEMA, "film_id": "demo-film", "fps": 24,
            "segments": [segment("A"), segment("B", transition_in={"type": "dissolve", "frames": 6})],
            "dialogue": [], "sfx": []}

def test_timeline_and_dissolve_overlap(document, tmp_path):
    validation = validate(document, tmp_path)
    assert validation["total_frames"] == 48 + 48 - 6
    assert validation["segments"][1]["start_f"] == 42
    assert validation["segments"][0]["trans"] == ("cut", 0)

def test_missing_source(document, tmp_path):
    document = copy.deepcopy(document)
    document["segments"][0]["source"] = str(tmp_path / "nope.mp4")
    assert code(document, tmp_path) == "EDL_SOURCE_MISSING"

@pytest.mark.parametrize("mutate", [
    lambda doc: doc["segments"][1].__setitem__("sha256", "0" * 64),
    lambda doc: doc["segments"][0].pop("sha256"),
])
def test_sha_mismatch(document, tmp_path, mutate):
    document = copy.deepcopy(document)
    mutate(document)
    assert code(document, tmp_path) == "EDL_SHA_MISMATCH"

@pytest.mark.parametrize("first,last", [(10, 10), (-1, 5), (0, 101), (20, 5)])
def test_bad_frame_range(document, tmp_path, first, last):
    document = copy.deepcopy(document)
    document["segments"][0].update(in_frame=first, out_frame=last)
    assert code(document, tmp_path) == "EDL_BAD_FRAME_RANGE"

@pytest.mark.parametrize("index,transition", [
    (1, {"type": "dissolve", "frames": 48}),
    (1, {"type": "wipe", "frames": 4}),
    (0, {"type": "dissolve", "frames": 4}),
])
def test_bad_transition(document, tmp_path, index, transition):
    document = copy.deepcopy(document)
    document["segments"][index]["transition_in"] = transition
    assert code(document, tmp_path) == "EDL_BAD_TRANSITION"

@pytest.mark.parametrize("mutate", [
    lambda doc: doc.__setitem__("schema", "x"),
    lambda doc: doc.__setitem__("fps", 25),
    lambda doc: doc.pop("film_id"),
    lambda doc: doc["segments"][1].__setitem__("id", "A"),
    lambda doc: doc["segments"][0].__setitem__("kind", "pose"),
    lambda doc: doc.__setitem__("segments", []),
])
def test_schema_refusals(document, tmp_path, mutate):
    document = copy.deepcopy(document)
    mutate(document)
    assert code(document, tmp_path) == "EDL_SCHEMA"

@pytest.mark.parametrize("cues", [
    [{"cue_id": "x", "segment": "ZZ", "at_s": 0}],
    [{"cue_id": "x", "segment": "A", "at_s": 99}],
    [{"cue_id": "x", "segment": "A", "at_s": -1}],
])
def test_audio_reference(document, tmp_path, cues):
    document = copy.deepcopy(document)
    document["sfx"] = cues
    assert code(document, tmp_path) == "EDL_AUDIO_REF"

def test_card_logo_missing_and_slate(document, tmp_path):
    document = copy.deepcopy(document)
    document["segments"].append({"id": "C", "kind": "card", "frames": 10, "logo": "no.png"})
    assert code(document, tmp_path) == "EDL_SOURCE_MISSING"
    document["segments"].pop()   # drop the broken card so the slate is the first failure
    document["segments"].append({"id": "S", "kind": "slate", "frames": 0})
    assert code(document, tmp_path) == "EDL_BAD_FRAME_RANGE"

def test_dialogue_wav_sha(document, tmp_path):
    wav = tmp_path / "line.wav"
    wav.write_bytes(b"LINE")
    good = hashlib.sha256(b"LINE").hexdigest()
    document = copy.deepcopy(document)
    document["dialogue"] = [{"id": "D1", "segment": "A", "at_s": 0.0, "wav": str(wav), "sha256": good, "text": "x", "placeholder": True}]
    assert validate(document, tmp_path)["total_frames"] == 90
    document["dialogue"][0]["sha256"] = "0" * 64
    assert code(document, tmp_path) == "EDL_SHA_MISMATCH"

def test_music_source_is_hash_bound(document, tmp_path):
    music = tmp_path / "bed.wav"
    music.write_bytes(b"BED")
    document = copy.deepcopy(document)
    document["music"] = {"source": str(music), "sha256": hashlib.sha256(b"BED").hexdigest()}
    assert validate(document, tmp_path)["total_frames"] == 90
    document["music"]["sha256"] = "0" * 64
    assert code(document, tmp_path) == "EDL_SHA_MISMATCH"

def test_fade_frames_are_bounded(document, tmp_path):
    document = copy.deepcopy(document)
    document["segments"][0]["fade_in_frames"] = 49
    assert code(document, tmp_path) == "EDL_BAD_FRAME_RANGE"

def test_output_guard(tmp_path):
    target = tmp_path / "master.mp4"
    E.guard_outputs([tmp_path / "free.mp4"])
    target.write_bytes(b"x")
    with pytest.raises(E.Refused) as caught:
        E.guard_outputs([target])
    assert E.code_of(caught.value) == "OUTPUT_EXISTS"
