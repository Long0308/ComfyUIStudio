"""Read-only container facts (docker inspect / docker logs) through an injected runner.

Used only to PROVE that a ComfyUI restart happened after a dispatch and to copy the GPU fault
signature out of the container log.  Nothing here ever starts, stops or restarts a container.
Every probe failure becomes ``None`` / an empty list: an unreadable container is "unknown", and
unknown never counts as proof of a restart (``engine.comfy.lost`` then answers Uncertain).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]

# Lines worth keeping from `docker logs` when a prompt was lost.  Case-insensitive.
FAULT_PATTERN = re.compile(
    r"CUDA error|cudaError|illegal instruction|Fatal Python error|out of memory|OutOfMemory|\bOOM\b|"
    r"Aborted|core dumped|Segmentation fault|device-side assert", re.I)
MAX_FAULT_LINES = 40
MAX_LINE_CHARS = 400
REDACTED = "[REDACTED]"
# Order matters: the specific shapes first, the generic long-run catch-all last.
_KEY = (r"(?:x-)?(?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|(?:auth[_-]?|access[_-]?|refresh[_-]?)?token|"
        r"passw(?:or)?d|authorization|proxy-authorization)")
_VALUE = r"""(?:"[^"]*"|'[^']*'|[^\s,;&}"']+)"""  # a quoted value may hold spaces
_REDACTIONS: tuple[tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"""(?i)\b(Bearer|Basic|Digest|Negotiate)\s+[^\s"',;]+"""), r"\1 " + REDACTED),
    # key=value, key: value, "key": "value", 'key': 'value' (the key may be quoted; the value may be quoted)
    (re.compile(r"""(?i)(?<![A-Za-z0-9])(["']?""" + _KEY + r"""["']?\s*[=:]\s*)(?!\[REDACTED\])""" + _VALUE),
     r"\1" + REDACTED),
    (re.compile(r"(?i)\b(authorization\s*:\s*\[REDACTED\])\s+\S+"), r"\1"),  # "Authorization: Digest a=b,c=d"
    (re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s@]+@"), r"\1" + REDACTED + "@"),  # scheme://user:pass@host
    (re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]*"), "[REDACTED-JWT]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"), "sk-" + REDACTED),
    (re.compile(r"\b(?:gh[pousr]_|xox[abprs]-|AKIA|AIza)[A-Za-z0-9_\-]{8,}"), REDACTED),
)
_LONG_RUN = re.compile(r"[A-Za-z0-9+/_=\-]{32,}")  # hex / base64 / opaque blobs of 32+ chars
_WORD = re.compile(r"\S+")
_DRIVE = re.compile(r"""["'(\[{<]*[A-Za-z]:[/\\]""")


def _is_path_like(word: str) -> bool:
    """File names and paths (dots, separators, drive letters) are evidence, not secrets."""
    return ("." in word or "\\" in word or word.lstrip("\"'([{<").startswith(("/", "~"))
            or bool(_DRIVE.match(word)))


def _redact_long_runs(line: str) -> str:
    def word(match: "re.Match[str]") -> str:
        token = match.group(0)
        if _is_path_like(token) or not _LONG_RUN.search(token):
            return token
        return _LONG_RUN.sub("[REDACTED-LONG]", token)
    return _WORD.sub(word, line)


_STARTED = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)$")


def default_runner(command: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(command, capture_output=True, text=True, timeout=60, check=False,
                          encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class ContainerState:
    started_at: float  # unix seconds (UTC) of the container's current start
    started_at_text: str  # as docker printed it
    running: bool
    restart_count: int | None


class ContainerProbe(Protocol):
    """What the lost-prompt classifier needs; tests inject a fake with this shape."""

    def state(self, container: str) -> ContainerState | None: ...

    def fault_lines(self, container: str, since: float) -> dict: ...


def parse_started_at(text: str) -> float | None:
    """Docker prints RFC3339 with nanoseconds (``2026-10-27T07:02:57.123456789Z``)."""
    match = _STARTED.match(text.strip())
    if not match:
        return None
    base, fraction, zone = match.groups()
    micro = ((fraction or ".0")[1:] + "000000")[:6]
    try:
        stamp = datetime.fromisoformat(f"{base}.{micro}{'+00:00' if zone == 'Z' else zone}")
    except ValueError:
        return None
    return stamp.astimezone(timezone.utc).timestamp()


def redact_line(line: str, *, limit: int = MAX_LINE_CHARS) -> str:
    """A log line that is safe to store in a receipt: token-like text replaced, then length-capped.

    Redaction runs BEFORE the cap so a secret that straddles the cut can never survive half-visible.
    """
    for pattern, replacement in _REDACTIONS:
        line = pattern.sub(replacement, line)
    return _redact_long_runs(line)[:limit]


class DockerProbe:
    def __init__(self, runner: Runner = default_runner) -> None:
        self.runner = runner

    def state(self, container: str) -> ContainerState | None:
        fmt = "{{.State.StartedAt}}|{{.State.Running}}|{{.RestartCount}}"
        try:
            done = self.runner(["docker", "inspect", "--format", fmt, container])
        except (OSError, subprocess.SubprocessError):
            return None
        if getattr(done, "returncode", 1) != 0:
            return None
        parts = (done.stdout or "").strip().split("|")
        if len(parts) != 3:
            return None
        started = parse_started_at(parts[0])
        if started is None:
            return None
        restarts = int(parts[2]) if parts[2].strip().isdigit() else None
        return ContainerState(started_at=started, started_at_text=parts[0].strip(),
                              running=parts[1].strip().lower() == "true", restart_count=restarts)

    def fault_lines(self, container: str, since: float) -> dict:
        """GPU/OOM signature lines from ``docker logs --since <dispatch>`` (stdout + stderr)."""
        try:
            done = self.runner(["docker", "logs", "--since", f"{since:.3f}", container])
        except (OSError, subprocess.SubprocessError) as error:
            return {"available": False, "error": redact_line(repr(error)), "matched_lines": [], "line_count": 0}
        text = (done.stdout or "") + (done.stderr or "")
        lines = [line.rstrip() for line in text.splitlines()]
        raw = [line for line in lines if FAULT_PATTERN.search(line)]  # patterns judged on the raw text
        matched = [redact_line(line) for line in raw]  # ... but only redacted text is ever kept
        hits = sorted({m.group(0).lower() for line in raw for m in [FAULT_PATTERN.search(line)] if m})
        return {"available": getattr(done, "returncode", 1) == 0, "since_unix": since,
                "line_count": len(lines), "patterns": hits,
                "matched_lines": matched[:MAX_FAULT_LINES], "matched_total": len(matched)}
