"""``jjv layout check``: validate every brief, continuity for every adjacent shot pair, placement text per shot.

CPU only (``scene_layout.py`` is stdlib). A scaffold that was never filled in, a draft status or an invalid brief
fails the check; a continuity MISMATCH between two different layouts is reported (it restricts the transition
type, it is not an error); a pair that cannot be compared (domain/aspect/brief problem) fails the check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file, write_json_atomic, write_atomic
from .plan import PLAN_FILE, PLAN_SCHEMA
from .tool import scene_layout_json, tool_pins


def load_plan(layout_dir: Path) -> dict[str, Any]:
    plan = read_json(Path(layout_dir) / PLAN_FILE)
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise Uncertain(f"{PLAN_FILE} in {layout_dir} is not a {PLAN_SCHEMA} document")
    return plan


def brief_path(layout_dir: Path, plan: dict[str, Any], shot: str) -> Path:
    """The brief a shot is drawn from (a carry shot uses the layout of its cut)."""
    row = next((s for s in plan["shots"] if s["shot"] == shot), None)
    if row is None:
        raise Refused(f"shot {shot!r} is not in {PLAN_FILE}")
    owner = next(s for s in plan["shots"] if s["shot"] == row["layout_of"])
    return Path(layout_dir) / owner["brief"]


def _scaffold_open(brief: dict[str, Any]) -> bool:
    return ((brief.get("provenance") or {}).get("jjv_scaffold") or {}).get("filled") is False


def check_brief(path: Path, *, allow_draft: bool) -> dict[str, Any]:
    brief = read_json(path)
    code, parsed, stderr = scene_layout_json("validate", str(path))
    findings = (parsed or {}).get("findings", []) if isinstance(parsed, dict) else []
    errors = [f for f in findings if f.get("level") == "error"]
    problems = [f"{f['code']}: {f['message']}" for f in errors]
    if _scaffold_open(brief):
        problems.append("SCAFFOLD_UNFILLED: provenance.jjv_scaffold.filled is false; fill the geometry first")
    if brief.get("status") == "draft" and not allow_draft:
        problems.append("DRAFT_STATUS: brief status is 'draft' (set layout_guide_only or previz_only when final)")
    if parsed is None:
        problems.append(f"VALIDATE_UNREADABLE: exit {code}: {stderr[:200]}")
    return {"brief": path.name, "brief_sha256": sha256_file(path), "valid": code == 0 and not errors,
            "ok": not problems, "problems": problems, "warnings": [f for f in findings if f.get("level") != "error"]}


def check_pair(layout_dir: Path, plan: dict[str, Any], left: dict, right: dict) -> dict[str, Any]:
    a, b = brief_path(layout_dir, plan, left["shot"]), brief_path(layout_dir, plan, right["shot"])
    base = {"from": left["shot"], "to": right["shot"], "to_kind": right["kind"],
            "briefs": [a.name, b.name]}
    if a == b:
        return {**base, "same_layout": True, "classification": "AGREE",
                "allowed_transitions": ["dissolve", "wipe", "bloom", "whip", "cut"], "comparable": True}
    code, parsed, stderr = scene_layout_json("continuity", str(a), str(b))
    if not isinstance(parsed, dict) or "classification" not in parsed:
        return {**base, "same_layout": False, "comparable": False, "classification": None,
                "error": stderr[:300] or f"continuity exit {code}"}
    return {**base, "same_layout": False, "comparable": True, "classification": parsed["classification"],
            "allowed_transitions": parsed.get("allowed_transitions"), "offenders": parsed.get("offenders", []),
            "report": parsed}


def placement_for(layout_dir: Path, plan: dict[str, Any], row: dict, out_dir: Path) -> dict[str, Any]:
    path = brief_path(layout_dir, plan, row["shot"])
    code, parsed, stderr = scene_layout_json("placement-text", str(path))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("lines"), list):
        return {"shot": row["shot"], "ok": False, "error": stderr[:300] or f"placement-text exit {code}"}
    text = "\n".join(parsed["lines"]) + "\n"
    target = Path(out_dir) / f"{row['shot']}.txt"
    write_atomic(target, text.encode("utf-8"))
    return {"shot": row["shot"], "ok": True, "file": f"placement/{target.name}", "sha256": sha256_file(target),
            "lines": len(parsed["lines"])}


def check_layout(layout_dir: Path, *, allow_draft: bool = False) -> dict[str, Any]:
    layout_dir = Path(layout_dir)
    plan = load_plan(layout_dir)
    pins = tool_pins()
    if pins != plan.get("tool"):
        changed = sorted(k for k in pins if pins[k] != (plan.get("tool") or {}).get(k))
        raise Refused(f"the shared layout tool changed since the plan was written: {changed}; "
                      "re-plan into a new version folder")
    briefs: dict[str, dict] = {}
    for row in plan["shots"]:
        if row["kind"] == "cut":
            briefs[row["shot"]] = check_brief(layout_dir / row["brief"], allow_draft=allow_draft)
    pairs = [check_pair(layout_dir, plan, left, right) for left, right in zip(plan["shots"], plan["shots"][1:])]
    placement = [placement_for(layout_dir, plan, row, layout_dir / "placement")
                 for row in plan["shots"] if row["kind"] == "cut"]
    mismatches = [f"{p['from']}->{p['to']}" for p in pairs if p.get("classification") == "MISMATCH"]
    incomparable = [f"{p['from']}->{p['to']}" for p in pairs if not p["comparable"]]
    ok = (all(b["ok"] for b in briefs.values()) and not incomparable and all(p["ok"] for p in placement))
    report = {"schema": "jjv/layout-check/v1", "episode_id": plan["episode_id"], "ok": ok,
              "briefs": briefs, "pairs": pairs, "placement": placement,
              "continuity_mismatches": mismatches, "incomparable_pairs": incomparable, "tool": pins}
    write_json_atomic(layout_dir / "storyboard-check.json", report, mode="ascii", stamp=True)
    write_json_atomic(layout_dir / "continuity-plan.json",
                      {"schema": "jjv/continuity-plan/v1", "episode_id": plan["episode_id"], "pairs": [
                          {k: v for k, v in p.items() if k != "report"} for p in pairs]}, mode="ascii", stamp=True)
    return report
