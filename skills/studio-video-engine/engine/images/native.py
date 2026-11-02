"""``jjv images native``: the 864x480 copy of a candidate that H3 takes as its input anchor.

Bound to a receipt (no anchor without one) and, by default, to an approval for that exact sha; ``--allow-unapproved``
makes a diagnostic copy and says so in its receipt. The size is recipe data; the resize is Lanczos on the whole
frame (a source whose aspect ratio is off by more than the tolerance is refused unless ``--center-crop``).

M4-f1: the copy is made under a temp name, published, and only then linked to its final name and receipted, so a
refused publish leaves no native file, receipt or folder behind (same rule as ``common.register``).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..comfy.staging import require_hash
from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from ..layout.context import ROUTES_RECIPE, Context, load_recipe
from . import approve as approve_mod
from . import imgutil, receipts, workflow_publish
from .common import link_final_then_receipt, scratch

NATIVE_SCHEMA = "jjv/native-anchor-receipt/v1"


def make_native(ctx: Context, out: Path, shot: str, sha: str, *, center_crop: bool, allow_unapproved: bool) -> dict[str, Any]:
    receipt = approve_mod.verified_candidate(out, shot, sha)
    full = receipt["output"]["sha256"]
    approval = approve_mod.current_approval(out, shot)
    approved = bool(approval and approval["candidate_sha256"] == full)
    if not approved and not allow_unapproved:
        raise Refused(f"candidate {full[:12]} has no current approval: run `jjv images approve` first "
                      "(or --allow-unapproved for a diagnostic copy)")
    spec = load_recipe(ROUTES_RECIPE, "jjv/images-routes/v1")[0]["native"]
    folder = Path(out) / shot / "native"
    name = f"{shot}-native{spec['width']}-{full[:12]}"
    png, record = folder / f"{name}.png", folder / f"{name}.receipt.json"
    if record.is_file():
        row = read_json(record)
        if not png.is_file() or sha256_file(png) != row["native"]["sha256"]:
            raise Refused(f"{record} exists but {png.name} no longer matches it")
        review = workflow_publish.publish_native(ctx, shot, {**row, "receipt_path": record.as_posix()}, receipt)
        return {**row, "receipt_path": record.as_posix(), "review_workflow": review, "reused": True}
    if record.exists():
        raise Refused(f"{record} exists but is not a receipt file")
    with scratch(folder) as work:
        staged = work.temp(f"{name}.png")
        info = imgutil.native_copy(Path(receipt["output"]["path"]), staged, spec["width"], spec["height"],
                                   tolerance=spec["aspect_tolerance"], center_crop=center_crop)
        new_sha = sha256_file(staged)
        if png.exists():
            require_hash(png, new_sha, "existing native anchor")
        body = {"schema": NATIVE_SCHEMA, "episode_id": ctx.episode_id, "shot": shot, "created_at": time.time(),
                "source": {"sha256": full, "path": receipt["output"]["path"], "receipt_sha256": sha256_file(Path(receipt["receipt_path"])),
                           "width": receipt["output"]["width"], "height": receipt["output"]["height"]},
                "native": {"path": png.resolve().as_posix(), "sha256": new_sha, **info, **receipts.png_info(staged)},
                "anchor_approved": approved, "approval": approval["path"] if approved else None,
                "note": "derivative of the source bytes above; H3 binds this sha256 as its input image"}
        # Publish reads the staged copy; the receipt it records names the final path.
        publish_row = {**body, "receipt_path": record.as_posix(),
                       "native": {**body["native"], "path": staged.as_posix()}}
        review = workflow_publish.publish_native(ctx, shot, publish_row, receipt)
        # Publish has succeeded: only now do the anchor and its receipt get their final names
        # (a failed receipt write removes the anchor again, but only if this call created it).
        link_final_then_receipt(staged, png, new_sha, "native anchor", record, body)
    return {**body, "receipt_path": record.as_posix(), "review_workflow": review, "reused": False}
