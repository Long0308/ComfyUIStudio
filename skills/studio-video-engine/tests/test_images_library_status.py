from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from engine.images import library_status
from engine.images.lease import holder_path


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_launched_lane_that_died_before_lane_start_is_dead_not_pending() -> None:
    case_dir = Path(".pytest_work_tmp") / f"N93-case-{uuid4().hex}"
    case_dir.mkdir()
    run_dir = case_dir / "run"
    plan = {
        "rev": "r005",
        "batches": {"batch-01": {"items": [{"prompt_id": "CHAR_01_FACE_1_r005", "char": "CHAR_01",
                                             "kind": "FACE", "prompt_sha256": None}]}},
        "lanes": [
            {"label": "launched", "account": "acct1", "variant": False, "batches": ["batch-01"]},
            {"label": "never-launched", "account": "acct2", "variant": False, "batches": ["batch-01"]},
        ],
    }
    run = {"lanes": {
        "launched": {"batches": [{"batch_id": "batch-01", "prompt_ids": ["CHAR_01_FACE_1_r005"]}]},
        "never-launched": {"batches": [{"batch_id": "batch-01", "prompt_ids": ["CHAR_01_FACE_1_r005"]}]},
    }}
    try:
        holder_path(library_status.lane_lock_path(run_dir, "launched")).parent.mkdir(parents=True)
        holder_path(library_status.lane_lock_path(run_dir, "launched")).write_text(
            json.dumps({"pid": _dead_pid(), "host": "sandbox", "created_unix": time.time(), "token": "dead-launch"}),
            encoding="ascii",
        )

        status = library_status.build_status(case_dir / "plan.json", plan, run_dir, run, library_out=None)

        assert {lane["label"]: lane["state"] for lane in status["lanes"]} == {
            "launched": "dead",
            "never-launched": "pending",
        }
    finally:
        shutil.rmtree(case_dir)
