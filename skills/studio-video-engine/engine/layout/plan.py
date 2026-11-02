"""``jjv layout plan``: set + one draft brief per cut shot, cast refs bound by sha256.

The engine scaffolds only (camera preset, proxy actors for the shot's speaker/listener); the agent fills the
geometry. A scaffold carries ``provenance.jjv_scaffold.filled = false`` and ``jjv layout check`` refuses it
until that flag is flipped, so a placeholder can never be mistaken for a layout.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_once
from . import cast as cast_mod
from .context import ROUTES_RECIPE, Context, domain_policy, load_recipe, rel
from .tool import tool_pins

PLAN_SCHEMA = "jjv/layout-plan/v1"
PLAN_FILE = "layout-plan.json"
KINDS = ("cut", "carry")


def _id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_").upper() or "ACTOR"


def episode_shots(ctx: Context) -> list[dict[str, Any]]:
    name = (ctx.episode.get("files") or {}).get("shots")
    if not name:
        raise Refused("episode.files.shots is not declared; a layout plan needs the shot list")
    document = read_json(ctx.episode_file.parent / name)
    shots = document.get("shots") if isinstance(document, dict) else None
    if not isinstance(shots, list) or not shots:
        raise Refused(f"{name}: no shots")
    return shots


def classify(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each shot with ``kind`` and ``layout_of`` (a carry shares the layout of the cut before it)."""
    rows: list[dict[str, Any]] = []
    last_cut: str | None = None
    for shot in shots:
        sid, kind = shot["shot"], (shot.get("entry") or {}).get("kind")
        if kind not in KINDS:
            raise Refused(f"shot {sid}: entry.kind {kind!r} is not one of {KINDS}")
        if kind == "cut":
            last_cut = sid
        elif last_cut is None:
            raise Refused(f"shot {sid} is a carry but no cut shot comes before it")
        rows.append({"shot": sid, "kind": kind, "layout_of": last_cut,
                     "speaker": shot.get("speaker"), "listener": shot.get("listener")})
    return rows


def scaffold_set(ctx: Context, scaffold: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "scene_set", "schema_version": 1, "set_id": f"{ctx.episode_id}-set", "domain": ctx.domain_id,
            "units": "meters",
            "purpose": "Scaffold SET written by `jjv layout plan`: replace the placeholder zone with the "
                       "episode's real static scenery before `layout check`.",
            "provenance": {"jjv_scaffold": {"filled": False}}, "ground": {"zones": [scaffold["set_zone"]]}}


def scaffold_brief(ctx: Context, row: dict[str, Any], cast: list[dict], policy: dict[str, Any],
                   scaffold: dict[str, Any], set_id: str) -> dict[str, Any]:
    roles = list(dict.fromkeys(r for r in (row["speaker"], row["listener"]) if r))
    xs = [scaffold["actor_x"], -scaffold["actor_x"]]
    bound = {c["role"]: c for c in cast}
    actors = []
    for index, role in enumerate(roles):
        actor = {"id": _id(role), "label": role, "role": "proxy", "pose": "standing", "position": [xs[index % 2], 0.0],
                 "facing_deg": 180.0 if index % 2 == 0 else 0.0, "head_top_z": scaffold["actor_head_top_z"],
                 "zone": scaffold["set_zone"]["id"], "proxy": "blocking_proxy"}
        if policy["cast_ref_in_brief"] and role in bound:
            actor["cast_ref"] = bound[role]["path"]
        actors.append(actor)
    return {"schema_version": 1, "brief_id": f"{ctx.episode_id}-{row['shot']}-layout", "domain": ctx.domain_id,
            "status": policy["brief_status"], "units": "meters",
            "purpose": f"Scaffold layout for shot {row['shot']}: geometry NOT filled in yet.",
            "notes": ["Written by `jjv layout plan`; the engine does not invent layouts. Replace the scaffold "
                      "actors/camera, then set provenance.jjv_scaffold.filled to true."],
            "provenance": {"jjv_scaffold": {"filled": False}}, "set": set_id,
            "actors": actors, "camera": dict(scaffold["camera"]), "output": dict(scaffold["output"])}


def build_plan(ctx: Context, out: Path, *, cast_file: Path | None, mapping: dict[str, str],
               allow_unbound: bool) -> dict[str, Any]:
    out = Path(out)
    policy = domain_policy(ctx)
    routes, routes_sha = load_recipe(ROUTES_RECIPE, "jjv/images-routes/v1")
    scaffold = routes["layout"]["scaffold"]
    rows = classify(episode_shots(ctx))
    cast = cast_mod.load_cast(cast_file) if cast_file else {}
    plan_roles = [r for row in rows if row["kind"] == "cut" for r in (row["speaker"], row["listener"]) if r]
    _, missing = cast_mod.bind(plan_roles, cast, mapping)
    if missing and not allow_unbound:
        raise Refused(f"no cast reference for {sorted(set(missing))}; pass --cast with those ids, "
                      "--map ROLE=CHARACTER_ID, or --allow-unbound (nothing was written)")
    set_doc = scaffold_set(ctx, scaffold)
    out.mkdir(parents=True, exist_ok=True)
    set_sha = write_json_once(out / "set.json", set_doc, mode="ascii")
    shots, unbound_all = [], []
    for row in rows:
        entry = {**row, "brief": None, "brief_sha256": None, "cast": []}
        if row["kind"] == "cut":
            bound, unbound = cast_mod.bind([r for r in (row["speaker"], row["listener"]) if r], cast, mapping)
            unbound_all += [f"{row['shot']}:{u}" for u in unbound]
            brief = scaffold_brief(ctx, row, bound, policy, scaffold, "../set.json")
            name = f"briefs/{row['shot']}.brief.json"
            entry.update(brief=name, brief_sha256=write_json_once(out / name, brief, mode="ascii"), cast=bound)
        shots.append(entry)
    plan = {"schema": PLAN_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
            "set": {"path": "set.json", "sha256": set_sha}, "shots": shots, "unbound_cast": unbound_all,
            "cast_file": {"path": rel(cast_file, ctx.root), "sha256": sha256_file(cast_file)} if cast_file else None,
            "routes_recipe_sha256": routes_sha, "tool": tool_pins()}
    plan_sha = write_json_once(out / PLAN_FILE, plan, mode="ascii", stamp=True)
    return {"plan": PLAN_FILE, "plan_sha256": plan_sha, "briefs": [s["brief"] for s in shots if s["brief"]],
            "carry": {s["shot"]: s["layout_of"] for s in shots if s["kind"] == "carry"},
            "unbound_cast": unbound_all}
