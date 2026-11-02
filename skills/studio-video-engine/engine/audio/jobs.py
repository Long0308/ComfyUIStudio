"""Guarded ComfyUI execution shared by ``audio music`` and ``audio sfx`` (REUSES ``engine.comfy``).

One job = one API graph = one receipt dir ``<out>/jobs/<job_id>/``.  State is derived from the receipts:

* READY     no post evidence: ``cmd_submit`` (graph sha + node-class guards + GPU lock + idle queue + intent + POST)
            then ``cmd_wait`` (bound history entry, ``job.json``).
* PENDING   post evidence without a COMPLETED ``job.json``: NEVER POSTed again.  A prompt id on file -> wait;
            an intent only -> ``cmd_reconcile`` (GETs) then wait; no trace -> Uncertain (exit 2).
* COMPLETED ``job.json`` COMPLETED and its outputs still hash: reused.
Dry run (no ``--execute``) does no HTTP at all.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..comfy.client import ComfyClient
from ..comfy.commands import JOB_FILE, cmd_reconcile, cmd_submit, cmd_wait
from ..comfy.dispatch import post_evidence
from ..comfy.guards import ClassPolicy, check_graph
from ..comfy.settings import ComfySettings
from ..core.errors import Failed, Refused, Uncertain
from ..core.io import read_json, sha256_file, write_json_once, write_once
from ..health.preflight import require_ready
from . import graphs

JOBS_DIR = "jobs"
WORKFLOWS_DIR = "workflows"


@dataclass(frozen=True)
class RunContext:
    client: ComfyClient
    settings: ComfySettings
    policy: ClassPolicy
    out: Path
    timeout_seconds: float
    emit: Callable[[str], None] = lambda message: None


def filename_prefix(episode_id: str, run_name: str, job_id: str) -> str:
    return f"episodes/{episode_id}/{run_name}/{job_id}"


def write_workflow(out: Path, job_id: str, graph: dict) -> dict:
    """Write the API graph write-once (``workflows/<job>.api.json``); returns path and file sha.

    The bytes are ``json.dumps(graph, ensure_ascii=False, indent=1) + newline``: the format of the first
    episode's saved audio graphs, so the same graph has the same FILE sha as its already-run twin."""
    payload = (json.dumps(graph, ensure_ascii=False, indent=1) + chr(10)).encode("utf-8")
    path = Path(out) / WORKFLOWS_DIR / f"{job_id}.api.json"
    return {"graph_file": f"{WORKFLOWS_DIR}/{job_id}.api.json", "graph_file_sha256": write_once(path, payload),
            "graph_sha256": graphs.graph_sha256(graph)}


def model_rows(recipe: dict) -> list[dict]:
    return [{"role": m["role"], "path": m["path"], "bytes": m["bytes"], "sha256": m["sha256"],
             "licence_id": m["licence_id"]} for m in recipe["models"]]


def licence_rows(recipe: dict) -> dict:
    used = {m["licence_id"] for m in recipe["models"]}
    return {key: value for key, value in recipe["licences"].items() if key in used}


def verify_models(recipe: dict, comfy_root: Path, *, full: bool) -> list[dict]:
    """Every pinned model must exist with the pinned size; ``full`` also re-hashes it (sha256)."""
    rows = []
    for model in recipe["models"]:
        path = Path(comfy_root) / model["path"]
        if not path.is_file():
            raise Refused(f"model file missing: {path}")
        size = path.stat().st_size
        if size != model["bytes"]:
            raise Refused(f"model {model['path']}: {size} bytes on disk, recipe pins {model['bytes']}")
        if full:
            digest = sha256_file(path)
            if digest != model["sha256"]:
                raise Refused(f"model {model['path']}: sha256 {digest} != pinned {model['sha256']}")
        rows.append({"path": model["path"], "bytes": size, "sha256_verified": full, "sha256": model["sha256"]})
    return rows


def job_dir(out: Path, job: dict) -> Path:
    return Path(out) / job["receipt_dir"]


def job_state(out: Path, job: dict) -> str:
    folder = job_dir(out, job)
    done = folder / JOB_FILE
    if done.is_file():
        status = read_json(done).get("status")
        if status == "COMPLETED":
            return "COMPLETED"
        if status == "FAILED":
            return "FAILED"
    return "PENDING" if post_evidence(folder) else "READY"


def dry_rows(out: Path, plan: dict, policy: ClassPolicy) -> list[dict]:
    rows = []
    for job in plan["jobs"]:
        graph = read_json(Path(out) / job["graph_file"])
        check_graph(None, graph, policy)  # static refusals only (no network)
        rows.append({"job_id": job["job_id"], "state": job_state(out, job), "graph_sha256": job["graph_sha256"],
                     "seconds": job.get("seconds")})
    return rows


def _graph_path(ctx: RunContext, job: dict) -> Path:
    path = ctx.out / job["graph_file"]
    graph = read_json(path)
    if graphs.graph_sha256(graph) != job["graph_sha256"] or sha256_file(path) != job["graph_file_sha256"]:
        raise Refused(f"{job['job_id']}: the saved graph no longer matches the plan (re-plan in a new folder)")
    return path


def _completed(ctx: RunContext, job: dict) -> dict:
    data = read_json(job_dir(ctx.out, job) / JOB_FILE)
    outputs = [o for o in data.get("outputs", []) if o.get("exists") and o.get("sha256")]
    if not outputs:
        raise Failed(f"{job['job_id']}: COMPLETED job.json lists no existing output")
    return data


def _resume(ctx: RunContext, job: dict) -> dict:
    folder = job_dir(ctx.out, job)
    has_prompt = any((folder / name).is_file() for name in ("submitted.json", "reconciled.json"))
    if not has_prompt:
        report, code = cmd_reconcile(ctx.client, ctx.settings, receipt_dir=folder)
        if code != 0:
            raise Uncertain(f"{job['job_id']}: an intent exists but the prompt cannot be found ({report}); "
                            "never resubmitted. Inspect ComfyUI and use a new plan folder", evidence=report)
    cmd_wait(ctx.client, ctx.settings, receipt_dir=folder, timeout_seconds=ctx.timeout_seconds)
    return _completed(ctx, job)


def run_job(ctx: RunContext, job: dict, *, models_checked: Callable[[], None]) -> dict:
    state = job_state(ctx.out, job)
    folder = job_dir(ctx.out, job)
    if state == "COMPLETED":
        _completed(ctx, job)
        return {"job_id": job["job_id"], "status": "REUSED"}
    if state == "FAILED":
        raise Failed(f"{job['job_id']}: ComfyUI reported a failure earlier (job.json); plan a new version folder")
    if state == "PENDING":
        ctx.emit(f"{job['job_id']}: resuming (post evidence on disk, never re-POSTed)")
        _resume(ctx, job)
        return {"job_id": job["job_id"], "status": "COMPLETED", "resumed": True}
    if ctx.settings.executor_lock_path.exists():
        raise Refused(f"a machine executor lock exists ({ctx.settings.executor_lock_path}); an upscale run is active")
    models_checked()
    folder.mkdir(parents=True, exist_ok=True)
    require_ready(ctx.client, ctx.settings, graph=read_json(_graph_path(ctx, job)), min_free_vram_mib=0)  # T-E39 (no VRAM minimum in audio recipes yet)
    submitted = cmd_submit(ctx.client, ctx.settings, ctx.policy, graph_path=_graph_path(ctx, job),
                           receipt_dir=folder, expect_sha=job["graph_file_sha256"])
    cmd_wait(ctx.client, ctx.settings, receipt_dir=folder, timeout_seconds=ctx.timeout_seconds)
    _completed(ctx, job)
    return {"job_id": job["job_id"], "status": "COMPLETED", "prompt_id": submitted["prompt_id"]}


def run_all(ctx: RunContext, plan: dict, recipe: dict, comfy_root: Path) -> dict:
    """Serial; stops at the first failure.  Models are hashed once, before the first POST."""
    state = {"done": False}

    def check_models() -> None:
        if not state["done"]:
            verify_models(recipe, comfy_root, full=True)
            state["done"] = True

    results = []
    for job in plan["jobs"]:
        results.append(run_job(ctx, job, models_checked=check_models))
    return {"results": results, "completed": sum(r["status"] == "COMPLETED" for r in results),
            "reused": sum(r["status"] == "REUSED" for r in results)}


def job_output(out: Path, job: dict, recipe: dict, output_root: Path) -> dict:
    """The one SaveAudio output of a COMPLETED job, with its file verified against the recorded sha."""
    done = job_dir(out, job) / JOB_FILE
    if not done.is_file():
        raise Uncertain(f"{job['job_id']}: no job.json yet (not generated); run submit --execute first")
    data = read_json(done)
    if data.get("status") != "COMPLETED":
        raise Refused(f"{job['job_id']}: not COMPLETED ({data.get('status')}); run submit first")
    rows = [o for o in data.get("outputs", []) if o.get("node_id") == recipe["output"]["node"] and o.get("exists")]
    if len(rows) != 1:
        raise Refused(f"{job['job_id']}: expected exactly one output of node {recipe['output']['node']}, found {len(rows)}")
    path = Path(rows[0]["path"])
    if not path.is_file() or sha256_file(path) != rows[0]["sha256"]:
        raise Refused(f"{job['job_id']}: ComfyUI output {path} is missing or differs from job.json")
    return {"path": path, "sha256": rows[0]["sha256"], "prompt_id": data.get("prompt_id"),
            "client_id": data.get("client_id"), "graph_sha256": data.get("graph_sha256")}


def decode_to_wav(ffmpeg: str, source: Path, scratch: Path, *, rate: int, channels: int = 2,
                  runner: Callable[..., Any] = subprocess.run, soxr: bool = False) -> bytes:
    """FLAC (or any ffmpeg-readable file) -> PCM16 WAV bytes at the editorial rate (real resample;
    ``soxr`` = the SoX resampler at precision 28, the SFX rule for the 44.1 kHz native clips)."""
    scratch.mkdir(parents=True, exist_ok=True)
    temporary = scratch / f".{uuid.uuid4().hex}.decode.wav"
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-i", str(source),
               *(["-af", "aresample=resampler=soxr:precision=28"] if soxr else []), "-ar", str(rate),
               "-ac", str(channels), "-c:a", "pcm_s16le", str(temporary)]
    try:
        done = runner(command, capture_output=True, text=True, timeout=900, check=False)
        if done.returncode != 0:
            raise Uncertain(f"ffmpeg decode failed ({done.returncode}): {done.stderr.strip()[:300]}")
        return temporary.read_bytes()
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"ffmpeg could not run: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)


def write_receipt_once(path: Path, document: dict) -> str:
    return write_json_once(path, document, mode="ascii", stamp=True)
