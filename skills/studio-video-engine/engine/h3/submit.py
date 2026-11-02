"""``jjv h3 submit``: guarded, idempotent dispatch of prepared H3 graphs (one GPU job at a time).

Order, every refusal before anything is sent:
``--approve-gpu`` -> re-verify prepared shots (hashes + WAV rule) -> node-class policy -> readiness
(container running, queue idle, no lock) -> stage hash-verified inputs -> ``engine.comfy.dispatch`` (lock, idle
queue, history twin check, O_EXCL intent, POST, container identity recorded) -> bounded wait.

Idempotence: a shot whose ``comfy/`` receipt dir already holds post evidence is never POSTed again (reported as
``ALREADY_SUBMITTED``; an intent without a submitted receipt is Uncertain: reconcile).  A twin of the graph in
ComfyUI history is refused by ``dispatch`` itself.

Khoá GPU (CR-VENG-RULES, 2026-10-31): ngoài khoá submit mà ``dispatch`` chỉ giữ lúc POST, ``submit`` giữ khoá
EXECUTOR máy (``ComfySettings.executor_lock_path``, cùng file ``seedvr2 execute`` giữ cả run) suốt POST + wait,
nên một H3 submit không chen được vào giữa hai chunk SeedVR2 và ngược lại.
"""

from __future__ import annotations

import json
import os
import socket
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from ..comfy import commands
from ..comfy.client import ComfyClient
from ..comfy.dispatch import INTENT_FILE, SUBMITTED_FILE, dispatch, post_evidence
from ..comfy.docker_probe import DockerProbe
from ..comfy.guards import ClassPolicy, check_graph
from ..comfy.settings import ComfySettings
from ..comfy.staging import stage_input
from ..comfy import lost
from ..core.errors import Refused, Uncertain
from ..core.io import read_json
from ..core.runlock import run_pid_lock
from ..layout.context import Context
from .prepare import load_prepared

COMFY_DIR = "comfy"
CLIENT_PREFIX = "jjv-h3-"


def container_instance(probe: Any, container: str) -> Callable[[], dict]:
    """The container's StartedAt before the POST: the identity a later lost-prompt proof compares against."""
    def read() -> dict:
        state = probe.state(container)
        if state is None:
            return {"container": container, "available": False}
        return {"container": container, "available": True, "started_at_text": state.started_at_text,
                "started_at": state.started_at, "running": state.running, "restart_count": state.restart_count}
    return read


def _existing(folder: Path) -> dict | None:
    """Summary of an earlier submit of this shot, or None when nothing was ever attempted."""
    receipts = folder / COMFY_DIR
    found = post_evidence(receipts)
    if not found:
        return None
    if (receipts / SUBMITTED_FILE).is_file():
        return {"status": "ALREADY_SUBMITTED", "prompt_id": read_json(receipts / SUBMITTED_FILE).get("prompt_id"),
                "evidence": found}
    raise Uncertain(f"{receipts} holds {found} but no {SUBMITTED_FILE}: the POST outcome is unknown; "
                    "run 'jjv comfy reconcile', never resubmit", evidence={"evidence": found})


def _recover_lost(folder: Path, receipt: dict, graph: dict, settings: ComfySettings,
                  client: ComfyClient, probe: Any) -> None:
    """Archive a proven lost H3 attempt so guarded dispatch may use a fresh receipt dir."""
    receipts = folder / COMFY_DIR
    submitted_path = receipts / SUBMITTED_FILE
    if not submitted_path.is_file() or (receipts / "job.json").is_file() and read_json(receipts / "job.json").get("status") == "COMPLETED":
        return
    intent_path = receipts / INTENT_FILE
    if not intent_path.is_file():
        raise Uncertain(f"{receipts}: submitted receipt has no dispatch intent; no automatic resubmit")
    submitted, intent = read_json(submitted_path), read_json(intent_path)
    prompt_id = submitted.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id or intent.get("graph_sha256") != receipt["graph_sha256"]:
        raise Uncertain(f"{receipts}: prompt id or graph identity is invalid; no automatic resubmit")
    prefixes = sorted({value for node in graph.values() if isinstance(node, dict)
                       for key, value in (node.get("inputs") or {}).items()
                       if key == "filename_prefix" and isinstance(value, str) and value})
    if not prefixes:
        raise Uncertain(f"{receipts}: no output prefix can be checked; no automatic resubmit")
    result = lost.classify_lost(client=client, probe=probe, container=settings.container,
                                dispatch_time=float(intent.get("created_at") or 0), output_dir=settings.output_dir,
                                output_prefix=prefixes[0], dispatch_instance=intent.get("container_instance"),
                                prompt_id=prompt_id, recheck_seconds=settings.lost_recheck_seconds)
    if result.verdict == lost.NOT_LOST:
        return
    if result.verdict != lost.LOST:
        raise Uncertain(f"{receipts}: old prompt could not be proven lost: {result.reasons}")
    for prefix in prefixes[1:]:
        if lost.outputs_with_prefix(settings.output_dir, prefix):
            raise Uncertain(f"{receipts}: an output exists for {prefix}; no automatic resubmit")
    ledger = folder.parent / lost.LEDGER_FILE
    used = lost.lost_retries_used(receipts, ledger, receipt["shot"], "h3")
    if used >= settings.max_lost_retries:
        raise Uncertain(f"{receipts}: lost-prompt retry budget exhausted ({used}/{settings.max_lost_retries})")
    record = lost.lost_receipt(result, identity={"shot": receipt["shot"], "prompt_id": prompt_id,
                                                 "graph_sha256": receipt["graph_sha256"]},
                               retries_before=used, max_lost_retries=settings.max_lost_retries,
                               decision="resubmit", clock=time.time)
    lost.archive_lost_attempt(receipts, record, time.time, ledger=ledger, shot_id=receipt["shot"], chunk="h3")


def _submit_one(ctx: Context, settings: ComfySettings, client: ComfyClient, folder: Path, receipt: dict, graph: dict, *,
                probe: Any, ps: commands.DockerPs, wait: bool, wait_timeout: float, done: list[str]) -> dict[str, Any]:
    report, ready = commands.cmd_check(client, settings, ps=ps)
    if not ready:
        raise Refused(f"ComfyUI is not ready for {receipt['shot']}: {report['problems']}; nothing was sent "
                      f"for this shot (already submitted: {done})")
    for item in [receipt["anchor"], receipt["wav"], *receipt["faces"], *(receipt.get("refs") or [])]:
        stage_input(Path(item["path"]), settings.input_dir, item["input_name"], item["sha256"])  # pack refs: flat staged names
    identity = {"kind": "h3-shot", "stage": "h3", "shot": receipt["shot"], "episode_id": ctx.episode_id,
                "preparation_graph_sha256": receipt["graph_sha256"]}
    result = dispatch(client, settings, graph=graph, receipt_dir=folder / COMFY_DIR, identity=identity,
                      client_prefix=CLIENT_PREFIX, container_instance=container_instance(probe, settings.container))
    row: dict[str, Any] = {"shot": receipt["shot"], "status": "SUBMITTED", "prompt_id": result.prompt_id,
                           "graph_sha256": result.graph_sha256}
    if wait:
        row.update(commands.cmd_wait(client, settings, receipt_dir=folder / COMFY_DIR, timeout_seconds=wait_timeout))
        row["status"] = "COMPLETED"
    return row


def require_caller_holds_lock(path: Path) -> dict[str, Any]:
    """``hold_executor_lock=False`` chỉ hợp lệ khi NGƯỜI GỌI đang giữ EXECUTOR-RUN-LOCK: thân khoá phải cùng host và
    ``pid`` là tiến trình này hoặc tiến trình cha (một run bọc submit).  Khoá vắng, không đọc được hay của pid khác ⇒
    Refused trước khi gửi (critic CR-VENG 3.5: trước đây cờ này bỏ qua khoá mà không kiểm)."""
    me, parent, here = os.getpid(), os.getppid(), socket.gethostname()
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"EXECUTOR_LOCK_NOT_HELD: hold_executor_lock=False but {path} does not exist; the caller must hold "
                      "the machine executor lock (run_pid_lock) around submit; nothing was sent") from None
    except (OSError, ValueError) as error:
        raise Refused(f"EXECUTOR_LOCK_NOT_HELD: {path} is unreadable ({error!r}); nothing was sent") from error
    pid = body.get("pid") if isinstance(body, dict) else None
    host = body.get("host") if isinstance(body, dict) else None
    if host != here or pid not in (me, parent):
        raise Refused(f"EXECUTOR_LOCK_NOT_HELD: {path} is held by pid {pid} on host {host!r}, not by this process "
                      f"({me}) or its parent ({parent}) on {here!r}; nothing was sent")
    return body


def submit(ctx: Context, out: Path, shots: list[str] | None, settings: ComfySettings, client: ComfyClient, *,
           approve_gpu: bool, probe: Any | None = None, ps: commands.DockerPs = commands.docker_ps,
           wait_timeout: float = 3600.0, wait: bool = True, hold_executor_lock: bool = True,
           recover_lost: bool = False) -> dict[str, Any]:
    """``hold_executor_lock``: giữ khoá EXECUTOR máy (``settings.executor_lock_path``, cùng khoá mà
    ``seedvr2 execute`` giữ cả run) suốt POST + wait của mọi shot, nên không GPU job nào chen vào giữa.  Chỉ
    ``False`` khi NGƯỜI GỌI đã giữ đúng khoá đó (``jjv video render``); ``run_pid_lock`` không re-entrant."""
    if not approve_gpu:
        raise Refused("h3 submit uses the GPU: pass --approve-gpu (explicit user approval for THIS run); "
                      "nothing was sent")
    prepared = load_prepared(ctx, out, shots=shots)
    probe = probe if probe is not None else DockerProbe()
    if recover_lost:
        if hold_executor_lock:
            raise Refused("recover_lost requires the caller to hold the machine executor lock")
        require_caller_holds_lock(settings.executor_lock_path)
        for folder, receipt, graph in prepared:
            _recover_lost(folder, receipt, graph, settings, client, probe)
    policy = ClassPolicy.from_domain(ctx.domain)
    cache: dict[str, str | None] = {}
    todo = []
    for folder, receipt, graph in prepared:
        if _existing(folder) is None:
            check_graph(client, graph, policy, cache=cache)
            todo.append((folder, receipt, graph))
    rows = [{"shot": r["shot"], **(_existing(f) or {})} for f, r, _ in prepared if _existing(f)]
    if todo and not hold_executor_lock:
        require_caller_holds_lock(settings.executor_lock_path)
    lock = (run_pid_lock(settings.executor_lock_path, report_dir=Path(out), scope="machine",
                         extra={"stage": "h3", "out": str(Path(out).resolve()), "shots": [r["shot"] for _, r, _ in todo]})
            if todo and hold_executor_lock else nullcontext())
    with lock:
        for folder, receipt, graph in todo:  # one at a time: dispatch demands an idle queue
            rows.append(_submit_one(ctx, settings, client, folder, receipt, graph, probe=probe, ps=ps, wait=wait,
                                    wait_timeout=wait_timeout, done=[r["shot"] for r in rows]))
    return {"episode_id": ctx.episode_id, "submitted": [r for r in rows if r["status"] != "ALREADY_SUBMITTED"],
            "already_submitted": [r for r in rows if r["status"] == "ALREADY_SUBMITTED"]}


__all__ = ["submit", "container_instance", "INTENT_FILE"]
