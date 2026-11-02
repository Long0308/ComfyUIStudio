"""``--prompt-batch`` loading and the queue dispatch gate for ``codex.py`` (N58 split, no behaviour change)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config.loader import REPO_ROOT
from ..core.errors import EngineError, Refused
from ..core.io import read_json, sha256_bytes, sha256_file
from ..layout.context import Context
from . import pool

MAX_N = 10
MAX_N_WHY = ("user 2026-10-30 asked for ~10 images per character per GPT call; a larger batch would burn the shared "
             "ChatGPT quota (accounts cool for hours) before a human has seen one take")


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
IMAGE_LINE = re.compile(r"(?m)^Image(\d+): ([^;\r\n]+); ([^;\r\n]+); SHA256 ([0-9a-fA-F]{64})")


def batch_roots(ctx: Context, accounts: list[pool.Account]) -> tuple[list[Path], list[Path]]:
    """``(allowed, forbidden)`` ref roots: the repo plus ``machine.images.batch_ref_roots``; never a codex home."""
    extra = (ctx.machine.get("images") or {}).get("batch_ref_roots") or []
    homes = [a.codex_home for a in accounts] + [a.codex_home for a in pool.accounts_from(ctx.machine, None)]
    return ([Path(p).resolve() for p in [REPO_ROOT, *extra]], [Path(h).resolve() for h in homes])


def _check_ref_path(raw: Any, where: str, allowed: list[Path], forbidden: list[Path]) -> Path:
    label = f"{where}: reference"
    if not isinstance(raw, str) or not raw:
        raise Refused(f"{label} has no path")
    path = Path(raw)
    if not path.is_absolute():
        raise Refused(f"{label} {raw!r} must be an absolute path")
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise Refused(f"{label} {raw!r} is not an image file ({sorted(IMAGE_SUFFIXES)}); a token or config file is never sent")
    if not path.is_file():
        raise Refused(f"{label} missing: {raw}")
    real = path.resolve()
    if any(real.is_relative_to(h) for h in forbidden):
        raise Refused(f"{label} {raw!r} lies under a codex home: refused")
    if not any(real.is_relative_to(a) for a in allowed):
        raise Refused(f"{label} {raw!r} is outside the allowed roots {[a.as_posix() for a in allowed]}")
    return path


def _queue_rows(path: Path) -> tuple[dict[str, list[tuple[str, dict[str, Any]]]], bool]:
    """``(prompt_id -> [(queue file, row), ...], queue_present)`` from every ``queue-*.json`` next to the batch file.

    The queue is the AUTHORITY (N52): an unreadable queue or one that is not an array refuses; it is never skipped.
    Every row is kept (N52b): a repeated id is a conflict for the caller to refuse, never a silent overwrite."""
    found: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    queues = sorted(Path(path).parent.glob("queue-*.json"))
    for queue in queues:
        try:
            rows = read_json(queue)
        except (ValueError, OSError, EngineError) as error:
            raise Refused(f"queue file {queue.name} next to the batch is not readable JSON: {error}; fix or remove it") from error
        if not isinstance(rows, list):
            raise Refused(f"queue file {queue.name} must be a JSON array")
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("prompt_id"), str):
                found.setdefault(row["prompt_id"], []).append((queue.name, row))
    return found, bool(queues)


def _queue_problem(pid: str, hits: list[tuple[str, dict[str, Any]]]) -> str | None:
    """Why a queue (which exists) does not clear ``pid`` for a real submit, else None. Fail-closed (N52b)."""
    if not hits:
        return f"no row for {pid!r} in any queue-*.json next to the batch"
    if len(hits) > 1:
        return f"prompt_id {pid!r} appears {len(hits)} times in the queues ({', '.join(name for name, _ in hits)}): ambiguous"
    return None


NO_QUEUE_WHY = ("this domain's route recipe says provenance_required: a real codex-exec submit must be cleared by a "
                "queue-*.json next to the --prompt-batch file with one boolean-true row per prompt_id (N52c)")
PROMPT_FILE_WHY = ("this domain's route recipe says provenance_required: --prompt-file/--n has no queue row to clear it; "
                   "use --prompt-batch FILE with a queue-*.json next to it (N52c)")


def provenance_problem(item: dict[str, Any] | None, provenance_required: bool) -> str | None:
    """Why a real submit of a provenance_required domain is refused for want of a queue, else None."""
    if not provenance_required:
        return None
    if item is None:
        return PROMPT_FILE_WHY
    return None if item.get("queue_present") else NO_QUEUE_WHY


def _refuse_blocked(item: dict[str, Any], provenance_required: bool = False) -> None:
    """Real submit gate. With a queue present: the row must exist, be unique across every queue-*.json and say
    ``dispatch_allowed`` is the boolean ``True``; anything else (false, "false", null, 0, missing) refuses.
    No queue next to the batch => old behaviour (the item's own ``dispatch_allowed`` None is accepted), EXCEPT for a
    ``provenance_required`` domain, which refuses (fail-closed, N52c)."""
    value = item.get("dispatch_allowed")
    if value is False:
        raise Refused(f"queue says dispatch_allowed:false for {item.get('prompt_id')} "
                      f"({item.get('dispatch_block_reason') or 'no reason given'}): a real submit is refused; --dry-run still plans it")
    if not item.get("queue_present"):
        why = provenance_problem(item, provenance_required)
        if why:
            raise Refused(f"no queue for {item.get('prompt_id')}: {why}; a real submit is refused; --dry-run still plans it")
        return
    problem = item.get("queue_problem")
    if problem:
        raise Refused(f"queue refuses {item.get('prompt_id')}: {problem}; a real submit is refused; --dry-run still plans it")
    if value is not True:
        raise Refused(f"queue row of {item.get('prompt_id')} has dispatch_allowed={value!r}, not boolean true "
                      f"({item.get('dispatch_block_reason') or 'no reason given'}): a real submit is refused; --dry-run still plans it")


def _check_brief_numbers(where: str, text: str, refs: list[dict[str, Any]], library: bool) -> None:
    lines = IMAGE_LINE.findall(text)
    if not lines:
        return
    if not library:
        raise Refused(f"{where}: the brief numbers its own images (Image1: ...) but this mode sends the shot guide as Image 1; "
                      "use --library-out (no guide, Image 1 = first ref)")
    for number, name, role, sha in lines:
        index = int(number) - 1
        ref = refs[index] if 0 <= index < len(refs) else None
        if ref is None or Path(ref["path"]).name != name or ref["role"] != role or ref["sha256"] != sha.lower():
            raise Refused(f"{where}: brief line Image{number} ({name}; {role}) disagrees with ref {number} of ref_images "
                          f"({Path(ref['path']).name + '; ' + ref['role'] if ref else 'missing'}): the order sent with -i would differ")


def load_batch(path: Path, *, allowed: list[Path], forbidden: list[Path], library: bool = False) -> list[dict[str, Any]]:
    """Validate a --prompt-batch file BEFORE any folder exists. Returns the items (batch_id = file stem).

    Shape: JSON array of 1..MAX_N ``{prompt_id, prompt_text, ref_images:[{path, role, sha256?}], prompt_sha256?}``;
    prompt_id unique, prompt_text not empty, prompt_text sha256 equal to ``prompt_sha256`` (item field or a sibling
    ``queue-*.json``) when one is stated, every ref an absolute image path under an allowed root and never under a
    codex home, present, and its sha256 equal when the file states one."""
    path = Path(path)
    if not path.is_file():
        raise Refused(f"--prompt-batch file not found: {path}")
    try:
        data = read_json(path)
    except (ValueError, OSError) as error:
        raise Refused(f"--prompt-batch {path.name} is not readable JSON: {error}") from error
    if not isinstance(data, list) or not data:
        raise Refused(f"--prompt-batch {path.name} must be a non-empty JSON array")
    if len(data) > MAX_N:
        raise Refused(f"--prompt-batch holds {len(data)} items; at most {MAX_N}; {MAX_N_WHY}")
    queue, queue_present = _queue_rows(path)
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for index, row in enumerate(data, 1):
        where = f"--prompt-batch {path.name} item {index}"
        if not isinstance(row, dict):
            raise Refused(f"{where} is not an object")
        pid, text, refs = row.get("prompt_id"), row.get("prompt_text"), row.get("ref_images")
        if not isinstance(pid, str) or not pid.strip():
            raise Refused(f"{where}: prompt_id missing")
        if pid in seen:
            raise Refused(f"{where}: duplicate prompt_id {pid!r}")
        seen.add(pid)
        where = f"{where} ({pid})"
        if not isinstance(text, str) or not text.strip():
            raise Refused(f"{where}: prompt_text is empty")
        hits = queue.get(pid, [])
        qrow = hits[0][1] if hits else None
        if len({str(h[1].get("prompt_sha256")).lower() for h in hits}) > 1:
            raise Refused(f"{where}: queues disagree on prompt_sha256 for this prompt_id ({', '.join(h[0] for h in hits)})")
        q_sha = qrow.get("prompt_sha256") if qrow else None
        q_sha = q_sha.lower() if isinstance(q_sha, str) else None
        own = row.get("prompt_sha256")
        if q_sha is not None and own is not None and str(own).lower() != q_sha:
            raise Refused(f"{where}: item prompt_sha256 {own} != queue prompt_sha256 {q_sha} (the queue is the authority)")
        expected = q_sha or own
        text_sha = sha256_bytes(text.encode("utf-8"))
        if expected is not None and str(expected).lower() != text_sha:
            raise Refused(f"{where}: prompt_text sha256 {text_sha} != prompt_sha256 {expected} (the queue/author's hash)")
        if not isinstance(refs, list):
            raise Refused(f"{where}: ref_images must be an array")
        clean = []
        for ref in refs:
            ref_path = _check_ref_path(ref.get("path") if isinstance(ref, dict) else None, where, allowed, forbidden)
            actual = sha256_file(ref_path)
            if ref.get("sha256") not in (None, actual):
                raise Refused(f"{where}: reference {ref['path']} changed: recorded {ref['sha256']}, now {actual}")
            clean.append({"path": ref["path"], "sha256": actual, "role": str(ref.get("role") or "reference")})
        _check_brief_numbers(where, text, clean, library)
        items.append({"prompt_id": pid, "prompt_text": text, "ref_images": clean, "batch_id": path.stem,
                      "batch_file": path.resolve().as_posix(), "prompt_text_sha256": text_sha,
                      "prompt_sha_verified": expected is not None,
                      "dispatch_allowed": qrow.get("dispatch_allowed") if qrow else None,
                      "queue_present": queue_present,
                      "queue_problem": _queue_problem(pid, hits) if queue_present else None,
                      "dispatch_block_reason": (qrow.get("dispatch_block_reason") or qrow.get("status")) if qrow else None})
    return items
