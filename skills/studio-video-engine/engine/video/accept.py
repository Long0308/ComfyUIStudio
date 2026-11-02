"""Group ``05 LƯU & QUAY TIẾP``: người dùng pick/reject bản 1080p theo sha256; đồng bộ với H3 ledger.

Acceptance gắn CẢ hai hash (native + 1080p).  Pick gọi ``h3 accept`` trên take native (ledger episode, hash-chained)
rồi chuyển state ``accepted``; reject ghi vào ledger và đưa shot về ``planned`` với revision mới (A9: hash bị
reject không bao giờ được pick lại, kể cả ở folder khác).  Final review là record riêng ở ``<out>/final-review/``.
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from ..comfy.staging import require_hash
from ..core.errors import Refused
from ..core.io import read_json, write_json_once
from ..h3 import accept as h3_accept
from ..h3 import ledger
from ..layout.context import Context
from ..voice.approval import check_listener
from . import state as state_mod
from . import tiers
from .render import h3_dir

ACCEPT_DIR = "acceptance"
FINAL_DIR = "final-review"
FINAL_SCHEMA = "jjv/video-final-review/v1"


def decide(ctx: Context, out: Path, shot: str, decision: str, *, by: str, reason: str, sha256: str | None,
           now: float | None = None) -> dict[str, Any]:
    if decision not in h3_accept.DECISIONS:
        raise Refused(f"decision must be one of {h3_accept.DECISIONS}")
    listener = check_listener(by)
    if not str(reason or "").strip():
        raise Refused("a reason is required for every pick/reject (what was watched)")
    plan = state_mod.read_plan(out)
    state_mod.require_plan_of(ctx, plan)
    tiers.validate(ctx, plan)
    state = state_mod.read_state(out, shot)
    if state["state"] != "upscaled_1080":
        raise Refused(f"{shot}: state is {state['state']!r}; acceptance needs the review-ready take of the current revision "
                      "(upscaled_1080); never pick a native or a pending shot")
    up = state_mod.verify_ref(out, state["receipts"].get("upscale"), "upscale")
    render = state_mod.verify_ref(out, state["receipts"].get("render"), "render")
    output = up["output"]
    if not sha256 or sha256.lower() != output["sha256"]:
        raise Refused(f"{shot}: --sha256 must equal the {state_mod.read_plan(out)['tier']} take you watched ({output['sha256'][:12]}); "
                      "a pick by filename or by the native sha is refused")
    require_hash(Path(output["path"]), output["sha256"], "reviewed take")
    native = render["native"]
    tier_record = None
    if render.get("promotion"):
        tiers.validate(ctx, state_mod.read_plan(out))
        if decision == "pick" and output["sha256"] in ledger.rejected_shas(ctx):
            raise Refused("TIER_TAKE_REJECTED: a rejected output cannot be picked in another folder")
        tier_record = ledger.append_entry(ctx, {"shot": shot, "decision": decision, "decided_by": listener,
                                              "reason": reason, "subject": {"sha256": output["sha256"]},
                                              "decided_unix": float(time.time() if now is None else now)})
        h3_record = None
    else:
        h3_record = h3_accept.decide(h3_dir(out, state["revision"]), shot, decision, ctx=ctx, by=listener, reason=reason,
                                     sha256=native["sha256"], now=now)
    record = {"schema": state_mod.ACCEPT_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id, "shot": shot,
              "revision": state["revision"], "decision": decision, "reason": str(reason).strip(), "decided_by": listener,
              "subject": {"native_sha256": native["sha256"], "output_1080_sha256": output["sha256"],
                          "output_1080_path": output["path"], "render_receipt": state["receipts"]["render"],
                          "upscale_receipt": state["receipts"]["upscale"]},
              "tier": state_mod.read_plan(out)["tier"], "tier_acceptance": tier_record,
              "h3_acceptance": {"record": h3_record["record"], "sha256": h3_record["sha256"]} if h3_record else None}
    folder = state_mod.shot_dir(out, shot) / ACCEPT_DIR
    path = folder / f"{state_mod.next_number(folder):03d}-{decision}.json"
    write_json_once(path, record, mode="utf8")
    if decision == "pick":
        fresh = state_mod.advance(out, state, "accepted", receipt_key="acceptance", receipt_path=path, now=now)
    else:
        fresh = state_mod.restart_revision(out, state, {"revision": state["revision"], "native_sha256": native["sha256"],
                                                        "output_1080_sha256": output["sha256"], "record": path.name},
                                           now=now)
    return {"shot": shot, "decision": decision, "state": fresh["state"], "revision": fresh["revision"],
            "record": str(path), "native_sha256": native["sha256"], "output_1080_sha256": output["sha256"]}


def final_review_record(out: Path) -> dict[str, Any] | None:
    folder = Path(out) / FINAL_DIR
    records = sorted(folder.glob("*.json")) if folder.is_dir() else []
    if not records:
        return None
    latest = read_json(records[-1])
    return latest if latest.get("decision") == "accept" else None


def final_review(ctx: Context, out: Path, *, by: str, note: str, decision: str = "accept") -> dict[str, Any]:
    reviewer = check_listener(by)
    if decision not in ("accept", "change"):
        raise Refused("final review decision must be accept or change")
    if not str(note or "").strip():
        raise Refused("--note is required for the final review")
    plan = state_mod.read_plan(out)
    state_mod.require_plan_of(ctx, plan)
    tiers.validate(ctx, plan)
    pending = [row["shot"] for row in plan["shots"] if state_mod.read_state(out, row["shot"])["state"] != "accepted"]
    if pending:
        raise Refused(f"final review needs every shot accepted; still pending: {pending}")
    subjects = {row["shot"]: state_mod.read_state(out, row["shot"])["receipts"]["acceptance"] for row in plan["shots"]}
    folder = Path(out) / FINAL_DIR
    path = folder / f"{state_mod.next_number(folder):03d}-{decision}.json"
    write_json_once(path, {"schema": FINAL_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
                           "decision": decision, "note": str(note).strip(), "decided_by": reviewer,
                           "subjects": subjects}, mode="utf8")
    return {"decision": decision, "record": str(path), "shots": sorted(subjects)}


__all__ = ["decide", "final_review", "final_review_record", "ACCEPT_DIR", "FINAL_DIR"]
