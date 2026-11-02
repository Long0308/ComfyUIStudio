"""``jjv images plan``: per shot {guide png sha, placement text sha, cast refs[sha], providers[]}.

Every file is hashed at plan time and re-hashed by every later verb, so a submit/adopt/compare that finds a
changed guide, placement text or reference refuses. Provider status is information only; a secret is never read
into the plan (OpenRouter: only whether the variable is set).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import sha256_file, write_json_once
from ..layout import check as layout_check
from ..layout import render as layout_render
from ..layout.cast import parse_pairs
from ..layout.context import Context, domain_policy, load_recipe, rel
from . import pool, receipts


def _provider_rows(ctx: Context, allowed: list[str], accounts: list[pool.Account]) -> list[dict[str, Any]]:
    local, _ = load_recipe("krea2-edit-local-v001", "jjv/images-local-recipe/v1")
    status = {
        "comfyui-local": {"qualification": local["qualification"]["status"], "needs": "--pilot until qualified"},
        "openrouter": {"key_present": bool(os.environ.get("OPENROUTER_API_KEY")), "needs": "--spend-ok"},
        "codex-adopt": {"needs": "a hand-made PNG + --prompt-file"},
        "codex-exec": {"accounts_configured": len(accounts), "auth_files_present": sum(a.auth_present for a in accounts)},
    }
    rows = [{"provider": p, "allowed": p in allowed, **status.get(p, {})} for p in status]
    return rows


def _guide(layout_dir: Path | None, shot: str, override: str | None) -> tuple[dict[str, str], str]:
    if override:
        return receipts.file_ref(override, "guide"), "--guide"
    found = layout_render.latest_beauty(layout_dir, shot) if layout_dir else None
    if found is None:
        raise Refused(f"shot {shot}: no guide PNG (pass --guide {shot}=PNG or render the layout first: "
                      f"`jjv layout render --layout ... --shot {shot}`)")
    return receipts.file_ref(found[0], "guide"), "layout render"


def _placement(layout_dir: Path | None, shot: str, override: str | None) -> dict[str, str]:
    path = Path(override) if override else (layout_dir / "placement" / f"{shot}.txt" if layout_dir else None)
    if path is None or not path.is_file():
        raise Refused(f"shot {shot}: no placement text (run `jjv layout check` or pass --placement {shot}=TXT)")
    return receipts.file_ref(path, "placement")


def build_images_plan(ctx: Context, out: Path, *, layout_dir: Path | None, shots: list[str], guides: list[str],
                      placements: list[str], extra_refs: list[str], providers: list[str] | None,
                      accounts: list[pool.Account]) -> dict[str, Any]:
    guide_map, placement_map = parse_pairs(guides, "--guide"), parse_pairs(placements, "--placement")
    layout_plan = layout_check.load_plan(layout_dir) if layout_dir else None
    names = shots or ([s["shot"] for s in layout_plan["shots"] if s["kind"] == "cut"] if layout_plan else [])
    if not names:
        raise Refused("no shots to plan: pass --shot (repeatable) or --layout")
    policy = domain_policy(ctx)
    allowed = [p for p in policy["allowed_providers"] if providers is None or p in providers]
    asked = [p for p in (providers or []) if p not in policy["allowed_providers"]]
    if asked:
        raise Refused(f"provider(s) {asked} are not allowed for domain {ctx.domain_id!r} "
                      f"(allowed: {policy['allowed_providers']}); nothing was written")
    extras: dict[str, list[dict]] = {}
    for item in extra_refs or []:
        head, sep, path = item.partition("=")
        shot_id, colon, role = head.partition(":")
        if not (sep and colon and shot_id and role and path):
            raise Refused(f"--ref expects SHOT:ROLE=PATH, got {item!r}")
        extras.setdefault(shot_id, []).append(receipts.file_ref(path, role))
    rows = []
    for shot in names:
        cast_refs: list[dict] = []
        if layout_plan:
            owner = next((s for s in layout_plan["shots"] if s["shot"] == shot), None)
            if owner is None:
                raise Refused(f"shot {shot!r} is not in the layout plan")
            cast_refs = [{"role": c["role"], "path": c["path"], "sha256": c["sha256"]} for c in owner["cast"]]
        guide, source = _guide(layout_dir, shot, guide_map.get(shot))
        rows.append({"shot": shot, "guide": guide, "guide_source": source,
                     "placement": _placement(layout_dir, shot, placement_map.get(shot)),
                     "refs": [receipts.verify_ref(r, f"{shot} cast ref {r['role']}") for r in cast_refs] + extras.get(shot, []),
                     "providers": _provider_rows(ctx, allowed, accounts)})
    unknown = sorted(set(extras) - set(names))
    if unknown:
        raise Refused(f"--ref names shot(s) {unknown} that are not being planned")
    plan = {"schema": receipts.PLAN_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
            "layout": {"dir": rel(layout_dir, ctx.root), "plan_sha256": sha256_file(Path(layout_dir) / "layout-plan.json")}
            if layout_dir else None, "allowed_providers": allowed, "shots": rows}
    Path(out).mkdir(parents=True, exist_ok=True)
    plan_sha = write_json_once(Path(out) / receipts.PLAN_FILE, plan, mode="ascii", stamp=True)
    return {"plan": receipts.PLAN_FILE, "plan_sha256": plan_sha, "shots": [
        {"shot": r["shot"], "guide_sha256": r["guide"]["sha256"], "placement_sha256": r["placement"]["sha256"],
         "refs": [x["sha256"] for x in r["refs"]], "providers": [p["provider"] for p in r["providers"] if p["allowed"]]}
        for r in rows]}
