"""Episode-level acceptance ledger: ONE append-only, hash-chained JSONL file per episode.

``<episode root>/engine/h3-acceptance-ledger.jsonl``.  Every pick/reject that ``accept`` writes into a
``--out`` folder is mirrored here, keyed by the take sha256, so re-preparing into a new folder cannot launder a
rejected take.  Each line carries ``prev`` (sha of the previous line) and ``line_sha256``; a rewritten, dropped
or reordered line breaks the chain and the ledger is refused (not trusted).  Known limits: ``--by`` is a name
check only (no authentication) and concurrent writers are not locked.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..core.errors import Refused
from ..core.io import canonical_sha256
from ..layout.context import Context

LEDGER_SCHEMA = "jjv/h3-acceptance-ledger/v1"
LEDGER_NAME = "h3-acceptance-ledger.jsonl"
GENESIS = "0" * 64


def ledger_path(ctx: Context) -> Path:
    return Path(ctx.root) / "engine" / LEDGER_NAME


def _seal(entry: dict) -> str:
    return canonical_sha256({k: v for k, v in entry.items() if k != "line_sha256"}, mode="ascii")


def read_ledger(ctx: Context) -> list[dict]:
    """All entries, chain-verified; a broken chain or foreign episode is ``Refused``."""
    path = ledger_path(ctx)
    if not path.is_file():
        return []
    entries, prev = [], GENESIS
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = json.loads(line)
        except ValueError as error:
            raise Refused(f"acceptance ledger {path.name} line {number} is not JSON: {error}") from error
        if (entry.get("schema"), entry.get("episode_id"), entry.get("prev")) != (LEDGER_SCHEMA, ctx.episode_id, prev) \
                or entry.get("line_sha256") != _seal(entry) or entry.get("seq") != number:
            raise Refused(f"acceptance ledger {path.name} line {number} was altered or does not chain; "
                          "the episode acceptance history cannot be trusted")
        entries.append(entry)
        prev = entry["line_sha256"]
    return entries


def append_entry(ctx: Context, record: dict) -> dict:
    """Append one decision (``record`` is the folder acceptance record) and return the sealed entry."""
    entries = read_ledger(ctx)
    entry = {"schema": LEDGER_SCHEMA, "seq": len(entries) + 1, "episode_id": ctx.episode_id, "shot": record["shot"],
             "decision": record["decision"], "sha256": record["subject"]["sha256"], "decided_by": record["decided_by"],
             "reason": record["reason"], "decided_unix": record["decided_unix"],
             "prev": entries[-1]["line_sha256"] if entries else GENESIS}
    entry["line_sha256"] = _seal(entry)
    path = ledger_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return entry


def rejected_shas(ctx: Context) -> set[str]:
    """Take shas rejected anywhere in the episode (a rejected take is never picked, in any folder)."""
    return {e["sha256"] for e in read_ledger(ctx) if e["decision"] == "reject"}


__all__ = ["ledger_path", "read_ledger", "append_entry", "rejected_shas"]
