"""Allow-list cho timing recipe va music-pick recipe: danh sach rong = TU CHOI (khong phai cho phep het)."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from engine.audio import musicpick
from engine.config.loader import SKILL_ROOT
from engine.config.schema import validate
from engine.core.errors import Refused
from engine.core.io import read_json
from engine.timing.recipe import resolve_recipe

SCHEMA = read_json(SKILL_ROOT / "schemas" / "domain.schema.json")
CARTOON = read_json(SKILL_ROOT / "domains" / "jenniejoy_cartoon_3d.json")
NEUTRAL = read_json(SKILL_ROOT / "domains" / "newtecons_live_action.json")
CARTOON_TIMING = ["timing/words-onset-v001", "timing/words-onset-v002", "timing/words-onset-v003"]
PICK = "audio/music-pick-v001"
MISSING_TIMING = "domain 'jenniejoy_cartoon_3d' is missing timing.allowed_recipes; timing is disabled"
INVALID_TIMING = "domain 'jenniejoy_cartoon_3d' has invalid timing.allowed_recipes; expected unique timing/<name> IDs"
MISSING_AUDIO = "domain 'jenniejoy_cartoon_3d' is missing audio.allowed_recipes; music pick is disabled"
INVALID_AUDIO = "domain 'jenniejoy_cartoon_3d' has invalid audio.allowed_recipes; expected unique audio recipe IDs"


def cfg(domain: dict, episode: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(domain=copy.deepcopy(domain), episode=episode or {})


def cartoon_with(**changes) -> dict:
    """Cartoon domain with keys replaced; a value of the sentinel string '<drop>' removes the key."""
    domain = copy.deepcopy(CARTOON)
    for key, value in changes.items():
        if value == "<drop>":
            domain.pop(key, None)
        else:
            domain[key] = value
    return domain


# ---- schema ----------------------------------------------------------------------------------------------------
def test_both_real_domains_validate_and_carry_the_right_lists() -> None:
    assert validate(CARTOON, SCHEMA, label="domain") == []
    assert validate(NEUTRAL, SCHEMA, label="domain") == []
    # 2026-10-31: user duyet phu de/karaoke NEWTECONS vao engine -> dung MOT recipe timing cua domain live-action;
    # 2026-10-31 (sau): user duyet nhac/SFX vao engine -> 4 recipe audio NEWTECONS rieng (spec audio-timing-recipes-v003,
    # khong tham chieu recipe JennieJoy; SFX default_enabled=false cho toi khi user chot).
    assert NEUTRAL["timing"]["allowed_recipes"] == ["timing/ntc-vi-words-v001"]
    assert NEUTRAL["audio"]["allowed_recipes"] == ["audio/music-pick-ntc-v001", "audio/ntc-instrumental-v001",
                                                   "audio/ntc-site-sfx-v001", "audio/ntc-mix-cinema-multitrack-v001"]
    assert not set(NEUTRAL["audio"]["allowed_recipes"]) & set(CARTOON["audio"]["allowed_recipes"])
    # 2026-10-31 user: "sfx bat va co the thay doi trong workflow video" -> ONLY the live-action domain grants SFX default-on.
    assert NEUTRAL["audio"]["sfx_default_on"] is True and "sfx_default_on" not in CARTOON["audio"]
    assert validate({**NEUTRAL, "audio": {**NEUTRAL["audio"], "sfx_default_on": "yes"}}, SCHEMA, label="domain") != []
    assert CARTOON["timing"]["allowed_recipes"] == CARTOON_TIMING
    assert PICK in CARTOON["audio"]["allowed_recipes"]


@pytest.mark.parametrize("block", [None, {}, {"allowed_recipes": None}, {"allowed_recipes": "timing/x"},
                                   {"allowed_recipes": ["timing/a", "timing/a"]}, {"allowed_recipes": [1]},
                                   {"allowed_recipes": ["audio/x"]}, {"allowed_recipes": [], "extra": 1}])
def test_schema_rejects_malformed_timing_block(block) -> None:
    assert validate({**CARTOON, "timing": block}, SCHEMA, label="domain") != []


# ---- timing ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("explicit,episode", [("timing/words-onset-v003", {}), (None, {}),
                                              (None, {"timing": {"recipe": "timing/words-onset-v003"}})])
def test_empty_timing_list_refuses_every_origin(explicit, episode) -> None:
    domain = cartoon_with(timing={"allowed_recipes": []})
    with pytest.raises(Refused) as caught:
        resolve_recipe(cfg(domain, episode), explicit)
    assert str(caught.value) == ("domain 'jenniejoy_cartoon_3d' does not list timing recipe "
                                 "'timing/words-onset-v003' in timing.allowed_recipes")


def test_unknown_recipe_refused_and_default_never_switches_silently() -> None:
    domain = cartoon_with(timing={"allowed_recipes": ["timing/words-onset-v001"]})
    with pytest.raises(Refused, match="does not list timing recipe 'timing/words-onset-v003'"):
        resolve_recipe(cfg(domain), None)
    with pytest.raises(Refused, match="does not list timing recipe 'timing/words-onset-v002'"):
        resolve_recipe(cfg(domain), "timing/words-onset-v002")


def test_missing_or_invalid_timing_block() -> None:
    with pytest.raises(Refused) as caught:
        resolve_recipe(cfg(cartoon_with(timing="<drop>")), None)
    assert str(caught.value) == MISSING_TIMING
    cases = ((cartoon_with(timing={}), MISSING_TIMING), (cartoon_with(timing="nope"), INVALID_TIMING))
    cases += tuple((cartoon_with(timing={"allowed_recipes": bad}), INVALID_TIMING)
                   for bad in ("x", None, ["timing/a", "timing/a"], ["audio/x"], [3]))
    for domain, text in cases:
        with pytest.raises(Refused) as caught:
            resolve_recipe(cfg(domain), None)
        assert str(caught.value) == text


def test_cartoon_still_resolves_all_its_timing_recipes() -> None:
    config = cfg(CARTOON)
    recipe, origin = resolve_recipe(config, None)
    assert (recipe.recipe_id, origin) == ("timing/words-onset-v003", "default recipe for the domain")
    for recipe_id in CARTOON_TIMING:
        assert resolve_recipe(config, recipe_id)[0].recipe_id == recipe_id


def test_listed_recipe_of_another_domain_still_fails_the_domain_check() -> None:
    domain = {**copy.deepcopy(NEUTRAL), "timing": {"allowed_recipes": ["timing/words-onset-v003"]}}
    with pytest.raises(Refused, match="belongs to domain 'jenniejoy_cartoon_3d'"):
        resolve_recipe(cfg(domain), "timing/words-onset-v003")


def test_neutral_domain_timing_is_refused_with_a_clear_message() -> None:
    with pytest.raises(Refused, match="does not list timing recipe 'timing/words-onset-v003'"):
        resolve_recipe(cfg(NEUTRAL), "timing/words-onset-v003")


def test_other_lists_never_authorize_timing() -> None:
    domain = cartoon_with(timing={"allowed_recipes": []}, allowed_recipes=["timing/words-onset-v003"])
    with pytest.raises(Refused, match="timing.allowed_recipes"):
        resolve_recipe(cfg(domain), "timing/words-onset-v003")


# ---- music pick ------------------------------------------------------------------------------------------------
def test_pick_denied_when_audio_list_is_empty_or_lacks_it() -> None:
    for allowed in ([], ["audio/mix-cinema-v001"]):
        for explicit in (None, PICK):
            with pytest.raises(Refused) as caught:
                musicpick.load_pick_recipe(cfg(cartoon_with(audio={"allowed_recipes": allowed})), explicit)
            assert str(caught.value) == ("domain 'jenniejoy_cartoon_3d' does not list music-pick recipe "
                                         "'audio/music-pick-v001' in audio.allowed_recipes")


def test_pick_missing_or_invalid_audio_list() -> None:
    cases = [(cartoon_with(audio="<drop>"), MISSING_AUDIO), (cartoon_with(audio={}), MISSING_AUDIO),
             (cartoon_with(audio=7), INVALID_AUDIO)]
    cases += [(cartoon_with(audio={"allowed_recipes": bad}), INVALID_AUDIO)
              for bad in (None, "x", [PICK, PICK], ["voice/x"], [5])]
    for domain, text in cases:
        with pytest.raises(Refused) as caught:
            musicpick.load_pick_recipe(cfg(domain))
        assert str(caught.value) == text


def test_cartoon_pick_default_and_explicit_load_the_same_recipe() -> None:
    first = musicpick.load_pick_recipe(cfg(CARTOON))
    second = musicpick.load_pick_recipe(cfg(CARTOON), PICK)
    assert first.recipe_id == PICK and first.sha256 == second.sha256


def test_neutral_domain_pick_is_refused_default_and_explicit() -> None:
    for explicit in (None, PICK):
        with pytest.raises(Refused, match="does not list music-pick recipe"):
            musicpick.load_pick_recipe(cfg(NEUTRAL), explicit)
