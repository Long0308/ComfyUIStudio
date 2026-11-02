"""``jjv edit review-render`` / ``master-render`` shim: argparse wiring, the node command line it builds, and its refusals (no render here)."""

from __future__ import annotations

import argparse

import pytest

from engine.core.errors import Refused
from engine.editorial import segments_edit_cli as edit


def parse(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    edit.register_cli(parser.add_subparsers(dest="stage", required=True))
    return parser.parse_args(["edit", *argv])


REVIEW = ("review-render", "--cache", "C", "--out", "film.mp4", "--episode-root", "R", "--episode", "E.json", "--boundaries", "B.json",
          "--word-timing", "W.json", "--episode-text", "T.json")


def test_review_command_carries_every_input_and_the_mode(monkeypatch) -> None:
    monkeypatch.setattr(edit.shutil, "which", lambda name: "node")
    cmd = edit.build_command(parse(*REVIEW, "--allow-outside", "logo.png", "--rehash-all", "--build-concurrency", "1", "--force-segment", "tr-T1,card-02"))
    assert cmd[1].endswith("edit-render.cjs") and cmd[2:4] == ["--mode", "review"]
    for flag, value in (("--cache", "C"), ("--out", "film.mp4"), ("--episode-root", "R"), ("--episode-json", "E.json"), ("--boundaries", "B.json"),
                        ("--word-timing", "W.json"), ("--episode-text", "T.json"), ("--allow-outside", "logo.png"), ("--build-concurrency", "1"),
                        ("--force-segment", "tr-T1,card-02")):
        assert cmd[cmd.index(flag) + 1] == value, flag
    assert "--rehash-all" in cmd and "--explain" not in cmd


def test_master_needs_the_master_config_and_maps_to_master_mode(monkeypatch) -> None:
    monkeypatch.setattr(edit.shutil, "which", lambda name: "node")
    with pytest.raises(SystemExit):
        parse("master-render", "--cache", "C", "--out", "f.mp4")  # argparse refuses: --master-config is required
    cmd = edit.build_command(parse("master-render", "--cache", "C", "--out", "f.mp4", "--master-config", "M.json", "--segments-file", "S.json"))
    assert cmd[2:4] == ["--mode", "master"] and cmd[cmd.index("--master-config") + 1] == "M.json" and cmd[cmd.index("--segments-file") + 1] == "S.json"


def test_explain_needs_no_out_but_a_build_does(monkeypatch) -> None:
    monkeypatch.setattr(edit.shutil, "which", lambda name: "node")
    explained = edit.build_command(parse("review-render", "--cache", "C", "--explain", "--episode-root", "R", "--episode-text", "T.json"))
    assert "--explain" in explained and "--out" not in explained
    with pytest.raises(Refused, match="--out FILE.mp4 is required"):
        edit.build_command(parse("review-render", "--cache", "C", "--episode-root", "R", "--episode-text", "T.json"))


def test_missing_node_is_refused_by_name(monkeypatch) -> None:
    monkeypatch.setattr(edit.shutil, "which", lambda name: None)
    with pytest.raises(Refused, match="node is not on PATH"):
        edit.build_command(parse(*REVIEW))


def test_tool_path_is_inside_the_kit_and_exists() -> None:
    assert edit.TOOL.name == "edit-render.cjs" and edit.TOOL.parent.parent.name == "remotion-kit"
    assert edit.TOOL.exists()


def test_run_edit_returns_the_node_exit_code(monkeypatch) -> None:
    monkeypatch.setattr(edit.shutil, "which", lambda name: "node")
    seen: list[list[str]] = []
    monkeypatch.setattr(edit.subprocess, "call", lambda cmd: seen.append(cmd) or 1)
    assert edit.run_edit(parse(*REVIEW)) == 1 and seen and seen[0][2:4] == ["--mode", "review"]
