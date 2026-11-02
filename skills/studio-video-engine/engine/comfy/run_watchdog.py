"""Host-only watchdog core; stdlib, injected bounded pollers, no HTTP/CLI/GPU.

Adapters supply bytes (verified cgroup-equivalent Docker usage), whole-card MiB,
raw Comfy /queue and bound StartedAt text. They must enforce short I/O timeouts
and container/GPU identity. Callers hold an exclusive producer lock throughout
run/cleanup; rechecks alone cannot make /interrupt atomic with another producer.
Completion must cover render AND stitch/encode. This core is not a dispatcher.
"""
from __future__ import annotations

import getpass
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class Pollers:
    ram_bytes: Callable[[], int]
    vram_mib: Callable[[], float]
    queue: Callable[[], dict[str, Any]]
    started_at: Callable[[], str]


@dataclass(frozen=True)
class Caps:
    ram_bytes: int = 24 * 1024**3
    vram_mib: float = 14500
    deadline_seconds: float = 300  # P3/P7 callers bind 900 instead.
    total_seconds: float = 2100
    telemetry_loss_polls: int = 2
    poll_seconds: float = 0.5
    stale_seconds: float = 1.0


def write_receipt_atomic(path: Path, body: dict[str, Any]) -> None:
    """Fsync a unique sibling then replace mutable state; keep temp on error."""
    payload = (json.dumps(body, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


def _sync_directory(path: Path) -> None:
    # Windows does not expose directory fsync through os.open. File fsync and
    # replace still apply; host qualification must verify filesystem durability.
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


GUARD_REQUIRED_MARKER = "terminal-guard-required.json"
_MARKER_LOOKUP_LEVELS = 4  # receipt dir + 3 parents (runs/<shot>/<chunk> nằm dưới run dir)


def declare_guard_required(run_dir: Path, *, run_id: str) -> Path:
    """Run tự khai cần terminal guard: marker nằm ở run dir, do watchdog ghi lúc khởi động (idempotent)."""
    path = Path(run_dir) / GUARD_REQUIRED_MARKER
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        write_receipt_atomic(path, {"schema": "jjv/terminal-guard-required/v1", "run_id": run_id,
                                    "terminal_guard_required": True})
    return path


def guard_required_marker(receipt_dir: Path) -> Path | None:
    """Marker của run ở ``receipt_dir`` hoặc tổ tiên gần (tồn tại = bắt buộc, kể cả khi nội dung hỏng)."""
    here = Path(receipt_dir)
    for folder in [here, *here.parents][:_MARKER_LOOKUP_LEVELS]:
        candidate = folder / GUARD_REQUIRED_MARKER
        if candidate.exists():
            return candidate
    return None


class GateTimeout(OSError):
    """Shared gate not acquired in time: callers must refuse (never proceed without it)."""


@contextmanager
def file_gate(path: Path, *, timeout: float = 5.0, poll: float = 0.02):
    """Interprocess gate: OS byte-range/flock lock, released by the OS when the holder dies."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise GateTimeout(f"gate {path} not acquired in {timeout}s") from error
                time.sleep(poll)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


@dataclass(frozen=True)
class TerminalGuard:
    """Guard bắt buộc cho đường pilot: dispatch kiểm latch dưới ``gate`` ngay trước POST."""
    run_id: str
    latch_path: Path
    gate: Callable[[], AbstractContextManager]


class LatchReadError(RuntimeError):
    """Invalid/unreadable guard evidence: dispatch must refuse."""


class TerminalLatchRefused(RuntimeError):
    """Staging refusal; production must map this to its Refused hierarchy."""


class PersistenceError(OSError):
    """Durable terminal evidence failed; stop the runner."""


LATCH_SCHEMA = "jjv/comfy-terminal-latch/v1"


def _validate_latch(body: Any, run_id: str) -> dict[str, Any]:
    if (not isinstance(body, dict) or body.get("schema") != LATCH_SCHEMA
            or body.get("version") != 1 or body.get("run_id") != run_id
            or body.get("execution_status") not in {"FAIL", "LOST"}
            or body.get("qualification_status") != "NOT_QUALIFIED"
            or body.get("dispatch_allowed") is not False):
        raise LatchReadError("invalid terminal latch identity/status")
    for field in ("reason", "timestamp", "container_epoch", "container_id"):
        if not isinstance(body.get(field), str) or not body[field].strip():
            raise LatchReadError(f"invalid latch {field}")
    try:
        _number(body["monotonic"])
    except (KeyError, ValueError) as error:
        raise LatchReadError("invalid latch monotonic") from error
    if not isinstance(body.get("evidence"), dict):
        raise LatchReadError("invalid latch evidence")
    return body


def read_latch(path: Path, *, run_id: str) -> dict[str, Any] | None:
    """Read under the shared gate. None means absent, NEVER valid ACTIVE.

    Dispatcher must additionally verify ACTIVE guard, epoch, heartbeat and
    budgets, holding the same interprocess gate throughout its POST.
    All malformed/unreadable evidence raises; callers must refuse dispatch.
    """
    try:
        with Path(path).open(encoding="utf-8") as stream:
            body = json.load(stream)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeError) as error:
        raise LatchReadError(f"cannot read terminal latch: {path}") from error
    return _validate_latch(body, run_id)


def is_latched(path: Path, *, run_id: str) -> bool:
    """Terminal presence only; False is not authorization to POST."""
    return read_latch(path, run_id=run_id) is not None


def latch_terminal(path: Path, *, run_id: str, execution_status: str,
                   reason: str, timestamp: str, monotonic: float,
                   container_epoch: str, container_id: str,
                   evidence: dict[str, Any]) -> dict[str, Any]:
    """Caller MUST hold only the shared gate, never the dispatch lock.

    Terminal updates preserve all evidence and cannot downgrade LOST to FAIL.
    Write/fsync/replace errors propagate; a runner must stop on any failure.
    """
    body = _validate_latch({"schema": LATCH_SCHEMA, "version": 1,
        "run_id": run_id, "execution_status": execution_status,
        "qualification_status": "NOT_QUALIFIED", "dispatch_allowed": False,
        "reason": reason, "timestamp": timestamp, "monotonic": monotonic,
        "container_epoch": container_epoch, "container_id": container_id,
        "evidence": evidence}, run_id)
    previous = read_latch(path, run_id=run_id)
    if previous is not None:
        if previous["execution_status"] == "LOST":
            body["execution_status"] = "LOST"
        body["previous"] = previous
    write_receipt_atomic(Path(path), body)
    return body


def _operator_clear_latch(path: Path, *, run_id: str, operator: str, reason: str,
                         runner_stopped: bool, watchdog_stopped: bool,
                         ownership_reconciled: bool,
                         gate: Callable[[], AbstractContextManager], confirm: str | None = None) -> Path:
    """PRIVATE: chỉ ``cli_clear_latch`` (verb ``jjv comfy watchdog clear``) được gọi hàm này.

    Explicit operator-only archive; never called by init/retry/run.

    Caller authenticates the operator and verifies these attestations. Preserve
    the original latch plus an audit receipt; no unlink/delete is used.
    """
    if (not operator.strip() or not reason.strip() or runner_stopped is not True
            or watchdog_stopped is not True or ownership_reconciled is not True):
        raise ValueError("operator identity/reason and stopped/reconciled attestations required")
    path = Path(path)
    with gate():
        if read_latch(path, run_id=run_id) is None:
            raise LatchReadError("no terminal latch to archive")
        archive = path.with_name(f"{path.name}.{uuid.uuid4().hex}.archived")
        write_receipt_atomic(archive.with_name(archive.name + ".operator.json"), {
            "run_id": run_id, "operator": operator, "reason": reason,
            "confirm": confirm, "runner_stopped": True, "watchdog_stopped": True,
            "ownership_reconciled": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "latch_path": str(path), "archive_path": str(archive)})
        os.replace(path, archive)
        _sync_directory(path.parent)
        return archive


class ClearRefused(ValueError):
    """CLI clear refused (confirmation/attestation/run id invalid); the latch is untouched."""


def cli_clear_latch(*, runs_root: Path, run_id: str, confirm: str | None, reason: str,
                    runner_stopped: bool, watchdog_stopped: bool, ownership_reconciled: bool,
                    operator: str | None = None) -> Path:
    """The ONLY entry to clearing a latch (CLI ``jjv comfy watchdog clear``): needs ``confirm == run_id``.

    Records operator (default: OS user), confirm and UTC time in the archive receipt; nothing is deleted.
    """
    if confirm != run_id:
        raise ClearRefused("--confirm must equal --run-id exactly; latch not cleared")
    if (not run_id or run_id != Path(run_id).name or run_id in {".", ".."}
            or any(c in run_id for c in "/\\")):
        raise ClearRefused("run id must be a plain folder name")
    who = (operator or "").strip() or getpass.getuser()
    run_dir = Path(runs_root) / run_id
    try:
        return _operator_clear_latch(
            run_dir / "terminal-latch.json", run_id=run_id, operator=who, reason=reason,
            runner_stopped=runner_stopped, watchdog_stopped=watchdog_stopped,
            ownership_reconciled=ownership_reconciled,
            gate=lambda: file_gate(run_dir / "terminal-latch.gate", timeout=5.0), confirm=confirm)
    except ValueError as error:
        raise ClearRefused(str(error)) from error


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("metric must be a number")
    if not math.isfinite(value) or value < 0:
        raise ValueError("metric must be finite and nonnegative")
    return value


def _queue_ids(queue: Any) -> tuple[list[str], list[str]]:
    result = []
    for key in ("queue_running", "queue_pending"):
        rows = queue[key]
        if not isinstance(rows, list):
            raise ValueError("queue rows must be lists")
        ids = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                raise ValueError("malformed queue record")
            if not isinstance(row[1], str) or not row[1]:
                raise ValueError("missing prompt ID")
            ids.append(row[1])
        result.append(ids)
    return tuple(result)


class Watchdog:
    def __init__(self, *, pollers: Pollers, interrupt: Callable[[], None],
                 delete_pending: Callable[[list[str]], None], receipt_path: Path,
                 latch_path: Path, container_id: str,
                 gate: Callable[[], AbstractContextManager],
                 run_id: str, prompt_ids: set[str], expected_started_at: str,
                 caps: Caps = Caps(), clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 utc: Callable[[], str] = lambda: datetime.now(timezone.utc).isoformat(),
                 started_monotonic: float | None = None,
                 total_started_monotonic: float | None = None):
        if not run_id or not prompt_ids or any(not isinstance(p, str) or not p for p in prompt_ids):
            raise ValueError("run and owned prompt IDs required")
        if not isinstance(expected_started_at, str) or not expected_started_at.strip():
            raise ValueError("pre-dispatch StartedAt required")
        if not isinstance(container_id, str) or not container_id.strip() or not callable(gate):
            raise ValueError("container identity and shared gate factory required")
        for value in (caps.ram_bytes, caps.vram_mib, caps.deadline_seconds,
                      caps.total_seconds, caps.poll_seconds, caps.stale_seconds):
            if _number(value) <= 0:
                raise ValueError("caps and intervals must be positive")
        if caps.poll_seconds > 0.5 or caps.stale_seconds > 1:
            raise ValueError("poll <=0.5s and stale <=1s required")
        if type(caps.telemetry_loss_polls) is not int or caps.telemetry_loss_polls < 1:
            raise ValueError("telemetry loss threshold must be a positive integer")
        self.path = Path(receipt_path)
        self.latch_path, self.gate, self.container_id = Path(latch_path), gate, container_id
        if self.latch_path.resolve() == self.path.resolve():
            raise ValueError("shared latch and receipt paths must be distinct")
        with gate():
            if is_latched(self.latch_path, run_id=run_id):
                raise TerminalLatchRefused("existing terminal latch; operator reconciliation required")
        if self.path.exists():
            raise FileExistsError("use a fresh run receipt; never overwrite historical evidence")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.latch_path.parent.mkdir(parents=True, exist_ok=True)
        declare_guard_required(self.latch_path.parent, run_id=run_id)  # run này từ giờ cấm dispatch không guard
        self.pollers, self.interrupt, self.delete_pending = pollers, interrupt, delete_pending
        self.run_id, self.owned, self.epoch = run_id, frozenset(prompt_ids), expected_started_at
        self.caps, self.clock, self.sleep, self.utc = caps, clock, sleep, utc
        now = clock()
        self.start = now if started_monotonic is None else _number(started_monotonic)
        self.total_start = self.start if total_started_monotonic is None else _number(total_started_monotonic)
        if self.start > now or self.total_start > self.start:
            raise ValueError("budget clocks must precede this run")
        self.status, self.receipt, self.losses = "ACTIVE", None, 0
        self._persistence_error = None

    def _persist(self) -> None:
        try:
            with self.gate():
                latch_terminal(self.latch_path, run_id=self.run_id,
                    execution_status=self.status,
                    reason=self.receipt["events"][0]["reason"],
                    timestamp=self.utc(), monotonic=self.clock(),
                    container_epoch=self.receipt.get("cleanup_observed_started_at",
                        self.receipt["samples"].get("started_at", self.epoch)),
                    container_id=self.container_id, evidence=self.receipt)
            write_receipt_atomic(self.path, self.receipt)
        except Exception as error:
            self.receipt.setdefault("receipt_errors", []).append(repr(error))
            self._persistence_error = PersistenceError("terminal persistence failed; runner stopped")
            raise self._persistence_error from error

    def _fresh_queue(self) -> tuple[list[str], list[str]]:
        began = self.clock()
        # Read queue first and epoch immediately before the caller's action.
        queue = self.pollers.queue()
        epoch = self.pollers.started_at()
        if not isinstance(epoch, str) or not epoch.strip():
            raise ValueError("cleanup StartedAt unavailable")
        if epoch != self.epoch:
            self.status = self.receipt["execution_status"] = "LOST"
            self.receipt["cleanup_observed_started_at"] = epoch
            self.receipt["events"].append({"reason": "container_restart", "measured": epoch,
                                           "cap": self.epoch, "unit": "StartedAt"})
            self._persist()
            raise ValueError("cleanup epoch changed")
        if self.clock() - began > self.caps.stale_seconds:
            raise ValueError("cleanup recheck stale")
        return _queue_ids(queue)

    def _cleanup(self) -> None:
        errors = []
        try:
            running, _ = self._fresh_queue()
            if len(running) == 1 and running[0] in self.owned:
                try:
                    self.interrupt()
                    self.receipt["actions"].append({"interrupt": running[0]})
                except Exception as error:
                    errors.append(repr(error))
            _, pending = self._fresh_queue()
            ids = sorted(self.owned.intersection(pending))
            if ids:
                try:
                    self.delete_pending(ids)
                    self.receipt["actions"].append({"delete_pending": ids})
                except Exception as error:
                    errors.append(repr(error))
            running, pending = self._fresh_queue()
            if not errors and not self.owned.intersection(running + pending):
                self.receipt["cleanup_status"] = "CONFIRMED"
        except PersistenceError:
            raise
        except Exception as error:
            errors.append(repr(error))
        self.receipt["cleanup_errors"] = errors

    def run(self, completed: Callable[[], bool]) -> dict[str, Any]:
        """Latch FAIL/LOST once; completion is execution-only, never qualification.

        Required-source exceptions/invalid metrics count as lost polls. Valid
        breaches still trip immediately during partial telemetry loss. This
        synchronous core cannot preempt a hung adapter: adapters MUST time out.
        """
        if self._persistence_error is not None:
            raise self._persistence_error
        if self.status != "ACTIVE":
            return self.receipt
        while True:
            began, values, errors, stamps = self.clock(), {}, {}, {}
            for name in ("ram_bytes", "vram_mib", "queue", "started_at"):
                try:
                    value = getattr(self.pollers, name)()
                    if name in ("ram_bytes", "vram_mib"):
                        _number(value)
                    elif name == "queue":
                        _queue_ids(value)
                    elif not isinstance(value, str) or not value.strip():
                        raise ValueError("StartedAt missing")
                    values[name], stamps[name] = value, self.clock()
                except Exception as error:
                    errors[name] = repr(error)
            done = False
            if not errors:
                try:
                    done = completed()
                    if type(done) is not bool:
                        raise ValueError("completion callback must return bool")
                except Exception as error:
                    errors["completion"] = repr(error)
            now = self.clock()
            if now - began > self.caps.stale_seconds:
                errors["freshness"] = "sample acquisition exceeded stale cap"
            self.losses = self.losses + 1 if errors else 0
            events = []
            for metric, measured, cap, unit, breach in (
                ("ram_bytes", values.get("ram_bytes"), self.caps.ram_bytes, "bytes", ">="),
                ("vram_mib", values.get("vram_mib"), self.caps.vram_mib, "MiB", ">"),
                ("deadline", now - self.start, self.caps.deadline_seconds, "seconds", ">="),
                ("total_deadline", now - self.total_start, self.caps.total_seconds, "seconds", ">="),
            ):
                if measured is not None and (measured >= cap if breach == ">=" else measured > cap):
                    events.append({"reason": metric, "measured": measured, "cap": cap, "unit": unit})
            restarted = "started_at" in values and values["started_at"] != self.epoch
            if restarted:
                events.insert(0, {"reason": "container_restart", "measured": values["started_at"],
                                  "cap": self.epoch, "unit": "StartedAt"})
            if errors and (self.losses >= self.caps.telemetry_loss_polls or "freshness" in errors):
                events.append({"reason": "telemetry_loss", "measured": self.losses,
                               "cap": self.caps.telemetry_loss_polls, "unit": "polls"})
            if events:
                self.status = "LOST" if restarted else "FAIL"
                self.receipt = {"schema": "jjv/comfy-watchdog-stage/v1", "run_id": self.run_id,
                                "execution_status": self.status, "qualification_status": "NOT_QUALIFIED",
                                "dispatch_allowed": False, "events": events, "timestamp": self.utc(),
                                "monotonic": now, "expected_started_at": self.epoch,
                                "prompt_ids": sorted(self.owned), "samples": values,
                                "sample_monotonic": stamps, "telemetry_errors": errors,
                                "cleanup_status": "UNCONFIRMED", "actions": []}
                self._persist()  # Durable terminal evidence BEFORE any cleanup callback.
                if not restarted:
                    self._cleanup()
                self._persist()
                return self.receipt
            if not errors and done:
                self.status = "COMPLETED"
                self.receipt = {"execution_status": "COMPLETED", "qualification_status": "NOT_QUALIFIED"}
                return self.receipt
            self.sleep(max(0, min(self.caps.poll_seconds - (self.clock() - began),
                                  self.start + self.caps.deadline_seconds - self.clock(),
                                  self.total_start + self.caps.total_seconds - self.clock())))
