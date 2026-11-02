"""The brand voice layer of ``jjv audio mix``: plays alone first, the music starts after it (T-E43)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from audio_fixtures import RATE, audio_world, hand_built_review, write_tone
from test_audio_mix_run import ffmpeg, make_args, run

from engine.audio import mix
from engine.core.errors import Refused
from engine.voice.wavio import read_wav


@pytest.fixture
def episode(tmp_path):
    config, _ = audio_world(tmp_path)
    root = Path(config.episode_root)
    doc = hand_built_review(root, total_frames=510, lines=(("S01_A", 90, 2.0, 0.17), ("S01_B", 210, 2.0, 0.17)),
                            cards=(("Alpha", 330, 3.0, 0.17), ("Beta", 420, 3.0, 0.17)))
    review = root / "review-config.json"
    review.write_text(json.dumps(doc), encoding="utf-8")
    music = root / "music.wav"
    write_tone(music, 6.0, 0.4, 180.0)
    voice = root / "brand.wav"
    sha = write_tone(voice, 1.0, 0.19, 523.0)
    return config, root, review, music, voice, sha


def stems(tmp_path: Path, name: str) -> np.ndarray:
    return np.frombuffer(read_wav(tmp_path / "mix" / mix.STEMS[name]).pcm, dtype="<i2").reshape(-1, 2)


def test_dry_run_adds_the_brand_voice_section_and_names_its_window(episode, tmp_path) -> None:
    config, root, review, music, voice, sha = episode
    summary, code = run(config, make_args(tmp_path, review, music, dry_run=True, brand_voice=str(voice), brand_voice_sha256=sha,
                                          brand_voice_start_s=0.15, brand_voice_db=0.0))
    assert code == 0 and summary["brand_voice"] == {"sha256": sha, "start_s": 0.15, "end_s": 1.15, "samples": RATE}
    assert [s["name"] for s in summary["sections"]][:3] == ["brand_voice", "intro", "dialogue"]
    assert summary["sections"][0]["end_frame_exclusive"] == 35 and summary["sections"][1]["start_frame"] == 35   # ceil(1.15 s * 30)


def test_the_voice_is_sample_exact_at_0_15_s_and_the_bed_starts_after_it_with_a_half_second_fade_in(episode, tmp_path) -> None:
    ffmpeg()
    config, root, review, music, voice, sha = episode
    summary, code = run(config, make_args(tmp_path, review, music, brand_voice=str(voice), brand_voice_sha256=sha,
                                          brand_voice_start_s=0.15, brand_voice_db=0.0))
    receipt = json.loads((tmp_path / "mix" / mix.RECEIPT_FILE).read_text("utf-8"))
    start, end = int(0.15 * RATE), int(0.15 * RATE) + RATE
    bound = np.frombuffer(read_wav(voice).pcm, dtype="<i2").reshape(-1, 2)
    brand = stems(tmp_path, "brand_voice")
    assert np.array_equal(brand[start:end], bound) and not np.any(brand[:start]) and not np.any(brand[end:])
    music_stem = np.abs(stems(tmp_path, "music").astype(np.int32))
    assert not np.any(music_stem[:end])                                              # no music while the voice speaks
    quarter, full = music_stem[end:end + RATE // 4].max(), music_stem[end + RATE:end + 2 * RATE].max()
    assert 0 < quarter < full and music_stem[end + RATE // 2:end + RATE // 2 + RATE].max() > 0.8 * full  # 0.5 s sin^2 fade-in
    assert receipt["bed_start_s"] == pytest.approx(end / RATE) and receipt["stems"]["brand_voice"]["sha256"]
    entry = receipt["brand_voice"]
    assert entry["sha256"] == sha and entry["gain_db"] == 0.0 and entry["stem_sha256"] == receipt["stems"]["brand_voice"]["sha256"]
    assert entry["file_name"] == "brand.wav" and -17.5 <= entry["section_lufs"] <= -14.5
    first = receipt["loudness"]["sections"][0]
    assert first["name"] == "brand_voice" and first["role"] == "brand_voice" and first["integrated_lufs"] == entry["section_lufs"]
    assert not any("brand voice" in f for f in receipt["failures"]) and receipt["dialogue_exact"]
    assert hashlib.sha256(voice.read_bytes()).hexdigest() == sha  # the source file is untouched and its sha is recorded separately


def test_a_voice_that_runs_into_the_first_speech_window_minus_0_2_s_is_refused(episode, tmp_path) -> None:
    config, root, review, music, voice, sha = episode
    long_voice = root / "long.wav"
    long_sha = write_tone(long_voice, 2.7, 0.19, 523.0)                              # ends at 2.85 s; the first line starts at 3.0 s
    with pytest.raises(Refused, match="guard before the first speech window"):
        run(config, make_args(tmp_path, review, music, dry_run=True, brand_voice=str(long_voice), brand_voice_sha256=long_sha,
                              brand_voice_start_s=0.15, brand_voice_db=0.0))
    ok = root / "ok.wav"
    ok_sha = write_tone(ok, 2.6, 0.19, 523.0)                                        # ends at 2.75 s <= 2.8 s
    summary, code = run(config, make_args(tmp_path, review, music, dry_run=True, brand_voice=str(ok), brand_voice_sha256=ok_sha,
                                          brand_voice_start_s=0.15, brand_voice_db=0.0))
    assert code == 0


def test_the_voice_must_match_its_sha_and_the_mix_format(episode, tmp_path) -> None:
    config, root, review, music, voice, sha = episode
    with pytest.raises(Refused, match="hashes to"):
        run(config, make_args(tmp_path, review, music, dry_run=True, brand_voice=str(voice), brand_voice_sha256="0" * 64,
                              brand_voice_start_s=0.15, brand_voice_db=0.0))
    import wave
    mono = root / "mono.wav"
    with wave.open(str(mono), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(b"\x00\x01" * 4800)
    with pytest.raises(Refused, match="stereo"):
        run(config, make_args(tmp_path, review, music, dry_run=True, brand_voice=str(mono), brand_voice_start_s=0.15, brand_voice_db=0.0))


def test_a_brand_voice_outside_minus_16_plus_minus_1_5_lufs_fails_the_gate(episode, tmp_path) -> None:
    ffmpeg()
    config, root, review, music, voice, sha = episode
    quiet = root / "quiet.wav"
    quiet_sha = write_tone(quiet, 1.0, 0.05, 523.0)                                  # about -26 LUFS
    summary, code = run(config, make_args(tmp_path, review, music, brand_voice=str(quiet), brand_voice_sha256=quiet_sha,
                                          brand_voice_start_s=0.15, brand_voice_db=0.0))
    assert code == 1 and any(f.startswith("brand voice") for f in summary["failures"])
    boosted, code = run(config, make_args(tmp_path / "again", review, music, brand_voice=str(quiet), brand_voice_sha256=quiet_sha,
                                          brand_voice_start_s=0.15, brand_voice_db=11.0))
    receipt = json.loads((tmp_path / "again" / "mix" / mix.RECEIPT_FILE).read_text("utf-8"))
    assert receipt["brand_voice"]["gain_db"] == 11.0 and -17.5 <= receipt["brand_voice"]["section_lufs"] <= -14.5
    assert not any(f.startswith("brand voice") for f in boosted["failures"])

@pytest.fixture(autouse=True)
def _brand_voice_in_film(monkeypatch):
    """These cases mix the brand voice INTO the film (the pre-intro ep04 cut): declare episode.audio.brand_voice = film.
    The default is 'intro' (the voice lives in the brand intro), see engine/audio/library_brand.py."""
    from engine.audio import library_brand
    monkeypatch.setattr(library_brand, "episode_mode", lambda _config: "film")
