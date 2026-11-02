"""``POST /v1/video/shot``: start ``jjv video run|render|status`` as a DETACHED child process and return at once.

Never a graph node: ``video run`` submits to the same ComfyUI, so a node that waited for it would deadlock the executor.
One video job at a time (the GPU runs one job).  The bridge never invents a GPU approval: ``gpu_approved`` is passed
only when the caller sends it, and without it the engine stops at its own ``gpu-approval`` gate (exit 0, ok:false).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from ..core.errors import Refused
from ..core.paths import require_inside
from ..core.winflags import no_window
from .config import BridgeConfig
from .jobs import BridgeBusy, JobStore

VERBS = ("run", "render", "status")
NEW_PROCESS_GROUP = 0x200


def _text(body: dict[str, Any], key: str, required: bool) -> str | None:
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise Refused(f"{key} is required (a non-empty string)")
    return value.strip()


SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _confine(value: str, root: Path, key: str, allow_slug: bool) -> str:
    """Resolve ``value`` (relative = under ``root``) and require it inside ``root``; ``..`` parts are refused outright."""
    if ".." in re.split(r"[\/]+", value):
        raise Refused(f"{key} {value!r} has a '..' part: it must stay inside the workspace {root.as_posix()}")
    if allow_slug and SLUG.fullmatch(value):
        return value  # an episode slug: the engine resolves it under its own episodes root
    target = Path(value)
    try:
        return require_inside(target if target.is_absolute() else root / target, root, f"{key} (workspace)").as_posix()
    except Refused as error:
        raise Refused(f"{key} must be inside the workspace {root.as_posix()}: {error}") from error


def validate_request(body: Any, root: Path | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise Refused("request body must be a JSON object")
    verb = body.get("verb") or "run"
    if verb not in VERBS:
        raise Refused(f"verb must be one of {VERBS} (got {verb!r}); accept/upscale stay human CLI steps")
    req: dict[str, Any] = {"verb": verb, "episode": _text(body, "episode", True), "out": _text(body, "out", True),
                           "shot": _text(body, "shot", verb == "render"), "gpu_approved": _text(body, "gpu_approved", False),
                           "dry_run": body.get("dry_run") is True, "revision": body.get("revision"), "route": None,
                           "timeout": body.get("timeout")}
    if verb == "render":
        if isinstance(req["revision"], bool) or not isinstance(req["revision"], int):
            raise Refused("render needs revision (an integer: the shot's current revision)")
        req["route"] = _text(body, "route", True)
    if root is not None:
        req["episode"] = _confine(req["episode"], Path(root), "episode", allow_slug=True)
        req["out"] = _confine(req["out"], Path(root), "out", allow_slug=False)
    if req["timeout"] is not None and (isinstance(req["timeout"], bool) or not isinstance(req["timeout"], (int, float))
                                       or req["timeout"] <= 0):
        raise Refused("timeout must be a positive number of seconds")
    return req


def video_argv(req: dict[str, Any]) -> list[str]:
    verb = req["verb"]
    argv = ["video", verb, "--episode", req["episode"], "--out", req["out"]]
    if verb == "render":
        argv += ["--shot", req["shot"], "--revision", str(req["revision"]), "--route", req["route"]]
    elif verb == "status" and req["shot"]:
        argv += ["--shot", req["shot"]]
    if verb == "run" and req["dry_run"]:
        argv.append("--dry-run")
    if verb in ("run", "render") and req["gpu_approved"]:
        argv += ["--gpu-approved", req["gpu_approved"]]
    if verb in ("run", "render") and req["timeout"] is not None:
        argv += ["--timeout", str(req["timeout"])]
    return argv


def _last_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        start = text.rfind("\n{")
        try:
            return json.loads(text[start + 1:]) if start >= 0 else None
        except ValueError:
            return None


def _watch(store: JobStore, job_id: str, process: Any, handles: list[Any]) -> None:
    try:
        code = process.wait()
    finally:
        for handle in handles:
            handle.close()
        with store.video_lock:
            if store.running_video == job_id:
                store.running_video = None
    folder = store.folder(job_id)
    result = _last_json((folder / "stdout.json").read_text(encoding="utf-8", errors="replace"))
    gate = result.get("gate") if isinstance(result, dict) else None

    def close(doc: dict[str, Any]) -> None:
        doc.update(state="done" if code == 0 else "failed", exit_code=code, result=result, gate=gate,
                   stderr_tail=(folder / "stderr.log").read_text(encoding="utf-8", errors="replace")[-800:])

    store.update(job_id, close)


def start(cfg: BridgeConfig, store: JobStore, body: Any, popen: Callable[..., Any] = subprocess.Popen) -> dict[str, Any]:
    req = validate_request(body, cfg.workspace_root)
    argv = video_argv(req)
    with store.video_lock:
        if store.running_video is not None:
            raise BridgeBusy(f"video job {store.running_video} is still running: one video job at a time (the GPU runs one job)")
        job_id = store.new("vd", {"kind": "video", "state": "running", "verb": req["verb"], "shot": req["shot"],
                                  "episode": req["episode"], "out": req["out"], "argv": argv,
                                  "gpu_approved_given": bool(req["gpu_approved"])})
        folder = store.folder(job_id)
        handles = [open(folder / "stdout.json", "wb"), open(folder / "stderr.log", "wb")]  # noqa: SIM115 - closed by _watch
        flags = no_window() | (NEW_PROCESS_GROUP if os.name == "nt" else 0)
        try:
            process = popen([*cfg.jjv_cmd, *argv], stdout=handles[0], stderr=handles[1], stdin=subprocess.DEVNULL,
                            cwd=str(folder), creationflags=flags)
        except OSError as error:
            for handle in handles:
                handle.close()
            store.update(job_id, lambda doc: doc.update(state="failed", error=f"cannot start jjv: {error!r}"))
            store.finish(job_id)
            raise Refused(f"cannot start jjv video: {error!r}") from error
        store.running_video = job_id
    store.update(job_id, lambda doc: doc.update(pid=process.pid))
    store.spawn(job_id, lambda: _watch(store, job_id, process, handles))
    return {"job_id": job_id, "state": "running", "pid": process.pid, "argv": argv}
