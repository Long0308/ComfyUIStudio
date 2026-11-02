"""Bounded wait for a prompt's history entry.  Never resubmits.

The caller must already hold a prompt_id; there is no way to wait for "whatever ran".
Poll errors are collected, not fatal: a flaky read must not look like a failed job.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from ..core.errors import WaitTimeout
from .client import ComfyClient


def wait_for_history(client: ComfyClient, prompt_id: str, *, timeout_seconds: float,
                     poll_seconds: float, sleep: Callable[[float], None] = time.sleep,
                     on_pending: Callable[[], None] | None = None) -> dict[str, Any]:
    """Return the history entry for ``prompt_id`` or raise :class:`WaitTimeout` (exit 3).

    ``on_pending`` (the stall watchdog) runs after every poll that found no entry; whatever it
    raises ends the wait.  It must never POST."""
    if not isinstance(prompt_id, str) or not prompt_id:
        raise ValueError("wait_for_history needs a prompt_id")
    if timeout_seconds < 0 or poll_seconds <= 0:
        raise ValueError("timeout must be >= 0 and poll interval positive")
    deadline = time.monotonic() + timeout_seconds
    errors: list[str] = []
    while True:
        try:
            value = client.get("/history/" + prompt_id)
            entry = value.get(prompt_id) if isinstance(value, dict) else None
            if isinstance(entry, dict) and entry:
                return entry
        except Exception as error:  # noqa: BLE001 - a flaky read is not a verdict
            errors.append(repr(error))
        if on_pending is not None:
            on_pending()
        if time.monotonic() >= deadline:
            break
        sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
    raise WaitTimeout(
        f"history for prompt {prompt_id} unavailable after {timeout_seconds:g}s; do not resubmit",
        evidence={"prompt_id": prompt_id, "timeout_seconds": timeout_seconds,
                  "poll_error_tail": errors[-5:], "poll_error_count": len(errors)})
