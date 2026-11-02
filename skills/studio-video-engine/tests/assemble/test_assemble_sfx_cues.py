"""SFX frame cues: exactly one position field, exact sample placement, and zero-fade transients."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from engine.assemble import edl as E
from engine.assemble import stems

SCHEMA = "demo/film-edl/v1"
KINDS = ("clip", "card", "slate")
TRANSITIONS = ("cut", "dissolve")
RATE = 48000
FPS = 24


def fake_probe(_path):
    return {"frames": 100, "fps": float(FPS), "width": 2560, "height": 1440, "has_audio": False}


def write_wav(path, pcm):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(np.asarray(pcm, dtype="<i2").tobytes())
    return path


def document(tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"clip-a")
    digest = hashlib.sha256(b"clip-a").hexdigest()

    def segment(sid, transition=None):
        row = {"id": sid, "kind": "clip", "source": str(clip), "sha256": digest, "in_frame": 0, "out_frame": 48}
        if transition:
            row["transition_in"] = transition
        return row

    return {
        "schema": SCHEMA,
        "film_id": "sfx-frame-cue-demo",
        "fps": FPS,
        "segments": [segment("A"), segment("B", {"type": "dissolve", "frames": 6})],
        "dialogue": [],
        "sfx": [],
    }


def validate(value, base):
    return E.validate_edl(value, base, schema=SCHEMA, fps=FPS, kinds=KINDS, transitions=TRANSITIONS,
                          probe=fake_probe)


@pytest.mark.parametrize("cue", [
    {"cue_id": "none", "segment": "A"},
    {"cue_id": "both", "segment": "A", "at_s": 0.0, "at_f": 0},
])
def test_sfx_requires_exactly_one_position(tmp_path, cue):
    value = document(tmp_path)
    value["sfx"] = [cue]
    with pytest.raises(E.Refused) as caught:
        validate(value, tmp_path)
    assert E.code_of(caught.value) == E.EDL_SFX_POSITION


def test_at_f_is_sample_exact_on_the_frame_grid(tmp_path):
    value = document(tmp_path)
    value["sfx"] = [{"cue_id": "hit", "segment": "B", "at_f": 7}]
    validation = validate(value, tmp_path)
    cue = value["sfx"][0]
    offset = stems.sfx_offset_samples(cue, validation["segments"][1]["start_f"], RATE, FPS)
    assert offset == (validation["segments"][1]["start_f"] + 7) * (RATE // FPS)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for the rendered SFX proof")
def test_fade_zero_keeps_the_first_sample_peak(tmp_path, monkeypatch):
    dialogue = np.zeros((RATE * 2, 2), dtype=np.int16)
    write_wav(tmp_path / "dialogue.wav", dialogue)
    hits = np.zeros((1000, 2), dtype=np.int16)
    hits[0] = 30000
    write_wav(tmp_path / "hit.wav", hits)

    value = document(tmp_path)
    value["dialogue"] = [{"id": "D", "segment": "A", "at_s": 0.0, "wav": "dialogue.wav"}]
    value["sfx"] = [{
        "cue_id": "hardhat-slam",
        "segment": "A",
        "at_f": 1,
        "source": "hit.wav",
        "dur_s": 0.05,
        "gain_vs_dialogue_db": 0.0,
        "fade_in_s": 0.0,
        "fade_out_s": 0.0,
    }]
    validation = validate(value, tmp_path)
    policy = SimpleNamespace(
        sample_rate=RATE,
        fps=FPS,
        dialogue_ref_dbfs=0.0,
        audio_format=lambda: "aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo",
    )
    monkeypatch.setattr(stems, "volume_mean_db", lambda *_args, **_kwargs: 0.0)

    paths, report = stems.build_stems(value, validation, tmp_path, policy, tmp_path, "ffmpeg", subprocess.run)
    pcm = stems.read_pcm16_stereo(paths["sfx"], "sfx", RATE)
    first = RATE // FPS
    assert report["sfx"][0]["offset_samples"] == first
    assert not pcm[first - 1].any()
    assert abs(int(pcm[first, 0])) > 1000


@pytest.mark.parametrize("cue", [
    {"cue_id": "neg", "segment": "A", "at_s": -1},
    {"cue_id": "text", "segment": "A", "at_s": "soon"},
    {"cue_id": "flag", "segment": "A", "at_s": True},
    {"cue_id": "far", "segment": "A", "at_s": 99},
])
def test_bad_at_s_keeps_the_audio_reference_refusal(tmp_path, cue):
    value = document(tmp_path)
    value["sfx"] = [cue]
    with pytest.raises(E.Refused) as caught:
        validate(value, tmp_path)
    assert E.code_of(caught.value) == E.EDL_AUDIO_REF


@pytest.mark.parametrize("frame", [-1, 1.5, True])
def test_bad_at_f_refuses_sfx_position(tmp_path, frame):
    value = document(tmp_path)
    value["sfx"] = [{"cue_id": "frame", "segment": "A", "at_f": frame}]
    with pytest.raises(E.Refused) as caught:
        validate(value, tmp_path)
    assert E.code_of(caught.value) == E.EDL_SFX_POSITION


@pytest.mark.parametrize("fade", [{"fade_in_s": -0.1}, {"fade_out_s": "x"}])
def test_bad_fade_refuses_sfx_position(tmp_path, fade):
    value = document(tmp_path)
    value["sfx"] = [{"cue_id": "fade", "segment": "A", "at_f": 1, **fade}]
    with pytest.raises(E.Refused) as caught:
        validate(value, tmp_path)
    assert E.code_of(caught.value) == E.EDL_SFX_POSITION
