"""Cast manifest reader: canonical identity references bound by sha256 (never regenerated here)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config.loader import REPO_ROOT
from ..core.errors import Refused
from ..core.io import read_json, sha256_file

# `script ingest` writes canonical_path (cast-bindings.json); older cast files use canonical_png/png/path.
PATH_KEYS = ("canonical_path", "canonical_png", "png", "path")
SHA_KEYS = ("canonical_sha256", "sha256")
UNBOUND = "unbound"  # ingest's reference_status for a role with no canonical reference yet


def _one(entry: dict[str, Any], keys: tuple[str, ...], code: str, label: str) -> str | None:
    """The single value under ``keys``; two keys holding DIFFERENT values is refused, never guessed."""
    values = {k: entry[k] for k in keys if isinstance(entry.get(k), str) and entry[k]}
    distinct = {v.lower() if keys is SHA_KEYS else v for v in values.values()}
    if len(distinct) > 1:
        raise Refused(f"{label}: {code}: row {entry.get('character_id')!r} has conflicting {sorted(values)}")
    return next(iter(values.values()), None)


def _locate(text: str, cast_file: Path) -> Path:
    given = Path(text)
    candidates = [given] if given.is_absolute() else [REPO_ROOT / given, cast_file.parent / given]
    found = next((c for c in candidates if c.is_file()), None)
    if found is None:
        raise Refused(f"cast reference file not found: {text}")
    return found.resolve()


def load_cast(cast_file: Path) -> dict[str, dict[str, Any]]:
    """``{character_id: {path, sha256[, roles]}}``; a file whose bytes differ from the recorded sha is refused.

    Rows of ``script ingest``'s ``cast-bindings.json`` carry ``role``: it is kept as ``roles`` so :func:`bind`
    resolves that role without ``--map``. A row with ``reference_status: unbound`` and no path/sha is not a
    reference (its role stays unbound); every other row needs exactly one path and one sha."""
    label = Path(cast_file).name
    document = read_json(cast_file)
    rows = document.get("characters") if isinstance(document, dict) else None
    if not isinstance(rows, list) or not rows:
        raise Refused(f"{label}: no `characters` list")
    cast: dict[str, dict[str, Any]] = {}
    owner: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise Refused(f"{label}: a character row is not an object")
        cid = row.get("character_id")
        text = _one(row, PATH_KEYS, "AMBIGUOUS_PATH", label)
        expected = _one(row, SHA_KEYS, "AMBIGUOUS_SHA", label)
        if row.get("reference_status") == UNBOUND:
            if text or expected:
                raise Refused(f"{label}: UNBOUND_WITH_REF: row {cid!r} is marked unbound but names a reference")
            continue
        if not (isinstance(cid, str) and cid and text and expected):
            raise Refused(f"{label}: HALF_BOUND: every character needs character_id, a png path and a sha256 "
                          f"(row {cid!r} has path={bool(text)} sha={bool(expected)})")
        if cid in cast:
            raise Refused(f"{label}: duplicate character_id {cid!r}")
        role = row.get("role")
        if role is not None:
            if not isinstance(role, str) or not role:
                raise Refused(f"{label}: row {cid!r} has an invalid role {role!r}")
            if role in owner:
                raise Refused(f"{label}: DUPLICATE_ROLE: role {role!r} is declared by {owner[role]!r} and {cid!r}")
            owner[role] = cid
        path = _locate(text, Path(cast_file))
        actual = sha256_file(path)
        if actual != expected.lower():
            raise Refused(f"cast reference {cid} hash mismatch: manifest {expected}, file {actual} ({path})")
        cast[cid] = {"path": path.as_posix(), "sha256": actual, **({"roles": [role]} if role else {})}
    return cast


def _declared(cast: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {role: cid for cid, entry in cast.items() for role in entry.get("roles", [])}


def bind(roles: list[str], cast: dict[str, dict[str, Any]], mapping: dict[str, str]) -> tuple[list[dict], list[str]]:
    """Bind each speaker/listener role to a cast character: ``([{role, character_id, path, sha256}], unbound roles)``.

    Order: an explicit ``--map`` entry, then a role declared by a cast row, then a character id equal to the role."""
    bound: list[dict] = []
    unbound: list[str] = []
    declared = _declared(cast)
    for role in dict.fromkeys(roles):
        cid = mapping.get(role, declared.get(role, role))
        if cid in cast:
            bound.append({"role": role, "character_id": cid, "path": cast[cid]["path"], "sha256": cast[cid]["sha256"]})
        else:
            unbound.append(role)
    return bound, unbound


def parse_pairs(items: list[str] | None, label: str) -> dict[str, str]:
    """``["a=b", ...]`` -> dict; a malformed item or a repeated key is refused."""
    out: dict[str, str] = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key or not value:
            raise Refused(f"{label}: expected KEY=VALUE, got {item!r}")
        if key in out:
            raise Refused(f"{label}: {key!r} given twice")
        out[key] = value
    return out
