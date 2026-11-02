#!/usr/bin/env python3
"""make_lut.py - build a 3D .cube LUT from a small look JSON (stdlib only, no numpy, no network).

Usage:  python make_lut.py --look recipes/grade/jenniejoy_soft_v001.json --out recipes/grade/jenniejoy_soft_v001.cube
        python make_lut.py --look ... --out ... --size 33        (33 is the default and the shipped size)
Output: writes the .cube (deterministic bytes) and prints one JSON summary on stdout with the cube sha256 and the
        brand-colour dE2000 of the look (before vs after, measured through the same trilinear lookup the cube gives).
Exit:   0 ok, 1 refused (bad look JSON), 2 tool error.

Look order per pixel (gamma-encoded RGB in 0..1):
  warmth (R x(1+w), B x(1-w)) -> saturation (about Rec.709 luma) -> split tone (cool shadows, warm highlights)
  -> lift/gain (out = lift + x*(gain-lift)) -> gamma (x^(1/gamma)) -> contrast (pivot 0.5; <1 flattens, >1 S-curve).
The look JSON is the only place numbers live; this tool knows no domain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Sequence

SCHEMA = "jjv/grade-look/v1"
NAME = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
LUMA = (0.2126, 0.7152, 0.0722)
DEFAULT_SIZE = 33


def _num(look: dict, key: str, lo: float, hi: float, default: float | None = None) -> float:
    value = look.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not lo <= value <= hi:
        raise ValueError(f"{key} must be a number in [{lo}, {hi}], got {value!r}")
    return float(value)


def _triple(look: dict, key: str, lo: float, hi: float) -> tuple[float, float, float]:
    value = look.get(key)
    if (not isinstance(value, list) or len(value) != 3
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi for v in value)):
        raise ValueError(f"{key} must be three numbers in [{lo}, {hi}], got {value!r}")
    return (float(value[0]), float(value[1]), float(value[2]))


def validate_look(look: object) -> dict:
    """Check every field; raise ValueError with the field name. Returns the look unchanged."""
    if not isinstance(look, dict):
        raise ValueError("look must be a JSON object")
    if look.get("schema") != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA!r}")
    if not isinstance(look.get("name"), str) or not NAME.match(look["name"]):
        raise ValueError("name must match ^[a-z][a-z0-9_]{2,63}$ (no paths)")
    if not isinstance(look.get("domain_id"), str) or not NAME.match(look["domain_id"]):
        raise ValueError("domain_id must be a short identifier")
    _triple(look, "lift", 0.0, 0.2)
    _triple(look, "gamma", 0.5, 2.0)
    _triple(look, "gain", 0.5, 1.0)
    _num(look, "warmth", -0.1, 0.1)
    _num(look, "saturation", 0.0, 1.5)
    _num(look, "contrast", 0.5, 1.5)
    split = look.get("split", {"shadow_cool": 0.0, "highlight_warm": 0.0})
    if not isinstance(split, dict):
        raise ValueError("split must be an object")
    _num(split, "shadow_cool", 0.0, 0.1, 0.0)
    _num(split, "highlight_warm", 0.0, 0.1, 0.0)
    brand = look.get("brand", [])
    if not isinstance(brand, list):
        raise ValueError("brand must be a list")
    for item in brand:
        if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
                or not isinstance(item.get("hex"), str) or not HEX.match(item["hex"])):
            raise ValueError("each brand entry needs name and a #RRGGBB hex")
    # null = brand gate skipped for this look (JennieJoy: brand blue/red rule is NEWTECONS-only); missing = 3.0
    if look.get("brand_de_max", 3.0) is not None:
        _num(look, "brand_de_max", 0.0, 10.0, 3.0)
    defaults = look.get("post_defaults", {"grain": 0, "halation": 0, "soften": 0})
    if not isinstance(defaults, dict):
        raise ValueError("post_defaults must be an object")
    for key in ("grain", "halation", "soften"):
        _num(defaults, key, 0.0, 1.0, 0.0)
    return look


def load_look(path: Path) -> dict:
    return validate_look(json.loads(Path(path).read_text(encoding="utf-8")))


def _clamp(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def apply_look(look: dict, r: float, g: float, b: float) -> tuple[float, float, float]:
    """One pixel through the look. Inputs and outputs are gamma-encoded RGB in 0..1."""
    warmth = look.get("warmth", 0.0)
    sat = look.get("saturation", 1.0)
    split = look.get("split", {})
    shadow_cool = split.get("shadow_cool", 0.0)
    highlight_warm = split.get("highlight_warm", 0.0)
    contrast = look.get("contrast", 1.0)
    lift, gain, gamma = look.get("lift", [0, 0, 0]), look.get("gain", [1, 1, 1]), look.get("gamma", [1, 1, 1])

    r, b = _clamp(r * (1.0 + warmth)), _clamp(b * (1.0 - warmth))
    y = LUMA[0] * r + LUMA[1] * g + LUMA[2] * b
    r, g, b = (y + sat * (r - y), y + sat * (g - y), y + sat * (b - y))
    r, g, b = _clamp(r), _clamp(g), _clamp(b)
    y = LUMA[0] * r + LUMA[1] * g + LUMA[2] * b
    shadow_w, high_w = (1.0 - y) ** 2, y ** 2
    b = b + shadow_cool * shadow_w
    r = r + highlight_warm * high_w
    b = b - highlight_warm * high_w
    out = []
    for ch, value in enumerate((r, g, b)):
        v = _clamp(value)
        v = lift[ch] + v * (gain[ch] - lift[ch])
        v = _clamp(v) ** (1.0 / gamma[ch])
        if contrast <= 1.0:
            v = 0.5 + (v - 0.5) * contrast
        else:
            s = v * v * (3 - 2 * v)
            v = v + (contrast - 1.0) * (s - v)
        out.append(_clamp(v))
    return out[0], out[1], out[2]


def build_table(look: dict, size: int = DEFAULT_SIZE) -> list[tuple[float, float, float]]:
    """size^3 entries, R varies fastest (the .cube convention)."""
    if size < 2:
        raise ValueError("size must be >= 2")
    step = 1.0 / (size - 1)
    table: list[tuple[float, float, float]] = []
    for b_i in range(size):
        for g_i in range(size):
            for r_i in range(size):
                table.append(apply_look(look, r_i * step, g_i * step, b_i * step))
    return table


def write_cube(path: Path, table: Sequence[tuple[float, float, float]], size: int, title: str) -> str:
    """Write a .cube and return its sha256. Bytes depend only on the table, size and title."""
    if len(table) != size ** 3:
        raise ValueError(f"table has {len(table)} entries, expected {size ** 3}")
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    lines += [f"{r:.6f} {g:.6f} {b:.6f}" for (r, g, b) in table]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def lookup(table: Sequence[tuple[float, float, float]], size: int, rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """Trilinear lookup, the same maths a .cube consumer uses for an in-between colour."""
    pos = [_clamp(v) * (size - 1) for v in rgb]
    base = [min(int(math.floor(p)), size - 2) for p in pos]
    frac = [p - bi for p, bi in zip(pos, base)]
    out = [0.0, 0.0, 0.0]
    for dz in (0, 1):
        for dy in (0, 1):
            for dx in (0, 1):
                w = ((frac[0] if dx else 1 - frac[0]) * (frac[1] if dy else 1 - frac[1])
                     * (frac[2] if dz else 1 - frac[2]))
                idx = (base[0] + dx) + (base[1] + dy) * size + (base[2] + dz) * size * size
                entry = table[idx]
                out[0] += w * entry[0]
                out[1] += w * entry[1]
                out[2] += w * entry[2]
    return out[0], out[1], out[2]


def _srgb_to_lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(_clamp(v)) for v in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def cie_de2000(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    """CIEDE2000 (Sharma, Wu, Dalal 2005) with kL = kC = kH = 1."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cbar = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(cbar ** 7 / (cbar ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)

    def hue(a: float, b: float) -> float:
        return 0.0 if a == 0 and b == 0 else math.degrees(math.atan2(b, a)) % 360

    h1p, h2p = hue(a1p, b1), hue(a2p, b2)
    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        if dhp > 180:
            dhp -= 360
        elif dhp < -180:
            dhp += 360
    dhp_big = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    lbarp = (l1 + l2) / 2
    cbarp = (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbarp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbarp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbarp = (h1p + h2p + 360) / 2
    else:
        hbarp = (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hbarp - 30)) + 0.24 * math.cos(math.radians(2 * hbarp))
         + 0.32 * math.cos(math.radians(3 * hbarp + 6)) - 0.20 * math.cos(math.radians(4 * hbarp - 63)))
    d_theta = 30 * math.exp(-(((hbarp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cbarp ** 7 / (cbarp ** 7 + 25.0 ** 7))
    sl = 1 + 0.015 * (lbarp - 50) ** 2 / math.sqrt(20 + (lbarp - 50) ** 2)
    sc = 1 + 0.045 * cbarp
    sh = 1 + 0.015 * cbarp * t
    rt = -math.sin(math.radians(2 * d_theta)) * rc
    tc, th = dcp / sc, dhp_big / sh
    return math.sqrt(dlp ** 2 / sl ** 2 + tc ** 2 + th ** 2 + rt * tc * th)


def _hex_rgb(text: str) -> tuple[float, float, float]:
    return tuple(int(text[i:i + 2], 16) / 255.0 for i in (1, 3, 5))  # type: ignore[return-value]


def brand_de(look: dict, size: int = DEFAULT_SIZE) -> dict[str, float]:
    """dE2000 between each brand colour and its image through the look's cube (lookup, not formula)."""
    table = build_table(look, size)
    result: dict[str, float] = {}
    for item in look.get("brand", []):
        src = _hex_rgb(item["hex"])
        out = lookup(table, size, src)
        result[item["name"]] = round(cie_de2000(_srgb_to_lab(src), _srgb_to_lab(out)), 4)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_lut")
    parser.add_argument("--look", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    args = parser.parse_args(argv)
    try:
        look = load_look(args.look)
    except (OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1
    try:
        table = build_table(look, args.size)
        sha = write_cube(args.out, table, args.size, look["name"])
        de = brand_de(look, args.size)
    except (OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2
    limit = look.get("brand_de_max", 3.0)
    gate = None if limit is None else all(v <= limit for v in de.values())  # None = gate skipped, not a pass
    print(json.dumps({"ok": True, "name": look["name"], "size": args.size, "cube": str(args.out), "sha256": sha,
                      "brand_de2000": de, "brand_de_max": limit, "brand_de_pass": gate}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
