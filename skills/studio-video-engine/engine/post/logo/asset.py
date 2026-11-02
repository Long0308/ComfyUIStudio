"""Tách icon (vùng đỏ, không lấy wordmark xanh) từ PNG logo mà domain khai báo; sha256 đi kèm."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ...core.errors import Refused
from ...core.io import sha256_file


@dataclass(frozen=True)
class LogoAsset:
    path: str
    sha256: str
    alpha: np.ndarray  # float32 (H,W) 0..1, crop sát icon
    bbox_xywh: tuple[int, int, int, int]  # vị trí icon trong PNG gốc
    source_size_wh: tuple[int, int]

    @property
    def aspect(self) -> float:
        return self.alpha.shape[1] / self.alpha.shape[0]

    def as_dict(self) -> dict:
        return {
            "path": self.path, "sha256": self.sha256, "icon_bbox_xywh": list(self.bbox_xywh),
            "icon_size_wh": [self.alpha.shape[1], self.alpha.shape[0]],
            "source_size_wh": list(self.source_size_wh), "selection": "red icon region only (wordmark excluded)",
        }


def load_icon(path: Path, pad: int = 2) -> LogoAsset:
    """Icon là vùng đỏ; wordmark xanh không được chạm bbox của icon (nếu chạm thì từ chối, không đoán)."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None or img.ndim != 3 or img.shape[2] != 4:
        raise Refused(f"LOGO_ASSET_INVALID: logo must be a PNG with alpha: {path}")
    blue, green, red, alpha = (img[..., i].astype(np.int32) for i in range(4))
    red_mask = (red > 150) & (green < 110) & (blue < 110) & (alpha > 0)
    if red_mask.sum() < 100:
        raise Refused("LOGO_ASSET_INVALID: no red icon region found in the logo")
    ys, xs = np.where(red_mask)
    x0, x1 = max(0, xs.min() - pad), min(img.shape[1], xs.max() + 1 + pad)
    y0, y1 = max(0, ys.min() - pad), min(img.shape[0], ys.max() + 1 + pad)
    blue_in_box = ((blue > 100) & (red < 100) & (alpha > 0))[y0:y1, x0:x1].sum()
    if blue_in_box > 0:
        raise Refused(f"LOGO_ASSET_INVALID: icon bbox touches {blue_in_box} wordmark pixels; not separable")
    icon_alpha = (alpha[y0:y1, x0:x1] / 255.0).astype(np.float32)
    return LogoAsset(
        path=str(path), sha256=sha256_file(path), alpha=icon_alpha,
        bbox_xywh=(int(x0), int(y0), int(x1 - x0), int(y1 - y0)),
        source_size_wh=(int(img.shape[1]), int(img.shape[0])),
    )
