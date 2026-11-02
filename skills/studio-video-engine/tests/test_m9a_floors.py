"""M9a item a: the end-card / derive floors come from the episode domain, never from literals in the engine."""

from __future__ import annotations

import copy
import dataclasses

import pytest

from editorial_fixtures import Inputs
from engine.core.errors import Refused
from engine.editorial import derive, end_card
from test_editorial_ending_params import DIALOGUE_END, _derive


def _with_floors(inputs: Inputs, *, card: int | None = None, hold: int | None = None, plate: int | None = None) -> Inputs:
    domain = copy.deepcopy(inputs.config.domain)
    sections = domain["delivery"]["sections"]
    if card is not None:
        sections["vocab_card"]["min"] = card
    if hold is not None:
        sections["logo_hold"]["min"] = hold
    if plate is not None:
        domain["delivery"]["end_card"]["frames_min"] = plate
    return inputs.with_config(domain=domain)


def test_the_engine_keeps_no_floor_literals() -> None:
    assert not hasattr(end_card, "CARD_MIN_FLOOR") and not hasattr(derive, "DEFAULT_CARD_MIN_FRAMES")
    assert not hasattr(derive, "DEFAULT_LOGO_HOLD_FRAMES") and not hasattr(end_card, "LOGO_HOLD_MIN")


def test_default_card_length_is_the_domain_vocab_card_floor(tmp_path) -> None:
    built = _derive(_with_floors(Inputs(tmp_path), card=100)).build()
    assert [c["duration_frames"] for c in built.config["outro_cards"]] == [100] * 12


def test_default_logo_hold_is_the_domain_logo_hold_floor(tmp_path) -> None:
    built = _derive(_with_floors(Inputs(tmp_path), hold=70)).build()
    assert built.config["outro_cards"][0]["start_frame"] == DIALOGUE_END + 70


def test_a_declared_card_min_below_the_domain_floor_is_refused(tmp_path) -> None:
    inputs = _with_floors(Inputs(tmp_path), card=100)
    inputs.boundaries["ending"]["card_min_frames"] = 95   # the old literal floor (90) would accept it
    with pytest.raises(Refused, match=r"card_min_frames.*>= 100"):
        inputs.build()


def test_a_declared_end_card_below_the_domain_floor_is_refused(tmp_path) -> None:
    inputs = _with_floors(Inputs(tmp_path), plate=60)
    domain = copy.deepcopy(inputs.config.domain)
    domain["delivery"]["end_card"] = {"frames_min": 75, "frames_max": 90}
    inputs.with_config(domain=domain).boundaries["ending"]["end_card_frames"] = 70
    inputs.boundaries["ending"]["end_card_frames"] = 70
    with pytest.raises(Refused, match=r"end_card_frames.*>= 75"):
        inputs.build()


def test_a_domain_without_the_section_refuses_derive_with_a_named_error(tmp_path) -> None:
    inputs = Inputs(tmp_path)
    domain = copy.deepcopy(inputs.config.domain)
    del domain["delivery"]["sections"]["vocab_card"]
    with pytest.raises(Refused, match=r"domain jenniejoy_cartoon_3d.*vocab_card"):
        _derive(inputs.with_config(domain=domain)).build()
