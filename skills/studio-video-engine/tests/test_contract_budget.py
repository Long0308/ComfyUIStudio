"""The section budget: floors are never squeezed, speech is never stretched, refusals carry numbers."""

from __future__ import annotations

import json
import pytest

from engine.config.budget import BudgetRefused, allocate, build_sections, totals
from engine.config.loader import SKILL_ROOT

DOMAIN = json.loads((SKILL_ROOT / "domains" / "jenniejoy_cartoon_3d.json").read_text(encoding="utf-8"))
NATIVE_STEP = DOMAIN["frame_rates"]["mapping"]["den"]


def inputs(lines=(4.5,) * 6, vocab=(0.8,) * 4, end=1.6, intro=60, clips=None, pins=None) -> dict:
    rows = [{"id": f"S{i + 1:02d}_A", "wav_s": seconds, **({"clip_frames": clips[i]} if clips else {})}
            for i, seconds in enumerate(lines)]
    return {"intro_frames": intro, "lines": rows, "pins": pins or {},
            "vocab": [{"term": f"W{i}", "wav_s": s} for i, s in enumerate(vocab)],
            "end_line": {"wav_s": end}, "end_card": True}


def floor_and_ceiling(data: dict) -> tuple[int, int]:
    sections = build_sections(DOMAIN, data)
    return sum(s.low for s in sections), sum(s.high for s in sections)


def test_floors_are_the_default_allocation() -> None:
    data = inputs()
    sections = allocate(DOMAIN, data)
    assert all(s.frames == s.low for s in sections)
    assert totals(sections)["total_frames"] == floor_and_ceiling(data)[0]


def test_every_target_from_floor_to_ceiling_is_hit_exactly_and_never_leaves_a_range() -> None:
    data = inputs()
    low, high = floor_and_ceiling(data)
    for target in range(low, high + 1, 7):
        sections = allocate(DOMAIN, data, target_frames=target)
        assert totals(sections)["total_frames"] == target
        assert all(s.low <= s.frames <= s.high for s in sections), target
    assert totals(allocate(DOMAIN, data, target_frames=high))["total_frames"] == high


def test_planned_clips_are_whole_native_multiples_and_hold_the_speech_with_a_pause() -> None:
    data = inputs(lines=(3.17, 4.62, 5.01, 2.4))
    pause = DOMAIN["delivery"]["sections"]["pause_native"]
    low, high = floor_and_ceiling(data)
    for target in (low, (low + high) // 2, high):
        sections = [s for s in allocate(DOMAIN, data, target_frames=target) if s.kind == "dialogue"]
        for section, line in zip(sections, data["lines"]):
            clip = section.frames * NATIVE_STEP // DOMAIN["frame_rates"]["mapping"]["num"]
            speech = -(-round(line["wav_s"] * 24 * 1000) // 1000)
            assert clip % NATIVE_STEP == 0
            assert clip >= speech + pause["min"] and clip <= -(-(speech + pause["max"]) // NATIVE_STEP) * NATIVE_STEP


def test_extension_order_pauses_first_then_hold_then_cards_then_plate() -> None:
    data = inputs(lines=(4.5,) * 4)
    low, _ = floor_and_ceiling(data)
    pauses = sum(s.high - s.low for s in build_sections(DOMAIN, data) if s.kind == "dialogue")
    sections = allocate(DOMAIN, data, target_frames=low + pauses)
    assert all(s.frames == s.high for s in sections if s.kind == "dialogue")
    assert all(s.frames == s.low for s in sections if s.kind not in ("dialogue",))
    more = allocate(DOMAIN, data, target_frames=low + pauses + 10)
    assert next(s for s in more if s.kind == "logo_hold").frames == next(s for s in sections if s.kind == "logo_hold").frames + 10


def test_a_target_below_the_floors_is_refused_with_numbers_and_options() -> None:
    data = inputs()
    low, _ = floor_and_ceiling(data)
    with pytest.raises(BudgetRefused) as caught:
        allocate(DOMAIN, data, target_frames=low - 100)
    refusal = caught.value
    assert f"{low}" in str(refusal) and "short by 100" in str(refusal)
    drop = next(o for o in refusal.options if o["option"].startswith("drop"))
    assert drop["frames"] <= -100 and drop["sufficient"] is True
    assert drop["new_floor_total"] == low + drop["frames"]
    assert {row["id"] for row in refusal.table} >= {"INTRO", "LOGO_HOLD", "END_CARD"}


def test_the_options_say_when_a_way_out_is_not_enough() -> None:
    data = inputs(vocab=(0.8,))
    low, _ = floor_and_ceiling(data)
    with pytest.raises(BudgetRefused) as caught:
        allocate(DOMAIN, data, target_frames=low - 400)
    only = [o for o in caught.value.options if o["option"].startswith("drop")]
    assert only and only[0]["sufficient"] is False


def test_a_target_above_what_holds_can_reach_is_refused_never_stretched() -> None:
    data = inputs()
    _, high = floor_and_ceiling(data)
    with pytest.raises(BudgetRefused) as caught:
        allocate(DOMAIN, data, target_frames=high + 1)
    assert "never stretched" in str(caught.value)
    add = next(o for o in caught.value.options if o["option"] == "add vocab cards")
    assert add["frames"] == DOMAIN["delivery"]["sections"]["vocab_card"]["min"] and add["needed"] == 1


def test_a_range_picks_the_shortest_film_inside_it_and_refuses_an_impossible_one() -> None:
    data = inputs()
    low, _ = floor_and_ceiling(data)
    inside = allocate(DOMAIN, data, min_frames=low - 50, max_frames=low + 500)
    assert totals(inside)["total_frames"] == low
    raised = allocate(DOMAIN, data, min_frames=low + 40, max_frames=low + 500)
    assert totals(raised)["total_frames"] == low + 40
    with pytest.raises(BudgetRefused):
        allocate(DOMAIN, data, min_frames=10, max_frames=low - 1)


def test_existing_clips_are_fixed_and_must_hold_their_speech() -> None:
    fixed = inputs(lines=(4.0, 4.0), clips=(120, 120))
    sections = [s for s in allocate(DOMAIN, fixed) if s.kind == "dialogue"]
    assert [s.frames for s in sections] == [150, 150] and all(s.low == s.high for s in sections)
    with pytest.raises(Exception, match="multiple of 4"):
        build_sections(DOMAIN, inputs(lines=(4.0,), clips=(122,)))
    with pytest.raises(Exception, match="hold the WAV"):
        build_sections(DOMAIN, inputs(lines=(6.0,), clips=(120,)))


def test_pins_fix_a_hold_inside_its_range_and_unpinning_is_an_option() -> None:
    data = inputs(pins={"logo_hold": 70})
    assert next(s for s in build_sections(DOMAIN, data) if s.kind == "logo_hold").frames == 70
    with pytest.raises(Exception, match="outside the allowed"):
        build_sections(DOMAIN, inputs(pins={"logo_hold": 59}))
    low, _ = floor_and_ceiling(data)
    with pytest.raises(BudgetRefused) as caught:
        allocate(DOMAIN, data, target_frames=low - 5)
    unpin = next(o for o in caught.value.options if o["option"].startswith("unpin"))
    assert unpin["frames"] == -10


def test_card_minimum_comes_from_the_domain_and_a_long_word_lengthens_its_card() -> None:
    cards = [s for s in build_sections(DOMAIN, inputs(vocab=(0.5, 3.4))) if s.kind == "vocab_card"]
    assert cards[0].low == 90 and cards[1].low == 102 and cards[1].high >= cards[1].low


def test_floors_live_in_the_domain_file_not_in_code() -> None:
    sections = DOMAIN["delivery"]["sections"]
    assert sections["logo_hold"]["min"] >= 60 and sections["vocab_card"]["min"] >= 90
    assert DOMAIN["delivery"]["end_card"]["frames_min"] >= 60
    assert "duration_s" not in DOMAIN["delivery"]["master"] and "frames" not in DOMAIN["delivery"]["master"]


def test_a_long_existing_clip_offers_a_re_make_option_with_its_number_and_its_cost() -> None:
    data = inputs(lines=(3.0, 4.0), clips=(160, 120))  # 3.0 s of speech in a 6.67 s clip
    low, _ = floor_and_ceiling(data)
    with pytest.raises(BudgetRefused) as caught:
        allocate(DOMAIN, data, target_frames=low - 50)
    remake = next(o for o in caught.value.options if o["option"].startswith("re-make 2 existing"))
    assert remake["costs"] == "GPU re-render" and remake["frames"] == -((200 - 100) + (150 - 130))  # 160 -> floor 80 native; 120 -> floor 104 native
