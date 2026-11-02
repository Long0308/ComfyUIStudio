"""M9a item d: the plan hashes include ``config_core_sha256`` so a contract / domain change shows in ``plan explain``."""

from __future__ import annotations

from pathlib import Path

from test_plan_support import base_config, mix_plan, record, rows, run, sha, write_version

OLD, NEW = sha("core-old"), sha("core-new")


def _pair(tmp_path: Path, old: str | None, new: str | None, target: str = "review") -> dict:
    d_old = write_version(tmp_path, "old", base_config(), plan=mix_plan(), record=record(),
                          descriptor={"config_core_sha256": old} if old else None)
    d_new = write_version(tmp_path, "new", base_config(), plan=mix_plan(), record=record(),
                          descriptor={"config_core_sha256": new} if new else None)
    return run(d_old, d_new, target=target)


def test_a_core_hash_change_is_listed_and_names_the_hash(tmp_path: Path) -> None:
    doc = _pair(tmp_path, OLD, NEW)
    assert doc["old"]["config_core_sha256"] == OLD and doc["new"]["config_core_sha256"] == NEW
    mux = rows(doc, kind="mux")["mux"]
    assert mux["status"] == "CHANGED" and any("global.config_core_sha256" in leaf for leaf in mux["leaves"])
    assert any("config_core_sha256" in w and "changed" in w for w in doc["warnings"])


def test_a_core_hash_change_never_schedules_a_gpu_job_or_a_segment(tmp_path: Path) -> None:
    doc = _pair(tmp_path, OLD, NEW, target="all")
    assert not rows(doc, kind="motion.h3", status="CHANGED") and doc["summary"]["gpu_jobs_need_approval"] == []
    assert not rows(doc, kind="composite.segment", status="CHANGED")


def test_the_same_core_hash_changes_nothing(tmp_path: Path) -> None:
    doc = _pair(tmp_path, OLD, OLD)
    assert {r["status"] for r in doc["rows"]} == {"UNCHANGED"} and not any("config_core_sha256" in w for w in doc["warnings"])


def test_a_core_hash_declared_on_one_side_only_is_noted(tmp_path: Path) -> None:
    doc = _pair(tmp_path, None, NEW)
    assert any("config_core_sha256" in w and "one side" in w for w in doc["warnings"])


def test_neither_side_declaring_it_is_the_old_behaviour(tmp_path: Path) -> None:
    doc = _pair(tmp_path, None, None)
    assert {r["status"] for r in doc["rows"]} == {"UNCHANGED"} and doc["old"]["config_core_sha256"] is None
