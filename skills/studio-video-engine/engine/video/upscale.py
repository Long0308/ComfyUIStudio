"""Group ``04 LÊN 1080P``: backend upscale cắm được; mặc định ``none``.

``none`` ghi ``upscale-pending.json`` và dừng ở cổng ``needs-gpu-pilot-approval``: domain chưa có recipe 1080p
được qualify thì không có gì chạy.  Backend khác chỉ được chọn khi ``routes.upscale.qualified[backend]`` của
ĐÚNG domain trỏ tới receipt qualification (path + sha256) và adapter của nó có trong :data:`REGISTRY`; recipe
SeedVR2 của domain khác không bao giờ được tra ở đây (AGENTS.md: v003 chỉ qualified cho hoạt hình).
"""

from __future__ import annotations

import inspect
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from ..comfy.staging import require_hash
from ..core.errors import Refused
from ..core.io import write_json_once
from ..core.paths import resolve_data_path
from ..core.runlock import run_pid_lock
from ..layout.context import REPO_ROOT, Context
from . import state as state_mod
from . import upscale_comfy

PENDING_FILE = "upscale-pending.json"
RECEIPT_FILE = "upscale-receipt.json"
GATE_PILOT = "needs-gpu-pilot-approval"


class UpscaleBackend(Protocol):
    name: str
    gpu: bool

    def run(self, ctx: Context, *, source: dict[str, Any], target: str, out_dir: Path, shot: str, revision: int,
            gpu_approval: dict[str, Any] | None, comfy: Any = None, render_receipt: dict[str, Any] | None = None,
            receipt_root: Path | None = None) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class NoneBackend:
    """Không upscale: ghi ``upscale_pending`` và để scheduler dừng ở cổng pilot GPU."""

    name: str = "none"
    gpu: bool = False

    def run(self, ctx: Context, *, source: dict[str, Any], target: str, out_dir: Path, shot: str, revision: int,
            gpu_approval: dict[str, Any] | None, **_: Any) -> dict[str, Any] | None:
        body = {"schema": state_mod.UPSCALE_PENDING_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
                "shot": shot, "revision": revision, "backend": self.name, "source": source, "target": target,
                "status": "upscale_pending", "gate": GATE_PILOT,
                "reason": f"domain {ctx.domain_id!r} has no qualified 1080p recipe; a user-authorised GPU pilot and a "
                          "qualification receipt listed in recipes/video routes upscale.qualified are required",
                "next": "run this domain's own upscale pilot with the user's approval, record its qualification "
                        "receipt in routes upscale.qualified[<backend>], then re-run `jjv video run --completion "
                        "--upscale-backend <backend> --gpu-approved <receipt>`"}
        write_json_once(Path(out_dir) / PENDING_FILE, body, mode="utf8")
        return None


@dataclass(frozen=True)
class UnqualifiedBackend:
    """Mọi backend không phải ``none`` mà domain chưa qualify: từ chối, không gửi gì."""

    name: str
    gpu: bool = True

    def run(self, ctx: Context, **_: Any) -> dict[str, Any] | None:
        raise Refused(f"UPSCALE_UNQUALIFIED: backend {self.name!r} has no qualification receipt for domain "
                      f"{ctx.domain_id!r} in the video routes (upscale.qualified); a recipe qualified for another "
                      "domain is never reused; nothing was sent")


# Adapter của backend đã qualify: name -> factory(qualification entry) -> backend.  Có adapter KHÔNG có nghĩa là
# qualified: chưa có pilot 1080p nào của domain live-action được nghiệm thu, routes ``qualified`` vẫn rỗng.
REGISTRY: dict[str, Callable[[dict[str, Any]], UpscaleBackend]] = {upscale_comfy.NAME: upscale_comfy.ComfyRealEsrgan1080}


def select_backend(ctx: Context, route: dict[str, Any], name: str | None, repo_root: Path = REPO_ROOT) -> UpscaleBackend:
    policy = route["upscale"]
    chosen = name or policy["default_backend"]
    if chosen not in policy["backends"]:
        raise Refused(f"upscale backend {chosen!r} is not one of {policy['backends']}")
    if chosen == "none":
        return NoneBackend()
    entry = (policy.get("qualified") or {}).get(chosen)
    if not isinstance(entry, dict):
        return UnqualifiedBackend(chosen)
    if not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
        raise Refused(f"video routes: upscale.qualified[{chosen!r}] needs a receipt path + sha256")
    given = Path(entry["path"])
    receipt = resolve_data_path(given if given.is_absolute() else repo_root / given)
    require_hash(receipt, entry["sha256"], f"upscale qualification receipt {chosen}")
    factory = REGISTRY.get(chosen)
    if factory is None:
        raise Refused(f"UPSCALE_NOT_IMPLEMENTED: backend {chosen!r} is qualified for {ctx.domain_id!r} but this engine "
                      "version has no adapter for it; nothing was sent")
    route_policy = {key: policy.get(key) for key in ("crop_mode",)}  # khung hình do route/user chọn, không default
    return factory({**entry, "path": str(receipt), "route": route_policy})


def upscale(ctx: Context, out: Path, state: dict[str, Any], route: dict[str, Any], *, backend_name: str | None,
            gpu_approval: dict[str, Any] | None, lock_path: Path | None = None, comfy: Any = None,
            render_receipt: dict[str, Any] | None = None) -> tuple[str, Path | None]:
    """``("done", receipt path)`` hoặc ``("pending", pending path)``; mọi từ chối trước mọi ghi.

    Backend GPU chạy dưới khoá EXECUTOR máy ``lock_path`` (``ComfySettings.executor_lock_path``: cùng khoá của
    ``seedvr2 execute`` / ``h3 submit`` / ``video render``), giữ suốt job; thiếu khoá ⇒ Refused, không chạy."""
    render = state_mod.verify_ref(out, state["receipts"].get("render"), "render")
    if render_receipt is not None and render_receipt != render:
        raise Refused("RENDER_RECEIPT_MISMATCH: supplied render document is not the current receipt; nothing was sent")
    source = dict(render["native"])
    require_hash(Path(source["path"]), source["sha256"], "native take")
    backend = select_backend(ctx, route, backend_name)
    if backend.gpu and gpu_approval is None:
        raise Refused(f"GPU_APPROVAL_MISSING: upscale backend {backend.name!r} uses the GPU; pass --gpu-approved "
                      "<receipt or token from the user>; nothing was sent")
    if backend.gpu and lock_path is None:
        raise Refused(f"GPU_LOCK_MISSING: upscale backend {backend.name!r} uses the GPU but no machine executor lock "
                      "path was given (machine.gpu_lock_path); nothing was sent")
    out_dir = state_mod.shot_dir(out, state["shot"]) / "upscale" / state_mod.rev(state["revision"])
    lock = (run_pid_lock(Path(lock_path), report_dir=out_dir.parent, scope="machine",
                         extra={"stage": "video-upscale", "shot": state["shot"], "revision": state["revision"],
                                "backend": backend.name})
            if backend.gpu else nullcontext())
    needs_handles = backend.gpu and not isinstance(backend, UnqualifiedBackend)  # chưa qualify: từ chối đúng tên trước
    if needs_handles and comfy is None:
        raise Refused("NO_COMFY_HANDLES: GPU upscale needs injected ComfyHandles (machine.json comfy + gpu_lock_path); "
                      "nothing was sent")
    if needs_handles and Path(lock_path).resolve() != Path(comfy.settings.executor_lock_path).resolve():
        raise Refused("GPU_LOCK_MISMATCH: lock must be the injected machine executor lock; nothing was sent")
    extra = {"comfy": comfy, "render_receipt": render, "receipt_root": Path(out).resolve()}
    accepted = inspect.signature(backend.run).parameters  # chỉ backend KHAI TÊN keyword mới mới nhận (test double cũ không)
    extra = {key: value for key, value in extra.items() if key in accepted}
    with lock:
        receipt = backend.run(ctx, source=source, target=route["upscale"]["target"], out_dir=out_dir,
                              shot=state["shot"], revision=state["revision"], gpu_approval=gpu_approval, **extra)
    if receipt is None:
        return "pending", out_dir / PENDING_FILE
    for key in ("output", "backend"):
        if key not in receipt:
            raise Refused(f"{state['shot']}: upscale backend {backend.name!r} returned no {key}")
    if receipt.get("source", {}).get("sha256") != source["sha256"]:
        raise Refused(f"{state['shot']}: upscale receipt source sha256 is not this shot's native take (A8)")
    body = {"schema": state_mod.UPSCALE_RECEIPT_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
            "shot": state["shot"], "revision": state["revision"], "target": route["upscale"]["target"],
            "gpu_approval": gpu_approval, "render_receipt": state["receipts"]["render"]}
    body = {**receipt, **body}  # envelope của wrapper thắng: adapter không ghi đè shot/target/episode được
    path = out_dir / RECEIPT_FILE
    write_json_once(path, body, mode="utf8")
    return "done", path


__all__ = ["UpscaleBackend", "NoneBackend", "UnqualifiedBackend", "REGISTRY", "select_backend", "upscale",
           "PENDING_FILE", "RECEIPT_FILE", "GATE_PILOT"]
