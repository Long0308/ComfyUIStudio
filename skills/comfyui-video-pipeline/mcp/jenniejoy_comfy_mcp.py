#!/usr/bin/env python3
"""Read-mostly MCP server for the JennieJoyKids/NEWTECONS ComfyUI engine.

The server speaks JSON-RPC 2.0 over newline-delimited stdio. It depends only on
the Python standard library. The single mutating tool delegates to the reviewed
``comfy_guarded_submit.py`` module so its O_EXCL lock, queue check, graph hash,
partner-node refusal and receipt semantics are not duplicated here.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import importlib.util
import inspect
import io
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, Iterable, Sequence

SERVER_NAME = "jenniejoy-comfy"
SERVER_VERSION = "1.1.0"
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = (
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_PATH_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _find_workspace_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".agents").is_dir() and (candidate / "production-local").is_dir():
            return candidate
    raise RuntimeError(f"cannot locate the workspace root above {start}")


ROOT = _find_workspace_root(Path(__file__).resolve().parent)
HELPER_PATH = (
    ROOT
    / ".agents"
    / "skills"
    / "comfyui-video-pipeline"
    / "scripts"
    / "comfy_guarded_submit.py"
)
DEFAULT_PLAN_PATH = (
    ROOT
    / "production-local"
    / "JennieJoyKids-Story"
    / "04-milk-and-mom"
    / "technical"
    / "seedvr2-production-v004"
    / "PRODUCTION-PLAN.json"
)


def _load_helper() -> ModuleType:
    if not HELPER_PATH.is_file():
        raise RuntimeError(f"reviewed guarded submit helper is missing: {HELPER_PATH}")
    module_name = "jenniejoy_comfy_guarded_submit"
    spec = importlib.util.spec_from_file_location(module_name, HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load guarded submit helper: {HELPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


GUARDED = _load_helper()

BRIDGE_CORE_PATH = (
    ROOT
    / ".agents"
    / "skills"
    / "comfyui-video-pipeline"
    / "custom_nodes"
    / "jenniejoy_claude_bridge"
    / "bridge_core.py"
)
DEFAULT_BRIDGE_SHARED = ROOT / "production-local" / "ComfyUI" / "user"
BRIDGE_WAIT_MAX_SECONDS = 100.0
_BRIDGE_CORE: ModuleType | None = None
# Only these tools prove a chat is serving the bridge; unrelated MCP calls must not look like a
# live chat (they would make mode=auto wait for an answer nobody is going to give).
BRIDGE_LIVENESS_TOOLS = frozenset({"bridge_wait", "bridge_pending", "bridge_answer"})


class ToolError(RuntimeError):
    """A tool request was refused or could not be completed."""


def _json_text(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_inside(raw_path: str | os.PathLike[str], label: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        resolved = candidate.resolve()
    except OSError as error:
        raise ToolError(f"{label} cannot be resolved: {raw_path!r}: {error}") from error
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ToolError(
            f"{label} is outside the allowed workspace root {ROOT}: {resolved}"
        )
    return resolved


def _base_url() -> str:
    raw_url = os.environ.get("JENNIEJOY_COMFY_URL", GUARDED.DEFAULT_BASE_URL).strip()
    if not raw_url:
        raise ToolError("ComfyUI URL must not be empty")
    try:
        parsed = urllib.parse.urlsplit(raw_url)
        port = parsed.port
    except ValueError as error:
        raise ToolError(f"invalid ComfyUI URL {raw_url!r}: {error}") from error
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ToolError("ComfyUI URL must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ToolError("ComfyUI URL must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ToolError("ComfyUI URL must not contain a path, query, or fragment")
    host = parsed.hostname.lower() if parsed.hostname else ""
    if host not in LOOPBACK_HOSTS:
        raise ToolError(
            "ComfyUI URL host must be loopback "
            "(127.0.0.1, localhost, or ::1)"
        )
    if port is not None and not 1 <= port <= 65535:
        raise ToolError("ComfyUI URL port is outside 1..65535")
    return raw_url.rstrip("/")


def _settings() -> Any:
    base_url = _base_url()
    lock_path = Path(GUARDED.DEFAULT_LOCK_PATH)
    return GUARDED.Settings(
        base_url=base_url,
        lock_path=lock_path,
        output_dir=GUARDED.DEFAULT_OUTPUT_DIR,
        lock_timeout=GUARDED.DEFAULT_LOCK_TIMEOUT,
        poll_seconds=GUARDED.DEFAULT_POLL_SECONDS,
    )


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise ToolError(f"{label} does not exist: {path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ToolError(f"{label} is not readable JSON: {path}: {error}") from error


def _queue_entries(queue: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("queue_running", "queue_pending"):
        entries: list[dict[str, Any]] = []
        for item in queue.get(key) or []:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            extra = item[3] if len(item) > 3 and isinstance(item[3], dict) else {}
            graph = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}
            entries.append(
                {
                    "number": item[0],
                    "prompt_id": item[1],
                    "client_id": extra.get("client_id"),
                    "node_count": len(graph),
                }
            )
        result[key] = entries
    return result


def _container_rows() -> tuple[list[dict[str, str]], str | None]:
    try:
        output = GUARDED.run_docker_ps()
    except Exception as error:
        return [], str(error)
    rows: list[dict[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 2)
        rows.append(
            {
                "name": parts[0] if parts else "",
                "state": parts[1] if len(parts) > 1 else "",
                "status": parts[2] if len(parts) > 2 else "",
            }
        )
    return rows, None


def comfy_status() -> dict[str, Any]:
    settings = _settings()
    report: dict[str, Any] = {
        "time": _now_iso(),
        "base_url": settings.base_url,
        "post_called": False,
    }
    problems: list[str] = []

    rows, docker_error = _container_rows()
    mine = [row for row in rows if row["name"] == GUARDED.CONTAINER_NAME]
    if docker_error:
        report["container"] = {"error": docker_error}
        problems.append(f"docker unavailable: {docker_error}")
    elif not mine:
        report["container"] = {"found": False}
        problems.append(f"container {GUARDED.CONTAINER_NAME} not found")
    else:
        container = mine[0]
        report["container"] = {"found": True, **container}
        if container["state"] != "running":
            problems.append(
                f"container is {container['state']!r} ({container['status']})"
            )
        elif "unhealthy" in container["status"].lower():
            problems.append(f"container is unhealthy ({container['status']})")

    try:
        queue = GUARDED.http_json(settings, "/queue")
        running, pending = GUARDED.queue_counts(queue)
        report["queue"] = {
            "running": running,
            "pending": pending,
            "entries": _queue_entries(queue),
        }
        if running or pending:
            problems.append(f"queue busy (running={running}, pending={pending})")
    except Exception as error:
        report["queue"] = {"error": str(error)}
        problems.append(f"GET /queue failed: {error}")

    try:
        stats = GUARDED.http_json(settings, "/system_stats")
        system = stats.get("system") if isinstance(stats, dict) else None
        devices = stats.get("devices") if isinstance(stats, dict) else None
        report["system"] = system if isinstance(system, dict) else {}
        report["argv"] = (
            report["system"].get("argv")
            if isinstance(report["system"], dict)
            else None
        )
        report["vram"] = []
        for device in devices or []:
            if not isinstance(device, dict):
                continue
            report["vram"].append(
                {
                    "name": device.get("name"),
                    "index": device.get("index"),
                    "type": device.get("type"),
                    "vram_free_mib": round((device.get("vram_free") or 0) / 1048576),
                    "vram_total_mib": round((device.get("vram_total") or 0) / 1048576),
                    "torch_vram_free_mib": round(
                        (device.get("torch_vram_free") or 0) / 1048576
                    ),
                    "torch_vram_total_mib": round(
                        (device.get("torch_vram_total") or 0) / 1048576
                    ),
                }
            )
        if not report["vram"]:
            problems.append("GET /system_stats returned no devices")
    except Exception as error:
        report["system"] = {"error": str(error)}
        report["vram"] = []
        problems.append(f"GET /system_stats failed: {error}")

    # The production submission lock belongs to the guarded helper. This read
    # tool never opens, stats, or probes that file while another job owns it.
    report["shared_submit_lock"] = {
        "checked": False,
        "owner": "comfy_guarded_submit.py",
        "reason": "status must not touch the production submission lock",
    }
    report["ready_for_submit"] = not problems
    report["problems"] = problems
    return report


def comfy_validate_graph(
    graph_path: str, expect_sha256: str | None = None
) -> dict[str, Any]:
    path = _validate_inside(graph_path, "graph_path")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ToolError(f"cannot read graph: {path}: {error}") from error
    graph_sha = GUARDED.sha256_file(path)
    expected = expect_sha256.lower() if isinstance(expect_sha256, str) else None
    report: dict[str, Any] = {
        "path": str(path),
        "sha256": graph_sha,
        "expect_sha256": expected,
        "sha256_match": expected is None or graph_sha == expected,
        "api_format": False,
        "known_classes": [],
        "unknown_classes": [],
        "partner_or_denied_classes": [],
        "class_details": [],
        "valid": False,
        "post_called": False,
    }
    try:
        graph = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as error:
        report["error"] = f"invalid JSON: {error}"
        return report

    settings = _settings()
    try:
        classes = GUARDED.graph_class_types(graph)
    except GUARDED.Refused as error:
        report["error"] = str(error)
        return report

    report["api_format"] = True
    try:
        reasons = GUARDED.partner_reasons(settings, classes)
    except Exception as error:
        raise ToolError(f"cannot validate node classes: {error}") from error

    denied = set(GUARDED.hard_denied(classes))
    for class_name in classes:
        class_reasons = [
            reason for reason in reasons if reason.startswith(class_name + ":")
        ]
        unknown = any("unknown to this ComfyUI" in reason for reason in class_reasons)
        hard_denied = class_name in denied
        banned = hard_denied or any(
            "partner/API node" in reason for reason in class_reasons
        )
        detail = {
            "class_type": class_name,
            "known": not unknown and not hard_denied,
            "partner_or_denied": banned,
            "reasons": class_reasons,
        }
        report["class_details"].append(detail)
        if not unknown and not hard_denied:
            report["known_classes"].append(class_name)
        else:
            if unknown:
                report["unknown_classes"].append(class_name)
        if banned:
            report["partner_or_denied_classes"].append(class_name)

    report["valid"] = bool(
        report["sha256_match"]
        and report["api_format"]
        and not report["unknown_classes"]
        and not report["partner_or_denied_classes"]
    )
    return report


def _file_token(path: Path) -> tuple[int, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size, stat.st_ino)


def comfy_submit_guarded(
    graph_path: str,
    receipt_dir: str,
    expect_sha256: str,
    confirm: str,
) -> dict[str, Any]:
    if confirm != "SUBMIT":
        raise ToolError(
            'submit refused: confirm must be exactly "SUBMIT"; nothing was queued'
        )
    if not isinstance(expect_sha256, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", expect_sha256
    ):
        raise ToolError(
            "submit refused: expect_sha256 must be one 64-character SHA-256"
        )

    graph = _validate_inside(graph_path, "graph_path")
    receipt = _validate_inside(receipt_dir, "receipt_dir")
    settings = _settings()
    rejected_path = receipt / "submit-rejected.json"
    rejected_before = _file_token(rejected_path)
    args = SimpleNamespace(
        graph=str(graph),
        receipt_dir=str(receipt),
        expect_sha=expect_sha256.lower(),
        partner_ok=False,
        # The stdio loop must not wait on GPU execution. The helper still owns
        # the O_EXCL lock through its idle-queue check, intent, and POST. A zero
        # post-submit hold returns as soon as submitted.json and prompt_id exist.
        hold_timeout=0.0,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = GUARDED.cmd_submit(settings, args)
    except GUARDED.Refused as error:
        raise ToolError(f"submit refused by guarded helper: {error}") from error
    except GUARDED.BadReceipt as error:
        raise ToolError(f"submit receipt error: {error}") from error
    except Exception as error:
        raise ToolError(f"submit error: {error!r}") from error

    stdout_text = stdout.getvalue().strip()
    stderr_text = stderr.getvalue().strip()
    parsed: Any = None
    if stdout_text:
        try:
            parsed = json.loads(stdout_text)
        except json.JSONDecodeError:
            parsed = None
    rejected_after = _file_token(rejected_path)
    post_rejected = rejected_after is not None and rejected_after != rejected_before
    if exit_code == GUARDED.EXIT_OK:
        post_called: bool | str = True
    elif exit_code == GUARDED.EXIT_ERROR:
        post_called = "unknown"
    elif post_rejected:
        post_called = True
    else:
        post_called = False
    result = {
        "exit_code": exit_code,
        "result": parsed if parsed is not None else stdout_text,
        "stderr": stderr_text or None,
        "partner_ok": False,
        "post_called": post_called,
        "hold_timeout_seconds": 0.0,
        "blocking_hold": False,
    }
    if exit_code != GUARDED.EXIT_OK:
        raise ToolError(_json_text(result))
    return result


def _receipt_prompt_id(value: dict[str, Any]) -> str | None:
    candidate = value.get("prompt_id")
    if isinstance(candidate, str) and candidate:
        return candidate
    response = value.get("prompt_response")
    if isinstance(response, dict):
        candidate = response.get("prompt_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def comfy_job(receipt_dir: str, include_history: bool = False) -> dict[str, Any]:
    directory = _validate_inside(receipt_dir, "receipt_dir")
    names = (
        "dispatch-intent.json",
        "submitted.json",
        "submit-unknown.json",
        "submit-rejected.json",
        "reconciled.json",
        "job.json",
    )
    receipts: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name in names:
        path = directory / name
        if not path.is_file():
            continue
        try:
            receipts[name] = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            errors[name] = str(error)

    prompt_id = None
    for name in ("job.json", "submitted.json", "reconciled.json", "dispatch-intent.json"):
        value = receipts.get(name)
        if isinstance(value, dict):
            prompt_id = _receipt_prompt_id(value)
            if prompt_id:
                break

    report: dict[str, Any] = {
        "receipt_dir": str(directory),
        "exists": directory.is_dir(),
        "prompt_id": prompt_id,
        "receipts": receipts,
        "errors": errors,
        "history": None,
        "post_called": False,
    }
    if include_history and prompt_id:
        settings = _settings()
        try:
            history = GUARDED.http_json(
                settings, "/history/" + urllib.parse.quote(prompt_id, safe="")
            )
            report["history"] = history
        except Exception as error:
            report["history_error"] = str(error)
    elif include_history:
        report["history_error"] = "no prompt_id is available in the receipts"
    return report


def comfy_reconcile(receipt_dir: str) -> dict[str, Any]:
    """Resolve an existing intent through GET /queue and GET /history only."""
    directory = _validate_inside(receipt_dir, "receipt_dir")
    settings = _settings()
    args = SimpleNamespace(receipt_dir=str(directory))
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = GUARDED.cmd_reconcile(settings, args)
    except GUARDED.Refused as error:
        raise ToolError(f"reconcile refused by guarded helper: {error}") from error
    except GUARDED.BadReceipt as error:
        raise ToolError(f"reconcile receipt error: {error}") from error
    except Exception as error:
        raise ToolError(f"reconcile error: {error!r}") from error

    stdout_text = stdout.getvalue().strip()
    stderr_text = stderr.getvalue().strip()
    parsed: Any = None
    if stdout_text:
        try:
            parsed = json.loads(stdout_text)
        except json.JSONDecodeError:
            parsed = None
    result = {
        "exit_code": exit_code,
        "result": parsed if parsed is not None else stdout_text,
        "stderr": stderr_text or None,
        "post_called": False,
    }
    if exit_code != GUARDED.EXIT_OK:
        raise ToolError(_json_text(result))
    return result


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _process_alive(pid: int) -> bool | None:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return None
        return True

    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(
        process_query_limited_information, False, wintypes.DWORD(pid)
    )
    if not handle:
        error_code = ctypes.get_last_error()
        if error_code == 87:  # ERROR_INVALID_PARAMETER: no such process
            return False
        # Access denied and unknown OS failures cannot prove the process is gone.
        return None
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _peak_from_samples(path: Path) -> tuple[int | None, int | None]:
    try:
        samples = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(samples, list):
        return None, None
    ram_values = [
        _as_int(item.get("container_memory_used_bytes"))
        for item in samples
        if isinstance(item, dict)
    ]
    vram_values = [
        _as_int(item.get("gpu_memory_used_mib"))
        for item in samples
        if isinstance(item, dict)
    ]
    ram = [value for value in ram_values if value is not None]
    vram = [value for value in vram_values if value is not None]
    return (max(ram) if ram else None, max(vram) if vram else None)


def _failure_summary(
    job: dict[str, Any], shot_id: str, chunk_name: str, path: Path
) -> dict[str, Any]:
    failure = job.get("failure") if isinstance(job.get("failure"), dict) else {}
    return {
        "shot_id": shot_id,
        "chunk_name": chunk_name,
        "prompt_id": job.get("prompt_id"),
        "stage": failure.get("stage"),
        "message": failure.get("message") or job.get("error"),
        "error_type": failure.get("error_type"),
        "uncertain": failure.get("uncertain"),
        "evidence": failure.get("evidence"),
        "job_path": str(path),
        "failed_at": failure.get("failed_at")
        or job.get("failed_at")
        or job.get("updated_at"),
    }


def seedvr2_run_status(plan_path: str | None = None) -> dict[str, Any]:
    plan_file = (
        _validate_inside(plan_path, "plan_path")
        if plan_path
        else DEFAULT_PLAN_PATH.resolve()
    )
    plan = _read_json(plan_file, "production plan")
    if not isinstance(plan, dict):
        raise ToolError(f"production plan is not a JSON object: {plan_file}")
    shots = plan.get("shots")
    if not isinstance(shots, list):
        raise ToolError(f"production plan has no shots list: {plan_file}")

    technical_root = plan_file.parent
    runs_root = technical_root / "runs"
    executor_lock_path = runs_root / ".executor.lock"
    expected: list[dict[str, Any]] = []
    invalid_entries: list[dict[str, Any]] = []
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        shot_id = shot.get("shot_id")
        chunks = shot.get("chunks")
        if not isinstance(shot_id, str) or not SAFE_PATH_COMPONENT.fullmatch(shot_id):
            invalid_entries.append(
                {
                    "shot_id": shot_id,
                    "chunk_name": None,
                    "reason": "shot_id must be a safe path component",
                }
            )
            continue
        if not isinstance(chunks, list):
            invalid_entries.append(
                {
                    "shot_id": shot_id,
                    "chunk_name": None,
                    "reason": "chunks must be a list",
                }
            )
            continue
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            chunk_name = chunk.get("chunk_name")
            if not isinstance(chunk_name, str) or not SAFE_PATH_COMPONENT.fullmatch(
                chunk_name
            ):
                invalid_entries.append(
                    {
                        "shot_id": shot_id,
                        "chunk_name": chunk_name,
                        "reason": "chunk_name must be a safe path component",
                    }
                )
                continue
            expected.append(
                {
                    "shot_id": shot_id,
                    "chunk_name": chunk_name,
                    "chunk_index": chunk.get("index"),
                    "chunk_dir": runs_root / shot_id / chunk_name,
                }
            )

    counts: dict[str, int] = {}
    per_shot: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    completed_seconds: list[float] = []
    peak_ram: tuple[int, Path] | None = None
    peak_vram: tuple[int, Path] | None = None
    receipt_errors: list[dict[str, str]] = []

    for item in expected:
        shot_id = str(item["shot_id"])
        chunk_name = str(item["chunk_name"])
        chunk_dir = Path(item["chunk_dir"])
        job_path = chunk_dir / "job.json"
        status = "NOT_STARTED"
        job: dict[str, Any] = {}
        if job_path.is_file():
            try:
                loaded = json.loads(job_path.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict):
                    job = loaded
                    status = str(job.get("status") or "UNKNOWN")
                else:
                    status = "INVALID_RECEIPT"
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                status = "INVALID_RECEIPT"
                receipt_errors.append({"path": str(job_path), "error": str(error)})

        counts[status] = counts.get(status, 0) + 1
        shot_summary = per_shot.setdefault(
            shot_id,
            {
                "expected_chunks": 0,
                "completed": 0,
                "status_counts": {},
                "last_chunk": None,
                "last_prompt_id": None,
                "last_activity": None,
            },
        )
        shot_summary["expected_chunks"] += 1
        shot_summary["status_counts"][status] = (
            shot_summary["status_counts"].get(status, 0) + 1
        )
        if status == "COMPLETED":
            shot_summary["completed"] += 1

        if job:
            shot_summary["last_chunk"] = chunk_name
            shot_summary["last_prompt_id"] = job.get("prompt_id")
            activity = (
                job.get("completed_at")
                or job.get("updated_at")
                or job.get("submitted_at")
            )
            if activity is not None:
                shot_summary["last_activity"] = activity

            submitted = _as_float(job.get("submitted_at"))
            completed = _as_float(job.get("completed_at"))
            if submitted is not None and completed is not None and completed >= submitted:
                completed_seconds.append(completed - submitted)

            if status == "FAILED":
                failures.append(_failure_summary(job, shot_id, chunk_name, job_path))

            telemetry = job.get("telemetry")
            if isinstance(telemetry, dict):
                ram = _as_int(telemetry.get("container_memory_peak_bytes"))
                vram = _as_int(telemetry.get("gpu_memory_peak_mib"))
                if ram is not None and (peak_ram is None or ram > peak_ram[0]):
                    peak_ram = (ram, chunk_dir / "job.json")
                if vram is not None and (peak_vram is None or vram > peak_vram[0]):
                    peak_vram = (vram, chunk_dir / "job.json")

        sample_path = chunk_dir / "telemetry-samples.json"
        if sample_path.is_file():
            ram, vram = _peak_from_samples(sample_path)
            if ram is not None and (peak_ram is None or ram > peak_ram[0]):
                peak_ram = (ram, sample_path)
            if vram is not None and (peak_vram is None or vram > peak_vram[0]):
                peak_vram = (vram, sample_path)

    for summary in per_shot.values():
        expected_chunks = int(summary["expected_chunks"])
        completed = int(summary["completed"])
        summary["remaining"] = expected_chunks - completed
        summary["progress_percent"] = (
            round(completed * 100.0 / expected_chunks, 2)
            if expected_chunks
            else 0.0
        )

    total = len(expected)
    completed_count = counts.get("COMPLETED", 0)
    average_seconds = (
        sum(completed_seconds) / len(completed_seconds)
        if completed_seconds
        else None
    )
    remaining = total - completed_count
    eta_seconds = (
        average_seconds * remaining if average_seconds is not None else None
    )

    run_state_path = runs_root / "run-state.json"
    run_state = None
    if run_state_path.is_file():
        try:
            run_state = json.loads(run_state_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            receipt_errors.append({"path": str(run_state_path), "error": str(error)})

    pid_file = technical_root / "full-run-r27.pid"
    pid_report: dict[str, Any] = {
        "path": str(pid_file),
        "exists": pid_file.is_file(),
        "pid": None,
        "alive": None,
    }
    if pid_file.is_file():
        try:
            pid_text = pid_file.read_text(encoding="ascii").strip()
            match = re.search(r"\d+", pid_text)
            if match:
                pid = int(match.group(0))
                pid_report["pid"] = pid
                pid_report["alive"] = _process_alive(pid)
        except (OSError, UnicodeError, ValueError) as error:
            pid_report["error"] = str(error)

    last_failure = None
    if failures:
        last_failure = max(
            failures,
            key=lambda item: (
                _as_float(item.get("failed_at"))
                or 0.0,
                str(item.get("job_path") or ""),
            ),
        )
    elif isinstance(run_state, dict) and run_state.get("failure"):
        last_failure = {
            "source": "run-state.json",
            "message": (
                run_state["failure"].get("message")
                if isinstance(run_state.get("failure"), dict)
                else run_state.get("failure_message")
            ),
            "failure": run_state.get("failure"),
            "failed_shot_id": run_state.get("failed_shot_id"),
            "failed_chunk_name": run_state.get("failed_chunk_name"),
        }

    return {
        "time": _now_iso(),
        "plan_path": str(plan_file),
        "plan_schema": plan.get("schema"),
        "plan_status": plan.get("status"),
        "film_id": plan.get("film_id"),
        "production_version": plan.get("production_version"),
        "runs_root": str(runs_root),
        "total_chunks": total,
        "completed_chunks": completed_count,
        "remaining_chunks": remaining,
        "progress_percent": round(completed_count * 100.0 / total, 2) if total else 0.0,
        "counts_by_status": counts,
        "per_shot": per_shot,
        "last_failure": last_failure,
        "receipt_errors": receipt_errors,
        "peak_container_ram_bytes": peak_ram[0] if peak_ram else None,
        "peak_container_ram_gib": (
            round(peak_ram[0] / (1024**3), 3) if peak_ram else None
        ),
        "peak_container_ram_source": str(peak_ram[1]) if peak_ram else None,
        "peak_gpu_vram_mib": peak_vram[0] if peak_vram else None,
        "peak_gpu_vram_source": str(peak_vram[1]) if peak_vram else None,
        "completed_chunks_in_average": len(completed_seconds),
        "average_seconds_per_chunk": (
            round(average_seconds, 3) if average_seconds is not None else None
        ),
        "eta_seconds_if_continuous": (
            round(eta_seconds, 3) if eta_seconds is not None else None
        ),
        "eta_hours_if_continuous": (
            round(eta_seconds / 3600.0, 3) if eta_seconds is not None else None
        ),
        "run_state": run_state,
        "executor_pid": pid_report,
        "executor_lock": {
            "path": str(executor_lock_path),
            "exists": executor_lock_path.exists(),
        },
        "invalid_entries": invalid_entries,
        "post_called": False,
    }


def _output_sha(value: dict[str, Any]) -> str | None:
    for key in ("output_sha256", "core_sha256"):
        candidate = value.get(key)
        if isinstance(candidate, str) and re.fullmatch(r"[0-9a-fA-F]{64}", candidate):
            return candidate.lower()
    outputs = value.get("outputs")
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict):
                candidate = item.get("sha256")
                if isinstance(candidate, str) and re.fullmatch(
                    r"[0-9a-fA-F]{64}", candidate
                ):
                    return candidate.lower()
    return None


def _validate_receipt_pattern(pattern: str) -> str:
    if not isinstance(pattern, str) or not pattern.strip():
        raise ToolError("pattern must be a non-empty glob string")
    if (
        ".." in pattern
        or re.match(r"[A-Za-z]:", pattern)
        or pattern.startswith(("/", "\\"))
        or Path(pattern).is_absolute()
    ):
        raise ToolError(
            "pattern must be a relative glob without drive letters, "
            "leading separators, or '..'"
        )
    return pattern


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def episode_receipts(
    episode_dir: str, pattern: str | None = None
) -> dict[str, Any]:
    directory = _validate_inside(episode_dir, "episode_dir")
    if not directory.is_dir():
        raise ToolError(f"episode_dir is not a directory: {directory}")
    if pattern:
        pattern = _validate_receipt_pattern(pattern)
        candidates = list(directory.rglob(pattern))
    else:
        candidates = list(directory.rglob("job.json")) + list(
            directory.rglob("preparation.json")
        )

    paths: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError as error:
            raise ToolError(
                f"receipt path cannot be resolved: {candidate}: {error}"
            ) from error
        if not _is_within(resolved, directory):
            raise ToolError(
                f"receipt path is outside episode_dir {directory}: {resolved}"
            )
        if not _is_within(resolved, ROOT):
            raise ToolError(
                f"receipt path is outside the allowed workspace root {ROOT}: {resolved}"
            )
        paths.append(resolved)

    receipts: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in sorted(paths, key=lambda item: str(item).lower()):
        if not path.is_file() or path in seen:
            continue
        seen.add(path)
        record: dict[str, Any] = {
            "path": str(path),
            "relative_path": str(path.relative_to(directory)),
            "kind": path.name,
            "prompt_id": None,
            "status": None,
            "output_sha256": None,
            "sha256": None,
        }
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            record["error"] = str(error)
            receipts.append(record)
            continue
        if not isinstance(value, dict):
            record["error"] = "receipt is not a JSON object"
            receipts.append(record)
            continue
        record["prompt_id"] = _receipt_prompt_id(value)
        record["status"] = value.get("status")
        record["output_sha256"] = _output_sha(value)
        record["sha256"] = value.get("sha256")
        for key in (
            "shot_id",
            "chunk_name",
            "production_version",
            "created_at",
            "submitted_at",
            "completed_at",
        ):
            if key in value:
                record[key] = value.get(key)
        receipts.append(record)

    return {
        "episode_dir": str(directory),
        "pattern": pattern,
        "count": len(receipts),
        "receipts": receipts,
    }


def _bridge_core() -> ModuleType:
    """Load the shared bridge core lazily so a missing pack never breaks the other tools."""
    global _BRIDGE_CORE
    if _BRIDGE_CORE is None:
        if not BRIDGE_CORE_PATH.is_file():
            raise ToolError(f"claude bridge core is missing: {BRIDGE_CORE_PATH}")
        module_name = "jenniejoy_claude_bridge_core"
        spec = importlib.util.spec_from_file_location(module_name, BRIDGE_CORE_PATH)
        if spec is None or spec.loader is None:
            raise ToolError(f"cannot load claude bridge core: {BRIDGE_CORE_PATH}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _BRIDGE_CORE = module
    return _BRIDGE_CORE


def _bridge_paths(core: ModuleType) -> Any:
    shared = (os.environ.get(core.ENV_SHARED) or "").strip()
    return core.BridgePaths.from_shared(shared or DEFAULT_BRIDGE_SHARED)


def _touch_bridge_heartbeat(tool_name: str) -> None:
    """Tell the ComfyUI node a chat is serving the bridge. Best effort; never fails a tool call."""
    try:
        core = _bridge_core()
        core.write_heartbeat(_bridge_paths(core), tool_name)
    except Exception:
        return


def _bridge_view(
    core: ModuleType, paths: Any, request: dict[str, Any], full: bool
) -> dict[str, Any]:
    prompt = request.get("prompt") if isinstance(request.get("prompt"), str) else ""
    created = _as_float(request.get("created_unix"))
    images: list[dict[str, Any]] = []
    for ref in request.get("images") or []:
        sha = ref.get("sha256") if isinstance(ref, dict) else None
        if not core.is_request_id(sha):
            continue
        image_path = paths.image(sha)
        images.append(
            {"sha256": sha, "host_path": str(image_path), "exists": image_path.is_file()}
        )
    view: dict[str, Any] = {
        "request_id": request.get("request_id"),
        "created_at": request.get("created_at"),
        "age_seconds": round(time.time() - created, 1) if created is not None else None,
        "timeout_s": request.get("timeout_s"),
        "prompt_chars": len(prompt),
        "images": images,
    }
    if "error" in request:
        view["error"] = request["error"]
    if full:
        view["system"] = request.get("system")
        view["prompt"] = prompt
        view["answered"] = bool(request.get("answered"))
    else:
        view["prompt_preview"] = prompt[:300]
    return view


def bridge_pending(request_id: str | None = None) -> dict[str, Any]:
    """List unanswered requests, or read one in full. Read-only."""
    core = _bridge_core()
    paths = _bridge_paths(core)
    age = core.heartbeat_age(paths)
    report: dict[str, Any] = {
        "bridge_dir": str(paths.base),
        "heartbeat_age_seconds": None if age is None else round(age, 1),
        "post_called": False,
    }
    try:
        if request_id is not None:
            request = core.read_pending(paths, request_id)
            report["request"] = _bridge_view(core, paths, request, True)
            return report
        pending = core.list_pending(paths)
    except core.BridgeError as error:
        raise ToolError(str(error)) from error
    report["count"] = len(pending)
    report["pending"] = [_bridge_view(core, paths, item, False) for item in pending]
    return report


def bridge_wait(timeout_s: float = 60.0) -> dict[str, Any]:
    """Block until a request is pending (keeps the heartbeat fresh), then list it."""
    core = _bridge_core()
    paths = _bridge_paths(core)
    wait = max(1.0, min(BRIDGE_WAIT_MAX_SECONDS, float(timeout_s)))
    started = time.monotonic()
    deadline = started + wait
    while True:
        core.write_heartbeat(paths, "bridge_wait")
        pending = core.list_pending(paths)
        if pending or time.monotonic() >= deadline:
            return {
                "bridge_dir": str(paths.base),
                "timed_out": not pending,
                "waited_seconds": round(time.monotonic() - started, 1),
                "count": len(pending),
                "pending": [_bridge_view(core, paths, item, False) for item in pending],
                "post_called": False,
            }
        time.sleep(1.0)


def bridge_answer(
    request_id: str,
    answer: str,
    confirm: str,
    model_reported: str | None = None,
) -> dict[str, Any]:
    """Publish one answer to the outbox (atomic, never overwrites, unknown ids refused)."""
    if confirm != "ANSWER":
        raise ToolError('answer refused: confirm must be exactly "ANSWER"; nothing was written')
    core = _bridge_core()
    paths = _bridge_paths(core)
    try:
        record = core.post_answer(paths, request_id, answer, model_reported)
    except core.BridgeError as error:
        raise ToolError(f"answer refused: {error}") from error
    return {
        "request_id": record["request_id"],
        "answered_at": record["answered_at"],
        "answer_sha256": record["answer_sha256"],
        "model_reported": record["model_reported"],
        "outbox_path": str(paths.entry(paths.outbox, record["request_id"])),
        "post_called": False,
    }


TOOLS: dict[str, tuple[str, dict[str, Any], Callable[..., Any]]] = {
    "comfy_status": (
        "Show the Comfyui-Studio container, live queue, and VRAM/argv. GET only; "
        "does not touch the helper-owned production submit lock.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        comfy_status,
    ),
    "comfy_validate_graph": (
        "Check graph SHA-256, API format, registered node classes, and partner/denied nodes. Never submits.",
        {
            "type": "object",
            "properties": {
                "graph_path": {"type": "string"},
                "expect_sha256": {"type": "string"},
            },
            "required": ["graph_path"],
            "additionalProperties": False,
        },
        comfy_validate_graph,
    ),
    "comfy_submit_guarded": (
        "Submit one hash-bound API graph through the reviewed shared-lock guard, "
        "then return after submitted.json without waiting for GPU execution. "
        "Requires confirm=SUBMIT.",
        {
            "type": "object",
            "properties": {
                "graph_path": {"type": "string"},
                "receipt_dir": {"type": "string"},
                "expect_sha256": {"type": "string"},
                "confirm": {"type": "string"},
            },
            "required": ["graph_path", "receipt_dir", "expect_sha256", "confirm"],
            "additionalProperties": False,
        },
        comfy_submit_guarded,
    ),
    "comfy_job": (
        "Read guarded/executor receipts, including unknown/rejected dispatch "
        "records, and optionally GET ComfyUI history. Never submits.",
        {
            "type": "object",
            "properties": {
                "receipt_dir": {"type": "string"},
                "include_history": {"type": "boolean", "default": False},
            },
            "required": ["receipt_dir"],
            "additionalProperties": False,
        },
        comfy_job,
    ),
    "comfy_reconcile": (
        "Resolve an existing dispatch intent by client_id through GET /queue and "
        "GET /history. Never POSTs.",
        {
            "type": "object",
            "properties": {"receipt_dir": {"type": "string"}},
            "required": ["receipt_dir"],
            "additionalProperties": False,
        },
        comfy_reconcile,
    ),
    "seedvr2_run_status": (
        "Summarize a v004-style SeedVR2 plan against runs receipts, telemetry, "
        "failures, ETA, executor PID and executor lock. plan_path defaults to the "
        "ep04 production plan.",
        {
            "type": "object",
            "properties": {"plan_path": {"type": "string"}},
            "additionalProperties": False,
        },
        seedvr2_run_status,
    ),
    "episode_receipts": (
        "List job.json and preparation.json receipts with prompt ID, status, and output SHA-256.",
        {
            "type": "object",
            "properties": {
                "episode_dir": {"type": "string"},
                "pattern": {"type": "string"},
            },
            "required": ["episode_dir"],
            "additionalProperties": False,
        },
        episode_receipts,
    ),
    "bridge_pending": (
        "Claude bridge: list unanswered JJClaudeBridge requests from the ComfyUI node, or read "
        "one in full with request_id. Read-only. Answer each with bridge_answer.",
        {
            "type": "object",
            "properties": {"request_id": {"type": "string"}},
            "additionalProperties": False,
        },
        bridge_pending,
    ),
    "bridge_wait": (
        "Claude bridge: block up to timeout_s (max 100) until a JJClaudeBridge request is "
        "pending, refreshing the heartbeat so the node sees this chat as live. Read-only.",
        {
            "type": "object",
            "properties": {"timeout_s": {"type": "number", "default": 60}},
            "additionalProperties": False,
        },
        bridge_wait,
    ),
    "bridge_answer": (
        "Claude bridge: write the answer for one pending request_id to the outbox. Atomic; "
        "refuses unknown or already-answered ids. Requires confirm=ANSWER. Write the answer "
        "yourself from the request; model_reported is a free-text label.",
        {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "answer": {"type": "string"},
                "confirm": {"type": "string"},
                "model_reported": {"type": "string"},
            },
            "required": ["request_id", "answer", "confirm"],
            "additionalProperties": False,
        },
        bridge_answer,
    ),
}


def _tool_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for name, (description, schema, _) in TOOLS.items():
        if name == "comfy_submit_guarded":
            annotations = {"readOnlyHint": False, "destructiveHint": True}
        elif name == "bridge_answer":
            annotations = {"readOnlyHint": False, "destructiveHint": False}
        elif name == "comfy_reconcile":
            # Never POSTs, but the helper writes reconcile-report.json / reconciled.json receipts.
            annotations = {"readOnlyHint": False, "destructiveHint": False}
        else:
            annotations = {"readOnlyHint": True, "destructiveHint": False}
        specs.append({
            "name": name,
            "description": description,
            "inputSchema": schema,
            "annotations": annotations,
        })
    return specs


def _tool_result(value: object, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": _json_text(value)}],
        "isError": is_error,
    }


def _call_tool(name: str, arguments: object) -> dict[str, Any]:
    tool = TOOLS.get(name)
    if tool is None:
        return _tool_result({"error": f"unknown tool: {name}"}, is_error=True)
    if not isinstance(arguments, dict):
        return _tool_result({"error": "tools/call arguments must be an object"}, True)
    _, _, handler = tool
    if name in BRIDGE_LIVENESS_TOOLS:
        _touch_bridge_heartbeat(name)
    try:
        signature = inspect.signature(handler)
        signature.bind(**arguments)
    except TypeError as error:
        return _tool_result({"error": f"invalid tool arguments: {error}"}, True)
    except (ValueError, AttributeError):
        # A callable without an inspectable signature still gets a normal call;
        # its own TypeErrors must not be mislabeled as argument-binding errors.
        pass
    try:
        return _tool_result(handler(**arguments), is_error=False)
    except ToolError as error:
        text = str(error)
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = {"error": text}
        return _tool_result(value, is_error=True)
    except Exception as error:
        return _tool_result(
            {"error": f"{type(error).__name__}: {error}"},
            is_error=True,
        )


def _error_response(request_id: object, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _write_response(target: Any, response: dict[str, Any]) -> bool:
    try:
        payload = json.dumps(response, ensure_ascii=False) + "\n"
        target.write(payload)
        target.flush()
        return True
    except Exception as error:
        try:
            sys.stderr.write(f"jenniejoy-comfy response write failed: {error!r}\n")
            sys.stderr.flush()
        except Exception:
            pass
        return False


def _handle_message(message: object) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return _error_response(None, -32600, "invalid request")
    request_id = message.get("id")
    method = message.get("method")
    is_notification = "id" not in message
    if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return None if is_notification else _error_response(
            request_id, -32600, "invalid request"
        )

    if method == "notifications/initialized":
        return None
    if method == "ping":
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "initialize":
        if is_notification:
            return None
        params = message.get("params")
        requested_version = (
            params.get("protocolVersion") if isinstance(params, dict) else None
        )
        negotiated_version = (
            requested_version
            if requested_version in SUPPORTED_PROTOCOL_VERSIONS
            else PROTOCOL_VERSION
        )
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": negotiated_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "tools/list":
        if is_notification:
            return None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": _tool_specs()},
        }
    if method == "tools/call":
        params = message.get("params")
        if is_notification:
            return None
        if not isinstance(params, dict):
            return _error_response(request_id, -32602, "tools/call params required")
        name = params.get("name")
        if not isinstance(name, str):
            return _error_response(request_id, -32602, "tool name required")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": _call_tool(name, params.get("arguments", {})),
        }
    if is_notification:
        return None
    return _error_response(request_id, -32601, f"method not found: {method}")


def serve(stdin: Iterable[str] | None = None, stdout: Any = None) -> int:
    source = stdin if stdin is not None else sys.stdin
    target = stdout if stdout is not None else sys.stdout
    for line in source:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            response = _error_response(None, -32700, f"parse error: {error}")
        else:
            try:
                response = _handle_message(message)
            except Exception as error:
                response = _error_response(
                    message.get("id") if isinstance(message, dict) else None,
                    -32603,
                    f"internal error: {error}",
                )
        if response is not None:
            _write_response(target, response)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
