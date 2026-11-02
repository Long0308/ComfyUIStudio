"""``jjv images compare``: one contact sheet per shot plus the review checklist.

Sheet = row 1: guide | each candidate; row 2: guide laid over each candidate at 50 % | the canonical cast refs.
Every cell is captioned with its role and sha256 prefix, the footer lists the checklist. The checklist file is
the reviewer's to edit (``unreviewed`` -> ``pass``/``fail``); re-running compare adds new candidates and never
overwrites a reviewed entry. Pixels still need a human/critic eye: the sheet only puts the evidence side by side.
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import canonical_sha256, read_json, sha256_file, write_atomic, write_json_once, write_once, pretty_json
from ..layout.context import ROUTES_RECIPE, Context, load_recipe
from . import approve as approve_mod
from . import imgutil, receipts
from .common import shot_inputs

CHECKLIST_SCHEMA = "jjv/image-checklist/v1"
MARGIN, CAPTION = 8, 18


def _cell(image: Any, caption: str, height: int) -> Any:
    tile = imgutil.fit_height(image, height)
    cell = imgutil.pil().new("RGB", (tile.width, height + CAPTION), (255, 255, 255))
    cell.paste(tile, (0, CAPTION))
    from PIL import ImageDraw

    ImageDraw.Draw(cell).text((2, 3), caption, fill=(10, 37, 64))
    return cell


def _row(cells: list[Any]) -> Any:
    width = sum(c.width for c in cells) + MARGIN * (len(cells) + 1)
    row = imgutil.pil().new("RGB", (max(width, 1), max((c.height for c in cells), default=1) + MARGIN), (247, 250, 253))
    x = MARGIN
    for cell in cells:
        row.paste(cell, (x, MARGIN // 2))
        x += cell.width + MARGIN
    return row


def build_sheet(guide: dict, cands: list[dict], refs: list[dict], items: list[str], cell_height: int, alpha: float) -> bytes:
    from PIL import ImageDraw

    g = imgutil.load_rgb(Path(guide["path"]))
    top = [_cell(g, f"guide {guide['sha256'][:8]}", cell_height)]
    bottom = []
    for c in cands:
        image = imgutil.load_rgb(Path(c["output"]["path"]))
        label = f"{c['route']} {c['output']['sha256'][:8]}"
        top.append(_cell(image, label, cell_height))
        overlay = imgutil.pil().blend(image, g.resize(image.size, imgutil.pil().Resampling.LANCZOS), alpha)
        bottom.append(_cell(overlay, f"guide {int(alpha * 100)}% over {c['output']['sha256'][:8]}", cell_height))
    for r in refs:
        bottom.append(_cell(imgutil.load_rgb(Path(r["path"])), f"ref {r['role']} {r['sha256'][:8]}", cell_height))
    rows = [_row(top), _row(bottom or [_cell(g, "(no overlays)", cell_height)])]
    footer = imgutil.pil().new("RGB", (max(r.width for r in rows), CAPTION * 2 + 4), (255, 255, 255))
    ImageDraw.Draw(footer).text((MARGIN, 4), "checklist: " + " | ".join(f"[ ] {i}" for i in items), fill=(10, 37, 64))
    rows.append(footer)
    sheet = imgutil.pil().new("RGB", (max(r.width for r in rows), sum(r.height for r in rows)), (247, 250, 253))
    y = 0
    for row in rows:
        sheet.paste(row, (0, y))
        y += row.height
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG")
    return buffer.getvalue()


def merge_checklist(path: Path, shot: str, shas: list[str], items: list[str]) -> dict[str, Any]:
    document = read_json(path) if path.is_file() else {"schema": CHECKLIST_SCHEMA, "shot": shot, "items": items,
                                                       "candidates": {}}
    for sha in shas:
        entry = document["candidates"].setdefault(sha, {})
        for item in items:
            entry.setdefault(item, {"status": "unreviewed", "note": ""})
    document["items"] = items
    write_atomic(path, pretty_json(document, mode="ascii"))
    return document


def compare(ctx: Context, out: Path, shot: str, shas: list[str] | None) -> dict[str, Any]:
    inputs = shot_inputs(out, shot)
    cands = ([approve_mod.verified_candidate(out, shot, s) for s in shas] if shas else
             [approve_mod.verified_candidate(out, shot, r["output"]["sha256"]) for r in receipts.candidates(out, shot)])
    if not cands:
        raise Refused(f"{shot} has no candidate receipts to compare (adopt or submit one first)")
    spec = load_recipe(ROUTES_RECIPE, "jjv/images-routes/v1")[0]["compare"]
    folder = Path(out) / shot / "compare"
    digest = canonical_sha256({"guide": inputs["guide"]["sha256"], "refs": [r["sha256"] for r in inputs["refs"]],
                               "candidates": sorted(c["output"]["sha256"] for c in cands)}, mode="ascii")[:12]
    sheet_bytes = build_sheet(inputs["guide"], cands, inputs["refs"], spec["checklist"], spec["cell_height"],
                              spec["overlay_alpha"])
    sheet = folder / f"compare-{digest}.png"
    write_once(sheet, sheet_bytes)
    checklist = folder / "checklist.json"
    merge_checklist(checklist, shot, [c["output"]["sha256"] for c in cands], spec["checklist"])
    record = {"schema": "jjv/image-compare/v1", "shot": shot, "created_at": time.time(),
              "sheet": {"path": sheet.resolve().as_posix(), "sha256": sha256_file(sheet)},
              "guide": inputs["guide"], "refs": inputs["refs"],
              "candidates": [{"sha256": c["output"]["sha256"], "route": c["route"], "receipt": c["receipt_path"]} for c in cands],
              "checklist": checklist.as_posix(), "checklist_items": spec["checklist"]}
    record_path = folder / f"compare-{digest}.json"
    if not record_path.exists():
        write_json_once(record_path, record, mode="ascii", stamp=True)
    return {"sheet": sheet.as_posix(), "sheet_sha256": record["sheet"]["sha256"], "checklist": checklist.as_posix(),
            "candidates": [c["output"]["sha256"] for c in cands], "checklist_items": spec["checklist"],
            "record": record_path.as_posix()}
