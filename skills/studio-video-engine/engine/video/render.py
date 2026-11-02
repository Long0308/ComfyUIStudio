"""Group ``03 AI QUAY VIDEO``: render một shot qua ĐÚNG đường H3 hiện có (prepare -> submit -> adopt).

Thứ tự, mọi từ chối trước khi gửi: ``--gpu-approved`` -> qualification H3 của domain (``recipes/h3/routes``) ->
``<out>/h3-inputs.json`` (do ``jjv h3 inputs`` dựng từ receipt: anchor đã duyệt, WAV đã nghe duyệt) phải mang
đúng prompt/length/seed đã đóng băng -> ``h3 prepare`` (offline, idempotent) -> dưới khoá EXECUTOR máy:
``h3 submit --approve-gpu`` (``comfy.dispatch`` có khoá submit, hàng đợi rỗng, intent O_EXCL) -> ``h3 adopt``.
Receipt render gắn prompt/ref/WAV/graph/output sha và prompt_id.  Một shot đã có post evidence không bao giờ
được POST lại (``h3 submit`` báo ALREADY_SUBMITTED, ``adopt`` idempotent).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..comfy.client import ComfyClient
from ..comfy.settings import ComfySettings
from ..core.errors import Refused
from ..core.io import read_json, write_json_once
from ..core.runlock import rename_stale_lock, run_pid_lock
from ..core import steplog
from ..comfy.queue import queue_counts
from ..h3 import adopt as adopt_mod
from ..h3 import prepare as prepare_mod
from ..h3 import submit as submit_mod
from ..layout.context import Context
from . import longrender as longrender_mod
from . import state as state_mod

MANIFEST_FILE = "h3-inputs.json"
RECEIPT_FILE = "render-receipt.json"
RUNS_DIR = "runs"


@dataclass(frozen=True)
class ComfyHandles:
    settings: ComfySettings
    client: ComfyClient
    probe: Any
    ps: Callable[[str], str]


def h3_dir(out: Path, revision: int) -> Path:
    return Path(out) / f"h3-{state_mod.rev(revision)}"


def manifest_path(out: Path) -> Path:
    return Path(out) / MANIFEST_FILE


def require_gpu_approval(gpu_approval: dict[str, Any] | None, what: str) -> None:
    if gpu_approval is None:
        raise Refused(f"GPU_APPROVAL_MISSING: {what} uses the GPU; pass --gpu-approved <receipt or token from the "
                      "user> (explicit approval for THIS run); nothing was sent")


def require_manifest(ctx: Context, out: Path, receipt: dict[str, Any], prompt_text: str) -> tuple[Path, dict[str, Any]]:
    """Hàng h3-inputs của shot, khớp byte với prompt/length/seed đã đóng băng và template của plan."""
    path = manifest_path(out)
    shot = receipt["shot"]
    if not path.is_file():
        raise Refused(f"H3_INPUTS_MISSING: {path} not found; build it from receipts with `jjv h3 inputs --episode "
                      f"{ctx.episode_id} --spec {Path(out) / 'h3-spec-<rev>.json'} --images <jjv images dir> --voice "
                      f"<jjv voice dir> --out {path}` (needs an approved native anchor and a listen-approved WAV per shot)")
    document = read_json(path)
    if (document.get("schema"), document.get("episode_id"), document.get("domain")) != (
            prepare_mod.INPUTS_SCHEMA, ctx.episode_id, ctx.domain_id):
        raise Refused(f"{path}: schema/episode/domain mismatch (needs {prepare_mod.INPUTS_SCHEMA} of {ctx.episode_id})")
    rows = [r for r in document.get("shots") or [] if isinstance(r, dict) and r.get("shot") == shot]
    if len(rows) != 1:
        raise Refused(f"H3_INPUTS_MISSING: {path} holds {len(rows)} rows for shot {shot} (need exactly one)")
    row = rows[0]
    ports = receipt["ports"]
    expected = {ports["prompt"]: prompt_text, ports["length"]: receipt["length"]["frames"], ports["seed"]: receipt["seed"]}
    mouth = row.get("mouth") or {}
    frozen = receipt.get("geometry")
    if frozen:  # cỡ H3 đóng băng ở plan: h3-inputs phải mang đúng cỡ đó (bội 32, đọc từ routes)
        wrong = sorted(f"{frozen['ports'][a]}={mouth.get(frozen['ports'][a])!r} (plan {frozen[a]})"
                       for a in ("width", "height") if mouth.get(frozen["ports"][a]) != frozen[a])
        if wrong:
            raise Refused(f"GEOMETRY_DRIFT: {shot}: h3-inputs mouth {wrong} differs from the frozen plan geometry "
                          f"{frozen['width']}x{frozen['height']}; rebuild the h3-spec with those widget values")
    drift = sorted(key for key, value in expected.items() if mouth.get(key) != value)
    if drift:
        raise Refused(f"PROMPT_DRIFT: {shot}: h3-inputs mouth values {drift} differ from the frozen prompt receipt; "
                      "rebuild h3-inputs.json from the h3-spec of this revision (a prompt is never changed mid-render)")
    if (row.get("template") or {}).get("sha256") != receipt["template"]["sha256"]:
        raise Refused(f"TEMPLATE_DRIFT: {shot}: h3-inputs template sha256 is not the plan template "
                      f"{receipt['template']['sha256'][:12]}")
    return path, row


def render(ctx: Context, out: Path, state: dict[str, Any], receipt: dict[str, Any], prompt_text: str,
           route: dict[str, Any], *, gpu_approval: dict[str, Any] | None, comfy: ComfyHandles,
           wait_timeout: float = 3600.0, take_decision: dict[str, Any] | None = None) -> Path:
    """Render shot ``state['shot']`` revision hiện tại; trả về đường dẫn ``render-receipt.json`` (write-once)."""
    shot, revision = state["shot"], int(state["revision"])
    require_gpu_approval(gpu_approval, "h3 submit")
    decision = take_decision or {"take_mode": "short", "route": route["h3_route"], "reason": "legacy short plan"}
    if decision["take_mode"] == "long":
        prepare_mod.domain_guard(ctx)
        manifest, row = require_manifest(ctx, out, receipt, prompt_text)
        folder, preparation, graph = longrender_mod.prepare_graph(
            ctx, out, state, receipt, prompt_text, route, manifest, row, gpu_approval)
        adopt_file, result = longrender_mod.dispatch_and_adopt(ctx, out, folder, preparation, graph, comfy, wait_timeout)
        adopted = result["adopted"]
        editorial = next(r for r in adopted["outputs"] if r["role"] == "editorial")
        preparation_file = folder / prepare_mod.PREPARATION_FILE
        body = {"schema": state_mod.RENDER_RECEIPT_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
                "shot": shot, "revision": revision, "route": decision["route"], "take_decision": decision,
                "gpu_approval": gpu_approval, "prompt_receipt": state["receipts"]["prompt"],
                "plan_receipt": state["receipts"]["plan"], "h3_inputs": state_mod.ref(out, manifest),
                "preparation": {**state_mod.ref(out, preparation_file), "graph_sha256": preparation["graph_sha256"],
                                "wav_sha256": preparation["wav"]["sha256"],
                                "anchor_sha256": preparation["anchor"]["sha256"],
                                "faces_sha256": [f["sha256"] for f in preparation["faces"]]},
                "adopt": state_mod.ref(out, adopt_file), "prompt_id": adopted["prompt_id"],
                "native": {"path": editorial["path"], "sha256": editorial["sha256"], "name": editorial["name"]},
                "submit": result["submitted"], "window_count": preparation["window_count"],
                "window_log": preparation["window_log"],
                "gpu_lock": {"path": str(comfy.settings.executor_lock_path), "scope": "machine",
                             "held": "video long-take: guarded H3 submit -> wait -> adopt"}}
        path = state_mod.shot_dir(out, shot) / "render" / state_mod.rev(revision) / RECEIPT_FILE
        write_json_once(path, body, mode="utf8")
        return path
    prepare_mod.domain_guard(ctx)  # Refused khi domain chưa có pilot H3 qualified (cổng needs-gpu-pilot-approval)
    manifest, _row = require_manifest(ctx, out, receipt, prompt_text)
    folder = h3_dir(out, revision)
    prepare_mod.prepare(ctx, manifest, folder, shots=[shot])
    identity = {"stage": "video-render", "video_out": str(Path(out).resolve()), "shot": shot, "revision": revision}
    lock_path = comfy.settings.executor_lock_path
    if lock_path.is_file():
        def queue_idle() -> bool:
            running, pending = queue_counts(comfy.client.get("/queue"))
            return running == pending == 0

        archived = rename_stale_lock(lock_path, queue_idle=queue_idle, report_dir=Path(out) / RUNS_DIR)
        if archived is not None:
            steplog.append(Path(out), run_id=Path(out).name, step_id=f"video.render.lock_recovery.{shot}.r{revision:03d}",
                           stage="video.render.lock_recovery", started=datetime.now(timezone.utc).isoformat(),
                           inputs=[], settings={"shot": shot, "revision": revision},
                           outputs=[steplog.file_ref(Path(out), archived, "stale_lock_archive")],
                           model={"name": None}, status="SKIPPED", note=f"renamed stale executor lock to {archived}")
    with run_pid_lock(lock_path, report_dir=Path(out) / RUNS_DIR, scope="machine", extra=identity):
        # Khoá EXECUTOR máy được giữ ở đây suốt submit -> wait -> adopt; `h3 submit` vì thế không tự lấy lại
        # (run_pid_lock không re-entrant) nhưng vẫn là CÙNG một khoá với `seedvr2 execute` và `jjv h3 submit`.
        submitted = submit_mod.submit(ctx, folder, [shot], comfy.settings, comfy.client, approve_gpu=True,
                                      probe=comfy.probe, ps=comfy.ps, wait_timeout=wait_timeout, wait=True,
                                      hold_executor_lock=False, recover_lost=True)
        adopt_mod.adopt(ctx, folder, [shot], comfy.settings, comfy.client, wait_timeout=wait_timeout)
    adopt_file = folder / shot / adopt_mod.ADOPT_FILE
    adopted = read_json(adopt_file)
    editorial = next(r for r in adopted["outputs"] if r["role"] == "editorial")
    preparation_file = folder / shot / prepare_mod.PREPARATION_FILE
    preparation = read_json(preparation_file)
    body = {"schema": state_mod.RENDER_RECEIPT_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
            "shot": shot, "revision": revision, "route": decision["route"], "take_decision": decision,
            "gpu_approval": gpu_approval,
            "prompt_receipt": state["receipts"]["prompt"], "plan_receipt": state["receipts"]["plan"],
            "h3_inputs": state_mod.ref(out, manifest),
            "preparation": {**state_mod.ref(out, preparation_file), "graph_sha256": preparation["graph_sha256"],
                            "wav_sha256": preparation["wav"]["sha256"], "anchor_sha256": preparation["anchor"]["sha256"],
                            "faces_sha256": [f["sha256"] for f in preparation["faces"]]},
            "adopt": state_mod.ref(out, adopt_file), "prompt_id": adopted["prompt_id"],
            "native": {"path": editorial["path"], "sha256": editorial["sha256"], "name": editorial["name"]},
            "submit": {"submitted": [r["shot"] for r in submitted["submitted"]],
                       "already_submitted": [r["shot"] for r in submitted["already_submitted"]]},
            "gpu_lock": {"path": str(lock_path), "scope": "machine",
                         "held": "video render: prepare -> h3 submit (POST + wait) -> adopt"}}
    path = state_mod.shot_dir(out, shot) / "render" / state_mod.rev(revision) / RECEIPT_FILE
    write_json_once(path, body, mode="utf8")
    return path


__all__ = ["ComfyHandles", "render", "require_manifest", "require_gpu_approval", "h3_dir", "manifest_path",
           "MANIFEST_FILE", "RECEIPT_FILE"]
