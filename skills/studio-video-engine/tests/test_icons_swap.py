"""Icon swap as data (T-E44): new registry version, old kept, nothing else touched, re-composite list."""

from __future__ import annotations

import json

import pytest

from engine.core.errors import Refused
from engine.editorial import icons as reg
from engine.editorial import icons_swap as swap
from engine.editorial import segments as seg
from test_icons_support import COLD, FFMPEG, REAL_EP, World, needs_ffmpeg, needs_real_ep, write_png

pytestmark = needs_ffmpeg
BLUE2 = (30, 90, 230)


def do_set(world: World, registry: dict, key: str, png, **kw):
    return swap.set_icon(registry, key, png, root=world.root, recipe=world.recipe, recipe_sha=world.recipe_sha,
                         ffmpeg=FFMPEG, **kw)


def test_set_writes_a_new_version_and_keeps_the_old_data(tmp_path):
    world = World(tmp_path)
    one = world.registry()
    new, change = do_set(world, one, "cold", world.new_png("cold-2.png", BLUE2, "square"))
    assert new["version"] == 2 and new["previous"] == {"version": 1, "sha256": one["sha256"]}
    assert new["icons"]["cold"]["png"] == "assets/swap/cold-2.png" and new["icons"]["cold"]["status"] == "candidate"
    assert one["icons"]["cold"]["png"] == "assets/vocab-v1/png/cold.png"          # version 1 is untouched
    assert {k: v for k, v in new["icons"].items() if k != "cold"} == {k: v for k, v in one["icons"].items() if k != "cold"}
    assert new["terms"] == one["terms"] and new["cards"] == one["cards"]
    assert new["history"][-1]["old"]["sha256"] == one["icons"]["cold"]["sha256"]
    assert change["words"] == ["cold"] and change["cards"] == []
    assert new["sha256"] == reg.registry_sha256(new)
    out = tmp_path / "reg"
    reg.write_registry(out, one)
    reg.write_registry(out, new)
    assert json.loads((out / "versions" / "icons-v001.json").read_text("utf-8"))["version"] == 1
    assert reg.load_registry(out / "icons.json")["version"] == 2


def test_set_resolves_icon_id_word_alias_and_card(tmp_path):
    world = World(tmp_path)
    one = world.registry()
    assert swap.resolve_icon_id(one, "farm") == "farm"
    assert swap.resolve_icon_id(one, "Green Farm") == "farm"
    assert swap.resolve_icon_id(one, "Warm and Cold") == "warm-cold"
    assert swap.resolve_icon_id(one, "warm-cold") == "warm-cold"
    with pytest.raises(Refused, match="no icon, spoken word or card"):
        swap.resolve_icon_id(one, "cheese")


def test_swap_that_breaks_the_gate_is_refused(tmp_path):
    world = World(tmp_path)
    one = world.registry()
    with pytest.raises(Refused, match="E_PAIR_SAME_IMAGE|E_DUP_IMAGE"):
        do_set(world, one, "cold", world.assets / "png" / "warm.png")                 # cold becomes the warm image
    with pytest.raises(Refused, match="E_PAIR_SHAPE"):
        do_set(world, one, "cold", world.new_png("cold-disc.png", COLD, "disc"))       # same shape as warm
    with pytest.raises(Refused, match="already uses"):
        do_set(world, one, "cold", world.assets / "png" / "cold.png")
    with pytest.raises(Refused, match="does not exist"):
        do_set(world, one, "cold", world.root / "nope.png")
    with pytest.raises(Refused, match="outside the episode"):
        do_set(world, one, "cold", write_png(tmp_path / "elsewhere.png", BLUE2, "square"))


def test_set_can_record_approval_and_a_new_attribute(tmp_path):
    world = World(tmp_path)
    one = world.registry()
    new, _ = do_set(world, one, "farm", world.new_png("farm-2.png", (20, 200, 90), "disc"), status="approved",
                    attribute="red barn with a white fence")
    assert new["icons"]["farm"]["status"] == "approved" and new["icons"]["farm"]["approved"] is True
    assert new["icons"]["farm"]["attribute"] == "red barn with a white fence"
    with pytest.raises(Refused, match="status must be"):
        do_set(world, one, "farm", world.new_png("farm-3.png", (1, 200, 90)), status="done")


EVENTS = [
    {"id": "IC01", "shot": "S01_A", "icon": "cold.png", "icon_path": "x/cold.png", "frame": 100, "total_frames": 32},
    {"id": "IC02", "shot": "S02_A", "icon": "warm.png", "icon_path": "x/warm.png", "frame": 200, "total_frames": 32},
    {"id": "IC03", "shot": "S09_A", "icon": "cold.png", "icon_path": "x/cold.png", "frame": 900, "total_frames": 32}]
SEGMENTS = {"segments": [{"id": "a", "start": 0, "end_exclusive": 150}, {"id": "b", "start": 150, "end_exclusive": 300},
                         {"id": "c", "start": 300, "end_exclusive": 880}, {"id": "d", "start": 880, "end_exclusive": 1000}]}


def test_affected_lists_only_the_segments_that_show_the_icon(tmp_path):
    world = World(tmp_path)
    old = world.registry()["icons"]["cold"]
    out = swap.affected(old, [], events=EVENTS, config=None, segments=SEGMENTS)
    assert [e["event"] for e in out["icon_events"]] == ["IC01", "IC03"]
    assert out["segments"] == ["a", "d"] and out["segments_total"] == 4 and out["shot_sources_changed"] is False
    assert out["composite_frames_hint"] == 64
    no_table = swap.affected(old, [], events=EVENTS, config=None, segments=None)
    assert no_table["segments"] is None and len(no_table["icon_events"]) == 2


def test_affected_includes_the_outro_card_of_a_swapped_card_icon(tmp_path):
    world = World(tmp_path)
    old = world.registry()["icons"]["warm-cold"]
    config = {"outro_cards": [{"term": "Creamy", "start_frame": 300, "duration_frames": 90},
                              {"term": "Warm and Cold", "start_frame": 390, "duration_frames": 90}]}
    segments = {"segments": [{"id": "c1", "start": 300, "end_exclusive": 390}, {"id": "c2", "start": 390, "end_exclusive": 480}]}
    out = swap.affected(old, ["Warm and Cold"], events=EVENTS, config=config, segments=segments)
    assert out["cards"] == [{"card": "Warm and Cold", "start": 390, "end_exclusive": 480}]
    assert out["segments"] == ["c2"] and out["icon_events"] == []


@needs_real_ep
def test_real_ep04_swap_touches_exactly_the_two_cold_shot_spans(tmp_path):
    config = json.loads((REAL_EP / "editorial" / "review-hd-v015" / "config" / "review-config-v015.json").read_text("utf-8"))
    events = json.loads((REAL_EP / "editorial" / "review-hd-v015" / "events-v015.json").read_text("utf-8"))
    table = swap.segments_from_review_config(config)
    seg.check(table)
    assert table["total_frames"] == 3444
    registry = reg.load_registry(REAL_EP / "technical" / "icons-registry-v001" / "icons.json")
    out = swap.affected(registry["icons"]["cold"], [], events=events["icon_events"], config=config, segments=table)
    assert [e["event"] for e in out["icon_events"]] == ["IC10", "IC12"]
    assert out["segments"] == ["shot-S04_A-1", "shot-S04_B-1"] and out["segments_total"] == len(table["segments"]) > 20
