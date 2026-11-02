"""Compare a suggestion with an approved cut: ``--compare-config`` reads ``motion.transitions[]`` of a review config.

Names are normalised the way the QA recipe does (hyphen -> underscore, then ``type_aliases``: ``push`` is
``cut_push``, ``dip`` is ``dip_white``), so a hand-built config ('push', 'dip', 'card-switch') compares with
engine preset names.  Pure comparison: it reads one JSON file and writes nothing.
"""

from __future__ import annotations

from pathlib import Path

from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from .boundaries_suggest_measure import QA_RECIPE


def normalise(name: str) -> str:
    aliases = read_json(QA_RECIPE)["type_aliases"]
    flat = str(name).replace("-", "_")
    return aliases.get(flat, flat)


def compare(suggested: dict, config_path: Path) -> dict:
    document = read_json(config_path)
    rows = (document.get("motion") or {}).get("transitions")
    if not isinstance(rows, list):
        raise Refused(f"{config_path.name}: no motion.transitions list to compare with")
    approved = {row["id"]: row for row in rows}
    out = []
    for item in suggested["boundaries"]:
        row = approved.get(item["id"])
        if row is None:
            continue
        want = normalise(row["type"])
        got = item["chosen"]["type"]
        out.append({"id": item["id"], "kind": item["kind"], "approved": {"type": want, "frames": row.get("frames"),
                                                                          "direction": row.get("direction", 0)},
                    "suggested": {"type": got, "frames": item["chosen"].get("frames"),
                                  "direction": item["chosen"].get("direction", 0)},
                    "type_match": want == got,
                    "full_match": want == got and row.get("frames") == item["chosen"].get("frames")
                    and row.get("direction", 0) == item["chosen"].get("direction", 0)})
    pictures = [r for r in out if r["kind"] == "picture"]
    return {"config": config_path.name, "config_sha256": sha256_file(config_path), "compared": len(out),
            "picture": {"compared": len(pictures), "type_match": sum(r["type_match"] for r in pictures),
                        "full_match": sum(r["full_match"] for r in pictures)},
            "rows": out}
