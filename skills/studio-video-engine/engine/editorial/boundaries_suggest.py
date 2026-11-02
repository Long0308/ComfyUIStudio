"""``jjv editorial boundaries suggest``: a transition preset per boundary, chosen BY RULE from the shots.

For every picture boundary (shots.json adjacency) it measures framing similarity on the SOURCE clips (last
editorial frame of A against first frame of B, the Q3 NCC), reads the declared continuity / motivation /
framing from an optional ``boundaries.json``, applies the user rule (:mod:`boundaries_suggest_rules`) and
writes ``boundaries-suggested.json``: per boundary the measured ncc, the rule applied, the chosen preset, the
alternatives the rule allows and whether a tail handle is needed (the native frames beyond the editorial cut a
tail preset plays; SeedVR2 must cover them).  Read-only on the episode; no GPU, no network, nothing rendered.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

from ..config.loader import SKILL_ROOT
from ..core.errors import Refused
from ..core.io import sha256_file
from . import boundaries_suggest_rules as rules
from . import presets, transitions
from .boundaries_suggest_measure import (QA_RECIPE, find_ffmpeg, measure_pair, probe_frames,
                                         q3_numbers)
from .timeline import INTRO, delivery_frames

SCHEMA = "jjv/boundaries-suggested/v1"
METHOD = ("ncc of 4x4 block means of a gray frame (analysis size from the QA recipe): last editorial frame of the "
          "outgoing clip vs first frame of the incoming clip")
BLOOM_FRAMES = 6
Measure = Callable[[dict, dict], dict]


def shot_grid(config: Any, shots: list[dict]) -> dict[str, Any]:
    """Delivery fps, native fps and every shot's first frame / delivery length (same arithmetic as the timeline)."""
    rates = config.domain["frame_rates"]
    fps = rates["delivery_fps"]
    cursor = round(fps * config.episode["timeline"]["intro_s"])
    starts, lengths = {}, {}
    for shot in shots:
        lengths[shot["shot"]] = delivery_frames(shot["clip"]["frames"], config.domain)
        starts[shot["shot"]] = cursor
        cursor += lengths[shot["shot"]]
    return {"fps": fps, "native_fps": rates["native_fps"], "intro_end": round(fps * config.episode["timeline"]["intro_s"]),
            "starts": starts, "lengths": lengths, "dialogue_end": cursor}


def tail_clip_for(root: Path, shot: dict, declared: dict | None) -> tuple[Path | None, str | None]:
    """The outgoing shot's native clip: the declared ``tail_clip`` or the ``<shot>-native`` file beside the editorial clip."""
    if declared and declared.get("tail_clip"):
        return root / declared["tail_clip"], "declared tail_clip"
    path = root / shot["clip"]["path"]
    sibling = path.with_name(path.name.replace("-editorial", "-native"))
    return (sibling, "sibling -native clip") if sibling != path and sibling.is_file() else (None, None)


def feasibility_for(root: Path, a: dict, b: dict, declared: dict | None, grid: dict, probe,
                    preset: str | None = None, frames: int | None = None) -> tuple:
    """``(feasibility per ready preset, outgoing shot, tail clip path | None, tail clip source)`` of one boundary.

    With ``preset`` / ``frames`` that preset's entry is judged at that frame count instead of its default."""
    clip, source = tail_clip_for(root, a, declared)
    outgoing = transitions.OutgoingShot(a["shot"], a["clip"]["frames"], grid["lengths"][a["shot"]])
    row = {"from_shot": a["shot"], "to_shot": b["shot"], "frames": frames or 0, "preset": preset}
    return transitions.feasibility(row, outgoing, clip, probe, grid["fps"], grid["native_fps"]), outgoing, clip, source


def _tail_entry(preset: presets.Preset, entry: dict, outgoing: transitions.OutgoingShot, grid: dict) -> dict:
    count = presets.tail_frames(preset, entry["frames"])
    out = {"needed": count > 0, "tail_output_frames": count, "native_frames_needed": entry["needs_tail_frames"],
           "have_native_frames": entry["have_native_frames"], "available": entry["available"],
           "native_index_range": None, "reason": entry["reason"]}
    if count and entry["have_native_frames"] is not None:
        native = entry["have_native_frames"] + outgoing.editorial_frames
        last = transitions._tail_figures(count, outgoing, native, grid["fps"], grid["native_fps"])["last"]
        out["native_index_range"] = [outgoing.editorial_frames, last]
    return out


def option(name: str, direction: int, feas: dict, outgoing, grid: dict) -> dict:
    preset = presets.get(name)
    entry = feas[name]
    dir_value = direction if preset.direction == "required" else 0
    return {"type": name, "label": preset.label, "frames": entry["frames"], "direction": dir_value,
            "params": presets.resolve_params(preset, None), "shows_both": preset.shows_both,
            "tail": _tail_entry(preset, entry, outgoing, grid)}


def _row_text(rule: str, boundary: dict, framing: dict) -> str:
    ncc = boundary["measured"]["ncc"]
    shown = "unmeasured" if ncc is None else f"ncc {ncc:.3f}"
    return f"suggested ({rule}, {shown}, framing {framing['framing']} by {framing['source']}): {rules.RULES[rule]}"


def _picture_boundary(a: dict, b: dict, start: int, declared: dict | None, ctx: dict) -> dict:
    grid, root = ctx["grid"], ctx["root"]
    measured = ctx["measure"](a, b)
    ncc = measured["ncc"]
    continuity = (declared or {}).get("continuity", "unknown")
    entry_kind = b["entry"]["kind"]
    item: dict[str, Any] = {
        "id": f"T{start}", "frame": start, "from": a["shot"], "to": b["shot"], "kind": "picture",
        "entry_kind": entry_kind, "measured": measured,
        "declared": {k: (declared or {}).get(k) for k in ("class", "type", "frames", "continuity", "framing", "g_bridge",
                                                          "motivation")},
        "warnings": []}
    if declared and declared.get("frame") not in (None, start):
        item["warnings"].append(f"declared boundary frame {declared['frame']} != timeline frame {start}")
    warn = rules.carry_check(entry_kind, ncc)
    if warn:
        item["warnings"].append(warn)
    if entry_kind == "carry":
        item.update(framing={"framing": "identical" if ncc is None or ncc >= rules.CARRY_NCC_MIN else rules.NEAR_SAME,
                             "source": "shots.json entry", "conflict": None}, rule="R1_carry",
                    chosen={"type": "none", "label": presets.get("none").label, "frames": 0, "direction": 0,
                            "params": {}, "shows_both": False,
                            "tail": {"needed": False, "tail_output_frames": 0, "native_frames_needed": 0,
                                     "have_native_frames": None, "available": True, "native_index_range": None,
                                     "reason": None}}, alternatives=[], motivated=None)
        return item
    framing = rules.classify(ncc, (declared or {}).get("framing"), ctx["q3"]["same_framing_ncc_min"])
    if framing["conflict"]:
        item["warnings"].append(framing["conflict"])
    motivated, cue = rules.motion_cue(declared or {})
    direction, dir_source = rules.infer_direction((declared or {}).get("motivation"))
    feas, outgoing, clip, clip_source = feasibility_for(root, a, b, declared, grid, ctx["probe"])
    order = rules.preference(framing["framing"], motivated)
    first = order[0]
    name, rule = next((n, r) for n, r in order if feas[n]["available"])   # a hard cut is always available
    item.update(framing=framing, rule=rule, motivated=({"value": motivated, "cue": cue} if framing["framing"] == rules.NEW_FRAMING
                                                      else None))
    if first[0] != name:
        item["fallback_from"] = {"type": first[0], "why": feas[first[0]]["reason"]}
    item["chosen"] = option(name, direction, feas, outgoing, grid)
    if item["chosen"]["direction"]:
        item["chosen"]["direction_source"] = dir_source
    names = rules.allowed(framing["framing"], continuity, ctx["pictures"], a["shot"], b["shot"])
    item["alternatives"] = [option(n, direction, feas, outgoing, grid) for n in names if n != name]
    item["tail_clip"] = {"path": clip.relative_to(root).as_posix() if clip and clip.is_relative_to(root) else None,
                         "source": clip_source}
    return item


def _row_of(item: dict, declared: dict | None) -> dict:
    """The boundary row (``schemas/boundaries.schema.json`` shape) that applies the choice."""
    chosen = item["chosen"]
    row: dict[str, Any] = {"frame": item["frame"], "from_shot": item["from"], "to_shot": item["to"],
                           "class": "carry" if item["entry_kind"] == "carry" else "cut", "type": chosen["type"],
                           "frames": chosen["frames"], "direction": chosen["direction"],
                           "motivation": _row_text(item["rule"], item, item["framing"]),
                           "continuity": (declared or {}).get("continuity", "unknown")}
    if item["framing"]["framing"] in (rules.SAME_FRAMING, rules.NEAR_SAME, rules.NEW_FRAMING):
        row["framing"] = rules.NEW_FRAMING if item["framing"]["framing"] == rules.NEW_FRAMING else rules.SAME_FRAMING
    if chosen["tail"]["needed"] and item["tail_clip"]["path"]:
        row["tail_clip"] = item["tail_clip"]["path"]
    return row


def _graphic_items(declared_rows: list[dict], names: set[str], grid: dict, first: str) -> list[dict]:
    out, seen = [], set()
    for row in declared_rows:
        if row["from_shot"] in names and row["to_shot"] in names:
            continue
        seen.add((row["from_shot"], row["to_shot"]))
        kept = {k: row[k] for k in ("frame", "from_shot", "to_shot", "class", "type", "frames", "direction", "params",
                                    "motivation", "continuity") if k in row}
        out.append({"id": f"T{row.get('frame', '?')}", "frame": row.get("frame"), "from": row["from_shot"],
                    "to": row["to_shot"], "kind": "graphic", "rule": "R7_graphic_keep", "chosen": {
                        "type": row["type"], "frames": row.get("frames"), "direction": row.get("direction", 0)},
                    "alternatives": [], "measured": {"ncc": None}, "row": kept, "warnings": []})
    if grid["intro_end"] > 0 and (INTRO, first) not in seen:
        bloom = presets.get("bloom")
        row = {"frame": grid["intro_end"], "from_shot": INTRO, "to_shot": first, "class": "cut", "type": "bloom",
               "frames": BLOOM_FRAMES, "direction": 0, "continuity": "unknown",
               "motivation": f"suggested (R8_intro_bloom): {rules.RULES['R8_intro_bloom']}"}
        out.append({"id": f"T{row['frame']}", "frame": row["frame"], "from": INTRO, "to": first, "kind": "graphic",
                    "rule": "R8_intro_bloom", "chosen": {"type": "bloom", "label": bloom.label, "frames": BLOOM_FRAMES,
                                                         "direction": 0},
                    "alternatives": [], "measured": {"ncc": None}, "row": row, "warnings": []})
    return out


def make_context(config: Any, shots: list[dict], declared: dict | None = None, *, ffmpeg: str | None = None,
                 measure: Measure | None = None, probe=probe_frames, allow: tuple = ()) -> dict:
    """Everything one boundary needs: grid, episode root, the measure / probe callables and the declared rows.
    ``measure(a_shot, b_shot)`` and ``probe(clip)`` can be replaced (tests, a cached run); by default they decode
    one frame per side with ffmpeg and count native frames."""
    if len(shots) < 1:
        raise Refused("shots.json has no shots")
    root = Path(config.episode_root)
    q3 = q3_numbers()
    if measure is None:
        exe = find_ffmpeg(ffmpeg)
        measure = lambda a, b: measure_pair(root, a, b, exe, q3["analysis"], allow)  # noqa: E731
    return {"grid": shot_grid(config, shots), "root": root, "measure": measure, "probe": probe, "q3": q3,
            "pictures": frozenset(s["shot"] for s in shots),
            "declared_rows": {(r["from_shot"], r["to_shot"]): r for r in (declared or {}).get("boundaries", [])}}


def suggest(config: Any, shots: list[dict], declared: dict | None = None, *, ctx: dict | None = None,
            hashes: dict | None = None, **ctx_args: Any) -> dict:
    """The ``jjv/boundaries-suggested/v1`` document (``ctx_args`` go to :func:`make_context`)."""
    ctx = ctx or make_context(config, shots, declared, **ctx_args)
    grid, q3, rows_by_pair = ctx["grid"], ctx["q3"], ctx["declared_rows"]
    items = [_picture_boundary(a, b, grid["starts"][b["shot"]], rows_by_pair.get((a["shot"], b["shot"])), ctx)
             for a, b in zip(shots, shots[1:])]
    for item in items:
        item["row"] = _row_of(item, rows_by_pair.get((item["from"], item["to"])))
        old_type = item["declared"]["type"]
        item["differs_from_declared"] = (None if old_type is None else
                                         presets.resolve_name(old_type, item["declared"]["frames"]) != item["chosen"]["type"])
    items += _graphic_items((declared or {}).get("boundaries", []), ctx["pictures"], grid, shots[0]["shot"])
    items.sort(key=lambda it: (it["frame"] is None, it["frame"] or 0))
    check_rows(items, ctx["pictures"])
    warnings = [f"{it['id']}: {w}" for it in items for w in it["warnings"]]
    return {"schema": SCHEMA, "episode_id": config.episode["episode_id"], "fps": grid["fps"],
            "native_fps": grid["native_fps"], "method": METHOD,
            "thresholds": {"same_framing_ncc_min": q3["same_framing_ncc_min"],
                           "layout_change_ncc_max": rules.LAYOUT_CHANGE_NCC_MAX, "carry_ncc_min": rules.CARRY_NCC_MIN,
                           "analysis": q3["analysis"], "source": QA_RECIPE.relative_to(SKILL_ROOT).as_posix()},
            "inputs": hashes or {}, "rules": rules.RULES, "boundaries": items,
            "rows": [it["row"] for it in items], "warnings": warnings, "summary": summary(items)}


def check_rows(items: list[dict], pictures: frozenset) -> None:
    """Every suggested picture row must pass the engine's own row rules (a bug here is a Refused, never silent)."""
    for it in items:
        if it["kind"] == "graphic":
            continue
        row = transitions.resolve_row(it["row"])
        try:
            transitions.check_row(row, pictures)
        except Refused as error:
            raise Refused(f"suggested row for {it['id']} breaks a boundary rule: {error}") from error


def summary(items: list[dict]) -> dict:
    by_type: dict[str, list[str]] = {}
    for it in items:
        by_type.setdefault(it["chosen"]["type"], []).append(it["id"])
    tails = [it["id"] for it in items if it.get("chosen", {}).get("tail", {}).get("needed")]
    return {"boundaries": len(items), "by_type": by_type, "tail_handle_needed": tails,
            "differs_from_declared": [it["id"] for it in items if it.get("differs_from_declared")],
            "unmeasured": [it["id"] for it in items if it["kind"] == "picture" and it["measured"]["ncc"] is None],
            "ncc_finite": all(it["measured"]["ncc"] is None or math.isfinite(it["measured"]["ncc"]) for it in items)}


def input_hashes(shots_path: Path | None, declared_path: Path | None) -> dict:
    return {"shots_sha256": sha256_file(shots_path) if shots_path else None,
            "boundaries_sha256": sha256_file(declared_path) if declared_path else None,
            "catalog_sha256": sha256_file(presets.CATALOG_PATH), "qa_recipe_sha256": sha256_file(QA_RECIPE)}
