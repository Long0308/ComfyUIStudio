"""Warp homography / trụ chính xác trên mặt phẳng tổng hợp (không cần ffmpeg)."""
from __future__ import annotations

import cv2
import numpy as np

from engine.post.logo.warp import cylinder_source_u, fit_homography, warp_logo

W0, H0 = 160, 100
BLOBS = [(30, 25), (130, 25), (130, 75), (30, 75), (80, 50)]   # asset-pixel centres of small discs


def blob_asset() -> tuple[np.ndarray, np.ndarray]:
    alpha = np.zeros((H0, W0), np.float32)
    for cx, cy in BLOBS:
        cv2.circle(alpha, (cx, cy), 4, 1.0, -1, cv2.LINE_AA)
    bgr = np.dstack([np.full((H0, W0), v, np.float32) for v in (40, 120, 220)])
    return bgr, alpha


def centroid(alpha: np.ndarray, near: tuple[float, float], radius: float = 14) -> tuple[float, float]:
    ys, xs = np.mgrid[0:alpha.shape[0], 0:alpha.shape[1]]
    m = alpha * (((xs - near[0]) ** 2 + (ys - near[1]) ** 2) < radius ** 2)
    return float((xs * m).sum() / m.sum()), float((ys * m).sum() / m.sum())


def test_fit_homography_maps_the_four_points_exactly() -> None:
    src = np.array([[0, 0], [W0, 0], [W0, H0], [0, H0]], np.float64)
    dst = np.array([[210, 40], [390, 70], [370, 190], [200, 170]], np.float64)
    h = fit_homography(src, dst)
    mapped = cv2.perspectiveTransform(src[None].astype(np.float32), h)[0]
    assert np.abs(mapped - dst).max() < 1e-3


def test_homography_warp_is_accurate_on_a_synthetic_plane() -> None:
    bgr, alpha = blob_asset()
    quad = np.array([[210.0, 40.0], [390.0, 70.0], [370.0, 190.0], [200.0, 170.0]])     # strong perspective
    h = fit_homography(np.array([[0, 0], [W0, 0], [W0, H0], [0, H0]], np.float64), quad)
    colour, out = warp_logo(bgr, alpha, quad, (230, 430), supersample=4)
    for bx, by in BLOBS:
        want = cv2.perspectiveTransform(np.array([[[bx, by]]], np.float32), h)[0, 0]
        got = centroid(out, tuple(want))
        assert np.hypot(got[0] - want[0], got[1] - want[1]) < 0.6, (bx, by, got, want)
    covered = cv2.GaussianBlur(out, (0, 0), 0.01) > 0.5
    assert covered.sum() > 0
    ys, xs = np.where(out > 0.5)
    inside = cv2.pointPolygonTest(quad.astype(np.float32), (float(xs.mean()), float(ys.mean())), False)
    assert inside >= 0
    assert np.allclose(colour[out > 0.9].mean(axis=0), [40, 120, 220], atol=3)           # straight colour is not darkened by alpha


def test_full_opaque_asset_fills_the_quad() -> None:
    bgr = np.full((H0, W0, 3), 100, np.float32)
    quad = np.array([[50.0, 30.0], [210.0, 45.0], [200.0, 150.0], [40.0, 140.0]])
    _, out = warp_logo(bgr, np.ones((H0, W0), np.float32), quad, (200, 260), supersample=3)
    mask = np.zeros(out.shape, np.uint8)
    cv2.fillPoly(mask, [np.round(quad).astype(np.int32)], 1)
    iou = ((out > 0.5) & (mask > 0)).sum() / ((out > 0.5) | (mask > 0)).sum()
    assert iou > 0.98


def test_cylinder_warp_compresses_the_edges_and_keeps_the_centre() -> None:
    u = np.linspace(0, 1, 101)
    assert np.allclose(cylinder_source_u(u, 0.0), u)
    s = cylinder_source_u(u, 40.0)
    assert abs(s[50] - 0.5) < 1e-9 and abs(s[0]) < 1e-9 and abs(s[-1] - 1) < 1e-9
    assert np.all(np.diff(s) > 0) and np.allclose(s + s[::-1], 1.0)                       # monotonic and symmetric
    assert s[10] > u[10]   # display 0.1 reads a source column right of 0.1: content is stretched at the centre, squeezed at the edge
    bgr, alpha = blob_asset()
    quad = np.array([[10.0, 10.0], [170.0, 10.0], [170.0, 110.0], [10.0, 110.0]])
    _, flat = warp_logo(bgr, alpha, quad, (130, 190), 3, 0.0)
    _, cyl = warp_logo(bgr, alpha, quad, (130, 190), 3, 40.0)
    fx = centroid(flat, (140, 35))[0]
    cx = centroid(cyl, (140, 35))[0]
    assert cx > fx + 0.5          # the right-hand blob is pushed toward the right edge (centre stretched, edge squeezed)
    assert abs(centroid(cyl, (90, 60))[0] - centroid(flat, (90, 60))[0]) < 0.3             # centre blob stays put
