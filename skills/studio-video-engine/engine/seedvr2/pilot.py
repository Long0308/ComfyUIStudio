"""Terminal guard của Executor (v004): opt-in bằng ``terminal_guard: true`` trong exec plan.

Mixin dùng ``self.plan/settings/client/container_probe/clock/emit/pilot/_pilot_guard_factory`` do ``Executor`` đặt.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from ..comfy import run_watchdog
from ..comfy.pilot_guard import PilotGuard, default_pollers
from ..core.errors import Uncertain
from ..core.io import read_json, write_json_atomic
from . import receipts as rc
from .execplan import Task


class PilotGuardMixin:
    def _default_pilot_guard(self) -> PilotGuard:
        s, client = self.settings, self.client
        return PilotGuard(
            run_dir=self.plan.root / "runs", run_id=f"seedvr2-{self.plan.sha256[:16]}",
            pollers=default_pollers(client, s.container, self.container_probe), container_id=s.container,
            interrupt=lambda: client.post("/interrupt", {}),
            delete_pending=lambda ids: client.post("/queue", {"delete": ids}),
            caps=run_watchdog.Caps(deadline_seconds=900))

    def _start_pilot_guard(self) -> None:
        if self.plan.plan.get("terminal_guard") is not True:
            return
        factory = self._pilot_guard_factory
        self.pilot = factory(self) if factory is not self._default_pilot_guard else factory()
        self.pilot.start()  # marker + poller check; Refused before any POST

    def _pilot_watch(self, task: Task, job: dict):
        if self.pilot is None:
            return nullcontext()
        paths = rc.task_paths(self.plan, task)
        epoch = ((read_json(paths["intent"]).get("container_instance") or {}).get("started_at_text") or "")
        return self.pilot.watch(prompt_id=job["prompt_id"], epoch=epoch,
                                receipt_path=paths["chunk_dir"] / f"watchdog-{int(self.clock() * 1000)}.json")

    def _pending_hook(self, stall: Any) -> Callable[[], None]:
        def hook() -> None:
            stall.check()
            if self.pilot is not None and self.pilot.tripped is not None:
                raise Uncertain("terminal watchdog latch set while waiting; stopping, nothing is resubmitted",
                                evidence={"stage": "terminal_latch", "watchdog": self.pilot.tripped})
        return hook

    def _terminal_stop(self, task: Task) -> dict[str, Any] | None:
        """Latch terminal (hoặc không đọc được) ⇒ ghi receipt của executor và dừng, không dispatch chunk kế."""
        if self.pilot is None:
            return None
        error = None
        try:
            latch = self.pilot.latch()
        except Exception as exc:  # noqa: BLE001 - latch không đọc được = không chứng minh được ACTIVE
            latch, error = {"execution_status": "UNREADABLE"}, repr(exc)
        if latch is None and self.pilot.tripped is None:
            return None
        status = (latch or {}).get("execution_status") or (self.pilot.tripped or {}).get("execution_status")
        body = {"schema": "jjv/seedvr2-terminal-guard-stop/v1", "run_id": self.pilot.run_id, "latch_status": status,
                "latch_path": str(self.pilot.latch_path), "next_chunk": f"{task.shot_id}/{task.name}",
                "latch_error": error, "watchdog": self.pilot.tripped, "at": self.clock(), "post_attempted": False}
        write_json_atomic(self.plan.root / "runs" / "terminal-guard-stop.json", body, mode="ascii")
        self._state("STOPPED", failure_stage="terminal_latch", failed_shot_id=task.shot_id,
                    failed_chunk_name=task.name)
        self.emit(f"STOP {task.shot_id}/{task.name} terminal_latch: watchdog {status}")
        return {"exit_code": 2, "completed": [], "stopped": {
            "shot_id": task.shot_id, "chunk": task.name, "stage": "terminal_latch", "latch_status": status}}
