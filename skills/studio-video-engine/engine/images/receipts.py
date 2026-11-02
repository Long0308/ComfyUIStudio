"""Image receipts: no anchor without a receipt (a lesson of the first episode, whose S02_A anchor had none).

Layout of an images folder ``OUT``::

    images-plan.json                      write-once plan (guide/placement/cast shas per shot)
    <shot>/candidates/<sha12>.png         the exact bytes of every candidate
    <shot>/candidates/<sha12>.receipt.json  jjv/image-receipt/v1, write-once, one per candidate sha
    <shot>/native/ <shot>/approvals/ <shot>/compare/   later stages, each bound to a candidate sha
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file

RECEIPT_SCHEMA = "jjv/image-receipt/v1"
PLAN_SCHEMA = "jjv/images-plan/v1"
PLAN_FILE = "images-plan.json"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# Keys build_candidate writes itself; the caller's ``fields`` may not reuse any of them.
IDENTITY_KEYS = ("schema", "episode_id", "domain", "shot", "status", "created_at", "plan_sha256", "output")


def png_info(path: Path) -> dict[str, int]:
    """Width/height/bytes from the IHDR; anything that is not a PNG is refused (candidates are PNG)."""
    path = Path(path)
    head = path.read_bytes()[:33] if path.is_file() else b""
    if len(head) < 24 or head[:8] != PNG_MAGIC or head[12:16] != b"IHDR":
        raise Refused(f"{path} is not a PNG file")
    width, height = struct.unpack(">II", head[16:24])
    return {"width": width, "height": height, "bytes": path.stat().st_size}


def file_ref(path: Path | str, role: str) -> dict[str, str]:
    path = Path(path)
    if not path.is_file():
        raise Refused(f"{role} file is missing: {path}")
    return {"role": role, "path": path.resolve().as_posix(), "sha256": sha256_file(path)}


def verify_ref(ref: dict[str, Any], label: str) -> dict[str, Any]:
    """Re-hash a recorded reference; a changed file is refused (a plan binds bytes, not names)."""
    path = Path(ref["path"])
    if not path.is_file():
        raise Refused(f"{label} is missing: {path}")
    actual = sha256_file(path)
    if actual != ref["sha256"]:
        raise Refused(f"{label} changed since the plan: recorded {ref['sha256']}, now {actual} ({path})")
    return ref


def load_plan(out: Path) -> dict[str, Any]:
    plan = read_json(Path(out) / PLAN_FILE)
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise Uncertain(f"{PLAN_FILE} in {out} is not a {PLAN_SCHEMA} document (run `jjv images plan` first)")
    return plan


def plan_shot(plan: dict[str, Any], shot: str) -> dict[str, Any]:
    row = next((s for s in plan["shots"] if s["shot"] == shot), None)
    if row is None:
        raise Refused(f"shot {shot!r} is not in {PLAN_FILE} (planned: {[s['shot'] for s in plan['shots']]})")
    return row


def candidate_dir(out: Path, shot: str) -> Path:
    return Path(out) / shot / "candidates"


def candidates(out: Path, shot: str) -> list[dict[str, Any]]:
    """Receipts of every candidate of ``shot``, oldest first."""
    rows = [{**read_json(p), "receipt_path": p.as_posix()} for p in sorted(candidate_dir(out, shot).glob("*.receipt.json"))]
    return sorted(rows, key=lambda r: (r.get("created_at", 0), r["output"]["sha256"]))


def find_receipt(out: Path, shot: str, sha: str) -> dict[str, Any]:
    """The receipt of candidate ``sha`` (a unique prefix of at least 8 hex digits is accepted), else Refused."""
    sha = sha.lower()
    if len(sha) < 8 or any(c not in "0123456789abcdef" for c in sha):
        raise Refused(f"--sha needs at least 8 hex digits of the candidate sha256, got {sha!r}")
    found = [r for r in candidates(out, shot) if r["output"]["sha256"].startswith(sha)]
    if len(found) != 1:
        raise Refused(f"{shot}: {len(found)} candidate receipts match sha {sha} (no anchor without a receipt: "
                      "register the image with `images adopt` or `images submit` first)")
    return found[0]


def build_candidate(*, episode_id: str, domain: str, shot: str, plan_sha256: str, created_at: float,
                    fields: dict[str, Any], output_path: Path, sha256: str, info: dict[str, int]) -> dict[str, Any]:
    """The one definition of a ``jjv/image-receipt/v1`` document (a pure dict; nothing is written).

    Key order is part of the receipt bytes: schema, identity, status, timestamps, plan sha, the caller's
    ``fields`` (route fields plus the plan-bound inputs), then ``output``. ``common.register`` is the only writer.
    A ``fields`` key that is one of ``IDENTITY_KEYS`` is Refused (it would overwrite the identity of the receipt).
    """
    clash = sorted(set(fields) & set(IDENTITY_KEYS))
    if clash:
        raise Refused(f"receipt fields may not overwrite identity keys: {', '.join(clash)}")
    return {"schema": RECEIPT_SCHEMA, "episode_id": episode_id, "domain": domain, "shot": shot,
            "status": "rendered_candidate", "created_at": created_at, "plan_sha256": plan_sha256, **fields,
            "output": {"path": Path(output_path).resolve().as_posix(), "sha256": sha256, **info}}
