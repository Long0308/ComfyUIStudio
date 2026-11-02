"""Domain gate of the grade step: ``domain.post.grade`` must be enabled and declare each LUT by name, file and sha256.

Not enabled = refused (no default allow). A LUT is identified by its file name; the file bytes must hash to the
declared sha. Engine code names no domain; every number and name lives in the domain JSON.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.errors import Refused
from ...core.io import sha256_file

_SHA = re.compile(r"^[0-9a-f]{64}$")
NOT_ENABLED = "GRADE_NOT_ENABLED"
ASSET_INVALID = "GRADE_ASSET_INVALID"
LUT_NOT_DECLARED = "LUT_NOT_DECLARED"
LUT_SHA_MISMATCH = "LUT_SHA_MISMATCH"


@dataclass(frozen=True)
class GradePolicy:
    domain_id: str
    luts: dict  # name -> {"path": str, "sha256": str}


def grade_policy(domain: Any) -> GradePolicy:
    name = domain.get("domain_id") if isinstance(domain, dict) else None
    post = domain.get("post") if isinstance(domain, dict) else None
    block = post.get("grade") if isinstance(post, dict) else None
    if not isinstance(block, dict):
        raise Refused(f"{NOT_ENABLED}: domain {name!r} declares no post.grade; the grade step is disabled")
    if block.get("enabled") is not True:
        raise Refused(f"{NOT_ENABLED}: domain {name!r} has post.grade.enabled != true")
    luts = block.get("luts")
    if not isinstance(luts, dict) or not luts:
        raise Refused(f"{ASSET_INVALID}: domain {name!r} post.grade.luts must be a non-empty object")
    for key, entry in luts.items():
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"]
                or not isinstance(entry.get("sha256"), str) or not _SHA.match(entry["sha256"])):
            raise Refused(f"{ASSET_INVALID}: domain {name!r} LUT {key!r} needs path and a 64-hex sha256")
    return GradePolicy(domain_id=str(name), luts={k: {"path": v["path"], "sha256": v["sha256"]} for k, v in luts.items()})


def require_lut(policy: GradePolicy, lut: Path, declared_sha256: str | None = None) -> dict:
    """The LUT file must be declared (by file name) and hash to the declared sha; else Refused, before any encode."""
    lut = Path(lut)
    if declared_sha256 is not None:
        declared = declared_sha256.strip().lower()
        if not _SHA.match(declared):
            raise Refused(f"{LUT_SHA_MISMATCH}: --lut-sha256 must be a 64-hex sha256")
    if not lut.is_file():
        raise Refused(f"{ASSET_INVALID}: LUT file not found: {lut}")
    matches = [(k, v) for k, v in policy.luts.items() if Path(v["path"]).name == lut.name]
    if not matches:
        raise Refused(f"{LUT_NOT_DECLARED}: {lut.name} is not declared by domain {policy.domain_id!r}")
    name, entry = matches[0]
    actual = sha256_file(lut)
    if actual != entry["sha256"]:
        raise Refused(f"{LUT_SHA_MISMATCH}: {lut.name} sha {actual[:12]} != declared {entry['sha256'][:12]}")
    if declared_sha256 is not None and declared != entry["sha256"]:
        raise Refused(f"{LUT_SHA_MISMATCH}: declared sha != domain sha for {name!r}")
    return {"name": name, "path": str(lut), "sha256": actual, "domain_declared_path": entry["path"]}
