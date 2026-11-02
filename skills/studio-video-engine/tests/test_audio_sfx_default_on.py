"""NEWTECONS mixes default SFX ON (user 2026-10-31); JennieJoy stays OFF; a per-episode override can switch it off."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from audio_fixtures import recipe_of, write_tone
from test_audio_mix_run import episode, make_args, run  # noqa: F401  (episode is a fixture)

from engine.audio import mix, mixcli
from engine.audio.limits import cinema_problems
from engine.audio.recipe import load_recipe, resolve_recipe
from engine.core.errors import Refused
from engine.voice.wavio import read_wav

NTC = "audio/ntc-mix-cinema-multitrack-v001"
CARTOON = "audio/mix-cinema-v001"
SKILL = Path(__file__).resolve().parents[1]
NTC_DOMAIN = json.loads((SKILL / "domains" / "newtecons_live_action.json").read_text("utf-8"))
CARTOON_DOMAIN = json.loads((SKILL / "domains" / "jenniejoy_cartoon_3d.json").read_text("utf-8"))


def test_only_the_newtecons_domain_grants_sfx_default_on() -> None:
    assert NTC_DOMAIN["audio"]["sfx_default_on"] is True
    assert "sfx_default_on" not in CARTOON_DOMAIN["audio"]   # JennieJoy domain file is untouched: default false


def test_newtecons_recipe_defaults_sfx_on_when_its_domain_allows_it() -> None:
    config = SimpleNamespace(domain=NTC_DOMAIN, episode={})
    recipe, _ = resolve_recipe(config, "audio-mix", NTC)
    assert recipe.data["domain"] == "newtecons_live_action" and recipe.data["sfx"]["default_enabled"] is True
    assert cinema_problems(recipe.data, sfx_default_on_allowed=True) == []
    with pytest.raises(Refused, match="sfx.default_enabled"):          # no domain given: no permission
        load_recipe(NTC, "audio-mix")


def test_a_jenniejoy_recipe_cannot_turn_itself_on_with_decision_text(tmp_path) -> None:
    root = tmp_path / "skill"
    (root / "recipes" / "audio").mkdir(parents=True)
    data = json.loads((SKILL / "recipes" / "audio" / "mix-cinema-v001.json").read_text("utf-8"))
    data["sfx"] = {**data["sfx"], "default_enabled": True, "default_on_decision": "self-approved"}
    (root / "recipes" / "audio" / "mix-cinema-v001.json").write_text(json.dumps(data), "utf-8")
    assert any("sfx.default_enabled" in p for p in cinema_problems(data))
    with pytest.raises(Refused, match="sfx.default_enabled"):
        load_recipe(CARTOON, "audio-mix", skill_root=root, domain=CARTOON_DOMAIN)
    with pytest.raises(Refused, match="sfx.default_enabled"):
        resolve_recipe(SimpleNamespace(domain=CARTOON_DOMAIN, episode={}), "audio-mix", CARTOON, skill_root=root)
    shutil.rmtree(root)
    cartoon = load_recipe(CARTOON, "audio-mix", domain=CARTOON_DOMAIN).data
    assert cartoon["sfx"]["default_enabled"] is False and cinema_problems(cartoon) == []


def test_sfx_enabled_follows_the_recipe_default_and_the_override_wins(episode) -> None:  # noqa: F811
    config = episode[0]
    ntc = resolve_recipe(SimpleNamespace(domain=NTC_DOMAIN, episode={}), "audio-mix", NTC)[0].data
    cartoon = load_recipe(CARTOON, "audio-mix", domain=CARTOON_DOMAIN).data
    assert mixcli.sfx_enabled(config, ntc, False) is True
    assert mixcli.sfx_enabled(config, cartoon, False) is False
    assert mixcli.sfx_enabled(config, ntc, True, {"sfx_enabled": False}) is False   # override beats the flag and the default
    assert mixcli.sfx_enabled(config, cartoon, False, {"sfx_enabled": True}) is True


def test_override_off_removes_the_sfx_stem_from_a_real_mix(episode, tmp_path) -> None:  # noqa: F811
    config, root, review, music_wav, _ = episode
    stem = root / "ambience.wav"
    write_tone(stem, 20.0, 0.2, 120.0)
    on = tmp_path / "on"
    off = tmp_path / "off"
    run(config, make_args(on, review, music_wav, sfx_stem=str(stem), with_sfx=True))
    pcm_on = np.frombuffer(read_wav(on / "mix" / mix.STEMS["sfx"]).pcm, dtype="<i2")
    assert np.any(pcm_on)
    override = tmp_path / "override.json"
    override.write_text(json.dumps({"audio": {"sfx_enabled": False}}), "utf-8")
    run(config, make_args(off, review, music_wav, sfx_stem=str(stem), with_sfx=True, audio_override=str(override)))
    receipt = json.loads((off / "mix" / mix.RECEIPT_FILE).read_text("utf-8"))
    assert receipt["sfx_enabled"] is False and receipt["inputs"]["audio_override"]["sfx_enabled"] is False
    assert not np.any(np.frombuffer(read_wav(off / "mix" / mix.STEMS["sfx"]).pcm, dtype="<i2"))


def test_unsupported_mute_and_bad_override_are_refused_not_ignored(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"audio": {"sfx_enabled": "yes"}}), "utf-8")
    with pytest.raises(Refused, match="sfx_enabled"):
        mixcli.load_audio_override(str(bad))
    mute = tmp_path / "mute.json"
    mute.write_text(json.dumps({"audio": {"mute_stems": ["music"]}}), "utf-8")
    with pytest.raises(Refused, match="mute_stems"):
        mixcli.load_audio_override(str(mute))
    assert mixcli.load_audio_override(None) == {}
