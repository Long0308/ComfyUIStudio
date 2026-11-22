"""Ghép màn hình clone lên mặt kính điện thoại trong ảnh (warp phối cảnh + bo góc + giữ phản chiếu kính)."""
import sys
import cv2
import numpy as np

def composite(photo, screen, quad, radius=40, keep_reflect=1.0, out=None):
    img = cv2.imread(photo).astype(np.float32)
    scr = cv2.imread(screen).astype(np.float32)
    sh, sw = scr.shape[:2]
    a = np.zeros((sh, sw), np.uint8)
    cv2.rectangle(a, (radius, 0), (sw - radius, sh), 255, -1); cv2.rectangle(a, (0, radius), (sw, sh - radius), 255, -1)
    for cx, cy in ((radius, radius), (sw - radius, radius), (radius, sh - radius), (sw - radius, sh - radius)):
        cv2.circle(a, (cx, cy), radius, 255, -1)
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]]), np.float32(quad))
    H, W = img.shape[:2]
    warped = cv2.warpPerspective(scr, M, (W, H), flags=cv2.INTER_LANCZOS4)
    alpha = cv2.warpPerspective(a, M, (W, H)).astype(np.float32)[..., None] / 255.0
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)[..., None] if alpha.ndim == 3 else alpha
    # vệt sáng kính chéo nhẹ (không lấy lại ảnh màn hình cũ ⇒ không lộ giao diện cũ)
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    sheen = np.clip(1 - np.abs((xx / sw + yy / sh) - 0.55) * 6, 0, 1) * 28
    sheen_w = cv2.warpPerspective(sheen, M, (W, H))[..., None]
    screen_lit = np.clip(warped + keep_reflect * sheen_w, 0, 255)
    res = img * (1 - alpha) + screen_lit * alpha
    cv2.imwrite(out, res.astype(np.uint8)); return out

if __name__ == "__main__":
    composite(sys.argv[1], sys.argv[2], eval(sys.argv[3]), out=sys.argv[4])
