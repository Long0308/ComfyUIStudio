"""Chép queue + ghi batch đã lọc vào run dir (tách khỏi ``library_run``; không đổi hành vi)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_bytes, sha256_file, write_once
from . import codex_queue, library_plan


def referenced_queues(plan: dict[str, Any]) -> list[Path]:
    """Queue mà plan nêu (``queue.path`` và ``queues[*].path`` nếu có)."""
    rows = [plan.get("queue")] + list(plan.get("queues") or [])
    return [Path(r["path"]) for r in rows if isinstance(r, dict) and r.get("path")]


def _carry_ownership(ctx: dict[str, Any], copies: list[dict[str, str]]) -> None:
    """Queue domain-less của episode (nằm dưới staging của nó) chép ra run dir: kèm sidecar để lane không mất bằng chứng sở hữu."""
    if not ctx.get("episode"):
        return
    from ..layout.context import load_context
    episode_ctx = load_context(str(ctx["episode"]), ctx.get("machine"))
    for copy in copies:
        codex_queue.write_owner_sidecar(episode_ctx, Path(copy["source"]), Path(copy["copy"]))


def _copy_queues(queue_dir: Path, batches_dir: Path, referenced: list[Path] | None = None, rev: str | None = None) -> list[dict[str, str]]:
    """Chép đúng queue plan nêu; glob ``queue-*.json`` chỉ là dự phòng khi plan không nêu queue nào.

    Cổng N52 (``codex_queue``) chỉ nhìn ``queue-*.json`` cạnh batch, nên queue tên khác được chép với tên ``queue-<rev>.json``."""
    copies = []
    sources = [Path(p) for p in (referenced or [])] or sorted(queue_dir.glob("queue-*.json"))
    for queue in sources:
        if not queue.is_file():
            raise Refused(f"queue {queue} named by the plan has gone: re-plan")
        payload = queue.read_bytes()
        name = queue.name if library_plan.QUEUE_NAME.match(queue.name) else f"queue-{rev or queue.stem}.json"
        target = batches_dir / name
        write_once(target, payload)
        copies.append({"source": queue.as_posix(), "copy": target.as_posix(), "sha256": sha256_bytes(payload)})
    if not copies:
        raise Refused(f"no queue-*.json next to the batches in {queue_dir}: the plan's queue has gone")
    return copies


def _write_filtered_batch(batches_dir: Path, row: dict[str, Any]) -> Path:
    source = Path(row["source"])
    if not source.is_file() or sha256_file(source) != row["source_sha256"]:
        raise Refused(f"batch file {source} changed or vanished since the plan ({row['batch_id']}): re-plan")
    keep = set(row["remaining"])
    items = [item for item in read_json(source) if isinstance(item, dict) and item.get("prompt_id") in keep]
    target = batches_dir / f"{row['batch_id']}.json"
    write_once(target, json.dumps(items, ensure_ascii=False, indent=1).encode("utf-8"))
    return target
