"""N94: khoá codex_home chung chỉ cho phép holder mang dấu N87; ``_copy_queues`` chép đúng queue plan nêu."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.images import library_run, pool

ROOT = Path(__file__).resolve().parents[1]
HOLD = ("import sys; sys.path.insert(0, sys.argv[2])\n"
        "from pathlib import Path\nfrom engine.images.lease import lease\n"
        "with lease(Path(sys.argv[1]), timeout_seconds=0):\n    print('ready', flush=True); sys.stdin.readline()\n")


def make_plan(tmp_path: Path) -> tuple[dict, str]:
    home = tmp_path / "home1"
    home.mkdir()
    machine = tmp_path / "machine.json"
    machine.write_text(json.dumps({"images": {"codex_accounts": [{"label": "a1", "codex_home": str(home)},
                                                                   {"label": "a2", "codex_home": str(home)}]}}), encoding="utf-8")
    plan = {"machine": str(machine), "rev": "r9", "lanes": [{"label": "a1", "codex_home": str(home)}]}
    return plan, str(tmp_path / "pool-state.json")


@pytest.fixture
def holders():
    procs: list[subprocess.Popen] = []

    def hold(lock: Path) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c", HOLD, str(lock), str(ROOT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        assert proc.stdout.readline().strip() == "ready"
        procs.append(proc)
        return proc

    yield hold
    for proc in procs:
        proc.stdin.close()
        proc.wait(timeout=10)


def test_old_engine_holder_without_marker_is_refused_naming_home_and_pid(tmp_path, holders):
    plan, state = make_plan(tmp_path)
    proc = holders(pool.label_lock_path(Path(state), "a2"))  # giữ khoá nhãn a2 (cùng home), không dấu N87
    with pytest.raises(Refused) as caught:
        library_run.require_n87_homes(plan, state)
    text = str(caught.value)
    assert "home1" in text and str(proc.pid) in text and "N87" in text


def test_holder_with_valid_n87_marker_is_allowed(tmp_path, holders):
    plan, state = make_plan(tmp_path)
    lock = pool.label_lock_path(Path(state), "a2")
    proc = holders(lock)
    home = Path(plan["lanes"][0]["codex_home"]).resolve().as_posix()
    library_run.n87_marker_path(lock).write_text(json.dumps({"n87": True, "pid": proc.pid, "codex_home": home}), encoding="ascii")
    library_run.require_n87_homes(plan, state)  # không ném


def test_marker_with_n87_false_or_wrong_pid_or_garbage_is_refused(tmp_path, holders):
    plan, state = make_plan(tmp_path)
    lock = pool.label_lock_path(Path(state), "a2")
    proc = holders(lock)
    home = Path(plan["lanes"][0]["codex_home"]).resolve().as_posix()
    for body in ({"n87": False, "pid": proc.pid, "codex_home": home}, {"n87": True, "pid": proc.pid + 1, "codex_home": home}, "{not json"):
        library_run.n87_marker_path(lock).write_text(body if isinstance(body, str) else json.dumps(body), encoding="ascii")
        with pytest.raises(Refused):
            library_run.require_n87_homes(plan, state)


def test_stale_lock_and_stale_marker_do_not_block(tmp_path):
    plan, state = make_plan(tmp_path)
    lock = pool.label_lock_path(Path(state), "a2")
    lock.write_bytes(b"")  # khoá mồ côi: file còn, không ai giữ
    library_run.n87_marker_path(lock).write_text(json.dumps({"n87": False, "pid": 99999999}), encoding="ascii")
    assert library_run.home_conflicts(plan, state) == []
    library_run.require_n87_homes(plan, state)


def test_lane_writes_n87_markers_for_every_label_of_its_home_and_clears_them(tmp_path):
    plan, state = make_plan(tmp_path)
    written = library_run.write_n87_markers(tmp_path / "plan.json", plan, state, "a1")
    assert len(written) == 2
    data = json.loads(written[0].read_text(encoding="ascii"))
    assert data["n87"] is True and data["pid"] == os.getpid() and data["engine_version"] and data["plan_rev"] == "r9"
    library_run.clear_n87_markers(written)
    assert not any(p.exists() for p in written)


def test_copy_queues_copies_the_referenced_queue_even_with_another_name(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir(), out.mkdir()
    (src / "queue-old.json").write_text("[1]", encoding="utf-8")  # glob cũ sẽ chép nhầm file này
    (src / "my-queue.json").write_text("[2]", encoding="utf-8")
    copies = library_run._copy_queues(src, out, [src / "my-queue.json"], "r9")
    assert [Path(c["source"]).name for c in copies] == ["my-queue.json"]
    assert (out / "queue-r9.json").read_text(encoding="utf-8") == "[2]"  # tên queue-*.json để cổng N52 thấy
    assert not (out / "queue-old.json").exists()


def test_copy_queues_falls_back_to_glob_when_plan_names_none(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir(), out.mkdir()
    (src / "queue-a.json").write_text("[1]", encoding="utf-8")
    assert [Path(c["source"]).name for c in library_run._copy_queues(src, out)] == ["queue-a.json"]
    with pytest.raises(Refused):
        library_run._copy_queues(tmp_path / "empty", out)
