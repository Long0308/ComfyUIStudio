"""Manifest nhiều điểm đánh dấu mỗi shot + nạp asset logo thật (có màu) theo biến thể color / white / n-only.

Seed box là ĐẦU VÀO đã đo (không đoán, không mặc định). Sai manifest = Refused cả lượt (chưa mở video);
chất lượng bám của từng mark là chuyện khác: mark hỏng bị bỏ qua và ghi lại (xem multimark.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ...core.errors import Refused
from ...core.io import read_json, sha256_file
from .policy import ASSET_INVALID, SHA_MISMATCH, LogoPolicy

MANIFEST_SCHEMA = "jjv/post-logo-marks/v1"
MANIFEST_INVALID = "MARKS_MANIFEST_INVALID"
TYPES = ("helmet", "vest_chest", "collar", "custom")
ASSETS = ("color", "white", "n-only", "n-only-thread")  # n-only-thread: icon alpha in the domain-declared thread colour (detect.mark_rgb)
WARPS = ("homography", "cylinder")
_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
DEFAULT_CYLINDER_DEG = {"helmet": 28.0}  # mũ cong; các loại khác phẳng nếu manifest không nói
RENDER_KEYS = {"blur_sigma": (0, 4), "opacity": (0.1, 1.0), "erase_pad": (0, 40), "erase_grow": (0, 1.0), "erase_min_dist": (3, 120)}


@dataclass(frozen=True)
class Mark:
    id: str
    type: str
    asset: str
    seed_frame: int
    seed_box: tuple[int, int, int, int]
    quad: tuple[tuple[float, float], ...] | None
    warp: str
    cylinder_deg: float
    track_window: int | None
    ring_scale: float | None
    render_overrides: dict
    partial: bool = False       # true: apply only on the valid track run around the seed, fading at its ends
    fade_frames: int = 6
    min_run: int = 12
    min_ncc: float = 0.35       # partial: frame có ncc_seed thấp hơn = bám không còn tin được

    def as_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "asset": self.asset, "seed_frame": self.seed_frame,
                "seed_box_xywh": list(self.seed_box), "quad": [list(p) for p in self.quad] if self.quad else None,
                "warp": self.warp, "cylinder_deg": self.cylinder_deg, "track_window": self.track_window,
                "ring_scale": self.ring_scale, "render_overrides": self.render_overrides,
                "partial": self.partial, "fade_frames": self.fade_frames, "min_run": self.min_run,
                "min_ncc": self.min_ncc}


@dataclass(frozen=True)
class MarkAsset:
    variant: str
    path: str
    sha256: str
    bgr: np.ndarray    # float32 (H,W,3) màu thật
    alpha: np.ndarray  # float32 (H,W) 0..1

    @property
    def aspect(self) -> float:
        return self.alpha.shape[1] / self.alpha.shape[0]

    def as_dict(self) -> dict:
        return {"variant": self.variant, "path": self.path, "sha256": self.sha256,
                "size_wh": [self.alpha.shape[1], self.alpha.shape[0]]}


def _bad(message: str) -> Refused:
    return Refused(f"{MANIFEST_INVALID}: {message}")


def _int(value: Any, label: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise _bad(f"{label} must be an integer in [{lo}, {hi}], got {value!r}")
    return value


def _num(value: Any, label: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise _bad(f"{label} must be a number in [{lo}, {hi}], got {value!r}")
    return float(value)


def _quad(value: Any, label: str) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(p, list) and len(p) == 2 for p in value):
        raise _bad(f"{label} must be 4 points [[x,y],...] in TL,TR,BR,BL order")
    pts = tuple((_num(p[0], label, -1e5, 1e5), _num(p[1], label, -1e5, 1e5)) for p in value)
    arr = np.array(pts, np.float32)
    cross = []
    for i in range(4):
        d1, d2 = arr[(i + 1) % 4] - arr[i], arr[(i + 2) % 4] - arr[(i + 1) % 4]
        cross.append(float(d1[0] * d2[1] - d1[1] * d2[0]))
    if not (all(c > 0 for c in cross) or all(c < 0 for c in cross)) or abs(cv2.contourArea(arr)) < 4:
        raise _bad(f"{label} must be a convex, non-degenerate quad")
    return pts


def parse_mark(raw: Any, index: int) -> Mark:
    if not isinstance(raw, dict):
        raise _bad(f"marks[{index}] must be an object")
    mid, kind, asset = raw.get("id"), raw.get("type"), raw.get("asset", "color")
    if not isinstance(mid, str) or not _ID.match(mid):
        raise _bad(f"marks[{index}].id must match {_ID.pattern}")
    if kind not in TYPES:
        raise _bad(f"marks[{index}].type must be one of {list(TYPES)}")
    if asset not in ASSETS:
        raise _bad(f"marks[{index}].asset must be one of {list(ASSETS)}")
    box = raw.get("seed_box")
    if not isinstance(box, list) or len(box) != 4:
        raise _bad(f"marks[{index}].seed_box is required: four measured integers x,y,w,h")
    seed_box = tuple(_int(v, f"marks[{index}].seed_box", 0, 100000) for v in box)
    if seed_box[2] < 2 or seed_box[3] < 2:
        raise _bad(f"marks[{index}].seed_box is too small")
    warp = raw.get("warp", "cylinder" if kind in DEFAULT_CYLINDER_DEG else "homography")
    if warp not in WARPS:
        raise _bad(f"marks[{index}].warp must be one of {list(WARPS)}")
    cyl = _num(raw.get("cylinder_deg", DEFAULT_CYLINDER_DEG.get(kind, 0.0)), f"marks[{index}].cylinder_deg", 0, 60)
    if warp == "homography":
        cyl = 0.0
    track = raw.get("track", {})
    if not isinstance(track, dict):
        raise _bad(f"marks[{index}].track must be an object")
    window = _int(track["window"], "track.window", 64, 2048) if "window" in track else None
    ring = _num(track["ring_scale"], "track.ring_scale", 1.2, 6.0) if "ring_scale" in track else None
    render = raw.get("render", {})
    if not isinstance(render, dict) or set(render) - set(RENDER_KEYS):
        raise _bad(f"marks[{index}].render may only set {sorted(RENDER_KEYS)}")
    overrides = {k: _num(v, f"render.{k}", *RENDER_KEYS[k]) for k, v in render.items()}
    partial = raw.get("partial", False)
    if not isinstance(partial, bool):
        raise _bad(f"marks[{index}].partial must be true or false")
    fade = _int(raw.get("fade_frames", 6), "fade_frames", 0, 48)
    min_run = _int(raw.get("min_run", 12), "min_run", 2, 10000)
    min_ncc = _num(raw.get("min_ncc", 0.35), "min_ncc", -1.0, 1.0)
    return Mark(min_ncc=min_ncc, partial=partial, fade_frames=fade, min_run=min_run, id=mid, type=kind, asset=asset, seed_frame=_int(raw.get("seed_frame", 0), "seed_frame", 0, 10**7),
                seed_box=seed_box, quad=_quad(raw["quad"], f"marks[{index}].quad") if "quad" in raw else None,
                warp=warp, cylinder_deg=cyl, track_window=window, ring_scale=ring, render_overrides=overrides)


def load_manifest(path: Path) -> tuple[list[Mark], dict]:
    path = Path(path)
    if not path.is_file():
        raise _bad(f"manifest not found: {path}")
    doc = read_json(path)
    if not isinstance(doc, dict) or doc.get("schema") != MANIFEST_SCHEMA:
        raise _bad(f"manifest schema must be {MANIFEST_SCHEMA!r}")
    raw = doc.get("marks")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 12:
        raise _bad("marks must be a list of 1..12 entries")
    marks = [parse_mark(m, i) for i, m in enumerate(raw)]
    ids = [m.id for m in marks]
    if len(set(ids)) != len(ids):
        raise _bad(f"duplicate mark ids: {ids}")
    return marks, {"path": str(path), "sha256": sha256_file(path)}


def _icon_rows(alpha: np.ndarray) -> slice:
    """Hàng của icon N = khối hàng có chữ đầu tiên (trên cùng), dừng ở khe trong suốt đầu tiên."""
    rows = np.where((alpha > 0.03).any(axis=1))[0]
    gap = np.where(np.diff(rows) > 1)[0]
    last = rows[gap[0]] if len(gap) else rows[-1]
    return slice(int(rows[0]), int(last) + 1)


def load_variant(policy: LogoPolicy, variant: str, repo_root: Path) -> MarkAsset:
    """Asset phải đúng sha mà domain khai (color/n-only dùng asset chính, white dùng ``assets.white``)."""
    if variant == "white":
        entry = policy.variants.get("white")
        if entry is None:
            raise Refused(f"{ASSET_INVALID}: domain {policy.domain_id!r} declares no 'white' logo asset")
        rel, want = entry["path"], entry["sha256"]
    else:
        rel, want = policy.asset_path, policy.asset_sha256
    path = Path(rel) if Path(rel).is_absolute() else Path(repo_root) / rel
    if not path.is_file():
        raise Refused(f"{ASSET_INVALID}: logo file not found: {path}")
    actual = sha256_file(path)
    if actual != want:
        raise Refused(f"{SHA_MISMATCH}: {variant} logo sha {actual[:12]} != domain asset sha {want[:12]}")
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None or img.ndim != 3 or img.shape[2] != 4:
        raise Refused(f"{ASSET_INVALID}: logo must be a PNG with alpha: {path}")
    alpha = img[..., 3].astype(np.float32) / 255.0
    if not (alpha > 0.03).any():
        raise Refused(f"{ASSET_INVALID}: logo is fully transparent: {path}")
    if variant in ("n-only", "n-only-thread"):
        keep = _icon_rows(alpha)
        img, alpha = img[keep], alpha[keep]
    if variant == "n-only-thread":
        if policy.detect is None:
            raise Refused(f"{ASSET_INVALID}: 'n-only-thread' needs the domain detect.mark_rgb thread colour")
        img = img.copy()
        img[..., :3] = np.array(policy.detect.mark_rgb[::-1], dtype=img.dtype)
    ys, xs = np.where(alpha > 0.03)
    sl = (slice(int(ys.min()), int(ys.max()) + 1), slice(int(xs.min()), int(xs.max()) + 1))
    return MarkAsset(variant, str(path), actual, img[sl][..., :3].astype(np.float32), alpha[sl])
