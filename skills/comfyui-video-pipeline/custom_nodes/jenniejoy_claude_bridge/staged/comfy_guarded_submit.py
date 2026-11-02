#!/usr/bin/env python3
"""Guarded submit / wait / reconcile helper for the local Docker ComfyUI.

Stdlib only (Python 3.12+). Any agent (Claude, Gemini, DeepSeek) can use it so
that every submission to ``http://127.0.0.1:8188`` goes through the same
dispatch discipline as the episode executors:

    sha check -> partner-node check -> shared O_EXCL lock -> empty queue
    -> dispatch-intent.json -> POST /prompt -> submitted.json

Sub-commands: ``check`` (read-only), ``submit``, ``wait``, ``reconcile``
(read-only). Only ``submit`` ever POSTs, and only after every guard passed.

Exit codes: 0 ok, 1 refused / not ready (nothing queued), 2 usage, I/O or ANY unexpected error,
3 wait timeout (job NOT resubmitted), 4 ComfyUI reported a failed execution.

Lock protocol: same path and O_EXCL protocol as ``existence_lock`` in
``04-milk-and-mom/tools/upscale_seedvr2_chunked.py`` (``os.open(path,
O_CREAT|O_EXCL|O_WRONLY)`` on ``<episode04>/technical/.comfyui-image-submit.lock``
with a one-line ``pid=.. acquired_unix=.. token=..`` body); release is
token-checked (the executor unlinks unconditionally). Receipt-dir exclusivity
is enforced INSIDE the lock by creating ``dispatch-intent.json`` with O_EXCL.
Classes ``ClaudeNode`` and ``JJClaudeBridge`` are hard refusals that ``--partner-ok``
cannot override (the latter is the authoring-only Claude bridge custom node).

Lock release choice: ``submit`` keeps the lock until the new prompt has left
``/queue`` (running -> history) or an error occurs, so no second dispatcher can
slip in while the first prompt is still being admitted. Safety does NOT depend
on that hold: every dispatcher requires an empty queue under the lock, which is
why the lock is also released (not left stale) when ``--hold-timeout`` expires
while the prompt is still running; ``wait`` then takes over. A stale lock is
never removed automatically, and we only unlink a lock file that still carries
our own token.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

DEFAULT_BASE_URL = "http://127.0.0.1:8188"
CONTAINER_NAME = "Comfyui-Studio"
EPISODE04 = Path(
    r"J:\1.JennieHomeSchool\03 Voice\production-local"
    r"\JennieJoyKids-Story\04-milk-and-mom"
)
DEFAULT_LOCK_PATH = EPISODE04 / "technical" / ".comfyui-image-submit.lock"
DEFAULT_OUTPUT_DIR = Path(
    r"J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\output"
)
DEFAULT_LOCK_TIMEOUT = 30.0
DEFAULT_POLL_SECONDS = 2.0
HTTP_TIMEOUT = 30.0

# Class names that are always partner/cloud nodes, even if object_info lies.
PARTNER_DENY_LIST = frozenset({"claudenode", "jjclaudebridge"})

EXIT_OK, EXIT_REFUSED, EXIT_ERROR, EXIT_TIMEOUT, EXIT_FAILED = 0, 1, 2, 3, 4


class Refused(Exception):
    """A guard refused the operation; nothing was sent to ComfyUI."""


class BadReceipt(Exception):
    """A receipt file is unreadable or malformed (exit 2, never 'refused')."""


@dataclass(frozen=True)
class Settings:
    base_url: str = DEFAULT_BASE_URL
    lock_path: Path = DEFAULT_LOCK_PATH
    output_dir: Path = DEFAULT_OUTPUT_DIR
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT
    poll_seconds: float = DEFAULT_POLL_SECONDS


# --------------------------------------------------------------------- utils
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    """Atomic JSON write (tmp + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def log(message: str) -> None:
    print(message, file=sys.stderr)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def http_json(
    settings: Settings, route: str, payload: object | None = None
) -> Any:
    """GET (payload None) or POST JSON. Only ``submit`` passes a payload."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        settings.base_url + route,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="GET" if data is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body.strip() else {}


# ---------------------------------------------------------------------- lock
def _lock_token(body: str) -> str | None:
    match = re.search(r"token=([0-9a-f]+)", body)
    return match.group(1) if match else None


@contextmanager
def existence_lock(path: Path, timeout_seconds: float) -> Iterator[None]:
    """Shared episode-wide submit sentinel (same protocol as the executor)."""
    if timeout_seconds < 0:
        raise ValueError("lock timeout cannot be negative")
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            if time.monotonic() >= deadline:
                raise Refused(
                    f"shared ComfyUI submit lock is held: {path}. The existing "
                    "sentinel was preserved; reconcile ComfyUI queue/history "
                    "before any manual removal."
                ) from error
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    token = uuid.uuid4().hex
    try:
        os.write(
            descriptor,
            f"pid={os.getpid()} acquired_unix={time.time():.6f} token={token}\n".encode(
                "ascii"
            ),
        )
    except BaseException:
        # We created this file with O_EXCL a moment ago, so it is ours to remove.
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            if _lock_token(path.read_text(encoding="ascii")) == token:
                path.unlink(missing_ok=True)
            else:
                log(f"WARNING: lock {path} no longer carries our token; "
                    "left in place (not ours to remove)")
        except OSError as error:
            log(f"WARNING: could not release lock {path}: {error!r}; "
                "it may be stale - reconcile before removing it manually")


# ------------------------------------------------------------------ guards
def graph_class_types(graph: object) -> list[str]:
    """Validate API-format graph shape and return its distinct class_types."""
    if not isinstance(graph, dict) or not graph:
        raise Refused("graph is not a non-empty API-format JSON object")
    if "nodes" in graph and "links" in graph:
        raise Refused("graph looks like a UI export; API-format JSON is required")
    classes: set[str] = set()
    for node_id, node in graph.items():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str):
            raise Refused(f"node {node_id!r} has no class_type; not API format")
        classes.add(node["class_type"])
    return sorted(classes)


def partner_reasons(settings: Settings, classes: Sequence[str]) -> list[str]:
    """Return one reason per class that is a partner/API node or unverifiable."""
    reasons: list[str] = []
    for name in classes:
        if name.lower() in PARTNER_DENY_LIST:
            reasons.append(f"{name}: on the partner deny list")
            continue
        try:
            info = http_json(settings, "/object_info/" + urllib.parse.quote(name))
        except urllib.error.URLError as error:
            raise Refused(f"cannot verify node class {name} via /object_info: {error}")
        entry = info.get(name) if isinstance(info, dict) else None
        if not isinstance(entry, dict):
            reasons.append(f"{name}: unknown to this ComfyUI (cannot verify)")
            continue
        module = str(entry.get("python_module", ""))
        category = str(entry.get("category", ""))
        if (
            entry.get("api_node")
            or "comfy_api_nodes" in module
            or category.lower().startswith("api node")
        ):
            reasons.append(
                f"{name}: partner/API node (module={module!r}, category={category!r})"
            )
    return reasons


def queue_counts(queue: dict) -> tuple[int, int]:
    return len(queue.get("queue_running") or []), len(queue.get("queue_pending") or [])


def require_idle_queue(settings: Settings) -> None:
    running, pending = queue_counts(http_json(settings, "/queue"))
    if running or pending:
        raise Refused(f"ComfyUI queue is busy (running={running}, pending={pending})")


def queue_entry_ids(queue: dict) -> set[str]:
    ids: set[str] = set()
    for key in ("queue_running", "queue_pending"):
        for item in queue.get(key) or []:
            if isinstance(item, (list, tuple)) and len(item) > 1:
                ids.add(str(item[1]))
    return ids


# --------------------------------------------------------------------- check
def run_docker_ps() -> str:
    """Overridable in tests. Returns ``name|state|status`` lines."""
    completed = subprocess.run(
        [
            "docker", "ps", "-a", "--filter", f"name={CONTAINER_NAME}",
            "--format", "{{.Names}}|{{.State}}|{{.Status}}",
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "docker ps failed")
    return completed.stdout


def cmd_check(settings: Settings, args: argparse.Namespace) -> int:
    report: dict[str, Any] = {"time": now_iso(), "base_url": settings.base_url}
    problems: list[str] = []
    try:
        lines = [x for x in run_docker_ps().splitlines() if x.strip()]
        rows = [x.split("|", 2) for x in lines]
        mine = [r for r in rows if r[0] == CONTAINER_NAME]
        if not mine:
            problems.append(f"container {CONTAINER_NAME} not found (docker ps -a)")
        else:
            _, state, status = (mine[0] + ["", ""])[:3]
            report["container"] = {"state": state, "status": status}
            if state != "running":
                problems.append(f"container {CONTAINER_NAME} is {state!r} ({status})")
            elif "unhealthy" in status:
                problems.append(f"container {CONTAINER_NAME} is unhealthy ({status})")
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        problems.append(f"docker unavailable: {error}")
    try:
        running, pending = queue_counts(http_json(settings, "/queue"))
        report["queue"] = {"running": running, "pending": pending}
        if running or pending:
            problems.append(f"queue busy (running={running}, pending={pending})")
    except (urllib.error.URLError, OSError, ValueError) as error:
        problems.append(f"GET /queue failed: {error}")
    try:
        stats = http_json(settings, "/system_stats")
        devices = stats.get("devices") or []
        report["vram"] = [
            {
                "name": d.get("name"),
                "vram_free_mib": round(d.get("vram_free", 0) / 1048576),
                "vram_total_mib": round(d.get("vram_total", 0) / 1048576),
            }
            for d in devices
        ]
        if not devices:
            problems.append("GET /system_stats returned no devices")
        elif args.min_vram_free_mib and any(
            v["vram_free_mib"] < args.min_vram_free_mib for v in report["vram"]
        ):
            problems.append(f"free VRAM below {args.min_vram_free_mib} MiB")
    except (urllib.error.URLError, OSError, ValueError) as error:
        problems.append(f"GET /system_stats failed: {error}")
    lock = settings.lock_path
    report["lock"] = {"path": str(lock), "exists": lock.exists()}
    if lock.exists():
        try:
            report["lock"]["content"] = lock.read_text(encoding="ascii").strip()
        except OSError as error:
            report["lock"]["content_error"] = repr(error)
        problems.append(f"shared submit lock file exists ({lock}); submit would refuse")
    report["ready"] = not problems
    report["problems"] = problems
    print(json.dumps(report, indent=2))
    return EXIT_OK if not problems else EXIT_REFUSED


# -------------------------------------------------------------------- submit
def hard_denied(classes: Sequence[str]) -> list[str]:
    return [c for c in classes if c.lower() in PARTNER_DENY_LIST]


def create_intent_exclusive(path: Path, intent: dict[str, Any]) -> None:
    """Create dispatch-intent.json with O_EXCL; FileExistsError means the receipt
    dir was already used (possibly by a racing submit) and must not be overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(intent, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise Refused(
            f"{path} already exists; this receipt dir was used. Run "
            "`reconcile`/`wait`; never resubmit into the same receipt dir."
        ) from error
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)


def hold_until_left_queue(
    settings: Settings, prompt_id: str, hold_timeout: float
) -> dict[str, Any]:
    """Hold phase AFTER a successful POST. Never raises: errors are reported in
    the result so a monitoring failure cannot masquerade as a pre-POST error."""
    result: dict[str, Any] = {"hold_timeout": False}
    deadline = time.monotonic() + hold_timeout
    while True:
        try:
            if prompt_id not in queue_entry_ids(http_json(settings, "/queue")):
                return result
        except Exception as error:  # incl. http.client.HTTPException (IncompleteRead)
            result["hold_monitor_error"] = repr(error)
            log(f"WARNING: prompt {prompt_id} WAS submitted, but monitoring /queue "
                f"failed ({error!r}); releasing lock, use `wait`")
            return result
        if time.monotonic() >= deadline:
            result["hold_timeout"] = True
            log("hold-timeout reached; lock released, prompt still queued/running. "
                "Use `wait`.")
            return result
        time.sleep(settings.poll_seconds)


def cmd_submit(settings: Settings, args: argparse.Namespace) -> int:
    graph_path = Path(args.graph)
    receipt_dir = Path(args.receipt_dir)
    graph_bytes = graph_path.read_bytes()
    graph_sha = hashlib.sha256(graph_bytes).hexdigest()
    if args.expect_sha and args.expect_sha.lower() != graph_sha:
        raise Refused(
            f"graph sha256 mismatch: expected {args.expect_sha.lower()}, got {graph_sha}"
        )
    graph = json.loads(graph_bytes.decode("utf-8"))
    classes = graph_class_types(graph)
    denied = hard_denied(classes)
    if denied:
        raise Refused(
            f"node class(es) {', '.join(denied)} are never allowed in a render graph "
            "(cloud/chat call, non-deterministic, breaks hash-bound graphs; JJClaudeBridge "
            "is authoring-only); "
            "--partner-ok does not override this"
        )
    reasons = partner_reasons(settings, classes)
    unknown = [r for r in reasons if "unknown to this ComfyUI" in r]
    partner = [r for r in reasons if r not in unknown]
    if unknown:
        raise Refused("unverifiable node classes: " + "; ".join(unknown))
    if partner and not args.partner_ok:
        raise Refused(
            "graph contains partner/API nodes (pass --partner-ok only with explicit "
            "user spend consent): " + "; ".join(partner)
        )
    intent_path = receipt_dir / "dispatch-intent.json"
    if intent_path.exists():  # fast path only; the authoritative check is O_EXCL below
        raise Refused(
            f"{intent_path} already exists; this receipt dir was used. Run "
            "`reconcile`/`wait`; never resubmit into the same receipt dir."
        )
    with existence_lock(settings.lock_path, settings.lock_timeout):
        require_idle_queue(settings)
        client_id = f"guarded-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        create_intent_exclusive(intent_path, {
            "schema": "comfy-guarded-submit/intent-v1",
            "graph_path": str(graph_path.resolve()),
            "graph_sha256": graph_sha,
            "client_id": client_id,
            "base_url": settings.base_url,
            "partner_ok": bool(args.partner_ok),
            "partner_classes": partner,
            "created_at": now_iso(),
            "created_unix": time.time(),
            "pid": os.getpid(),
        })
        try:
            result = http_json(
                settings, "/prompt", {"prompt": graph, "client_id": client_id}
            )
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            write_json(receipt_dir / "submit-rejected.json", {
                "status": "REJECTED_BY_COMFY", "http_status": error.code,
                "body": body, "client_id": client_id, "at": now_iso(),
            })
            log(f"ComfyUI rejected the prompt (HTTP {error.code}): {body[:500]}")
            return EXIT_REFUSED
        except Exception as error:  # outcome unknown: keep intent, never retry
            write_json(receipt_dir / "submit-unknown.json", {
                "status": "DISPATCH_STATUS_UNKNOWN", "error": repr(error),
                "client_id": client_id, "at": now_iso(),
                "next_action": "run reconcile; do not resubmit",
            })
            log(f"dispatch outcome unknown ({error!r}); run reconcile")
            return EXIT_ERROR
        prompt_id = result.get("prompt_id") if isinstance(result, dict) else None
        if not prompt_id:
            write_json(receipt_dir / "submit-unknown.json", {
                "status": "DISPATCH_STATUS_UNKNOWN", "response": result,
                "client_id": client_id, "at": now_iso(),
                "next_action": "run reconcile; do not resubmit",
            })
            log("ComfyUI returned no prompt_id; run reconcile")
            return EXIT_ERROR
        # ---- from here the prompt IS queued: never return a pre-POST error code.
        summary: dict[str, Any] = {"prompt_id": prompt_id, "client_id": client_id}
        log(f"submitted prompt_id={prompt_id} client_id={client_id}")
        try:
            write_json(receipt_dir / "submitted.json", {
                "schema": "comfy-guarded-submit/submitted-v1",
                "prompt_id": prompt_id, "client_id": client_id,
                "number": result.get("number"),
                "node_errors": result.get("node_errors", {}),
                "graph_sha256": graph_sha, "submitted_at": now_iso(),
            })
        except OSError as error:
            summary["submitted_receipt_error"] = repr(error)
            log(f"WARNING: submitted.json could not be written ({error!r}); "
                "prompt_id above is the only record; use `reconcile`")
        summary.update(hold_until_left_queue(settings, prompt_id, args.hold_timeout))
        print(json.dumps(summary))
    return EXIT_OK


# ---------------------------------------------------------------------- wait
def collect_outputs(history: dict, output_dir: Path) -> list[dict[str, Any]]:
    root = output_dir.resolve()
    found: list[dict[str, Any]] = []
    for node_id, node_out in (history.get("outputs") or {}).items():
        if not isinstance(node_out, dict):
            continue
        for kind, entries in node_out.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not (isinstance(entry, dict) and "filename" in entry):
                    continue
                record: dict[str, Any] = {
                    "node_id": node_id, "kind": kind,
                    "filename": entry["filename"],
                    "subfolder": entry.get("subfolder", ""),
                    "type": entry.get("type", "output"),
                    "path": None, "exists": False, "sha256": None, "bytes": None,
                }
                if record["type"] == "output":
                    path = (root / record["subfolder"] / record["filename"]).resolve()
                    if root not in path.parents:
                        record["error"] = "path escapes output folder"
                    else:
                        record["path"] = str(path)
                        if path.is_file():
                            record.update(exists=True, sha256=sha256_file(path),
                                          bytes=path.stat().st_size)
                found.append(record)
    return found


def _wait_target(receipt_dir: Path) -> dict[str, Any]:
    for name in ("submitted.json", "reconciled.json"):
        if (receipt_dir / name).is_file():
            data = read_json(receipt_dir / name)
            if data.get("prompt_id"):
                return data
    raise Refused(f"no submitted.json/reconciled.json with prompt_id in {receipt_dir}; "
                  "run `reconcile` (never resubmit)")


def cmd_wait(settings: Settings, args: argparse.Namespace) -> int:
    receipt_dir = Path(args.receipt_dir)
    target = _wait_target(receipt_dir)
    prompt_id = str(target["prompt_id"])
    deadline = time.monotonic() + args.timeout
    history: dict | None = None
    errors: list[str] = []
    while True:
        try:
            history = http_json(settings, "/history/" + prompt_id).get(prompt_id)
        except Exception as error:  # incl. http.client.HTTPException (IncompleteRead)
            history = None
            errors.append(repr(error))
            if len(errors) <= 3 or len(errors) % 30 == 0:
                log(f"WARNING: GET /history/{prompt_id} failed "
                    f"({len(errors)} so far): {error!r}")
        if history or time.monotonic() >= deadline:
            break
        time.sleep(settings.poll_seconds)
    poll_errors = {"count": len(errors), "last": errors[-3:]}
    if not history:
        in_queue: bool | None
        queue_error: str | None = None
        try:
            in_queue = prompt_id in queue_entry_ids(http_json(settings, "/queue"))
        except Exception as error:
            in_queue, queue_error = None, repr(error)
            log(f"WARNING: GET /queue failed while closing wait: {error!r}")
        write_json(receipt_dir / "job.json", {
            "schema": "comfy-guarded-submit/job-v1", "prompt_id": prompt_id,
            "status": "WAIT_TIMEOUT", "prompt_in_queue": in_queue,
            "queue_error": queue_error, "poll_errors": poll_errors,
            "timeout_seconds": args.timeout, "at": now_iso(),
            "next_action": "run wait again or reconcile; never resubmit",
        })
        log(f"timeout after {args.timeout}s; prompt_in_queue={in_queue}")
        return EXIT_TIMEOUT
    try:
        status = (history.get("status") or {}).get("status_str", "unknown")
        outputs = collect_outputs(history, settings.output_dir)
        write_json(receipt_dir / "job.json", {
            "schema": "comfy-guarded-submit/job-v1", "prompt_id": prompt_id,
            "client_id": target.get("client_id"),
            "status": "COMPLETED" if status == "success" else "FAILED",
            "comfy_status": history.get("status"), "outputs": outputs,
            "poll_errors": poll_errors, "at": now_iso(),
        })
    except Exception as error:  # history exists: the job RAN; never look 'refused'
        log(f"ERROR: could not finalise job {prompt_id}: {error!r}")
        try:
            write_json(receipt_dir / "job.json", {
                "schema": "comfy-guarded-submit/job-v1", "prompt_id": prompt_id,
                "status": "WAIT_ERROR", "error": repr(error),
                "comfy_status": history.get("status")
                if isinstance(history, dict) else None,
                "poll_errors": poll_errors, "at": now_iso(),
                "next_action": "inspect /history/<prompt_id>; never resubmit",
            })
        except OSError as write_error:
            log(f"ERROR: job.json could not be written either: {write_error!r}")
        return EXIT_ERROR
    print(json.dumps({"prompt_id": prompt_id, "comfy_status": status,
                      "outputs": len(outputs)}))
    return EXIT_OK if status == "success" else EXIT_FAILED


# ----------------------------------------------------------------- reconcile
def _find_client(entries: Sequence[Any], client_id: str) -> str | None:
    for item in entries:
        if isinstance(item, (list, tuple)) and len(item) > 3:
            extra = item[3] if isinstance(item[3], dict) else {}
            if extra.get("client_id") == client_id:
                return str(item[1])
    return None


def cmd_reconcile(settings: Settings, args: argparse.Namespace) -> int:
    receipt_dir = Path(args.receipt_dir)
    intent_path = receipt_dir / "dispatch-intent.json"
    if not intent_path.is_file():
        raise Refused(f"no dispatch-intent.json in {receipt_dir}; nothing to reconcile")
    intent = read_json(intent_path)
    client_id = intent.get("client_id") if isinstance(intent, dict) else None
    if not isinstance(client_id, str) or not client_id:
        raise BadReceipt(
            f"{intent_path} has no usable string `client_id`; cannot reconcile "
            "(do not resubmit; inspect ComfyUI queue/history manually)"
        )
    report: dict[str, Any] = {"client_id": client_id, "at": now_iso(),
                              "has_submitted": (receipt_dir / "submitted.json").is_file(),
                              "has_job": (receipt_dir / "job.json").is_file()}
    queue = http_json(settings, "/queue")
    history = http_json(settings, "/history")
    location, prompt_id = "not_found", None
    for key in ("queue_running", "queue_pending"):
        prompt_id = _find_client(queue.get(key) or [], client_id)
        if prompt_id:
            location = key
            break
    if not prompt_id and isinstance(history, dict):
        for pid, entry in history.items():
            extra = (entry.get("prompt") or [None] * 4)[3] if isinstance(entry, dict) else None
            if isinstance(extra, dict) and extra.get("client_id") == client_id:
                location, prompt_id = "history", str(pid)
                break
    report.update(location=location, prompt_id=prompt_id)
    if prompt_id:
        write_json(receipt_dir / "reconciled.json", {
            "prompt_id": prompt_id, "client_id": client_id,
            "location": location, "at": now_iso()})
        report["next_action"] = "run `wait` (it reads reconciled.json)"
    else:
        report["next_action"] = ("no trace of this client_id in queue/history; "
                                 "outcome indeterminate - human review before any new intent")
    write_json(receipt_dir / "reconcile-report.json", report)
    print(json.dumps(report, indent=2))
    return EXIT_OK


# ----------------------------------------------------------------------- cli
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--lock-timeout", type=float, default=DEFAULT_LOCK_TIMEOUT)
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL_SECONDS)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="container, queue and VRAM readiness (read-only)")
    check.add_argument("--min-vram-free-mib", type=int, default=0)
    submit = sub.add_parser("submit", help="guarded POST /prompt")
    submit.add_argument("--graph", required=True)
    submit.add_argument("--receipt-dir", required=True)
    submit.add_argument("--expect-sha")
    submit.add_argument("--partner-ok", action="store_true")
    submit.add_argument("--hold-timeout", type=float, default=3600.0)
    wait = sub.add_parser("wait", help="poll /history, write job.json (never resubmits)")
    wait.add_argument("--receipt-dir", required=True)
    wait.add_argument("--timeout", type=float, default=3600.0)
    rec = sub.add_parser("reconcile", help="find an intent's prompt by client_id (never POSTs)")
    rec.add_argument("--receipt-dir", required=True)
    return parser


COMMANDS: dict[str, Callable[[Settings, argparse.Namespace], int]] = {
    "check": cmd_check, "submit": cmd_submit, "wait": cmd_wait,
    "reconcile": cmd_reconcile,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings(
        base_url=args.base_url.rstrip("/"), lock_path=args.lock_path,
        output_dir=args.output_dir, lock_timeout=args.lock_timeout,
        poll_seconds=args.poll,
    )
    try:
        return COMMANDS[args.command](settings, args)
    except Refused as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return EXIT_REFUSED
    except BadReceipt as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as error:  # incl. OSError, ValueError, URLError, HTTPException
        # Unexpected failures must never surface as EXIT_REFUSED (1): an agent could
        # read "refused" as "nothing was queued" and resubmit.
        print(f"ERROR: {error!r}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
