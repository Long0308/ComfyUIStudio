"""The registry gate (``jjv icons validate``): every spoken word has exactly one icon and the files are real.

Returns a report instead of raising: ``{ok, errors[], warnings[], pairs[], summary}`` with one entry per
finding ``{code, subject, message}``.  Thresholds come from ``recipes/editorial/icons-v001.json``.

Errors: E_REGISTRY_SHA, E_SCHEMA, E_TERM_MISSING, E_ICON_MISSING, E_SHARED_ICON (one icon for two words
unless the icon is marked ``shared``), E_DUP_IMAGE (same bytes under two icons), E_FILE_MISSING,
E_SHA_MISMATCH, E_ICON_SIZE, E_ICON_NO_ALPHA, E_PALETTE_DRIFT, E_STATUS, E_NOT_APPROVED (only with
``require_approved``), E_PAIR_SAME_IMAGE / E_PAIR_COLOUR / E_PAIR_HUE / E_PAIR_SHAPE, E_PAIR_FIELD,
E_ATTRIBUTE_MISSING, E_SCRIPT_DRIFT.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..core.io import read_json
from . import icons as reg
from .icons_build import plan_terms

MeasureFn = Callable[[Path, dict, str], dict]
MaskFn = Callable[[Path, dict, str], Any]


class _Findings:
    def __init__(self) -> None:
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def error(self, code: str, subject: str, message: str) -> None:
        self.errors.append({"code": code, "subject": subject, "message": message})

    def warn(self, code: str, subject: str, message: str) -> None:
        self.warnings.append({"code": code, "subject": subject, "message": message})


def _coverage(registry: dict, out: _Findings) -> None:
    for card, row in registry["cards"].items():
        if row["icon"] not in registry["icons"]:
            out.error("E_ICON_MISSING", card, f"card {card!r} points at icon {row['icon']!r}, which is not registered")
        for word in row["spoken"]:
            term = registry["terms"].get(word)
            if term is None:
                out.error("E_TERM_MISSING", word, f"spoken word {word!r} of card {card!r} has no icon")
            elif term["icon"] not in registry["icons"]:
                out.error("E_ICON_MISSING", word, f"spoken word {word!r} points at unregistered icon {term['icon']!r}")
    by_icon: dict[str, list[str]] = {}
    for word, term in registry["terms"].items():
        by_icon.setdefault(term["icon"], []).append(word)
    for icon_id, words in by_icon.items():
        entry = registry["icons"].get(icon_id)
        if len(words) > 1 and entry is not None:
            if entry.get("shared"):
                out.warn("W_SHARED_MARKED", icon_id, f"icon {icon_id!r} is shared by {words} (marked intentional)")
            else:
                out.error("E_SHARED_ICON", icon_id, f"icon {icon_id!r} is bound to {len(words)} spoken words {words}: "
                          "one icon per word (G-ICON-ART); give each word its own image or mark it shared")
    used = set(by_icon) | {row["icon"] for row in registry["cards"].values()}
    for icon_id in sorted(set(registry["icons"]) - used):
        out.warn("W_ORPHAN_ICON", icon_id, f"icon {icon_id!r} is registered but no word or card uses it")
    seen: dict[str, str] = {}
    for icon_id, entry in registry["icons"].items():
        other = seen.setdefault(entry["sha256"], icon_id)
        if other != icon_id and not (entry.get("shared") and registry["icons"][other].get("shared")):
            out.error("E_DUP_IMAGE", icon_id, f"icons {other!r} and {icon_id!r} are the same image bytes")


def _files(registry: dict, root: Path, recipe: dict, ffmpeg: str, measure_fn: MeasureFn, out: _Findings,
           require_approved: bool) -> dict[str, dict]:
    facts: dict[str, dict] = {}
    for icon_id, entry in registry["icons"].items():
        path = Path(root) / entry["png"]
        if entry["status"] not in recipe["statuses"]:
            out.error("E_STATUS", icon_id, f"status {entry['status']!r} is not one of {recipe['statuses']}")
        if entry["status"] != "approved":
            (out.error if require_approved else out.warn)(
                "E_NOT_APPROVED" if require_approved else "W_CANDIDATE", icon_id,
                f"icon {icon_id!r} is {entry['status']} (parent visual review pending)")
        if not path.is_file():
            out.error("E_FILE_MISSING", icon_id, f"{entry['png']} does not exist")
            continue
        if reg.sha256_file(path) != entry["sha256"]:
            out.error("E_SHA_MISMATCH", icon_id, f"{entry['png']}: sha256 on disk differs from the registry's")
            continue
        info = measure_fn(path, recipe, ffmpeg)
        facts[icon_id] = info
        width, height = info["size"]
        if width != height or min(width, height) < recipe["min_side_px"]:
            out.error("E_ICON_SIZE", icon_id, f"{width}x{height}: need a square of at least {recipe['min_side_px']} px")
        if not info["has_alpha"]:
            out.error("E_ICON_NO_ALPHA", icon_id, "the PNG has no alpha channel: the icon is an overlay")
        drift = max(abs(a - b) for a, b in zip(info["palette"]["rgb"], entry["palette"]["rgb"]))
        if drift > recipe["palette_drift_tolerance"]:
            out.error("E_PALETTE_DRIFT", icon_id, f"measured colour differs from the registry's by {drift:.1f}")
    return facts


def _pairs(registry: dict, root: Path, recipe: dict, ffmpeg: str, facts: dict, mask_fn: MaskFn,
           out: _Findings) -> list[dict]:
    rows: list[dict] = []
    by_norm = {reg.norm(k): row["icon"] for k, row in registry["terms"].items()}
    expected: dict[str, str] = {}
    for a, b in recipe["opposite_pairs"]:
        ia, ib = by_norm.get(reg.norm(a)), by_norm.get(reg.norm(b))
        if not (ia and ib):
            continue
        if ia != ib:
            expected[ia], expected[ib] = ib, ia
        row: dict = {"pair": [a, b], "icons": [ia, ib], "status": "PASS", "reasons": []}
        rows.append(row)
        ea, eb = registry["icons"].get(ia), registry["icons"].get(ib)
        if ea is None or eb is None:
            continue
        if ia == ib or ea["sha256"] == eb["sha256"]:
            row["reasons"].append(("E_PAIR_SAME_IMAGE", f"'{a}' and '{b}' use the identical icon image"))
        elif ia in facts and ib in facts:
            pa, pb = ea["palette"], eb["palette"]
            row["delta_e_file"] = round(reg.delta_e(pa["rgb"], pb["rgb"]), 1)
            if row["delta_e_file"] < recipe["min_delta_e_file"]:
                row["reasons"].append(("E_PAIR_COLOUR", f"colours too similar: delta E {row['delta_e_file']} < "
                                       f"{recipe['min_delta_e_file']}"))
            elif min(pa["saturation"], pb["saturation"]) >= recipe["hue_min_saturation"]:
                dist = abs(pa["hue"] - pb["hue"]) % 360.0
                row["hue_distance_deg"] = round(min(dist, 360.0 - dist), 1)
                if row["hue_distance_deg"] < recipe["min_hue_distance_deg"]:
                    row["reasons"].append(("E_PAIR_HUE", f"hues too close: {row['hue_distance_deg']} deg < "
                                           f"{recipe['min_hue_distance_deg']}"))
            row["silhouette_iou"] = round(reg.iou(mask_fn(Path(root) / ea["png"], recipe, ffmpeg),
                                                  mask_fn(Path(root) / eb["png"], recipe, ffmpeg)), 3)
            if row["silhouette_iou"] > recipe["max_silhouette_iou"]:
                row["reasons"].append(("E_PAIR_SHAPE", f"shapes too similar: silhouette IoU {row['silhouette_iou']} > "
                                       f"{recipe['max_silhouette_iou']}"))
        for code, text in row["reasons"]:
            out.error(code, f"{a}/{b}", f"pair {a}/{b}: {text}")
        row["reasons"] = [text for _, text in row["reasons"]]
        row["status"] = "FAIL" if row["reasons"] else "PASS"
    for icon_id, entry in registry["icons"].items():
        if entry.get("pair") != expected.get(icon_id):
            out.error("E_PAIR_FIELD", icon_id, f"pair is {entry.get('pair')!r}, the recipe pairs imply {expected.get(icon_id)!r}")
        if not entry.get("attribute"):
            if entry.get("pair") and recipe["attribute_required_for_pairs"]:
                out.error("E_ATTRIBUTE_MISSING", icon_id, f"icon {icon_id!r} is half of an opposite pair: its "
                          "distinguishing attribute must be written down")
            else:
                out.warn("W_ATTRIBUTE_MISSING", icon_id, f"icon {icon_id!r} has no attribute text")
    return rows


def _script_drift(registry: dict, script: dict, recipe: dict, out: _Findings) -> None:
    terms, cards = plan_terms(script.get("vocabulary_cards") or [], set(registry["icons"]), recipe["compound_separators"])
    if {k: v["icon"] for k, v in terms.items()} != {k: v["icon"] for k, v in registry["terms"].items()}:
        out.error("E_SCRIPT_DRIFT", "terms", "the spoken terms/icons the script implies differ from the registry")
    if {k: (v["icon"], v["spoken"]) for k, v in cards.items()} != \
            {k: (v["icon"], v["spoken"]) for k, v in registry["cards"].items()}:
        out.error("E_SCRIPT_DRIFT", "cards", "the vocabulary cards of the script differ from the registry's")


def validate_registry(registry: dict, *, root: Path, recipe: dict, ffmpeg: str, require_approved: bool = False,
                      script_path: Path | None = None, measure_fn: MeasureFn = reg.measure,
                      mask_fn: MaskFn = reg.silhouette) -> dict:
    out = _Findings()
    if registry.get("schema") != reg.SCHEMA:
        out.error("E_SCHEMA", "registry", f"schema is {registry.get('schema')!r}, expected {reg.SCHEMA}")
        return _report(registry, out, [])
    if registry.get("sha256") != reg.registry_sha256(registry):
        out.error("E_REGISTRY_SHA", "registry", "sha256 does not match the content (hand-edited?)")
    _coverage(registry, out)
    facts = _files(registry, root, recipe, ffmpeg, measure_fn, out, require_approved)
    pairs = _pairs(registry, root, recipe, ffmpeg, facts, mask_fn, out)
    if script_path is not None:
        _script_drift(registry, read_json(Path(script_path)), recipe, out)
    return _report(registry, out, pairs)


def _report(registry: dict, out: _Findings, pairs: list[dict]) -> dict:
    icons = registry.get("icons") or {}
    statuses = [e.get("status") for e in icons.values()]
    return {"ok": not out.errors, "errors": out.errors, "warnings": out.warnings, "pairs": pairs,
            "summary": {"version": registry.get("version"), "icons": len(icons), "spoken_terms": len(registry.get("terms") or {}),
                        "cards": len(registry.get("cards") or {}), "approved": statuses.count("approved"),
                        "candidate": statuses.count("candidate")}}
