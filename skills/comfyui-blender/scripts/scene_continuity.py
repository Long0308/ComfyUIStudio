"""Shot-to-shot continuity: do two planned shot layouts agree enough to share a transition?

    python scene_layout.py continuity <briefA.json> <briefB.json> [--transition dissolve|wipe|bloom|whip|cut] [--json]

Entities are matched by id (or `track_as`) across the two briefs. For every shared entity the report
gives world displacement (m), facing change (deg), pose change, and the NDC box in each shot's own
camera with the centre shift and IoU when both boxes are composited at the same screen place.
AGREE = every shared entity is within tolerance; MISMATCH = list of offenders.

    AGREE     -> dissolve, wipe, bloom, whip, cut
    MISMATCH  -> bloom, whip, cut     (never a transition that shows both shots at once)

Exit codes: 0 agree, 1 mismatch (or --transition not allowed), 2 usage / unreadable / incomparable.
Honest scope: this proves the PLANNED layouts agree. It does not prove the generated H3 frames obey
them; the review still has to check pixels. Pure standard library.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import scene_layout as sl
from scene_set import SetResolution, resolve_set
from scene_track import Tracked, box_centre, box_iou, box_visible, collect, ndc_box

# POLICY/GUESS, NOT MEASURED: default tolerances. A character moved 0.15 m / turned 15 deg / shifted
# 2.5% of frame width is hard to see in a dissolve; none of these were tuned against real frames.
DEFAULT_RULES: dict[str, Any] = {
    "position_tol_m": 0.15, "facing_tol_deg": 15.0, "ndc_shift_tol": 0.05, "min_iou": 0.0, "include_set_props": False}
TRANSITIONS = ("dissolve", "wipe", "bloom", "whip", "cut")
SAFE_WHEN_MISMATCHED = ("bloom", "whip", "cut")
EPS = 1e-9
GRID = [round(-0.9 + 0.1 * i, 1) for i in range(19)]


class ContinuityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


@dataclass(frozen=True)
class Shot:
    brief: dict[str, Any]       # resolved + normalized
    resolution: SetResolution
    tracked: tuple[Tracked, ...]


def _prepare(raw: dict[str, Any], base: Path | None, label: str) -> Shot:
    findings, _ = sl.validate(raw, base)
    errors = [f for f in findings if f.level == "error"]
    if errors:
        raise ContinuityError("BRIEF_INVALID", f"brief {label} is invalid: " + " | ".join(f.line() for f in errors))
    resolution = resolve_set(raw, base)
    brief = sl.normalize(resolution.brief)
    return Shot(brief, resolution, tuple(collect(resolution, brief)))


def effective_rules(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Defaults, overridden by each brief's `continuity` block; where both declare a value the stricter wins."""
    blocks = [x.get("continuity", {}) for x in (a, b)]
    rules = dict(DEFAULT_RULES)
    for key in ("position_tol_m", "facing_tol_deg", "ndc_shift_tol"):
        values = [blk[key] for blk in blocks if key in blk]
        if values:
            rules[key] = min(values)
    values = [blk["min_iou"] for blk in blocks if "min_iou" in blk]
    if values:
        rules["min_iou"] = max(values)
    rules["include_set_props"] = any(blk.get("include_set_props", False) for blk in blocks)
    return rules


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _box_dict(box) -> dict[str, list[float]] | None:
    return {"x": [box[0], box[1]], "y": [box[2], box[3]]} if box else None


def _row(x: Tracked, y: Tracked, a: Shot, b: Shot, rules: dict[str, Any]) -> dict[str, Any]:
    offenders: list[str] = []
    key = x.key
    displacement = math.dist(x.position, y.position) if len(x.position) == len(y.position) else math.dist(x.position[:2], y.position[:2])
    if displacement > rules["position_tol_m"] + EPS:
        offenders.append(f"{key}: moved {displacement:.3f} m in the world (> {rules['position_tol_m']} m)")
    facing = angle_diff(x.facing_deg, y.facing_deg) if x.facing_deg is not None and y.facing_deg is not None else None
    if facing is not None and facing > rules["facing_tol_deg"] + EPS:
        offenders.append(f"{key}: facing changed {facing:.1f} deg (> {rules['facing_tol_deg']} deg)")
    if x.pose != y.pose:
        offenders.append(f"{key}: pose {x.pose} -> {y.pose}")
    box_a, box_b = ndc_box(a.brief, x.corners), ndc_box(b.brief, y.corners)
    vis = [box_visible(box_a), box_visible(box_b)]
    shift = iou = None
    if all(vis):
        (ax, ay), (bx, by) = box_centre(box_a), box_centre(box_b)
        shift, iou = math.hypot(ax - bx, ay - by), box_iou(box_a, box_b)
        if shift > rules["ndc_shift_tol"] + EPS:
            offenders.append(f"{key}: screen centre shifted {shift:.3f} NDC between the two cameras (> {rules['ndc_shift_tol']})")
        if rules["min_iou"] > 0 and iou < rules["min_iou"] - EPS:
            offenders.append(f"{key}: screen overlap IoU {iou:.2f} (< {rules['min_iou']})")
    return {"id": key, "ids": [x.id, y.id], "kind": x.kind, "displacement_m": displacement, "facing_change_deg": facing,
            "pose": [x.pose, y.pose] if x.pose or y.pose else None, "visible": vis,
            "ndc_a": _box_dict(box_a if vis[0] else None), "ndc_b": _box_dict(box_b if vis[1] else None),
            "ndc_centre_shift": shift, "iou": iou, "offenders": offenders, "ok": not offenders}


def _distance(box: dict[str, list[float]], x: float, y: float) -> float:
    return math.hypot(max(box["x"][0] - x, 0.0, x - box["x"][1]), max(box["y"][0] - y, 0.0, y - box["y"][1]))


def wipe_mask_origin(rows: list[dict[str, Any]], mismatch: bool) -> dict[str, Any]:
    """Screen point farthest from the shared entities (AGREE) or from the offenders (MISMATCH, hint only)."""
    boxes = [b for r in rows if not (mismatch and r["ok"]) for b in (r["ndc_a"], r["ndc_b"]) if b]
    best, best_d = (0.0, 0.0), -1.0
    for gx in GRID:
        for gy in GRID:
            d = min((_distance(b, gx, gy) for b in boxes), default=2.0)
            if d > best_d + EPS:
                best, best_d = (gx, gy), d
    x, y = best
    region = f"{'upper' if y > 0.33 else 'lower' if y < -0.33 else 'middle'} {'left' if x < -0.33 else 'right' if x > 0.33 else 'centre'}"
    note = ("avoids every shared entity in both shots" if not mismatch else
            "hint only: a wipe is NOT allowed for this pair; this is where no offending entity sits in either shot")
    return {"ndc": [x, y], "region": region, "clearance_ndc": best_d, "usable": not mismatch, "note": note}


def compare(raw_a: dict[str, Any], raw_b: dict[str, Any], base_a: Path | None = None, base_b: Path | None = None,
            transition: str | None = None) -> dict[str, Any]:
    a, b = _prepare(raw_a, base_a, "A"), _prepare(raw_b, base_b, "B")
    if a.brief["domain"] != b.brief["domain"]:
        raise ContinuityError("DOMAIN_MISMATCH", f"{a.brief['domain']} vs {b.brief['domain']}: continuity is only checked inside one domain")
    oa, ob = a.brief["output"], b.brief["output"]
    if oa["width"] * ob["height"] != ob["width"] * oa["height"]:
        raise ContinuityError("ASPECT_MISMATCH", f"{oa['width']}x{oa['height']} vs {ob['width']}x{ob['height']}: NDC boxes are not comparable")
    rules = effective_rules(raw_a, raw_b)
    same_set = a.resolution.set_id is not None and a.resolution.set_id == b.resolution.set_id
    by_key_b = {t.key: t for t in b.tracked}
    keys_a = {t.key for t in a.tracked}
    rows: list[dict[str, Any]] = []
    only_a: list[str] = []
    skipped = 0
    for x in a.tracked:
        y = by_key_b.get(x.key)
        if y is None:
            if not (same_set and x.from_set):
                only_a.append(x.key)
        elif same_set and x.from_set and y.from_set and not rules["include_set_props"]:
            skipped += 1
        else:
            rows.append(_row(x, y, a, b, rules))
    only_b = [t.key for t in b.tracked if t.key not in keys_a and not (same_set and t.from_set)]
    offenders = [line for r in rows for line in r["offenders"]]
    mismatch = bool(offenders)
    allowed = list(SAFE_WHEN_MISMATCHED if mismatch else TRANSITIONS)
    errors: list[dict[str, str]] = []
    if transition is not None and transition not in allowed:
        errors.append({"code": "TRANSITION_NOT_ALLOWED", "message":
                       f"'{transition}' shows both shots at once but the layouts disagree ({len(offenders)} offender(s)); allowed: {', '.join(allowed)}"})
    return {"a": a.brief["brief_id"], "b": b.brief["brief_id"], "domain": a.brief["domain"],
            "set_ids": [a.resolution.set_id, b.resolution.set_id], "classification": "MISMATCH" if mismatch else "AGREE",
            "tolerances": rules, "entities": rows, "only_in_a": only_a, "only_in_b": only_b, "skipped_set_props": skipped,
            "offenders": offenders, "allowed_transitions": allowed, "wipe_mask_origin": wipe_mask_origin(rows, mismatch),
            "transition": transition, "errors": errors,
            "scope": "planned layouts only: the generated H3 frames still need a pixel review"}


def format_report(r: dict[str, Any]) -> str:
    lines = [f"CONTINUITY {r['a']} -> {r['b']}: {r['classification']}",
             f"  domain {r['domain']}; {len(r['entities'])} shared entit(ies) compared, {r['skipped_set_props']} static set prop(s) skipped; "
             f"tolerances {r['tolerances']['position_tol_m']} m / {r['tolerances']['facing_tol_deg']} deg / NDC {r['tolerances']['ndc_shift_tol']}"]
    for e in r["entities"]:
        turn = "n/a" if e["facing_change_deg"] is None else f"{e['facing_change_deg']:.1f} deg"
        shift = "off-screen" if e["ndc_centre_shift"] is None else f"{e['ndc_centre_shift']:.3f} (iou {e['iou']:.2f})"
        lines.append(f"  {'ok  ' if e['ok'] else 'FAIL'} {e['id']} [{e['kind']}] moved {e['displacement_m']:.3f} m, turned {turn}, screen shift {shift}")
    for note, keys in (("only in A", r["only_in_a"]), ("only in B", r["only_in_b"])):
        if keys:
            lines.append(f"  INFO {note}: {', '.join(keys)}")
    for line in r["offenders"]:
        lines.append(f"  OFFENDER {line}")
    lines.append(f"  allowed: {', '.join(r['allowed_transitions'])}")
    w = r["wipe_mask_origin"]
    lines.append(f"  wipe mask origin{'' if w['usable'] else ' (hint only)'}: ndc [{w['ndc'][0]:.1f}, {w['ndc'][1]:.1f}] {w['region']}, clearance {w['clearance_ndc']:.2f}")
    lines.extend(f"  ERROR {e['code']}: {e['message']}" for e in r["errors"])
    lines.append(f"  scope: {r['scope']}")
    return "\n".join(lines)


def _cmd_continuity(args: argparse.Namespace) -> int:
    try:
        raw_a, raw_b = sl.load_brief(args.brief_a), sl.load_brief(args.brief_b)
        report = compare(raw_a, raw_b, args.brief_a.parent, args.brief_b.parent, args.transition)
    except ContinuityError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": exc.message}}, indent=2) if args.json else f"ERROR {exc.code}: {exc.message}")
        return 2
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 1 if report["classification"] == "MISMATCH" or report["errors"] else 0


def _cmd_placement(args: argparse.Namespace) -> int:
    import scene_placement
    brief = sl.load_brief(args.brief)
    findings, _ = sl.validate(brief, args.brief.parent)
    errors = [f for f in findings if f.level == "error"]
    if errors:
        for f in errors:
            print(f.line(), file=sys.stderr)
        print(f"refusing to describe an invalid brief: {len(errors)} validation error(s)", file=sys.stderr)
        return 1
    ids = [s for s in args.ids.split(",") if s] if args.ids else None
    lines = scene_placement.placement_lines(brief, args.brief.parent, ids, args.include_set)
    print(json.dumps({"brief_id": brief["brief_id"], "lines": lines}, indent=2) if args.json else "\n".join(lines))
    return 0


def add_parsers(sub: Any) -> None:
    c = sub.add_parser("continuity", help="do two shot briefs agree enough to share a transition? (planned layout only)")
    c.add_argument("brief_a", type=Path)
    c.add_argument("brief_b", type=Path)
    c.add_argument("--transition", choices=TRANSITIONS, help="exit 1 with TRANSITION_NOT_ALLOWED if this type is not allowed for the pair")
    c.add_argument("--json", action="store_true", help="machine-readable report")
    c.set_defaults(func=_cmd_continuity)
    p = sub.add_parser("placement-text", help="deterministic English placement sentences to repeat in H3 prompts")
    p.add_argument("brief", type=Path)
    p.add_argument("--ids", help="comma-separated entity ids to describe (default: actors, animals and shot props)")
    p.add_argument("--include-set", action="store_true", help="also describe static props that come from the shared set")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_placement)
