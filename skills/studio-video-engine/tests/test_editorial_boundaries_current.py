"""M8b(c)-f2: boundaries.json has ONE current writer protocol: versions/ -> boundaries.json -> boundaries.current.json."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.core import provenance
from engine.core.io import read_json, sha256_file
from engine.editorial import boundaries as table
from engine.editorial import boundaries_write as bw
from engine.editorial import boundaries_current as current
from engine.editorial import presets_swap
from engine.config.loader import SKILL_ROOT
from test_editorial_boundaries_write import DOMAIN, _build
from test_transitions_swap import current as swap_current, run as swap_run, world  # noqa: F401  (fixture)

SCHEMA = SKILL_ROOT / "schemas" / "boundaries.schema.json"
RECEIPT = "boundaries.current.json"


def _changed(document: dict, frames: int) -> dict:
    other = copy.deepcopy(document)
    other["ending"]["end_card_frames"] = frames
    return other


def test_a_complete_write_stamps_a_receipt_bound_to_boundaries_json(tmp_path: Path) -> None:
    document, _ = _build()
    out = bw.write_outputs(tmp_path, document, [])
    receipt = read_json(tmp_path / RECEIPT)
    assert receipt["version"] == 1 and receipt["writer"] == "boundaries-write"
    assert receipt["path"] == "versions/boundaries-v001.json"
    assert receipt["sha256"] == sha256_file(tmp_path / "boundaries.json") and receipt["inputs_digest"]
    assert out["current_is_stale"] is False and out["current_version"] == 1


def test_the_loader_refuses_a_boundaries_json_that_no_longer_matches_its_receipt(tmp_path: Path) -> None:
    document, _ = _build()
    bw.write_outputs(tmp_path, document, [])
    assert table.load_document(tmp_path / "boundaries.json", SCHEMA, "e", DOMAIN)["episode_id"] == "e"
    (tmp_path / "boundaries.json").write_text(json.dumps(_changed(document, 61)), encoding="utf8")
    with pytest.raises(Refused, match="does not match boundaries.current.json"):
        table.load_document(tmp_path / "boundaries.json", SCHEMA, "e", DOMAIN)


def test_a_legacy_folder_without_a_receipt_loads_as_before(tmp_path: Path) -> None:
    document, _ = _build()
    (tmp_path / "boundaries.json").write_text(json.dumps(document), encoding="utf8")
    assert table.load_document(tmp_path / "boundaries.json", SCHEMA, "e", DOMAIN)["episode_id"] == "e"


def test_a_draft_run_leaves_the_current_files_alone_and_reports_the_stale_final(tmp_path: Path) -> None:
    document, _ = _build()
    bw.write_outputs(tmp_path, document, [])
    before = (sha256_file(tmp_path / "boundaries.json"), current.receipt_identity(read_json(tmp_path / RECEIPT)))
    draft = bw.write_outputs(tmp_path, _changed(document, 61), ["icons missing"])
    # STAMP-2: the receipt now carries engine_tree_sha256, so its BYTES name the engine that wrote it, not the
    # boundaries it certifies; "unchanged" is therefore asserted on its identity (schema + version, path, sha256,
    # writer, inputs_digest).  The bytes are pinned separately for a no-op publish under another engine tree below.
    assert (sha256_file(tmp_path / "boundaries.json"), current.receipt_identity(read_json(tmp_path / RECEIPT))) == before
    assert draft["complete"] is False and draft["current_version"] == 1 and draft["current_is_stale"] is True
    same = bw.write_outputs(tmp_path, document, ["icons missing"])
    assert same["current_is_stale"] is False


def test_versions_use_max_suffix_plus_one_when_there_are_gaps(tmp_path: Path) -> None:
    document, _ = _build()
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "boundaries-v001.json").write_text("{}", encoding="utf8")
    (versions / "boundaries-v003.json").write_text("{}", encoding="utf8")
    out = bw.write_outputs(tmp_path, document, [])
    assert out["version"] == 4 and out["reused"] is False
    assert read_json(tmp_path / RECEIPT)["version"] == 4


def test_identical_content_names_the_version_that_holds_it_even_with_a_gap(tmp_path: Path) -> None:
    document, _ = _build()
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "boundaries-v001.json").write_text("{}", encoding="utf8")
    first = bw.write_outputs(tmp_path, document, [])
    again = bw.write_outputs(tmp_path, document, [])
    assert first["version"] == 2 and again["version"] == 2 and again["reused"] is True


def test_a_swap_publishes_the_same_receipt_and_the_loader_follows_it(world) -> None:  # noqa: F811
    swap_run(world, "T120", "cut")
    workspace = world[4]
    receipt = read_json(workspace / RECEIPT)
    assert receipt["writer"] == "presets-swap" and receipt["version"] == 2
    assert receipt["path"] == "versions/boundaries-v002.json"
    assert receipt["sha256"] == sha256_file(workspace / "boundaries.json")
    (workspace / "boundaries.json").write_text(json.dumps(swap_current(world)) + " ", encoding="utf8")
    with pytest.raises(Refused, match="does not match boundaries.current.json"):
        swap_run(world, "T150", "cut")


# ---- M8b(c)-f3 ------------------------------------------------------------------------------------------------------
def _fail_on(monkeypatch, module, name: str, target: str) -> None:
    real = getattr(module, name)

    def broken(path, *args, **kwargs):
        if Path(path).name == target:
            raise OSError("simulated crash")
        return real(path, *args, **kwargs)
    monkeypatch.setattr(module, name, broken)


def test_a_crash_between_boundaries_json_and_the_first_receipt_is_not_read_as_legacy(tmp_path: Path, monkeypatch) -> None:
    document, _ = _build()
    with monkeypatch.context() as patch:
        _fail_on(patch, current, "write_json_atomic", RECEIPT)
        with pytest.raises(OSError):
            bw.write_outputs(tmp_path, document, [])
    assert (tmp_path / "boundaries.json").is_file() and not (tmp_path / RECEIPT).exists()
    with pytest.raises(Refused, match="interrupted publish"):
        table.load_document(tmp_path / "boundaries.json", SCHEMA, "e", DOMAIN)
    bw.write_outputs(tmp_path, document, [])          # the identical publish completes it and clears the marker
    assert not (tmp_path / "boundaries.publishing").exists()
    assert table.load_document(tmp_path / "boundaries.json", SCHEMA, "e", DOMAIN)["episode_id"] == "e"


def test_a_draft_with_no_receipt_reports_staleness_as_unknown(tmp_path: Path) -> None:
    document, _ = _build()
    draft = bw.write_outputs(tmp_path, document, ["icons missing"])
    assert draft["current_version"] is None and draft["current_is_stale"] is None


def test_swap_versions_use_the_shared_max_suffix_allocator(world) -> None:  # noqa: F811
    swap_run(world, "T150", "dip_black")
    (world[4] / "versions" / "boundaries-v005.json").write_text("{}", encoding="utf8")
    summary = swap_run(world, "T180", "cut")
    assert summary["version"] == 6 and read_json(world[4] / RECEIPT)["version"] == 6


def test_a_crash_between_the_receipt_and_the_swap_log_is_repaired_by_an_identical_retry(world, monkeypatch) -> None:  # noqa: F811
    with monkeypatch.context() as patch:
        _fail_on(patch, presets_swap, "write_json_atomic", "swap-log.json")
        with pytest.raises(OSError):
            swap_run(world, "T150", "dip_black")
    workspace = world[4]
    assert read_json(workspace / RECEIPT)["version"] == 2 and not (workspace / "swap-log.json").exists()
    again = swap_run(world, "T150", "dip_black")
    assert again["unchanged"] is True
    assert [v["version"] for v in read_json(workspace / "swap-log.json")["versions"]] == [1, 2]


def test_a_swap_interrupted_inside_publish_is_completed_by_the_retry_and_the_log_follows(world, monkeypatch) -> None:  # noqa: F811
    with monkeypatch.context() as patch:
        _fail_on(patch, current, "write_json_atomic", RECEIPT)
        with pytest.raises(OSError):
            swap_run(world, "T150", "dip_black")
    workspace = world[4]
    assert (workspace / "boundaries.publishing").is_file()
    assert swap_run(world, "T150", "dip_black")["unchanged"] is True
    assert not (workspace / "boundaries.publishing").exists()
    assert read_json(workspace / RECEIPT)["version"] == 2 and read_json(workspace / RECEIPT)["sha256"] == sha256_file(workspace / "boundaries.json")
    assert [v["version"] for v in read_json(workspace / "swap-log.json")["versions"]] == [1, 2]


def test_the_swap_reads_its_workspace_through_the_full_loader_checks(world) -> None:  # noqa: F811
    swap_run(world, "T150", "dip_black")
    workspace = world[4]
    (workspace / RECEIPT).unlink()                       # legacy folder: only the loader's own checks are left
    other = swap_current(world)
    other["episode_id"] = "another-episode"
    (workspace / "boundaries.json").write_text(json.dumps(other), encoding="utf8")
    with pytest.raises(Refused, match="episode_id"):
        swap_run(world, "T180", "cut")


# ---- STAMP-2: the receipt and the marker say which engine tree wrote them ----------------------------------------
def _tree(monkeypatch, name: str) -> str:
    digest = (name * 64)[:64]
    monkeypatch.setattr(provenance, "receipt_header",
                        lambda skill_root=None: {"engine_tree_sha256": digest, "engine_tree_files": 1})
    return digest


def test_the_receipt_carries_the_engine_tree_that_wrote_it(tmp_path: Path) -> None:
    document, _ = _build()
    bw.write_outputs(tmp_path, document, [])
    receipt = read_json(tmp_path / RECEIPT)
    assert receipt["engine_tree_sha256"] == provenance.engine_tree_sha256()["engine_tree_sha256"]
    assert receipt["engine_tree_files"] == provenance.engine_tree_sha256()["file_count"]
    assert receipt["sha256"] == sha256_file(tmp_path / "boundaries.json")


def test_the_marker_of_an_interrupted_publish_carries_the_engine_tree(tmp_path: Path, monkeypatch) -> None:
    document, _ = _build()
    tree = _tree(monkeypatch, "a")
    with monkeypatch.context() as patch:
        _fail_on(patch, current, "write_json_atomic", RECEIPT)
        with pytest.raises(OSError):
            bw.write_outputs(tmp_path, document, [])
    marker = read_json(tmp_path / "boundaries.publishing")
    assert marker["engine_tree_sha256"] == tree and marker["version"] == 1 and marker["writer"] == "boundaries-write"


def test_a_no_op_publish_under_another_engine_tree_keeps_the_receipt_bytes(tmp_path: Path, monkeypatch) -> None:
    document, _ = _build()
    first = _tree(monkeypatch, "a")
    bw.write_outputs(tmp_path, document, [])
    before = (tmp_path / RECEIPT).read_bytes()
    _tree(monkeypatch, "b")
    again = bw.write_outputs(tmp_path, document, [])
    assert again["reused"] is True and (tmp_path / RECEIPT).read_bytes() == before
    assert read_json(tmp_path / RECEIPT)["engine_tree_sha256"] == first
    assert not (tmp_path / "boundaries.publishing").exists()


def test_a_real_publish_under_another_engine_tree_writes_a_fresh_stamp(tmp_path: Path, monkeypatch) -> None:
    document, _ = _build()
    _tree(monkeypatch, "a")
    bw.write_outputs(tmp_path, document, [])
    second = _tree(monkeypatch, "b")
    out = bw.write_outputs(tmp_path, _changed(document, 61), [])
    receipt = read_json(tmp_path / RECEIPT)
    assert out["version"] == 2 and receipt["version"] == 2 and receipt["engine_tree_sha256"] == second
    assert receipt["sha256"] == sha256_file(tmp_path / "boundaries.json")


def test_a_receipt_with_the_same_content_but_another_schema_is_rewritten(tmp_path: Path, monkeypatch) -> None:
    document, _ = _build()
    bw.write_outputs(tmp_path, document, [])
    old = read_json(tmp_path / RECEIPT)
    (tmp_path / RECEIPT).write_text(json.dumps({**old, "schema": "jjv/boundaries-current/v0"}), encoding="utf8")
    tree = _tree(monkeypatch, "c")
    bw.write_outputs(tmp_path, document, [])
    receipt = read_json(tmp_path / RECEIPT)
    assert receipt["schema"] == current.RECEIPT_SCHEMA and receipt["engine_tree_sha256"] == tree


def test_an_unreadable_receipt_is_replaced_by_a_publish(tmp_path: Path) -> None:
    document, _ = _build()
    bw.write_outputs(tmp_path, document, [])
    (tmp_path / RECEIPT).write_text("{not json", encoding="utf8")
    bw.write_outputs(tmp_path, document, [])
    assert read_json(tmp_path / RECEIPT)["sha256"] == sha256_file(tmp_path / "boundaries.json")
