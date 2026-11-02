"""Icon registry build (T-E44): terms/cards/icons from the asset manifest + script, determinism, lookups, IO."""

from __future__ import annotations

import json

import pytest

from engine.core.errors import Refused
from engine.editorial import icons as reg
from engine.editorial import icons_build as build
from test_icons_support import WARM, World, needs_ffmpeg, tampered

pytestmark = needs_ffmpeg


def test_build_binds_one_icon_per_spoken_word(tmp_path):
    registry = World(tmp_path).registry()
    assert set(registry["terms"]) == {"creamy", "warm", "cold", "farm"}
    assert registry["terms"]["warm"]["icon"] == "warm" and registry["terms"]["cold"]["icon"] == "cold"
    assert registry["cards"]["Warm and Cold"] == {"icon": "warm-cold", "spoken": ["warm", "cold"],
                                                  "phrases": ["warm or cold"]}
    assert registry["icons"]["warm-cold"]["kind"] == "card" and registry["icons"]["warm"]["kind"] == "spoken"
    assert registry["icons"]["warm"]["pair"] == "cold" and registry["icons"]["cold"]["pair"] == "warm"
    assert registry["icons"]["warm"]["palette"]["rgb"] == pytest.approx(list(WARM), abs=6.0)  # ffmpeg area-scaling bleeds edge pixels
    assert registry["terms"]["farm"]["aliases"] == ["green farm"]      # "farms" is the term itself
    assert registry["icons"]["farm"]["png"] == "assets/vocab-v1/png/farm.png"
    assert registry["icons"]["warm"]["status"] == "candidate" and registry["icons"]["warm"]["approved"] is False


def test_build_is_deterministic_and_sealed(tmp_path):
    world = World(tmp_path)
    a, b = world.registry(), world.registry()
    assert reg.pretty_json(a, mode="utf8") == reg.pretty_json(b, mode="utf8")
    assert a["sha256"] == reg.registry_sha256(a)


def test_compound_card_without_word_icons_shares_the_card_icon(tmp_path):
    world = World(tmp_path, per_word=False)
    registry = world.registry(allow_shared=("warm-cold",))
    assert registry["terms"]["warm"]["icon"] == registry["terms"]["cold"]["icon"] == "warm-cold"
    assert registry["icons"]["warm-cold"]["shared"] is True
    assert registry["icons"]["warm-cold"]["pair"] is None      # an icon cannot be its own opposite


def test_unknown_allow_shared_and_bad_manifest_are_refused(tmp_path):
    world = World(tmp_path)
    with pytest.raises(Refused, match="allow-shared"):
        world.registry(allow_shared=("nope",))
    (world.assets / "png" / "farm.png").write_bytes(b"changed")
    with pytest.raises(Refused, match="differs from the manifest sha256"):
        world.registry()


def test_card_icon_missing_from_manifest_is_refused(tmp_path):
    world = World(tmp_path)
    world.script["vocabulary_cards"][2]["icon"] = "ghost"
    world.write_script()
    with pytest.raises(Refused, match="ghost"):
        world.registry()


def test_spoken_term_in_two_cards_is_refused(tmp_path):
    world = World(tmp_path)
    world.script["vocabulary_cards"].append({"term": "Farm", "icon": "farm", "ipa": "x", "vi": "y", "example_en": "z"})
    world.write_script()
    with pytest.raises(Refused, match="two vocabulary cards"):
        world.registry()


def test_lookups_resolve_terms_aliases_and_cards(tmp_path):
    registry = World(tmp_path).registry()
    assert reg.icon_for_word(registry, "Farm")["id"] == "farm"
    assert reg.icon_for_word(registry, "green farm")["id"] == "farm"
    assert reg.icon_for_word(registry, "COLD")["id"] == "cold"
    assert reg.icon_for_word(registry, "table") is None
    assert reg.icon_for_card(registry, "Warm and Cold")["id"] == "warm-cold"
    with pytest.raises(Refused, match="no card"):
        reg.icon_for_card(registry, "Cheese")
    assert reg.icon_ref(registry["icons"]["farm"]) == {"path": "assets/vocab-v1/png/farm.png",
                                                       "sha256": registry["icons"]["farm"]["sha256"]}


def test_load_registry_detects_a_hand_edit(tmp_path):
    registry = World(tmp_path).registry()
    path = tmp_path / "icons.json"
    path.write_bytes(reg.pretty_json(registry, mode="utf8"))
    assert reg.load_registry(path)["sha256"] == registry["sha256"]
    edited = json.loads(path.read_text("utf-8"))
    edited["icons"]["farm"]["status"] = "approved"
    path.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(Refused, match="hand-edited"):
        reg.load_registry(path)


def test_write_registry_keeps_every_version_and_refuses_overwrite(tmp_path):
    world = World(tmp_path)
    one = world.registry()
    out = tmp_path / "out"
    reg.write_registry(out, one)
    reg.write_registry(out, one)                                 # idempotent
    assert (out / "icons.json").read_bytes() == (out / "versions" / "icons-v001.json").read_bytes()
    other = tampered(one, lambda r: r["icons"]["farm"].update(status="approved"))
    with pytest.raises(Refused, match="refusing to overwrite"):
        reg.write_registry(out, other)
    two = tampered(one, lambda r: r.update(version=2, previous={"version": 1, "sha256": one["sha256"]}))
    reg.write_registry(out, two)
    assert json.loads((out / "icons.json").read_text("utf-8"))["version"] == 2
    assert (out / "versions" / "icons-v001.json").is_file()      # the old version stays
    three = tampered(one, lambda r: r.update(version=4, previous={"version": 3, "sha256": "0"}))
    with pytest.raises(Refused, match="derived from"):
        reg.write_registry(out, three)


def test_plan_terms_is_pure_and_matches_build(tmp_path):
    world = World(tmp_path)
    registry = world.registry()
    terms, cards = build.plan_terms(world.script["vocabulary_cards"], set(registry["icons"]),
                                    world.recipe["compound_separators"])
    assert {k: v["icon"] for k, v in terms.items()} == {k: v["icon"] for k, v in registry["terms"].items()}
    assert cards == registry["cards"]


def test_load_attributes_merges_files_and_prompt_documents(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"icons": [{"id": "farm", "prompt": " red barn "}, {"id": "x"}]}))
    (tmp_path / "b.json").write_text(json.dumps({"farm": "green barn", "cold": "ice"}))
    assert build.load_attributes(tmp_path / "a.json") == {"farm": "red barn"}
    assert build.load_attributes(tmp_path / "a.json", tmp_path / "b.json", None) == {"farm": "green barn", "cold": "ice"}
    (tmp_path / "c.json").write_text("[1]")
    with pytest.raises(Refused):
        build.load_attributes(tmp_path / "c.json")


def test_recipe_thresholds_equal_the_review_gate_q2_values():
    """The registry gate and QA gate Q2 must not drift apart: same numbers, one recipe each."""
    q2 = json.loads((reg.SKILL_ROOT / "recipes" / "qa" / "review-gates-v001.json").read_text("utf-8"))["q2_icons"]
    mine = reg.load_recipe()[0]
    for key in ("alpha_min", "min_delta_e_file", "min_hue_distance_deg", "hue_min_saturation", "opposite_pairs"):
        assert mine[key] == q2[key], key
