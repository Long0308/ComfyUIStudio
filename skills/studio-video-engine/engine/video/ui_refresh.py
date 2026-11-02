"""Tự làm mới dữ liệu panel ``jjv/video-ui-state/v1`` sau khi một verb stage ghi receipt.

Opt-in theo episode: chỉ episode có file target ``<episode root>/engine/ui-state-target.json``
(``jjv/ui-state-target/v1``, ``enabled: true``) mới được làm mới; episode không có file ⇒ không đụng gì.  Target khai các
tham số của ``jjv video ui-state`` (``out`` là file dữ liệu panel).  Ghi atomic (temp + ``os.replace``, ``ui_state.write``);
lỗi làm mới KHÔNG làm hỏng verb gốc (trả ``refreshed: false`` + lý do).  Code không nêu tên domain nào.
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

from ..core.errors import EngineError, Refused
from ..core.io import read_json
from ..layout.context import REPO_ROOT, Context, load_context
from . import ui_state

TARGET_SCHEMA = "jjv/ui-state-target/v1"
TARGET_FILE = "ui-state-target.json"
REFRESH_STAGES = ("video", "h3", "captions")  # stage verb ghi receipt mà panel hiển thị
SKIP_VERBS = ("ui-state",)


def target_path(ctx: Context) -> Path:
    return ctx.root / "engine" / TARGET_FILE


def _abs(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def load_target(ctx: Context) -> dict[str, Any] | None:
    """Target của episode, hoặc ``None`` khi chưa đăng ký / tắt; file sai schema hoặc sai episode ⇒ Refused."""
    path = target_path(ctx)
    if not path.is_file():
        return None
    target = read_json(path)
    if not isinstance(target, dict) or target.get("schema") != TARGET_SCHEMA:
        raise Refused(f"{path}: not a {TARGET_SCHEMA} document")
    if target.get("episode_id") not in (None, ctx.episode_id):
        raise Refused(f"{path}: target belongs to episode {target.get('episode_id')!r}, not {ctx.episode_id!r}")
    if target.get("enabled") is not True:
        return None
    for key in ("out", "shotlist"):
        if not isinstance(target.get(key), str) or not target[key]:
            raise Refused(f"{path}: target needs a `{key}` path")
    return target


def refresh(ctx: Context) -> dict[str, Any]:
    """Dựng lại và ghi atomic file dữ liệu panel của episode; không có target ⇒ ``refreshed: false`` và KHÔNG ghi gì."""
    target = load_target(ctx)
    if target is None:
        return {"refreshed": False, "reason": "no enabled ui-state target for this episode"}
    h3_dirs = [_abs(d) for d in target.get("h3_dirs") or []]
    for pattern in target.get("h3_dir_globs") or []:
        h3_dirs += [Path(p) for p in sorted(glob.glob(str(_abs(pattern)))) if Path(p).is_dir()]
    pipeline = target.get("pipeline")
    if isinstance(pipeline, dict):
        pipeline = {**pipeline, "video_out": target.get("video_out"),
                    "episode_arg": pipeline.get("episode_arg") or str(target_path(ctx).parent / "episode.json")}
    opt = lambda key: _abs(target[key]) if target.get(key) else None  # noqa: E731
    document = ui_state.build(
        ctx, shotlist=_abs(target["shotlist"]), video_out=opt("video_out"), h3_dirs=list(dict.fromkeys(h3_dirs)),
        receipts={k: _abs(v) for k, v in (target.get("receipts") or {}).items()}, shots_doc=opt("shots_doc"),
        wardrobe=opt("wardrobe"), anchor_dir=opt("anchor_dir"), pipeline=pipeline)
    digest = ui_state.write(document, _abs(target["out"]))
    if target.get("index"):
        ui_state.upsert_index(_abs(target["index"]), episode=ctx.episode_id, domain=ctx.domain_id,
                              file=_abs(target["out"]).name, label=target.get("label"))
    return {"refreshed": True, "out": str(_abs(target["out"])), "sha256": digest, "counts": document["counts"]}


def refresh_after(stage: str, verb: str | None, episode: str | None, machine: str | None = None, dry_run: bool = False) -> dict[str, Any] | None:
    """Gọi sau một verb stage: chỉ ``REFRESH_STAGES`` (không phải ``ui-state``, không ``--dry-run``); không bao giờ ném lỗi."""
    if stage not in REFRESH_STAGES or verb in SKIP_VERBS or dry_run or not episode:
        return None
    try:
        return refresh(load_context(episode, machine))
    except EngineError as error:
        return {"refreshed": False, "error": str(error)}
    except Exception as error:  # noqa: BLE001 - làm mới panel không được làm hỏng verb gốc
        return {"refreshed": False, "error": f"{type(error).__name__}: {error}"}


__all__ = ["TARGET_SCHEMA", "TARGET_FILE", "REFRESH_STAGES", "target_path", "load_target", "refresh", "refresh_after"]
