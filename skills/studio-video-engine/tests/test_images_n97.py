"""N97: marker N87 theo (nhãn, pid), base_label chỉ gộp biến thể <base-có-chữ-số><chữ>, lane chết trước LANE_START hiện 'dead'."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from engine.images import library_run, library_status, pool
from engine.images.lease import holder_path

from tests.test_images_library_locks import holders, make_plan  # noqa: F401  (fixture `holders`)


def _two_lane_plan(tmp_path: Path) -> tuple[dict, str]:
    plan, state = make_plan(tmp_path)
    plan["lanes"].append({"label": "a2", "codex_home": plan["lanes"][0]["codex_home"]})
    return plan, state


def test_sibling_lane_markers_do_not_overwrite_each_other(tmp_path, holders, monkeypatch):  # noqa: F811
    plan, state = _two_lane_plan(tmp_path)
    proc = holders(pool.label_lock_path(Path(state), "a1"))  # lane a1 giữ khoá nhãn a1 (pid thật)
    monkeypatch.setattr(library_run.os, "getpid", lambda: proc.pid)
    first = library_run.write_n87_markers(tmp_path / "plan.json", plan, state, "a1")
    monkeypatch.setattr(library_run.os, "getpid", lambda: proc.pid + 100000)  # lane anh em a2 khởi động sau
    second = library_run.write_n87_markers(tmp_path / "plan.json", plan, state, "a2")
    assert library_run.home_conflicts(plan, state) == []  # marker của a1 phải còn hợp lệ với holder a1
    library_run.require_n87_homes(plan, state)
    library_run.clear_n87_markers(second)  # anh em dọn: không được xoá marker của lane a1
    assert library_run.home_conflicts(plan, state) == []
    assert all(Path(p).exists() for p in first if proc.pid == json.loads(Path(p).read_text(encoding="ascii"))["pid"])


def test_clear_only_removes_markers_owned_by_this_pid(tmp_path, monkeypatch):
    plan, state = _two_lane_plan(tmp_path)
    monkeypatch.setattr(library_run.os, "getpid", lambda: 111)
    mine = library_run.write_n87_markers(tmp_path / "plan.json", plan, state, "a1")
    monkeypatch.setattr(library_run.os, "getpid", lambda: 222)
    other = library_run.write_n87_markers(tmp_path / "plan.json", plan, state, "a2")
    library_run.clear_n87_markers(other)
    assert all(Path(p).exists() for p in mine)
    assert not any(Path(p).exists() for p in other)


def test_base_label_does_not_merge_unrelated_account_with_letter_suffix():
    labels = {"acct", "acctb"}
    assert pool.base_label("acctb", labels) == "acctb"
    assert pool.base_label("acct", labels) == "acct"


def test_base_label_keeps_numbered_variants():
    labels = {"acct3", "acct3b", "acct3c", "acct4", "acct4b"}
    assert pool.base_label("acct3b", labels) == "acct3"
    assert pool.base_label("acct3c", labels) == "acct3"
    assert pool.base_label("acct4b", labels) == "acct4"
    assert pool.base_label("acct3", labels) == "acct3"


def test_lane_dead_before_lane_start_is_dead_after_holder_removed():
    case_dir = Path(".pytest_work_tmp") / f"N97-case-{uuid4().hex}"
    case_dir.mkdir(parents=True)
    run_dir = case_dir / "run"
    plan = {"rev": "r005", "batches": {"batch-01": {"items": [{"prompt_id": "P1", "char": "C", "kind": "FACE", "prompt_sha256": None}]}},
            "lanes": [{"label": "died", "account": "a", "variant": False, "batches": ["batch-01"]},
                      {"label": "never", "account": "b", "variant": False, "batches": ["batch-01"]}]}
    run = {"lanes": {n: {"batches": [{"batch_id": "batch-01", "prompt_ids": ["P1"]}]} for n in ("died", "never")}}
    try:
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        library_run.write_launch_record(run_dir, "died", dead.pid)  # spawn_lane ghi trước khi tiến trình con chạy
        assert not holder_path(library_status.lane_lock_path(run_dir, "died")).exists()  # lease.py đã gỡ .holder
        status = library_status.build_status(case_dir / "plan.json", plan, run_dir, run, library_out=None)
        assert {l["label"]: l["state"] for l in status["lanes"]} == {"died": "dead", "never": "pending"}
    finally:
        shutil.rmtree(case_dir)


def test_lane_just_spawned_and_alive_is_not_dead():
    case_dir = Path(".pytest_work_tmp") / f"N97-live-{uuid4().hex}"
    case_dir.mkdir(parents=True)
    run_dir = case_dir / "run"
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        library_run.write_launch_record(run_dir, "starting", live.pid)
        assert library_status.lane_launched(run_dir, "starting") is False  # còn sống, chưa lấy khoá => chưa phải dead
    finally:
        live.kill()
        live.wait()
        shutil.rmtree(case_dir)
