"""Reuse evidence of ``jjv run episode``: input hashes, receipt presence, the per-stage ledger, the time log.

A stage is REUSED (not re-run) only when BOTH hold: its ledger entry (written after its last successful run)
records the same ``inputs_sha256`` as the inputs on disk now, AND every declared receipt pattern matches at
least one file.  Receipts made by hand (a shipped episode without a ledger) are never silently reused: the
engine can not tell them from stale ones, so the stage is listed as ``run`` and the decision says why.
"""

from __future__ import annotations

import glob
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.io import canonical_sha256, read_json, sha256_file, write_json_atomic

LEDGER_SCHEMA = "jjv/run-ledger-entry/v1"
TIME_LOG = "stage-times.jsonl"
ABSENT = "absent"
MTIME_SLACK = 2.0   # seconds: FAT-class file systems round mtime down to 2 s


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_glob(text: str) -> bool:
    return any(ch in text for ch in "*?[")


def expand(pattern: str) -> list[Path]:
    """Files matching a resolved path or glob, sorted; a plain path that exists is itself."""
    if _is_glob(pattern):
        return sorted(Path(p) for p in glob.glob(pattern) if Path(p).is_file())
    path = Path(pattern)
    return [path] if path.is_file() else []


def hash_inputs(patterns: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    """``(sha256 of the canonical {path: sha} map, the map)``; an absent input hashes as the word ``absent``."""
    table: dict[str, str] = {}
    for pattern in patterns:
        found = expand(pattern)
        if not found:
            table[pattern] = ABSENT
        for file in found:
            table[str(file)] = sha256_file(file)
    return canonical_sha256(table, mode="utf8"), table


def receipts_state(patterns: tuple[str, ...]) -> tuple[bool, dict[str, list[str]]]:
    """Every pattern must match at least one file; returns the matches per pattern (the reuse question)."""
    found = {pattern: [str(p) for p in expand(pattern)] for pattern in patterns}
    return all(found[p] for p in patterns), found


def fresh_receipts_state(patterns: tuple[str, ...], *, since: float, named: set[str], shas: set[str]
                         ) -> tuple[bool, dict[str, list[str]], list[str]]:
    """Like :func:`receipts_state`, but a match proves THIS run only when it was written at or after ``since`` (the
    stage's start, wall clock, with :data:`MTIME_SLACK` for coarse file systems) or a step's output named it (its path
    or its sha256: a verb that reused an identical versioned file).  Older matches are listed as stale and ignored."""
    found: dict[str, list[str]] = {}
    stale: list[str] = []
    for pattern in patterns:
        fresh = []
        for file in expand(pattern):
            if file.stat().st_mtime >= since - MTIME_SLACK or str(file.resolve()) in named or sha256_file(file) in shas:
                fresh.append(str(file))
            else:
                stale.append(str(file))
        found[pattern] = fresh
    return all(found[p] for p in patterns), found, stale


def receipts_sha(found: dict[str, list[str]]) -> dict[str, str]:
    return {file: sha256_file(Path(file)) for files in found.values() for file in files}


def entry_path(ledger_dir: Path, stage_id: str) -> Path:
    return ledger_dir / f"{stage_id}.json"


def read_entry(ledger_dir: Path, stage_id: str) -> dict[str, Any] | None:
    path = entry_path(ledger_dir, stage_id)
    if not path.is_file():
        return None
    entry = read_json(path)
    return entry if isinstance(entry, dict) and entry.get("schema") == LEDGER_SCHEMA else None


def write_entry(ledger_dir: Path, stage_id: str, *, run_id: str, inputs_sha256: str, inputs: dict[str, str],
                receipts: dict[str, str], dag_sha256: str, status: str = "complete") -> Path:
    """Mutable state (the latest successful run wins); the run receipt is the immutable record.
    ``status`` is ``complete`` or ``steps-done`` (steps succeeded, the stage's post-step human gate is still open)."""
    path = entry_path(ledger_dir, stage_id)
    write_json_atomic(path, {"schema": LEDGER_SCHEMA, "stage": stage_id, "run_id": run_id, "ended": utc_now(),
                             "status": status, "dag_sha256": dag_sha256, "inputs_sha256": inputs_sha256,
                             "inputs": inputs, "receipts": receipts}, mode="utf8")
    return path


def mark_complete(ledger_dir: Path, stage_id: str) -> None:
    entry = read_entry(ledger_dir, stage_id)
    if entry and entry.get("status") != "complete":
        write_json_atomic(entry_path(ledger_dir, stage_id), {**entry, "status": "complete"}, mode="utf8")


def decide_reuse(*, always: bool, entry: dict[str, Any] | None, inputs_sha256: str, receipts_ok: bool,
                 receipts_declared: bool) -> dict[str, Any]:
    """The reuse verdict and its reason, in words a human can check."""
    if always:
        return {"reuse": False, "reason": "stage is always run (declared `always`)"}
    if not receipts_declared:
        return {"reuse": False, "reason": "stage declares no receipts, so nothing proves a previous run"}
    if entry is None:
        return {"reuse": False, "reason": "no ledger entry: receipts present on disk are not proven to match "
                                          "the inputs (hand-made or pre-engine)" if receipts_ok
                                          else "no ledger entry and no receipts"}
    if entry.get("inputs_sha256") != inputs_sha256:
        return {"reuse": False, "reason": f"inputs changed since run {entry.get('run_id')} "
                                          f"({str(entry.get('inputs_sha256'))[:12]} -> {inputs_sha256[:12]})",
                "previous_run_id": entry.get("run_id")}
    if not receipts_ok:
        return {"reuse": False, "reason": f"ledger matches run {entry.get('run_id')} but a receipt is missing",
                "previous_run_id": entry.get("run_id")}
    stale = [f for f, sha in (entry.get("receipts") or {}).items()
             if not Path(f).is_file() or sha256_file(Path(f)) != sha]
    if stale:
        return {"reuse": False, "reason": f"receipt bytes changed since run {entry.get('run_id')}: {stale[:3]}",
                "previous_run_id": entry.get("run_id")}
    return {"reuse": True, "reason": f"inputs and receipts unchanged since run {entry.get('run_id')}",
            "previous_run_id": entry.get("run_id")}


class StageClock:
    """Wall-clock + monotonic timing of one step; ``row()`` is the time-log line."""

    def __init__(self, stage: str, step: str, argv: tuple[str, ...]) -> None:
        self.stage, self.step, self.argv = stage, step, list(argv)
        self.start, self._t0 = utc_now(), time.perf_counter()

    def row(self, exit_code: int | None, *, reused: bool = False, kind: str = "step") -> dict[str, Any]:
        return {"stage": self.stage, "step": self.step, "kind": kind, "argv": self.argv, "start": self.start,
                "end": utc_now(), "seconds": round(time.perf_counter() - self._t0, 3), "exit": exit_code,
                "reused": reused}


def append_time_row(run_dir: Path, row: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / TIME_LOG).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")
