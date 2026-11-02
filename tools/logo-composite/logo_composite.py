#!/usr/bin/env python3
"""Deterministic CPU logo compositor for NEWTECONS stills.

Spec items use TL, TR, BR, BL quads in source-image pixel coordinates.
`curvature` is a cylindrical bend angle in radians (0 is flat); size_scale
shrinks or enlarges the quad uniformly around its center. OpenCV and NumPy
are the only runtime dependencies. No generative model or GPU is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
ASSETS = {
    "helmet": ROOT / "docs/media-stage/S07-PPE-ANCHORS-V004/helmet_logo_rgba.png",
    "vest_chest": ROOT / "docs/media-stage/S07-PPE-ANCHORS-V004/chest_logo_exact_alpha.png",
    # The canon back render uses the same centered white NEWTECONS lockup.
    "vest_back": ROOT / "docs/media-stage/S07-PPE-ANCHORS-V004/chest_logo_exact_alpha.png",
    "collar": ROOT / "docs/media-stage/BLENDER-COSTUMES-NEWTECONS-V002/collar_N_source_derived.png",
}
KINDS = tuple(ASSETS)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(data)


def size_quad(quad: np.ndarray, scale: float) -> np.ndarray:
    center = quad.mean(axis=0)
    return center + (quad - center) * scale


def composite_one(base_rgb: np.ndarray, logo_rgba: np.ndarray,
                  quad: np.ndarray, curvature: float, seed: int) -> tuple[np.ndarray, list[int]]:
    h, w = base_rgb.shape[:2]
    q = np.asarray(quad, dtype=np.float32)
    if q.shape != (4, 2) or not np.isfinite(q).all():
        raise ValueError("quad must contain four finite [x,y] points (TL,TR,BR,BL)")
    if abs(cv2.contourArea(q)) < 4:
        raise ValueError("quad area must be at least 4 pixels")
    x0 = max(0, int(np.floor(q[:, 0].min())))
    y0 = max(0, int(np.floor(q[:, 1].min())))
    x1 = min(w, int(np.ceil(q[:, 0].max())) + 1)
    y1 = min(h, int(np.ceil(q[:, 1].max())) + 1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("quad lies outside image")

    # Work only inside the item's bbox. Inverse perspective maps image pixels
    # back into logo UV space; the angular inverse models a cylindrical wrap.
    local_quad = q - np.array([x0, y0], dtype=np.float32)
    H = cv2.getPerspectiveTransform(
        np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32), local_quad)
    inv = np.linalg.inv(H)
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    ones = np.ones_like(xx)
    dst = np.stack([xx - x0, yy - y0, ones], axis=-1) @ inv.T
    den = np.where(np.abs(dst[..., 2]) < 1e-8, 1e-8, dst[..., 2])
    u = dst[..., 0] / den
    v = dst[..., 1] / den

    theta = float(curvature)
    if not np.isfinite(theta) or abs(theta) > 2.8:
        raise ValueError("curvature must be finite and between -2.8 and 2.8 radians")
    if abs(theta) > 1e-6:
        s = np.sin(theta / 2)
        u = 0.5 + np.arcsin(np.clip((2 * u - 1) * s, -0.999999, 0.999999)) / theta

    lh, lw = logo_rgba.shape[:2]
    map_x = (u * (lw - 1)).astype(np.float32)
    map_y = (v * (lh - 1)).astype(np.float32)
    warped = cv2.remap(logo_rgba, map_x, map_y, cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.rint(local_quad).astype(np.int32), 255)
    alpha = warped[..., 3].astype(np.float32) / 255.0
    alpha *= (mask > 0)

    patch = base_rgb[y0:y1, x0:x1].astype(np.float32)
    luminance = cv2.cvtColor(patch.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    blur = cv2.GaussianBlur(luminance, (0, 0), 2.0)
    edge = cv2.dilate((alpha > 0.02).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    reference = max(float(np.percentile(luminance[edge], 90)) if np.any(edge) else 255.0, 1.0)
    shade = np.clip(blur / reference, 0.42, 1.0)
    grain = luminance - cv2.GaussianBlur(luminance, (0, 0), 1.0)
    sigma = float(grain[edge].std()) if np.any(edge) else 0.0
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, sigma, size=alpha.shape).astype(np.float32)[..., None]
    logo_rgb = warped[..., :3].astype(np.float32) * shade[..., None] + noise
    a = alpha[..., None]
    mixed = np.rint(patch * (1 - a) + np.clip(logo_rgb, 0, 255) * a).clip(0, 255).astype(np.uint8)
    # Alpha threshold prevents subpixel fringe changes outside the intended mark.
    keep = alpha > 0.004
    out = base_rgb.copy()
    roi = out[y0:y1, x0:x1]
    roi[keep] = mixed[keep]
    return out, [x0, y0, x1, y1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--spec", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    receipt_path = args.out.with_suffix(args.out.suffix + ".receipt.json")
    if args.out.exists() or receipt_path.exists():
        raise FileExistsError(f"refusing to overwrite output or receipt: {args.out}")

    with args.spec.open("r", encoding="utf-8") as f:
        spec = json.load(f)
    src = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if src is None:
        raise ValueError(f"could not read image: {args.image}")
    base = cv2.cvtColor(src, cv2.COLOR_BGR2RGB)
    result = base.copy()
    items = spec.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("spec.items must be a non-empty list")
    records = []
    permitted = np.zeros(base.shape[:2], dtype=np.uint8)

    for i, item in enumerate(items):
        kind = item.get("kind")
        if kind not in KINDS:
            raise ValueError(f"item {i}: kind must be one of {KINDS}")
        quad = np.asarray(item.get("quad"), dtype=np.float32)
        scale = float(item.get("size_scale", 1.0))
        if not np.isfinite(scale) or scale <= 0 or scale > 4:
            raise ValueError(f"item {i}: size_scale must be in (0,4]")
        quad = size_quad(quad, scale)
        asset = ASSETS[kind]
        logo = cv2.imread(str(asset), cv2.IMREAD_UNCHANGED)
        if logo is None or logo.ndim != 3 or logo.shape[2] != 4:
            raise ValueError(f"asset must be RGBA: {asset}")
        logo = cv2.cvtColor(logo, cv2.COLOR_BGRA2RGBA)
        # Stable per-item grain; same inputs and spec always produce same pixels.
        result, bbox = composite_one(result, logo, quad, float(item.get("curvature", 0)), 20261101 + i)
        x0, y0, x1, y1 = bbox
        permitted[y0:y1, x0:x1] = 1
        records.append({"kind": kind, "asset": str(asset), "asset_sha256": sha256(asset),
                        "quad_TL_TR_BR_BL": quad.tolist(), "curvature_radians": float(item.get("curvature", 0)),
                        "size_scale": scale, "bbox_xyxy_exclusive": bbox})

    changed = np.any(result != base, axis=2)
    outside = int(np.count_nonzero(changed & (permitted == 0)))
    if outside != 0:
        raise AssertionError(f"changed pixels outside item bboxes: {outside}")
    ok, encoded = cv2.imencode(args.out.suffix or ".png", cv2.cvtColor(result, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("image encoding failed")
    write_new(args.out, encoded.tobytes())
    receipt = {
        "tool": "LOGO-COMPOSITE-TOOL-V001", "status": "CPU_COMPOSITE_COMPLETE_CANDIDATE",
        "source": str(args.image.resolve()), "source_sha256": sha256(args.image),
        "spec": str(args.spec.resolve()), "spec_sha256": sha256(args.spec),
        "output": str(args.out.resolve()), "output_sha256": sha256(args.out),
        "dimensions": [int(result.shape[1]), int(result.shape[0])], "items": records,
        "changed_pixels": int(np.count_nonzero(changed)),
        "changed_pixels_outside_item_bboxes": outside,
        "method": "perspective inverse-map + cylindrical angular bend + local luminance multiply + deterministic grain",
        "execution": "OpenCV/NumPy CPU only; no GPU; no generative model",
    }
    write_new(receipt_path, (json.dumps(receipt, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(json.dumps({"output": str(args.out), "receipt": str(receipt_path),
                      "changed_pixels": receipt["changed_pixels"], "outside_bbox": outside}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
