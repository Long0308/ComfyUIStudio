"""``jjv video status``: chỉ đọc state + receipt chain; không gửi gì, không ghi gì."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import EngineError, Refused
from ..layout.context import Context
from . import accept as accept_mod
from . import routes as routes_mod
from . import state as state_mod

NEXT_ACTION = {
    "planned": "jjv video run --episode {ep} --out {out} [--lanes N] (prompt stage, CPU only)",
    "prompted": "jjv video run --episode {ep} --out {out} --completion --gpu-approved <receipt> (needs the domain H3 "
                "qualification receipt and {out}/h3-inputs.json from `jjv h3 inputs`)",
    "rendered": "jjv video run --episode {ep} --out {out} --completion [--upscale-backend B --gpu-approved <receipt>] "
                "(backend none records upscale_pending and waits for a qualified 1080p pilot)",
    "upscaled_1080": "jjv video accept --episode {ep} --out {out} --shot {shot} --pick|--reject --sha256 <1080p sha> "
                     "--by <person> --reason <what was watched>",
    "accepted": "done; the scheduler opens the next shot",
}


def _row(ctx: Context, out: Path, shot: str, stages: list[str]) -> dict[str, Any]:
    try:
        state = state_mod.read_state(out, shot)
    except EngineError as error:
        return {"shot": shot, "state": None, "problems": [str(error)], "chain_ok": False}
    problems: list[str] = []
    chain: dict[str, Any] = {}
    for key, entry in state["receipts"].items():
        try:
            state_mod.verify_ref(out, entry, key)
            chain[key] = {"path": entry["path"], "sha256": entry["sha256"], "ok": True}
        except EngineError as error:
            chain[key] = {"path": entry.get("path"), "ok": False}
            problems.append(str(error))
    index = state_mod.STATES.index(state["state"])
    return {"shot": shot, "order": state["order"], "state": state["state"], "revision": state["revision"],
            "next_stage": stages[index + 1] if index + 1 < len(stages) else None,
            "chain": chain, "chain_ok": not problems, "problems": problems, "gate": state.get("gate"),
            "rejected": state.get("rejected", []),
            "next_action": NEXT_ACTION[state["state"]].format(ep=ctx.episode_id, out=out, shot=shot)}


def status(ctx: Context, out: Path, shot: str | None = None, *, routes_path: Path | None = None) -> dict[str, Any]:
    plan = state_mod.read_plan(out)
    state_mod.require_plan_of(ctx, plan)
    routes = routes_mod.load_routes(routes_path)
    routes_mod.domain_route(ctx, routes)
    stages = list(plan["stages"])
    shots = [r["shot"] for r in plan["shots"] if shot is None or r["shot"] == shot]
    if shot is not None and not shots:
        raise Refused(f"shot {shot!r} is not in the plan ({[r['shot'] for r in plan['shots']]})")
    rows = [_row(ctx, out, name, stages) for name in shots]
    counts = {name: sum(1 for r in rows if r["state"] == name) for name in state_mod.STATES}
    produced = [r["shot"] for r in rows if r["state"] in ("upscaled_1080", "accepted")]
    progress = {"produced": len(produced), "accepted": counts["accepted"], "total": len(rows),
                "pending_review": [r["shot"] for r in rows if r["state"] == "upscaled_1080"]}
    current = next((r["shot"] for r in rows if r["state"] != "accepted"), None)
    final = accept_mod.final_review_record(out)
    return {"out": str(out), "plan_sha256": plan.get("shotlist", {}).get("sha256"), "stages": stages,
            "upscale": plan.get("upscale"), "counts": counts, "progress": progress, "current_shot": current,
            "complete": current is None and final is not None, "final_review": final is not None,
            "chain_ok": all(r["chain_ok"] for r in rows), "shots": rows}


__all__ = ["status"]
