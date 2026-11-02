"""Single-executor guard: a visible PID lock for one run folder (task T-E30).

``engine.core.filelock`` is an OS lock that dies with its process; it can not tell an operator WHO
holds a run or whether a "dead looking" executor is really dead (incident 2026-10-27: a second
executor was nearly started while the first, log-less one was still alive).  This lock is a plain
JSON file (``pid``, process ``start_time``, ``host``) created with O_EXCL:

* a live holder (same host, PID alive, same process start time) -> ``Refused``, always;
* a holder whose PID is dead, or whose PID now belongs to a different process (start time
  differs) -> the lock is STALE: ``Refused`` with the details unless ``break_stale=True``, in which
  case a ``stale-lock-<ts>.json`` report is written and the lock is taken over;
* a lock from another host, or an unreadable lock, can not be judged -> ``Refused``, never broken.

The file is removed on exit only if it still carries our token.  It is never removed otherwise.

Breaking a stale lock is race-safe: acquisition, recovery and release are serialised by an OS lock on
``<lock>.mutex`` (released at process death). The visible lock is re-read before removal or rename.
``extra`` (e.g. the plan) is stored in the body and named in refusals; ``scope="machine"`` is the
machine-level twin (one per gpu lock folder) that excludes executors of other plans.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .errors import Refused
from .filelock import run_lock
from .io import write_json_atomic

LOCK_SCHEMA = "jjv/run-lock/v1"
_START_TOLERANCE_SECONDS = 5.0
BREAK_GUARD_SECONDS = 5.0  # how long a breaker waits for another breaker before refusing


def _windows_process(pid: int) -> tuple[bool, float | None]:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5, None  # 5 = access denied: the process exists
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return False, None
        created, exited, kern, user = (wintypes.FILETIME() for _ in range(4))
        if kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                  ctypes.byref(kern), ctypes.byref(user)):
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
            return True, (ticks - 116444736000000000) / 1e7
        return True, None
    finally:
        kernel.CloseHandle(handle)


def _posix_process(pid: int) -> tuple[bool, float | None]:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False, None
    except PermissionError:
        pass
    start: float | None = None
    try:  # Linux: field 22 of /proc/<pid>/stat is the start time in clock ticks since boot
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        boot = next(float(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines()
                    if line.startswith("btime"))
        start = boot + float(fields[19]) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        start = None
    return True, start


def process_info(pid: int) -> tuple[bool, float | None]:
    """``(alive, start_time_unix_or_None)`` for ``pid`` on this host; never raises."""
    try:
        return _windows_process(pid) if sys.platform == "win32" else _posix_process(pid)
    except Exception:  # noqa: BLE001 - an unanswerable probe must not crash the guard
        return True, None  # unknown is treated as alive: never break a lock on a guess


ProcessInfo = Callable[[int], "tuple[bool, float | None]"]


def _read(path: Path) -> dict | None:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise Refused(f"run lock {path} exists but is unreadable ({error!r}); it was left in place. "
                      "Verify no executor is running, then remove it by hand") from error
    if not isinstance(body, dict) or not isinstance(body.get("pid"), int):
        raise Refused(f"run lock {path} is not a jjv run lock; it was left in place")
    return body


def _holder_text(body: dict) -> str:
    plan = f", plan {body['plan']!r}" if body.get("plan") else ""
    return (f"pid {body.get('pid')} on host {body.get('host')!r}{plan}, started "
            f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(body.get('acquired_at') or 0))}")


def _create(path: Path, body: dict) -> bool:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o644)
    except FileExistsError:
        return False
    except PermissionError:  # Windows: the name is held by a delete-pending / just-renamed file; look again
        time.sleep(0.01)
        return False
    with os.fdopen(fd, "wb") as handle:
        handle.write(json.dumps(body, indent=2, sort_keys=True).encode("utf-8"))
    return True


def _unlink(path: Path) -> bool:
    """Remove a file we own; a sharing violation (a contender reading it for an instant) is retried, then given up
    quietly (the name is unique or the lock is ours: leaving it is harmless, raising from a ``finally`` is not)."""
    for _ in range(50):
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError:
            time.sleep(0.01)
        except OSError:
            return False
    return False


@contextmanager
def _break_guard(path: Path) -> Iterator[None]:
    """Serialise lock breakers: only the holder of ``<lock>.break`` (O_EXCL) may judge-and-remove a stale lock."""
    guard = path.with_name(path.name + ".break")
    deadline = time.monotonic() + BREAK_GUARD_SECONDS
    while True:
        try:
            os.close(os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o644))
            break
        except (FileExistsError, PermissionError):
            if time.monotonic() >= deadline:
                raise Refused(f"another process is breaking run lock {path} right now (guard file {guard} exists); "
                              "the lock was left in place. If no executor is starting, delete the guard by hand "
                              "and re-run") from None
            time.sleep(0.01)
    try:
        yield
    finally:
        _unlink(guard)


def _break_stale(path: Path, held: dict, why: str, *, report_dir: Path, scope: str, me: int,
                 clock: Callable[[], float]) -> None:
    """Remove the stale lock we JUDGED, and only that one.

    Breakers are serialised by an OS mutex. Under it the lock is re-read IN PLACE (it is never moved, so a
    live lock is never absent, not even for an instant) and removed only if it still carries the token that
    was judged stale; if another executor replaced it meanwhile the break is refused and nothing is touched.
    """
    with run_lock(path.with_name(path.name + ".mutex"), timeout_seconds=BREAK_GUARD_SECONDS), _break_guard(path):
        moved = _read(path)  # Refused if it became unreadable; None if it is already gone
        if moved is None:
            return  # the caller's create loop simply tries again
        if moved.get("token") != held.get("token") or moved.get("pid") != held.get("pid"):
            raise Refused(f"run lock {path} changed while it was being judged stale (now {_holder_text(moved)}); "
                          "nothing was broken. Check which executor is running, then re-run")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(clock()))
        name = (f"stale-lock-{stamp}-{held['pid']}.json" if scope == "run"
                else f"stale-lock-{scope}-{stamp}-{held['pid']}.json")
        write_json_atomic(Path(report_dir) / name, {"schema": "jjv/stale-lock-report/v1", "why": why, "lock": held,
                                                    "scope": scope, "broken_by_pid": me, "broken_at": clock()},
                          mode="ascii")
        if not _unlink(path):
            raise Refused(f"stale run lock {path} could not be removed (another process is using it); it was "
                          "left in place. Check which executor is running, then re-run")


def rename_stale_lock(path: Path, *, queue_idle: Callable[[], bool], report_dir: Path,
                      max_age_seconds: float = 1800.0, info: ProcessInfo = process_info,
                      clock: Callable[[], float] = time.time, host: str | None = None) -> Path | None:
    """Archive a dead/reused or aged executor lock after proving the ComfyUI queue is idle.

    The OS mutex serialises recovery; the lock is checked again beneath it. A contender
    taking the name after the rename is handled by the caller's normal O_EXCL lock acquisition.
    """
    path = Path(path)
    with run_lock(path.with_name(path.name + ".mutex"), timeout_seconds=BREAK_GUARD_SECONDS):
        held = _read(path)
        if held is None:
            return None
        here = host if host is not None else socket.gethostname()
        if held.get("host") != here:
            raise Refused(f"machine-level run lock {path} belongs to another host; left in place")
        alive, start = info(int(held["pid"]))
        recorded = held.get("process_start_time")
        reused = alive and isinstance(recorded, (int, float)) and start is not None and abs(start - recorded) > _START_TOLERANCE_SECONDS
        acquired = held.get("acquired_at")
        aged = isinstance(acquired, (int, float)) and 0 <= clock() - acquired >= max_age_seconds
        if alive and not reused and not aged:
            raise Refused(f"another executor is running: machine-level run lock {path} is held by {_holder_text(held)}")
        if not queue_idle():
            raise Refused(f"machine-level run lock {path} was left in place: ComfyUI queue is busy or unreadable")
        current = _read(path)
        if current is None or current.get("token") != held.get("token") or current.get("pid") != held.get("pid"):
            raise Refused(f"machine-level run lock {path} changed during recovery; left in place")
        why = "pid is not running" if not alive else ("pid was reused" if reused else f"aged at least {max_age_seconds:g}s with idle queue")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(clock()))
        archive = path.with_name(f"{path.name}.stale-{stamp}-{held.get('token', 'unknown')}")
        if archive.exists():
            raise Refused(f"stale-lock archive already exists: {archive}; lock left in place")
        report = Path(report_dir) / f"stale-lock-machine-{stamp}-{held['pid']}.json"
        os.replace(path, archive)
        write_json_atomic(report, {"schema": "jjv/stale-lock-report/v1", "why": why, "lock": held,
                                   "scope": "machine", "broken_by_pid": os.getpid(), "broken_at": clock(),
                                   "archive": str(archive)}, mode="ascii")
        return archive


@contextmanager
def run_pid_lock(path: Path, *, break_stale: bool = False, report_dir: Path | None = None,
                 info: ProcessInfo = process_info, host: str | None = None,
                 pid: int | None = None, clock: Callable[[], float] = time.time,
                 extra: dict | None = None, scope: str = "run") -> Iterator[dict]:
    """Take the visible PID lock at ``path``.  ``extra`` is stored in the lock body (e.g. the plan that
    holds it) and shown in every refusal; ``scope`` ("run" or "machine") only words the messages."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    me = pid if pid is not None else os.getpid()
    here = host if host is not None else socket.gethostname()
    label = "run lock" if scope == "run" else f"{scope}-level run lock"
    _, my_start = info(me)
    body = {**(extra or {}), "schema": LOCK_SCHEMA, "pid": me, "host": here, "process_start_time": my_start,
            "acquired_at": clock(), "token": uuid.uuid4().hex}
    attempts = 0
    while True:
        # Recovery holds the same guard while it verifies and renames a stale lock.
        # Serialising normal acquisitions here prevents a replacement lock from
        # appearing between that verification and the rename.
        with run_lock(path.with_name(path.name + ".mutex"), timeout_seconds=BREAK_GUARD_SECONDS):
            created = _create(path, body)
        if created:
            break
        attempts += 1
        if attempts > 500:
            raise Refused(f"{label} {path} could not be created or read after {attempts} tries (it keeps "
                          "changing); another executor is starting. Check which executor is running, then re-run")
        held = _read(path)
        if held is None:
            continue  # vanished between create and read: try again
        if held.get("host") != here:
            raise Refused(f"{label} {path} is held by {_holder_text(held)}; another host can not be "
                          "checked from here. The lock was left in place")
        alive, start = info(int(held["pid"]))
        recorded = held.get("process_start_time")
        reused = (alive and isinstance(recorded, (int, float)) and start is not None
                  and abs(start - recorded) > _START_TOLERANCE_SECONDS)
        if alive and not reused:
            raise Refused(f"another executor is running: {label} {path} is held by {_holder_text(held)} "
                          "and that process is alive. Never run two executors on one run or one machine")
        why = "pid now belongs to a different process" if reused else "pid is not running"
        if not break_stale:
            raise Refused(f"STALE {label} {path} ({why}): held by {_holder_text(held)}. If you verified "
                          "that executor is dead, re-run with --break-stale-lock")
        _break_stale(path, held, why, report_dir=Path(report_dir or path.parent), scope=scope, me=me, clock=clock)
    try:
        yield body
    finally:
        with run_lock(path.with_name(path.name + ".mutex"), timeout_seconds=BREAK_GUARD_SECONDS):
            current = None
            try:
                current = _read(path)
            except Refused:
                pass
            if current is not None and current.get("token") == body["token"]:
                _unlink(path)
