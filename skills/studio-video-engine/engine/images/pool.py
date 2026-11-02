"""Codex account pool for the ``codex-exec`` route: PATHS and LABELS only.

One CODEX_HOME directory per ChatGPT account (the workspace's supported way to run Codex as a given account).
This module never opens, reads, hashes, copies or moves ``auth.json``: it only asks whether the file EXISTS.
State (sticky last good account, cooling-until times) holds labels and unix times, nothing else.
"""

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from typing import Callable, Iterator

from ..core.errors import Refused, Uncertain
from ..core.io import read_json, write_json_atomic
from .lease import lease

STATE_SCHEMA = "jjv/codex-pool-state/v1"
LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,60}$")


@dataclass(frozen=True)
class Account:
    label: str
    codex_home: Path

    @property
    def auth_present(self) -> bool:
        return (self.codex_home / "auth.json").is_file()  # existence only, never the contents


def accounts_from(machine: dict[str, Any], cli_pairs: list[str] | None) -> list[Account]:
    """``--codex-account LABEL=HOME`` wins over ``machine.images.codex_accounts``; labels must be unique."""
    rows: list[tuple[str, str]] = []
    if cli_pairs:
        for pair in cli_pairs:
            label, sep, home = pair.partition("=")
            if not sep or not label or not home:
                raise Refused(f"--codex-account expects LABEL=CODEX_HOME, got {pair!r}")
            rows.append((label, home))
    else:
        for row in ((machine.get("images") or {}).get("codex_accounts") or []):
            rows.append((str(row.get("label", "")), str(row.get("codex_home", ""))))
    accounts, seen = [], set()
    for label, home in rows:
        if not LABEL.match(label) or label in seen or not home:
            raise Refused(f"codex account label {label!r} is invalid or duplicated (labels are [A-Za-z0-9_.-], unique)")
        seen.add(label)
        accounts.append(Account(label, Path(home)))
    return accounts


def load_state(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {"schema": STATE_SCHEMA, "last_good": None, "cooling": {}, "history": []}
    for attempt in range(100):  # Windows: reading while another lane replaces the file raises PermissionError (N25, measured)
        try:
            state = read_json(path)
            break
        except Uncertain as error:
            if not isinstance(error.__cause__, PermissionError) or attempt == 99:
                raise
            time.sleep(0.02)
    if not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA:
        raise Refused(f"{path} is not a {STATE_SCHEMA} document")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    write_json_atomic(Path(path), state, mode="ascii")


def label_lock_path(state_path: Path, label: str) -> Path:
    """Per-account job lock: ``<state stem>.<label>.lock`` (a label is [A-Za-z0-9_.-], safe in a file name)."""
    state_path = Path(state_path)
    return state_path.with_name(f"{state_path.stem}.{label}.lock")


@contextmanager
def locked(path: Path, *, timeout_seconds: float, what: str = "lock") -> Iterator[Any]:
    """The images engine's lock (``lease.py``): an OS-level lock released when the holder dies, no orphan to reclaim;
    the holder (pid, host, time) is recorded beside it only for the refusal message. Not the ComfyUI lock."""
    with lease(Path(path), timeout_seconds=timeout_seconds, what=what) as handle:
        yield handle


def update_state(path: Path, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Read-modify-write the shared state under a SHORT lock (``<stem>.lock``), re-reading inside the lock so two
    lanes finishing at once never overwrite each other's record. Simplest option: one state file, held for
    milliseconds only (no per-label state files to merge when ordering accounts)."""
    path = Path(path)
    with locked(path.with_suffix(".lock"), timeout_seconds=30.0, what="codex pool state lock"):
        state = load_state(path)
        mutate(state)
        save_state(path, state)
        return state


def cooling_labels(machine: dict[str, Any], accounts: list[Account]) -> set[str]:
    """Keep machine base labels visible when CLI lanes override the selectable accounts."""
    return {a.label for a in accounts} | {
        str(row.get("label", "")) for row in ((machine.get("images") or {}).get("codex_accounts") or [])}


def base_label(label: str, configured_labels: set[str]) -> str:
    """Strip one ASCII lowercase suffix only for variants ``<base><letter>`` whose base is configured AND ends with a digit
    (acct3b -> acct3). An independent account such as ``acctb`` next to ``acct`` stays its own base (N97)."""
    base = label[:-1]
    return base if label and "a" <= label[-1] <= "z" and base and base[-1].isdigit() and base in configured_labels else label


def order(accounts: list[Account], state: dict[str, Any], now: float, *,
          configured_labels: set[str] | None = None) -> tuple[list[Account], dict[str, float]]:
    """Sticky first (the last good account), then the rest in configured order; cooling accounts are left out.

    Returns ``(candidates, {label: cooling_until})`` for the accounts that were skipped.
    Old per-label v1 records remain valid: each base uses its latest unexpired label deadline.
    Pass the full configured labels when ``accounts`` is a pinned or post-lock subset."""
    labels = {a.label for a in accounts} | (configured_labels or set())
    by_base: dict[str, float] = {}
    for label, value in (state.get("cooling") or {}).items():
        until = float(value)
        if until > now:
            base = base_label(label, labels)
            by_base[base] = max(by_base.get(base, until), until)
    cooling = {a.label: by_base[base_label(a.label, labels)] for a in accounts if base_label(a.label, labels) in by_base}
    live = [a for a in accounts if a.label not in cooling]
    sticky = state.get("last_good")
    live.sort(key=lambda a: 0 if a.label == sticky else 1)  # stable: configured order is kept after the sticky one
    return live, {a.label: cooling[a.label] for a in accounts if a.label in cooling}


def mark_cooling(state: dict[str, Any], label: str, until: float, reason: str, now: float | None = None) -> None:
    state.setdefault("cooling", {})[label] = until
    state.setdefault("history", []).append({"at": now if now is not None else time.time(), "label": label,
                                            "event": "cooling", "until": until, "reason": reason})
    del state["history"][:-50]


def mark_good(state: dict[str, Any], label: str, now: float | None = None) -> None:
    state["last_good"] = label
    (state.setdefault("cooling", {})).pop(label, None)
    state.setdefault("history", []).append({"at": now if now is not None else time.time(), "label": label,
                                            "event": "ok"})
    del state["history"][:-50]
