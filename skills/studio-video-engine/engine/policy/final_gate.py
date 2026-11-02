"""Final gate: a FINAL cut/render/deliver needs a user-approval receipt bound to the exact media sha256 of every shot.

Rule source (data, in the domain ``final_gate`` block): NO_FINAL_UNTIL_SHOTS_APPROVED.  This module REUSES the
existing approval records (``jjv/h3-acceptance/v1`` written by ``h3 accept`` and ``jjv/video-acceptance/v1`` written
by ``video accept``, both under ``<shot>/acceptance/NNN-<pick|reject>.json``); it adds no registry of its own.
A domain without an enabled ``final_gate`` block is never touched (JennieJoy behaves as before).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..config.loader import REPO_ROOT
from ..core.errors import Refused
from ..core.io import read_json, sha256_file

CODE = "FINAL_GATE_UNAPPROVED"
SHA_KEYS = {"jjv/h3-acceptance/v1": ("sha256",),
            "jjv/video-acceptance/v1": ("native_sha256", "output_1080_sha256")}
ASSEMBLE_RECEIPT_SCHEMA = "jjv/assemble-receipt/v1"
DEFAULT_RULE = "NO_FINAL_UNTIL_SHOTS_APPROVED"


def block(domain: Mapping[str, Any] | None) -> dict | None:
    gate = (domain or {}).get("final_gate")
    return gate if isinstance(gate, Mapping) and gate.get("enabled") is True else None


def enabled(domain: Mapping[str, Any] | None) -> bool:
    return block(domain) is not None


DECISIONS_GLOB = "USER-DECISIONS-*.json"
DECISIONS_SCHEMA = "newtecons/user-decisions/v1"
MIN_PREFIX = 8


@dataclass(frozen=True)
class Approvals:
    picked: Mapping[str, str]   # media sha256 -> record path
    rejected: frozenset[str]
    prefixes: Mapping[str, str] = None  # sha256 prefix (>= 8 hex) -> record path (user wrote only a prefix)

    def hit(self, sha: str) -> str | None:
        """The record that approves ``sha`` (exact, or by a recorded prefix), else None."""
        if sha in self.picked:
            return self.picked[sha]
        return next((rec for pre, rec in (self.prefixes or {}).items() if sha.startswith(pre)), None)


def _decisions(path: Path, picked: dict, prefixes: dict, rejected: set) -> None:
    """``approved_shots[]`` of a USER-DECISIONS file: ``{id, sha256 | sha256_prefix, file?}``.  A row whose named
    file exists but no longer hashes to its sha256 is not an approval of those bytes and is skipped."""
    try:
        doc = read_json(path)
    except (OSError, ValueError):
        return
    if not isinstance(doc, dict) or doc.get("schema") != DECISIONS_SCHEMA:
        return
    for row in doc.get("approved_shots") or []:
        if not isinstance(row, dict):
            continue
        record = f"{path}#{row.get('id')}"
        sha, prefix = row.get("sha256"), row.get("sha256_prefix")
        if isinstance(sha, str) and len(sha) == 64:
            file = row.get("file")
            located = _locate(file, path) if isinstance(file, str) else None
            if located is not None and sha256_file(located) != sha.lower():
                continue
            picked[sha.lower()] = record
        elif isinstance(prefix, str) and len(prefix) >= MIN_PREFIX:
            prefixes[prefix.lower()] = record
    for row in doc.get("rejected_shots") or []:
        if isinstance(row, dict) and isinstance(row.get("sha256"), str):
            rejected.add(row["sha256"].lower())


def _locate(file: str, decisions: Path) -> Path | None:
    """A decisions row names its file relative to the repo root (or absolute); None when not found."""
    candidate = Path(file)
    options = [candidate] if candidate.is_absolute() else [REPO_ROOT / candidate, decisions.parent / candidate]
    return next((p for p in options if p.is_file()), None)


def load_approvals(roots: Iterable[str | Path]) -> Approvals:
    """Every ``*/acceptance/*.json`` pick/reject under the roots.  A sha rejected anywhere is never approved."""
    picked: dict[str, str] = {}
    prefixes: dict[str, str] = {}
    rejected: set[str] = set()
    for root in roots or ():
        for path in sorted(Path(root).rglob(DECISIONS_GLOB)):
            _decisions(path, picked, prefixes, rejected)
        for path in sorted(Path(root).rglob("acceptance/*.json")):
            try:
                record = read_json(path)
            except (OSError, ValueError):
                continue
            keys = SHA_KEYS.get(record.get("schema")) if isinstance(record, dict) else None
            if not keys:
                continue
            subject = record.get("subject") or {}
            shas = {subject[k].lower() for k in keys if isinstance(subject.get(k), str)}
            if record.get("decision") == "reject":
                rejected |= shas
            elif record.get("decision") == "pick":
                for sha in shas:
                    picked[sha] = str(path)
    return Approvals(picked, frozenset(rejected), prefixes)


def check_shots(domain: Mapping[str, Any], shots: Sequence[tuple[str, Sequence[str | None]]],
                roots: Iterable[str | Path], *, verb: str) -> list[dict]:
    """``shots`` = ``[(shot_id, [candidate shas])]``.  Returns approval rows; ``Refused`` naming every unapproved shot."""
    gate = block(domain)
    if gate is None:
        return []
    folders = [*(roots or ()), *(REPO_ROOT / d for d in gate.get("decision_roots") or [])]
    approvals = load_approvals(folders)
    rows, missing = [], []
    for shot, shas in shots:
        wanted = [s.lower() for s in shas if isinstance(s, str) and s]
        hit = next((s for s in wanted if approvals.hit(s) and s not in approvals.rejected), None)
        if hit is None:
            why = "rejected" if any(s in approvals.rejected for s in wanted) else "no approval receipt"
            missing.append(f"{shot} ({why}; media sha {wanted[0][:12] if wanted else 'none'})")
        else:
            rows.append({"shot": shot, "sha256": hit, "record": approvals.hit(hit)})
    if missing:
        raise Refused(f"{CODE}: {verb} is a FINAL step and rule {gate.get('rule', DEFAULT_RULE)} requires a "
                      "user-approval receipt bound to each media sha256; unapproved shots: " + "; ".join(missing)
                      + ". Preview cuts stay allowed (use --preview).")
    return rows


def require_final_master(domain: Mapping[str, Any], master: str | Path, *, verb: str) -> dict | None:
    """A master may go on to delivery only if a FINAL assemble receipt beside it lists its sha256."""
    gate = block(domain)
    if gate is None:
        return None
    master = Path(master).resolve()
    digest = sha256_file(master)
    for path in sorted(master.parent.glob("receipt-*.json")):
        try:
            doc = read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or doc.get("schema") != ASSEMBLE_RECEIPT_SCHEMA or doc.get("cut_kind") != "final":
            continue
        if any(isinstance(v, dict) and v.get("sha256") == digest for v in (doc.get("outputs") or {}).values()):
            return {"receipt": str(path), "master_sha256": digest}
    raise Refused(f"{CODE}: {verb} needs a FINAL master (rule {gate.get('rule', DEFAULT_RULE)}): {master.name} sha "
                  f"{digest[:12]} is not listed in any cut_kind=final assemble receipt beside it "
                  "(a preview cut or an unreceipted file is not deliverable)")
