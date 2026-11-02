"""CLI handlers of segments / tails (argument parsing, exit codes, JSON summaries) on the fake world."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.seedvr2 import cli_cut, segments, tails
from test_seedvr2_segments_support import fake_probe, make_world


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="jjv")
    stages = top.add_subparsers(dest="stage", required=True)
    verbs = stages.add_parser("seedvr2").add_subparsers(dest="verb", required=True)
    plan = verbs.add_parser("plan")
    cli_cut.add_plan_coverage_args(plan)
    cli_cut.register_cli(verbs)
    return top


@pytest.fixture()
def cli(tmp_path: Path, monkeypatch, capsys):
    world = make_world(tmp_path)
    reads = tmp_path / "reads.json"
    reads.write_text(json.dumps({"schema": "jjv/timeline-reads/v1", "reads": [
        {"shot": "S01_A", "start_frame": 0, "end_frame_exclusive": 40},
        {"shot": "S01_A", "start_frame": 40, "end_frame_exclusive": 43, "reason": "T40 outgoing tail",
         "source": world.source,
         "transition": {"id": "T40", "delivery_start_frame": 50, "output_frames": 3, "delivery_fps": 30}}]}))
    monkeypatch.setattr(cli_cut, "resolve_episode", lambda ref: world.config)
    for module, name in ((cli_cut, "run_segments"), (cli_cut, "plan_tails")):
        real = getattr(module, name)
        monkeypatch.setattr(module, name, lambda *a, _real=real, **k: _real(*a, probe=fake_probe,
                                                                            runner=world.runner, **k))

    def call(*argv: str) -> tuple[int, dict]:
        code = cli_cut.run(parser().parse_args(["seedvr2", *argv]))
        out = capsys.readouterr().out
        return code, json.loads(out) if out.strip() else {}

    call.world, call.reads = world, reads
    return call


def test_segments_dry_run_then_cut(cli, tmp_path: Path) -> None:
    code, dry = cli("segments", "--episode", "x", "--out", str(tmp_path / "s"), "--dry-run", "--only", "S02_A")
    assert code == 0 and dry["dry_run"] and dry["chunks"] == len(dry["segments"]) and not (tmp_path / "s").exists()
    code, done = cli("segments", "--episode", "x", "--out", str(tmp_path / "s"), "--only", "S02_A")
    assert code == 0 and done["cut"] == done["chunks"] and Path(done["receipt_path"]).is_file()


def test_segments_out_inside_comfy_is_refused(cli) -> None:
    with pytest.raises(Refused, match="ComfyUI"):
        cli("segments", "--episode", "x", "--out", str(cli.world.comfy_root / "input"))


def test_tails_plan_then_check_is_red_until_the_run_happens(cli) -> None:
    out = cli.world.root / "tails-run"
    code, dry = cli("tails", "plan", "--episode", "x", "--reads", str(cli.reads), "--out", str(out), "--dry-run")
    assert code == 0 and dry["gaps"] == 1 and not out.exists()
    code, planned = cli("tails", "plan", "--episode", "x", "--reads", str(cli.reads), "--out", str(out))
    assert code == 0 and planned["status"] == "PLANNED_NOT_RENDERED"
    with pytest.raises(Refused, match="not empty"):
        cli("tails", "plan", "--episode", "x", "--reads", str(cli.reads), "--out", str(out))
    plan_path = out / tails.TAILS_PLAN_FILE
    code, report = cli("tails", "check", "--episode", "x", "--plan", str(plan_path))
    assert code == 1 and report["ok"] is False and not report["all_pass"]


def test_tails_plan_outside_the_episode_needs_scratch(cli, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    with pytest.raises(Refused, match="outside the episode tree"):
        cli("tails", "plan", "--episode", "x", "--reads", str(cli.reads), "--out", str(outside))
    code, planned = cli("tails", "plan", "--episode", "x", "--reads", str(cli.reads), "--out", str(outside),
                        "--scratch")
    assert code == 0 and planned["segments_cut"] == 1


def test_plan_flags_parse() -> None:
    args = parser().parse_args(["seedvr2", "plan", "--reads", "r.json", "--tail-map", "a", "--tail-map", "b"])
    assert args.reads == "r.json" and args.tail_map == ["a", "b"]
