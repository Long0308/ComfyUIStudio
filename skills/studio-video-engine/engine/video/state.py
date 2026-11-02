"""Trạng thái từng shot của ``jjv video`` và chuỗi receipt bất biến.

``state.json`` là file DUY NHẤT thay đổi được (``write_atomic``); mọi receipt là write-once.  State chỉ tiến
khi receipt tương ứng đã nằm trên đĩa và được băm; khi resume từng receipt được kiểm lại theo sha256
(:func:`verify_ref`), không suy trạng thái từ tên file hay từ hàng đợi ComfyUI (spec §2a).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file, write_json_atomic
from ..layout.context import Context

STATES = ("planned", "prompted", "rendered", "upscaled_1080", "accepted")
NEXT_STATE = {state: STATES[index + 1] for index, state in enumerate(STATES[:-1])}
STATE_SCHEMA = "jjv/video-shot-state/v1"
PLAN_SCHEMA = "jjv/video-plan/v1"
PLAN_RECEIPT_SCHEMA = "jjv/video-plan-receipt/v1"
PROMPT_RECEIPT_SCHEMA = "jjv/video-prompt-receipt/v1"
RENDER_RECEIPT_SCHEMA = "jjv/video-render-receipt/v1"
UPSCALE_RECEIPT_SCHEMA = "jjv/video-upscale-receipt/v1"
UPSCALE_PENDING_SCHEMA = "jjv/video-upscale-pending/v1"
ACCEPT_SCHEMA = "jjv/video-acceptance/v1"
RUN_SCHEMA = "jjv/video-run/v1"
PLAN_FILE = "plan.json"
STATE_FILE = "state.json"
PLAN_RECEIPT_FILE = "plan-receipt.json"


def rev(revision: int) -> str:
    return f"r{int(revision):03d}"


def shot_dir(out: Path, shot: str) -> Path:
    return Path(out) / shot


def read_plan(out: Path) -> dict[str, Any]:
    path = Path(out) / PLAN_FILE
    if not path.is_file():
        raise Refused(f"no {PLAN_FILE} under {out}; run 'jjv video plan' first")
    plan = read_json(path)
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise Refused(f"{path}: not a {PLAN_SCHEMA} document")
    return plan


def require_plan_of(ctx: Context, plan: dict[str, Any]) -> None:
    if (plan.get("episode_id"), plan.get("domain")) != (ctx.episode_id, ctx.domain_id):
        raise Refused(f"video plan belongs to episode {plan.get('episode_id')!r} / domain {plan.get('domain')!r}, "
                      f"not {ctx.episode_id!r} / {ctx.domain_id!r}")


def read_state(out: Path, shot: str) -> dict[str, Any]:
    path = shot_dir(out, shot) / STATE_FILE
    if not path.is_file():
        raise Uncertain(f"RECONCILE: {shot}: {STATE_FILE} is missing under {out}")
    state = read_json(path)
    if not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA or state.get("state") not in STATES \
            or state.get("shot") != shot:
        raise Uncertain(f"RECONCILE: {path} is not a {STATE_SCHEMA} document of shot {shot}")
    return state


def write_state(out: Path, state: dict[str, Any]) -> str:
    return write_json_atomic(shot_dir(out, state["shot"]) / STATE_FILE, state, mode="utf8")


def ref(out: Path, path: Path) -> dict[str, str]:
    """Tham chiếu receipt: đường dẫn tương đối so với ``out`` + sha256 của file."""
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(Path(out).resolve()).as_posix()
    except ValueError:
        relative = resolved.as_posix()
    return {"path": relative, "sha256": sha256_file(resolved)}


def ref_path(out: Path, entry: dict[str, Any]) -> Path:
    given = Path(entry["path"])
    return given if given.is_absolute() else Path(out) / given


def verify_ref(out: Path, entry: Any, label: str) -> dict[str, Any]:
    """Receipt phải tồn tại và băm đúng; sai ⇒ Uncertain (resume dừng để reconcile, không skip)."""
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
        raise Uncertain(f"RECONCILE: {label} receipt reference is malformed: {entry!r}")
    path = ref_path(out, entry)
    if not path.is_file():
        raise Uncertain(f"RECONCILE: {label} receipt is missing: {path}")
    actual = sha256_file(path)
    if actual != entry["sha256"]:
        raise Uncertain(f"RECONCILE: {label} receipt {path.name} changed after it was recorded "
                        f"(expected {entry['sha256'][:12]}, found {actual[:12]}); nothing is skipped or re-sent")
    return read_json(path)


def new_state(ctx: Context, shot: str, order: int, plan_receipt: dict[str, str], *, now: float | None = None) -> dict:
    return {"schema": STATE_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id, "shot": shot,
            "order": order, "state": STATES[0], "revision": 1, "receipts": {"plan": plan_receipt}, "gate": None,
            "rejected": [], "history": [{"state": STATES[0], "revision": 1, "at": float(time.time() if now is None else now)}]}


def advance(out: Path, state: dict[str, Any], to: str, *, receipt_key: str | None = None,
            receipt_path: Path | None = None, now: float | None = None) -> dict[str, Any]:
    """Chuyển state tiến đúng một bậc (bản sao mới, ghi atomic); receipt của bước đó được băm vào state."""
    if to != NEXT_STATE.get(state["state"]):
        raise Refused(f"{state['shot']}: illegal transition {state['state']} -> {to}")
    receipts = dict(state["receipts"])
    if receipt_key is not None:
        if receipt_path is None:
            raise Refused(f"{state['shot']}: transition to {to} needs the {receipt_key} receipt path")
        receipts[receipt_key] = ref(out, receipt_path)
    fresh = {**state, "state": to, "gate": None, "receipts": receipts,
             "history": [*state["history"], {"state": to, "revision": state["revision"],
                                             "at": float(time.time() if now is None else now)}]}
    write_state(out, fresh)
    return fresh


def set_gate(out: Path, state: dict[str, Any], gate: dict[str, Any] | None) -> dict[str, Any]:
    fresh = {**state, "gate": gate}
    write_state(out, fresh)
    return fresh


def restart_revision(out: Path, state: dict[str, Any], rejected: dict[str, Any], *, now: float | None = None) -> dict:
    """Sau reject: về ``planned`` với revision mới; hash bị reject được giữ lại trong state (A9)."""
    revision = int(state["revision"]) + 1
    fresh = {**state, "state": STATES[0], "revision": revision, "gate": None,
             "receipts": {"plan": state["receipts"]["plan"]}, "rejected": [*state["rejected"], rejected],
             "history": [*state["history"], {"state": STATES[0], "revision": revision,
                                             "at": float(time.time() if now is None else now)}]}
    write_state(out, fresh)
    return fresh


def next_number(folder: Path) -> int:
    folder = Path(folder)
    return (len(list(folder.glob("*.json"))) if folder.is_dir() else 0) + 1


__all__ = ["STATES", "NEXT_STATE", "rev", "shot_dir", "read_plan", "require_plan_of", "read_state", "write_state",
           "ref", "ref_path", "verify_ref", "new_state", "advance", "set_gate", "restart_revision", "next_number"]
