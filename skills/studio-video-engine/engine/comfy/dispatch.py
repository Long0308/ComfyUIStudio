"""Guarded dispatch of one API graph to ComfyUI (invariants I1, I2, I12).

Order, all under the injected machine-wide lock::

    receipt dir unused -> pending-free queue -> history snapshot -> O_EXCL dispatch-intent -> POST

Once the intent file exists the outcome of this call is *unknowable* from the engine's point
of view, so EVERY exception from that point on is :class:`PostOutcomeUnknown` (exit 2) and the
intent stays on disk: the only legal next step is ``reconcile``, never a second POST.  A POST
answered with an HTTP error status is also treated as unknown (conservative: the engine cannot
prove nothing was queued).  The lock is released as soon as the POST has been answered; the
queued prompt keeps every other dispatcher out because they all require no pending prompt.
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..core.errors import Refused, Uncertain
from ..core.io import canonical_sha256, write_json_once
from .client import ComfyClient, ComfyError
from .graph_identity import wanted_shas
from .lock import existence_lock
from . import run_watchdog
from .queue import prompt_records, queue_records, require_idle
from .settings import ComfySettings

INTENT_SCHEMA = "jjv/dispatch-intent/v1"
SUBMITTED_SCHEMA = "jjv/dispatch-submitted/v1"
INTENT_FILE = "dispatch-intent.json"
SUBMITTED_FILE = "submitted.json"
UNKNOWN_FILE = "submit-unknown.json"
RECONCILED_FILE = "reconciled.json"  # written by engine.comfy.reconcile.record_reconciled
REFUSED_TERMINAL_FILE = "dispatch-refused-terminal.json"
REFUSED_TERMINAL_SCHEMA = "jjv/dispatch-refused-terminal/v1"
# REFUSED_TERMINAL_FILE cố ý KHÔNG nằm trong EVIDENCE_FILES: nó chứng minh KHÔNG có POST (post_attempted=false).
EVIDENCE_FILES = (INTENT_FILE, SUBMITTED_FILE, UNKNOWN_FILE, RECONCILED_FILE)
_RESERVED = frozenset({"schema", "correlation_id", "client_id", "graph_sha256", "canonicalization",
                       "created_at", "pid", "queue_before_post", "history_entries_before", "base_url",
                       "container_instance"})


class PostOutcomeUnknown(Uncertain):
    """The dispatch intent exists but the POST outcome is not known: reconcile, never resubmit."""


class GuardRefused(Refused):
    """Latch guard unusable (gate timeout, unreadable/invalid latch): nothing was POSTed (post_attempted=false)."""


class GuardRequired(Refused):
    """The run declared a terminal guard (marker ``terminal-guard-required.json``) but the caller passed none."""


class TerminalLatchRefused(Refused):
    """A terminal watchdog latch exists for this run: nothing was POSTed (post_attempted=false)."""


@dataclass(frozen=True)
class DispatchResult:
    prompt_id: str
    client_id: str
    correlation_id: str
    graph_sha256: str
    response: dict[str, Any]
    intent_path: Path
    submitted_receipt_error: str | None = None


def client_id_for(prefix: str, correlation_id: str) -> str:
    return prefix + correlation_id


def post_evidence(receipt_dir: Path) -> list[str]:
    """Names of the receipts proving a POST was attempted or answered for this receipt dir."""
    return [name for name in EVIDENCE_FILES if (Path(receipt_dir) / name).exists()]


def _used(receipt_dir: Path) -> Refused:
    found = post_evidence(receipt_dir)
    return Refused(f"receipt dir {receipt_dir} already holds post evidence {found}; "
                   "this receipt dir was used. Run reconcile; never resubmit into the same receipt dir.")


def _record_unknown(receipt_dir: Path, body: dict[str, Any]) -> str | None:
    try:
        write_json_once(receipt_dir / UNKNOWN_FILE, body, mode="ascii")
    except Exception as error:  # noqa: BLE001 - the intent is the authoritative record
        return repr(error)
    return None


def _unknown(receipt_dir: Path, client_id: str, why: str, evidence: dict[str, Any]) -> PostOutcomeUnknown:
    body = {"status": "DISPATCH_STATUS_UNKNOWN", "client_id": client_id, "why": why,
            "evidence": evidence, "next_action": "run reconcile; do not resubmit"}
    note = _record_unknown(receipt_dir, body)
    return PostOutcomeUnknown(
        f"POST outcome is unknown ({why}); the dispatch intent was kept. Run reconcile; "
        "do not resubmit", evidence={**evidence, **({"unknown_receipt_error": note} if note else {})})


def _refuse_terminal(guard: "run_watchdog.TerminalGuard", receipt_dir: Path, *, graph_sha: str, client_id: str,
                     correlation_id: str, clock: Callable[[], float], kind: type[Refused], why: str,
                     latch: dict[str, Any] | None, error: str | None) -> Refused:
    body = {"schema": REFUSED_TERMINAL_SCHEMA, "run_id": guard.run_id, "refusal": kind.__name__, "why": why,
            "latch_path": str(guard.latch_path), "latch_status": (latch or {}).get("execution_status"),
            "latch_reason": (latch or {}).get("reason"), "guard_error": error,
            "graph_sha256": graph_sha, "client_id": client_id, "correlation_id": correlation_id,
            "created_at": clock(), "post_attempted": False}
    try:
        run_watchdog.write_receipt_atomic(receipt_dir / REFUSED_TERMINAL_FILE, body)
        note = None
    except Exception as write_error:  # noqa: BLE001 - still refuse; the failure goes into the evidence
        note = repr(write_error)
    return kind(f"{why}; nothing was POSTed (the dispatch intent was kept)",
                evidence={"stage": "terminal_latch", **body, **({"refused_receipt_error": note} if note else {})})


def _check_guard(guard: "run_watchdog.TerminalGuard", stack: ExitStack, receipt_dir: Path, **ctx: Any) -> None:
    """Enter the shared gate (kept until the POST finished: ``stack``) and refuse on any latch/guard problem."""
    try:
        stack.enter_context(guard.gate())
    except Exception as error:  # noqa: BLE001 - cannot prove synchronisation => refuse
        raise _refuse_terminal(guard, receipt_dir, kind=GuardRefused, latch=None, error=repr(error),
                               why="terminal-latch gate unavailable", **ctx) from error
    try:
        latch = run_watchdog.read_latch(guard.latch_path, run_id=guard.run_id)
    except run_watchdog.LatchReadError as error:
        raise _refuse_terminal(guard, receipt_dir, kind=GuardRefused, latch=None, error=repr(error),
                               why="terminal latch unreadable/invalid", **ctx) from error
    if latch is not None:
        raise _refuse_terminal(guard, receipt_dir, kind=TerminalLatchRefused, latch=latch, error=None,
                               why=f"terminal latch {latch['execution_status']} exists for run {guard.run_id}", **ctx)


def _post_and_receipt(client: ComfyClient, graph: dict, receipt_dir: Path, *, client_id: str,
                      correlation_id: str, graph_sha: str, clock: Callable[[], float]) -> tuple[dict, str | None]:
    try:
        response = client.post("/prompt", {"prompt": graph, "client_id": client_id})
    except ComfyError as error:
        raise _unknown(receipt_dir, client_id, "POST failed", {
            "error": repr(error), "http_status": error.http_status}) from error
    prompt_id = response.get("prompt_id") if isinstance(response, dict) else None
    if not isinstance(prompt_id, str) or not prompt_id:
        raise _unknown(receipt_dir, client_id, "POST returned no prompt_id", {"response": response})
    try:
        write_json_once(receipt_dir / SUBMITTED_FILE, {
            "schema": SUBMITTED_SCHEMA, "prompt_id": prompt_id, "client_id": client_id,
            "correlation_id": correlation_id, "graph_sha256": graph_sha, "canonicalization": "ascii",
            "number": response.get("number"), "node_errors": response.get("node_errors", {}),
            "submitted_at": clock()}, mode="ascii")
    except Exception as error:  # noqa: BLE001 - the prompt IS queued; the receipt is best effort
        return response, repr(error)
    return response, None


def dispatch(client: ComfyClient, settings: ComfySettings, *, graph: dict[str, Any],
             receipt_dir: Path, identity: dict[str, Any], client_prefix: str = "jjv-",
             history_max_items: int = 200, clock: Callable[[], float] = time.time,
             container_instance: Callable[[], dict[str, Any] | None] | None = None,
             guard: "run_watchdog.TerminalGuard | None" = None,
             strict_idle: bool = False) -> DispatchResult:
    """Dispatch ``graph`` once.  Raises ``Refused`` before the intent exists, and
    :class:`PostOutcomeUnknown` (exit 2) for anything that goes wrong afterwards.

    ``container_instance`` (optional) is called under the lock right before the intent is written and its
    result is stored in the intent as ``container_instance`` (the container's ``StartedAt`` BEFORE the POST:
    the instance identity that a later lost-prompt proof compares against).  Without a usable ``started_at_text``
    (callable failed, docker unreadable) the dispatch is REFUSED before the intent is written: ``Uncertain``,
    nothing sent, because a prompt that can never be proven lost can only hang.

    ``guard`` (pilot path, v004): after the intent and right before the POST, still inside the dispatch lock, the
    shared gate is taken and the terminal latch read; the gate is held through the POST.  A latch / unusable guard
    raises :class:`TerminalLatchRefused` / :class:`GuardRefused` (``Refused``, post_attempted=false, receipt
    ``dispatch-refused-terminal.json``) - never ``PostOutcomeUnknown``."""
    clash = _RESERVED & set(identity)
    if clash:
        raise ValueError(f"identity may not use reserved keys: {sorted(clash)}")
    receipt_dir = Path(receipt_dir)
    intent_path = receipt_dir / INTENT_FILE
    if post_evidence(receipt_dir):  # fast path; the authoritative check is O_EXCL below
        raise _used(receipt_dir)
    if guard is None:  # fail-closed: yêu cầu guard do RUN khai (marker), không do thiện chí của caller
        marker = run_watchdog.guard_required_marker(receipt_dir)
        if marker is not None:
            raise GuardRequired(f"run declares a terminal guard ({marker}) but dispatch got guard=None; "
                                "nothing was POSTed", evidence={"stage": "guard_required", "marker": str(marker),
                                                                "post_attempted": False})
    graph_sha = canonical_sha256(graph, mode="ascii")
    with existence_lock(settings.lock_path, timeout_seconds=settings.lock_timeout_seconds):
        if post_evidence(receipt_dir):
            raise _used(receipt_dir)
        queue = client.get("/queue")
        require_idle(queue, strict_idle=strict_idle)
        history = client.get(f"/history?max_items={history_max_items}")
        twins = sorted({r.prompt_id for r in (*queue_records(queue), *prompt_records(history, "history"))
                        if r.matches(wanted_shas(graph, graph_sha))})
        if twins:  # receipts may have been lost: the graph names its own input and output, so a twin is a POST
            raise Uncertain(f"ComfyUI queue/history already holds prompt(s) {twins} with this exact graph; a second "
                            "POST is forbidden. Reconcile by hand; a new run needs a new version folder",
                            evidence={"stage": "post_evidence", "prompt_ids": twins})
        correlation_id = str(uuid.uuid4())
        client_id = client_id_for(client_prefix, correlation_id)
        instance: dict[str, Any] = {}
        if container_instance is not None:
            try:
                recorded = container_instance()
            except Exception as error:  # noqa: BLE001 - same outcome as an unreadable container
                recorded = {"available": False, "error": repr(error)}
            text = recorded.get("started_at_text") if isinstance(recorded, dict) else None
            if not isinstance(text, str) or not text.strip():
                raise Uncertain("the container's StartedAt could not be read before the POST (docker unreadable?); "
                                "nothing was sent. Without it a lost prompt can never be proven, so the dispatch "
                                "is refused: fix docker access and re-run with --resume",
                                evidence={"stage": "container_instance_unavailable", "container_instance": recorded})
            instance = {"container_instance": recorded}
        write_json_once(intent_path, {
            "schema": INTENT_SCHEMA, **identity, "correlation_id": correlation_id, "client_id": client_id,
            "graph_sha256": graph_sha, "canonicalization": "ascii", "base_url": settings.base_url,
            "created_at": clock(), "pid": os.getpid(), "queue_before_post": queue,
            "history_entries_before": len(history) if isinstance(history, dict) else None, **instance,
        }, mode="ascii")
        with ExitStack() as gate_stack:
            if guard is not None:  # refusal here is certain "not POSTed": it must NOT reach the catch-all below
                _check_guard(guard, gate_stack, receipt_dir, graph_sha=graph_sha, client_id=client_id,
                             correlation_id=correlation_id, clock=clock)
            # ---- from here on: any failure is "outcome unknown", never "refused".
            try:
                response, receipt_error = _post_and_receipt(
                    client, graph, receipt_dir, client_id=client_id, correlation_id=correlation_id,
                    graph_sha=graph_sha, clock=clock)
            except PostOutcomeUnknown:
                raise
            except Exception as error:  # noqa: BLE001 - see module docstring
                raise _unknown(receipt_dir, client_id, "unexpected error after intent",
                               {"error": repr(error)}) from error
    return DispatchResult(prompt_id=response["prompt_id"], client_id=client_id,
                          correlation_id=correlation_id, graph_sha256=graph_sha, response=response,
                          intent_path=intent_path, submitted_receipt_error=receipt_error)
