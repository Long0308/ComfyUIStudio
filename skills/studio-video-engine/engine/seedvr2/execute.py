"""Serial, resumable SeedVR2 chunk executor (invariants I1-I6, I8, I9, I12).

Dry run is the default and touches neither the network, the lock, the ComfyUI folders nor the
disk.  ``execute`` walks the selected chunks one at a time and stops at the first failure.
Per chunk: verify segment + graph shas -> verify graph == pilot except the two ports -> guard
node classes -> stage input -> dispatch under the machine lock (``engine.comfy.dispatch``) ->
wait for history (a prompt_id is required) -> bind history to graph+client -> copy the raw
output -> raw frames must equal ``expected_raw_output_frames`` at the recipe processing size ->
trim the core and crop -> job receipt.  Nothing is ever resubmitted: an intent without a job is
reconciled by exact graph + client_id, and no match stops the run.

The one exception (T-E30): a prompt PROVEN lost to a ComfyUI/container restart (``engine.comfy.lost``:
container StartedAt changed since the dispatch + absent from history and queue twice + no output with
the chunk prefix) is archived (``abandoned-lost-<ts>/``) and re-dispatched at most ``max_lost_retries``
times per chunk; the next loss stops the run (exit 2), doubt refuses the dispatch (no StartedAt) or stops
it after 3 stalled windows with an UNCERTAIN proof (exit 2); PID locks refuse a second executor per run/machine.
"""

from __future__ import annotations

import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from ..comfy.client import ComfyClient
from ..comfy.dispatch import INTENT_FILE, INTENT_SCHEMA, dispatch, post_evidence
from ..comfy.docker_probe import ContainerProbe, DockerProbe
from ..comfy.guards import ClassPolicy, check_graph
from ..comfy.graph_identity import wanted_shas
from ..comfy.history import select_bound_entry
from ..comfy.lost import LostPrompt
from ..comfy.pilot_guard import PilotGuard
from ..comfy.outputs import node_output_entries, resolve_output
from ..comfy.reconcile import PromptAbsent, reconcile_intent, verify_known_prompt
from ..comfy.settings import ComfySettings
from ..comfy.staging import input_state, link_new_file, require_hash, stage_input
from ..comfy.wait import wait_for_history
from ..config.loader import ResolvedConfig
from ..core.errors import EngineError, Failed, Refused, Uncertain, WaitTimeout, exit_code_for
from ..core.filelock import run_lock
from ..core.runlock import run_pid_lock
from ..core.io import read_json, sha256_file, write_json_atomic, write_json_once
from ..core.paths import require_inside
from ..health.preflight import require_ready
from ..media.probe import probe_video
from . import receipts as rc
from .execplan import ExecPlan, Task, verify_task_graph
from .finalize import finalize_shot_if_complete
from .media_ops import Probe, Runner, default_runner, trim_core, verify_video
from .pilot import PilotGuardMixin
from .recovery import LostRecovery
from .recipe import load_pilot_graph

RUN_PID_LOCK = "RUN-LOCK.json"  # single-executor guard (engine.core.runlock), beside run-state.json
# The machine-level twin (ComfySettings.executor_lock_path, beside the machine gpu lock) excludes executors
# of OTHER plans.  Non-engine executors (e.g. the frozen v004 script) do not take it: see SKILL.md.
_PROTECT_JOB = frozenset({"existing_state", "state_drift", "job_unreadable", "intent_missing"})
Emit = Callable[[str], None]
SamplerFactory = Callable[[Path], Any]


def _stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _stage_of(error: BaseException) -> str:
    if isinstance(error, EngineError) and error.evidence.get("stage"):
        return str(error.evidence["stage"])
    return {"PostOutcomeUnknown": "post_outcome_unknown", "WaitTimeout": "history_timeout",
            "Refused": "refused", "Failed": "comfy_execution"}.get(type(error).__name__, "execution")


class Executor(PilotGuardMixin, LostRecovery):
    def __init__(self, *, config: ResolvedConfig, recipe: dict, plan: ExecPlan, settings: ComfySettings,
                 repo_root: Path, client: ComfyClient | None = None, probe: Probe = probe_video,
                 runner: Runner = default_runner, sampler_factory: SamplerFactory | None = None,
                 clock: Callable[[], float] = time.time, emit: Emit = _stderr,
                 container_probe: ContainerProbe | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 pilot_guard_factory: "Callable[[Executor], PilotGuard] | None" = None) -> None:
        self.config, self.recipe, self.plan, self.settings = config, recipe, plan, settings
        self.client = client or ComfyClient(settings.base_url, timeout_seconds=settings.http_timeout_seconds)
        self.probe, self.runner, self.sampler_factory = probe, runner, sampler_factory
        self.clock, self.emit, self.sleep = clock, emit, sleep
        self.container_probe: ContainerProbe = container_probe or DockerProbe()
        self.policy = ClassPolicy.from_domain(config.domain)
        self.pilot_graph = load_pilot_graph(recipe, repo_root)
        self._class_cache: dict[str, str | None] = {}
        self._posted = False  # True once THIS chunk attempt may have caused / resumed a POST
        self.lost_redispatches: list[dict] = []
        self.pilot: PilotGuard | None = None  # chỉ có khi exec plan opt-in `terminal_guard: true` (v004)
        self._pilot_guard_factory = pilot_guard_factory or self._default_pilot_guard

    # ---- verification ------------------------------------------------------------------
    def graph_for(self, task: Task) -> tuple[dict, str]:
        """The chunk API graph: canonical sha == plan, and == pilot except the two ports (``execplan``)."""
        return verify_task_graph(self.plan, task, pilot_graph=self.pilot_graph, recipe=self.recipe)

    def validate_task_files(self, task: Task) -> tuple[Path, dict, str]:
        chunk, g = task.chunk, self.plan.geometry
        segment = require_inside(self.plan.segments_root / chunk["segment_path"], self.plan.segments_root,
                                 f"{task.shot_id}/{task.name} segment")
        require_hash(segment, chunk["segment_sha256"], f"{task.shot_id}/{task.name} segment")
        graph, graph_sha = self.graph_for(task)
        native = self.recipe["native"]  # the qualified size, never a number read from the plan
        verify_video(segment, frames=chunk["segment_frames"], width=native["width"],
                     height=native["height"], fps=g.fps, probe=self.probe)
        return segment, graph, graph_sha

    def identity(self, task: Task) -> dict[str, Any]:
        return rc.task_identity(self.plan, task, graph_file_sha256=self.graph_for(task)[1])

    # ---- dry run -----------------------------------------------------------------------
    def dry_run(self, tasks: list[Task]) -> list[dict]:
        rows = []
        for task in tasks:
            _, graph, graph_sha = self.validate_task_files(task)
            check_graph(None, graph, self.policy)  # static class policy only; no network
            name = task.chunk["comfy_input_name"]
            if Path(name).name != name:
                raise Refused(f"unsafe ComfyUI input name: {name!r}")
            label = f"CHUNK {task.shot_id}/{task.name}"
            self.emit(f"{label} raw_output_frames_expected={task.chunk['expected_raw_output_frames']} "
                      f"plan_padded_frames={task.chunk['seedvr2_padded_frames']} "
                      f"segment_sha256={task.chunk['segment_sha256']} VERIFIED "
                      f"api_graph_canonical_sha256={task.chunk['api_graph_canonical_sha256']} VERIFIED")
            self.emit(f"{label} WOULD stage ComfyUI input {self.settings.input_dir / name} "
                      "(ComfyUI folders are not inspected in a dry run)")
            self.emit(f"{label} POST skipped (dry-run)")
            rows.append({"shot_id": task.shot_id, "chunk": task.name, "graph_file_sha256": graph_sha,
                         "post": "POST skipped (dry-run)"})
        self.emit(f"DRY-RUN planned_chunks={len(tasks)}; no queue/history access, no lock, "
                  "no filesystem writes, no GPU submission")
        return rows

    # ---- one chunk ---------------------------------------------------------------------
    @staticmethod
    def _read_job(path: Path, label: str) -> dict[str, Any]:
        try:
            job = read_json(path)
        except Uncertain as error:
            raise Uncertain(f"{label} job.json is unreadable and will not be overwritten: {error}",
                            evidence={"stage": "job_unreadable"}) from error
        if not isinstance(job, dict):
            raise Uncertain(f"{label} job.json is not a JSON object", evidence={"stage": "job_unreadable"})
        return job

    def process_chunk(self, task: Task, *, resume: bool, history_max_items: int) -> dict[str, Any]:
        self._posted = False
        require_hash(self.plan.path, self.plan.sha256, "plan before chunk")
        paths = rc.task_paths(self.plan, task)
        identity = self.identity(task)
        label = f"{task.shot_id}/{task.name}"
        evidence = post_evidence(paths["chunk_dir"])  # what is on disk, not what this attempt did
        intent_exists, job_exists = INTENT_FILE in evidence, paths["job"].exists()
        job = rc.base_job(identity, task, self.clock)
        redispatches = 0 if job_exists else self.lost_retries_used(task)  # Uncertain if the ledger outruns the archives
        if redispatches and not job_exists:
            job["lost_redispatches"] = redispatches  # this job is the re-dispatch after a proven loss
        if job_exists:
            job = self._read_job(paths["job"], label)
            rc.verify_job_identity(job, identity, task)
        if not intent_exists and (evidence or job.get("prompt_id")):
            raise Uncertain(f"{label} has post evidence ({evidence or 'job.prompt_id'}) but no dispatch intent; "
                            "a second POST is forbidden. Inspect ComfyUI queue/history by hand",
                            evidence={"stage": "intent_missing", "post_evidence": evidence})
        state = {"stage": "existing_state"}
        if job_exists:
            if job.get("status") == "COMPLETED":
                if not resume:
                    raise Refused(f"{label} is already COMPLETED; use --resume to verify and skip it",
                                  evidence=state)
                rc.verify_completed_chunk(self.plan, task, job, identity, self.probe)
                self.emit(f"CHUNK {label} RESUME verified COMPLETED; POST skipped")
                return job
            if not resume:
                raise Refused(f"{label} has job state {job.get('status')!r}; use --resume", evidence=state)
        if intent_exists:
            if not resume:
                raise Refused(f"{label} has a dispatch intent; use --resume (reconcile, never resubmit)",
                              evidence=state)
            self._posted = True  # a prior attempt dispatched: nothing here may report "nothing sent"
            return self.resume_intent(task, identity, job)
        if not resume and (job_exists or paths["chunk_dir"].exists()):
            raise Refused(f"{label} already has run state; use --resume", evidence=state)
        job.pop("failure", None)  # a re-dispatch after a pre-POST failure starts clean
        segment, graph, _ = self.validate_task_files(task)
        check_graph(self.client, graph, self.policy, cache=self._class_cache)
        stage_input(segment, self.settings.input_dir, task.chunk["comfy_input_name"],
                    task.chunk["segment_sha256"])
        job.update(status="PREPARED", updated_at=self.clock())
        write_json_atomic(paths["job"], job, mode="ascii")
        require_ready(self.client, self.settings, graph=graph, min_free_vram_mib=int(self.recipe.get("min_free_vram_mib", 0)))  # T-E39
        try:
            result = dispatch(self.client, self.settings, graph=graph, receipt_dir=paths["chunk_dir"],
                              identity={"kind": "seedvr2-chunk", **identity}, client_prefix=rc.CLIENT_PREFIX,
                              history_max_items=history_max_items, clock=self.clock,
                              container_instance=self._container_instance,
                              guard=self.pilot.guard if self.pilot is not None else None)
        finally:
            # No intent existed before this call, so an intent now means a POST may have happened.
            self._posted = paths["intent"].exists()
        job = {**job, "status": "SUBMITTED", "prompt_id": result.prompt_id,
               "correlation_id": result.correlation_id, "client_id": result.client_id,
               "prompt_response": result.response, "submitted_at": self.clock(), "updated_at": self.clock(),
               **({"submitted_receipt_error": result.submitted_receipt_error}
                  if result.submitted_receipt_error else {})}
        write_json_atomic(paths["job"], job, mode="ascii")
        return self.materialize(task, job, graph, identity)

    def resume_intent(self, task: Task, identity: dict, job: dict) -> dict[str, Any]:
        paths = rc.task_paths(self.plan, task)
        intent = read_json(paths["intent"])
        rc.verify_intent(intent, identity, INTENT_SCHEMA)
        graph, _ = self.graph_for(task)
        graph_sha, client_id = intent["graph_sha256"], intent["client_id"]
        wanted = wanted_shas(graph, graph_sha)  # ComfyUI may record int widgets as floats
        if graph_sha != task.chunk["api_graph_canonical_sha256"]:
            raise Uncertain(f"{task.name} intent graph sha differs from the plan",
                            evidence={"stage": "state_drift"})
        known = job.get("prompt_id")
        submitted = paths["chunk_dir"] / "submitted.json"
        if known is None and submitted.is_file():
            known = read_json(submitted).get("prompt_id")
        if known:
            try:
                verify_known_prompt(self.client, prompt_id=known, graph_sha256=wanted, client_id=client_id)
            except PromptAbsent as absent:
                self._lost_or_raise(task, absent, job=job, prompt_id=known, graph_sha256=wanted,
                                    client_id=client_id, intent=intent)
            prompt_id = known
        else:
            found = reconcile_intent(self.client, graph_sha256=wanted, client_id=client_id,
                                     history_max_items=max(200, 2 * len(self.plan.tasks)))
            if found.status != "matched":
                self._lost_or_raise(
                    task, Uncertain(f"{task.shot_id}/{task.name} has a dispatch intent but no unique queue/history "
                                    "match; automatic resubmission is forbidden",
                                    evidence={"stage": "reconciliation_no_match", "client_id": client_id}),
                    job=job, prompt_id=None, graph_sha256=wanted, client_id=client_id, intent=intent)
            prompt_id = found.prompt_id
            job = {**job, "status": "SUBMITTED", "prompt_id": prompt_id, "reconciled_at": self.clock()}
        job.pop("failure", None)
        job = {**job, "correlation_id": intent["correlation_id"], "client_id": client_id,
               "updated_at": self.clock()}
        write_json_atomic(paths["job"], job, mode="ascii")
        return self.materialize(task, job, graph, identity)

    def materialize(self, task: Task, job: dict, graph: dict, identity: dict) -> dict[str, Any]:
        paths, g = rc.task_paths(self.plan, task), self.plan.geometry
        chunk, prompt_id, client_id = task.chunk, job["prompt_id"], job["client_id"]
        job = {**job, "status": "WAITING", "wait_started_at": self.clock(), "updated_at": self.clock()}
        write_json_atomic(paths["job"], job, mode="ascii")
        sampler = self.sampler_factory(paths["telemetry"]) if self.sampler_factory else nullcontext()
        with sampler as active, self._pilot_watch(task, job):
            watchdog = self._watchdog(task, job, active)
            try:
                history = wait_for_history(self.client, prompt_id,
                                           timeout_seconds=self.settings.history_timeout_seconds,
                                           poll_seconds=self.settings.poll_seconds, sleep=self.sleep,
                                           on_pending=self._pending_hook(watchdog))
            except WaitTimeout as timeout:  # the hard timeout also gets the proof before it gives up
                self._lost_or_raise(task, timeout, job=job, prompt_id=prompt_id,
                                    graph_sha256=wanted_shas(graph, chunk["api_graph_canonical_sha256"]), client_id=client_id)
        # summarise AFTER the sampler stopped (its thread replaces the samples file; hashing it live raced)
        telemetry = active.summary() if hasattr(active, "summary") else None
        try:
            entry = select_bound_entry({prompt_id: history}, prompt_id=prompt_id, client_id=client_id,
                                       graph=graph, label="completed history")
        finally:
            write_json_once(paths["history"], {prompt_id: history}, mode="ascii")
        if paths["core_dir"].exists() and any(paths["core_dir"].iterdir()):
            raise Failed("an unreceipted core already exists; reconcile before that media can be reused",
                         evidence={"stage": "output_validation", "core_dir": str(paths["core_dir"])})
        records = node_output_entries(entry, rc.OUTPUT_NODE)
        if len(records) != 1:
            raise Failed(f"history must hold exactly one node-{rc.OUTPUT_NODE} video output; found {len(records)}",
                         evidence={"stage": "output_validation"})
        source = resolve_output(self.settings.output_dir, records[0])
        output = link_new_file(source, paths["output_dir"] / Path(records[0]["filename"]).name,
                               sha256_file(source), "copied output")
        try:
            verify_video(output, frames=chunk["expected_raw_output_frames"], width=g.processing_width,
                         height=g.processing_height, fps=g.fps, probe=self.probe, error=Failed)
        except Failed as error:
            error.evidence["stage"] = "output_validation"
            raise
        core = paths["core_dir"] / f"{output.stem}-core-{g.final_width}x{g.final_height}.mp4"
        trim_core(output, core, offset=chunk["core_offset_in_segment"], frames=chunk["core_frames"],
                  geometry=g, runner=self.runner, probe=self.probe)
        output_sha, core_sha = sha256_file(output), sha256_file(core)
        done = {**job, "status": "COMPLETED", "completed_at": self.clock(), "updated_at": self.clock(),
                "history_path": str(paths["history"]), "history_sha256": sha256_file(paths["history"]),
                "history_output": records[0], "output_path": str(output), "output_sha256": output_sha,
                "output_frame_count": chunk["expected_raw_output_frames"],
                "output_dimensions": {"width": g.processing_width, "height": g.processing_height},
                "core_path": str(core), "core_sha256": core_sha, "core_frame_count": chunk["core_frames"],
                "core_dimensions": {"width": g.final_width, "height": g.final_height},
                "core_encoding": g.core_encoding, "telemetry": telemetry,
                "core_provenance": rc.provenance(self.plan, task, job, output_sha, core_sha,
                                                 identity["api_graph_file_sha256"]),
                **({"stall_alerts": {"path": str(paths["chunk_dir"] / "stall-alerts.json"),
                                     "count": len(read_json(paths["chunk_dir"] / "stall-alerts.json"))}}
                   if (paths["chunk_dir"] / "stall-alerts.json").is_file() else {})}
        write_json_atomic(paths["job"], done, mode="ascii")
        return done

    # ---- run loop ----------------------------------------------------------------------
    def mark_failure(self, task: Task, error: BaseException) -> dict[str, Any]:
        """Record a failure.  ``posted`` comes from the receipts on disk (any post evidence, from
        this or an earlier run), so a later refusal can never report exit 1 after a POST.  An
        unreadable, foreign, COMPLETED or state-refused job.json is NEVER rewritten: the failure goes
        to the sibling ``job-check-failure.json``."""
        paths = rc.task_paths(self.plan, task)
        posted = self._posted or bool(post_evidence(paths["chunk_dir"]))
        failure = {"stage": _stage_of(error), "message": str(error), "error_type": type(error).__name__,
                   "evidence": getattr(error, "evidence", {}), "uncertain": isinstance(error, Uncertain),
                   "intent_exists": paths["intent"].exists(), "posted": posted,
                   "exit_code": exit_code_for(error, posted=posted), "automatic_resubmit": False}
        job: dict | None = None
        if paths["job"].exists():
            try:
                job = self._read_job(paths["job"], task.name)
            except Uncertain:
                job = None
            if job is None or job.get("status") == "COMPLETED" or failure["stage"] in _PROTECT_JOB:
                write_json_atomic(paths["chunk_dir"] / "job-check-failure.json", failure, mode="ascii")
                return {"status": "UNCHANGED", "failure": failure}
        job = job or {"schema": rc.JOB_SCHEMA, "shot_id": task.shot_id, "chunk_name": task.name,
                      "plan_sha256": self.plan.sha256}
        job = {**job, "status": "FAILED", "prior_status": job.get("status"), "failed_at": self.clock(),
               "updated_at": self.clock(), "failure": failure}
        write_json_atomic(paths["job"], job, mode="ascii")
        return job

    def _state(self, status: str, **extra: Any) -> None:
        write_json_atomic(self.plan.root / "runs" / "run-state.json", {
            "schema": rc.RUN_SCHEMA, "status": status, "episode_id": self.plan.plan["episode_id"],
            "plan_sha256": self.plan.sha256, "at": self.clock(), "automatic_retry": bool(self.lost_redispatches),
            **({"lost_redispatches": self.lost_redispatches} if self.lost_redispatches else {}), **extra},
            mode="ascii")

    def run(self, tasks: list[Task], *, resume: bool = False, break_stale_lock: bool = False) -> dict[str, Any]:
        """Execute ``tasks`` serially; returns a summary with ``exit_code`` (never raises for a
        chunk failure, so the failure receipt is always written first)."""
        s = self.settings
        if s.history_timeout_seconds < s.min_history_timeout_seconds:
            raise Refused(f"history timeout must be at least {s.min_history_timeout_seconds:g}s")
        runs = self.plan.root / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        done: list[dict] = []
        holder = {"plan": str(self.plan.root), "plan_sha256": self.plan.sha256}
        with run_pid_lock(runs / RUN_PID_LOCK, break_stale=break_stale_lock, report_dir=runs, clock=self.clock), \
                run_pid_lock(s.executor_lock_path, break_stale=break_stale_lock, report_dir=runs, clock=self.clock,
                             extra=holder, scope="machine"), \
                run_lock(runs / ".executor.lock", timeout_seconds=s.lock_timeout_seconds):
            self._load_prior_redispatches()
            self._start_pilot_guard()  # opt-in: marker + guard + pollers TRƯỚC dispatch đầu tiên
            self._state("RUNNING", selected_chunk_count=len(tasks), resume=resume)
            for task in tasks:
                stopped = self._terminal_stop(task)
                if stopped:
                    return {**stopped, "completed": done}
                try:
                    job = self._run_task(task, resume=resume)
                except Exception as error:  # noqa: BLE001 - the receipt is written, then the run stops
                    failed = self.mark_failure(task, error)
                    self._state("STOPPED", failed_shot_id=task.shot_id, failed_chunk_name=task.name,
                                failure=failed["failure"])
                    self.emit(f"STOP {task.shot_id}/{task.name} {failed['failure']['stage']}: {error}")
                    return {"exit_code": failed["failure"]["exit_code"], "completed": done,
                            "stopped": {"shot_id": task.shot_id, "chunk": task.name, **failed["failure"]}}
                done.append({"shot_id": task.shot_id, "chunk": task.name, "status": job["status"]})
            shots, stop = self._finalize_complete_shots()
            if stop:
                self._state("STOPPED", failure_stage="shot_finalize", failure_message=stop["error"])
                return {"exit_code": stop["exit_code"], "completed": done, "shots": shots, "stopped": stop}
            self._state("COMPLETED_SELECTION", selected_chunk_count=len(tasks), resume=resume)
        return {"exit_code": 0, "completed": done, "shots": shots, "stopped": None}

    def _finalize_complete_shots(self) -> tuple[list[dict], dict | None]:
        shots: list[dict] = []
        for shot_id in self.plan.shot_ids:
            try:
                receipt = finalize_shot_if_complete(
                    self.plan, shot_id, verify=lambda t, j: rc.verify_completed_chunk(
                        self.plan, t, j, self.identity(t), self.probe),
                    probe=self.probe, runner=self.runner, clock=self.clock, emit=self.emit)
            except Exception as error:  # noqa: BLE001
                return shots, {"shot_id": shot_id, "error": str(error), "exit_code": exit_code_for(error)}
            if receipt:
                shots.append({"shot_id": shot_id, "path": receipt["path"], "frame_count": receipt["frame_count"]})
        return shots, None
