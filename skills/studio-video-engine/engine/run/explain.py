"""``plan explain`` before a re-run: snapshots of a stage's explain inputs (old = ledger, new = this run).

``jjv plan explain --old DIR --new DIR`` needs a review config in each directory (``plan-inputs.json`` or the
``review-config*.json`` layout).  After every successful run of a stage that declares ``explain`` the JSON files
directly inside its ``inputs_dir`` are copied to ``<ledger>/<stage>/explain/`` with a descriptor; the next run
of that stage with changed inputs copies the current files to ``<run>/stages/<stage>/explain-new/`` and runs the
verb on the two folders.  The explain verb itself never runs anything; its JSON lands next to the snapshot.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..core.io import write_json_atomic

DESCRIPTOR = "plan-inputs.json"
DESCRIPTOR_SCHEMA = "jjv/plan-inputs/v1"


def snapshot(inputs_dir: Path, target: Path) -> dict[str, Any]:
    """Copy the JSON files of ``inputs_dir`` (no recursion) into ``target``; returns what was copied."""
    if not inputs_dir.is_dir():
        return {"ok": False, "reason": f"{inputs_dir} is not a directory", "files": []}
    files = sorted(p for p in inputs_dir.glob("*.json") if p.is_file() and p.name != DESCRIPTOR)
    configs = [p.name for p in files if p.name.startswith("review-config") and p.suffix == ".json"]
    if len(configs) != 1:
        return {"ok": False, "reason": f"{inputs_dir.name}: {len(configs)} review-config*.json files (need exactly one)",
                "files": [p.name for p in files]}
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for file in files:
        shutil.copy2(file, target / file.name)
    write_json_atomic(target / DESCRIPTOR, {"schema": DESCRIPTOR_SCHEMA, "config": configs[0]}, mode="utf8")
    return {"ok": True, "dir": str(target), "config": configs[0], "files": [p.name for p in files]}


def ledger_snapshot_dir(ledger_dir: Path, stage_id: str) -> Path:
    return ledger_dir / stage_id / "explain"


def run_snapshot_dir(run_dir: Path, stage_id: str) -> Path:
    return run_dir / "stages" / stage_id / "explain-new"


def explain_argv(old: Path, new: Path, target: str, json_out: Path) -> tuple[str, ...]:
    return ("plan", "explain", "--old", str(old), "--new", str(new), "--target", target, "--no-table",
            "--json-out", str(json_out))
