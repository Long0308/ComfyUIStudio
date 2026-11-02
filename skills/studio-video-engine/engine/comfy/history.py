"""Bind a ComfyUI /history entry to the exact graph we submitted (invariant I4).

An entry is accepted only if it is the single entry for our prompt_id, its
prompt graph equals the submitted graph and its client_id matches, and its
status is ``success`` with ``completed`` true.  Graph equality compares
canonical bytes of the identity form (``graph_identity``): an integral float that
ComfyUI recorded for an int widget (16.0 for 16) is the same number, while
``true``/``1`` and ``16``/``16.5`` are NOT conflated.
"""

from __future__ import annotations

from typing import Any

from ..core.errors import Failed, Uncertain
from .graph_identity import as_sha_set, graph_shas, same_graph


def history_entries(value: object) -> list[dict[str, Any]]:
    """Every dict carrying a ComfyUI ``prompt`` record
    ``[number, prompt_id, graph, extra, ...]``, wherever it is nested."""
    found: list[dict[str, Any]] = []

    def visit(item: object) -> None:
        if isinstance(item, dict):
            prompt = item.get("prompt")
            if (
                isinstance(prompt, list)
                and len(prompt) >= 4
                and isinstance(prompt[1], str)
                and isinstance(prompt[2], dict)
                and isinstance(prompt[3], dict)
            ):
                found.append(item)
                return
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def _same_graph(left: object, right: object) -> bool:
    return same_graph(left, right)


def select_bound_entry(
    value: object,
    *,
    prompt_id: str,
    client_id: str,
    graph: dict[str, Any] | None = None,
    graph_sha256: str | frozenset[str] | None = None,
    label: str = "history",
) -> dict[str, Any]:
    """Return the entry for the prompt we POSTed, verified and completed.

    Binding order (matches the v004 executor): select by ``prompt_id`` first;
    exactly one entry must carry it (none or several: Uncertain).  Then that
    entry's graph (canonical bytes) and client_id must equal what we submitted
    (otherwise Uncertain).  Finally status must be success and completed
    (missing status: Uncertain; not successful: Failed).  A different prompt
    that merely carries the same graph is never returned.

    Name the expected graph either as the graph itself (``graph``) or, when only a receipt
    survives, by its canonical-ascii sha (``graph_sha256``); exactly one of the two.
    """
    if (graph is None) == (graph_sha256 is None):
        raise ValueError("pass exactly one of graph / graph_sha256")
    matches = [e for e in history_entries(value) if e["prompt"][1] == prompt_id]
    if len(matches) != 1:
        raise Uncertain(
            f"{label} must hold exactly one entry for prompt {prompt_id}; "
            f"found {len(matches)}"
        )
    entry = matches[0]
    if entry["prompt"][3].get("client_id") != client_id:
        raise Uncertain(f"{label} prompt {prompt_id} has a different client_id")
    recorded = entry["prompt"][2]
    same = (_same_graph(recorded, graph) if graph is not None
            else bool(as_sha_set(graph_sha256) & graph_shas(recorded)))
    if not same:
        raise Uncertain(f"{label} prompt {prompt_id} carries a different graph")
    status = entry.get("status")
    if not isinstance(status, dict):
        raise Uncertain(f"{label} entry has no status object")
    if status.get("status_str") != "success" or status.get("completed") is not True:
        raise Failed(f"{label} entry did not complete successfully: {status}")
    return entry
