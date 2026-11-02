"""Parse a 3D .cube LUT (strict: header, size, count, range). Malformed input is Refused, never guessed."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...core.errors import Refused


@dataclass(frozen=True)
class CubeLut:
    size: int
    table: tuple[tuple[float, float, float], ...]  # R fastest


def parse_cube(path: Path) -> CubeLut:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise Refused(f"LUT_INVALID: cannot read {path}: {error}") from error
    size: int | None = None
    domain_min, domain_max = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    rows: list[tuple[float, float, float]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        key = parts[0].upper()
        if key == "TITLE":
            continue
        if key == "LUT_3D_SIZE":
            if len(parts) != 2 or not parts[1].isdigit() or not 2 <= int(parts[1]) <= 129:
                raise Refused(f"LUT_INVALID: bad LUT_3D_SIZE at line {lineno}")
            size = int(parts[1])
            continue
        if key in ("DOMAIN_MIN", "DOMAIN_MAX"):
            try:
                vals = tuple(float(v) for v in parts[1:])
            except ValueError as error:
                raise Refused(f"LUT_INVALID: {key} at line {lineno} is not numeric") from error
            if len(vals) != 3:
                raise Refused(f"LUT_INVALID: {key} needs three numbers at line {lineno}")
            if key == "DOMAIN_MIN":
                domain_min = vals
            else:
                domain_max = vals
            continue
        if len(parts) != 3:
            raise Refused(f"LUT_INVALID: unexpected line {lineno}: {line[:60]!r}")
        try:
            rgb = tuple(float(v) for v in parts)
        except ValueError as error:
            raise Refused(f"LUT_INVALID: non-numeric entry at line {lineno}") from error
        if not all(0.0 <= v <= 1.0 for v in rgb):
            raise Refused(f"LUT_INVALID: entry outside 0..1 at line {lineno}: {rgb}")
        rows.append(rgb)  # type: ignore[arg-type]
    if size is None:
        raise Refused("LUT_INVALID: LUT_3D_SIZE header missing")
    if domain_min != (0.0, 0.0, 0.0) or domain_max != (1.0, 1.0, 1.0):
        raise Refused("LUT_INVALID: only the 0..1 domain is supported")
    if len(rows) != size ** 3:
        raise Refused(f"LUT_INVALID: {len(rows)} entries, expected {size ** 3} for size {size}")
    return CubeLut(size=size, table=tuple(rows))
