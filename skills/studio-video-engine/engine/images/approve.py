"""``jjv images approve``: a pick bound to one candidate sha256 (Studio will call this verb later).

Refused unless the candidate has a receipt, its bytes still match it, a reviewer and scope are named, and the
compare checklist holds a ``pass`` for EVERY item for that sha. Approvals are write-once versions
(``approval-v001.json`` ...); a later one records what it supersedes, and ``current_approval`` is stale-proof:
it re-checks the image bytes against the receipt every time.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_once
from ..layout.context import ROUTES_RECIPE, Context, load_recipe
from . import receipts
from .common import shot_inputs

APPROVAL_SCHEMA = "jjv/image-approval/v1"


def approvals_dir(out: Path, shot: str) -> Path:
    return Path(out) / shot / "approvals"


def checklist_items() -> list[str]:
    return list(load_recipe(ROUTES_RECIPE, "jjv/images-routes/v1")[0]["compare"]["checklist"])


def verified_candidate(out: Path, shot: str, sha: str) -> dict[str, Any]:
    """The receipt of ``sha`` whose image file still hashes to what the receipt recorded."""
    receipt = receipts.find_receipt(out, shot, sha)
    path = Path(receipt["output"]["path"])
    if not path.is_file() or sha256_file(path) != receipt["output"]["sha256"]:
        raise Refused(f"candidate {receipt['output']['sha256']} no longer matches its receipt ({path}); not usable")
    return receipt


def current_approval(out: Path, shot: str) -> dict[str, Any] | None:
    """The newest approval whose candidate bytes still match its receipt, else None."""
    folder = approvals_dir(out, shot)
    for path in sorted(folder.glob("approval-v[0-9][0-9][0-9].json"), reverse=True) if folder.is_dir() else []:
        row = read_json(path)
        try:
            verified_candidate(out, shot, row["candidate_sha256"])
        except Refused:
            return None  # the newest approval is stale: no older one is silently revived
        return {**row, "path": path.as_posix()}
    return None


def approve(ctx: Context, out: Path, shot: str, sha: str, *, reviewer: str, scope: str,
            checklist: Path | None) -> dict[str, Any]:
    if not reviewer.strip() or not scope.strip():
        raise Refused("--reviewer and --scope are required (an approval names who approved what, and for which use)")
    receipt = verified_candidate(out, shot, sha)
    full = receipt["output"]["sha256"]
    inputs = shot_inputs(out, shot)
    path = Path(checklist) if checklist else Path(out) / shot / "compare" / "checklist.json"
    if not path.is_file():
        raise Refused(f"no checklist at {path}: run `jjv images compare --shot {shot}` and fill it in")
    sheet = read_json(path)
    checks = (sheet.get("candidates") or {}).get(full)
    if not isinstance(checks, dict):
        raise Refused(f"the checklist has no entry for candidate {full}; re-run `images compare` after registering it")
    wanted = checklist_items()
    bad = {item: (checks.get(item) or {}).get("status", "missing") for item in wanted
           if (checks.get(item) or {}).get("status") != "pass"}
    if bad:
        raise Refused(f"candidate {full[:12]} is not approved: checklist items not 'pass': {bad}")
    previous = current_approval(out, shot)
    folder = approvals_dir(out, shot)
    count = len(list(folder.glob("approval-v*.json"))) if folder.is_dir() else 0
    file = folder / f"approval-v{count + 1:03d}.json"
    body = {"schema": APPROVAL_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id, "shot": shot,
            "candidate_sha256": full, "receipt_sha256": sha256_file(Path(receipt["receipt_path"])),
            "route": receipt["route"], "plan_sha256": inputs["plan_sha256"], "guide_sha256": inputs["guide"]["sha256"],
            "reviewer": reviewer.strip(), "scope": scope.strip(), "checks": {k: checks[k] for k in wanted},
            "checklist_sha256": sha256_file(path), "created_at": time.time(),
            "supersedes": previous["path"] if previous else None, "status": "accepted_image",
            "note": "covers the still only; motion, lip sync and continuity need their own reviews"}
    write_json_once(file, body, mode="ascii", stamp=True)
    return {"approval": file.as_posix(), "candidate_sha256": full, "shot": shot, "supersedes": body["supersedes"]}
