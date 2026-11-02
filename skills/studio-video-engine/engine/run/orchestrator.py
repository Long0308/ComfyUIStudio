"""The walk: for every stage in range -> reuse? -> gates -> plan explain (re-run) -> steps -> receipts -> ledger.

STOP rules (exit != 0, ``stop.next_step`` says what to do): a placeholder with no value (blocked), a gate verb
that fails, a ``gpu`` step without ``--approve-gpu`` (nothing is submitted) or without an available health
preflight, a health preflight that is not ready, a human gate that does not hold (listen approval, shot
acceptance, image approval, music approval, user review beyond the limit, publish approval), a declared ``pre`` /
``post`` check that fails (an unresolved ``delivery.json`` marker, a boundaries draft, an unmet H3 gap, a published
shot list the episode does not adopt), a step that exits non-zero, a receipt the stage promised but did not write
in THIS run.  ``--dry-run`` evaluates every stage read-only (each one as if it were reached, so the plan shows
every would-stop), runs NO verb (not even a gate) and writes only ``<run_dir>/plan.json``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from ..config.loader import SKILL_ROOT
from ..core.errors import EXIT_REFUSED, Refused
from ..core.io import write_json_atomic
from ..core.winflags import no_window
from . import checks
from . import explain as explain_mod
from . import gates, ledger
from . import proof as proof_mod
from .context import RunContext, Unresolved, resolve, resolve_all, shots_of
from .dag import Dag, Stage, Step, select_range

RUN_SCHEMA = "jjv/run-episode/v1"
PLAN_SCHEMA = "jjv/run-plan/v1"
Stop = dict[str, Any]


@dataclass(frozen=True)
class StepResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[tuple[str, ...]], StepResult]


def default_runner(argv: tuple[str, ...]) -> StepResult:
    """Every verb runs as its own ``python -I bin/jjv.py`` process: real exit codes, no shared state."""
    command = [sys.executable, "-I", str(SKILL_ROOT / "bin" / "jjv.py"), *argv]
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=no_window())
    return StepResult(done.returncode, done.stdout, done.stderr)


def health_gate_status(dag: Dag) -> str:
    """``available`` only when the T-E39 module imports AND ``bin/jjv.py`` registers its verb; else why not."""
    module = str(dag.health_gate.get("module") or "")
    if not module or importlib.util.find_spec(module) is None:
        return "not-available (TODO T-E39: engine/health missing)"
    if module not in (SKILL_ROOT / "bin" / "jjv.py").read_text("utf-8"):
        return "not-available (engine/health present but its verb is not registered in bin/jjv.py: " \
               "apply engine/health/CLI-PATCH-health.md)"
    return "available"


class Run:
    """One walk of the DAG for one episode.  ``execute()`` returns the run receipt (also written to disk)."""

    def __init__(self, ctx: RunContext, dag: Dag, *, from_id: str | None, to_id: str | None, runner: Runner) -> None:
        if dag.human_proof == "required" and not ctx.proof_required:
            ctx = replace(ctx, proof_required=True)       # the recipe, not the caller, decides that a name is not enough
        self.ctx, self.dag, self.runner = ctx, dag, runner
        self._gpu: tuple[proof_mod.Verified | None, str] | None = None   # (verified GPU proof, why not)
        self.range = select_range(dag, from_id, to_id)
        self.bounds = {"from": from_id, "to": to_id}
        self.stages: list[dict[str, Any]] = []
        self.stop: Stop | None = None
        self.health = health_gate_status(dag)
        self._stdouts: list[str] = []      # this stage's step outputs: evidence for the receipts (checks.evidence)

    # ---- helpers -------------------------------------------------------------------------------------
    def _stop(self, stage: Stage, kind: str, reason: str, next_step: str, *, step: str | None = None,
              exit_code: int = EXIT_REFUSED) -> Stop:
        record = {"stage": stage.id, "step": step, "kind": kind, "reason": reason, "next_step": next_step,
                  "exit_code": exit_code or EXIT_REFUSED}
        if self.stop is None:
            self.stop = record
        return record

    def _rerun_hint(self, stage: Stage) -> str:
        return f"fix the cause, then `jjv run episode --episode {self.ctx.ref} --from {stage.id}`"

    def _run_verb(self, stage: Stage, step_id: str, argv: tuple[str, ...], *, kind: str) -> dict[str, Any]:
        clock = ledger.StageClock(stage.id, step_id, argv)
        result = self.runner(argv)
        row = clock.row(result.exit_code, kind=kind)
        ledger.append_time_row(self.ctx.run_dir, row)
        folder = self.ctx.run_dir / "stages" / stage.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{kind}-{step_id}.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (folder / f"{kind}-{step_id}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        if kind == "step":
            self._stdouts.append(result.stdout)
        return {"id": step_id, "argv": list(argv), "exit": result.exit_code, "seconds": row["seconds"],
                "start": row["start"], "end": row["end"]}

    def _expand_steps(self, stage: Stage) -> list[dict[str, Any]]:
        rows = []
        for step in stage.steps:
            if not step.per_shot:
                rows.append({"step": step, "shot": None, "argv": checks.optional_argv(step, self.ctx, stage.id)})
                continue
            for shot in shots_of(Path(resolve(step.per_shot, self.ctx, stage.id))):
                extra = {"shot": shot}
                if any("{approved_sha}" in token for token in step.argv):  # the images pick of this shot
                    spec = gates.spec_of(stage.human_gates, "images-approval", self.ctx, stage.id)
                    try:
                        extra["approved_sha"] = gates.approved_sha(spec, shot)
                    except Unresolved as error:
                        rows.append({"step": step, "shot": shot, "argv": None, "unresolved": str(error)})
                        continue
                rows.append({"step": step, "shot": shot, "argv": checks.optional_argv(step, self.ctx, stage.id, extra)})
        return rows

    def _gpu_authorization(self, stage: Stage) -> tuple[proof_mod.Verified | None, str]:
        """Recipe ``gpu_authorization: proof``: ``--approve-gpu`` is only a request; dispatch needs a signed GPU proof
        for this episode, THIS recipe hash and this stage (file token = speed bump, see engine/run/proof.py)."""
        if self.dag.gpu_authorization != "proof":
            return None, ""
        if self.ctx.gpu_proof is None:
            return None, "no --gpu-proof: a bare --approve-gpu flag is a request, not an authorization"
        try:
            ok = proof_mod.verify(proof_mod.load_file(self.ctx.gpu_proof), gate="gpu-dispatch", episode_id=self.ctx.episode_id,
                                  domain=self.ctx.domain_id)
        except Refused as error:
            return None, f"gpu proof refused: {error}"
        scope = ok.scope
        if scope.get("dag_sha256") != self.dag.sha256 or stage.id not in (scope.get("stages") or []):
            return None, f"gpu proof {ok.proof_id} does not cover recipe {self.dag.sha256[:12]} / stage {stage.id}"
        return ok, ""

    def _gate_state(self, stage: Stage, gate: str) -> gates.GateState:
        try:
            return gates.check(self.ctx, stage.id, stage.human_gates, gate)
        except Unresolved as error:
            return gates.GateState(gate, False, f"cannot evaluate: {error}", self._rerun_hint(stage))

    def _check(self, stage: Stage, spec: dict[str, Any], *, step: str | None = None) -> tuple[dict[str, Any], Stop | None]:
        """One declared read-only check; a pending verdict (its file is planned) stops only a real run."""
        verdict = checks.evaluate(spec, self.ctx, stage.id)
        if verdict.ok or (verdict.pending and self.ctx.dry_run):
            return verdict.as_dict(), None
        return verdict.as_dict(), self._stop(stage, verdict.kind, verdict.detail, verdict.next_step, step=step)

    # ---- one stage -----------------------------------------------------------------------------------
    def _stage(self, stage: Stage, out_of_range: str | None) -> None:
        report: dict[str, Any] = {"id": stage.id, "s": stage.s, "label": stage.label, "needs": list(stage.needs),
                                  "known_gap": stage.known_gap, "gates": [], "explain": None, "steps": [], "human": None}
        self.stages.append(report)
        if out_of_range:
            report.update(status="skipped-range", reason=out_of_range)
            return
        if self.stop is not None and not self.ctx.dry_run:
            report.update(status="pending", reason=f"not reached: run stopped at stage {self.stop['stage']}")
            return
        report["after_stop"] = self.stop is not None
        try:
            self._stage_body(stage, report)
        except Unresolved as error:
            report.update(status="blocked", reason=str(error))
            report["would_stop" if self.ctx.dry_run else "stop"] = self._stop(
                stage, "blocked", str(error), f"declare the missing input, then re-run --from {stage.id}")

    def _stage_body(self, stage: Stage, report: dict[str, Any]) -> None:
        ctx = self.ctx
        self._stdouts = []
        started = time.time()
        inputs = resolve_all(stage.inputs, ctx, stage.id)
        receipts = resolve_all(stage.receipts, ctx, stage.id)
        inputs_sha, table = ledger.hash_inputs(inputs)
        receipts_ok, found = ledger.receipts_state(receipts)
        entry = ledger.read_entry(ctx.ledger_dir, stage.id)
        decision = ledger.decide_reuse(always=stage.always, entry=entry, inputs_sha256=inputs_sha,
                                       receipts_ok=receipts_ok, receipts_declared=bool(receipts))
        report.update(inputs_sha256=inputs_sha, inputs=table, receipts={"ok": receipts_ok, "found": found},
                      reuse=decision)
        if decision["reuse"]:
            local = self._reused(stage, report)
        else:
            plan = self._expand_steps(stage)
            local = self._gates(stage, report) or self._explain(stage, report, entry)
            local = self._steps(stage, report, plan, local)
            if local is None and ctx.dry_run and stage.has_post:
                local = self._post_gate(stage, report)
        if ctx.dry_run:
            report["status"] = "reuse" if decision["reuse"] else "planned"
            if local:
                report["would_stop"] = local
            return
        if local:
            report.update(status="stopped", stop=local)
            return
        if not decision["reuse"]:
            self._finish(stage, report, inputs_sha, table, receipts, started)

    def _post_gate(self, stage: Stage, report: dict[str, Any]) -> Stop | None:
        """The stage's human gate, then its declared post checks: read-only, re-evaluated on reuse and in --dry-run."""
        if stage.human:
            state = self._gate_state(stage, str(stage.human))
            report["human"] = state.as_dict()
            if not state.ok:
                return self._stop(stage, "human-gate", state.detail, state.next_step)
        report["post"] = []
        for spec in stage.post:
            verdict, local = self._check(stage, spec)
            report["post"].append(verdict)
            if local:
                return local
        return None

    def _reused(self, stage: Stage, report: dict[str, Any]) -> Stop | None:
        report["status"] = "reused"
        local = self._post_gate(stage, report) if stage.has_post else None
        if local is None and not self.ctx.dry_run:
            ledger.mark_complete(self.ctx.ledger_dir, stage.id)
            ledger.append_time_row(self.ctx.run_dir, ledger.StageClock(stage.id, "-", ()).row(0, reused=True, kind="stage"))
        return local

    def _gates(self, stage: Stage, report: dict[str, Any]) -> Stop | None:
        for gate in stage.gates:
            argv = resolve_all(gate.argv, self.ctx, stage.id)
            if self.ctx.dry_run:
                report["gates"].append({"id": gate.id, "argv": list(argv), "status": "planned"})
                continue
            row = self._run_verb(stage, gate.id, argv, kind="gate")
            report["gates"].append({**row, "status": "ok" if row["exit"] == 0 else "failed"})
            if row["exit"] != 0:
                return self._stop(stage, "gate-failed", f"gate {gate.id} exited {row['exit']}", self._rerun_hint(stage),
                                  step=gate.id, exit_code=row["exit"])
        return None

    def _explain(self, stage: Stage, report: dict[str, Any], entry: dict[str, Any] | None) -> Stop | None:
        if not stage.explain:
            report["explain"] = {"status": "not-declared", "reason": "stage consumes no review config"}
            return None
        if entry is None:
            report["explain"] = {"status": "first-run", "reason": "no previous run of this stage in the ledger"}
            return None
        old = explain_mod.ledger_snapshot_dir(self.ctx.ledger_dir, stage.id)
        new_dir = explain_mod.run_snapshot_dir(self.ctx.run_dir, stage.id)
        inputs_dir = Path(resolve(stage.explain["inputs_dir"], self.ctx, stage.id))
        argv = explain_mod.explain_argv(old, new_dir, str(stage.explain.get("target", "review")),
                                        new_dir.parent / "plan-explain.json")
        if self.ctx.dry_run:
            report["explain"] = {"status": "planned", "argv": list(argv), "previous_run_id": entry.get("run_id")}
            return None
        if not (old / explain_mod.DESCRIPTOR).is_file():
            report["explain"] = {"status": "skipped", "reason": f"previous run {entry.get('run_id')} left no explain snapshot"}
            return None
        snap = explain_mod.snapshot(inputs_dir, new_dir)
        if not snap["ok"]:
            report["explain"] = {"status": "skipped", "reason": snap["reason"]}
            return None
        row = self._run_verb(stage, "plan-explain", argv, kind="explain")
        report["explain"] = {**row, "status": "ok" if row["exit"] == 0 else "failed", "previous_run_id": entry.get("run_id")}
        if row["exit"] != 0:
            return self._stop(stage, "explain-failed", f"plan explain exited {row['exit']}", self._rerun_hint(stage),
                              step="plan-explain", exit_code=row["exit"])
        return None

    def _steps(self, stage: Stage, report: dict[str, Any], plan: list[dict[str, Any]], local: Stop | None) -> Stop | None:
        for item in plan:
            step: Step = item["step"]
            row: dict[str, Any] = {"id": step.id, "shot": item["shot"], "argv": list(item["argv"] or ()), "gpu": step.gpu,
                                   "human": step.human, "note": step.note}
            report["steps"].append(row)
            if local is not None:
                row["status"] = "after-stop"
                continue
            local = self._step(stage, step, item, row)
        return local

    def _step(self, stage: Stage, step: Step, item: dict[str, Any], row: dict[str, Any]) -> Stop | None:
        if item["argv"] is None:
            row["status"] = "blocked"
            return self._stop(stage, "blocked", item["unresolved"], self._rerun_hint(stage), step=step.id)
        exists = checks.write_once_exists(step, self.ctx, stage.id)
        if exists:
            row.update(status="exists", reason=f"write-once output already on disk: {exists} (the verb would refuse "
                                                "to overwrite it; move it aside to rebuild)")
            return None
        if step.human:
            state = self._gate_state(stage, step.human)
            row["human_state"] = state.as_dict()
            if not state.ok:
                row["status"] = "stop"
                return self._stop(stage, "human-gate", state.detail, state.next_step, step=step.id)
        if step.gpu and not self.ctx.approve_gpu:
            row["status"] = "stop"
            return self._stop(stage, "gpu-approval", f"step {step.id} spends GPU time and --approve-gpu was not "
                              "given; nothing was submitted", "get the user's explicit approval for THIS run, then "
                              f"re-run with --approve-gpu --from {stage.id}", step=step.id)
        extra: tuple[str, ...] = ()
        if step.gpu and self.dag.gpu_authorization == "proof":
            verified, why = self._gpu_authorization(stage)
            if verified is None:
                row["status"] = "stop"
                return self._stop(stage, "gpu-approval", f"step {step.id}: {why}; nothing was submitted",
                                  "the user signs a scoped GPU proof, then re-run with --approve-gpu --gpu-proof FILE "
                                  f"--from {stage.id}", step=step.id)
            row["gpu_proof"] = verified.proof_id
            extra = next((a for m, a in step.argv_if_mode if m == verified.scope.get("mode")), ())
            item = {**item, "argv": (*item["argv"], *extra)}
            row["argv"] = list(item["argv"])
        if step.pre:
            row["pre"], local = self._check(stage, step.pre, step=step.id)
            if local:
                row["status"] = "stop"
                return local
        if step.gpu:
            row["health_gate"] = self.health
            if self.health != "available":
                row["status"] = "stop"
                return self._stop(stage, "health-gate", f"health preflight is {self.health}; a GPU step never runs "
                                  "unchecked (nothing was submitted)", "register `jjv health preflight` "
                                  f"(engine/health/CLI-PATCH-health.md), then re-run --approve-gpu --from {stage.id}",
                                  step=step.id)
        if self.ctx.dry_run:
            row["status"] = "planned"
            return None
        if step.gpu:
            argv = resolve_all(tuple(self.dag.health_gate.get("argv") or ()), self.ctx, stage.id)
            health = self._run_verb(stage, f"health-{step.id}", argv, kind="gate")
            row["health_result"] = health
            if health["exit"] != 0:
                row["status"] = "stop"
                return self._stop(stage, "health-gate", f"health preflight exited {health['exit']} (nothing was "
                                  "submitted)", "fix docker/ComfyUI by hand as the preflight report says, then "
                                  f"re-run --approve-gpu --from {stage.id}", step=step.id, exit_code=health["exit"])
        label = f"{step.id}-{item['shot']}" if item["shot"] else step.id
        result = self._run_verb(stage, label, item["argv"], kind="step")
        row.update(result, status="ok" if result["exit"] == 0 else "failed")
        if result["exit"] != 0:
            return self._stop(stage, "step-failed", f"step {step.id} exited {result['exit']}", self._rerun_hint(stage),
                              step=step.id, exit_code=result["exit"])
        return None

    def _finish(self, stage: Stage, report: dict[str, Any], inputs_sha: str, table: dict[str, str],
                receipts: tuple[str, ...], started: float) -> None:
        named, shas = checks.evidence(self._stdouts, self.ctx.episode_root)
        receipts_ok, found, stale = ledger.fresh_receipts_state(receipts, since=started, named=named, shas=shas)
        report["receipts"] = {"ok": receipts_ok, "found": found, "stale": stale}
        if not receipts_ok:
            missing = [p for p, files in found.items() if not files]
            reason = f"stage steps exited 0 but receipts are missing: {missing}"
            if stale:
                reason += f"; stale files from an earlier run do not count: {stale[:3]}"
            report.update(status="stopped", stop=self._stop(stage, "receipt-missing", reason, self._rerun_hint(stage),
                                                            exit_code=2))
            return
        local = self._post_gate(stage, report) if stage.has_post else None
        ledger.write_entry(self.ctx.ledger_dir, stage.id, run_id=self.ctx.run_id, inputs_sha256=inputs_sha,
                           inputs=table, receipts=ledger.receipts_sha(found), dag_sha256=self.dag.sha256,
                           status="steps-done" if local else "complete")
        if stage.explain:
            inputs_dir = Path(resolve(stage.explain["inputs_dir"], self.ctx, stage.id))
            report["explain_snapshot"] = explain_mod.snapshot(
                inputs_dir, explain_mod.ledger_snapshot_dir(self.ctx.ledger_dir, stage.id))
        if local:
            report.update(status="stopped", stop=local)
            return
        report["status"] = "ran"

    # ---- the walk ------------------------------------------------------------------------------------
    def execute(self) -> dict[str, Any]:
        for stage, out_of_range in self.range:
            self._stage(stage, out_of_range)
        exit_code = 0 if self.stop is None or self.ctx.dry_run else int(self.stop["exit_code"])
        receipt = {"schema": PLAN_SCHEMA if self.ctx.dry_run else RUN_SCHEMA, "ok": self.stop is None,
                   "dry_run": self.ctx.dry_run, "run_id": self.ctx.run_id, "run_dir": str(self.ctx.run_dir),
                   "episode_id": self.ctx.episode_id, "domain": self.ctx.domain_id, "episode_file": str(self.ctx.episode_file),
                   "dag": {"id": self.dag.id, "path": str(self.dag.path), "sha256": self.dag.sha256},
                   "bounds": self.bounds, "approve_gpu": self.ctx.approve_gpu, "health_gate": self.health,
                   "stages_root": str(self.ctx.stages_root), "ledger_dir": str(self.ctx.ledger_dir),
                   "first_stop": self.stop, "exit_code": exit_code, "stages": self.stages,
                   "ran_nothing": self.ctx.dry_run}
        write_json_atomic(self.ctx.run_dir / ("plan.json" if self.ctx.dry_run else "run.json"), receipt,
                          mode="utf8", stamp=True)
        return receipt
