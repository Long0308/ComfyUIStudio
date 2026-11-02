"""Audio recipes, the film-mix limits, slot filling and the NHAC-2 graph identity (T-E43)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from audio_fixtures import audio_world, copy_recipes, hand_built_review

from engine.audio import brief, graphs, jobs, music, sections
from engine.audio.recipe import load_recipe, select_recipe_id
from engine.core.errors import Refused

NHAC2_STYLE = (
    "English, long-form extended instrumental, about 2 minutes 30 seconds long, eight sections with intro, repeated themes "
    "and outro, instrumental only, no vocals, no singing, gentle cheerful preschool cartoon background music, major key, "
    "warm and bright, playful but calm, steady soft groove, no sudden loud hits, no drops, clean mix, 96 BPM, G major, "
    "soft felt piano, music box and celesta melody, warm upright bass, brushed light percussion, lullaby-like")
NHAC2_INSTRUMENTS = "soft felt piano, music box and celesta melody, warm upright bass, brushed light percussion, lullaby-like"
NHAC2_PREFIX = "episodes/04-milk-and-mom/music-yue2-v001/NHAC-2-piano-musicbox-take3/NHAC-2-piano-musicbox-take3"
NHAC2_FILE_SHA = "7cbf2a548811b8f379b283592d09d75b534d39ff20b638a7528555070960dfba"  # the graph file that really ran
LANE_GRAPH = Path(Path(__file__).resolve().parents[4], r"production-local\JennieJoyKids-Story\04-milk-and-mom\audio"
                  r"\music-yue2-v001\workflows\NHAC-2-piano-musicbox-take3\NHAC-2-piano-musicbox-take3.api.json")


@pytest.fixture
def world(tmp_path):
    return audio_world(tmp_path)


def test_every_shipped_audio_recipe_loads(world) -> None:
    _, skill = world
    for recipe_id, family in (("audio/music-yue2-int8-v001", "audio-music"), ("audio/sfx-stable-audio-3-small-v001", "audio-sfx"),
                              ("audio/mix-cinema-v001", "audio-mix"), ("audio/mix-legacy-v004-parity", "audio-mix")):
        recipe = load_recipe(recipe_id, family, skill_root=skill)
        assert recipe.data["recipe_id"] == recipe_id and len(recipe.sha256) == 64


def test_default_mix_recipe_is_the_cinema_one_and_legacy_needs_a_name(world) -> None:
    config, skill = world
    assert select_recipe_id(config, "audio-mix", None, skill_root=skill)[0] == "audio/mix-cinema-v001"
    assert select_recipe_id(config, "audio-mix", "audio/mix-legacy-v004-parity", skill_root=skill)[1] == "cli"


@pytest.mark.parametrize("path,value", [
    (("duck", "depth_db"), -3.0), (("duck", "depth_db"), -12.0), (("duck", "attack_s"), 0.5), (("duck", "release_s"), 0.2),
    (("duck", "merge_gap_s"), 0.0), (("loudness", "target_lufs"), -14.0), (("loudness", "tolerance_lu"), 2.0),
    (("loudness", "true_peak_max_dbtp"), 0.0), (("loudness", "max_section_jump_lu"), 3.0), (("pumping", "max_swing_db"), 6.0),
    (("loudness", "enabled"), False), (("pumping", "enabled"), False), (("loudness", "max_bed_step_db"), 4.0),
    (("loudness", "ramp_s"), 0.3), (("pumping", "min_window_s"), 0.2),
    (("speech_buses", "*"), {"mode": "solve", "min_db": -5.0, "max_db": 3.0}),
    (("speech_buses", "*"), {"mode": "fixed", "gain_db": -9.0}), (("sfx", "default_enabled"), True),
    (("music", "gain_db"), -3.0), (("loudness", "bed_gain_max_db"), 3.0), (("loudness", "bed_only"), {"target_lufs": -17.0, "tolerance_lu": 3.0, "below_speech_lu": 3.0, "min_s": 3.0}),
    (("loudness", "bed_only"), {"target_lufs": -22.0, "tolerance_lu": 6.0, "below_speech_lu": 3.0, "min_s": 3.0}),
    (("loudness", "bed_only"), {"target_lufs": -22.0, "tolerance_lu": 3.0, "below_speech_lu": 1.0, "min_s": 3.0}),
    (("loudness", "brand_voice"), {"target_lufs": -16.0, "tolerance_lu": 3.0})])
def test_a_cinema_recipe_cannot_loosen_the_film_mix_standard(tmp_path, path, value) -> None:
    skill = copy_recipes(tmp_path)
    target = skill / "recipes" / "audio" / "mix-cinema-v001.json"
    data = json.loads(target.read_text("utf-8"))
    data[path[0]][path[1]] = value
    target.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Refused, match="loosens the film-mix standard"):
        load_recipe("audio/mix-cinema-v001", "audio-mix", skill_root=skill)


def test_the_outro_bed_gain_cannot_be_louder_than_the_limit(tmp_path) -> None:
    skill = copy_recipes(tmp_path)
    target = skill / "recipes" / "audio" / "mix-cinema-v001.json"
    data = json.loads(target.read_text("utf-8"))
    data["music"]["section_gains_db"]["outro_cards"] = -3.0
    target.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Refused, match="section_gains_db"):
        load_recipe("audio/mix-cinema-v001", "audio-mix", skill_root=skill)


def test_a_cinema_recipe_may_tighten(tmp_path) -> None:
    skill = copy_recipes(tmp_path)
    target = skill / "recipes" / "audio" / "mix-cinema-v001.json"
    data = json.loads(target.read_text("utf-8"))
    data["loudness"]["tolerance_lu"], data["pumping"]["max_swing_db"] = 0.5, 2.0
    target.write_text(json.dumps(data), encoding="utf-8")
    assert load_recipe("audio/mix-cinema-v001", "audio-mix", skill_root=skill).data["loudness"]["tolerance_lu"] == 0.5


def test_a_model_not_bound_to_the_graph_is_refused(tmp_path) -> None:
    skill = copy_recipes(tmp_path)
    target = skill / "recipes" / "audio" / "music-yue2-int8-v001.json"
    data = json.loads(target.read_text("utf-8"))
    data["models"][0]["graph_binding"]["value"] = "other.safetensors"
    target.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Refused, match="not bound to graph"):
        load_recipe("audio/music-yue2-int8-v001", "audio-music", skill_root=skill)


def _nhac2_brief(world) -> dict:
    config, skill = world
    recipe = load_recipe("audio/music-yue2-int8-v001", "audio-music", skill_root=skill)
    result, sources = music.resolve_brief(config, recipe.data, derived={"bpm": 100, "key": "C major", "instruments": "x"},
                                          brief_file=None, overrides={"bpm": 96.0, "key": "G major", "instruments": NHAC2_INSTRUMENTS})
    assert sources["bpm"] == "cli"
    return result


def test_the_style_text_is_the_approved_wording_plus_the_episode_brief(world) -> None:
    _, skill = world
    recipe = load_recipe("audio/music-yue2-int8-v001", "audio-music", skill_root=skill)
    assert music.style_text(recipe.data, _nhac2_brief(world)) == NHAC2_STYLE


def test_the_nhac2_graph_is_reproduced_byte_for_byte(world, tmp_path) -> None:
    _, skill = world
    recipe = load_recipe("audio/music-yue2-int8-v001", "audio-music", skill_root=skill)
    values = {"style": NHAC2_STYLE, "lyrics": recipe.data["lyrics"], "seed": 20261102, "seconds": recipe.data["max_duration_s"],
              "filename_prefix": NHAC2_PREFIX}
    graph = graphs.fill_slots(recipe.data, values)
    saved = jobs.write_workflow(tmp_path / "out", "music-c01-t01", graph)
    assert saved["graph_file_sha256"] == NHAC2_FILE_SHA  # the identity sha of the graph that produced the liked take
    assert [graph[n]["class_type"] for n in sorted(graph)] == [
        "CheckpointLoaderSimple", "YuE2GenerateABC", "YuE2GenerateMusic", "ConditioningZeroOut", "EmptyYuE2LatentAudio",
        "KSampler", "VAEDecodeAudioTiled", "SaveAudio"]
    if LANE_GRAPH.is_file():  # the file the first episode saved: same bytes
        assert (tmp_path / "out" / saved["graph_file"]).read_bytes() == LANE_GRAPH.read_bytes()


def test_the_plan_builds_the_same_graph_apart_from_the_output_prefix(world, tmp_path) -> None:
    config, skill = world
    recipe = load_recipe("audio/music-yue2-int8-v001", "audio-music", skill_root=skill)
    plan = music.build_plan(config, recipe, "cli", out=tmp_path / "run-a", timeline={"duration_s": 86.0, "total_samples": 1,
                            "fps": 30, "total_frames": 2580, "sample_rate": 48000}, brief=_nhac2_brief(world), brief_sources={},
                            evidence=None, takes=2, seed=20261102, write=True)
    first = json.loads((tmp_path / "run-a" / plan["jobs"][0]["graph_file"]).read_text("utf-8"))
    assert first["8"]["inputs"]["filename_prefix"] == "episodes/04-milk-and-mom/run-a/music-c01-t01"
    first["8"]["inputs"]["filename_prefix"] = NHAC2_PREFIX
    assert graphs.graph_sha256(first) == graphs.graph_sha256(json.loads(LANE_GRAPH.read_text("utf-8"))) if LANE_GRAPH.is_file() else True
    assert [j["seed"] for j in plan["jobs"]] == [20261102, 20261103] and plan["bed_target_s"] == 89.0


def test_slots_only_and_typed(world) -> None:
    _, skill = world
    recipe = load_recipe("audio/music-yue2-int8-v001", "audio-music", skill_root=skill)
    values = {"style": "s", "lyrics": "[Intro]", "seed": 1, "seconds": 30.0, "filename_prefix": "p/q"}
    with pytest.raises(Refused, match="needs"):
        graphs.fill_slots(recipe.data, {**values, "seed": "1"})
    with pytest.raises(Refused, match="do not match"):
        graphs.fill_slots(recipe.data, {k: v for k, v in values.items() if k != "seed"})
    graph = graphs.fill_slots(recipe.data, values)
    tampered = copy.deepcopy(graph)
    tampered["6"]["inputs"]["steps"] = 8
    with pytest.raises(Refused, match="not a slot"):
        graphs.require_only_slots_differ(recipe.data, tampered)


def _review_with(texts: list[str], seconds: float) -> dict:
    return {"dialogue": [{"id": f"S{i + 1:02d}_A", "start_frame": 90 + i * 150, "duration_frames": int(seconds * 30),
                          "speech_text": text} for i, text in enumerate(texts)]}


def test_the_brief_follows_the_script_density_and_setting(world) -> None:
    config, skill = world
    recipe = load_recipe("audio/music-yue2-int8-v001", "audio-music", skill_root=skill).data
    slow = _review_with(["one two three four five six seven eight"] * 3, 5.0)   # 1.6 words/s: calm
    fast = _review_with(["one two three four five six seven eight nine ten eleven twelve thirteen fourteen"] * 3, 5.0)  # 2.8
    for review, energy, bpm in ((slow, "calm", 96), (fast, "lively", 108)):
        sects = sections.derive_sections({**review, "outro_cards": []}, {"total_frames": 900, "fps": 30, "sample_rate": 48000})
        derived, evidence = brief.derive(recipe, review, sects, 30, "ep-x", ["a quiet room"])
        assert evidence["overall_energy"] == energy and derived["bpm"] == bpm and "major" in derived["key"]
    pastoral, why = brief.pick_palette(recipe["derivation"], ["a cow in the meadow by the garden"], "calm")
    assert pastoral["id"] == "pastoral" and why["by"] == "keyword hits"
    lullaby, why = brief.pick_palette(recipe["derivation"], ["a plain room"], "calm")
    assert lullaby["id"] == "lullaby" and why["by"] == "energy calm"


def test_the_key_is_deterministic_per_episode_and_minor_keys_are_refused(world) -> None:
    config, skill = world
    recipe = load_recipe("audio/music-yue2-int8-v001", "audio-music", skill_root=skill).data
    review = _review_with(["a b c d e f g h"] * 2, 5.0)
    sects = sections.derive_sections({**review, "outro_cards": []}, {"total_frames": 900, "fps": 30, "sample_rate": 48000})
    first = brief.derive(recipe, review, sects, 30, "ep-1", [])[0]["key"]
    assert first == brief.derive(recipe, review, sects, 30, "ep-1", [])[0]["key"]
    with pytest.raises(Refused, match="major key"):
        music.resolve_brief(config, recipe, derived=None, brief_file=None, overrides={"key": "A minor"})
    assert hand_built_review  # fixture import stays used


def test_candidates_differ_in_instruments_key_and_tempo_with_their_own_seeds(world, tmp_path) -> None:
    config, skill = world
    recipe = load_recipe("audio/music-yue2-int8-v001", "audio-music", skill_root=skill)
    timeline = {"duration_s": 86.0, "total_samples": 1, "fps": 30, "total_frames": 2580, "sample_rate": 48000}
    plan = music.build_plan(config, recipe, "cli", out=tmp_path / "run-b", timeline=timeline, brief=_nhac2_brief(world),
                            brief_sources={}, evidence=None, takes=2, seed=100, write=False, candidates=3)
    assert [j["job_id"] for j in plan["jobs"]] == ["music-c01-t01", "music-c01-t02", "music-c02-t01", "music-c02-t02",
                                                   "music-c03-t01", "music-c03-t02"]
    assert [j["seed"] for j in plan["jobs"]] == [100, 101, 200, 201, 300, 301]
    briefs = [plan["jobs"][i]["brief"] for i in (0, 2, 4)]
    assert len({b["instruments"] for b in briefs}) == len({b["key"] for b in briefs}) == len({b["bpm"] for b in briefs}) == 3
    assert all("major" in b["key"] and plan["jobs"][i]["style"].endswith(b["instruments"]) for b, i in zip(briefs, (0, 2, 4)))
    assert plan["prompt"]["style"] == NHAC2_STYLE and briefs[0]["instruments"] == NHAC2_INSTRUMENTS


def test_a_music_recipe_cannot_loosen_the_vocal_free_standard(tmp_path) -> None:
    skill = copy_recipes(tmp_path)
    target = skill / "recipes" / "audio" / "music-yue2-int8-v001.json"
    data = json.loads(target.read_text("utf-8"))
    assert data["vocal_gate"]["limit_db"] == -35.0
    data["vocal_gate"]["limit_db"] = -20.0
    target.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Refused, match="loosens the vocal-free standard"):
        load_recipe("audio/music-yue2-int8-v001", "audio-music", skill_root=skill)
    data["vocal_gate"]["limit_db"] = -40.0   # tightening is fine
    target.write_text(json.dumps(data), encoding="utf-8")
    assert load_recipe("audio/music-yue2-int8-v001", "audio-music", skill_root=skill).data["vocal_gate"]["limit_db"] == -40.0


def test_the_cinema_defaults_carry_the_channel_rules(world) -> None:
    _, skill = world
    data = load_recipe("audio/mix-cinema-v001", "audio-mix", skill_root=skill).data
    assert data["music"]["gain_db"] == -6.0 and data["music"]["section_gains_db"]["outro_cards"] == -4.5
    assert data["sfx"]["default_enabled"] is False and data["loudness"]["bed_gain_max_db"] == 0.0
    assert data["speech_buses"]["*"] == {"mode": "solve", "min_db": -3.0, "max_db": 3.0} and data["pumping"]["min_window_s"] == 1.0
    assert data["loudness"]["max_bed_step_db"] == 3.0 and data["loudness"]["ramp_s"] == 1.0


def test_the_ep04_recipe_pins_the_approved_hand_mix_and_is_never_a_default(world) -> None:
    config, skill = world
    data = load_recipe("audio/mix-cinema-ep04-final-v001", "audio-mix", skill_root=skill).data
    assert data["music"]["gain_db"] == -9.0 and data["music"]["section_gains_db"]["outro_cards"] == -6.5
    buses = data["speech_buses"]
    assert (buses["dialogue"], buses["vocabulary"], buses["end_line"]) == (
        {"mode": "fixed", "gain_db": -1.5}, {"mode": "fixed", "gain_db": 2.7}, {"mode": "fixed", "gain_db": -3.3})
    assert data["duck"]["depth_db"] == -7.0 and data["pinned_from"].endswith("mix-plan-v016-final-giongC-nhacV2-4.json")
    assert select_recipe_id(config, "audio-mix", None, skill_root=skill)[0] == "audio/mix-cinema-v001"
