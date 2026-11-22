"""Đạo cụ màn hình cuộc gọi: CLONE 100% ảnh mẫu user (REF_USER_CALL_SCREEN.png), chỉ thay số «090 090090» bằng tên.
User 16/11: «phải clone ảnh 100% đổi tên thôi». Xoá số bằng inpaint, viết tên Segoe UI Light trắng cùng vị trí/cỡ."""
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

NAME = "NEW - Anh Nam GĐDA"
src = cv2.imread("REF_USER_CALL_SCREEN.png")
h, w = src.shape[:2]
gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
band = (slice(60, 140), slice(40, w - 40))           # vùng số điện thoại
mask = np.zeros((h, w), np.uint8)
sub = (gray[band] > 120).astype(np.uint8) * 255      # nét chữ trắng
mask[band] = cv2.dilate(sub, np.ones((7, 7), np.uint8))
clean = cv2.inpaint(src, mask, 9, cv2.INPAINT_TELEA)
ys, xs = np.nonzero(sub)
y0, y1 = ys.min() + 60, ys.max() + 60                 # chiều cao chữ số gốc (cap height)
im = Image.fromarray(cv2.cvtColor(clean, cv2.COLOR_BGR2RGB))
d = ImageDraw.Draw(im)
size = int((y1 - y0) * 1.38)
font = ImageFont.truetype("C:/Windows/Fonts/segoeuil.ttf", size)
while d.textlength(NAME, font=font) > w - 70:
    size -= 1; font = ImageFont.truetype("C:/Windows/Fonts/segoeuil.ttf", size)
d.text((w // 2, (y0 + y1) // 2), NAME, font=font, fill="white", anchor="mm")
im.save("CALL_SCREEN_CLONE_464x818.png")
im.resize((750, int(750 * h / w)), Image.LANCZOS).save("CALL_SCREEN_CLONE_750.png")
print("digits box y", y0, y1, "font", size)
