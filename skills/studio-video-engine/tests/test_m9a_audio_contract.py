"""M9a item c: the audio timeline refuses (a named error) a length or section layout that contradicts the episode contract."""

from __future__ import annotations

import copy
import json

import pytest

from engine.audio import sections, timeline
from engine.config import loader
from engine.core.errors import Refused

ROOT = loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom"
V014 = ROOT / "editorial" / "review-hd-v014" / "config" / "review-config-v014.json"
RATE = 48000


@pytest.fixture(scope="module")
def config():
    return loader.resolve_episode("04-milk-and-mom")


@pytest.fixture()
def review() -> dict:
    return json.loads(V014.read_text("utf-8-sig"))


def test_the_named_error_is_a_refusal() -> None:
    assert issubclass(timeline.ContractMismatch, Refused)


def test_a_review_config_of_the_contract_length_resolves(config, review) -> None:
    assert timeline.resolve(config, review, RATE)["total_frames"] == 3444


def test_a_review_config_of_another_length_is_refused(config, review) -> None:
    review["total_frames_with_endlogo"] = 2520
    with pytest.raises(timeline.ContractMismatch, match="2520.*3444"):
        timeline.resolve(config, review, RATE)


def test_an_explicit_total_frames_override_is_refused_when_it_contradicts_the_contract(config) -> None:
    with pytest.raises(timeline.ContractMismatch, match="2520.*3444"):
        timeline.resolve(config, None, RATE, total_frames=2520)


def test_the_episode_without_a_contract_is_not_checked(config, review) -> None:
    episode = {k: v for k, v in config.episode.items() if k != "contract"}
    free = type(config)(**{**config.__dict__, "episode": episode}) if not hasattr(config, "__dataclass_fields__") else \
        __import__("dataclasses").replace(config, episode=episode)
    review["total_frames_with_endlogo"] = 2520
    assert timeline.resolve(free, review, RATE)["total_frames"] == 2520


def test_sections_that_match_the_contract_pass(config, review) -> None:
    line = timeline.resolve(config, review, RATE)
    timeline.check_sections(config, sections.derive_sections(review, line))


def test_a_section_that_starts_off_the_contract_is_refused(config, review) -> None:
    line = timeline.resolve(config, review, RATE)
    rows = copy.deepcopy(sections.derive_sections(review, line))
    next(r for r in rows if r["name"] == "outro_cards")["start_frame"] += 6
    with pytest.raises(timeline.ContractMismatch, match="outro_cards.*vocab_card"):
        timeline.check_sections(config, rows)


def test_a_dialogue_start_off_the_contract_is_refused(config, review) -> None:
    line = timeline.resolve(config, review, RATE)
    rows = copy.deepcopy(sections.derive_sections(review, line))
    next(r for r in rows if r["name"] == "dialogue")["start_frame"] = 96
    with pytest.raises(timeline.ContractMismatch, match="dialogue"):
        timeline.check_sections(config, rows)
