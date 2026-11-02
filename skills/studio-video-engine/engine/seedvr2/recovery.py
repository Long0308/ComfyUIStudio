"""Crash recovery for the SeedVR2 executor (task T-E30), as a mixin of :class:`engine.seedvr2.execute.Executor`.

Lost-prompt proof (``engine.comfy.lost``), the stall watchdog (``engine.comfy.watchdog``), the bounded
archive-and-redispatch (``max_lost_retries`` per chunk, counted as ``max(runs/LOST-LEDGER.jsonl rows,
abandoned-lost-* folders)`` so the limit survives an executor restart AND the deletion of an archive) and the retry loop around ``process_chunk``.  The host class
supplies ``settings``, ``plan``, ``client``, ``container_probe``, ``clock``, ``emit``, ``sleep``,
``identity``, ``process_chunk`` and ``_state``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..comfy.lost import (EXHAUSTED_RECEIPT, INCIDENT_SCHEMA, LEDGER_FILE, Classification, LostPrompt,
                          archive_lost_attempt, classify_lost, lost_receipt, lost_retries_used,
                          outputs_with_prefix)
from ..comfy.graph_identity import wanted_shas
from ..comfy.queue import queue_records
from ..comfy.watchdog import StallWatchdog, expected_seconds, gpu_bucket
from ..core.errors import EngineError, Uncertain
from ..core.io import read_json, write_json_atomic
from . import receipts as rc
from .execplan import Task


class LostRecovery:
    settings: Any
    plan: Any
    client: Any
    container_probe: Any
    clock: Any
    emit: Any
    sleep: Any
    lost_redispatches: list

    # ---- crash recovery (T-E30) --------------------------------------------------------
    def _output_prefix(self, task: Task) -> str:
        return self.plan.plan["naming"]["output_prefix_template"].format(shot=task.shot_id, chunk=task.name)

    def _ledger_path(self) -> Path:
        return self.plan.root / "runs" / LEDGER_FILE

    def lost_retries_used(self, task: Task) -> int:
        return lost_retries_used(rc.task_paths(self.plan, task)["chunk_dir"], self._ledger_path(),
                                 task.shot_id, task.name)

    def _dispatch_instance(self, task: Task, intent: dict | None) -> dict | None:
        """The ``container_instance`` the dispatch recorded in the intent BEFORE its POST (None if absent)."""
        if intent is None:
            path = rc.task_paths(self.plan, task)["intent"]
            if not path.is_file():
                return None
            try:
                intent = read_json(path)
            except Uncertain:
                return None
        value = intent.get("container_instance") if isinstance(intent, dict) else None
        return value if isinstance(value, dict) else None

    def _dispatch_time(self, task: Task, job: dict, intent: dict | None) -> float:
        """job.submitted_at, else submitted.json, else the intent's created_at (first one on file)."""
        paths = rc.task_paths(self.plan, task)
        found = [job.get("submitted_at")]
        for path, key in ((paths["chunk_dir"] / "submitted.json", "submitted_at"),
                          (paths["intent"], "created_at")):
            if path.is_file():
                try:
                    found.append(read_json(path).get(key))
                except Uncertain:
                    pass
        if intent is not None:
            found.append(intent.get("created_at"))
        for value in found:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        raise Uncertain(f"{task.shot_id}/{task.name} has no recorded dispatch time; cannot prove a loss",
                        evidence={"stage": "lost_no_dispatch_time"})

    def classify(self, task: Task, *, job: dict, prompt_id: str | None, graph_sha256: str | frozenset[str] | None,
                 client_id: str | None, intent: dict | None = None) -> Classification:
        return classify_lost(
            client=self.client, probe=self.container_probe, container=self.settings.container,
            dispatch_time=self._dispatch_time(task, job, intent), output_dir=self.settings.output_dir,
            output_prefix=self._output_prefix(task), dispatch_instance=self._dispatch_instance(task, intent),
            prompt_id=prompt_id, graph_sha256=graph_sha256,
            client_id=client_id, recheck_seconds=self.settings.lost_recheck_seconds,
            history_max_items=max(200, 2 * len(self.plan.tasks)), sleep=self.sleep, clock=self.clock)

    def _lost_or_raise(self, task: Task, error: EngineError, *, job: dict, prompt_id: str | None,
                       graph_sha256: str | frozenset[str] | None, client_id: str | None,
                       intent: dict | None = None) -> None:
        """Raise ``LostPrompt`` if the loss is PROVEN; otherwise raise ``error`` carrying the verdict."""
        try:
            verdict = self.classify(task, job=job, prompt_id=prompt_id, graph_sha256=graph_sha256,
                                    client_id=client_id, intent=intent)
        except Uncertain:  # no dispatch time on file: nothing to prove, keep the original stop
            raise error from None
        if verdict.lost:
            raise LostPrompt(f"{task.shot_id}/{task.name}: {error}", classification=verdict) from error
        error.evidence["lost_classification"] = verdict.as_dict()
        raise error

    def _watchdog(self, task: Task, job: dict, active: Any) -> StallWatchdog:
        paths, prompt_id = rc.task_paths(self.plan, task), job["prompt_id"]
        graph_sha = wanted_shas(self.graph_for(task)[0], task.chunk["api_graph_canonical_sha256"])
        client_id = job["client_id"]
        expected = expected_seconds(self.settings.expected_chunk_seconds, task.chunk)
        alerts = paths["chunk_dir"] / "stall-alerts.json"
        prefix = self._output_prefix(task)

        def fingerprint() -> Any:
            running = tuple(sorted(r.prompt_id for r in queue_records(self.client.get("/queue"))))
            files = tuple((f["name"], f["bytes"]) for f in outputs_with_prefix(self.settings.output_dir, prefix))
            return (running, files, gpu_bucket(getattr(active, "samples", None)))

        def alert(body: dict) -> None:
            body = {**body, "at": self.clock(), "prompt_id": prompt_id, "expected_chunk_seconds": expected,
                    "stall_factor": self.settings.stall_factor}
            existing = read_json(alerts) if alerts.is_file() else []
            write_json_atomic(alerts, [*existing, body], mode="ascii")
            self.emit(f"STALL {task.shot_id}/{task.name}: no progress for {body['quiet_seconds']}s "
                      f"(limit {body['stall_seconds']:g}s); classification "
                      f"{body['classification']['verdict']}; still waiting for the hard timeout")

        def stop(body: dict) -> None:
            write_json_atomic(paths["chunk_dir"] / "INCIDENT-stall-uncertain.json", {
                "schema": INCIDENT_SCHEMA, "kind": "stall_uncertain", "at": self.clock(), "prompt_id": prompt_id,
                "consecutive_uncertain": body["consecutive_uncertain"], "classification": body["classification"],
                "stall_seconds": body["stall_seconds"], "expected_chunk_seconds": expected,
                "automatic_resubmit": False,
                "next_action": "fix whatever made docker/ComfyUI/the output folder unreadable, then --resume"},
                mode="ascii")
            self.emit(f"STOP {task.shot_id}/{task.name}: stall with UNCERTAIN proof x{body['consecutive_uncertain']}")

        return StallWatchdog(
            stall_seconds=self.settings.stall_factor * expected, fingerprint=fingerprint, on_alert=alert,
            on_stop=stop,
            classify=lambda: self.classify(task, job=job, prompt_id=prompt_id, graph_sha256=graph_sha,
                                           client_id=client_id))

    def _handle_lost(self, task: Task, lost: LostPrompt) -> None:
        """Archive a proven-lost attempt for ONE re-dispatch, or stop loudly when retries are used up."""
        chunk_dir = rc.task_paths(self.plan, task)["chunk_dir"]
        used, limit = self.lost_retries_used(task), self.settings.max_lost_retries
        identity = {k: v for k, v in self.identity(task).items() if k in rc.IDENTITY_KEYS}
        if used >= limit:
            receipt = lost_receipt(lost.classification, identity=identity, retries_before=used,
                                   max_lost_retries=limit, decision="STOP", clock=self.clock)
            write_json_atomic(chunk_dir / EXHAUSTED_RECEIPT, receipt, mode="ascii")
            raise Uncertain(f"{task.shot_id}/{task.name} lost its prompt again after {used} automatic "
                            f"re-dispatch(es) (max_lost_retries={limit}); stopping. See {EXHAUSTED_RECEIPT} and "
                            "the container log; raise max_lost_retries and --resume only after investigating",
                            evidence={"stage": "lost_retries_exhausted", "lost_retries_used": used,
                                      "classification": lost.classification.as_dict()})
        receipt = lost_receipt(lost.classification, identity=identity, retries_before=used,
                               max_lost_retries=limit, decision="REDISPATCH", clock=self.clock)
        archive = archive_lost_attempt(chunk_dir, receipt, self.clock, ledger=self._ledger_path(),
                                       shot_id=task.shot_id, chunk=task.name)
        self.lost_redispatches.append({"shot_id": task.shot_id, "chunk": task.name, "archive": str(archive)})
        self.emit(f"LOST {task.shot_id}/{task.name}: {lost.classification.reasons[0]}; archived to {archive.name}; "
                  f"re-dispatching ({used + 1}/{limit})")
        self._state("RUNNING")

    def _container_instance(self) -> dict[str, Any]:
        """The container's StartedAt as docker reports it now: the instance identity written into the dispatch
        intent BEFORE the POST.  Unreadable docker is recorded as such (a later loss is then UNCERTAIN)."""
        container = self.settings.container
        state = self.container_probe.state(container)
        if state is None:
            return {"container": container, "available": False}
        return {"container": container, "available": True, "started_at_text": state.started_at_text,
                "started_at": state.started_at, "running": state.running, "restart_count": state.restart_count}

    def _load_prior_redispatches(self) -> None:
        """Earlier runs' ``lost_redispatches`` come first in this run's state (an executor restart must not
        erase them); entries are de-duplicated by archive path."""
        path = self.plan.root / "runs" / "run-state.json"
        if not path.is_file():
            return
        try:
            prior = read_json(path).get("lost_redispatches") or []
            if not isinstance(prior, list):
                raise ValueError("lost_redispatches is not a list")
        except (Uncertain, ValueError, AttributeError) as error:
            self.emit(f"WARNING run-state.json could not be read for earlier lost_redispatches ({error}); "
                      "runs/LOST-LEDGER.jsonl still holds the full count")
            return
        seen = {row.get("archive") for row in self.lost_redispatches if isinstance(row, dict)}
        carried = [row for row in prior if isinstance(row, dict) and row.get("archive") not in seen]
        self.lost_redispatches = [*carried, *self.lost_redispatches]

    def _run_task(self, task: Task, *, resume: bool) -> dict[str, Any]:
        while True:
            try:
                return self.process_chunk(task, resume=resume, history_max_items=max(200, 2 * len(self.plan.tasks)))
            except LostPrompt as lost:
                self._handle_lost(task, lost)
                resume = True  # the folder is clean now; resume lets the next attempt dispatch afresh
