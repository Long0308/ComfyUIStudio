"""ep04 parity: the generated icon registry and episode-text.json against the real hand-built artefacts.

Reads the real episode (read-only).  The registry/text outputs under ``technical/icons-registry-v001`` are
the committed results of ``jjv icons build`` / ``jjv text build``; these tests rebuild them and compare.
"""

from __future__ import annotations

import json

import pytest

from engine.core.errors import Refused
from engine.editorial import episode_text as et
from engine.editorial import icons as reg
from engine.editorial import icons_build as build
from engine.editorial.icons_check import validate_registry
from test_icons_support import FFMPEG, KIT_TEXT, REAL_EP, needs_ffmpeg, needs_real_ep

pytestmark = [needs_real_ep, needs_ffmpeg]
OUT = REAL_EP / "technical" / "icons-registry-v001"
SCRIPT = REAL_EP / "script" / "script-astra-candidate-v003.json"
PACK = REAL_EP / "script" / "shot-prompt-pack-v004.json"
MUSIC = "audio/mix-plan-v003/milk-mom-music-stem-v003-candidate.wav"
AMBIENCE = "audio/mix-plan-v003/milk-mom-ambience-foley-stem-v003-candidate.wav"
CARDS = ["Creamy", "Smooth", "Liquid", "Dairy Cow", "Farm", "Fresh", "Yummy", "Warm and Cold", "Bones", "Yogurt",
         "Cheese", "Ice Cream"]
ADDITIVE = {"title", "captions", "endPlate"} | {f"cards.{c}.exampleVi" for c in CARDS}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def generate(registry: dict) -> dict:
    recipe = et.load_recipe()[0]
    pack = read(PACK)
    et.check_locked(SCRIPT, pack)
    doc, _ = et.build_text(
        read(SCRIPT), registry, recipe, copy=et.load_copy(OUT / "inputs" / "episode-copy.json"),
        opening=et.opening_from_pack(pack, REAL_EP, recipe), music=et.bind_asset(REAL_EP, MUSIC, "music"),
        ambience=et.bind_asset(REAL_EP, AMBIENCE, "ambience"), ending=read(OUT / "inputs" / "ending-params.json"))
    return doc


def test_real_registry_is_green_and_matches_what_the_v015_cut_used():
    registry = reg.load_registry(OUT / "icons.json")
    report = validate_registry(registry, root=REAL_EP, recipe=reg.load_recipe()[0], ffmpeg=FFMPEG, script_path=SCRIPT)
    assert report["ok"], report["errors"]
    (pair,) = report["pairs"]
    assert pair["status"] == "PASS" and pair["delta_e_file"] > 30 and pair["silhouette_iou"] < 0.8
    events = read(REAL_EP / "editorial" / "review-hd-v015" / "events-v015.json")["icon_events"]
    by_file = {e["file"]: e["sha256"] for e in registry["icons"].values()}
    assert {e["icon"] for e in events} <= set(by_file)
    for event in events:                       # the registry names the very bytes the reviewed cut composited
        assert by_file[event["icon"]] == event["icon_sha256"], event["id"]
    config = read(REAL_EP / "editorial" / "review-hd-v015" / "config" / "review-config-v015.json")
    for card in config["outro_cards"]:
        assert reg.icon_for_card(registry, card["term"])["sha256"] == card["icon"]["sha256"], card["term"]


def test_real_registry_binds_every_spoken_vocabulary_word_of_the_script_to_one_icon():
    registry = reg.load_registry(OUT / "icons.json")
    cards = read(SCRIPT)["vocabulary_cards"]
    assert [c["term"] for c in cards] == CARDS
    spoken = {w for c in registry["cards"].values() for w in c["spoken"]}
    assert spoken == set(registry["terms"]) and len(spoken) == 13        # warm and cold are two words
    assert len({registry["terms"][w]["icon"] for w in spoken}) == 13     # no two words share an icon
    assert reg.icon_for_word(registry, "dairy cows")["id"] == "dairy-cow"


def test_generated_text_equals_the_hand_written_file_except_the_documented_diffs():
    generated = generate(reg.load_registry(OUT / "icons.json"))
    diff = et.diff_documents(generated, read(KIT_TEXT))
    kinds = {d["path"]: d["kind"] for d in diff["diffs"]}
    expected = {"note": "changed", "cards.Warm and Cold.icon.sha256": "changed", **{p: "only_generated" for p in ADDITIVE},
                **{f"cards.{c}.icon.path": "changed" for c in CARDS}}
    assert kinds == expected
    assert not [d for d in diff["diffs"] if d["kind"] == "only_reference"]
    assert diff["equal_fields"] >= 80
    # the 12 path diffs are only the v002 -> v003 asset folder; 11 icons are the same bytes
    for d in diff["diffs"]:
        if d["path"].endswith("icon.path"):
            assert d["generated"].replace("vocabulary-v003", "vocabulary-v002") == d["reference"]


def test_text_from_the_v002_asset_set_equals_the_hand_written_file_field_by_field():
    """The hand-written file is a v002-era file: with v002 icons every field it has is reproduced."""
    recipe = reg.load_recipe()[0]
    manifest = REAL_EP / "assets3d" / "vocabulary-v002" / "manifest.json"
    registry = build.build_registry(episode_id="04-milk-and-mom", root=REAL_EP, manifest_path=manifest, script_path=SCRIPT,
                                    recipe=recipe, recipe_sha="0" * 64, ffmpeg=FFMPEG, allow_shared=("warm-cold",))
    assert not validate_registry(registry, root=REAL_EP, recipe=recipe, ffmpeg=FFMPEG)["ok"]   # the gate refuses it
    diff = et.diff_documents(generate(registry), read(KIT_TEXT))
    assert {d["path"] for d in diff["diffs"]} == {"note", *ADDITIVE}
    assert diff["equal_fields"] >= 94


def test_the_gate_refuses_the_v002_asset_set_for_the_right_reasons():
    recipe = reg.load_recipe()[0]
    manifest = REAL_EP / "assets3d" / "vocabulary-v002" / "manifest.json"
    registry = build.build_registry(episode_id="04-milk-and-mom", root=REAL_EP, manifest_path=manifest, script_path=SCRIPT,
                                    recipe=recipe, recipe_sha="0" * 64, ffmpeg=FFMPEG)
    codes = {e["code"] for e in validate_registry(registry, root=REAL_EP, recipe=recipe, ffmpeg=FFMPEG)["errors"]}
    assert {"E_SHARED_ICON", "E_PAIR_SAME_IMAGE"} <= codes


def test_end_plate_lines_match_the_boundaries_table_the_cut_was_built_from():
    plate = read(REAL_EP / "engine" / "boundaries.json")["ending"]["end_plate"]
    line = generate(reg.load_registry(OUT / "icons.json"))["endPlate"]["lines"][0]
    assert (line["en"], line["vi"]) == (plate["text_en"], plate["text_vi"])


def test_committed_text_is_what_the_builder_makes_now():
    committed = OUT / "text-ep04" / "episode-text.json"
    assert committed.read_bytes() == reg.pretty_json(generate(reg.load_registry(OUT / "icons.json")), mode="utf8")


def test_an_unlocked_script_is_refused():
    other = read(PACK)
    other["source_provenance"]["script_sha256"] = "0" * 64
    with pytest.raises(Refused, match="E_SCRIPT_NOT_LOCKED"):
        et.check_locked(SCRIPT, other)
