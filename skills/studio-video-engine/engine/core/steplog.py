"""STEPLOG: append-only per-step input/output log of an engine run (domain-neutral).

Each run directory holds ``steplog.jsonl``: one canonical JSON line per step, chained through
``prev_sha256`` (sha256 of the previous raw line, without its newline). A line records the step's input
files (path, sha256, role), its output files, the settings (always with an explicit ``seed``), the model
name/sha, the status (COMPLETE | FAIL | SKIPPED) and ``input_key``: sha256 of the canonical JSON of
{step_id, input sha256s, settings, model}.

``verify`` re-checks the chain, every line and every referenced file. ``plan_resume`` decides, read-only,
which steps can be reused and which must be rerun. Nothing in this module runs a step.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from .errors import Refused
from .filelock import run_lock
from .io import canonical_json, canonical_sha256, sha256_bytes, sha256_file

SCHEMA = "jjv/steplog/v1"
LOG_NAME = "steplog.jsonl"
LOCK_NAME = ".steplog.lock"
GENESIS = "0" * 64
STATUSES = ("COMPLETE", "FAIL", "SKIPPED")
DECISIONS = ("reuse", "rerun", "downstream-rerun")
REQUIRED_KEYS = ("schema", "run_id", "seq", "step_id", "stage", "started", "ended", "elapsed_ms", "inputs",
                 "settings", "outputs", "model", "status", "input_key", "prev_sha256")


def input_key(step_id: str, input_shas: Sequence[str | None], settings: dict[str, Any], model: dict[str, Any]) -> str:
    """sha256 of the canonical JSON of what a step consumed: step id, input file hashes, settings (seed), model."""
    return canonical_sha256({"step_id": step_id, "inputs": list(input_shas), "settings": settings,
                             "model": {"name": model.get("name"), "sha256": model.get("sha256")}}, mode="utf8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _stored(run_dir: Path, path: Path) -> str:
    """Path inside the run directory is stored relative to it; anything outside stays absolute."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path(run_dir).resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _absolute(run_dir: Path, stored: str) -> Path:
    candidate = Path(stored)
    return candidate if candidate.is_absolute() else Path(run_dir) / candidate


def file_ref(run_dir: Path, path: Path, role: str) -> dict[str, Any]:
    path = Path(path)
    digest = sha256_file(path) if path.is_file() else None
    return {"path": _stored(run_dir, path), "sha256": digest, "role": role}


def append(run_dir: Path, *, run_id: str, step_id: str, stage: str, started: str, inputs: list[dict[str, Any]],
           settings: dict[str, Any], outputs: list[dict[str, Any]], model: dict[str, Any], status: str,
           elapsed_ms: int = 0, error: str | None = None, note: str | None = None) -> dict[str, Any]:
    """Append one step line under the run lock. Refuses when the existing log is not intact."""
    if status not in STATUSES:
        raise Refused(f"steplog status must be one of {STATUSES}, got {status!r}")
    if status == "COMPLETE" and (not outputs or any(item.get("sha256") is None for item in outputs)):
        raise Refused(f"step {step_id} is COMPLETE but outputs are empty or an output is not on disk; nothing was logged")
    settings = {"seed": None, **settings}
    model = {"name": model.get("name"), "sha256": model.get("sha256")}
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    with run_lock(run_dir / LOCK_NAME, timeout_seconds=60.0):
        records, errors, raw = _scan(run_dir, check_files=False)
        if errors:
            raise Refused("steplog is not intact; refusing to append: " + "; ".join(errors[:3]))
        if records and records[0].get("run_id") != run_id:
            raise Refused(f"steplog belongs to run {records[0].get('run_id')!r}, not {run_id!r}")
        record: dict[str, Any] = {
            "schema": SCHEMA, "run_id": run_id, "seq": len(records) + 1, "step_id": step_id, "stage": stage,
            "started": started, "ended": _now(), "elapsed_ms": elapsed_ms, "inputs": inputs, "settings": settings,
            "outputs": outputs, "model": model, "status": status,
            "input_key": input_key(step_id, [item["sha256"] for item in inputs], settings, model),
            "prev_sha256": sha256_bytes(raw[-1]) if raw else GENESIS,
        }
        if error is not None:
            record["error"] = error
        if note is not None:
            record["note"] = note
        line = canonical_json(record, mode="utf8") + b"\n"
        with (run_dir / LOG_NAME).open("ab") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
    return record


class Step:
    """One step in progress. Inputs are hashed at start; the caller registers outputs after writing them."""

    def __init__(self, run_dir: Path, run_id: str, step_id: str, stage: str,
                 inputs: Sequence[tuple[str, Path]], settings: dict[str, Any] | None,
                 model: dict[str, Any] | None) -> None:
        self.run_dir = Path(run_dir)
        self.run_id, self.step_id, self.stage = run_id, step_id, stage
        self.started = _now()
        self._t0 = time.monotonic()
        self.inputs = [file_ref(self.run_dir, Path(path), role) for role, path in inputs]
        self.settings: dict[str, Any] = dict(settings or {})
        self.model: dict[str, Any] = dict(model or {})
        self.outputs: list[dict[str, Any]] = []
        self.status: str | None = None
        self.note: str | None = None

    def output(self, path: Path, role: str) -> None:
        self.outputs.append(file_ref(self.run_dir, Path(path), role))

    def skip(self, note: str) -> None:
        """Nothing was produced on purpose (dry run, gate): the line says SKIPPED with the reason."""
        self.status, self.note = "SKIPPED", note


@contextmanager
def logged_step(run_dir: Path, *, run_id: str, step_id: str, stage: str,
                inputs: Sequence[tuple[str, Path]] = (), settings: dict[str, Any] | None = None,
                model: dict[str, Any] | None = None) -> Iterator[Step]:
    """Write exactly one line for the block: COMPLETE on success, SKIPPED if the block called skip(), FAIL on error."""
    step = Step(run_dir, run_id, step_id, stage, inputs, settings, model)
    try:
        yield step
    except BaseException as error:
        _log(step, "FAIL", error=f"{type(error).__name__}: {error}"[:500])
        raise
    _log(step, step.status or "COMPLETE")


def _log(step: Step, status: str, *, error: str | None = None) -> dict[str, Any]:
    return append(step.run_dir, run_id=step.run_id, step_id=step.step_id, stage=step.stage, started=step.started,
                  inputs=step.inputs, settings=step.settings, outputs=step.outputs, model=step.model, status=status,
                  elapsed_ms=int((time.monotonic() - step._t0) * 1000), error=error, note=step.note)


def _file_errors(run_dir: Path, where: str, kind: str, item: dict[str, Any], *, required: bool) -> list[str]:
    recorded = item.get("sha256")
    role, stored = item.get("role"), item.get("path", "")
    if recorded is None:
        return [f"{where} {kind} {role} missing: {stored} was not on disk when logged"] if required else []
    target = _absolute(run_dir, stored)
    if not target.is_file():
        return [f"{where} {kind} {role} missing on disk: {stored}"]
    actual = sha256_file(target)
    if actual != recorded:
        return [f"{where} {kind} {role} drift: {stored} recorded {recorded[:12]} now {actual[:12]}"]
    return []


def _scan(run_dir: Path, *, check_files: bool = True) -> tuple[list[dict[str, Any]], list[str], list[bytes]]:
    """Parse every line, check canonical form, seq, chain, input_key and every referenced file."""
    path = Path(run_dir) / LOG_NAME
    if not path.is_file():
        return [], [], []
    data = path.read_bytes()
    errors: list[str] = []
    if data and not data.endswith(b"\n"):
        errors.append("last line has no trailing newline (truncated write?)")
    raw_lines = data.split(b"\n")
    if raw_lines and raw_lines[-1] == b"":
        raw_lines.pop()
    records: list[dict[str, Any]] = []
    prev = GENESIS
    run_ids: set[Any] = set()
    for index, raw in enumerate(raw_lines, start=1):
        where = f"line {index}"
        expected_prev, prev = prev, sha256_bytes(raw)
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            errors.append(f"{where}: not JSON ({error})")
            continue
        if not isinstance(record, dict):
            errors.append(f"{where}: not a JSON object")
            continue
        records.append(record)
        if canonical_json(record, mode="utf8") != raw:
            errors.append(f"{where}: not canonical JSON (edited by hand?)")
        if record.get("prev_sha256") != expected_prev:
            errors.append(f"{where}: chain broken: prev_sha256 does not match the previous line")
        missing = [key for key in REQUIRED_KEYS if key not in record]
        if missing:
            errors.append(f"{where}: missing keys {missing}")
            continue
        run_ids.add(record["run_id"])
        if record["schema"] != SCHEMA or record["seq"] != index or record["status"] not in STATUSES:
            errors.append(f"{where}: schema, seq or status is wrong")
        required = record["status"] == "COMPLETE"
        expected_key = input_key(record["step_id"], [i.get("sha256") for i in record["inputs"]],
                                 record["settings"], record["model"])
        if record["input_key"] != expected_key:
            errors.append(f"{where}: input_key does not match the line's own fields")
        if required and not record["outputs"]:
            errors.append(f"{where}: COMPLETE has no outputs")
        if check_files:
            for item in record["inputs"]:
                errors.extend(_file_errors(run_dir, where, "input", item, required=required))
            for item in record["outputs"]:
                errors.extend(_file_errors(run_dir, where, "output", item, required=required))
    if len(run_ids) > 1:
        errors.append(f"run_id differs across lines: {sorted(str(r) for r in run_ids)}")
    return records, errors, raw_lines


def verify(run_dir: Path) -> dict[str, Any]:
    """Read-only integrity check of one run directory. ok only when there are no errors."""
    path = Path(run_dir) / LOG_NAME
    if not path.is_file():
        return {"ok": False, "log": path.as_posix(), "lines": 0, "head_seq": 0,
                "errors": [f"no {LOG_NAME} under {run_dir}"]}
    records, errors, _ = _scan(Path(run_dir))
    return {"ok": not errors, "log": path.as_posix(), "lines": len(records),
            "head_seq": records[-1].get("seq", 0) if records else 0, "errors": errors}


def _current_sha(run_dir: Path, item: dict[str, Any]) -> str | None:
    target = _absolute(run_dir, item.get("path", ""))
    return sha256_file(target) if target.is_file() else None


def _output_problem(run_dir: Path, item: dict[str, Any]) -> str | None:
    recorded = item.get("sha256")
    if recorded is None:
        return "was not on disk when logged"
    now = _current_sha(run_dir, item)
    if now is None:
        return f"is missing: {item.get('path')}"
    if now != recorded:
        return f"drifted: {item.get('path')}"
    return None


def _path_key(run_dir: Path, item: dict[str, Any]) -> str:
    return os.path.normcase(str(_absolute(run_dir, item["path"]).resolve()))


def _decide(run_dir: Path, record: dict[str, Any], producers: dict[str, set[str]]) -> tuple[str, str]:
    sid = record["step_id"]
    if record.get("status") != "COMPLETE":
        why = record.get("error") or record.get("note") or "no output"
        return "rerun", f"last attempt {record.get('status')}: {why}"
    if not record.get("outputs"):
        return "rerun", "COMPLETE has no outputs"
    for item in record["outputs"]:
        problem = _output_problem(run_dir, item)
        if problem:
            return "rerun", f"output {item.get('role')} {problem}"
    for item in record.get("inputs", []):
        recorded = item.get("sha256")
        if recorded is None:
            return "rerun", f"input {item.get('role')} was not on disk when logged"
        if _current_sha(run_dir, item) != recorded:
            upstream = sorted(producers.get(_path_key(run_dir, item), set()) - {sid})
            if upstream:
                return "downstream-rerun", f"input {item.get('role')} {item.get('path')} changed (made by {upstream})"
            return "rerun", f"input {item.get('role')} {item.get('path')} changed and no logged step made it (input_key changed)"
    return "reuse", "input_key and output hashes match"


def plan_resume(run_dir: Path, from_step: str | None = None) -> dict[str, Any]:
    """Read-only plan from each step's latest attempt; --from selects its dependency descendants.

    Historic outputs (including registered partial outputs of failed attempts) establish path lineage,
    never the validity of a step's current output. That is checked against its latest COMPLETE attempt
    only when COMPLETE is also its latest status. Historical file drift remains visible in errors.
    """
    run_dir = Path(run_dir)
    records, errors, _ = _scan(run_dir)
    last: dict[str, dict[str, Any]] = {}
    producers: dict[str, set[str]] = {}
    for record in records:
        sid = record["step_id"]
        last[sid] = record
        for item in record.get("outputs", []):
            if item.get("sha256"):
                producers.setdefault(_path_key(run_dir, item), set()).add(sid)
    if from_step is not None and from_step not in last:
        raise Refused(f"--from {from_step!r}: no such step in {run_dir}")
    parents = {sid: set().union(*(producers.get(_path_key(run_dir, item), set())
                                 for item in record.get("inputs", []))) - {sid}
               for sid, record in last.items()}
    forced = {from_step} if from_step is not None else set()
    while True:
        descendants = {sid for sid, upstream in parents.items() if upstream & forced}
        if descendants <= forced:
            break
        forced.update(descendants)
    choices = {sid: _decide(run_dir, record, producers) for sid, record in last.items()}
    for sid in forced:
        choices[sid] = (("rerun", "selected by --from") if sid == from_step else
                        ("downstream-rerun", f"depends on --from {from_step}"))
    # Fixed-point propagation is independent of append/completion order (parallel shots may interleave).
    while True:
        changed = False
        for sid, upstream in parents.items():
            if choices[sid][0] != "reuse":
                continue
            pending = sorted(name for name in upstream if choices[name][0] != "reuse")
            if pending:
                choices[sid] = ("downstream-rerun", f"consumes output of {pending}")
                changed = True
        if not changed:
            break
    rows = [{"seq": record.get("seq"), "step_id": sid, "decision": choices[sid][0], "reason": choices[sid][1]}
            for sid, record in last.items()]
    return {"ok": not errors, "errors": errors, "steps": rows}


def _table(plan: dict[str, Any]) -> str:
    lines = [f"{'seq':>4}  {'step_id':<44} {'decision':<16} reason"]
    for row in plan["steps"]:
        lines.append(f"{str(row['seq']):>4}  {row['step_id']:<44} {row['decision']:<16} {row['reason']}")
    if plan["errors"]:
        lines.append("log problems: " + "; ".join(plan["errors"]))
    return "\n".join(lines)


def register_cli(stages: Any) -> None:
    parser = stages.add_parser("steplog", help="per-step input/output log: show | verify | plan-resume (read-only)")
    verbs = parser.add_subparsers(dest="verb", required=True)
    for name, text in (("show", "print every step line of --run"),
                       ("verify", "re-check the chain and every referenced file; exit 1 on any problem"),
                       ("plan-resume", "print reuse | rerun | downstream-rerun per step; executes nothing")):
        sub = verbs.add_parser(name, help=text)
        sub.add_argument("--run", required=True, help="run directory that holds steplog.jsonl")
        if name == "plan-resume":
            sub.add_argument("--from", dest="from_step", default=None,
                             help="force this step and its output-to-input dependency descendants to rerun")


def run_cli(args: argparse.Namespace) -> int:
    run = Path(args.run)
    if args.verb == "show":
        if not (run / LOG_NAME).is_file():
            print(json.dumps({"ok": False, "errors": [f"no {LOG_NAME} under {run}"]}, indent=2))
            return 1
        records, errors, _ = _scan(run)
        print(json.dumps({"ok": not errors, "errors": errors, "steps": records}, ensure_ascii=True, indent=2))
        return 0
    if args.verb == "verify":
        result = verify(run)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if result["ok"] else 1
    print(_table(plan_resume(run, from_step=args.from_step)))
    return 0
