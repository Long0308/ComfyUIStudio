"""The four stand-alone ComfyUI verbs behind ``jjv comfy``: check, submit, wait, reconcile.

Each takes an injected client/settings (tests use a fake server and temp paths).  Only
``submit`` can POST, and only through ``engine.comfy.dispatch`` after every guard passed.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from ..core.errors import Failed, Refused, Uncertain
from ..core.io import read_json, sha256_bytes, write_json_atomic
from .client import ComfyClient, ComfyError
from .dispatch import INTENT_FILE, SUBMITTED_FILE, dispatch
from .guards import ClassPolicy, check_graph, require_sha
from .history import select_bound_entry
from .outputs import collect_outputs
from .queue import may_submit, queue_counts
from .reconcile import RECONCILED_FILE, reconcile_intent, record_reconciled
from .settings import ComfySettings
from .wait import wait_for_history

JOB_FILE = "job.json"
JOB_SCHEMA = "jjv/comfy-job/v1"
DockerPs = Callable[[str], str]


def docker_ps(container: str) -> str:
    done = subprocess.run(["docker", "ps", "-a", "--filter", f"name={container}",
                           "--format", "{{.Names}}|{{.State}}|{{.Status}}"],
                          capture_output=True, text=True, timeout=30, check=False)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or "docker ps failed")
    return done.stdout


def _container_problems(settings: ComfySettings, ps: DockerPs, report: dict) -> list[str]:
    try:
        rows = [line.split("|", 2) for line in ps(settings.container).splitlines() if line.strip()]
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return [f"docker unavailable: {error}"]
    mine = [r for r in rows if r[0] == settings.container]
    if not mine:
        return [f"container {settings.container} not found"]
    state, status = (mine[0] + ["", ""])[1:3]
    report["container"] = {"state": state, "status": status}
    if state != "running":
        return [f"container {settings.container} is {state!r} ({status})"]
    return [f"container {settings.container} is unhealthy ({status})"] if "unhealthy" in status else []


def cmd_check(client: ComfyClient, settings: ComfySettings, *, ps: DockerPs = docker_ps,
              min_vram_free_mib: int = 0, strict_idle: bool = False) -> tuple[dict[str, Any], bool]:
    """Read-only readiness: container, pending-free queue, VRAM, no lock sentinel."""
    report: dict[str, Any] = {"base_url": settings.base_url}
    problems = _container_problems(settings, ps, report)
    try:
        queue = client.get("/queue")
        running, pending = queue_counts(queue)
        report["queue"] = {"running": running, "pending": pending}
        if not may_submit(queue, strict_idle=strict_idle):
            problems.append(f"queue busy (running={running}, pending={pending})")
    except (ComfyError, Uncertain) as error:
        problems.append(f"GET /queue failed: {error}")
    try:
        devices = (client.get("/system_stats") or {}).get("devices") or []
        report["vram"] = [{"name": d.get("name"), "vram_free_mib": round(d.get("vram_free", 0) / 1048576),
                           "vram_total_mib": round(d.get("vram_total", 0) / 1048576)} for d in devices]
        if not devices:
            problems.append("GET /system_stats returned no devices")
        elif min_vram_free_mib and any(v["vram_free_mib"] < min_vram_free_mib for v in report["vram"]):
            problems.append(f"free VRAM below {min_vram_free_mib} MiB")
    except (ComfyError, AttributeError) as error:
        problems.append(f"GET /system_stats failed: {error}")
    lock = settings.lock_path
    report["lock"] = {"path": str(lock), "exists": lock.exists()}
    if lock.exists():
        problems.append(f"shared submit lock file exists ({lock}); submit would refuse")
    report["ready"], report["problems"] = not problems, problems
    return report, not problems


def cmd_submit(client: ComfyClient, settings: ComfySettings, policy: ClassPolicy, *, graph_path: Path,
               receipt_dir: Path, expect_sha: str | None = None, strict_idle: bool = False) -> dict[str, Any]:
    """sha check -> class guards -> lock/queue/intent/POST.  Returns the dispatch summary."""
    graph_bytes = Path(graph_path).read_bytes()
    file_sha = sha256_bytes(graph_bytes)
    require_sha(file_sha, expect_sha, "graph file")
    try:
        graph = json.loads(graph_bytes.decode("utf-8-sig"))
    except ValueError as error:
        raise Refused(f"graph is not JSON: {error}") from error
    classes = check_graph(client, graph, policy)
    result = dispatch(client, settings, graph=graph, receipt_dir=Path(receipt_dir),
                      identity={"kind": "comfy-submit", "graph_path": str(Path(graph_path).resolve()),
                                "graph_file_sha256": file_sha, "classes": classes}, strict_idle=strict_idle)
    return {"prompt_id": result.prompt_id, "client_id": result.client_id,
            "graph_sha256": result.graph_sha256, "submitted_receipt_error": result.submitted_receipt_error}


def _prompt_target(receipt_dir: Path) -> tuple[dict, dict]:
    intent_path = receipt_dir / INTENT_FILE
    if not intent_path.is_file():
        raise Refused(f"no {INTENT_FILE} in {receipt_dir}")
    intent = read_json(intent_path)
    for name in (SUBMITTED_FILE, RECONCILED_FILE):
        if (receipt_dir / name).is_file():
            data = read_json(receipt_dir / name)
            if data.get("prompt_id"):
                return intent, data
    raise Refused(f"no {SUBMITTED_FILE}/{RECONCILED_FILE} with a prompt_id in {receipt_dir}; "
                  "run reconcile (never resubmit)")


def cmd_wait(client: ComfyClient, settings: ComfySettings, *, receipt_dir: Path,
             timeout_seconds: float) -> dict[str, Any]:
    """Poll history for the receipt's prompt; bind it to the intent graph + client; write job.json."""
    receipt_dir = Path(receipt_dir)
    intent, target = _prompt_target(receipt_dir)
    prompt_id = target["prompt_id"]
    job_path = receipt_dir / JOB_FILE
    base = {"schema": JOB_SCHEMA, "prompt_id": prompt_id, "client_id": intent["client_id"],
            "graph_sha256": intent["graph_sha256"], "at": time.time()}
    try:
        history = wait_for_history(client, prompt_id, timeout_seconds=timeout_seconds,
                                   poll_seconds=settings.poll_seconds)
    except Exception as error:
        write_json_atomic(job_path, {**base, "status": "WAIT_TIMEOUT", "error": str(error),
                                     "next_action": "wait again or reconcile; never resubmit"}, mode="ascii")
        raise
    try:
        entry = select_bound_entry({prompt_id: history}, prompt_id=prompt_id, client_id=intent["client_id"],
                                   graph_sha256=intent["graph_sha256"], label="history")
    except Failed as error:
        write_json_atomic(job_path, {**base, "status": "FAILED", "error": str(error),
                                     "comfy_status": history.get("status")}, mode="ascii")
        raise
    outputs = collect_outputs(entry, settings.output_dir)
    write_json_atomic(job_path, {**base, "status": "COMPLETED", "comfy_status": entry.get("status"),
                                 "outputs": outputs}, mode="ascii")
    return {"prompt_id": prompt_id, "status": "COMPLETED", "outputs": len(outputs)}


def cmd_reconcile(client: ComfyClient, settings: ComfySettings, *, receipt_dir: Path) -> tuple[dict, int]:
    """Locate the intent's prompt by exact graph + client_id; never POSTs.  Exit 2 if none/ambiguous."""
    receipt_dir = Path(receipt_dir)
    intent_path = receipt_dir / INTENT_FILE
    if not intent_path.is_file():
        raise Refused(f"no {INTENT_FILE} in {receipt_dir}; nothing to reconcile")
    intent = read_json(intent_path)
    client_id, graph_sha = intent.get("client_id"), intent.get("graph_sha256")
    if not isinstance(client_id, str) or not client_id or not isinstance(graph_sha, str):
        raise Uncertain(f"{intent_path} has no usable client_id/graph_sha256; do not resubmit, "
                        "inspect ComfyUI queue/history manually")
    found = reconcile_intent(client, graph_sha256=graph_sha, client_id=client_id)
    report: dict[str, Any] = {"client_id": client_id, "status": found.status,
                              "prompt_id": found.prompt_id, "location": found.location}
    if found.status != "matched":
        report["next_action"] = ("no trace of this graph/client in queue/history; outcome indeterminate - "
                                 "human review before any new intent; never resubmit")
        return report, 2
    record_reconciled(receipt_dir, result=found, client_id=client_id, graph_sha256=graph_sha)
    report["next_action"] = "run wait (it reads reconciled.json)"
    return report, 0
