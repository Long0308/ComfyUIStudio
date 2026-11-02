"""Lost-prompt classification and the receipts that go with it (task T-E30).

Incident 2026-10-27: ComfyUI aborted with a CUDA fault, Docker restarted the container, and the
prompt the executor was waiting for no longer existed.  Resubmitting without proof is forbidden
(invariant I3), so the run hung.  This module supplies the proof.

A dispatched prompt is **LOST** only if ALL of these hold:

1. the container's current ``StartedAt`` DIFFERS from the ``StartedAt`` recorded in the dispatch intent
   before the POST (it is a different container instance now: it restarted since).  The two values
   are compared only with each other: the host clock is never compared with the Docker VM clock;
2. the prompt is absent from ``/history`` and ``/queue`` in two consecutive checks, a few seconds
   apart;
3. no output file carrying the chunk's output prefix exists in the ComfyUI output folder.

Condition 1 failing is ``NOT_LOST`` (the container never restarted, so the prompt cannot have been
wiped by one).  Any condition that cannot be established (docker unreadable, container not
running, no ``StartedAt`` recorded at dispatch, ComfyUI unreachable, output folder root missing or
unreadable) is ``UNCERTAIN``.  Both mean: never
resubmit.  Nothing here POSTs, and nothing here touches a container.
"""

from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..core.errors import EngineError, Uncertain
from ..core.io import sha256_file, write_json_atomic
from .client import ComfyClient
from .docker_probe import ContainerProbe
from .queue import prompt_records, queue_records

LOST, NOT_LOST, UNCERTAIN = "LOST", "NOT_LOST", "UNCERTAIN"
LOST_SCHEMA = "jjv/lost-prompt/v1"
INCIDENT_SCHEMA = "jjv/incident/v1"
LOST_RECEIPT = "LOST.json"
INCIDENT_FILE = "INCIDENT.json"
EXHAUSTED_RECEIPT = "LOST-retries-exhausted.json"
ARCHIVE_PREFIX = "abandoned-lost-"
LEDGER_FILE = "LOST-LEDGER.jsonl"  # append-only, run-wide (beside run-state.json), one row per archive made
LEDGER_SCHEMA = "jjv/lost-ledger/v1"


@dataclass(frozen=True)
class Classification:
    verdict: str  # LOST | NOT_LOST | UNCERTAIN
    reasons: tuple[str, ...]
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def lost(self) -> bool:
        return self.verdict == LOST

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "reasons": list(self.reasons), **self.evidence}


class LostPrompt(Uncertain):
    """Raised by the wait path when the awaited prompt is proven LOST; the executor decides what next.

    Exit code 2 (Uncertain) if it ever escapes: it is never a success and never a refusal.
    """

    def __init__(self, message: str, *, classification: Classification) -> None:
        super().__init__(message, evidence={"stage": "lost_prompt", "classification": classification.as_dict()})
        self.classification = classification


def outputs_with_prefix(output_dir: Path, prefix: str) -> list[dict[str, Any]]:
    """Files in the ComfyUI output folder that carry ``prefix`` (``sub/dir/name`` -> ``name*``).

    The output ROOT must be a readable directory: a missing or non-directory root (unmounted drive, wrong
    path) is an ``OSError``, never "no files" (absence can only be proven against a root that is there).
    Only ``FileNotFoundError`` on the prefix sub-folder under a readable root is a genuine empty result;
    every other ``OSError`` (access denied, ...) propagates, because ``Path.is_dir()`` would swallow it
    and an unreadable folder would read as "no output".
    """
    root = Path(output_dir)
    if not stat.S_ISDIR(os.stat(root).st_mode):  # FileNotFoundError / PermissionError / ... propagate
        raise NotADirectoryError(f"ComfyUI output root is not a readable directory: {root}")
    subfolder, _, name = prefix.rpartition("/")
    folder = root / subfolder if subfolder else root
    try:
        folder_mode = os.stat(folder).st_mode
    except FileNotFoundError:
        return []
    if not stat.S_ISDIR(folder_mode):
        raise NotADirectoryError(f"ComfyUI output prefix folder is not a directory: {folder}")
    return [{"name": item.name, "bytes": item.stat().st_size}
            for item in sorted(folder.iterdir()) if item.is_file() and item.name.startswith(name)]


def _snapshot(client: ComfyClient, prompt_id: str | None, graph_sha256: str | None,
              client_id: str | None, history_max_items: int, clock: Callable[[], float]) -> dict[str, Any]:
    """What /history and /queue say about the prompt now (raises ``ComfyError`` on a bad read)."""
    queue = client.get("/queue")
    records = queue_records(queue)
    snap: dict[str, Any] = {"at": clock(), "queue_running": len(queue.get("queue_running") or []),
                            "queue_pending": len(queue.get("queue_pending") or [])}
    if prompt_id:
        value = client.get("/history/" + prompt_id)
        in_history = isinstance(value, dict) and prompt_id in value
        in_queue = any(r.prompt_id == prompt_id for r in records)
    else:  # no prompt id on file: the intent's exact graph + client_id stand in for it
        history = prompt_records(client.get(f"/history?max_items={history_max_items}"), "history")
        in_history = any(r.matches(graph_sha256) and r.client_id == client_id for r in history)
        in_queue = any(r.matches(graph_sha256) and r.client_id == client_id for r in records)
    snap.update(in_history=bool(in_history), in_queue=bool(in_queue))
    return snap


def classify_lost(*, client: ComfyClient, probe: ContainerProbe, container: str, dispatch_time: float,
                  output_dir: Path, output_prefix: str, dispatch_instance: dict[str, Any] | None = None,
                  prompt_id: str | None = None,
                  graph_sha256: str | frozenset[str] | None = None, client_id: str | None = None,
                  recheck_seconds: float = 5.0, history_max_items: int = 200,
                  sleep: Callable[[float], None] = time.sleep,
                  clock: Callable[[], float] = time.time) -> Classification:
    """Apply the three conditions above.  Never raises for an unreadable source: that is UNCERTAIN.

    ``dispatch_instance`` is the ``container_instance`` record the dispatch wrote into the intent before
    the POST (``{"started_at_text": ...}``); ``dispatch_time`` is kept as evidence only.
    """
    if not prompt_id and not (graph_sha256 and client_id):
        raise ValueError("classify_lost needs a prompt_id or graph_sha256 + client_id")
    evidence: dict[str, Any] = {"prompt_id": prompt_id, "dispatch_time": dispatch_time,
                                "container": container, "output_prefix": output_prefix}
    state = probe.state(container)
    if state is None:
        return Classification(UNCERTAIN, ("container state unreadable (docker inspect failed)",), evidence)
    recorded = str((dispatch_instance or {}).get("started_at_text") or "").strip()
    evidence["dispatch_container_started_at_text"] = recorded or None
    evidence["container_started_at"] = state.started_at
    evidence["container_started_at_text"] = state.started_at_text
    evidence["container_running"] = state.running
    evidence["container_restart_count"] = state.restart_count
    if not state.running:
        return Classification(UNCERTAIN, ("container is not running",), evidence)
    if not recorded:
        return Classification(UNCERTAIN, ("no container StartedAt was recorded when this chunk was dispatched; "
                                          "a restart cannot be proven without it (the host clock is never "
                                          "compared with the Docker VM clock)",), evidence)
    if state.started_at_text.strip() == recorded:
        return Classification(NOT_LOST, ("container has not restarted since the dispatch "
                                         f"(StartedAt unchanged: {state.started_at_text})",), evidence)
    snapshots: list[dict[str, Any]] = []
    evidence["snapshots"] = snapshots
    for check in range(2):
        if check:
            sleep(recheck_seconds)
        try:
            snap = _snapshot(client, prompt_id, graph_sha256, client_id, history_max_items, clock)
        except EngineError as error:
            return Classification(UNCERTAIN, (f"ComfyUI unreadable during check {check + 1}: {error}",), evidence)
        snapshots.append(snap)
        if snap["in_history"] or snap["in_queue"]:
            where = "history" if snap["in_history"] else "queue"
            return Classification(NOT_LOST, (f"prompt is present in /{where} (check {check + 1})",), evidence)
    try:
        found = outputs_with_prefix(output_dir, output_prefix)
    except OSError as error:
        return Classification(UNCERTAIN, (f"output folder unreadable: {error!r}",), evidence)
    evidence["outputs_with_prefix"] = found
    if found:
        return Classification(NOT_LOST, (f"{len(found)} output file(s) carry the chunk prefix",), evidence)
    evidence["gpu_fault"] = probe.fault_lines(container, dispatch_time)
    return Classification(LOST, ("container restarted after dispatch (StartedAt changed from "
                                 f"{recorded} to {state.started_at_text.strip()}); prompt absent from /history and /queue "
                                 "in two checks; no output with the chunk prefix",), evidence)


# ---- receipts and archive -----------------------------------------------------------------
def count_lost_archives(chunk_dir: Path) -> int:
    chunk_dir = Path(chunk_dir)
    return sum(1 for p in chunk_dir.glob(ARCHIVE_PREFIX + "*") if p.is_dir()) if chunk_dir.is_dir() else 0


def _ledger_rows(ledger: Path | None) -> list[dict[str, Any]]:
    if ledger is None or not Path(ledger).is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = Path(ledger).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise Uncertain(f"lost-prompt ledger {ledger} is unreadable ({error!r}); the retry budget cannot be "
                        "established, so no automatic re-dispatch",
                        evidence={"stage": "lost_ledger_unreadable"}) from error
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as error:
            raise Uncertain(f"lost-prompt ledger {ledger} line {number} is not JSON; the retry budget cannot be "
                            "established", evidence={"stage": "lost_ledger_unreadable"}) from error
        if not isinstance(row, dict):
            raise Uncertain(f"lost-prompt ledger {ledger} line {number} is not an object",
                            evidence={"stage": "lost_ledger_unreadable"})
        rows.append(row)
    return rows


def lost_retries_used(chunk_dir: Path, ledger: Path | None, shot_id: str, chunk: str) -> int:
    """Automatic re-dispatches already spent on a chunk: ``max(ledger rows, abandoned-lost-* folders)``.

    The ledger is appended when an archive is made and is never rewritten, so deleting an archive folder
    cannot hand the chunk a fresh budget.  A ledger that counts MORE archives than exist on disk means
    evidence was removed: ``Uncertain`` (stage ``lost_ledger_mismatch``), never a silent reset.
    """
    folders = count_lost_archives(chunk_dir)
    recorded = sum(1 for row in _ledger_rows(ledger) if row.get("shot_id") == shot_id and row.get("chunk") == chunk)
    if recorded > folders:
        raise Uncertain(f"{shot_id}/{chunk}: the lost-prompt ledger records {recorded} archived attempt(s) but "
                        f"only {folders} {ARCHIVE_PREFIX}* folder(s) exist; evidence was removed. Restore it or "
                        f"inspect by hand; the ledger {ledger} is append-only and is never edited by the engine",
                        evidence={"stage": "lost_ledger_mismatch", "ledger_rows": recorded,
                                  "archive_folders": folders})
    return max(recorded, folders)


def _append_ledger(ledger: Path, row: dict[str, Any]) -> None:
    ledger = Path(ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
    fd = os.open(ledger, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def lost_receipt(classification: Classification, *, identity: dict[str, Any], retries_before: int,
                 max_lost_retries: int, decision: str, clock: Callable[[], float]) -> dict[str, Any]:
    return {"schema": LOST_SCHEMA, "status": "LOST", "recorded_at": clock(), "identity": identity,
            "classification": classification.as_dict(), "retries_before": retries_before,
            "max_lost_retries": max_lost_retries, "decision": decision}


def _describe(path: Path) -> dict[str, Any]:
    if path.is_dir():
        files = [{"name": str(p.relative_to(path)), "bytes": p.stat().st_size, "sha256": sha256_file(p)}
                 for p in sorted(path.rglob("*")) if p.is_file()]
        return {"name": path.name, "kind": "dir", "files": files}
    return {"name": path.name, "kind": "file", "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def archive_lost_attempt(chunk_dir: Path, receipt: dict[str, Any], clock: Callable[[], float], *,
                         ledger: Path | None = None, shot_id: str | None = None,
                         chunk: str | None = None) -> Path:
    """Move this chunk's attempt state into ``abandoned-lost-<ts>/`` (with LOST.json + INCIDENT.json).

    Everything in the chunk folder except earlier ``abandoned-*`` folders moves (job.json,
    dispatch-intent.json, submitted.json, history/telemetry, output/ and core/), so the folder is
    clean for exactly one re-dispatch.  Nothing is deleted; the archive keeps the hashes.  When ``ledger``
    is given, one row is appended to it right after the archive folder is created (before anything moves),
    so an interrupted archive still counts against the retry budget.
    """
    chunk_dir = Path(chunk_dir)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(clock()))
    target, n = chunk_dir / f"{ARCHIVE_PREFIX}{stamp}", 1
    while target.exists():
        n += 1
        target = chunk_dir / f"{ARCHIVE_PREFIX}{stamp}-{n}"
    target.mkdir(parents=True)
    if ledger is not None:
        _append_ledger(ledger, {"schema": LEDGER_SCHEMA, "shot_id": shot_id, "chunk": chunk,
                                "archive": target.name, "archived_at": clock(),
                                "decision": receipt.get("decision")})
    moved = []
    for item in sorted(chunk_dir.iterdir()):
        if item == target or item.name.startswith("abandoned-"):
            continue
        moved.append(_describe(item))
        os.replace(item, target / item.name)
    write_json_atomic(target / LOST_RECEIPT, receipt, mode="ascii")
    write_json_atomic(target / INCIDENT_FILE, {
        "schema": INCIDENT_SCHEMA, "kind": "lost_prompt", "archived_at": clock(),
        "reason": receipt["classification"]["reasons"], "archived": moved, "lost_receipt": LOST_RECEIPT,
        "gpu_fault": receipt["classification"].get("gpu_fault"),
        "next_action": "the executor re-dispatches this chunk once per max_lost_retries; this folder is evidence"},
        mode="ascii")
    return target
