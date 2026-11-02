"""Parity of ``jjv audio mix`` with the first episode's mix-plan v004 (music stem, duck windows) and the remux proof."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from engine.audio import mix, mixcli
from engine.voice.wavio import read_wav
from engine.core.io import sha256_file
from engine.seedvr2.seam_media import find_ffmpeg

EP = Path(__file__).resolve().parents[4] / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom"
MUSIC_SRC = EP.parent / "03-drinking-milk/audio/music/milk-pentatonic-bed-48k-v1.wav"
MUSIC_SRC_SHA = "57e58d07e5f1006ed1521fe877ecdc082b426190697c1e1f2eafca63a21b6601"
V004 = EP / "audio/mix-plan-v004"
V013 = EP / "editorial/review-hd-v013"
pytestmark = pytest.mark.skipif(not (V004 / "cue-manifest-v004.json").is_file() or not MUSIC_SRC.is_file(),
                                reason="first episode files not present")


@pytest.fixture
def v004_without_contract(parity_mix_allowed, monkeypatch):  # type: ignore[no-untyped-def]
    """These tests pin the v004-era 3314 f cut (``--total-frames 3314``).  The live ep04 now carries its 3444 f delivery
    contract, which the audio timeline refuses to contradict (M9a), so they resolve the episode WITHOUT a contract."""
    import dataclasses

    real = mixcli.resolve_episode

    def resolve(ref, **kwargs):  # type: ignore[no-untyped-def]
        config = real(ref, **kwargs)
        return dataclasses.replace(config, episode={k: v for k, v in config.episode.items() if k != "contract"})

    monkeypatch.setattr(mixcli, "resolve_episode", resolve)


def windows_v004(path: Path) -> None:
    """The v004 duck windows as a ``--windows`` file: captions-v002 dialogue + the card WAV durations (same rule)."""
    caption = json.loads((EP / "editorial/captions-v002/manifest.json").read_text("utf-8"))
    config = json.loads((V013.parent / "review-hd-v012/config/review-config-v012.json").read_text("utf-8-sig"))
    rows = [{"id": item["shot_id"], "start_s": round(float(item["timeline_delivery_30fps"]["start_s"]), 6),
             "end_s": round(min(84.0, float(item["timeline_delivery_30fps"]["start_s"]) + float(item["audio"]["speech_end_in_window_s"])), 6)}
            for item in caption["dialogue_captions"]]
    duration = {c["term"]: float(c["audio"]["duration_s"]) for c in caption["vocabulary_cards"]}
    for index, card in enumerate(config["outro_cards"]):
        start = (2230 + 90 * index) / 30
        rows.append({"id": f"OUTRO_{index + 1:02d}_{card['term']}", "start_s": start, "end_s": start + duration[card["term"]]})
    path.write_text(json.dumps(sorted(rows, key=lambda r: (r["start_s"], r["end_s"]))), encoding="utf-8")


def args_for(tmp_path: Path, **over) -> argparse.Namespace:
    windows_v004(tmp_path / "windows.json")
    # the shipped config names its WAVs under the retired D: root; the engine reads them where they live now (machine.legacy_roots)
    values = dict(episode="04-milk-and-mom", out=str(tmp_path / "mix"), review_config=str(V013 / "config/review-config-v013.json"),
                  recipe="audio/mix-legacy-v004-parity", music_receipt=None, music_wav=str(MUSIC_SRC), music_sha256=MUSIC_SRC_SHA,
                  sfx_receipt=None, sfx_stem=str(V004 / "milk-mom-ambience-foley-stem-v004-candidate.wav"),
                  sfx_sha256="04185d30e3da19a73d0a54422b7cd26e41da8c9aaf6d0fe8282b01cff8702ee6",
                  windows=str(tmp_path / "windows.json"), sections=None, allow_outside=[], ffmpeg=None, dry_run=False,
                  remux=None, remux_out=None, total_frames=3314, with_sfx=True, extra_wav=[], brand_voice=None, brand_voice_sha256=None,
                  brand_voice_start_s=0.15, brand_voice_db=0.0, allow_ungated_music=False)  # the main film (v004 stems end before the end-logo tail)
    values.update(over)
    return argparse.Namespace(**values)


@pytest.mark.usefixtures("v004_without_contract")
def test_the_music_stem_is_the_v004_stem_byte_for_byte(tmp_path) -> None:
    summary, code = mixcli.run_mix(args_for(tmp_path))
    assert code == 0 and summary["verdict"] == "UNGATED"
    reference = V004 / "milk-mom-music-stem-v004-candidate.wav"
    assert sha256_file(tmp_path / "mix" / mix.STEMS["music"]) == sha256_file(reference) == summary["stems"]["music"]
    assert summary["stems"]["sfx"] == "04185d30e3da19a73d0a54422b7cd26e41da8c9aaf6d0fe8282b01cff8702ee6"  # a prebuilt stem passes through
    receipt = json.loads((tmp_path / "mix" / mix.RECEIPT_FILE).read_text("utf-8"))
    manifest = json.loads((V004 / "cue-manifest-v004.json").read_text("utf-8"))["music"]["duck_windows"]
    ours = [(w["start_sample"], w["end_sample_exclusive"]) for w in receipt["duck_windows"]]
    assert ours == [(w["start_frame"], w["end_frame_exclusive"]) for w in manifest]  # the manifest stores SAMPLE indices under those names
    assert receipt["dialogue_exact"] and len(receipt["dialogue_wavs"]) == 24


@pytest.mark.usefixtures("v004_without_contract")
def test_remux_of_the_v013_review_cut_leaves_the_video_packets_untouched(tmp_path) -> None:
    mp4 = V013 / "milk-and-mom-REVIEW-1080p30-native-upscaled-v013.mp4"
    if not mp4.is_file():
        pytest.skip("v013 review cut not present")
    film = tmp_path / "v013-remuxed.mp4"
    summary, code = mixcli.run_mix(args_for(tmp_path, remux=str(mp4), remux_out=str(film)))
    assert code == 0 and summary["mux"]["video_untouched"]
    packets = summary["mux"]["picture"]["video_packets"]
    assert packets == summary["mux"]["output"]["video_packets"] and packets["packets"] == 3374
    assert summary["mux"]["picture"]["sha256"] == sha256_file(mp4) and film.is_file()
    ff = find_ffmpeg()
    probe = subprocess.run([ff, "-hide_banner", "-i", str(film)], capture_output=True, text=True).stderr
    assert "Video: h264" in probe and "Audio: aac" in probe


V016 = EP / "editorial/audio-mix-v016/mix-plan-v016-final-giongC-nhacV2-4.json"
LIBRARY = EP.parent / "_library"


@pytest.mark.skipif(not V016.is_file() or not (LIBRARY / "brand-voice").is_dir(), reason="the approved v016 final mix is not present")
@pytest.mark.usefixtures("_brand_voice_in_film")
def test_the_engine_reproduces_the_approved_v016_final_hand_mix_within_0_3_lu_and_passes_its_own_gate(tmp_path) -> None:
    """Parity target: the user-approved FINAL mix (bed NHAC-V2-4, brand voice GIONG-C, story -9.0 / outro -6.5 dB, duck -7 dB,
    dialogue -1.5, vocabulary +2.7, end line +2.7-6.0) as the episode recipe ``audio/mix-cinema-ep04-final-v001``."""
    from engine.audio import loudness
    plan = json.loads(V016.read_text("utf-8"))
    args = args_for(tmp_path, recipe="audio/mix-cinema-ep04-final-v001", total_frames=None, sfx_stem=None, sfx_sha256=None,
                    with_sfx=False, windows=None, music_wav=str(LIBRARY / "music-beds/NHAC-V2-4-V2A-guitar-marimba-inst-full-48k.wav"),
                    music_sha256=plan["bed"]["sha256"], review_config=str(EP / "editorial/review-hd-v015/config/review-config-v015.json"),
                    brand_voice=str(LIBRARY / "brand-voice/GIONG-C-jennie-joy-kids.wav"), brand_voice_sha256=plan["jingle"]["sha256"],
                    brand_voice_start_s=plan["jingle"]["start_s"], brand_voice_db=plan["jingle"]["gain_db"],
                    extra_wav=["end line|audio/end-line-v001/end-line-mother-trim-v001-48k.wav|"
                               "d250672daa49e7d70eb589311ef46e1c100fca17c35d603a5d04bd3baa01b5d7|3322|end_line"])
    summary, code = mixcli.run_mix(args)
    receipt = json.loads((tmp_path / "mix" / mix.RECEIPT_FILE).read_text("utf-8"))
    assert code == 0 and summary["verdict"] == "PASS", receipt["failures"]                       # its OWN gate
    assert receipt["bed_start_s"] == pytest.approx(plan["bed"]["start_s"], abs=0.001)             # the music starts when the voice ends
    assert {k: v["gain_db"] for k, v in receipt["speech_buses"].items()} == {"dialogue": -1.5, "end_line": -3.3, "vocabulary": 2.7}
    assert receipt["brand_voice"]["sha256"] == plan["jingle"]["sha256"] and receipt["roles"].count("speech") == 3
    final = np.frombuffer(read_wav(tmp_path / "mix" / mix.STEMS["final"]).pcm, dtype="<i2").reshape(-1, 2)
    seconds = len(final) / 48000
    windows = {"intro_0_3s": (0, 3), "dialogue_0_72s": (0, 72), "logo_hold_72_74.33s": (72, 74.33), "cards_74.33_110.33s": (74.33, 110.33),
               "plate_line_endlogo_110.33_end": (110.33, seconds), "whole": (0, seconds)}
    for name, (start, end) in windows.items():
        got = loudness.measure(final[int(start * 48000):int(end * 48000)], 48000, find_ffmpeg())
        assert abs(got.integrated_lufs - plan["sections"][name]["integrated_LUFS"]) <= 0.3, (name, got.integrated_lufs)
    whole = loudness.measure(final, 48000, find_ffmpeg())
    assert abs(whole.true_peak_dbtp - plan["sections"]["whole"]["true_peak_dBTP"]) <= 0.3

@pytest.fixture
def _brand_voice_in_film(monkeypatch):
    """These cases mix the brand voice INTO the film (the pre-intro ep04 cut): declare episode.audio.brand_voice = film.
    The default is 'intro' (the voice lives in the brand intro), see engine/audio/library_brand.py."""
    from engine.audio import library_brand
    monkeypatch.setattr(library_brand, "episode_mode", lambda _config: "film")
