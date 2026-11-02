"""``engine.core.paths.resolve_data_path``: a path recorded by hash-bound data under a retired root is read where the tree
lives now (``machine.legacy_roots``); the data file itself is never edited.  Plus the machine schema key and the hash rule
(the key is a location fact, not render content: outside ``config_core_sha256``)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from config_fixtures import make_world
from engine.config import loader
from engine.config.schema import validate
from engine.core import paths


def _tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """``(old_root, new_root, file under new_root)``: the old root does not exist, the new one holds the file."""
    old_root, new_root = tmp_path / "old-root" / "03 Voice", tmp_path / "new-root" / "03 Voice"
    target = new_root / "ep" / "mix-plan.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    return old_root, new_root, target


def _machine(old_root: Path, new_root: Path) -> dict:
    return {"legacy_roots": {str(old_root): str(new_root)}}


def test_a_missing_path_under_a_legacy_root_is_read_where_it_lives_now(tmp_path: Path) -> None:
    old_root, new_root, target = _tree(tmp_path)
    given = old_root / "ep" / "mix-plan.json"
    assert not given.exists()
    assert paths.resolve_data_path(given, _machine(old_root, new_root)) == target
    assert paths.resolve_data_path(str(given), _machine(old_root, new_root)) == target


def test_an_existing_path_is_returned_as_it_is_even_when_it_matches_a_legacy_root(tmp_path: Path) -> None:
    old_root, new_root, target = _tree(tmp_path)
    assert paths.resolve_data_path(target, _machine(new_root, old_root)) == target


def test_a_path_that_is_missing_on_both_sides_or_matches_no_root_is_returned_unchanged(tmp_path: Path) -> None:
    old_root, new_root, _target = _tree(tmp_path)
    machine = _machine(old_root, new_root)
    missing = old_root / "ep" / "nowhere.json"
    assert paths.resolve_data_path(missing, machine) == missing           # the caller's error names the recorded path
    other = tmp_path / "elsewhere" / "ep" / "mix-plan.json"
    assert paths.resolve_data_path(other, machine) == other
    assert paths.resolve_data_path(Path("ep/mix-plan.json"), machine) == Path("ep/mix-plan.json")   # relative: untouched
    assert paths.resolve_data_path(missing, {}) == missing and paths.resolve_data_path(missing, None) == missing


def test_the_root_must_match_a_whole_path_component(tmp_path: Path) -> None:
    old_root, new_root, _target = _tree(tmp_path)
    sibling = Path(str(old_root) + "X") / "ep" / "mix-plan.json"      # "...\\03 VoiceX\\..." is not under "...\\03 Voice"
    assert paths.resolve_data_path(sibling, _machine(old_root, new_root)) == sibling


@pytest.mark.skipif(os.name != "nt", reason="drive-letter case and separator folding are Windows semantics")
def test_on_windows_the_prefix_matches_case_insensitively_and_across_separators(tmp_path: Path) -> None:
    old_root, new_root, target = _tree(tmp_path)
    machine = _machine(old_root, new_root)
    swapped = str(old_root).swapcase().replace("\\", "/") + "/ep/mix-plan.json"
    assert paths.resolve_data_path(swapped, machine) == target


def test_without_an_explicit_machine_the_default_machine_file_supplies_the_roots(tmp_path: Path, monkeypatch) -> None:
    old_root, new_root, target = _tree(tmp_path)
    machine_file = tmp_path / "machine.json"
    machine_file.write_text(json.dumps(_machine(old_root, new_root)), encoding="utf-8")
    monkeypatch.setattr(loader, "DEFAULT_MACHINE_PATH", machine_file)
    given = old_root / "ep" / "mix-plan.json"
    assert paths.resolve_data_path(given) == target
    machine_file.write_text(json.dumps({"legacy_roots": {}}), encoding="utf-8")     # edited file: re-read, not cached
    assert paths.resolve_data_path(given) == given
    monkeypatch.setattr(loader, "DEFAULT_MACHINE_PATH", tmp_path / "no-such-machine.json")
    assert paths.resolve_data_path(given) == given                                   # no machine file: never an error


def test_the_shipped_machine_file_names_the_retired_roots_without_hardcoding_them_in_code() -> None:
    machine = json.loads(loader.DEFAULT_MACHINE_PATH.read_text(encoding="utf-8"))
    roots = machine.get("legacy_roots")
    assert isinstance(roots, dict) and roots, "machine.json must carry legacy_roots (old absolute root -> current root)"
    for old, new in roots.items():
        assert Path(old).is_absolute() and Path(new).is_absolute(), (old, new)
    source = (Path(paths.__file__)).read_text(encoding="utf-8")
    for old in roots:
        assert old.split(os.sep)[0] not in source and old.replace("\\", "/") not in source, "no drive letter in code"


# ---- schema + hashes --------------------------------------------------------------------------------------------------
def _schema() -> dict:
    return json.loads((loader.SKILL_ROOT / "schemas" / "machine.schema.json").read_text(encoding="utf-8"))


def test_machine_schema_accepts_legacy_roots_as_a_string_map_only() -> None:
    base = json.loads(loader.DEFAULT_MACHINE_PATH.read_text(encoding="utf-8"))
    assert validate({**base, "legacy_roots": {"D:\\old": "J:\\new"}}, _schema()) == []
    assert validate({**base, "legacy_roots": {}}, _schema()) == []
    assert validate({k: v for k, v in base.items() if k != "legacy_roots"}, _schema()) == []     # optional
    assert validate({**base, "legacy_roots": {"D:\\old": 3}}, _schema())
    assert validate({**base, "legacy_roots": [["D:\\old", "J:\\new"]]}, _schema())
    assert validate({**base, "legacy_roots": {"": "J:\\new"}}, _schema())
    assert validate({**base, "legacy_roots": {"D:\\old": ""}}, _schema())


def test_legacy_roots_change_the_full_config_hash_but_not_the_core(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    build = lambda: loader.build_config(world.episode_file, skill_root=world.skill_root,  # noqa: E731
                                        machine_path=world.machine_path).config
    base = build()
    world.edit(world.machine_path, lambda m: m.update(legacy_roots={"Q:\\retired": "R:\\current"}))
    moved = build()
    assert moved.config_core_sha256 == base.config_core_sha256 != ""
    assert moved.config_sha256 != base.config_sha256
