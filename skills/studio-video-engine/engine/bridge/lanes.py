"""Codex-exec tasks (N takes of ONE confirmed prompt, or one take per prompt of up to 10 prompts) dealt over the
allow-listed account lanes (one thread per label, so at most one take per label runs at a time).

Each take is a full ``codex.submit_library_batch`` call pinned to its lane's label (``--account``), so the per-label
lock, cooling and receipts are the engine's.  A lane that fails (quota, auth, timeout, refusal) stops and records why;
its unfinished task goes back to the queue for a healthy lane (no lane left => that item is `failed`).  Every receipt-bound PNG is copied write-once into ``<comfy input>/codex-lane/<job_id>/``.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ..comfy.settings import settings_from_machine
from ..core.errors import EngineError, Uncertain
from ..core.io import read_json, sha256_file, write_once
from ..images import codex, pool
from ..layout.context import Context
from .config import BridgeConfig
from .jobs import JobStore

INPUT_SUBDIR = "codex-lane"


def _land(store: JobStore, job_id: str, index: int, take: dict[str, Any], input_dir: Path, label: str,
          task: dict[str, Any]) -> None:
    receipt_path = Path(take["receipt"])
    receipt = read_json(receipt_path)
    source, digest = Path(receipt["output"]["path"]), str(take["candidate_sha256"])
    if sha256_file(source) != digest:
        raise Uncertain(f"{source} no longer hashes to its receipt ({digest}); not copied")
    relpath = f"{INPUT_SUBDIR}/{job_id}/{index:02d}_{digest[:12]}.png"
    target = input_dir / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    if write_once(target, source.read_bytes()) != digest:
        raise Uncertain(f"copy into the ComfyUI input folder did not reproduce {digest}: {target}")
    row = {"index": index, "path": target.as_posix(), "input_relpath": relpath, "sha256": digest,
           "receipt": receipt_path.as_posix(), "library_png": source.as_posix(), "account_label": label,
           "take": take.get("take"), "runtime_id": take.get("runtime_id"), "prompt_index": task.get("prompt_index"),
           "prompt_id": task.get("prompt_id"), "prompt_sha256": task.get("prompt_sha256")}

    def add(doc: dict[str, Any]) -> None:
        doc.setdefault("images", []).append(row)
        doc["images"].sort(key=lambda r: r["index"])
        for item in doc.get("items") or []:
            if item["index"] == index:
                item.update(status="done", lane=label, output_sha256=digest, receipt=receipt_path.as_posix(),
                            input_relpath=relpath)

    store.update(job_id, add)


def _record_error(store: JobStore, job_id: str, label: str, error: BaseException) -> None:
    text = str(error) if isinstance(error, EngineError) else f"{type(error).__name__}: {error}"
    store.update(job_id, lambda doc: doc.setdefault("errors", []).append({"lane": label, "error": text[:800]}))


def _set_item(store: JobStore, job_id: str, index: int, **fields: Any) -> None:
    def mutate(doc: dict[str, Any]) -> None:
        for item in doc.get("items") or []:
            if item["index"] == index:
                item.update(fields)

    store.update(job_id, mutate)


def run_lanes(cfg: BridgeConfig, store: JobStore, job_id: str, ctx: Context, accounts: list[pool.Account],
              tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """``tasks``: ``{index, batch, prompt_id, prompt_sha256, prompt_index}`` in output order (index 1-based, unique)."""
    folder = store.folder(job_id)
    library_out = folder / "library"
    input_dir = settings_from_machine(ctx.machine).input_dir
    state_path = Path((ctx.machine.get("images") or {}).get("codex_state_path") or folder / "codex-pool-state.json")
    codex_cmd = cfg.codex_cmd or codex.find_codex(None, ctx.machine)
    remaining, lock = list(tasks), threading.Lock()

    def lane(account: pool.Account) -> None:
        while True:
            with lock:
                if not remaining:
                    return
                task = remaining.pop(0)
            try:
                _set_item(store, job_id, task["index"], status="running", lane=account.label)
                result = codex.submit_library_batch(ctx, library_out, Path(task["batch"]), [account], account=account.label,
                                                    codex_cmd=codex_cmd, state_path=state_path, timeout=cfg.timeout,
                                                    base_env=cfg.base_env)
                _land(store, job_id, task["index"], result["takes"][0], input_dir, account.label, task)
            except Exception as error:  # noqa: BLE001 - a lane stops on its first failure; the reason is recorded
                with lock:
                    remaining.insert(0, task)
                _set_item(store, job_id, task["index"], status="pending", lane=None)
                _record_error(store, job_id, account.label, error)
                return

    store.update(job_id, lambda doc: doc.update(lanes=[a.label for a in accounts], library_out=library_out.as_posix(),
                                                 input_dir=input_dir.as_posix(), pool_state=state_path.as_posix()))
    threads = [threading.Thread(target=lane, args=(a,), name=f"{job_id}-{a.label}", daemon=True) for a in accounts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    def close(doc: dict[str, Any]) -> None:
        for item in doc.get("items") or []:
            if item["status"] != "done":
                item.update(status="failed", lane=None, error="no healthy lane was left to run this prompt")
        made = len(doc.get("images") or [])
        doc["state"] = "done" if made == len(tasks) else ("partial" if made else "failed")
        doc["done"] = made

    return store.update(job_id, close)
