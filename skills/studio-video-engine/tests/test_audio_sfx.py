"""SFX cue sheet derived from the script (shot actions + review config events) and the SFX run (T-E43)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from audio_fixtures import RATE, Rig, audio_world, hand_built_review, recipe_of, sfx_wav
from fake_comfy import FakeComfy

from engine.audio import cuesheet, jobs, sfx
from engine.core.errors import Refused
from engine.core.io import read_json, write_json_once
from engine.seedvr2.seam_media import find_ffmpeg

TIMELINE = {"fps": 30, "total_frames": 600, "duration_s": 20.0, "sample_rate": RATE, "total_samples": 600 * 1600}
EP04 = Path(Path(__file__).resolve().parents[4], r"production-local\JennieJoyKids-Story\04-milk-and-mom")


@pytest.fixture
def world(tmp_path):
    config, skill = audio_world(tmp_path)
    recipe = recipe_of(skill, "audio/sfx-stable-audio-3-small-v001", "audio-sfx")
    review = hand_built_review(Path(config.episode_root))
    return config, skill, recipe, review


def derive(recipe, review, texts, **kw):
    return cuesheet.derive(recipe.data, review, texts, TIMELINE, include_optional=kw.pop("include_optional", False), **kw)


def by_class(sheet: dict) -> dict:
    out: dict = {}
    for p in sheet["placements"]:
        out.setdefault(p["class"], []).append(p)
    return out


def test_a_cue_comes_from_an_action_on_screen_and_a_negated_one_is_rejected(world) -> None:
    _, _, recipe, review = world
    texts = {"S01_A": "Mother gently rotates it a quarter-turn. No pouring or drinking-glass lift.",
             "S01_B": "She pours the milk into the cup and the cup clinks."}
    sheet = derive(recipe, review, texts)
    cues = by_class(sheet)
    assert "bottle_rotate" in cues and cues["bottle_rotate"][0]["shot"] == "S01_A"
    assert [p["shot"] for p in cues["pour"]] == ["S01_B"] and [p["shot"] for p in cues["clink"]] == ["S01_B"]
    rejected = [s for s in sheet["skipped"] if s.get("reason") == "negated in the shot text"]
    assert [(s["class"], s["shot"]) for s in rejected] == [("pour", "S01_A")] and "No pouring" in rejected[0]["evidence"]
    assert cues["pour"][0]["frame"] == 150 + round(0.5 * 30) and cues["pour"][0]["action"].startswith("She pours")


def test_repeated_actions_get_their_own_cue_and_spans_loop_over_the_shot(world) -> None:
    _, _, recipe, review = world
    texts = {"S01_A": "Mother slides an orange fabric sleeve onto one cup and a blue fabric sleeve onto a second cup.",
             "S01_B": "A milkmaid keeps a calm alternating hand-milking cycle."}
    cues = by_class(derive(recipe, review, texts))
    sleeves = cues["fabric_sleeve"]
    assert [p["frame"] for p in sleeves] == [30 + 12, 30 + 12 + 21]  # offset_s 0.4 s, then +0.7 s
    milking = cues["hand_milking"][0]
    assert milking["loop"] and milking["frame"] == 150 + 9 and milking["duration_s"] == pytest.approx((66 - 9) / 30)


def test_event_cues_follow_icons_cards_transitions_and_anchors(world) -> None:
    _, _, recipe, review = world
    cues = by_class(derive(recipe, review, {}))
    assert [p["frame"] for p in cues["sparkle"]] == [50]
    assert [p["frame"] for p in cues["card_sparkle"]] == [300, 390]
    assert [(p["frame"], p["shot"]) for p in cues["whoosh"]] == [(117, "S01_B")]  # start 118 - lead 1
    assert [p["frame"] for p in cues["logo_chime"]] == [485]  # logo_disc.in 480 + 5; end_logo absent: skipped
    assert any(s["class"] == "logo_chime" and "end_logo.from_frame" in s["reason"] for s in derive(recipe, review, {})["skipped"])


def test_a_cue_outside_the_film_is_skipped_not_placed(world) -> None:
    _, _, recipe, review = world
    review["motion"]["ending"]["logo_disc"]["in"] = 5000
    sheet = derive(recipe, review, {})
    assert "logo_chime" not in by_class(sheet) and any("outside the film" in s["reason"] for s in sheet["skipped"])


def test_optional_classes_need_the_flag_and_manual_cues_keep_their_reason(world) -> None:
    _, _, recipe, review = world
    texts = {"S01_A": "Alice is walking across the lawn."}
    assert "footsteps" not in by_class(derive(recipe, review, texts))
    assert "footsteps" in by_class(derive(recipe, review, texts, include_optional=True))
    manual = derive(recipe, review, {}, extra=[{"class": "moo", "frame": 200, "reason": "cow B calls in the wide shot"}])
    row = by_class(manual)["moo"][0]
    assert row["source"] == "manual" and row["action"] == "MANUAL: cow B calls in the wide shot" and row["frame"] == 200
    with pytest.raises(Refused, match="needs a known class"):
        derive(recipe, review, {}, extra=[{"class": "moo", "frame": 200}])


def test_one_clip_per_class_with_a_stable_seed(world) -> None:
    _, _, recipe, review = world
    first = derive(recipe, review, {"S01_A": "She rotates it gently."})
    second = derive(recipe, review, {"S01_A": "She rotates it gently."}, include_optional=True)
    seeds = {c["class"]: c["seed"] for c in first["clips"]}
    assert {c["class"]: c["seed"] for c in second["clips"] if c["class"] in seeds} == seeds  # optional classes do not shift seeds
    assert len({c["clip_id"] for c in first["clips"]}) == len(first["clips"])


def test_shot_pack_text_loading(tmp_path) -> None:
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps({"shots": [{"shot_id": "S01_A", "visual_description": "Mother sets three tokens", "x": 1}]}), "utf-8")
    assert sfx.load_shot_texts(pack, ["visual_description"]) == {"S01_A": "Mother sets three tokens"}
    with pytest.raises(Refused, match="no shot action text"):
        sfx.load_shot_texts(pack, ["missing_field"])
    with pytest.raises(Refused, match="no shot pack"):
        sfx.load_shot_texts(None, ["visual_description"])


@pytest.mark.skipif(not (EP04 / "script/shot-prompt-pack-v004.json").is_file(), reason="first episode files not present")
def test_the_first_episode_cue_list_matches_the_accepted_sfx_v003_cues() -> None:
    """Parity fixture: derived (class, shot) pairs against the accepted list of audio/sfx-v003 (SFX-01 and SFX-20 rejected)."""
    from engine.audio.recipe import load_recipe
    recipe = load_recipe("audio/sfx-stable-audio-3-small-v001", "audio-sfx")
    review = read_json(EP04 / "editorial/review-hd-v013/config/review-config-v013.json")
    texts = sfx.load_shot_texts(EP04 / "script/shot-prompt-pack-v004.json", ["visual_description"])
    sheet = cuesheet.derive(recipe.data, review, texts, {"fps": 30, "total_frames": review["total_frames"],
                            "duration_s": review["total_frames"] / 30, "sample_rate": RATE, "total_samples": 0}, include_optional=False)
    got = {(p["class"], p["shot"]) for p in sheet["placements"] if p["class"] not in ("sparkle", "card_sparkle", "whoosh")}
    accepted = {("hand_milking", "S02_A"), ("hand_milking", "S02_B"), ("bottle_rotate", "S01_A"), ("liquid_slosh", "S01_B"),
                ("wood_token_set", "S03_A"), ("wood_token_place", "S03_B"), ("fabric_sleeve", "S04_A"), ("wood_token_slide", "S04_B"),
                ("wood_hinge", "S05_A"), ("ribbon_tension", "S05_B"), ("page_turn", "S06_A"), ("logo_chime", "anchor")}
    assert got == accepted  # not derivable from the text (lane judgement): moo S02_B, leaves x3, cup clink x2 -> --extra-cues
    assert not any(c in ("pour", "footsteps") for c, _ in got)  # SFX-01 and SFX-20 are rejected
    classes = by_class(sheet)
    assert len(classes["sparkle"]) == 19 and len(classes["card_sparkle"]) == 12 and len(classes["fabric_sleeve"]) == 2 and len(classes["wood_token_slide"]) == 2
    assert {p["frame"] for p in classes["whoosh"]} >= {1490}  # T1495, the required whip pan
    assert {s["class"] for s in sheet["skipped"] if s["reason"] == "negated in the shot text"} == {"pour"}


def test_sfx_run_generates_one_clip_per_class_and_places_them(world, tmp_path) -> None:
    config, skill, recipe, review = world
    texts = {"S01_A": "Mother rotates it a quarter-turn.", "S01_B": "Alice tips the sealed bottle a few degrees."}
    sheet = derive(recipe, review, texts)
    out = tmp_path / "sfx-v001"
    plan = sfx.build_plan(config, recipe, "cli", out=out, timeline=TIMELINE, sheet=sheet, write=True, review_config_sha256="0" * 64)
    write_json_once(out / sfx.PLAN_FILE, plan, mode="ascii")
    with FakeComfy() as fake:
        rig = Rig(tmp_path, fake, recipe, skill)
        rig.serve(lambda prompt: sfx_wav(0.5))
        result = jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        assert result["completed"] == len(plan["jobs"]) == len(fake.posts_made())
        assert jobs.run_all(rig.context(out), plan, rig.data, rig.root)["reused"] == len(plan["jobs"])
        assert len(fake.posts_made()) == len(plan["jobs"])  # a finished job is never POSTed again
        receipt = sfx.finalize(out, sfx.load_plan(out), recipe, output_root=rig.settings.output_dir,
                               ffmpeg=find_ffmpeg(), rate=RATE)
    clip = receipt["clips"][0]
    assert 0.45 < clip["duration_s"] < 0.6  # 0.3 s of silence trimmed from each end
    assert clip["metrics"]["peak_dbfs"] == pytest.approx(-3.0, abs=0.1)
    assert receipt["licences"] and receipt["models"] and {p["source_sha256"] for p in receipt["placements"]} <= {c["sha256"] for c in receipt["clips"]}
    assert receipt["recipe"]["sha256"] == recipe.sha256


def test_a_new_topic_runs_and_the_library_gaps_are_reported_not_invented(world) -> None:
    """ep05-style input (fruit orchard, no shared action with the first episode): events work, unknown actions are listed."""
    _, _, recipe, review = world
    texts = {"S01_A": "Mother slices an apple on a wooden board beside the basket.", "S01_B": "Alice hugs the basket and smiles."}
    sheet = derive(recipe, review, texts, extra=[{"class": "page_turn", "frame": 200, "shot": "S01_B", "reason": "she flips the recipe card"}])
    assert sheet["uncovered_shots"] == ["S01_A"]  # S01_B is covered by the manual cue
    assert {"sparkle", "card_sparkle", "whoosh"} <= set(by_class(sheet))                  # event cues need no action text
    assert not any(p["source"] == "keyword" for p in sheet["placements"])                 # nothing is invented from "slices an apple"
    assert any(p["source"] == "manual" and p["shot"] == "S01_B" for p in sheet["placements"])
