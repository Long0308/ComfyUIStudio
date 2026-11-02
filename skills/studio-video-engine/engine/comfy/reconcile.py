"""Find what became of a dispatch intent (invariant I3).  Never POSTs; the ONLY write is
``record_reconciled`` (an immutable, timestamp-free ``reconciled.json``, which counts as post
evidence for its receipt dir).

A prompt belongs to an intent only if BOTH the canonical sha of its recorded graph and its
client_id equal the intent's.  Several distinct matching prompts are ambiguous (``Uncertain``);
no match is reported as ``status="none"`` and the caller must STOP (never resubmit): the
prompt may simply have fallen out of the bounded history window.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.errors import Uncertain
from ..core.io import write_json_once
from .client import ComfyClient
from .queue import PromptRecord, prompt_records, queue_records

from .dispatch import RECONCILED_FILE
RECONCILED_SCHEMA = "jjv/dispatch-reconciled/v1"


class PromptAbsent(Uncertain):
    """A prompt id on file has no queue/history record at all (possibly wiped by a ComfyUI restart:
    ``engine.comfy.lost`` decides; this alone never authorises a resubmission)."""


@dataclass(frozen=True)
class Reconciled:
    status: str  # "matched" | "none"
    prompt_id: str | None
    location: str | None


def reconcile_intent(client: ComfyClient, *, graph_sha256: str | frozenset[str], client_id: str,
                     history_max_items: int = 200) -> Reconciled:
    records = queue_records(client.get("/queue")) + prompt_records(
        client.get(f"/history?max_items={history_max_items}"), "history")
    matches = [r for r in records if r.matches(graph_sha256) and r.client_id == client_id]
    ids = sorted({r.prompt_id for r in matches})
    if len(ids) > 1:
        raise Uncertain(f"multiple ComfyUI prompts match the exact graph/client of the intent: {ids}")
    if not ids:
        return Reconciled("none", None, None)
    # a prompt seen in the queue and history at once is reported where it is still live
    first = next(r for r in matches if r.location != "history") if any(
        r.location != "history" for r in matches) else matches[0]
    return Reconciled("matched", ids[0], first.location)


def verify_known_prompt(client: ComfyClient, *, prompt_id: str, graph_sha256: str | frozenset[str],
                        client_id: str) -> list[PromptRecord]:
    """A prompt id already on file must still carry the intent's graph and client_id."""
    records = [r for r in prompt_records(client.get("/history/" + prompt_id), "history")
               + queue_records(client.get("/queue")) if r.prompt_id == prompt_id]
    if not records:
        raise PromptAbsent(f"prompt {prompt_id} has no structured queue/history evidence")
    if any(not r.matches(graph_sha256) or r.client_id != client_id for r in records):
        raise Uncertain(f"prompt {prompt_id} graph/client differs from its dispatch intent")
    return records


def record_reconciled(receipt_dir: Path, *, result: Reconciled, client_id: str, graph_sha256: str) -> str:
    """Immutable, timestamp-free so a repeat reconcile is idempotent."""
    return write_json_once(Path(receipt_dir) / RECONCILED_FILE, {
        "schema": RECONCILED_SCHEMA, "prompt_id": result.prompt_id, "client_id": client_id,
        "graph_sha256": graph_sha256, "canonicalization": "ascii", "location": result.location,
    }, mode="ascii")
