"""M9b-3: engine-side reader/validator for the Studio review feedback JSONL (v1).

Feedback ANNOTATES. Nothing here edits inputs, writes files, spawns processes or
lets a note trigger a rerender; this module only reads one byte snapshot and
returns typed notes bound to receipt SHAs. Wiring into `plan explain` is M9b-4.

The validator mirrors the Studio writer (production-local/studio-app/jjv_feedback.py)
and both are run against the same corpus (CORPUS_SHA pinned in each test file).
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Collection, Mapping

SCHEMA = "jjv/studio-feedback/v1"
STAGES = frozenset({
    "script", "storyboard", "layout", "images", "voice", "h3", "timing", "icons",
    "audio", "editorial", "review", "seedvr2", "master", "delivery", "publish",
})
VERDICTS = frozenset({"comment", "changes", "approve"})
# Stages that review media: artifact_sha256 must be non-null (design: image/audio/video).
ARTIFACT_STAGES = frozenset({"images", "voice", "h3", "audio", "seedvr2", "master", "delivery"})
KEYS = (
    "schema", "id", "domain", "episode", "shot", "stage", "verdict", "note", "author",
    "ts", "receipt", "receipt_sha256", "artifact_sha256", "frame", "supersedes",
)
FRAME_COUNT_KEYS = frozenset({"frame_count", "frames", "nb_frames"})
DEFAULT_RELATIVE = "editorial/review-feedback/feedback-v1.jsonl"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_TS = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})\.[0-9]{3}Z\Z")
_DRIVE = re.compile(r"[A-Za-z]:")


class FeedbackError(ValueError):
    """Explicit refusal. kind: schema|scope|path|missing|stale|corrupt|supersedes."""

    def __init__(self, message: str, *, kind: str = "schema", line: int | None = None):
        super().__init__(message if line is None else f"line {line}: {message}")
        self.kind = kind
        self.line = line


@dataclass(frozen=True)
class FeedbackNote:
    line: int
    id: str
    domain: str
    episode: str
    shot: str | None
    stage: str
    verdict: str
    note: str
    author: str
    ts: str
    receipt: str
    receipt_sha256: str
    artifact_sha256: str | None
    frame: int | None
    supersedes: str | None
    stale: bool = False
    superseded: bool = False


@dataclass(frozen=True)
class FeedbackSnapshot:
    path: str
    present: bool
    sha256: str | None
    bytes: int
    line_count: int
    notes: tuple[FeedbackNote, ...]
    unresolved_changes: tuple[str, ...]
    stale: tuple[str, ...]


def feedback_path(root: Path) -> Path:
    """Canonical v1 path under the episode root R (no parent-folder search)."""
    return Path(root) / Path(*DEFAULT_RELATIVE.split("/"))


def _bad(msg: str, kind: str = "schema") -> FeedbackError:
    return FeedbackError(msg, kind=kind)


def _text(rec: Mapping[str, Any], key: str, lo: int, hi: int) -> str:
    value = rec[key]
    if not isinstance(value, str):
        raise _bad(f"{key} must be a string")
    if value != value.strip() or not lo <= len(value) <= hi:
        raise _bad(f"{key} must be trimmed text of {lo}..{hi} characters")
    return value


def _hex(value: Any, key: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _HEX.match(value):
        raise _bad(f"{key} must be 64 lowercase hex characters")
    return value


def _uuid(value: Any, key: str) -> str:
    try:
        ok = isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        ok = False
    if not ok:
        raise _bad(f"{key} must be a lowercase canonical UUID")
    return value


def _check_ts(value: Any) -> None:
    match = _TS.match(value) if isinstance(value, str) else None
    if match is None:
        raise _bad("ts must be YYYY-MM-DDTHH:MM:SS.sssZ")
    try:
        datetime(*(int(g) for g in match.groups()))
    except ValueError as exc:
        raise _bad(f"ts is not a valid calendar time: {exc}") from None


def _check_rel(rel: Any) -> str:
    if not isinstance(rel, str) or not rel or "\\" in rel or "\x00" in rel:
        raise _bad("receipt must be a POSIX relative path", "path")
    if rel.startswith("/") or _DRIVE.match(rel):
        raise _bad("receipt must not be absolute", "path")
    if any(part in ("", ".", "..") for part in rel.split("/")):
        raise _bad("receipt must not contain empty, '.' or '..' parts", "path")
    return rel


def receipt_snapshot(root: Path, rel: str) -> bytes:
    """Raw receipt bytes through ONE handle, resolved inside R."""
    base = Path(root).resolve()
    target = (base / Path(*_check_rel(rel).split("/"))).resolve()
    if base != target and base not in target.parents:
        raise _bad("receipt escapes the episode root", "path")
    try:
        with open(target, "rb") as handle:
            return handle.read()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, PermissionError) as exc:
        raise _bad(f"receipt unreadable: {exc.__class__.__name__}", "missing") from None


def _walk(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield key, item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield None, item
            yield from _walk(item)


def _loads(raw: bytes) -> Any:
    def pairs(items: list) -> dict:
        out: dict = {}
        for key, item in items:
            if key in out:
                raise ValueError(f"duplicate key {key!r}")
            out[key] = item
        return out

    def const(name: str) -> Any:
        raise ValueError(f"non-finite constant {name}")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=const)


def validate_record(
    rec: Any,
    *,
    domain: str,
    episode: str,
    shots: Collection[str],
    root: Path,
    artifact_resolver: Callable[[Mapping[str, Any]], Path | None] | None = None,
) -> None:
    """Whole-record validation + receipt/artifact binding. Raises FeedbackError."""
    if not isinstance(rec, Mapping):
        raise _bad("record must be a JSON object")
    missing = [k for k in KEYS if k not in rec]
    extra = sorted(set(rec) - set(KEYS))
    if missing or extra:
        raise _bad(f"keys differ from v1 (missing={missing}, extra={extra})")
    if rec["schema"] != SCHEMA:
        raise _bad("schema must be " + SCHEMA)
    _uuid(rec["id"], "id")
    if not isinstance(domain, str) or not domain or rec["domain"] != domain:
        raise _bad("domain differs from the episode's domain", "scope")
    if rec["episode"] != episode or not isinstance(rec["episode"], str) or not 1 <= len(episode) <= 128:
        raise _bad("episode differs from the bound episode", "scope")
    shot = rec["shot"]
    if shot is not None and (not isinstance(shot, str) or shot not in shots):
        raise _bad("shot is not in the bound episode snapshot", "scope")
    if not isinstance(rec["stage"], str) or rec["stage"] not in STAGES:
        raise _bad("stage is not allowed")
    if not isinstance(rec["verdict"], str) or rec["verdict"] not in VERDICTS:
        raise _bad("verdict is not allowed")
    _text(rec, "note", 1, 2000)
    _text(rec, "author", 1, 80)
    _check_ts(rec["ts"])
    rel = _check_rel(rec["receipt"])
    _hex(rec["receipt_sha256"], "receipt_sha256")
    artifact = _hex(rec["artifact_sha256"], "artifact_sha256", nullable=True)
    frame = rec["frame"]
    if frame is not None and (isinstance(frame, bool) or not isinstance(frame, int) or frame < 0):
        raise _bad("frame must be an integer >= 0 or null")
    if rec["supersedes"] is not None:
        _uuid(rec["supersedes"], "supersedes")
        if rec["supersedes"] == rec["id"]:
            raise _bad("a note cannot supersede itself", "supersedes")
    if artifact is None and rec["stage"] in ARTIFACT_STAGES:
        raise _bad(f"stage {rec['stage']} reviews media: artifact_sha256 is required")
    raw = receipt_snapshot(root, rel)
    if hashlib.sha256(raw).hexdigest() != rec["receipt_sha256"]:
        raise _bad("receipt bytes differ from receipt_sha256 (stale)", "stale")
    if artifact is None and frame is None:
        return
    try:
        doc = _loads(raw)
    except ValueError:
        raise _bad("receipt is not JSON, so it cannot bind artifact/frame") from None
    if artifact is not None and not any(v == artifact for _, v in _walk(doc)):
        raise _bad("receipt does not bind artifact_sha256")
    if frame is not None:
        counts = [v for k, v in _walk(doc) if k in FRAME_COUNT_KEYS and isinstance(v, int) and not isinstance(v, bool)]
        if not counts:
            raise _bad("receipt binds no frame count")
        if frame >= counts[0]:
            raise _bad("frame is outside the receipt-bound frame count")
    if artifact is not None and artifact_resolver is not None:
        served = artifact_resolver(rec)
        if served is not None:
            digest = hashlib.sha256(Path(served).read_bytes()).hexdigest()
            if digest != artifact:
                raise _bad("artifact bytes differ from artifact_sha256 (stale)", "stale")


_SAME = ("domain", "episode", "shot", "stage", "receipt", "artifact_sha256")


def read_feedback(
    path: Path | None,
    *,
    root: Path,
    episode: str,
    domain: str,
    shots: Collection[str],
    require: bool = False,
    on_stale: str = "refuse",
    artifact_resolver: Callable[[Mapping[str, Any]], Path | None] | None = None,
) -> FeedbackSnapshot:
    """Read one stable byte snapshot of the v1 log; refuse on any malformed line.

    path None means the canonical file under R. An absent default file yields zero
    notes with present=False; an absent explicit file (require=True) is refused.
    on_stale='mark' keeps notes whose receipt/artifact changed, flagged stale=True.
    """
    if on_stale not in ("refuse", "mark"):
        raise ValueError("on_stale must be 'refuse' or 'mark'")
    target = feedback_path(root) if path is None else Path(path)
    try:
        with open(target, "rb") as handle:
            data = handle.read()
    except FileNotFoundError:
        if require or path is not None:
            raise FeedbackError(f"feedback file not found: {target}", kind="missing") from None
        return FeedbackSnapshot(str(target), False, None, 0, 0, (), (), ())
    except OSError as exc:
        raise FeedbackError(f"feedback file unreadable: {exc}", kind="corrupt") from None
    digest = hashlib.sha256(data).hexdigest()
    if data.startswith(b"\xef\xbb\xbf"):
        raise FeedbackError("BOM is not allowed", kind="corrupt", line=1)
    if data and not data.endswith(b"\n"):
        raise FeedbackError("torn tail: last line has no LF", kind="corrupt", line=data.count(b"\n") + 1)
    lines = data.split(b"\n")[:-1] if data else []
    seen: dict[str, FeedbackNote] = {}
    notes: list[FeedbackNote] = []
    stale: list[str] = []
    for number, raw in enumerate(lines, 1):
        try:
            rec = _loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise FeedbackError(f"not valid UTF-8 JSON: {exc}", kind="corrupt", line=number) from None
        is_stale = False
        try:
            validate_record(rec, domain=domain, episode=episode, shots=shots, root=root,
                            artifact_resolver=artifact_resolver)
        except FeedbackError as exc:
            if exc.kind != "stale" or on_stale != "mark":
                raise FeedbackError(str(exc), kind=exc.kind, line=number) from None
            is_stale = True
        if rec["id"] in seen:
            raise FeedbackError("duplicate note id", kind="corrupt", line=number)
        parent = rec["supersedes"]
        if parent is not None:
            prior = seen.get(parent)
            if prior is None or any(getattr(prior, k) != rec[k] for k in _SAME):
                raise FeedbackError("supersedes must name an earlier note with the same scope",
                                    kind="supersedes", line=number)
        note = FeedbackNote(line=number, stale=is_stale, **{k: rec[k] for k in KEYS if k != "schema"})
        seen[note.id] = note
        notes.append(note)
        if is_stale:
            stale.append(note.id)
    superseded = {n.supersedes for n in notes if n.supersedes}
    final = tuple(
        FeedbackNote(**{**n.__dict__, "superseded": n.id in superseded}) for n in notes
    )
    unresolved = tuple(n.id for n in final if n.verdict == "changes" and not n.superseded)
    return FeedbackSnapshot(str(target), True, digest, len(data), len(lines), final, unresolved, tuple(stale))
