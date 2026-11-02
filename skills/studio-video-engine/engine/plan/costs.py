"""The measured cost table (``recipes/plan/costs-v001.json``) and the arithmetic on it.

Every number carries a basis: ``measured`` (taken as-is), ``derived`` (arithmetic on measured numbers) or ``unmeasured``
(no number exists: the estimate is ``None`` and prints as ``?``; the planner never invents one).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..core.errors import Refused
from ..core.io import read_json, sha256_file

SCHEMA = "jjv/plan-costs/v1"
BASES = ("measured", "derived", "unmeasured")
_RANK = {b: i for i, b in enumerate(BASES)}


@dataclass(frozen=True)
class Estimate:
    seconds: float | None     # None = unmeasured
    basis: str                # measured | derived | unmeasured | n/a
    lines: tuple = ()         # "<units> x <s/unit> (<entry>)" for the audit trail


ZERO = Estimate(0.0, "n/a")


@dataclass(frozen=True)
class Costs:
    entries: dict
    path: str
    sha256: str
    version: str

    def price(self, items: Iterable[tuple[str, float]]) -> Estimate:
        """Sum ``units x seconds_per_unit`` over ``items``; one unmeasured entry makes the whole estimate unmeasured."""
        total, basis, lines = 0.0, "measured", []
        for name, units in items:
            entry = self.entries.get(name)
            if entry is None:
                raise Refused(f"cost table {self.path} has no entry {name!r}")
            if entry["basis"] == "unmeasured" or entry["seconds_per_unit"] is None or units is None:
                return Estimate(None, "unmeasured", tuple(lines) + (f"{name}: unmeasured",))
            total += units * entry["seconds_per_unit"]
            basis = max(basis, entry["basis"], key=_RANK.__getitem__)
            lines.append(f"{units:g} x {entry['seconds_per_unit']:g} s ({name}, {entry['basis']})")
        return Estimate(round(total, 3), basis, tuple(lines))


def load_costs(path: str | Path) -> Costs:
    p = Path(path)
    doc = read_json(p)
    if doc.get("schema") != SCHEMA:
        raise Refused(f"{p}: schema must be {SCHEMA!r}")
    for name, entry in doc["entries"].items():
        if entry.get("basis") not in BASES:
            raise Refused(f"{p}: entry {name!r} needs basis in {BASES}")
        if (entry["basis"] == "unmeasured") != (entry.get("seconds_per_unit") is None):
            raise Refused(f"{p}: entry {name!r}: unmeasured <=> seconds_per_unit null")
        if not entry.get("source"):
            raise Refused(f"{p}: entry {name!r} has no source (a number without a source is a guess)")
    return Costs(entries=doc["entries"], path=str(p), sha256=sha256_file(p), version=doc.get("version", "?"))
