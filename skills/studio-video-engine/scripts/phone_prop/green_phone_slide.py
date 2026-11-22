"""Ghép màn hình clone vào điện thoại phông xanh (ngón tay giữ nguyên trên cùng) + hoạt hình «trượt để trả lời».
Ra khung PNG 1280x720 cho ffmpeg. Dùng: python -X utf8 -I green_phone_slide.py PHOTO OUTDIR"""
import sys
from pathlib import Path
import cv2
import numpy as np

photo, outdir = sys.argv[1], Path(sys.argv[2]); outdir.mkdir(exist_ok=True)
img = cv2.imread(photo)
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
green = cv2.inRange(hsv, (40, 120, 120), (85, 255, 255))
green = cv2.morphologyEx(green, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
cnts, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
c = max(cnts, key=cv2.contourArea)
hull = cv2.convexHull(c)
rect = cv2.minAreaRect(hull); box = cv2.boxPoints(rect)
s = box.sum(1); dif = np.diff(box, axis=1).ravel()
quad = np.float32([box[np.argmin(s)], box[np.argmin(dif)], box[np.argmax(s)], box[np.argmax(dif)]])  # TL TR BR BL
print("quad", quad.round(1).tolist())
# alpha = vùng xanh mở rộng nhẹ (giữ ngón tay), khử viền xanh
alpha = cv2.GaussianBlur(cv2.dilate(green, np.ones((3, 3), np.uint8)), (3, 3), 0).astype(np.float32)[..., None] / 255
base = img.astype(np.float32)
b, g, r = cv2.split(base); g = np.minimum(g, np.maximum(b, r) * 1.05); base = cv2.merge([b, g, r])  # despill

scr0 = cv2.imread("CALL_SCREEN_CLONE_464x818.png")
sh, sw = scr0.shape[:2]
# tách nút trượt (vòng trắng có ống nghe) và nền dưới nó
K_C, K_R = (88, 685), 50
knob = scr0[K_C[1]-K_R-2:K_C[1]+K_R+2, K_C[0]-K_R-2:K_C[0]+K_R+2].copy()
kmask = np.zeros(knob.shape[:2], np.uint8); cv2.circle(kmask, (K_R+2, K_R+2), K_R+1, 255, -1)
hole = np.zeros((sh, sw), np.uint8); cv2.circle(hole, K_C, K_R + 3, 255, -1)
text_box = (150, 655, 410, 715)  # vùng chữ «trượt để trả lời»
x0_, y0_, x1_, y1_ = text_box
tg = cv2.cvtColor(scr0[y0_:y1_, x0_:x1_], cv2.COLOR_BGR2GRAY)
tmask = (tg < cv2.GaussianBlur(tg, (0, 0), 6) - 12).astype(np.uint8) * 255  # nét chữ tối trên nền thanh sáng
hole[y0_:y1_, x0_:x1_] = np.maximum(hole[y0_:y1_, x0_:x1_], cv2.dilate(tmask, np.ones((5, 5), np.uint8)))
empty = cv2.inpaint(scr0, hole, 7, cv2.INPAINT_TELEA)
M = cv2.getPerspectiveTransform(np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]]), quad)
H, W = img.shape[:2]
FPS, DUR = 30, 1.5
for i in range(int(FPS * DUR)):
    t = i / FPS
    p = 0.0 if t < 0.7 else min(1.0, (t - 0.7) / 0.45)
    p = p * p * (3 - 2 * p)  # ease
    scr = empty.copy()
    if p < 0.6:  # chữ mờ dần khi trượt
        a = 1 - p / 0.6
        x0, y0, x1, y1 = text_box
        scr[y0:y1, x0:x1] = (scr0[y0:y1, x0:x1] * a + empty[y0:y1, x0:x1] * (1 - a)).astype(np.uint8)
    kx = int(K_C[0] + p * (428 - 50 - K_C[0]))
    y0, x0 = K_C[1] - K_R - 2, kx - K_R - 2
    roi = scr[y0:y0 + knob.shape[0], x0:x0 + knob.shape[1]]
    m = kmask[..., None] / 255.0
    scr[y0:y0 + knob.shape[0], x0:x0 + knob.shape[1]] = (knob * m + roi * (1 - m)).astype(np.uint8)
    warped = np.clip(cv2.warpPerspective(scr.astype(np.float32), M, (W, H), flags=cv2.INTER_CUBIC), 0, 255)
    frame = base * (1 - alpha) + warped * alpha
    # đẩy máy nhẹ 1.00 → 1.04
    z = 1 + 0.04 * t / DUR; cw, ch = int(W / z), int(H / z)
    fx, fy = (W - cw) // 2 + int(30 * t / DUR), (H - ch) // 2
    frame = cv2.resize(frame[fy:fy + ch, fx:fx + cw], (1280, 720), interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(str(outdir / f"f{i:03d}.png"), np.clip(frame, 0, 255).astype(np.uint8))
print("frames", int(FPS * DUR))
