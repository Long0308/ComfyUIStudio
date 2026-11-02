"""Receipts of a SeedVR2 run: identity, job, intent checks, provenance, completed-chunk proof.

Layout under the plan folder (``plan.root``)::

    runs/<shot>/<chunk>/{job.json, dispatch-intent.json, submitted.json, history.json,
                         telemetry-samples.json, output/<raw>.mp4, core/<core>.mp4}
    runs/<shot>/{shot.json, <shot>-core.mp4}     runs/run-state.json

``job.json`` is the only mutable receipt (atomic replace); everything else is write-once.
Identity fields bind a receipt to the exact plan, segment and graph it was made for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..core.errors import Refused, Uncertain
from ..core.paths import require_inside
from ..comfy.staging import require_hash
from .execplan import ExecPlan, Task
from .media_ops import Probe, verify_video
from .recipe import OUTPUT_PORT

JOB_SCHEMA = "jjv/seedvr2-chunk-job/v1"
RUN_SCHEMA = "jjv/seedvr2-run/v1"
SHOT_SCHEMA = "jjv/seedvr2-shot/v1"
CLIENT_PREFIX = "jjv-"
OUTPUT_NODE = OUTPUT_PORT[0]
IDENTITY_KEYS = ("episode_id", "production_version", "shot_id", "chunk_index", "chunk_name", "plan_sha256",
                 "segment_sha256", "comfy_input_name", "api_graph_canonical_sha256", "api_graph_file_sha256")


def task_paths(plan: ExecPlan, task: Task) -> dict[str, Path]:
    runs = plan.root / "runs"
    chunk_dir = require_inside(runs / task.shot_id / task.name, runs, "chunk run folder")
    return {"runs": runs, "chunk_dir": chunk_dir, "job": chunk_dir / "job.json",
            "intent": chunk_dir / "dispatch-intent.json", "history": chunk_dir / "history.json",
            "telemetry": chunk_dir / "telemetry-samples.json", "output_dir": chunk_dir / "output",
            "core_dir": chunk_dir / "core"}


def task_identity(plan: ExecPlan, task: Task, *, graph_file_sha256: str) -> dict[str, Any]:
    chunk = task.chunk
    return {"episode_id": plan.plan["episode_id"], "production_version": plan.plan["production_version"],
            "shot_id": task.shot_id, "chunk_index": chunk["index"], "chunk_name": task.name,
            "plan_sha256": plan.sha256, "segment_sha256": chunk["segment_sha256"],
            "comfy_input_name": chunk["comfy_input_name"],
            "api_graph_canonical_sha256": chunk["api_graph_canonical_sha256"],
            "api_graph_file_sha256": graph_file_sha256}


def base_job(identity: dict[str, Any], task: Task, clock: Callable[[], float]) -> dict[str, Any]:
    chunk = task.chunk
    return {"schema": JOB_SCHEMA, "status": "PREPARED", "canonicalization": "ascii", **identity,
            "raw_output_frames_expected": chunk["expected_raw_output_frames"],
            "plan_padded_frames": chunk["seedvr2_padded_frames"],
            "expected_core_frame_count": chunk["core_frames"],
            "prompt_id": None, "correlation_id": None, "client_id": None,
            "created_at": clock(), "updated_at": clock()}


def _drift(found: dict, expected: dict, label: str) -> None:
    bad = {k: {"expected": v, "actual": found.get(k)} for k, v in expected.items() if found.get(k) != v}
    if bad:
        raise Uncertain(f"{label} drifted from the plan: {bad}", evidence={"stage": "state_drift"})


def verify_job_identity(job: dict, identity: dict[str, Any], task: Task) -> None:
    _drift(job, {"schema": JOB_SCHEMA, **identity,
                 "raw_output_frames_expected": task.chunk["expected_raw_output_frames"],
                 "plan_padded_frames": task.chunk["seedvr2_padded_frames"]}, "durable chunk job")


def verify_intent(intent: dict, identity: dict[str, Any], intent_schema: str) -> None:
    _drift(intent, {"schema": intent_schema, "kind": "seedvr2-chunk", **identity}, "dispatch intent")
    correlation, client = intent.get("correlation_id"), intent.get("client_id")
    if not isinstance(correlation, str) or not correlation or client != CLIENT_PREFIX + correlation:
        raise Uncertain("dispatch intent has an inconsistent correlation_id/client_id",
                        evidence={"stage": "state_drift"})


def provenance(plan: ExecPlan, task: Task, job: dict[str, Any], output_sha: str, core_sha: str,
               graph_file_sha256: str) -> dict[str, Any]:
    return {"output_sha256": output_sha, "core_sha256": core_sha, "prompt_id": job["prompt_id"],
            "correlation_id": job["correlation_id"], "api_graph_file_sha256": graph_file_sha256,
            "api_graph_canonical_sha256": task.chunk["api_graph_canonical_sha256"],
            "trim_offset": task.chunk["core_offset_in_segment"], "trim_frames": task.chunk["core_frames"],
            "crop": plan.geometry.crop_filter, "encoding": plan.geometry.core_encoding}


def verify_completed_chunk(plan: ExecPlan, task: Task, job: dict, identity: dict[str, Any],
                           probe: Probe) -> None:
    """A COMPLETED job is trusted only after its output and core re-hash and re-probe."""
    verify_job_identity(job, identity, task)
    if job.get("status") != "COMPLETED":
        raise Refused(f"{task.shot_id}/{task.name} job is not COMPLETED")
    chunk_dir = task_paths(plan, task)["chunk_dir"]
    output = require_inside(Path(job.get("output_path") or ""), chunk_dir / "output", "completed output")
    core = require_inside(Path(job.get("core_path") or ""), chunk_dir / "core", "completed core")
    require_hash(output, job.get("output_sha256") or "", "completed output")
    require_hash(core, job.get("core_sha256") or "", "completed core")
    expected = provenance(plan, task, job, job["output_sha256"], job["core_sha256"],
                          identity["api_graph_file_sha256"])
    _drift(job.get("core_provenance") or {}, expected, "completed core provenance")
    g = plan.geometry
    verify_video(output, frames=task.chunk["expected_raw_output_frames"], width=g.processing_width,
                 height=g.processing_height, fps=g.fps, probe=probe)
    verify_video(core, frames=task.chunk["core_frames"], width=g.final_width, height=g.final_height,
                 fps=g.fps, probe=probe)
