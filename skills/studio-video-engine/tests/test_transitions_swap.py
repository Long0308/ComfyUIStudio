"""T-E42 follow-up: ``boundaries swap`` (versioned boundaries.json + segments to re-composite) and the CLIs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from engine.config import loader
from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.editorial import boundaries_suggest as bs
from engine.editorial import boundaries_suggest_cli as cli
from engine.editorial import presets_cli, presets_swap
from transitions_fixtures import GRAD_X, GRAD_Y, build, declared, needs_ffmpeg

SPECS = [("S01_A", 24, "cut", GRAD_X), ("S01_B", 24, "cut", GRAD_Y), ("S02_A", 24, "cut", GRAD_X),
         ("S02_B", 24, "cut", GRAD_Y)]


def table() -> dict:
    """Declared table: S01_A->S01_B dip_white, S01_B->S02_A whip, S02_A->S02_B cut_push."""
    rows = [{"frame": 120, "from_shot": "S01_A", "to_shot": "S01_B", "type": "dip_white", "frames": 8,
             "tail_clip": "clips/S01_A-native.mp4"},
            {"frame": 150, "from_shot": "S01_B", "to_shot": "S02_A", "type": "whip", "frames": 8, "direction": 1},
            {"frame": 180, "from_shot": "S02_A", "to_shot": "S02_B", "type": "cut_push", "frames": 12}]
    document = declared(rows)
    return {"schema": "jjv/boundaries/v1", "episode_id": "test-episode", **document,
            "icons": {"dir": "icons", "terms": [{"term": "milk", "icon": "milk.png"}], "hold_frames": 30,
                      "fade_frames": 6, "pop_frames": 6, "lead_frames": 6}}


@pytest.fixture()
def world(tmp_path: Path):
    config, shots = build(tmp_path / "ep", SPECS, tail={"S01_A": 13, "S01_B": 13})
    doc_path = tmp_path / "declared.json"
    doc_path.write_text(json.dumps(table(), indent=2), encoding="utf-8")
    ctx = bs.make_context(config, shots, table(), ffmpeg=None, measure=lambda a, b: {"ncc": None})
    return config, shots, ctx, doc_path, tmp_path / "workspace"


def run(world, boundary: str, preset: str, **kwargs) -> dict:
    config, shots, ctx, doc_path, workspace = world
    return presets_swap.swap(ctx, shots, config, doc_path, workspace, boundary, preset, **kwargs)


def current(world) -> dict:
    return json.loads((world[4] / "boundaries.json").read_text("utf-8"))


# ---- a swap is data ------------------------------------------------------------------------------------------------
@needs_ffmpeg
def test_a_swap_writes_versions_the_current_file_and_a_log_and_never_touches_the_declared_table(world) -> None:
    before = sha256_file(world[3])
    summary = run(world, "T150", "dip_black")
    workspace = world[4]
    assert summary["version"] == 2 and summary["from"] == "whip" and summary["to"] == "dip_black"
    assert (workspace / "versions" / "boundaries-v001.json").is_file()
    v2 = json.loads((workspace / "versions" / "boundaries-v002.json").read_text("utf-8"))
    assert current(world) == v2
    row = next(r for r in v2["boundaries"] if r["frame"] == 150)
    assert (row["type"], row["frames"], row["direction"]) == ("dip_black", 8, 0)
    assert row["tail_clip"] == "clips/S01_B-native.mp4" and row["motivation"].startswith("swap v002: whip -> dip_black")
    assert "previous motivation: declared" in row["motivation"]
    assert [r for r in v2["boundaries"] if r["frame"] != 150] == [r for r in table()["boundaries"] if r["frame"] != 150]
    log = json.loads((workspace / "swap-log.json").read_text("utf-8"))
    assert [v["version"] for v in log["versions"]] == [1, 2] and log["versions"][1]["parent"] == 1
    assert log["versions"][1]["sha256"] == sha256_file(workspace / "versions" / "boundaries-v002.json")
    assert sha256_file(world[3]) == before                       # the declared table is read-only


@needs_ffmpeg
def test_the_segments_to_recomposite_are_the_two_shot_spans_around_the_cut_and_the_effect_window(world) -> None:
    summary = run(world, "T150", "dip_black")
    ids = [s["id"] for s in summary["re_composite"]]
    assert ids == ["shot-S01_B-1", "tr-T150", "shot-S02_A-1"]
    window = next(s for s in summary["re_composite"] if s["id"] == "tr-T150")
    assert (window["start"], window["end_exclusive"]) == (148, 156)      # dip_black: B-2 .. B+5
    assert summary["segments_total"] > len(ids)                          # the rest of the film is NOT redone


@needs_ffmpeg
def test_naming_the_effect_that_is_already_there_changes_and_writes_nothing(world) -> None:
    summary = run(world, "T150", "whip")
    assert summary["unchanged"] is True and summary["re_composite"] == [] and not world[4].exists()


@needs_ffmpeg
def test_a_motivation_note_alone_never_makes_a_segment_dirty(world) -> None:
    config, shots, ctx, _, _ = world
    old = presets_swap.records_of(table(), ctx)
    noted = table()
    noted["boundaries"][1]["motivation"] = "a different sentence"
    new = presets_swap.records_of(noted, ctx)
    assert old != new
    assert presets_swap.segments_to_recomposite(old, new, shots, ctx["grid"], "e")["re_composite"] == []


@needs_ffmpeg
def test_a_second_swap_makes_version_three_and_the_current_file_follows(world) -> None:
    run(world, "T150", "dip_black")
    summary = run(world, "180", "cut")
    assert summary["version"] == 3 and summary["boundary"] == "T180"
    assert current(world) == json.loads((world[4] / "versions" / "boundaries-v003.json").read_text("utf-8"))
    assert {r["frame"]: r["type"] for r in current(world)["boundaries"]} == {120: "dip_white", 150: "dip_black", 180: "cut"}


@needs_ffmpeg
def test_options_ride_on_the_token_and_params_of_the_old_effect_are_dropped(world) -> None:
    summary = run(world, "T180", "cut_push:frames=8:scale_from=1.06")
    row = next(r for r in current(world)["boundaries"] if r["frame"] == 180)
    assert (summary["frames"], row["params"]) == (8, {"scale_from": 1.06})
    again = run(world, "T180", "cut_push")                       # the whole spec is replaced: defaults, no old params
    assert "params" not in next(r for r in current(world)["boundaries"] if r["frame"] == 180) and again["frames"] == 12


@needs_ffmpeg
def test_a_dry_run_validates_and_lists_the_segments_but_writes_nothing(world) -> None:
    summary = run(world, "T150", "dip_black", dry_run=True)
    assert summary["dry_run"] is True and summary["re_composite"]
    assert not world[4].exists()


# ---- refusals write nothing --------------------------------------------------------------------------------------------
@needs_ffmpeg
@pytest.mark.parametrize("boundary, preset, message", [
    ("T150", "crossfade", "both sides in one frame"),               # continuity unknown: no two-shot effect
    ("T150", "whip:direction=0", "whip needs direction"),
    ("T150", "dip_white:frames=9", "frames"),
    ("T150", "glitch", "planned"),
    ("T999", "cut", "no boundary"),
])
def test_a_refused_swap_names_the_rule_and_leaves_the_workspace_untouched(world, boundary, preset, message) -> None:
    with pytest.raises(Refused, match=message):
        run(world, boundary, preset)
    assert not world[4].exists()


@needs_ffmpeg
def test_a_tail_preset_without_a_long_enough_handle_is_refused_with_no_gpu_message(tmp_path: Path) -> None:
    config, shots = build(tmp_path / "ep", SPECS, tail={"S01_A": 13, "S01_B": 0})
    ctx = bs.make_context(config, shots, table(), ffmpeg=None, measure=lambda a, b: {"ncc": None})
    path = tmp_path / "d.json"
    path.write_text(json.dumps(table()), encoding="utf-8")
    with pytest.raises(Refused, match="no GPU work is requested"):
        presets_swap.swap(ctx, shots, config, path, tmp_path / "w", "T150", "dip_white")
    assert not (tmp_path / "w").exists()


@needs_ffmpeg
def test_a_graphic_boundary_is_not_swapped_here(tmp_path: Path) -> None:
    config, shots = build(tmp_path / "ep", SPECS)
    doc = table()
    doc["boundaries"].append({"frame": 240, "from_shot": "S02_B", "to_shot": "OUTRO", "class": "cut", "type": "iris",
                              "frames": 44, "continuity": "unknown", "motivation": "end", "params": {"disc_fade_frames": 6}})
    path = tmp_path / "d.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    ctx = bs.make_context(config, shots, doc, measure=lambda a, b: {"ncc": None})
    with pytest.raises(Refused, match="not between two picture shots"):
        presets_swap.swap(ctx, shots, config, path, tmp_path / "w", "T240", "cut")


# ---- CLIs ---------------------------------------------------------------------------------------------------------------
def test_presets_list_and_show_resolve_the_users_words(capsys) -> None:
    assert presets_cli.main(["list"]) == 0
    rows = json.loads(capsys.readouterr().out)["presets"]
    assert len(rows) == 33 and sum(r["status"] == "ready" for r in rows) == 30
    assert presets_cli.main(["show", "push"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["name"] == "cut_push" and shown["asked_as"] == "push"
    assert shown["defaults"]["frames"] == 12 and shown["defaults"]["tail_output_frames"] == 0
    assert shown["defaults"]["window_from_cut"] == [0, 12]
    assert presets_cli.main(["show", "flash"]) == 0 and json.loads(capsys.readouterr().out)["name"] == "dip_white"
    assert presets_cli.main(["show", "glitch"]) == 0 and json.loads(capsys.readouterr().out)["status"] == "planned"
    assert presets_cli.main(["show", "nope"]) == 1 and "unknown transition preset" in capsys.readouterr().out
    assert presets_cli.main(["show"]) == 1
    assert presets_cli.main([]) == 0                                     # the old behaviour: the whole catalog


def test_the_boundaries_verb_registers_suggest_preview_swap_and_parses_the_documented_lines() -> None:
    parser = argparse.ArgumentParser()
    verbs = parser.add_subparsers(dest="verb")
    cli.register(verbs)
    got = parser.parse_args(["boundaries", "preview", "--episode", "E", "--boundary", "T1310", "--presets",
                             "push,dip,cut", "--out", "G"])
    assert (got.action, got.boundary, got.presets, got.context_frames) == ("preview", "T1310", "push,dip,cut", 24)
    assert parser.parse_args(["boundaries", "suggest", "--episode", "E", "--out", "O"]).action == "suggest"
    assert parser.parse_args(["boundaries", "swap", "--episode", "E", "--boundaries", "B", "--boundary", "T1310",
                              "--preset", "push", "--out", "W", "--dry-run"]).dry_run is True
    with pytest.raises(SystemExit):
        parser.parse_args(["boundaries", "suggest"])                     # --episode / --out are required


EP = loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom"
REAL = pytest.mark.skipif(not (EP / "clips" / "motion-v004" / "S04_B-editorial.mp4").is_file(), reason="episode clips absent")


@REAL
@needs_ffmpeg
def test_suggest_cli_on_the_reference_episode_writes_once_prints_a_table_and_compares_with_the_approved_cut(
        tmp_path: Path, capsys) -> None:
    approved = EP / "editorial" / "review-hd-v015" / "config" / "review-config-v015.json"
    argv = ["suggest", "--episode", "04-milk-and-mom", "--boundaries", str(EP / "engine" / "boundaries.json"),
            "--out", str(tmp_path)]
    if approved.is_file():
        argv += ["--compare-config", str(approved)]
    assert cli.main(argv) == 0
    captured = capsys.readouterr()
    assert "T1310" in captured.err and "cut_push" in captured.err and "ncc" in captured.err
    summary = json.loads(captured.out)
    document = json.loads((tmp_path / "boundaries-suggested.json").read_text("utf-8"))
    assert summary["sha256"] == sha256_file(tmp_path / "boundaries-suggested.json")
    if approved.is_file():
        assert summary["parity"] == {"compared": 13, "type_match": 13, "full_match": 13}
    assert cli.main(argv) == 0                                           # identical bytes: idempotent
    document["boundaries"][0]["id"] = "tampered"
    (tmp_path / "boundaries-suggested.json").write_text(json.dumps(document), encoding="utf-8")
    assert cli.main(argv) == 1 and "refusing to overwrite" in capsys.readouterr().out
