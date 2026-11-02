"""N96: `library run --view-out/--view-libraries/--view-queues/--review-out` làm mới view/review sau mỗi batch.
Thư viện giả (thư mục tạm); view/review được thay bằng bản giả để đo thứ tự, khoá và ghi vết trong run.json."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.images import library_review, library_run, library_view


def make_run(tmp: Path, *, view: bool = True, review: bool = True) -> tuple[Path, dict]:
    run_dir = tmp / "run"
    run_dir.mkdir()
    libs, queues = tmp / "lib", tmp / "queue-r1.json"
    libs.mkdir()
    queues.write_text("[]", encoding="utf-8")
    cfg = library_run.view_config(str(tmp / "by-char") if view else None, [str(libs)], [str(queues)],
                                  str(tmp / "review.html") if review else None)
    run = {"schema": library_run.RUN_SCHEMA, "view": cfg}
    (run_dir / "run.json").write_text(json.dumps(run), encoding="ascii")
    return run_dir, run


def test_no_flags_means_no_refresh(tmp_path):
    assert library_run.view_config(None, None, None, None) is None
    run_dir, _ = make_run(tmp_path)
    assert library_run.refresh_views(run_dir, {}, "L1", why="x") is None


def test_flags_validated():
    with pytest.raises(Refused):
        library_run.view_config("out", None, ["q"], None)
    with pytest.raises(Refused):
        library_run.view_config("out", ["lib"], None, None)


def test_view_and_review_refreshed_and_recorded(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(library_view, "view", lambda libs, qs, out, **kw: calls.append(("view", out)) or {"exit": 0, "errors": []})
    monkeypatch.setattr(library_review, "review", lambda libs, out, **kw: calls.append(("review", out)) or {"exit": 0})
    run_dir, run = make_run(tmp_path)
    entry = library_run.refresh_views(run_dir, run, "L1", why="batch b1")
    assert entry["ok"] and [c[0] for c in calls] == ["view", "review"]
    log = json.loads((run_dir / "run.json").read_text(encoding="ascii"))["view_refresh"]
    assert log["count"] == 1 and log["errors"] == 0 and log["last"]["why"] == "batch b1"


def test_concurrent_refresh_is_serialized(tmp_path, monkeypatch):
    state = {"in": 0, "max": 0}
    guard = threading.Lock()

    def slow_view(libs, qs, out, **kw):
        with guard:
            state["in"] += 1
            state["max"] = max(state["max"], state["in"])
        time.sleep(0.15)
        with guard:
            state["in"] -= 1
        return {"exit": 0, "errors": []}

    monkeypatch.setattr(library_view, "view", slow_view)
    monkeypatch.setattr(library_review, "review", lambda *a, **k: {"exit": 0})
    run_dir, run = make_run(tmp_path)
    threads = [threading.Thread(target=library_run.refresh_views, args=(run_dir, run, f"L{i}"), kwargs={"why": "t"}) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert state["max"] == 1
    log = json.loads((run_dir / "run.json").read_text(encoding="ascii"))["view_refresh"]
    assert log["count"] == 4 and log["errors"] == 0


def test_refresh_error_recorded_and_lane_continues(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("view exploded")

    monkeypatch.setattr(library_view, "view", boom)
    monkeypatch.setattr(library_review, "review", lambda *a, **k: {"exit": 0})
    run_dir, run = make_run(tmp_path)
    entry = library_run.refresh_views(run_dir, run, "L1", why="x")  # không ném
    assert not entry["ok"] and "view exploded" in entry["errors"][0]
    log = json.loads((run_dir / "run.json").read_text(encoding="ascii"))["view_refresh"]
    assert log["errors"] == 1


def test_lane_body_refreshes_after_each_batch(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(library_run, "run_submit", lambda argv: {"takes": [1]})
    monkeypatch.setattr(library_run, "refresh_status", lambda *a, **k: {})
    monkeypatch.setattr(library_run, "submit_argv", lambda *a, **k: [])
    monkeypatch.setattr(library_run, "refresh_views", lambda rd, run, label, *, why, **k: seen.append(why))
    lane = {"label": "L1", "batches": [{"batch_id": b, "state": "pending", "remaining": [1], "file": "f"} for b in ("b1", "b2")]}
    ctx = {"library_out": None}
    out = library_run._run_lane_body(tmp_path, {}, {}, tmp_path, "L1", lane, ctx, 0)
    assert out["state"] == "done" and out["images"] == 2
    assert seen == ["batch b1", "batch b2"]
