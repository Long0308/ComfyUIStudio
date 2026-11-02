"""Sample-exact dialogue stem (numpy), EDL_AUDIO_FORMAT and equal-length stems.  The music/sfx beds use ffmpeg and are
covered by the parity run; here only the dialogue stem and fit_wav run, so no ffmpeg is needed."""

from __future__ import annotations

import wave
from types import SimpleNamespace  # noqa: F401

import numpy as np
import pytest

from engine.assemble import edl as E
from engine.assemble import stems

RATE = 48000


def write_wav(path, pcm, rate=RATE, channels=2, width=2):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(np.asarray(pcm, dtype="<i2").tobytes())
    return path


def noise(n, seed):
    return np.random.default_rng(seed).integers(-30000, 30000, size=(n, 2), dtype=np.int16)


VALIDATION = {"total_frames": 48, "segments": [{"id": "A", "start_f": 0, "dur_f": 24}, {"id": "B", "start_f": 24, "dur_f": 24}]}


def test_dialogue_stem_is_a_sample_copy_at_exact_offsets(tmp_path):
    first, second = noise(5000, 1), noise(7000, 2)
    write_wav(tmp_path / "a.wav", first)
    write_wav(tmp_path / "b.wav", second)
    edl = {"dialogue": [{"id": "A1", "segment": "A", "at_s": 0.1, "wav": "a.wav"},
                        {"id": "B1", "segment": "B", "at_s": 0.0, "wav": "b.wav"}]}
    out = tmp_path / "stem.wav"
    report = stems.dialogue_stem(edl, VALIDATION, out, RATE, 24, tmp_path)
    pcm = stems.read_pcm16_stereo(out, "stem", RATE)
    assert len(pcm) == 48 * 2000
    assert report[0]["offset_samples"] == 4800 and np.array_equal(pcm[4800:9800], first)
    assert report[1]["offset_samples"] == 24 * 2000 and np.array_equal(pcm[48000:55000], second)
    assert all(r["stem_slice_equals_wav"] and r["tail_trimmed_samples"] == 0 for r in report)


def test_tail_past_the_picture_is_trimmed_and_counted(tmp_path):
    long = noise(RATE * 3, 3)
    write_wav(tmp_path / "l.wav", long)
    edl = {"dialogue": [{"id": "L", "segment": "B", "at_s": 0.0, "wav": "l.wav"}]}
    report = stems.dialogue_stem(edl, VALIDATION, tmp_path / "s.wav", RATE, 24, tmp_path)
    assert report[0]["tail_trimmed_samples"] == len(long) - 24 * 2000
    assert report[0]["stem_slice_equals_wav"] is True


def test_overlapping_samples_are_excluded_not_hidden(tmp_path):
    write_wav(tmp_path / "a.wav", noise(4000, 4))
    write_wav(tmp_path / "b.wav", noise(4000, 5))
    edl = {"dialogue": [{"id": "A1", "segment": "A", "at_s": 0.0, "wav": "a.wav"},
                        {"id": "B1", "segment": "A", "at_s": 0.04, "wav": "b.wav"}]}   # starts 1920 samples in
    report = stems.dialogue_stem(edl, VALIDATION, tmp_path / "s.wav", RATE, 24, tmp_path)
    assert report[0]["overlap_samples_excluded"] == 4000 - 1920 and report[1]["overlap_samples_excluded"] == 4000 - 1920
    assert all(r["stem_slice_equals_wav"] for r in report)


def test_gain_disables_the_exactness_claim(tmp_path):
    write_wav(tmp_path / "a.wav", noise(1000, 6))
    edl = {"dialogue": [{"id": "A1", "segment": "A", "wav": "a.wav", "gain_db": -6}]}
    report = stems.dialogue_stem(edl, VALIDATION, tmp_path / "s.wav", RATE, 24, tmp_path)
    assert report[0]["stem_slice_equals_wav"] is False


@pytest.mark.parametrize("make", [
    lambda p: write_wav(p, noise(100, 7), rate=44100),
    lambda p: write_wav(p, noise(100, 7)[:, 0], channels=1),
    lambda p: p.write_bytes(b"not a wav"),
])
def test_wrong_audio_format_is_refused(tmp_path, make):
    make(tmp_path / "bad.wav")
    edl = {"dialogue": [{"id": "X", "segment": "A", "wav": "bad.wav"}]}
    with pytest.raises(E.Refused) as caught:
        stems.dialogue_stem(edl, VALIDATION, tmp_path / "s.wav", RATE, 24, tmp_path)
    assert E.code_of(caught.value) == "EDL_AUDIO_FORMAT"


def test_non_wav_suffix_is_refused(tmp_path):
    (tmp_path / "x.mp3").write_bytes(b"x")
    edl = {"dialogue": [{"id": "X", "segment": "A", "wav": "x.mp3"}]}
    with pytest.raises(E.Refused) as caught:
        stems.dialogue_stem(edl, VALIDATION, tmp_path / "s.wav", RATE, 24, tmp_path)
    assert E.code_of(caught.value) == "EDL_AUDIO_FORMAT"


@pytest.mark.parametrize("n", [1000, 5000])
def test_fit_wav_pads_and_trims_to_picture_length(tmp_path, n):
    path = write_wav(tmp_path / f"f{n}.wav", noise(n, 8))
    stems.fit_wav(path, 3000, RATE)
    pcm = stems.read_pcm16_stereo(path, "f", RATE)
    kept = min(n, 3000)
    assert len(pcm) == 3000
    assert np.array_equal(pcm[:kept], noise(n, 8)[:kept])
    assert not pcm[kept:].any()
