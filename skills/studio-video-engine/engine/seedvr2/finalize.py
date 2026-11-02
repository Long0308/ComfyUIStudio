"""Per-shot finalize: concatenate the verified chunk cores into one shot file.

Runs only when EVERY chunk of the shot is COMPLETED and each completed chunk re-verifies
(hashes, provenance, probes).  The concat is a stream copy of the cores (they share encoding
and size by construction), written to a temp file, probed for the EXACT frame count the plan
promises, then hard-linked into place (no overwrite).  The shot receipt is write-once.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Callable

from ..comfy.staging import require_hash
from ..core.errors import Failed, Refused
from ..core.io import read_json, sha256_file, write_atomic, write_json_once
from . import receipts as rc
from .execplan import ExecPlan, Task
from .media_ops import Probe, Runner, run_command, verify_video


def _concat_list(cores: list[Path]) -> bytes:
    lines = []
    for core in cores:
        escaped = str(core.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _verify_shot(plan: ExecPlan, path: Path, frames: int, probe: Probe) -> None:
    g = plan.geometry
    verify_video(path, frames=frames, width=g.final_width, height=g.final_height, fps=g.fps, probe=probe)


def finalize_shot_if_complete(plan: ExecPlan, shot_id: str, *, verify: Callable[[Task, dict], None],
                              probe: Probe, runner: Runner, clock: Callable[[], float],
                              emit: Callable[[str], None] = lambda message: None) -> dict[str, Any] | None:
    """Return the shot receipt, or None while any chunk of the shot is not COMPLETED."""
    tasks = plan.shot_tasks(shot_id)
    jobs: list[dict] = []
    for task in tasks:
        job_path = rc.task_paths(plan, task)["job"]
        if not job_path.is_file():
            return None
        job = read_json(job_path)
        if job.get("status") != "COMPLETED":
            return None
        jobs.append(job)
    for task, job in zip(tasks, jobs):
        verify(task, job)
    shot = tasks[0].shot
    expected = sum(t.chunk["core_frames"] for t in tasks)
    if expected != shot["expected_output"]["restored_core_frames"]:
        raise Failed(f"{shot_id} core frame total {expected} differs from the plan")
    g = plan.geometry
    shot_dir = plan.root / "runs" / shot_id
    destination = shot_dir / f"{shot_id}-core-{g.final_width}x{g.final_height}.mp4"
    receipt_path = shot_dir / "shot.json"
    if destination.exists() or receipt_path.exists():
        if not (destination.is_file() and receipt_path.is_file()):
            raise Refused(f"{shot_id}: shot concat and receipt are not paired")
        receipt = read_json(receipt_path)
        require_hash(destination, receipt.get("sha256") or "", "existing shot concat")
        _verify_shot(plan, destination, expected, probe)
        return receipt
    concat_list = shot_dir / "concat-cores.list"
    write_atomic(concat_list, _concat_list([Path(j["core_path"]) for j in jobs]))
    temporary = shot_dir / f".{shot_id}.{uuid.uuid4().hex}.tmp.mp4"
    try:
        run_command(runner, ["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                             "-map", "0:v:0", "-c", "copy", "-an", str(temporary)], f"{shot_id} concat")
        _verify_shot(plan, temporary, expected, probe)
        try:
            os.link(temporary, destination)
        except FileExistsError as error:
            raise Refused(f"refusing to overwrite shot concat: {destination}") from error
    finally:
        temporary.unlink(missing_ok=True)
    receipt = {"schema": rc.SHOT_SCHEMA, "status": "COMPLETED", "episode_id": plan.plan["episode_id"],
               "production_version": plan.plan["production_version"], "shot_id": shot_id,
               "plan_sha256": plan.sha256, "path": str(destination), "sha256": sha256_file(destination),
               "frame_count": expected, "expected_frame_count": shot["expected_output"]["restored_core_frames"],
               "fps": g.fps_text, "dimensions": {"width": g.final_width, "height": g.final_height},
               "concat_codec": "stream-copy", "core_encodings": [g.core_encoding], "finalized_at": clock(),
               "chunk_cores": [{"chunk_name": t.name, "core_path": j["core_path"], "core_sha256": j["core_sha256"],
                                "core_frame_count": j["core_frame_count"]} for t, j in zip(tasks, jobs)]}
    write_json_once(receipt_path, receipt, mode="ascii")
    emit(f"SHOT {shot_id} FINALIZED {destination} frames={expected}")
    return receipt
