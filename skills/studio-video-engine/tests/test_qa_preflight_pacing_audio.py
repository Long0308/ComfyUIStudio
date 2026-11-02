"""Preflight pacing arithmetic and the audio contract: pure config/receipt checks (no ffmpeg, no pixels)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from test_qa_review_support import make_config, recipe
from engine.core.errors import Refused, Uncertain
from engine.qa import preflight, preflight_audio, preflight_pacing, preflight_recipe
from engine.qa.gates import FAIL, PASS, UNCERTAIN
from engine.qa.preflight_segments import pieces
from engine.qa.review_model import build_model

PRE, _ = preflight_recipe.load_recipe()


def cards_config(durations: list[int], *, starts: list[int] | None = None, plate: int | None = None, **extra) -> dict:
    starts = starts or [100 + sum(durations[:i]) for i in range(len(durations))]
    cards = [{"term": f"Term{i}", "start_frame": s, "duration_frames": d} for i, (s, d) in enumerate(zip(starts, durations))]
    end = starts[-1] + durations[-1]
    ending = {"logo_still_frames": 66, "end_plate": {"start": end if plate is None else plate}}
    config = make_config([{"boundary": 5, "type": "none", "frames": 0}], outro_cards=cards, main_frames=end + 74,
                         end_hold_frames=60, motion={"transitions": [{"boundary": 5, "type": "none", "frames": 0}], "ending": ending},
                         total_frames_with_endlogo=end + 74 + 60)
    config["dialogue"][0]["end_frame_exclusive"] = 50
    config["dialogue"][1].update(start_frame=50, end_frame_exclusive=100)
    config.update(extra)
    return config


def pace(config: dict, **kw) -> dict:
    return preflight_pacing.run(config, build_model(config, recipe()), recipe(), pieces(config, Path(".")), **kw)


def test_well_formed_config_passes() -> None:
    result = pace(cards_config([90, 90, 90]))
    assert result["status"] == PASS, result["failures"]


@pytest.mark.parametrize("durations", [[24, 90, 90], [90, 89, 90]])
def test_a_card_under_90_frames_is_refused(durations: list[int]) -> None:
    result = pace(cards_config(durations))
    assert result["status"] == FAIL and any("card_length_every_card" in f and "< 90" in f for f in result["failures"])


def test_declared_90_but_the_start_frames_imply_24_is_refused() -> None:
    """The audit hole: a floor that only looks at the DECLARED length."""
    config = cards_config([90, 90, 90], starts=[100, 124, 214])
    result = pace(config)
    text = " ".join(result["failures"])
    assert result["status"] == FAIL and "derived 24" in text and "next start implies 24" in text


def test_the_config_may_raise_the_floor_but_never_lower_it() -> None:
    config = cards_config([90, 90, 90])
    config["motion"]["ending"]["card_min_frames"] = 120
    assert pace(config)["status"] == FAIL
    config["motion"]["ending"]["card_min_frames"] = 1  # the build-side hole: a low declared floor must not win
    config["outro_cards"][0]["duration_frames"] = 24
    assert pace(config)["status"] == FAIL


def test_logo_still_under_60_frames_is_refused() -> None:
    config = cards_config([90, 90])
    config["motion"]["ending"]["logo_still_frames"] = 13
    assert pace(config)["status"] == FAIL


def test_total_frames_must_equal_the_contract() -> None:
    config = cards_config([90, 90])
    total = config["total_frames_with_endlogo"]
    assert pace(config, explicit=total)["status"] == PASS
    result = pace(config, explicit=total + 60)
    assert result["status"] == FAIL and any("contract_frames" in f for f in result["failures"])
    assert pace({**config}, contract={"master": {"frames": total}})["status"] == PASS
    assert pace(config, contract={"master": {"frames": total - 1}})["status"] == FAIL
    with pytest.raises(Refused):
        pace(config, explicit=total, contract={"master": {"frames": total + 1}})


def test_no_contract_is_reported_as_a_warning_not_hidden() -> None:
    assert "no contract frame count" in pace(cards_config([90, 90]))["warnings"][0]


def test_contract_sections_are_compared_with_the_config() -> None:
    config = cards_config([90, 90])
    contract = {"master": {"frames": config["total_frames_with_endlogo"]}, "sections": [
        {"id": "S01_A", "kind": "dialogue", "frames": 50}, {"id": "S01_B", "kind": "dialogue", "frames": 50},
        {"id": "CARD_01", "kind": "vocab_card", "frames": 90}, {"id": "CARD_02", "kind": "vocab_card", "frames": 90},
        {"id": "END_CARD", "kind": "end_card", "frames": 60}]}
    assert pace(config, contract=contract)["status"] == PASS
    contract["sections"][1]["frames"] = 75
    result = pace(config, contract=contract)
    assert result["status"] == FAIL and any("contract_sections" in f for f in result["failures"])


# ---- audio ---------------------------------------------------------------------------------
def write(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def music(tmp_path: Path, status: str, *, bad_hash: bool = False) -> Path:
    stem = tmp_path / "bed.wav"
    stem.write_bytes(b"RIFFdata")
    import hashlib
    digest = "0" * 64 if bad_hash else hashlib.sha256(stem.read_bytes()).hexdigest()
    return write(tmp_path / "music-finalize.json", {"stem": {"path": "bed.wav", "sha256": digest, "vocal_gate": {"status": status}}})


def audio(config: dict | None = None, **kw) -> dict:
    base = dict(music_path=None, mix_path=None, with_sfx=False, allow_ungated=False, require=False, speech_start_s=3.0)
    return preflight_audio.run(config or {}, copy.deepcopy(PRE), **{**base, **kw})


def test_music_receipt_needs_a_passing_vocal_gate(tmp_path: Path) -> None:
    assert audio(music_path=music(tmp_path, "PASS"))["status"] == PASS
    for status in ("NOT_RUN", "FAIL", "ERROR"):
        result = audio(music_path=music(tmp_path, status))
        assert result["status"] == FAIL and status in result["failures"][0]
    assert audio(music_path=music(tmp_path, "NOT_RUN"), allow_ungated=True)["status"] == PASS
    assert audio(music_path=music(tmp_path, "PASS", bad_hash=True))["status"] == FAIL


def mix(tmp_path: Path, **over) -> Path:
    doc = {"schema": "jjv/audio-mix/v1", "verdict": "PASS", "music": {"source": "receipt", "vocal_gate": "PASS"},
           "sfx": {"enabled": False}, "inputs": {"sfx": {"enabled": False}}, "brand_voice": None}
    doc.update(over)
    return write(tmp_path / "mix.json", doc)


def test_sfx_is_off_unless_the_film_opted_in(tmp_path: Path) -> None:
    on = mix(tmp_path, sfx={"enabled": True})
    result = audio(mix_path=on)
    assert result["status"] == FAIL and "did not opt in" in result["failures"][0]
    assert audio(mix_path=on, with_sfx=True)["status"] == PASS
    assert audio(mix_path=mix(tmp_path))["status"] == PASS


def test_a_mix_whose_music_bypassed_the_vocal_gate_fails(tmp_path: Path) -> None:
    result = audio(mix_path=mix(tmp_path, music={"source": "explicit WAV", "vocal_gate": "not applicable (explicit WAV)"}))
    assert result["status"] == FAIL and mix(tmp_path, verdict="UNGATED") and audio(mix_path=mix(tmp_path, verdict="UNGATED"))["status"] == FAIL


def test_brand_voice_must_end_before_the_first_speech(tmp_path: Path) -> None:
    assert audio(mix_path=mix(tmp_path, brand_voice={"end_s": 2.7}))["status"] == PASS
    result = audio(mix_path=mix(tmp_path, brand_voice={"end_s": 2.9}))
    assert result["status"] == FAIL and "guard" in result["failures"][0]
    with pytest.raises(Uncertain):
        audio(mix_path=mix(tmp_path, brand_voice={"end_s": 2.0}), speech_start_s=None)


def test_no_receipt_is_skipped_with_a_warning_and_uncertain_when_required() -> None:
    result = audio({"mix": {"music": {}}})
    assert result["status"] == "SKIPPED" and any("NOT checked" in w for w in result["warnings"])
    assert any("hand-built" in w for w in result["warnings"])
    assert audio(require=True)["status"] == UNCERTAIN


def test_wrong_receipt_schema_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refused):
        audio(mix_path=write(tmp_path / "x.json", {"schema": "other"}))


# ---- recipe + orchestrator guard ------------------------------------------------------------
def test_malformed_preflight_recipe_is_uncertain(tmp_path: Path) -> None:
    bad = copy.deepcopy(PRE)
    bad["transitions"]["same_framing_ncc_min_source"] = 7
    path = write(tmp_path / "r.json", bad)
    with pytest.raises(Uncertain):
        preflight_recipe.load_recipe(path)


def test_unknown_check_name_is_refused() -> None:
    with pytest.raises(Refused):
        preflight.run_preflight(config=cards_config([90]), config_sha256="x", root=Path("."), recipe=recipe(), recipe_sha256="x",
                                pre=copy.deepcopy(PRE), pre_sha256="x", timing_recipe=None, ffmpeg="ffmpeg", checks=("Q9",))


# ---- domain floors + episode contract total (read from the domain / rules.timeline_frames, not hard-coded) --------
def test_domain_floors_only_raise_the_recipe_floors() -> None:
    rec = recipe()
    out = preflight.apply_floors(rec, {"card_min": 100, "logo_hold_min": 50}, overrides := {})
    assert out["q5_pacing"]["card_min_frames"] == 100 and out["q5_pacing"]["logo_still_min_frames"] == 60  # 50 < 60 never lowers
    assert overrides == {"q5_pacing.card_min_frames": "domain"}


def test_a_domain_raised_card_floor_fails_a_90_frame_card() -> None:
    rec = preflight.apply_floors(recipe(), {"card_min": 100}, {})
    config = cards_config([90, 90])
    result = preflight_pacing.run(config, build_model(config, rec), rec, pieces(config, Path(".")))
    assert result["status"] == FAIL and "floor 100" in result["failures"][0]


def test_domain_ceilings_and_the_episode_total() -> None:
    config = cards_config([160, 90])
    limits = {"card_min": 90, "card_max": 150, "end_card_min": 60, "end_card_max": 60}
    result = pace(config, limits=limits)
    assert result["status"] == FAIL and any("domain_section_limits" in f and "> 150" in f for f in result["failures"])
    total = cards_config([90, 90])["total_frames_with_endlogo"]
    good = pace(cards_config([90, 90]), limits=limits, episode_total=total)
    assert good["status"] == PASS and good["contract_source"].startswith("episode contract")
    assert pace(cards_config([90, 90]), episode_total=total + 60)["status"] == FAIL
    disagree = pace(cards_config([90, 90]), contract={"master": {"frames": total}}, episode_total=total + 60)
    assert any("episode_vs_contract_file" in f for f in disagree["failures"])
