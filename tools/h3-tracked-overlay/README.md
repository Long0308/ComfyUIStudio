# tracked_overlay.py — dán chữ/logo sạch lên clip H3 bằng bám vùng (CPU)

Yêu cầu: Python 3.14, opencv-python 5.0, numpy, Pillow, ffmpeg/ffprobe trên PATH. Không GPU, không model sinh ảnh.

```
python -X utf8 tracked_overlay.py --video <clip.mp4> --spec <spec.json> --work <thư mục tạm> ^
  --out <ra.mp4> --receipt <receipt.json> --track-json <track.json> [--preview <quad.mp4>] [--crf 14]
python -X utf8 make_contact_sheet.py --before <clip.mp4> --after <ra.mp4> --track-json <track.json> --work <tạm> --out <sheet.jpg>
python -X utf8 verify_lock.py --orig-frames <tạm>/in --out-frames <tạm>/out --track-json <track.json> --spec <spec.json> --report <lock.json> --strip <strip.png>
```

Mọi đầu ra ghi mới (`x` mode) — có sẵn là lỗi, không đè. Audio gốc được `-c:a copy`.

## Spec (toạ độ khung 0, quad = TL,TR,BR,BL)

```json
{
  "font": "C:/Windows/Fonts/Roboto-Bold.ttf",
  "smooth_sigma_frames": 1.0,
  "regions": [
    {"name": "LA_text", "kind": "text", "text": "KHỐI KỸ THUẬT",
     "center": [275, 351], "height_px": 15, "render_px": 160,
     "ctx_pad": [48, 40], "core_pad": 6, "cover_pad": [10, 6], "cover_mask": "bright", "smear_grow": 6,
     "model": "homography", "softness": 0.55,
     "anchor": {"mode": "bright", "blend": 0.25, "pad": [8, 5], "min_px": 15, "max_jump_px": 14, "px_ratio_gate": [0.35, 2.5]}},
    {"name": "LA_helmet", "kind": "helmet_logo", "asset": "docs/media-stage/S07-PPE-ANCHORS-V004/helmet_logo_rgba.png",
     "quad": [[238, 77], [284, 77], [284, 100], [238, 100]], "curvature": 0.16,
     "cover_pad": [5, 5], "cover_mask": "red_cyan", "softness": 0.6, "shade_ref_abs": 240, "shade_floor": 0.5,
     "anchor": {"mode": "red", "scale_from": "LA_text", "search_pad": 16, "min_px": 10, "blend": 0.6,
                "rot_clamp_deg": 8, "max_jump_px": 30, "px_ratio_gate": [0.3, 3.0], "smooth_sigma_frames": 2.0}}
  ]
}
```

- `kind: text`: cho `center`+`height_px` (cao kể cả dấu) thì bề rộng tự tính theo tỉ lệ font; hoặc cho `quad` thẳng.
- `kind: helmet_logo`: cần vết N đỏ của H3 ở khung 0 trong quad (neo màu). `scale_from` là vùng chữ của cùng người.
- `cover_mask`: `bright` (chữ thêu trắng) · `red_cyan` (vết logo) — thêm vào vùng inpaint.
- `kind: track_only` + `ctx_poly` (đa giác khung 0, vd vỏ + vành mũ): tracker feature chỉ trong đa giác (co 4 px), không vẽ; dùng làm `scale_from` cho logo mũ và làm cổng vỏ mũ `"shell": {"poly_from": "<tên>"}` — vết N đỏ phải có ≥ 50 % điểm trong đa giác mới được nhận; không có vết hợp lệ (H3 vẽ logo rời mũ) → logo đặt tay ở `quad` và giữ tư thế theo tracker đa giác.
- `kind: erase`: chỉ inpaint vùng che + mask vết (không dán gì) — dùng xoá vết logo H3 vẽ lạc chỗ; bám bằng `anchor` mode `red` như logo mũ.
- RAM: khung đọc từ đĩa theo cache 3 khung (máy dùng chung với lane GPU; đo 01/11 còn 946 MB commit) — không giữ cả clip trong bộ nhớ.
- Đo quad khung 0: trích khung `ffmpeg -i clip.mp4 -frames:v 1 f0.png`, zoom 5× và đọc toạ độ (xem `AUDIT.md` §2).

## Giới hạn đã biết
- Chữ bám vải (feature) + kéo về vết H3; nếu vết H3 nhảy > `max_jump_px`·scale thì bỏ đo khung đó.
- Logo mũ dùng similarity: không foreshortening khi đầu quay mạnh.
- Mũ trắng trơn hoàn toàn (không vết đỏ) thì neo màu không chạy — cần quad tay + bám feature (chưa làm).
- Vùng ra khỏi khung hình: không vẽ; metric đánh dấu "unmeasurable".
