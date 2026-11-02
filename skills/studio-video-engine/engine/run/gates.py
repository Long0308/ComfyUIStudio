"""Human gates of the run: each one READS a receipt another verb (or a person) wrote; none is ever inferred.

- ``voice-listen-approval``: every job of ``voice-plan.json`` has a listen approval bound to its native take
  (``engine/voice/approval.py``); next step ``jjv voice approve``.
- ``images-approval``: every shot has a current image approval (``engine/images/approve.py``).
- ``h3-acceptance``: every shot's adopted take is picked (``engine/h3/accept.py``); next step ``jjv h3 accept``.
- ``music-approval`` / ``publish-approval``: a ``jjv run approve`` record (write-once, numbered) with verdict
  ``accept`` bound to the subject file's CURRENT sha256 (CR-M8: a record without a sha, or of an older version,
  never passes; a changed subject invalidates the approval).
- ``receipt-gate``: a recipe-named file/glob must exist (a qualification or pilot receipt a person/verb wrote).
- ``library-coverage``: every required character x kind x slot approved + cast bound (``engine/run/library_gate.py``).
- Human proof (recipe ``human_proof: required``): a record counts only with an issuer-signed proof that re-verifies at
  gate time (``engine/run/proof.py``; a file token = speed bump, NOT unforgeable); ``--by`` is a label, never authority.
- ``user-review``: a ``jjv run approve --gate user-review`` record for the CURRENT review film; verdict
  ``change`` consumes one of the ``limit`` user-facing versions; after ``limit`` changed versions the run stops
  until a person records ``override`` (allowed only once that limit is really reached; it resets the count).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_once
from . import proof as proof_mod
from .context import RunContext, Unresolved, resolve, shots_of
from .ledger import expand

APPROVAL_SCHEMA = "jjv/run-approval/v1"
VERDICTS = ("accept", "change", "override")
MACHINE_NAMES = ("agent", "bot", "claude", "codex", "engine", "gpt", "jjv", "machine", "system")
DEFAULT_REVIEW_LIMIT = 2   # user-facing versions before an override is needed (the recipe's human_gates.user-review.limit)


@dataclass(frozen=True)
class GateState:
    gate: str
    ok: bool
    detail: str
    next_step: str

    def as_dict(self) -> dict[str, Any]:
        return {"gate": self.gate, "ok": self.ok, "detail": self.detail, "next_step": self.next_step}


def spec_of(stage_gates: dict[str, dict[str, Any]] | None, gate: str, ctx: RunContext, stage_id: str) -> dict[str, str]:
    """The recipe's ``human_gates.<gate>`` block with every placeholder resolved."""
    raw = (stage_gates or {}).get(gate)
    if not isinstance(raw, dict):
        raise Refused(f"stage {stage_id!r}: human gate {gate!r} has no human_gates block in the recipe")
    return {k: resolve(v, ctx, stage_id) if isinstance(v, str) else v for k, v in raw.items()}


def records(approvals_dir: Path, gate: str) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(approvals_dir.glob(f"{gate}-[0-9][0-9][0-9].json")) if approvals_dir.is_dir() else []:
        doc = read_json(path)
        if isinstance(doc, dict) and doc.get("schema") == APPROVAL_SCHEMA and doc.get("gate") == gate:
            rows.append({**doc, "path": str(path)})
    return rows


def _changed_since_override(rows: list[dict[str, Any]]) -> set[str]:
    """Distinct versions a person asked to change since the last override: the count the review limit applies to."""
    last_override = max((i for i, r in enumerate(rows) if r.get("verdict") == "override"), default=-1)
    return {r["sha256"] for r in rows[last_override + 1:] if r.get("verdict") == "change" and r.get("sha256")}


def proved_records(ctx: RunContext, gate: str) -> list[dict[str, Any]]:
    """The gate's records; under ``proof_required`` only those whose signed proof re-verifies NOW (legacy: needs-human-proof)."""
    rows = records(ctx.approvals_dir, gate)
    if not ctx.proof_required:
        return rows
    kept = []
    for row in rows:
        try:
            proof_mod.verify(row.get("proof"), gate=gate, episode_id=ctx.episode_id, domain=ctx.domain_id,
                             verdicts=(str(row.get("verdict")),), subject=row.get("sha256"))
        except Refused:
            continue
        kept.append(row)
    return kept


def record_approval(ctx: RunContext, gate: str, *, by: str | None, note: str, verdict: str, sha256: str | None,
                    limit: int = DEFAULT_REVIEW_LIMIT, proof: dict[str, Any] | None = None) -> Path:
    """Write-once numbered record ``<runs_root>/approvals/<gate>-NNN.json`` of a person's decision."""
    if gate not in ("music-approval", "user-review", "publish-approval"):
        raise Refused(f"--gate must be one of music-approval, user-review, publish-approval (not {gate!r}); "
                      "voice, images and h3 approvals are recorded by their own verbs")
    principal = None
    if ctx.proof_required:   # a typed name is not authentication: only a verified signed proof makes a record
        if proof is None:
            raise Refused(f"gate {gate}: this recipe requires a signed human proof (--approval-file); a typed --by name "
                          "opens nothing")
        subject = sha256.lower() if sha256 else None
        principal = proof_mod.verify(proof, gate=gate, episode_id=ctx.episode_id, domain=ctx.domain_id,
                                     verdicts=(verdict,), subject=subject).principal
        if by and by.strip() != principal:
            raise Refused(f"--by {by!r} is not the principal of the proof ({principal!r})")
        by = principal
    if not (by or "").strip() or by.strip().lower() in MACHINE_NAMES:
        raise Refused(f"--by must name the person who decided, not {by!r}")
    if not note.strip():
        raise Refused("--note is required (what was reviewed and why)")
    if verdict not in VERDICTS:
        raise Refused(f"--verdict must be one of {VERDICTS}")
    if sha256 is not None and (len(sha256) != 64 or set(sha256.lower()) - set("0123456789abcdef")):
        raise Refused("--sha256 must be a 64-hex sha256 of the reviewed file")
    if verdict in ("accept", "change") and sha256 is None:
        raise Refused(f"--sha256 is required for {verdict}: the record binds the decision to the reviewed file "
                      "(sha256 of the subject); a record without it never satisfies a gate")
    if verdict == "override":
        if gate != "user-review":
            raise Refused("override is a user-review verdict (one more version beyond the limit); use accept")
        changed = _changed_since_override(proved_records(ctx, gate))
        if len(changed) < limit:
            raise Refused(f"override is allowed only after the user-review limit is reached ({limit} changed "
                          f"versions); {len(changed)} so far")
    ctx.approvals_dir.mkdir(parents=True, exist_ok=True)
    number = len(list(ctx.approvals_dir.glob(f"{gate}-[0-9][0-9][0-9].json"))) + 1
    path = ctx.approvals_dir / f"{gate}-{number:03d}.json"
    write_json_once(path, {"schema": APPROVAL_SCHEMA, "gate": gate, "episode_id": ctx.episode_id, "by": by.strip(),
                           "note": note.strip(), "verdict": verdict, "sha256": sha256.lower() if sha256 else None,
                           **({"proof": proof, "principal": principal} if proof is not None else {})},
                    mode="utf8", stamp=True)
    return path


def _subject_sha(spec: dict[str, Any]) -> tuple[str | None, str]:
    subject = spec.get("subject")
    if not subject:
        return None, "no subject file declared"
    path = Path(subject)
    if not path.is_file():
        return None, f"subject {path.name} does not exist yet"
    return sha256_file(path), path.name


def _record_gate(ctx: RunContext, gate: str, spec: dict[str, Any]) -> GateState:
    sha, label = _subject_sha(spec)
    rows = proved_records(ctx, gate)
    cmd = f"jjv run approve --episode {ctx.ref} --gate {gate} --verdict accept --by NAME --note TEXT"
    if sha is None:
        return GateState(gate, False, f"nothing to approve yet: {label}", "produce the subject first, then " + cmd)
    accepted = [r for r in rows if r.get("verdict") == "accept" and r.get("sha256") == sha]   # the CURRENT bytes only
    if accepted:
        return GateState(gate, True, f"accepted by {accepted[-1]['by']} ({Path(accepted[-1]['path']).name})", "")
    return GateState(gate, False, f"no accept record for {label} sha {sha[:12]} (an older or unbound record does not "
                     "count)", cmd + f" --sha256 {sha}")


def _user_review(ctx: RunContext, spec: dict[str, Any]) -> GateState:
    gate = "user-review"
    limit = int(spec.get("limit", 2))
    sha, label = _subject_sha(spec)
    rows = proved_records(ctx, gate)
    cmd = f"jjv run approve --episode {ctx.ref} --gate {gate} --verdict accept|change --by NAME --note TEXT"
    if sha is None:
        return GateState(gate, False, f"no review film yet: {label}", "render the review cut first, then " + cmd)
    if any(r.get("verdict") == "accept" and r.get("sha256") == sha for r in rows):
        return GateState(gate, True, f"version {sha[:12]} accepted", "")
    changed = _changed_since_override(rows)
    if sha in changed:
        return GateState(gate, False, f"version {sha[:12]} was reviewed: change requested; re-render a new version",
                         "apply the change, then re-run `jjv run episode --from edit`")
    if len(changed) >= limit:
        return GateState(gate, False, f"user review limit {limit} reached ({len(changed)} versions changed); "
                         "a further version needs the user's explicit go",
                         f"jjv run approve --episode {ctx.ref} --gate {gate} --verdict override --by NAME --note WHY")
    return GateState(gate, False, f"waiting for the user's review of version {len(changed) + 1} ({sha[:12]})",
                     cmd + f" --sha256 {sha}")


def _voice(ctx: RunContext, spec: dict[str, Any]) -> GateState:
    from ..voice import approval, receipts
    gate = "voice-listen-approval"
    out = Path(spec["out"])
    if not (out / receipts.PLAN_FILE).is_file():
        return GateState(gate, False, f"{receipts.PLAN_FILE} missing in {out.name}", "run `jjv voice plan` first")
    jobs = list(receipts.load_plan(out).get("jobs") or [])
    missing = approval.unapproved(out, jobs, ctx.episode_root)
    if missing:
        ids = ", ".join(str(m.get("request_id", "?")) for m in missing[:5])
        return GateState(gate, False, f"{len(missing)}/{len(jobs)} jobs without a listen approval: {ids}",
                         f"listen, then `jjv voice approve --episode {ctx.ref} --out {out} --job ID --by NAME --note TEXT`")
    return GateState(gate, True, f"{len(jobs)}/{len(jobs)} jobs listen-approved", "")


def _images(ctx: RunContext, spec: dict[str, Any]) -> GateState:
    from ..images.approve import current_approval
    gate = "images-approval"
    out = Path(spec["out"])
    shots = shots_of(Path(spec["shots"]))
    missing = [s for s in shots if current_approval(out, s) is None]
    if missing:
        return GateState(gate, False, f"{len(missing)}/{len(shots)} shots without an approved anchor: {missing[:5]}",
                         f"`jjv images compare` then `jjv images approve --episode {ctx.ref} --out {out} --shot S --sha H "
                         "--reviewer NAME --scope full`")
    return GateState(gate, True, f"{len(shots)}/{len(shots)} shots approved", "")


def approved_sha(spec: dict[str, Any], shot: str) -> str:
    from ..images.approve import current_approval
    record = current_approval(Path(spec["out"]), shot)
    sha = (record or {}).get("sha256") if isinstance(record, dict) else None
    if not isinstance(sha, str):
        raise Unresolved("approved_sha", f"shot {shot} has no current image approval")
    return sha


def _h3(ctx: RunContext, spec: dict[str, Any]) -> GateState:
    from ..h3 import accept
    from ..layout.context import load_context
    gate = "h3-acceptance"
    out = Path(spec["out"])
    shots = shots_of(Path(spec["shots"]))
    state: dict[str, str] = {}
    if out.is_dir():   # the accept API reads the episode-wide rejection ledger through the layout context (M7-f1)
        episode = load_context(str(ctx.episode_file))
        state = {row["shot"]: row["review"] for row in accept.status(out, ctx=episode)}
    pending = [s for s in shots if state.get(s) != "picked"]
    if pending:
        detail = ", ".join(f"{s}={state.get(s, 'not adopted')}" for s in pending[:5])
        return GateState(gate, False, f"{len(pending)}/{len(shots)} shots not picked: {detail}",
                         f"watch the take, then `jjv h3 accept --episode {ctx.ref} --out {out} --shot S --pick --by NAME --reason TEXT`")
    return GateState(gate, True, f"{len(shots)}/{len(shots)} shots picked", "")


def _receipt(spec: dict[str, Any]) -> GateState:
    """``receipt-gate``: holds only while a file (or glob) the recipe names exists; nothing is inferred or written."""
    gate = "receipt-gate"
    pattern, label = spec.get("file"), str(spec.get("label") or "receipt")
    next_step = str(spec.get("next") or "produce the receipt named by the recipe")
    if not pattern:
        return GateState(gate, False, f"{label}: the recipe names no file", next_step)
    found = expand(pattern)
    if found:
        return GateState(gate, True, f"{label}: {found[-1].name} present", "")
    return GateState(gate, False, f"{label}: no receipt at {pattern}", next_step)


def _library(ctx: RunContext, spec: dict[str, Any]) -> GateState:
    from . import library_gate
    gate = "library-coverage"
    try:
        problems, done, need = library_gate.evaluate(ctx, spec)
    except Refused as error:
        return GateState(gate, False, f"library requirements invalid: {error}", "fix the requirement manifest / cast")
    if problems:
        shown = "; ".join(problems[:4]) + (f"; +{len(problems) - 4} more" if len(problems) > 4 else "")
        return GateState(gate, False, f"{done}/{need} library slots approved: {shown}",
                         "approve every missing slot (`jjv images approve --library-out ...`), bind the picks into cast, "
                         f"re-run --from library")
    return GateState(gate, True, f"{done}/{need} library slots approved and cast-bound", "")


def check(ctx: RunContext, stage_id: str, stage_gates: dict[str, dict[str, Any]] | None, gate: str) -> GateState:
    """Evaluate one human gate read-only (safe in --dry-run)."""
    spec = spec_of(stage_gates, gate, ctx, stage_id)
    if gate == "user-review":
        return _user_review(ctx, spec)
    if gate in ("music-approval", "publish-approval"):
        return _record_gate(ctx, gate, spec)
    if gate == "library-coverage":
        return _library(ctx, spec)
    if gate == "receipt-gate":
        return _receipt(spec)
    if gate == "voice-listen-approval":
        return _voice(ctx, spec)
    if gate == "images-approval":
        return _images(ctx, spec)
    if gate == "h3-acceptance":
        return _h3(ctx, spec)
    raise Refused(f"unknown human gate {gate!r}")
