"""Q5: pacing arithmetic, file facts (ffprobe), measured logo still, per-section loudness."""

from __future__ import annotations

import copy
from fractions import Fraction
from pathlib import Path

import pytest

from test_qa_review_support import (FFMPEG, FPS, H, W, ep_config, gray_of, make_config, needs_ep, needs_ffmpeg, np, recipe,
                                    scene, write_wav)
from engine.media.probe import VideoInfo
from engine.qa.gates import FAIL, PASS, UNCERTAIN, q5_loudness, q5_pacing
from engine.qa.review_model import build_model, contract_frames, logo_still_frames

LEVEL = 0.2  # peak of a 1 kHz sine at about -17 LUFS


def config(**over) -> dict:
    base = make_config([{"boundary": 5, "type": "none", "frames": 0}], main_frames=540, end_hold_frames=30, total_frames=540,
                       outro_cards=[{"term": "Alpha", "start_frame": 330, "duration_frames": 90},
                                    {"term": "Beta", "start_frame": 420, "duration_frames": 90}],
                       ending={"logo_disc": {"still_hold": "f100-f165 (66 f)"}, "end_plate": {"start": 510}})
    base["dialogue"] = [{"id": "S01_A", "start_frame": 90, "end_frame_exclusive": 200, "words": [], "segments": []},
                        {"id": "S01_B", "start_frame": 200, "end_frame_exclusive": 300, "words": [], "segments": []}]
    base.update(over)
    return base


def check(result: list[dict], name: str) -> dict:
    return next(c for c in result if c["name"] == name)


def pace(cfg: dict, expect=None):
    return q5_pacing.pacing(cfg, build_model(cfg, recipe()), recipe(), expect)


def test_a_consistent_config_passes_every_arithmetic_check() -> None:
    checks, total = pace(config())
    assert total == 570 and all(c["ok"] for c in checks), [c for c in checks if not c["ok"]]
    assert {c["name"] for c in checks} >= {"logo_still", "card_length", "tiling", "plate_after_cards", "main_plus_end_card"}


@pytest.mark.parametrize("text,ok", [("f100-f159 (60 f)", True), ("f100-f158 (59 f)", False), ("f2147-f2159 (13 f)", False)])
def test_the_logo_still_must_reach_sixty_frames(text: str, ok: bool) -> None:
    checks, _ = pace(config(ending={"logo_disc": {"still_hold": text}, "end_plate": {"start": 510}}))
    assert check(checks, "logo_still")["ok"] is ok


def test_a_numeric_still_and_a_missing_still_are_read_or_uncertain() -> None:
    cfg = config(ending={"logo_still_frames": 75})
    assert logo_still_frames(build_model(cfg, recipe()))[0] == 75
    checks, _ = pace(config(ending={}))
    assert check(checks, "logo_still")["uncertain"] is True and not check(checks, "logo_still")["ok"]


def test_each_card_must_last_ninety_frames() -> None:
    cfg = config()
    cfg["outro_cards"][1]["duration_frames"] = 89
    cfg["outro_cards"][1]["start_frame"] = 420
    detail = check(pace(cfg)[0], "card_length")
    assert not detail["ok"] and "Beta: 89 f" in detail["detail"]


def test_gaps_overlaps_and_wrong_totals_are_found() -> None:
    cfg = config()
    cfg["dialogue"][1]["start_frame"] = 205
    cfg["outro_cards"][1]["start_frame"] = 425
    names = {c["name"] for c in pace(cfg)[0] if not c["ok"]}
    assert {"dialogue_tiling", "card_tiling"} <= names
    assert not check(pace(config(main_frames=541, total_frames_with_endlogo=570))[0], "main_plus_end_card")["ok"]
    assert not check(pace(config(), expect=3444)[0], "contract_frames")["ok"]
    assert check(pace(config(), expect=570)[0], "contract_frames")["ok"]


def test_the_contract_total_comes_from_the_most_specific_config_key() -> None:
    cfg = config(total_frames_with_endlogo=999)
    assert contract_frames(cfg, build_model(cfg, recipe())) == (999, "total_frames_with_endlogo")
    cfg = {k: v for k, v in config().items() if k != "main_frames"}
    assert contract_frames(cfg, build_model(cfg, recipe()))[1] == "total_frames + end_hold_frames"


def test_file_facts_are_compared_with_the_contract() -> None:
    model = build_model(config(), recipe())
    info = VideoInfo(frames=570, width=W, height=H, fps=Fraction(30))
    good = {"has_audio": True, "audio_s": 19.0, "video_s": 19.0}
    assert all(c["ok"] for c in q5_pacing.file_checks(info, good, model, 570, False, 0.25))
    bad = q5_pacing.file_checks(VideoInfo(569, W, H + 2, Fraction(25)), {**good, "audio_s": 17.0}, model, 570, False, 0.25)
    assert {c["name"] for c in bad if not c["ok"]} == {"frame_count", "fps", "size", "audio_stream"}
    assert q5_pacing.file_checks(VideoInfo(None, W, H, Fraction(30)), good, model, 570, True, 0.25)[0]["uncertain"]


def test_the_picture_must_honour_the_declared_still() -> None:
    p = recipe()["q5_pacing"]
    still = np.stack([gray_of(scene(1)[None])[0]] * 80 + [gray_of(scene(i)[None])[0] for i in range(2, 22)])
    assert q5_pacing.measure_still(still, 0, (10, 70), p)["longest_still_run"] == 61
    moving = np.stack([gray_of(scene(i)[None])[0] for i in range(100)])
    assert q5_pacing.measure_still(moving, 0, (10, 70), p)["longest_still_run"] <= 1
    assert q5_pacing.measure_still(moving, 0, None, p) is None and q5_pacing.measure_still(moving, 0, (50, 150), p) is None


def test_run_rolls_up_failures_and_uncertain() -> None:
    cfg = config()
    model = build_model(cfg, recipe())
    ok = q5_pacing.run(cfg, model, recipe(), None, None, None, None, 0, None, False)
    assert ok["status"] == PASS and ok["contract_frames"] == 570
    cfg["outro_cards"][0]["duration_frames"] = 30
    assert q5_pacing.run(cfg, build_model(cfg, recipe()), recipe(), None, None, None, None, 0, None, False)["status"] == FAIL
    cfg = config(ending={})
    assert q5_pacing.run(cfg, build_model(cfg, recipe()), recipe(), None, None, None, None, 0, None, False)["status"] == UNCERTAIN


@needs_ep
def test_real_review_configs_v012_fails_and_v014_passes_the_arithmetic() -> None:
    for version, expected in (("012", FAIL), ("013", PASS), ("014", PASS), ("015", PASS)):
        cfg = ep_config(version)
        model = build_model(cfg, recipe())
        result = q5_pacing.run(cfg, model, recipe(), None, None, None, None, 0, None, False)
        assert result["status"] == expected, (version, result["failures"])
    cfg = ep_config("012")
    names = {f.split(":")[0] for f in q5_pacing.run(cfg, build_model(cfg, recipe()), recipe(), None, None, None, None, 0, None, False)["failures"]}
    assert {"logo_still", "card_length"} <= names
    assert contract_frames(cfg, build_model(cfg, recipe()))[0] == 2580 and contract_frames(ep_config("014"), build_model(ep_config("014"), recipe()))[0] == 3444


# ---- loudness ----------------------------------------------------------------------------------------------------


def audio(tmp_path: Path, parts) -> Path:
    return write_wav(tmp_path / "mix.wav", parts)


@needs_ffmpeg
def test_sections_at_the_film_mix_level_pass_and_the_intro_is_informational(tmp_path: Path) -> None:
    wav = audio(tmp_path, [(3, 0.03), (7, LEVEL), (1, LEVEL), (6, LEVEL), (2, LEVEL)])
    result = q5_loudness.run(build_model(config(), recipe()), recipe(), wav, FFMPEG, 570)
    by = {r["section"]: r for r in result["sections"]}
    assert result["status"] == PASS, result["failures"]
    assert set(by) == {"intro", "dialogue", "logo_hold", "cards", "plate_endlogo", "whole"} and not by["intro"]["gated"]
    assert by["dialogue"]["lufs"] == pytest.approx(-17.0, abs=0.6)


@needs_ffmpeg
def test_a_quiet_outro_and_a_jump_between_sections_fail(tmp_path: Path) -> None:
    wav = audio(tmp_path, [(3, LEVEL), (7, LEVEL), (1, LEVEL), (6, 0.03), (2, LEVEL)])  # cards ~ -33 LUFS
    result = q5_loudness.run(build_model(config(), recipe()), recipe(), wav, FFMPEG, 570)
    text = " | ".join(result["failures"])
    assert result["status"] == FAIL and "section cards" in text and "loudness jump" in text


@needs_ffmpeg
def test_a_true_peak_above_minus_one_fails_and_clips_use_their_origin(tmp_path: Path) -> None:
    loud = audio(tmp_path, [(19, 0.99)])
    result = q5_loudness.run(build_model(config(), recipe()), recipe(), loud, FFMPEG, 570)
    assert any("true peak" in f for f in result["failures"])
    (tmp_path / "c").mkdir()
    clip = write_wav(tmp_path / "c" / "clip.wav", [(5, LEVEL)])  # audio of global 14 s .. 19 s only
    part = q5_loudness.run(build_model(config(), recipe()), recipe(), clip, FFMPEG, 570, audio_origin_s=14.0)
    assert [r["section"] for r in part["sections"]] == ["plate_endlogo"]  # the sections that start before the clip are dropped


def test_loudness_needs_dialogue_and_cards_or_it_is_unreadable() -> None:
    from engine.core.errors import Uncertain
    with pytest.raises(Uncertain):
        q5_loudness.section_frames(build_model(make_config([{"boundary": 5, "type": "none", "frames": 0}]), recipe()), 570)
    assert q5_loudness.run(build_model(config(), recipe()), recipe(), Path("x.wav"), "ffmpeg", None)["status"] == UNCERTAIN
    assert copy.deepcopy(FPS) == 30
