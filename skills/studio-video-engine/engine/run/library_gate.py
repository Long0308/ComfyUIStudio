"""``library-coverage`` gate: EVERY required character x kind x slot has a live approval, and the cast binds them.

The requirement manifest (``episode.files.library_requirements``, schema ``jjv/library-requirements/v1``) is data:
``{"characters": [...], "kinds": {"FACE": 10, "ACTION": 10}, "slots": [{"character","kind","slot","prompt_id"}]}``.
The gate RECOMPUTES from the sources every time (no ``ok`` flag is trusted).  A slot counts only when
``images.library.current_approval`` still verifies its receipt/checklists AND the approval is for this episode and
domain, this character, scope ``character-library``, status ``accepted_library_image``, with the take's PNG on disk
matching its sha256.  The cast must bind every required character to an image that IS one of that character's
approved picks.  When human proof is required (recipe) each approval also needs a verified sidecar proof
``approval-vNNN.proof.json`` (gate ``library-approval``, subject = candidate sha256).  The manifest itself is NOT signed
here (known gap): whoever can edit it could lower the requirement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from . import proof as proof_mod
from .context import RunContext

REQ_SCHEMA = "jjv/library-requirements/v1"
LIBRARY_SCOPE = "character-library"


def _requirements(path: Path) -> tuple[list[str], dict[str, int], list[dict[str, str]]]:
    doc = read_json(path)
    if not isinstance(doc, dict) or doc.get("schema") != REQ_SCHEMA:
        raise Refused(f"{path.name}: not a {REQ_SCHEMA} document")
    chars, kinds, slots = doc.get("characters"), doc.get("kinds"), doc.get("slots")
    if not (isinstance(chars, list) and chars and all(isinstance(c, str) for c in chars)):
        raise Refused(f"{path.name}: `characters` must be a non-empty list")
    if not (isinstance(kinds, dict) and kinds and all(isinstance(n, int) and n > 0 for n in kinds.values())):
        raise Refused(f"{path.name}: `kinds` must map kind -> required slot count")
    keys = ("character", "kind", "slot", "prompt_id")
    if not (isinstance(slots, list) and all(isinstance(s, dict) and all(isinstance(s.get(k), str) and s[k] for k in keys)
                                            for s in slots)):
        raise Refused(f"{path.name}: every slot needs {', '.join(keys)}")
    return list(chars), dict(kinds), [{k: s[k] for k in keys} for s in slots]


def _slot_problems(chars: list[str], kinds: dict[str, int], slots: list[dict[str, str]]) -> list[str]:
    problems, seen_ids, seen_slots = [], set(), set()
    for s in slots:
        ident, tag = s["prompt_id"], (s["character"], s["kind"], s["slot"])
        if ident in seen_ids or tag in seen_slots:
            problems.append(f"duplicate slot/prompt {tag}/{ident} (revisions never fill another slot)")
        seen_ids.add(ident)
        seen_slots.add(tag)
    for c in chars:
        for kind, count in kinds.items():
            have = sum(1 for s in slots if s["character"] == c and s["kind"] == kind)
            if have != count:
                problems.append(f"{c}/{kind}: manifest lists {have} slots, policy needs {count}")
    return problems


def _approval_problem(ctx: RunContext, library_out: Path, slot: dict[str, str]) -> tuple[str | None, str | None]:
    """``(problem, candidate_sha256)`` of one slot."""
    from ..images import library
    label = f"{slot['character']}/{slot['kind']}/{slot['slot']}"
    row = library.current_approval(library_out, slot["prompt_id"])
    if row is None:
        return f"{label}: no live approval for {slot['prompt_id']}", None
    sha = row.get("candidate_sha256")
    wrong = [name for name, ok in (
        ("schema", row.get("schema") == library.APPROVAL_SCHEMA), ("status", row.get("status") == "accepted_library_image"),
        ("episode", row.get("episode_id") == ctx.episode_id), ("domain", row.get("domain") == ctx.domain_id),
        ("character", row.get("character") == slot["character"] and library.character_of(slot["prompt_id"]) == slot["character"]),
        ("prompt", row.get("prompt_id") == slot["prompt_id"]), ("scope", LIBRARY_SCOPE in str(row.get("scope", "")))) if not ok]
    if wrong:
        return f"{label}: approval has wrong {', '.join(wrong)}", None
    try:
        receipt = read_json(Path(row["receipt"]["path"]))
        png = Path(receipt["output"]["path"])
        if not isinstance(sha, str) or receipt["output"]["sha256"] != sha or not png.is_file() or sha256_file(png) != sha:
            return f"{label}: PNG missing or its sha256 differs from the approved candidate", None
    except (Refused, KeyError, TypeError, OSError) as error:
        return f"{label}: receipt unreadable ({error})", None
    if ctx.proof_required:
        side = Path(row["path"]).with_name(Path(row["path"]).stem + ".proof.json")
        try:
            proof_mod.verify(proof_mod.load_file(side), gate="library-approval", episode_id=ctx.episode_id,
                             domain=ctx.domain_id, subject=sha)
        except Refused as error:
            return f"{label}: needs human proof ({error})", None
    return None, sha


def _cast_problems(spec: dict[str, Any], chars: list[str], approved: dict[str, set[str]]) -> list[str]:
    from ..layout.cast import load_cast
    try:
        cast = load_cast(Path(spec["cast"]))
    except Refused as error:
        return [f"cast: {error}"]
    problems = []
    for c in chars:
        if c not in cast:
            problems.append(f"cast: {c} is not bound to a canonical image")
        elif cast[c]["sha256"] not in approved.get(c, set()):
            problems.append(f"cast: canonical image of {c} is not one of its approved library picks")
    return problems


def evaluate(ctx: RunContext, spec: dict[str, Any]) -> tuple[list[str], int, int]:
    """``(problems, approved_slots, required_slots)``; empty problems = gate holds."""
    req = Path(spec["requirements"])
    if not req.is_file():
        return [f"requirement manifest {req.name} does not exist"], 0, 0
    chars, kinds, slots = _requirements(req)
    problems = _slot_problems(chars, kinds, slots)
    approved: dict[str, set[str]] = {}
    done = 0
    for slot in slots:
        problem, sha = _approval_problem(ctx, Path(spec["library_dir"]), slot)
        if problem:
            problems.append(problem)
        else:
            done += 1
            approved.setdefault(slot["character"], set()).add(str(sha))
    problems.extend(_cast_problems(spec, chars, approved))
    return problems, done, len(chars) * sum(kinds.values())
