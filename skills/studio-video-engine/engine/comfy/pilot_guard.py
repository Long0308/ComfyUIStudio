"""Terminal guard của một run pilot: marker + TerminalGuard + Watchdog chạy nền theo từng prompt (v004).

Executor (opt-in bằng ``terminal_guard: true`` trong exec plan) dùng lớp này:

* ``start()`` TRƯỚC dispatch đầu tiên: ghi marker ``terminal-guard-required.json`` và kiểm mọi poller
  đọc được một lần; lỗi ⇒ :class:`PilotGuardStartError` (``Refused``): chưa POST, fail-closed.
* ``guard`` được truyền vào MỌI ``dispatch(..., guard=...)``.
* ``watch(...)`` chạy ``Watchdog.run`` trong thread cho tới khi chunk xong; trạng thái terminal ⇒ latch đã ghi
  bền, ``tripped`` được đặt để executor dừng chờ và không dispatch chunk kế.

Hàm thuần stdlib nằm ở ``run_watchdog``; chỗ này nối với ComfyClient/docker/nvidia-smi (poller thật, có thể inject).
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from ..core.errors import Refused
from . import run_watchdog as wd

LATCH_FILE = "terminal-latch.json"
GATE_FILE = "terminal-latch.gate"
GATE_TIMEOUT_SECONDS = 5.0
JOIN_TIMEOUT_SECONDS = 5.0
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class PilotGuardStartError(Refused):
    """The terminal guard could not start (poller unreadable / marker unwritable): nothing was POSTed."""


def _run(command: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(command, capture_output=True, text=True, timeout=10, check=False,
                          encoding="utf-8", errors="replace")


_UNITS = {"b": 1, "kib": 1024, "mib": 1024**2, "gib": 1024**3, "kb": 1000, "mb": 1000**2, "gb": 1000**3}


def default_pollers(client: Any, container: str, probe: Any, runner: Runner = _run) -> wd.Pollers:
    """Poller thật: /queue, StartedAt (ContainerProbe), ``docker stats`` (RAM), ``nvidia-smi`` (VRAM). Có timeout 10s."""
    def ram_bytes() -> int:
        out = runner(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container]).stdout or ""
        match = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)\s*/", out)
        if not match or match.group(2).lower() not in _UNITS:
            raise ValueError(f"unparseable docker stats: {out!r}")
        return int(float(match.group(1)) * _UNITS[match.group(2).lower()])

    def vram_mib() -> float:
        out = runner(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]).stdout or ""
        values = [float(line) for line in out.split() if line.strip()]
        if not values:
            raise ValueError("nvidia-smi returned no value")
        return max(values)

    def started_at() -> str:
        state = probe.state(container)
        if state is None or not str(state.started_at_text).strip():
            raise ValueError("container StartedAt unreadable")
        return state.started_at_text

    return wd.Pollers(ram_bytes=ram_bytes, vram_mib=vram_mib, queue=lambda: client.get("/queue"),
                      started_at=started_at)


@dataclass
class PilotGuard:
    run_dir: Path
    run_id: str
    pollers: wd.Pollers
    container_id: str
    interrupt: Callable[[], None]
    delete_pending: Callable[[list[str]], None]
    caps: wd.Caps = field(default_factory=wd.Caps)
    watchdog_cls: Any = wd.Watchdog  # inject để test
    tripped: dict[str, Any] | None = None
    watch_errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        self.latch_path = self.run_dir / LATCH_FILE
        self._gate_path = self.run_dir / GATE_FILE
        self._total_started = time.monotonic()
        self.guard = wd.TerminalGuard(run_id=self.run_id, latch_path=self.latch_path, gate=self.gate)

    def gate(self):
        return wd.file_gate(self._gate_path, timeout=GATE_TIMEOUT_SECONDS)

    def start(self) -> None:
        """Marker trước, rồi mọi poller đọc được một lần: lỗi ⇒ từ chối trước POST."""
        try:
            wd.declare_guard_required(self.run_dir, run_id=self.run_id)
            for name in ("ram_bytes", "vram_mib", "queue", "started_at"):
                getattr(self.pollers, name)()
        except Exception as error:  # noqa: BLE001 - mọi lỗi khởi động ⇒ fail-closed
            raise PilotGuardStartError(f"terminal guard could not start ({error!r}); nothing was POSTed",
                                       evidence={"stage": "terminal_guard_start", "error": repr(error)}) from error

    def latch(self) -> dict[str, Any] | None:
        """Latch terminal của run (None = chưa có). Đọc hỏng ⇒ ném (caller coi như terminal)."""
        with self.gate():
            return wd.read_latch(self.latch_path, run_id=self.run_id)

    @contextmanager
    def watch(self, *, prompt_id: str, epoch: str, receipt_path: Path) -> Iterator[None]:
        stop = threading.Event()
        try:
            dog = self.watchdog_cls(
                pollers=self.pollers, interrupt=self.interrupt, delete_pending=self.delete_pending,
                receipt_path=receipt_path, latch_path=self.latch_path, container_id=self.container_id,
                gate=self.gate, run_id=self.run_id, prompt_ids={prompt_id}, expected_started_at=epoch,
                caps=self.caps, sleep=lambda seconds: stop.wait(seconds),
                total_started_monotonic=self._total_started)
        except wd.TerminalLatchRefused as error:
            # Latch đã có trước khi watchdog của prompt này dựng được: POST đã qua gate nên không rút lại được.
            # Không có watchdog để canh ⇒ đánh dấu tripped: executor dừng chờ nếu còn pending và không dispatch tiếp.
            self.tripped = {"execution_status": "LATCHED", "reason": str(error)}
            yield
            return
        def body() -> None:
            try:
                receipt = dog.run(lambda: stop.is_set())
                if receipt.get("execution_status") in ("FAIL", "LOST"):
                    self.tripped = receipt
            except Exception as error:  # noqa: BLE001 - PersistenceError etc. ⇒ coi như terminal
                self.watch_errors.append(repr(error))
                self.tripped = {"execution_status": "FAIL", "reason": "watchdog_error", "error": repr(error)}
        thread = threading.Thread(target=body, name="pilot-watchdog", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(JOIN_TIMEOUT_SECONDS)
