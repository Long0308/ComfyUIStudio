"""Shot acceptance gate: per shot, a human picks or rejects an adopted take, with a reason.

Records are write-once files ``<shot>/acceptance/NNN-<pick|reject>.json`` bound to the take's editorial sha256
(append-only history; the latest decision per sha wins, but a REJECTED sha can never be picked again).  A record
also pins the sha256 of the ``adopt.json`` it was decided on (publish re-checks it; older records lack it).  The
edit stage asks :func:`accepted_takes` / :func:`require_accepted`: a rejected or never-reviewed take has no
path to the cut.  Like voice approval, ``--by`` must name the person who watched, not a machine.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_once
from ..layout.context import Context
from ..voice.approval import check_listener
from .adopt import ADOPT_FILE
from .ledger import append_entry, ledger_path, rejected_shas

ACCEPT_SCHEMA = "jjv/h3-acceptance/v1"
ACCEPT_DIR = "acceptance"
DECISIONS = ("pick", "reject")


def _records(folder: Path) -> list[dict]:
    return [read_json(p) for p in sorted((folder / ACCEPT_DIR).glob("*.json"))]


def _state(records: list[dict], banned: set[str]) -> dict[str, str]:
    """sha -> pick|reject (latest wins in the folder); a sha rejected anywhere in the episode is ``reject``."""
    state: dict[str, str] = {}
    for record in records:
        state[record["subject"]["sha256"]] = record["decision"]
    for sha in banned:
        state[sha] = "reject"
    return state


def _pin(records: list[dict], sha: str) -> dict:
    """What the latest pick of ``sha`` saw: prompt, graph and (records since M8b(e)-f) the adopt.json sha256."""
    subject = next(r["subject"] for r in reversed(records) if r["decision"] == "pick" and r["subject"]["sha256"] == sha)
    return {key: subject.get(key) for key in ("prompt_id", "graph_sha256", "adopt_sha256")}


def _adopted(folder: Path) -> dict:
    path = folder / ADOPT_FILE
    if not path.is_file():
        raise Refused(f"{folder.name}: not adopted yet ({ADOPT_FILE} missing); run 'jjv h3 adopt' first")
    return read_json(path)


def decide(out: Path, shot: str, decision: str, *, ctx: Context, by: str, reason: str, sha256: str | None = None,
           now: float | None = None) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise Refused(f"decision must be one of {DECISIONS}")
    listener = check_listener(by)
    if not str(reason or "").strip():
        raise Refused("a reason is required for every pick/reject (what was watched: lips, identity, motion, seams)")
    folder = Path(out) / shot
    adopted = _adopted(folder)
    editorial = next(r for r in adopted["outputs"] if r["role"] == "editorial")
    if sha256 is not None and sha256.lower() != editorial["sha256"]:
        raise Refused(f"{shot}: --sha256 {sha256[:12]} is not the adopted editorial take {editorial['sha256'][:12]}")
    if sha256_file(Path(editorial["path"])) != editorial["sha256"]:
        raise Refused(f"{shot}: the adopted take on disk no longer matches its receipt")
    records = _records(folder)
    state = _state(records, rejected_shas(ctx))
    sha = editorial["sha256"]
    if decision == "pick":
        if state.get(sha) == "reject":
            raise Refused(f"{shot}: take {sha[:12]} was rejected; a rejected take is never picked "
                          "(prepare a new take instead)")
        others = [s for s, d in state.items() if d == "pick" and s != sha]
        if others:
            raise Refused(f"{shot}: take {others[0][:12]} is already picked; reject it first")
    record = {"schema": ACCEPT_SCHEMA, "episode_id": adopted["episode_id"], "shot": shot, "decision": decision,
              "reason": str(reason).strip(), "decided_by": listener,
              "subject": {"kind": "h3_editorial_take", "path": editorial["path"], "sha256": sha,
                          "prompt_id": adopted["prompt_id"], "graph_sha256": adopted["graph_sha256"],
                          "adopt_sha256": sha256_file(folder / ADOPT_FILE)},
              "decided_unix": float(time.time() if now is None else now)}
    append_entry(ctx, record)  # episode ledger first: a crash may over-reject, never under-reject
    name = f"{len(records) + 1:03d}-{decision}.json"
    write_json_once(folder / ACCEPT_DIR / name, record, mode="ascii")
    return {"shot": shot, "decision": decision, "sha256": sha, "record": str(folder / ACCEPT_DIR / name)}


def accepted_takes(out: Path, shots: list[str] | None = None, *, ctx: Context) -> list[dict]:
    """The picked, file-verified editorial take of every shot that has one (the only takes the edit may use)."""
    rows, banned = [], rejected_shas(ctx)
    for adopt_file in sorted(Path(out).glob(f"*/{ADOPT_FILE}")):
        folder = adopt_file.parent
        if shots and folder.name not in shots:
            continue
        records = _records(folder)
        picked = [s for s, d in _state(records, banned).items() if d == "pick"]
        if not picked:
            continue
        adopted = read_json(adopt_file)
        edit = next(r for r in adopted["outputs"] if r["role"] == "editorial")
        if edit["sha256"] in picked and sha256_file(Path(edit["path"])) == edit["sha256"]:
            rows.append({"shot": folder.name, "path": edit["path"], "sha256": edit["sha256"],
                         "prompt_id": adopted["prompt_id"], "acceptance": _pin(records, edit["sha256"])})
    return rows


def status(out: Path, *, ctx: Context) -> list[dict]:
    """Every adopted shot with its review state: pending | picked | rejected."""
    rows, banned = [], rejected_shas(ctx)
    for adopt_file in sorted(Path(out).glob(f"*/{ADOPT_FILE}")):
        folder = adopt_file.parent
        edit = next(r for r in read_json(adopt_file)["outputs"] if r["role"] == "editorial")
        verdict = _state(_records(folder), banned).get(edit["sha256"])
        rows.append({"shot": folder.name, "sha256": edit["sha256"],
                     "review": {"pick": "picked", "reject": "rejected"}.get(verdict, "pending")})
    return rows


def require_accepted(out: Path, shot: str, sha256: str, *, ctx: Context) -> None:
    if not any(r["shot"] == shot and r["sha256"] == sha256.lower() for r in accepted_takes(out, [shot], ctx=ctx)):
        raise Refused(f"{shot}: take {sha256[:12]} has no pick; rejected or unreviewed takes never reach the edit")


__all__ = ["decide", "accepted_takes", "status", "require_accepted", "ledger_path"]
