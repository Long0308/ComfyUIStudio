"""``jjv icons build|validate|set`` through the real argparse wiring (in-process; stdout is the JSON summary)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from engine.editorial import icons_cli
from test_icons_support import World, needs_ffmpeg

pytestmark = needs_ffmpeg


def run(capsys, *argv: str) -> tuple[int, dict]:
    parser = argparse.ArgumentParser()
    icons_cli.register_cli(parser.add_subparsers(dest="stage", required=True))
    code = icons_cli.run_icons(parser.parse_args(["icons", *argv]))
    return code, json.loads(capsys.readouterr().out)


def build_args(world: World, out: Path, *extra: str) -> list[str]:
    attrs = world.root / "attrs.json"
    attrs.write_text(json.dumps({"warm": "orange mug with steam", "cold": "blue mug with ice"}), encoding="utf-8")
    return ["build", "--episode", str(world.root), "--assets-manifest", str(world.manifest_path),
            "--script", str(world.script_path), "--attributes", str(attrs), "--out", str(out), "--recipe", str(world.recipe_path), *extra]


def test_build_validate_and_set_round_trip(tmp_path, capsys):
    world = World(tmp_path)
    out = world.root / "technical" / "icons"
    code, summary = run(capsys, *build_args(world, out, "--dry-run"))
    assert code == 0 and summary["dry_run"] and not (out / "icons.json").exists()
    code, summary = run(capsys, *build_args(world, out))
    assert code == 0 and summary["summary"]["icons"] == 5 and (out / "icons.json").is_file()
    again_code, _ = run(capsys, *build_args(world, out))                       # idempotent
    assert again_code == 0
    code, report = run(capsys, "validate", "--episode", str(world.root), "--registry", str(out / "icons.json"),
                       "--script", str(world.script_path), "--recipe", str(world.recipe_path))
    assert code == 0 and report["ok"]
    code, report = run(capsys, "validate", "--episode", str(world.root), "--registry", str(out / "icons.json"),
                       "--require-approved", "--recipe", str(world.recipe_path))
    assert code == 1 and any(e["code"] == "E_NOT_APPROVED" for e in report["errors"])
    new_png = world.new_png("cold-2.png", (30, 90, 230), "square")
    events = world.root / "events.json"
    events.write_text(json.dumps({"icon_events": [
        {"id": "IC1", "shot": "S01_A", "icon": "cold.png", "icon_path": "x", "frame": 50, "total_frames": 32}]}))
    code, done = run(capsys, "set", "cold", "--episode", str(world.root), "--registry", str(out / "icons.json"),
                     "--png", str(new_png), "--events", str(events), "--recipe", str(world.recipe_path))
    assert code == 0 and done["change"]["version"] == 2
    assert done["change"]["recomposite"]["icon_events"][0]["start"] == 50
    assert done["change"]["recomposite"]["shot_sources_changed"] is False
    assert json.loads((out / "icons.json").read_text("utf-8"))["version"] == 2
    assert (out / "versions" / "icons-v001.json").is_file() and (out / "versions" / "icons-v002.json").is_file()


def test_build_exits_1_and_writes_nothing_when_the_gate_fails(tmp_path, capsys):
    world = World(tmp_path, per_word=False)                                    # warm and cold would share one image
    out = world.root / "technical" / "icons"
    code, summary = run(capsys, *build_args(world, out))
    assert code == 1 and summary["ok"] is False and not out.exists()
    assert {e["code"] for e in summary["errors"]} >= {"E_SHARED_ICON", "E_PAIR_SAME_IMAGE"}


def test_set_without_a_registry_is_refused_and_a_bad_swap_changes_nothing(tmp_path, capsys):
    world = World(tmp_path)
    out = world.root / "technical" / "icons"
    run(capsys, *build_args(world, out))
    before = (out / "icons.json").read_bytes()
    from engine.core.errors import Refused
    with pytest.raises(Refused, match="no registry"):
        run(capsys, "set", "cold", "--episode", str(world.root), "--png", str(world.new_png("c.png", (1, 2, 3))), "--recipe", str(world.recipe_path))
    with pytest.raises(Refused, match="E_PAIR_SHAPE"):
        run(capsys, "set", "cold", "--episode", str(world.root), "--registry", str(out / "icons.json"),
            "--png", str(world.new_png("disc.png", (30, 90, 230), "disc")), "--recipe", str(world.recipe_path))
    assert (out / "icons.json").read_bytes() == before and not (out / "versions" / "icons-v002.json").exists()
