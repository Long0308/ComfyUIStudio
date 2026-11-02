"""Timeline = main film + optional end card; 2K deliverable; review size (user decision 2026-10-27).

The domain no longer fixes a film length: ``delivery.length`` is a min/max range for the MAIN film and
the episode's hashed contract carries the real length.  A domain must explicitly allow an end card
(``delivery.end_card.frames_min/frames_max``); an episode may only use it, never grant it to itself
(M2 no-loosening).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config_fixtures import REAL_EPISODE_ENGINE, make_live_action_world, make_world
from engine.config import loader, rules

CARTOON = "jenniejoy_cartoon_3d"
LIVE = "newtecons_live_action"


def _build(world):
    return loader.build_config(world.episode_file, skill_root=world.skill_root,
                               machine_path=world.machine_path)


def _expect(world, text: str) -> None:
    report = _build(world)
    assert any(text in problem for problem in report.violations), report.violations
    assert report.config is None


def _domain(world, change) -> None:
    world.edit(world.data(f"domains/{CARTOON}.json"), change)


def _timeline(world, **values) -> None:
    world.edit_episode(lambda d: d["timeline"].update(values))


# ---- the real data ----------------------------------------------------------------------
def test_real_cartoon_domain_states_main_film_end_card_2k_and_1080p_review() -> None:
    domain = json.loads((loader.SKILL_ROOT / "domains" / f"{CARTOON}.json").read_text("utf-8"))
    delivery = domain["delivery"]
    assert delivery["master"] == {"width": 3840, "height": 2160, "fps": 30}  # size and rate only
    assert delivery["length"] == {"main_frames_min": 600, "main_frames_max": 5400}
    assert delivery["end_card"] == {"frames_min": 60, "frames_max": 60}
    assert delivery["review"] == {"width": 1920, "height": 1080,
                                  "label": "REVIEW 1080p · native upscaled"}
    assert delivery["film_2k"] == {"width": 2560, "height": 1440, "method": "lanczos",
                                   "source": "master"}


def test_real_ep04_has_a_two_second_end_card_and_totals_3444_frames() -> None:
    config = loader.build_config(REAL_EPISODE_ENGINE / "episode.json").config
    assert config is not None
    line = config.episode["timeline"]
    assert (line["end_card_s"], line["end_card_frames"]) == (2.0, 60)
    assert round(line["intro_s"] + line["dialogue_s"] + line["outro_s"], 6) == 112.8
    totals = rules.timeline_frames(config.episode, config.domain)
    assert totals == {"main_frames": 3384, "end_card_frames": 60, "total_frames": 3444,
                      "total_s": 114.8}


def test_second_domain_semantics_are_unchanged() -> None:
    live = json.loads((loader.SKILL_ROOT / "domains" / f"{LIVE}.json").read_text("utf-8"))
    # `assemble` (the opt-in master assembler gate, 2026-11-01) is checked by tests/assemble; the rest stays pinned here.
    assert {k: v for k, v in live["delivery"].items() if k != "assemble"} == {
        "master": {"width": 1920, "height": 1080, "fps": 24},
        "length": {"main_frames_min": 240, "main_frames_max": 4320},
        "review": {"width": 1280, "height": 720},
        "sections": {
            "pause_native": {"min": 6, "max": 24},
            "logo_hold": {"min": 48, "max": 96},
            "vocab_card": {"min": 72, "max": 120},
            "end_plate": {"lead_min": 10, "tail_min": 10, "max": 120},
        },
    }


# ---- end-card arithmetic ----------------------------------------------------------------
def test_totals_without_an_end_card_equal_the_main_film(tmp_path: Path) -> None:
    world = make_live_action_world(tmp_path)
    config = _build(world).config
    assert config is not None
    assert rules.timeline_frames(config.episode, config.domain) == {
        "main_frames": 1080, "end_card_frames": 0, "total_frames": 1080, "total_s": 45.0}


def test_zero_end_card_is_the_same_as_none(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    _timeline(world, end_card_s=0, end_card_frames=0)
    assert _build(world).violations == ()
    world = make_live_action_world(tmp_path / "live")
    _timeline(world, end_card_s=0, end_card_frames=0)
    assert _build(world).violations == ()


def test_main_film_must_stay_inside_the_domain_length_range(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    _timeline(world, outro_s=11.0)  # 83 s is a different film from 84 s but both are inside the range
    assert _build(world).violations == ()
    _timeline(world, outro_s=200.0)
    _expect(world, "episode.timeline main film 8160 frames is outside the domain range 600..5400")


def test_end_card_seconds_and_frames_must_be_given_together(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.edit_episode(lambda d: d["timeline"].pop("end_card_frames"))
    _expect(world, "end_card_s and end_card_frames must be given together")
    world = make_world(tmp_path / "b")
    world.edit_episode(lambda d: d["timeline"].pop("end_card_s"))
    _expect(world, "end_card_s and end_card_frames must be given together")


def test_end_card_frames_must_match_seconds_at_delivery_fps(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    _timeline(world, end_card_frames=59)
    _expect(world, "end_card_frames 59 != end_card_s*delivery_fps 60")


def test_end_card_beyond_the_domain_allowance_is_refused(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    _timeline(world, end_card_s=2.5, end_card_frames=75)
    _expect(world, "end card 75 frames is outside the domain end_card range 60..60")


def test_end_card_without_a_domain_allowance_is_refused(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    _domain(world, lambda d: d["delivery"].pop("end_card"))
    _expect(world, "declares an end card but the domain delivery has no end_card allowance")


def test_live_action_domain_does_not_allow_an_end_card(tmp_path: Path) -> None:
    world = make_live_action_world(tmp_path)
    _timeline(world, end_card_s=2.0, end_card_frames=48)
    _expect(world, "declares an end card but the domain delivery has no end_card allowance")


def test_negative_or_non_integer_end_card_values_are_schema_errors(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    _timeline(world, end_card_s=-1)
    _expect(world, "end_card_s")
    _timeline(world, end_card_s=2.0, end_card_frames=60.5)
    _expect(world, "end_card_frames")


# ---- no loosening -----------------------------------------------------------------------
def test_episode_cannot_raise_the_domain_end_card_allowance(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.edit_episode(lambda d: d["overrides"].update({"domain.delivery.end_card.frames_max": 120}))
    _expect(world, "override 'domain.delivery.end_card.frames_max'")


def test_episode_cannot_grant_itself_an_end_card_on_a_domain_without_one(tmp_path: Path) -> None:
    world = make_live_action_world(tmp_path)
    world.edit_episode(lambda d: d["overrides"].update({"domain.delivery.end_card.frames_max": 48}))
    _expect(world, "override 'domain.delivery.end_card.frames_max': no such key")


@pytest.mark.parametrize("key,value", [
    ("domain.delivery.review.width", 2560),
    ("domain.delivery.review.height", 1440),
    ("domain.delivery.film_2k.width", 1920),
    ("domain.delivery.film_2k.method", "bicubic"),
])
def test_episode_cannot_change_review_or_2k_deliverable(tmp_path: Path, key: str, value) -> None:
    world = make_world(tmp_path)
    world.edit_episode(lambda d: d["overrides"].update({key: value}))
    _expect(world, f"override {key!r}")


def test_episode_may_restate_the_new_delivery_values(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.edit_episode(lambda d: d["overrides"].update({
        "domain.delivery.end_card.frames_max": 60, "domain.delivery.review.width": 1920,
        "domain.delivery.film_2k.height": 1440}))
    assert _build(world).violations == ()


# ---- domain arithmetic for the 2K deliverable -------------------------------------------
def test_film_2k_must_keep_the_master_aspect_and_be_smaller(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    _domain(world, lambda d: d["delivery"]["film_2k"].update(height=1200))
    _expect(world, "delivery.film_2k must keep the master aspect ratio")
    _domain(world, lambda d: d["delivery"]["film_2k"].update(width=3840, height=2160))
    _expect(world, "delivery.film_2k must be smaller than the master")


def test_film_2k_method_and_source_are_closed_sets(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    _domain(world, lambda d: d["delivery"]["film_2k"].update(method="nearest"))
    _expect(world, "film_2k.method")
    _domain(world, lambda d: d["delivery"]["film_2k"].update(method="lanczos", source="review"))
    _expect(world, "film_2k.source")
