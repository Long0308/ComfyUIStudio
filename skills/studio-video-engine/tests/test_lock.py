"""Lock tests: every path is a tmp_path; nothing here may touch a real lock."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from engine.comfy.lock import existence_lock, read_lock_body
from engine.core.errors import Refused


def test_acquire_writes_pid_time_token_then_releases(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    with existence_lock(path, timeout_seconds=0) as handle:
        body = path.read_text(encoding="ascii")
        assert body.startswith(f"pid={handle.pid} acquired_unix=")
        assert body.rstrip().endswith(f"token={handle.token}")
        info = read_lock_body(path)
        assert info is not None and info["token"] == handle.token and info["pid"] == handle.pid
        assert handle.released is None
    assert not path.exists() and handle.released is True


def test_held_lock_is_refused_and_preserved_never_deleted(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    path.write_text("pid=1 acquired_unix=1.0 token=deadbeef\n", encoding="ascii")
    with pytest.raises(Refused):
        with existence_lock(path, timeout_seconds=0):
            pytest.fail("must not acquire")
    assert path.read_text(encoding="ascii") == "pid=1 acquired_unix=1.0 token=deadbeef\n"


def test_waits_then_refuses_after_timeout(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    path.write_text("pid=1 token=ab\n", encoding="ascii")
    start = time.monotonic()
    with pytest.raises(Refused):
        with existence_lock(path, timeout_seconds=0.2, poll_seconds=0.02):
            pass
    assert 0.15 <= time.monotonic() - start < 3
    assert path.exists()


def test_second_acquirer_waits_for_release(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    order: list[str] = []
    ready = threading.Event()

    def holder() -> None:
        with existence_lock(path, timeout_seconds=0):
            ready.set()
            time.sleep(0.2)
            order.append("holder-done")

    thread = threading.Thread(target=holder)
    thread.start()
    assert ready.wait(5)
    with existence_lock(path, timeout_seconds=5, poll_seconds=0.02):
        order.append("second-in")
    thread.join()
    assert order == ["holder-done", "second-in"]


def test_release_is_token_checked_foreign_body_left_in_place(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    with existence_lock(path, timeout_seconds=0) as handle:
        with open(path, "w", encoding="ascii") as other:  # someone else rewrote it
            other.write("pid=999 acquired_unix=2.0 token=feedface\n")
    assert path.exists() and "feedface" in path.read_text(encoding="ascii")
    assert handle.released is False and "token" in handle.release_note


def test_release_when_file_vanished_does_not_raise(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    with existence_lock(path, timeout_seconds=0) as handle:
        pass
    assert handle.released is True
    again = tmp_path / "gone.lock"
    with existence_lock(again, timeout_seconds=0) as second:
        second_path = again
    assert not second_path.exists()


def test_exception_in_block_still_releases(tmp_path: Path) -> None:
    path = tmp_path / "gpu.lock"
    with pytest.raises(RuntimeError):
        with existence_lock(path, timeout_seconds=0):
            raise RuntimeError("boom")
    assert not path.exists()


def test_creates_parent_and_rejects_negative_timeout(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "gpu.lock"
    with existence_lock(nested, timeout_seconds=0):
        assert nested.exists()
    with pytest.raises(ValueError):
        with existence_lock(tmp_path / "n.lock", timeout_seconds=-1):
            pass


def test_read_lock_body_missing_and_malformed(tmp_path: Path) -> None:
    assert read_lock_body(tmp_path / "none.lock") is None
    odd = tmp_path / "odd.lock"
    odd.write_text("garbage", encoding="ascii")
    info = read_lock_body(odd)
    assert info is not None and info["token"] is None and info["pid"] is None


def test_token_is_rechecked_immediately_before_unlink(tmp_path: Path, monkeypatch) -> None:
    """A foreign rewrite landing between the first check and the unlink must not
    be deleted (residual window is only the gap between final read and unlink)."""
    from engine.comfy import lock as lock_module

    path = tmp_path / "gpu.lock"
    real_read = lock_module.read_lock_body
    state = {"calls": 0}

    def flaky(target: Path):  # type: ignore[no-untyped-def]
        state["calls"] += 1
        info = real_read(target)
        if state["calls"] >= 2 and info is not None:
            return {**info, "token": "feedface"}  # someone replaced it after read #1
        return info

    monkeypatch.setattr(lock_module, "read_lock_body", flaky)
    with existence_lock(path, timeout_seconds=0) as handle:
        pass
    assert state["calls"] >= 2
    assert path.exists() and handle.released is False
