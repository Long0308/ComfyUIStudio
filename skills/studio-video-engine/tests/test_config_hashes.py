"""config_core_sha256, engine_tree_sha256 (+ receipt header, frozen --tree) and the race-free snapshot copy."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from config_fixtures import copy_snapshot, make_world
from engine import frozen
from engine.config import hashes, loader
from engine.core import provenance


def build(world):
    return loader.build_config(world.episode_file, skill_root=world.skill_root, machine_path=world.machine_path)


# ---- config_core_sha256 --------------------------------------------------------------------------------
def test_writing_shots_after_a_plan_changes_the_full_hash_but_not_the_core(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    first = build(world).config
    world.edit(world.engine_dir / "shots.json", lambda d: d["shots"][0]["clip"].update(sha256="cd" * 32))
    second = build(world).config
    assert second.config_sha256 != first.config_sha256
    assert second.config_core_sha256 == first.config_core_sha256 != ""


def test_the_core_follows_machine_domain_recipes_and_episode_but_not_stage_private_machine_blocks(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    base = build(world).config
    world.edit(world.machine_path, lambda m: m.update(voicestudio={"url": "http://127.0.0.1:9999"},
                                                     timing={"python": "py", "model_dir": "m"}, note="changed"))
    private = build(world).config
    assert private.config_core_sha256 == base.config_core_sha256 and private.config_sha256 != base.config_sha256
    world.edit(world.machine_path, lambda m: m["comfy"].update(url="http://127.0.0.1:9188"))
    assert build(world).config.config_core_sha256 != base.config_core_sha256
    world.edit(world.machine_path, lambda m: m["comfy"].update(url=base.machine["comfy"]["url"]))
    world.edit_episode(lambda d: d.update(title="Another title"))
    assert build(world).config.config_core_sha256 != base.config_core_sha256
    world.edit_episode(lambda d: d.update(title=base.episode["title"]))
    world.edit(world.data("domains/jenniejoy_cartoon_3d.json"), lambda d: d["delivery"]["review"].update(label="X"))
    assert build(world).config.config_core_sha256 != base.config_core_sha256


def test_stage_machine_sha256_is_per_block_and_rejects_unknown_stages() -> None:
    machine = {"voicestudio": {"url": "http://a"}, "timing": {"python": "p"}}
    assert hashes.stage_machine_sha256(machine, "voicestudio") != hashes.stage_machine_sha256(machine, "timing")
    assert hashes.stage_machine_sha256(machine, "audio") == hashes.stage_machine_sha256({}, "audio")
    try:
        hashes.stage_machine_sha256(machine, "comfy")
    except ValueError as error:
        assert "stage must be one of" in str(error)
    else:
        raise AssertionError("an unknown stage must be refused")


def test_an_episode_pin_must_match_the_tree_and_is_not_part_of_the_core(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    unpinned = build(world).config
    tree = provenance.engine_tree_sha256(world.skill_root)["engine_tree_sha256"]
    world.edit_episode(lambda d: d.update(engine_tree_sha256=tree))
    pinned = build(world)
    assert pinned.ok and pinned.config.config_core_sha256 == unpinned.config_core_sha256
    (world.skill_root / "recipes" / "zz-new.json").write_text("{}", encoding="utf-8")
    drift = build(world)
    assert not drift.ok and any("engine_tree_sha256 differs" in v for v in drift.violations)


# ---- engine_tree_sha256 ----------------------------------------------------------------------------------
def make_tree(root: Path) -> None:
    for name, text in {"engine/a.py": "x = 1\n", "recipes/qa/r.json": "{}", "bin/jjv.py": "pass\n",
                       "engine/sub/b.py": "y = 2\n"}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


def test_the_tree_hash_ignores_caches_tests_docs_temp_and_backup_files(tmp_path: Path) -> None:
    make_tree(tmp_path)
    clean = provenance.engine_tree_sha256(tmp_path)
    for name in ("engine/__pycache__/a.cpython-314.pyc", "engine/tests/t.py", "engine/NOTES.md",
                 "recipes/qa/.review-gates.json.0f3a.tmp", "engine/a.py.bak-20261027T000000Z", "engine/a.py~",
                 "recipes/qa/x.tmp", "bin/.hidden"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("noise", encoding="utf-8")
    assert provenance.engine_tree_sha256(tmp_path) == clean and clean["file_count"] == 4


def test_the_tree_hash_changes_on_edit_rename_add_and_remove(tmp_path: Path) -> None:
    make_tree(tmp_path)
    base = provenance.engine_tree_sha256(tmp_path)["engine_tree_sha256"]
    seen = {base}
    (tmp_path / "engine/a.py").write_text("x = 2\n", encoding="utf-8")
    seen.add(provenance.engine_tree_sha256(tmp_path)["engine_tree_sha256"])
    (tmp_path / "engine/sub/b.py").rename(tmp_path / "engine/sub/c.py")
    seen.add(provenance.engine_tree_sha256(tmp_path)["engine_tree_sha256"])
    (tmp_path / "bin/new.py").write_text("", encoding="utf-8")
    seen.add(provenance.engine_tree_sha256(tmp_path)["engine_tree_sha256"])
    (tmp_path / "bin/new.py").unlink()
    (tmp_path / "recipes/qa/r.json").unlink()
    seen.add(provenance.engine_tree_sha256(tmp_path)["engine_tree_sha256"])
    assert len(seen) == 5


def test_a_file_that_vanishes_during_the_walk_is_skipped_not_fatal(tmp_path: Path, monkeypatch) -> None:
    make_tree(tmp_path)
    real, clean = provenance.tree_files, provenance.engine_tree_sha256(tmp_path)
    monkeypatch.setattr(provenance, "tree_files", lambda root=tmp_path: [*real(root), "recipes/qa/gone.json"])
    assert provenance.engine_tree_sha256(tmp_path) == clean


def test_the_real_tree_is_stable_and_excludes_tests() -> None:
    files = provenance.tree_files()
    assert len(files) > 100 and not any("/tests/" in f or "__pycache__" in f or f.endswith(".md") for f in files)
    assert provenance.engine_tree_sha256() == provenance.engine_tree_sha256()


def test_the_receipt_header_is_opt_in_and_never_replaces_a_recorded_header(tmp_path: Path) -> None:
    make_tree(tmp_path)
    header = provenance.receipt_header(tmp_path)
    assert set(header) == {"engine_tree_sha256", "engine_tree_files"} and header["engine_tree_files"] == 4
    stamped = provenance.stamp({"schema": "x/v1", "status": "PASS"}, tmp_path)
    assert stamped["engine_tree_sha256"] == header["engine_tree_sha256"] and stamped["status"] == "PASS"
    kept = provenance.stamp({"engine_tree_sha256": "f" * 64}, tmp_path)
    assert kept["engine_tree_sha256"] == "f" * 64


def test_frozen_verify_tree_prints_the_hash_and_compares_with_the_episode_pin(tmp_path: Path, capsys) -> None:
    (tmp_path / "f.txt").write_bytes(b"abc")
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"files": [{"path": "f.txt", "sha256": hashlib.sha256(b"abc").hexdigest()}]}),
                        encoding="utf-8")
    assert frozen.run_verify(manifest, tmp_path, tree=True) == 0
    out = capsys.readouterr().out
    assert "TREE     engine_tree_sha256 " in out and "RESULT   ALL MATCH" in out
    episode = tmp_path / "episode.json"
    episode.write_text(json.dumps({"engine_tree_sha256": None}), encoding="utf-8")
    assert frozen.run_tree(str(episode)) == 0
    episode.write_text(json.dumps({"engine_tree_sha256": "0" * 64}), encoding="utf-8")
    assert frozen.run_tree(str(episode)) == 1 and "MISMATCH" in capsys.readouterr().out
    pin = provenance.engine_tree_sha256()["engine_tree_sha256"]
    episode.write_text(json.dumps({"engine_tree_sha256": pin}), encoding="utf-8")
    assert frozen.run_tree(str(episode)) == 0


# ---- the race the audit saw: a recipes/qa temp file deleted while a test copies the skill folder ---------
def test_snapshot_copy_ignores_temp_and_backup_files(tmp_path: Path) -> None:
    source = tmp_path / "src"
    for name in ("ok.json", ".ok.json.ab12.tmp", "ok.json.bak-1", "__pycache__/x.pyc", "qa/r.json"):
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_text("{}", encoding="utf-8")
    copy_snapshot(source, tmp_path / "dst")
    assert sorted(p.relative_to(tmp_path / "dst").as_posix() for p in (tmp_path / "dst").rglob("*") if p.is_file()) == [
        "ok.json", "qa/r.json"]


def test_snapshot_copy_survives_a_file_deleted_mid_copy(tmp_path: Path, monkeypatch) -> None:
    import config_fixtures

    source = tmp_path / "src"
    for name in ("a.json", "b.json", "c.json"):
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_text("{}", encoding="utf-8")
    real = config_fixtures.shutil.copy2

    def vanish(src, dst, **kw):
        if str(src).endswith("b.json"):
            raise FileNotFoundError(src)
        return real(src, dst, **kw)

    monkeypatch.setattr(config_fixtures.shutil, "copy2", vanish)
    copy_snapshot(source, tmp_path / "dst")
    assert sorted(p.name for p in (tmp_path / "dst").iterdir()) == ["a.json", "c.json"]


def test_snapshot_copy_with_a_concurrent_writer_has_no_flaky_failure(tmp_path: Path) -> None:
    source = tmp_path / "src"
    (source / "qa").mkdir(parents=True)
    (source / "qa" / "stable.json").write_text("{}", encoding="utf-8")
    stop = threading.Event()

    def writer() -> None:  # what write_once does: a dot-temp file that lives for a moment
        count = 0
        while not stop.is_set():
            temp = source / "qa" / f".review-gates.json.{count % 7}.tmp"
            temp.write_text("x", encoding="utf-8")
            temp.unlink(missing_ok=True)
            count += 1

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        for index in range(25):
            copy_snapshot(source, tmp_path / f"dst{index}")
            assert (tmp_path / f"dst{index}" / "qa" / "stable.json").is_file()
    finally:
        stop.set()
        thread.join(timeout=5)


# ---- the shared receipt writers take the header on request ----------------------------------------------------
def test_json_writers_stamp_only_when_asked(tmp_path: Path) -> None:
    from engine.core.io import read_json, write_json_atomic, write_json_once

    write_json_once(tmp_path / "plain.json", {"schema": "x/v1"}, mode="ascii")
    write_json_once(tmp_path / "evidence.json", {"schema": "x/v1"}, mode="ascii", stamp=True)
    write_json_atomic(tmp_path / "state.json", {"schema": "x/v1"}, mode="ascii", stamp=True)
    assert "engine_tree_sha256" not in read_json(tmp_path / "plain.json")
    tree = provenance.engine_tree_sha256()["engine_tree_sha256"]
    for name in ("evidence.json", "state.json"):
        stamped = read_json(tmp_path / name)
        assert stamped["engine_tree_sha256"] == tree and stamped["schema"] == "x/v1" and stamped["engine_tree_files"] > 100
