"""``jjv text build``: every field generated from the locked script + icon registry; refusals; data-only swap."""

from __future__ import annotations

import argparse
import copy
import json

import pytest

from engine.core.errors import Refused
from engine.editorial import episode_text as et
from engine.editorial import episode_text_cli as cli
from engine.editorial import icons as reg
from engine.editorial import icons_swap as swap
from test_icons_support import FFMPEG, World, needs_ffmpeg

pytestmark = needs_ffmpeg
RECIPE = et.load_recipe()[0]
COPY = {"intro": {"pill": "x"}}


def test_text_is_generated_from_script_and_registry(tmp_path):
    world = World(tmp_path)
    registry = world.registry()
    doc, missing = world.text(registry)
    assert doc["schema"] == et.SCHEMA
    assert doc["strings"] == {"cardsHeader": "Bé cùng đọc nhé! · Say it with me!",
                              "cardsHeaderClosing": "Hẹn gặp lại bé nhé! · See you next time!"}
    assert doc["intro"] == {"kicker": "JENNIEJOY KIDS", "titleLines": ["Milk", "and Mom"], "pill": "Cùng bé",
                            "footer": "3 từ vựng · 2 cuộc trò chuyện nhỏ", "mark": "drop"}
    assert doc["shotVi"] == {"S01_A": "Sữa béo ngậy!", "S01_B": "x" * 70}
    assert doc["captionLines"] == {"S01_B": 2}                       # only the 70-char line needs two lines
    assert doc["captions"]["S01_A"] == {"en": "Creamy milk!", "vi": "Sữa béo ngậy!", "lines": 1}
    assert doc["cards"]["Warm and Cold"] == {"ipa": "/w/", "vi": "Ấm và lạnh", "exampleEn": "Warm and cold.",
                                             "icon": reg.icon_ref(registry["icons"]["warm-cold"])}
    assert doc["cards"]["Creamy"]["exampleVi"] == "Sữa béo."
    assert doc["title"] == {"en": "Milk and Mom", "vi": None}
    assert doc["endPlate"] == {"lines": [{"en": "See you next time!", "vi": "Hẹn gặp lại bé nhé!"}]}
    assert missing[:3] == ["assets.opening", "assets.music", "ending"] and "title.vi" in missing[3]


def test_recipe_holds_no_episode_specific_text():
    flat = json.dumps(RECIPE, ensure_ascii=False)
    for episode_word in ("Milk", "sữa", "Creamy"):
        assert episode_word not in flat


def test_title_line_rule():
    br = RECIPE["intro"]["title_break_before"]
    assert et.title_lines("Milk and Mom", br) == ["Milk", "and Mom"]
    assert et.title_lines("Cats & Dogs", br) == ["Cats", "& Dogs"]
    assert et.title_lines("Farm Day", br) == ["Farm Day"]
    assert et.title_lines("And Then", br) == ["And Then"]            # a leading connector never breaks


def test_pill_comes_from_script_then_copy_and_is_never_invented(tmp_path):
    world = World(tmp_path)
    registry = world.registry()
    with pytest.raises(Refused, match="E_COPY_MISSING"):
        world.text(registry, copy={})
    world.script["structure"]["intro"]["pill_vi"] = "Từ kịch bản"
    doc, _ = world.text(registry, copy={"intro": {"pill": "Từ copy"}})
    assert doc["intro"]["pill"] == "Từ kịch bản"                     # the script wins
    world.script["title_vi"] = "Sữa và Mẹ"
    assert world.text(registry)[0]["title"]["vi"] == "Sữa và Mẹ"


def test_missing_script_data_is_refused(tmp_path):
    world = World(tmp_path)
    registry = world.registry()
    broken = copy.deepcopy(world.script)
    broken["shots"][0].pop("dialogue_vi")
    with pytest.raises(Refused, match="S01_A"):
        et.build_text(broken, registry, RECIPE, copy=COPY)
    broken = copy.deepcopy(world.script)
    broken["vocabulary_cards"][0].pop("ipa")
    with pytest.raises(Refused, match="ipa is required"):
        et.build_text(broken, registry, RECIPE, copy=COPY)
    broken = copy.deepcopy(world.script)
    broken["vocabulary_cards"].append({"term": "Cheese", "ipa": "i", "vi": "v", "example_en": "e", "icon": "x"})
    with pytest.raises(Refused, match="no card 'Cheese'"):
        et.build_text(broken, registry, RECIPE, copy=COPY)
    with pytest.raises(Refused, match="no shots"):
        et.build_text({**world.script, "shots": []}, registry, RECIPE, copy=COPY)


def test_an_icon_swap_changes_only_that_cards_icon_in_the_text(tmp_path):
    """The point of T-E44: an icon change is registry data; the generated text differs in one card's icon only."""
    world = World(tmp_path)
    one = world.registry()
    two, _ = swap.set_icon(one, "Warm and Cold", world.new_png("wc2.png", (100, 100, 100), "square"), root=world.root,
                           recipe=world.recipe, recipe_sha=world.recipe_sha, ffmpeg=FFMPEG)
    diff = et.diff_documents(world.text(two)[0], world.text(one)[0])
    assert {d["path"] for d in diff["diffs"]} == {"cards.Warm and Cold.icon.path", "cards.Warm and Cold.icon.sha256"}


def test_check_locked_and_bound_assets(tmp_path):
    world = World(tmp_path)
    pack = {"source_provenance": {"script_sha256": reg.sha256_file(world.script_path)}}
    et.check_locked(world.script_path, pack)
    with pytest.raises(Refused, match="E_SCRIPT_NOT_LOCKED"):
        et.check_locked(world.script_path, {"source_provenance": {"script_sha256": "0" * 64}})
    stem = world.root / "audio.wav"
    stem.write_bytes(b"RIFF")
    assert et.bind_asset(world.root, "audio.wav", "m") == {"path": "audio.wav", "sha256": reg.sha256_file(stem)}
    with pytest.raises(Refused, match="does not exist"):
        et.bind_asset(world.root, "nope.wav", "m")
    anchor = world.root / "open.png"
    anchor.write_bytes(b"x")
    ok = {"approved_anchors": {"S01_A_opening_frame": {"path": "open.png", "sha256": reg.sha256_file(anchor)}}}
    assert et.opening_from_pack(ok, world.root, RECIPE)["path"] == "open.png"
    bad = {"approved_anchors": {"S01_A_opening_frame": {"path": "open.png", "sha256": "0" * 64}}}
    with pytest.raises(Refused, match="differs"):
        et.opening_from_pack(bad, world.root, RECIPE)
    with pytest.raises(Refused, match="no approved anchor"):
        et.opening_from_pack({}, world.root, RECIPE)


def test_diff_documents_reports_changed_added_and_removed_fields():
    out = et.diff_documents({"a": 1, "b": {"c": 2, "d": 3}, "x": 9}, {"a": 1, "b": {"c": 5}, "y": 8, "n": 0},
                            ignore=("n",))
    kinds = {d["path"]: d["kind"] for d in out["diffs"]}
    assert kinds == {"b.c": "changed", "b.d": "only_generated", "x": "only_generated", "y": "only_reference"}
    assert out["equal_fields"] == 1
    assert et.diff_documents({"a": [1, 2]}, {"a": [1, 2]})["diff_count"] == 0


def parse(*argv):
    parser = argparse.ArgumentParser()
    cli.register_cli(parser.add_subparsers(dest="stage", required=True))
    return parser.parse_args(["text", *argv])


def lock(world: World, pack) -> None:
    pack.write_text(json.dumps({"source_provenance": {"script_sha256": reg.sha256_file(world.script_path)}}))


def test_cli_build_is_write_once_and_diff_exits_1_on_difference(tmp_path, capsys):
    world = World(tmp_path)
    registry_path = world.root / "technical" / "icons.json"
    reg.write_registry(registry_path.parent, world.registry())
    pack = world.root / "script" / "pack.json"
    lock(world, pack)
    copy_file = world.root / "copy.json"
    copy_file.write_text(json.dumps({"schema": et.COPY_SCHEMA, "intro": {"pill": "Cùng bé"}}), encoding="utf-8")
    out = world.root / "text"
    argv = ["build", "--episode", str(world.root), "--registry", str(registry_path), "--script", str(world.script_path),
            "--shot-pack", str(pack), "--copy", str(copy_file), "--out"]
    assert cli.run_text(parse(*argv, str(out), "--dry-run")) == 0 and not out.exists()
    capsys.readouterr()
    assert cli.run_text(parse(*argv, str(out))) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["shots"] == 2 and summary["cards"] == 3 and summary["registry_version"] == 1
    first = (out / "episode-text.json").read_bytes()
    assert cli.run_text(parse(*argv, str(out))) == 0 and (out / "episode-text.json").read_bytes() == first
    capsys.readouterr()
    world.script["shots"][0]["dialogue_vi"] = "Khác"
    world.write_script()
    lock(world, pack)
    with pytest.raises(Refused, match="refusing to overwrite"):
        cli.run_text(parse(*argv, str(out)))
    other = world.root / "text2"
    assert cli.run_text(parse(*argv, str(other))) == 0
    capsys.readouterr()
    code = cli.run_text(parse("diff", "--generated", str(other / "episode-text.json"),
                              "--reference", str(out / "episode-text.json")))
    paths = [d["path"] for d in json.loads(capsys.readouterr().out)["diffs"]]
    assert code == 1 and "shotVi.S01_A" in paths and "captions.S01_A.vi" in paths


def test_cli_refuses_an_unlocked_script_and_a_missing_registry(tmp_path):
    world = World(tmp_path)
    pack = world.root / "pack.json"
    pack.write_text(json.dumps({"source_provenance": {"script_sha256": "0" * 64}}))
    with pytest.raises(Refused, match="no registry"):
        cli.run_text(parse("build", "--episode", str(world.root), "--out", str(world.root / "o")))
    registry_path = world.root / "icons.json"
    reg.write_registry(world.root, world.registry())
    with pytest.raises(Refused, match="E_SCRIPT_NOT_LOCKED"):
        cli.run_text(parse("build", "--episode", str(world.root), "--registry", str(registry_path), "--script",
                           str(world.script_path), "--shot-pack", str(pack), "--out", str(world.root / "o")))
