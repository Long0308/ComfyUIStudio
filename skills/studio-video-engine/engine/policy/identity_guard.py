"""Identity source guard: a face/identity reference must be a user-approved anchor or KEEP face, by sha256.

The allow-list is DATA in the domain ``identity_guard`` block (``allowed_refs[] = {name, path, sha256}``).  A generated
scene still used as identity is refused.  A domain with no enabled block is not touched.
"""
from __future__ import annotations

import sys
from typing import Any, Iterable, Mapping

from ..core.errors import Refused

CODE = "IDENTITY_SOURCE_REFUSED"
TIER_CANON, TIER_QA = "canon", "qa_keep"
QA_WARNING = "QA proposal, not user canon"


def block(domain: Mapping[str, Any] | None) -> dict | None:
    guard = (domain or {}).get("identity_guard")
    return guard if isinstance(guard, Mapping) and guard.get("enabled") is True else None


def _allowed(guard: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(r.get("sha256", "")).lower(): r for r in guard.get("allowed_refs") or [] if isinstance(r, Mapping)}


def _entry(ref: Mapping[str, Any], row: Mapping[str, Any]) -> dict:
    tier = row.get("tier") if row.get("tier") in (TIER_CANON, TIER_QA) else TIER_QA  # unknown tier fails safe
    entry = {"path": ref.get("path"), "sha256": str(ref.get("sha256", "")).lower(), "name": row.get("name"),
             "identity_tier": tier}
    if tier == TIER_QA:
        entry["warning"] = QA_WARNING
    return entry


def listed_report(domain: Mapping[str, Any] | None, refs: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Receipt rows for every ref whose sha256 is on the allow-list (canon: no warning; qa_keep: warning field).
    Refs not on the list are ignored here (they may be wardrobe/location); ``check_refs`` is what refuses."""
    guard = block(domain)
    if guard is None:
        return []
    allowed = _allowed(guard)
    return [_entry(ref, allowed[str(ref.get("sha256", "")).lower()]) for ref in refs
            if str(ref.get("sha256", "")).lower() in allowed]


def warn(entries: Iterable[Mapping[str, Any]], *, where: str) -> None:
    """One WARNING line (stderr) per qa_keep use."""
    for entry in entries:
        if entry.get("identity_tier") == TIER_QA:
            print(f"WARNING: {where}: identity ref {entry.get('name') or entry.get('path')} is tier qa_keep "
                  f"({QA_WARNING})", file=sys.stderr)


def check_refs(domain: Mapping[str, Any] | None, refs: Iterable[Mapping[str, Any]], *, where: str) -> int:
    """``refs`` rows ``{role, path, sha256}``; only rows whose role is in the block ``roles`` are identity refs.
    Returns the number checked; raises ``Refused`` naming each ref that is not on the allow-list."""
    guard = block(domain)
    if guard is None:
        return 0
    roles = {str(r).lower() for r in guard.get("roles") or []}
    allowed = _allowed(guard)
    checked, bad, used = 0, [], []
    for ref in refs:
        if str(ref.get("role", "")).lower() not in roles:
            continue
        checked += 1
        sha = str(ref.get("sha256", "")).lower()
        if sha not in allowed:
            bad.append(f"{ref.get('role')} {ref.get('path')} sha256={sha[:12] or 'none'}")
        else:
            used.append(_entry(ref, allowed[sha]))
    if bad:
        raise Refused(f"{CODE}: {where}: identity reference not on the user-approved allow-list "
                      "(approved anchors / KEEP face sets, domain identity_guard.allowed_refs): " + "; ".join(bad)
                      + ". A generated scene still can never be an identity source.")
    warn(used, where=where)
    return checked
