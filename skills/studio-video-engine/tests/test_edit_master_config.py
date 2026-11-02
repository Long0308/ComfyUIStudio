"""``jjv edit master-config``: producer of the master-config the master adapter reads (synthetic inputs, no render, no GPU)."""

from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.core.errors import Refused
from engine.edit import master_config as mc
from engine.edit import master_config_cli as cli

FPS = 24
CONTRACT = mc.Contract(3840, 2160, FPS, Fraction(24), 100, 10)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


@pytest.fixture()
def world(tmp_path: Path) -> SimpleNamespace:
    root = tmp_path / "ep"
    clip = put(root / "clips" / "S01_A-review.mp4", b"review-clip")
    native = put(root / "clips" / "S01_A-native.mp4", b"native-clip")
    review = {"episode_id": "E1", "fps": FPS, "main_frames": 100, "end_hold_frames": 10, "total_frames": 110,
              "dialogue": [{"id": "S01", "start_frame": 0, "duration_frames": 50, "segments": [
                  {"shot": "S01_A", "start_frame": 0, "duration_frames": 50, "native_frames": 40,
                   "clip": {"path": "clips/S01_A-review.mp4", "sha256": sha(clip)}}]}],
              "motion": {"transitions": [{"id": "T50", "boundary": 50, "outgoing_tail": {
                  "shot": "S01_A", "editorial_frames": 40, "native_frames": 48, "tail_output_frames": 6, "start_from_frame": 40,
                  "native_path": "clips/S01_A-native.mp4", "native_sha256": sha(native)}}]}}
    events = {"transitions": [{"id": "T50"}]}
    runs = tmp_path / "runs"
    core = put(runs / "S01_A" / "S01_A-core.mp4", b"core-4k")
    shot = {"status": "COMPLETED", "shot_id": "S01_A", "path": str(core), "sha256": sha(core), "frame_count": 40}
    put(runs / "S01_A" / "shot.json", json.dumps(shot).encode())
    tail = put(tmp_path / "tails" / "S01_A-tail.mp4", b"tail-4k")
    tail_map = {"schema": "jjv/master-tail-map/v1", "tails": [{"transition": "T50", "clip": "S01_A-tail.mp4", "clip_sha256": sha(tail),
                                                                "native_first": 40, "frames": 8}]}
    put(tmp_path / "tails" / "MASTER-TAIL-MAP.json", json.dumps(tail_map).encode())
    return SimpleNamespace(root=root, review=review, events=events, runs=runs, tail_map=tmp_path / "tails" / "MASTER-TAIL-MAP.json",
                           tmp=tmp_path, clip=clip, core=core)


def build(w: SimpleNamespace, **over):
    kw = {"episode_root": w.root, "runs_dir": w.runs, "tail_map": w.tail_map, **over}
    return mc.build_master_config(w.review, w.events, CONTRACT, **kw)


def test_final_master_binds_core_and_tail_by_hash(world) -> None:
    doc = build(world)
    seg = doc["dialogue"][0]["segments"][0]
    assert doc["master_ready"] is True and doc["build_mode"] == "master" and doc["missing_shots"] == [] and doc["missing_tails"] == []
    assert seg["source_kind"] == "shot-final-4k" and seg["sha256"] == sha(world.core) and seg["relative_start_frame"] == 0
    tail = doc["motion"]["transitions"][0]
    assert tail["tail_source"]["kind"] == "tail-core-4k" and tail["tail_source"]["receipt"] == str(world.tail_map)
    assert tail["outgoing_tail"]["start_from_frame"] == 0 and tail["outgoing_tail"]["review_start_from_frame"] == 40
    assert doc["master_contract"]["main_frames"] == 100 and doc["master_contract"]["native_restored_fps"] == "24/1"


def test_final_refuses_naming_every_missing_input(world) -> None:
    with pytest.raises(Refused) as caught:
        build(world, runs_dir=None, tail_map=None)
    text = str(caught.value)
    assert "S01_A: no final shot receipt" in text and "T50: no row for this transition in the tail map" in text


def test_preview_binds_review_clip_and_is_not_ready(world) -> None:
    doc = build(world, runs_dir=None, tail_map=None, preview=True)
    seg = doc["dialogue"][0]["segments"][0]
    assert doc["master_ready"] is False and doc["build_mode"] == "preview" and doc["missing_shots"] == ["S01_A"] and doc["missing_tails"] == ["T50"]
    assert seg["source_kind"] == "editorial-preview" and seg["sha256"] == sha(world.clip) and seg["preview_only"] is True
    assert doc["motion"]["transitions"][0]["tail_source"]["kind"] == "preview_only_tail"


def test_changed_core_bytes_are_refused(world) -> None:
    world.core.write_bytes(b"tampered")
    with pytest.raises(Refused, match="S01_A final core: sha256 differs"):
        build(world)


def test_shot_receipt_must_sit_beside_the_core(world) -> None:
    moved = put(world.tmp / "elsewhere" / "core.mp4", b"core-4k")
    receipt = json.loads((world.runs / "S01_A" / "shot.json").read_text())
    receipt.update(path=str(moved), sha256=sha(moved))
    (world.runs / "S01_A" / "shot.json").write_text(json.dumps(receipt))
    with pytest.raises(Refused, match="must sit in the folder of the final core"):
        build(world)


def test_contract_must_match_the_build(world) -> None:
    with pytest.raises(Refused, match="main_frames 100 != contract 99"):
        mc.build_master_config(world.review, world.events, mc.Contract(3840, 2160, FPS, Fraction(24), 99, 10), episode_root=world.root,
                               runs_dir=world.runs, tail_map=world.tail_map)


def test_contract_from_config_names_what_is_missing() -> None:
    bare = SimpleNamespace(episode={"contract": {"fps": 24}}, domain={})
    with pytest.raises(Refused, match="domain.delivery.master.width.*episode.contract.main_frames"):
        mc.contract_from_config(bare)
    with pytest.raises(Refused, match="no contract"):
        mc.contract_from_config(SimpleNamespace(episode={}, domain={}))


def args_for(w: SimpleNamespace, build_dir: Path, **over) -> argparse.Namespace:
    base = {"episode": "E1", "build": str(build_dir), "runs": str(w.runs), "tail_map": str(w.tail_map), "variants": None, "preview": False, "out": None}
    return argparse.Namespace(**{**base, **over})


def resolver(w: SimpleNamespace):
    config = SimpleNamespace(episode={"contract": {"fps": FPS, "main_frames": 100, "end_card_frames": 10}}, config_sha256="c" * 64, episode_root=str(w.root),
                             domain={"delivery": {"master": {"width": 3840, "height": 2160}}, "frame_rates": {"native_fps": "24/1"}})
    return lambda ref: config


def write_build(w: SimpleNamespace) -> Path:
    folder = w.tmp / "build"
    put(folder / cli.REVIEW_NAME, json.dumps(w.review).encode())
    put(folder / cli.EVENTS_NAME, json.dumps(w.events).encode())
    return folder


def test_cli_writes_once_and_names_a_missing_build_file(world, capsys) -> None:
    empty = world.tmp / "empty"
    empty.mkdir()
    assert cli.run_master_config(args_for(world, empty), resolve=resolver(world)) == 1
    assert "review-config.json missing" in capsys.readouterr().err and not (empty / cli.OUT_NAME).exists()
    folder = write_build(world)
    assert cli.run_master_config(args_for(world, folder), resolve=resolver(world)) == 0
    summary = json.loads(capsys.readouterr().out)
    out = folder / cli.OUT_NAME
    assert summary["master_ready"] is True and summary["sha256"] == sha(out)
    assert json.loads(out.read_text())["inputs"]["review_config_sha256"] == sha(folder / cli.REVIEW_NAME)
    assert cli.run_master_config(args_for(world, folder), resolve=resolver(world)) == 0  # identical bytes: idempotent


def test_cli_final_without_runs_refuses_and_writes_nothing(world, capsys) -> None:
    folder = write_build(world)
    assert cli.run_master_config(args_for(world, folder, runs=None, tail_map=None), resolve=resolver(world)) == 1
    assert "no final shot receipt" in capsys.readouterr().err and not (folder / cli.OUT_NAME).exists()
    assert cli.run_master_config(args_for(world, folder, runs=None, tail_map=None, preview=True), resolve=resolver(world)) == 0
    assert json.loads((folder / cli.OUT_NAME).read_text())["master_ready"] is False


def test_cli_names_the_build_files_and_an_unresolvable_episode_together(world, capsys) -> None:
    empty = world.tmp / "empty2"
    empty.mkdir()

    def broken(ref: str):
        raise Refused("schema: episode: missing required property 'recipes'")

    assert cli.run_master_config(args_for(world, empty, runs=None, tail_map=None), resolve=broken) == 1
    err = capsys.readouterr().err
    assert "review-config.json missing" in err and "events.json missing" in err and "does not resolve" in err and "'recipes'" in err


# ---- M8b f3 ----------------------------------------------------------------------------
def test_relative_shot_path_is_anchored_to_the_receipt_not_the_cwd(world, monkeypatch, tmp_path) -> None:
    receipt = json.loads((world.runs / "S01_A" / "shot.json").read_text())
    receipt["path"] = "S01_A-core.mp4"
    (world.runs / "S01_A" / "shot.json").write_text(json.dumps(receipt))
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    doc = build(world)
    assert doc["master_ready"] is True
    assert doc["dialogue"][0]["segments"][0]["path"] == str(world.core.resolve())


def test_accepted_tail_map_schemas_come_from_the_recipe_not_the_engine_source() -> None:
    source = Path(mc.__file__).read_text(encoding="utf-8")
    assert "mam-r27" not in source
    assert "mam-r27-master-tail-map/v1" in mc.tail_map_schemas()
    assert "jjv/master-tail-map/v1" in mc.tail_map_schemas()


def test_tail_map_schema_in_a_custom_recipe_is_honoured(world, tmp_path) -> None:
    recipe = tmp_path / "r.json"
    recipe.write_text(json.dumps({"schema": "jjv/master-config-recipe/v1", "tail_map_schemas": ["x/y/v9"]}))
    doc = json.loads(world.tail_map.read_text())
    doc["schema"] = "x/y/v9"
    world.tail_map.write_text(json.dumps(doc))
    assert mc.tail_map_schemas(recipe) == ("jjv/master-tail-map/v1", "x/y/v9")
    with pytest.raises(Refused, match="not in"):  # default recipe does not list x/y/v9
        build(world)


def test_both_tail_problems_are_reported(world) -> None:
    world.review["motion"]["transitions"][0]["outgoing_tail"]["editorial_frames"] = 41  # offset fine; make tail map miss the row
    world.tail_map.write_text(json.dumps({"schema": "jjv/master-tail-map/v1", "tails": []}))
    with pytest.raises(Refused) as err:
        build(world)
    assert "no row for this transition" in str(err.value) and "no 4K tail core" in str(err.value)


def test_domain_without_delivery_is_a_named_refusal() -> None:
    config = SimpleNamespace(episode={"contract": {"fps": 30, "main_frames": 1, "end_card_frames": 1}}, domain={"frame_rates": {"native_fps": 24}})
    with pytest.raises(Refused, match="domain.delivery.master.width"):
        mc.contract_from_config(config)
