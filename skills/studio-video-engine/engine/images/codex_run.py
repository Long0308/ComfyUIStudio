"""Codex CLI process helpers for ``codex.py``: the exec call, the binary lookup and the text parsers (N58 split, no behaviour change)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from ..core.errors import Refused
from ..core.winflags import no_window

UNIT = {"s": 1, "sec": 1, "second": 1, "m": 60, "min": 60, "minute": 60, "h": 3600, "hr": 3600, "hour": 3600,
        "d": 86400, "day": 86400}
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def default_runner(argv: list[str], *, input_text: str, env: Mapping[str, str], cwd: str, timeout: float):
    flags = (0x4000 if os.name == "nt" else 0) | no_window()  # BELOW_NORMAL_PRIORITY_CLASS + không cửa sổ console
    return subprocess.run(argv, input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=dict(env), cwd=cwd, timeout=timeout, check=False, creationflags=flags)


def find_codex(explicit: str | None, machine: dict[str, Any]) -> list[str]:
    """``--codex-bin``, ``machine.images.codex_bin`` (string or argv list), ``$CODEX_BIN`` or PATH."""
    import shutil

    configured = (machine.get("images") or {}).get("codex_bin")
    for candidate in (explicit, configured, os.environ.get("CODEX_BIN"), shutil.which("codex")):
        if isinstance(candidate, list) and candidate:
            return [str(c) for c in candidate]
        if isinstance(candidate, str) and candidate and Path(candidate).is_file():
            return [candidate]
    raise Refused("Codex CLI not found (pass --codex-bin, set CODEX_BIN or machine.images.codex_bin, or put `codex` on PATH). "
                  "Nothing was run; the engine does not log in for you")


def failure_kind(text: str, recipe: dict[str, Any]) -> str | None:
    """'quota' | 'auth' | None from the CLI's own message text (patterns are recipe policy, a GUESS)."""
    low = text.lower()
    for kind, key in (("quota", "quota_patterns"), ("auth", "auth_patterns")):
        for pattern in recipe[key]:
            hit = re.search(rf"\b{re.escape(pattern)}\b", low) if pattern.isdigit() else (pattern in low)
            if hit:
                return kind
    return None


def cooling_seconds(text: str, default: int) -> int:
    """Seconds named by 'try again in 2 hours 30 minutes' / 'retry after 45m'; else ``default``."""
    found = re.search(r"(?:try again|retry|resets?)[^.\n]{0,24}?\b(?:in|after)\s+([^.\n]+)", text, re.I)
    if not found:
        return default
    total = sum(int(n) * UNIT[u.lower().rstrip("s")] if u.lower().rstrip("s") in UNIT else 0
                for n, u in re.findall(r"(\d+)\s*([a-zA-Z]+)", found.group(1)))
    return total if total > 0 else default


def thread_id(stdout: str) -> str | None:
    """First session/thread id in the ``--json`` event lines (None when the CLI printed none)."""
    def walk(node: Any) -> str | None:
        if isinstance(node, dict):
            for key in ("thread_id", "session_id", "conversation_id"):
                if isinstance(node.get(key), str) and node[key]:
                    return node[key]
            for child in node.values():
                if (hit := walk(child)):
                    return hit
        elif isinstance(node, list):
            for child in node:
                if (hit := walk(child)):
                    return hit
        return None

    for line in stdout.splitlines():
        try:
            hit = walk(json.loads(line))
        except ValueError:
            continue
        if hit:
            return hit
    return None


def snapshot(home: Path, recipe: dict[str, Any]) -> dict[str, float]:
    folder = Path(home) / recipe["generated_images_dir"]
    return {p.as_posix(): p.stat().st_mtime for p in folder.rglob("*.png")} if folder.is_dir() else {}


def own_session(paths: Any, session: str | None) -> list[str]:
    """N87: the images under ``generated_images/<session>/`` only (case-insensitive). Two processes may share one
    CODEX_HOME, so a snapshot diff of the whole tree can hold the OTHER process's image. No session id -> none."""
    if not session:
        return []
    wanted = session.strip().lower()
    return sorted(p for p in paths if Path(p).parent.name.lower() == wanted)
