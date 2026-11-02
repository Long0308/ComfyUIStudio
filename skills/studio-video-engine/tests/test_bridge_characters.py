"""``jjv bridge library-stage``: copies current character library images write-once, writes the step-UI JSON (tmp dirs only)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from engine.bridge import characters, cli as bridge_cli
from engine.core.errors import Refused
from images_fixtures import World, make_png, sha

DOMAIN = "dom_x"


@pytest.fixture()
def lib(tmp_path):
    world = World(tmp_path / "w")
    root = tmp_path / "library"
    made = {}
    for char, colour in (("CHAR_01", 10), ("CHAR_02", 20)):
        for kind in ("FACE", "ACTION"):
            made[(char, kind)] = make_png(root / char / kind / f"01_01_{kind}__aa{colour}.png", (colour, 0 if kind == "FACE" else 7, 0), (16, 16))
            (root / char / kind / f"01_01_{kind}__aa{colour}.prompt.txt").write_text("prompt", "utf-8")
        make_png(root / char / "FACE_r005b_rejected" / "rejected.png", (255, 0, 0), (16, 16))  # never staged
    make_png(root / "CHAR_02" / "ACTION" / "extra.png", (99, 0, 0), (16, 16))
    bible = tmp_path / "bible.json"
    bible.write_text(json.dumps({"characters": [{"id": "CHAR_01", "name": "Nguyễn Văn Minh"}]}), "utf-8")
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"verdicts": {sha(made[("CHAR_01", "FACE")]): "pass"}}), "utf-8")
    config = {DOMAIN: {"library_root": str(root), "bible": str(bible), "stage_subdir": "chars",
                       "ui_data": str(tmp_path / "ui"), "qa_ledger": str(ledger)}}
    return world, config, made


def test_stage_counts_copies_write_once_and_never_reads_rejected(lib, tmp_path):
    world, config, made = lib
    done = characters.stage(config, DOMAIN, world.machine_path)
    assert done["counts"] == {"CHAR_01": {"face": 1, "action": 1}, "CHAR_02": {"face": 1, "action": 2}}
    written = json.loads((tmp_path / "ui" / f"{DOMAIN}.json").read_text("utf-8"))
    assert written["schema"] == characters.SCHEMA and written["domain"] == DOMAIN
    assert written["characters"]["CHAR_01"]["name"] == "Nguyễn Văn Minh" and written["characters"]["CHAR_02"]["name"] is None
    assert "rejected" not in json.dumps(written)
    for char in written["characters"].values():
        for row in char["face"] + char["action"]:
            staged = world.comfy_root / "input" / row["file"]
            assert staged.is_file() and sha(staged) == row["sha256"] and row["file"].startswith(f"chars/CHAR_0")
    assert all(p.is_file() for p in made.values())  # originals stay
    characters.stage(config, DOMAIN, world.machine_path)  # idempotent
    staged = world.comfy_root / "input" / written["characters"]["CHAR_01"]["face"][0]["file"]
    staged.write_bytes(b"tampered")
    with pytest.raises(Refused, match="refusing to overwrite"):
        characters.stage(config, DOMAIN, world.machine_path)


def test_qa_is_the_ledger_verdict_or_null_never_invented(lib):
    world, config, made = lib
    chars = characters.stage(config, DOMAIN, world.machine_path)["characters"]
    assert chars["CHAR_01"]["face"][0]["qa"] == "pass" and chars["CHAR_01"]["action"][0]["qa"] is None
    del config[DOMAIN]["qa_ledger"]
    chars = characters.stage(config, DOMAIN, world.machine_path)["characters"]
    assert chars["CHAR_01"]["face"][0]["qa"] is None


def test_missing_config_or_library_is_refused(lib, tmp_path):
    world, config, _ = lib
    with pytest.raises(Refused, match="no characters block"):
        characters.stage({}, DOMAIN, world.machine_path)
    config[DOMAIN]["library_root"] = str(tmp_path / "nope")
    with pytest.raises(Refused, match="library_root not found"):
        characters.stage(config, DOMAIN, world.machine_path)


def test_library_stage_cli_verb(lib, tmp_path, capsys):
    world, config, _ = lib
    state = tmp_path / "state"
    state.mkdir()
    (state / "config.json").write_text(json.dumps({"accounts": ["acct3"], "characters": config}), "utf-8")
    args = argparse.Namespace(verb="library-stage", domain=DOMAIN, state_dir=str(state), machine=str(world.machine_path))
    assert bridge_cli.run_bridge(args) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["CHAR_02"] == {"face": 1, "action": 2}
