"""Read-only views of ComfyUI ``/queue`` and ``/history`` payloads.

A ComfyUI prompt record is ``[number, prompt_id, graph, extra_data, outputs_to_execute]``;
it appears in queue lists and (as ``entry["prompt"]``) in history entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import canonical_sha256
from .graph_identity import as_sha_set, graph_shas


@dataclass(frozen=True)
class PromptRecord:
    prompt_id: str
    graph_sha256: str  # canonical ascii sha of the recorded graph
    client_id: str | None
    location: str  # "queue_running" | "queue_pending" | "history"
    identity_shas: frozenset[str] = frozenset()  # graph_identity.graph_shas of the recorded graph

    def matches(self, wanted: str | frozenset[str]) -> bool:
        """True if ``wanted`` (a submitted graph's sha, or ``graph_identity.wanted_shas`` of it) names
        this record's graph."""
        return bool(as_sha_set(wanted) & ({self.graph_sha256} | self.identity_shas))


def _is_record(item: object) -> bool:
    return (isinstance(item, list) and len(item) >= 4 and isinstance(item[1], str)
            and isinstance(item[2], dict) and isinstance(item[3], dict))


def prompt_records(value: object, location: str) -> list[PromptRecord]:
    """Every prompt record nested anywhere in ``value``."""
    found: list[PromptRecord] = []

    def visit(item: object) -> None:
        if _is_record(item):
            found.append(PromptRecord(
                prompt_id=item[1], graph_sha256=canonical_sha256(item[2], mode="ascii"),
                identity_shas=graph_shas(item[2]),
                client_id=item[3].get("client_id"), location=location))
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def queue_records(queue: object) -> list[PromptRecord]:
    if not isinstance(queue, dict):
        raise Uncertain("GET /queue did not return a JSON object")
    return [r for key in ("queue_running", "queue_pending")
            for r in prompt_records(queue.get(key) or [], key)]


def queue_counts(queue: object) -> tuple[int, int]:
    if not isinstance(queue, dict):
        raise Uncertain("GET /queue did not return a JSON object")
    return len(queue.get("queue_running") or []), len(queue.get("queue_pending") or [])


def may_submit(queue: object, *, max_pending: int = 0, allow_running: bool = True,
               strict_idle: bool = False) -> bool:
    """Allow one running prompt and no pending prompts by default."""
    if max_pending < 0:
        raise ValueError("max_pending cannot be negative")
    running, pending = queue_counts(queue)
    return running <= (0 if strict_idle or not allow_running else 1) and pending <= (0 if strict_idle else max_pending)


def require_idle(queue: object, *, max_pending: int = 0, allow_running: bool = True,
                 strict_idle: bool = False) -> None:
    """Invariant I2: at most one running prompt and no pending prompts before dispatch."""
    if not may_submit(queue, max_pending=max_pending, allow_running=allow_running, strict_idle=strict_idle):
        running, pending = queue_counts(queue)
        raise Refused(f"ComfyUI queue is busy (running={running}, pending={pending}); no dispatch")


def queue_prompt_ids(queue: object) -> set[str]:
    return {record.prompt_id for record in queue_records(queue)}
