"""Cổng domain cho bước logo: ``domain.post.logo_composite`` (bật, asset sha, tham số dò seed box).

Không bật = từ chối (không phải mặc định cho phép). Engine không biết domain nào; mọi số nằm trong JSON domain.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...core.errors import Refused
from ...core.io import sha256_file

_SHA = re.compile(r"^[0-9a-f]{64}$")
NOT_ENABLED = "LOGO_COMPOSITE_NOT_ENABLED"
SHA_MISMATCH = "LOGO_SHA_MISMATCH"
ASSET_INVALID = "LOGO_ASSET_INVALID"
DETECT_INVALID = "DETECT_CONFIG_INVALID"


@dataclass(frozen=True)
class DetectConfig:
    search_region: tuple[float, float, float, float]  # x, y, w, h as fractions of the frame
    mark_height_frac: tuple[float, float]              # min, max mark height as a fraction of frame height
    aspect_tolerance: float                            # +-fraction around the asset icon aspect
    mark_rgb: tuple[int, int, int]                     # thread colour; chroma direction gates candidates
    dark_threshold: int                                # black-hat response (0..255) that counts as "dark"
    fill_range: tuple[float, float]                    # component area / bbox area
    color_min_similarity: float                        # cosine of chroma vs mark_rgb chroma
    box_pad_frac: float                                # tracking box = mark rect grown by pad = round(frac * h)
    search_frames: int
    min_score: float
    min_margin: float
    min_agreement: float

    def as_dict(self) -> dict:
        return {"search_region": list(self.search_region), "mark_height_frac": list(self.mark_height_frac),
                "aspect_tolerance": self.aspect_tolerance, "mark_rgb": list(self.mark_rgb),
                "dark_threshold": self.dark_threshold, "fill_range": list(self.fill_range),
                "color_min_similarity": self.color_min_similarity, "box_pad_frac": self.box_pad_frac,
                "search_frames": self.search_frames, "min_score": self.min_score, "min_margin": self.min_margin,
                "min_agreement": self.min_agreement}


@dataclass(frozen=True)
class LogoPolicy:
    domain_id: str
    asset_path: str
    asset_sha256: str
    detect: DetectConfig | None
    variants: dict = field(default_factory=dict)  # name -> {path, sha256}: extra pinned logo files (e.g. white)


def _num(block: dict, key: str, lo: float, hi: float, *, integer: bool = False) -> float:
    value = block.get(key)
    ok = isinstance(value, int) and not isinstance(value, bool) if integer else (
        isinstance(value, (int, float)) and not isinstance(value, bool))
    if not ok or not (lo <= value <= hi):
        raise Refused(f"{DETECT_INVALID}: detect.{key} must be a number in [{lo}, {hi}], got {value!r}")
    return value


def _pair(block: dict, key: str, lo: float, hi: float, names: tuple[str, str] | None = None) -> tuple[float, float]:
    value = block.get(key)
    if names:
        if not isinstance(value, dict):
            raise Refused(f"{DETECT_INVALID}: detect.{key} must be an object")
        pair = (_num(value, names[0], lo, hi), _num(value, names[1], lo, hi))
    else:
        if not isinstance(value, list) or len(value) != 2:
            raise Refused(f"{DETECT_INVALID}: detect.{key} must be a 2-item list")
        pair = (_num({"v": value[0]}, "v", lo, hi), _num({"v": value[1]}, "v", lo, hi))
    if pair[0] >= pair[1]:
        raise Refused(f"{DETECT_INVALID}: detect.{key} min must be below max")
    return pair


def detect_config(block: Any) -> DetectConfig:
    if not isinstance(block, dict):
        raise Refused(f"{DETECT_INVALID}: detect must be an object")
    region = block.get("search_region")
    if not isinstance(region, dict):
        raise Refused(f"{DETECT_INVALID}: detect.search_region must be an object")
    x, y = _num(region, "x", 0, 1), _num(region, "y", 0, 1)
    w, h = _num(region, "w", 0, 1), _num(region, "h", 0, 1)
    if w <= 0 or h <= 0 or x + w > 1 + 1e-9 or y + h > 1 + 1e-9:
        raise Refused(f"{DETECT_INVALID}: detect.search_region must lie inside the frame with positive size")
    rgb = block.get("mark_rgb")
    if not isinstance(rgb, list) or len(rgb) != 3 or not all(
            isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 255 for v in rgb):
        raise Refused(f"{DETECT_INVALID}: detect.mark_rgb must be three integers 0..255")
    for key in ("min_score", "min_agreement", "search_frames"):
        if _num(block, key, 0, 240) <= 0:
            raise Refused(f"{DETECT_INVALID}: detect.{key} must be > 0 (a zero threshold would accept anything)")
    return DetectConfig(
        search_region=(x, y, w, h), mark_height_frac=_pair(block, "mark_height_frac", 0, 1, ("min", "max")),
        aspect_tolerance=_num(block, "aspect_tolerance", 0, 1), mark_rgb=(rgb[0], rgb[1], rgb[2]),
        dark_threshold=int(_num(block, "dark_threshold", 1, 254, integer=True)),
        fill_range=_pair(block, "fill_range", 0, 1), color_min_similarity=_num(block, "color_min_similarity", -1, 1),
        box_pad_frac=_num(block, "box_pad_frac", 0, 1), search_frames=int(_num(block, "search_frames", 1, 240, integer=True)),
        min_score=_num(block, "min_score", 0, 1), min_margin=_num(block, "min_margin", 0, 1),
        min_agreement=_num(block, "min_agreement", 0, 1))


def logo_policy(domain: dict) -> LogoPolicy:
    """The domain must declare ``post.logo_composite`` with ``enabled: true`` and the asset sha; else Refused."""
    name = domain.get("domain_id") if isinstance(domain, dict) else None
    post = domain.get("post") if isinstance(domain, dict) else None
    block = post.get("logo_composite") if isinstance(post, dict) else None
    if not isinstance(block, dict):
        raise Refused(f"{NOT_ENABLED}: domain {name!r} declares no post.logo_composite; the logo step is disabled")
    if block.get("enabled") is not True:
        raise Refused(f"{NOT_ENABLED}: domain {name!r} has post.logo_composite.enabled != true")
    asset = block.get("asset")
    if (not isinstance(asset, dict) or not isinstance(asset.get("path"), str) or not asset["path"]
            or not isinstance(asset.get("sha256"), str) or not _SHA.match(asset["sha256"])):
        raise Refused(f"{ASSET_INVALID}: domain {name!r} post.logo_composite.asset needs path and a 64-hex sha256")
    detect = detect_config(block["detect"]) if "detect" in block else None
    variants = block.get("assets", {})
    if not isinstance(variants, dict) or not all(
            isinstance(v, dict) and isinstance(v.get("path"), str) and v["path"]
            and isinstance(v.get("sha256"), str) and _SHA.match(v["sha256"]) for v in variants.values()):
        raise Refused(f"{ASSET_INVALID}: domain {name!r} post.logo_composite.assets entries need path and a 64-hex sha256")
    return LogoPolicy(domain_id=str(name), asset_path=asset["path"], asset_sha256=asset["sha256"], detect=detect,
                      variants={k: {"path": v["path"], "sha256": v["sha256"]} for k, v in variants.items()})


def require_asset(policy: LogoPolicy, logo: Path, declared_sha256: str | None) -> dict:
    """The logo file must hash to the domain-declared sha (and to the caller's declared sha when given)."""
    if declared_sha256 is not None:
        declared = declared_sha256.strip().lower()
        if not _SHA.match(declared):
            raise Refused(f"{SHA_MISMATCH}: --logo-sha256 must be a 64-hex sha256")
        if declared != policy.asset_sha256:
            raise Refused(f"{SHA_MISMATCH}: declared logo sha {declared[:12]} != domain asset sha "
                          f"{policy.asset_sha256[:12]} for domain {policy.domain_id!r}")
    if not Path(logo).is_file():
        raise Refused(f"{ASSET_INVALID}: logo file not found: {logo}")
    actual = sha256_file(Path(logo))
    if actual != policy.asset_sha256:
        raise Refused(f"{SHA_MISMATCH}: logo file sha {actual[:12]} != domain asset sha "
                      f"{policy.asset_sha256[:12]} for domain {policy.domain_id!r}")
    return {"path": str(logo), "sha256": actual, "domain_declared_sha256": policy.asset_sha256,
            "domain_declared_path": policy.asset_path}
