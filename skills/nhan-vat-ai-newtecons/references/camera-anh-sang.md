# Lớp CAMERA · LIGHT · FINISH và bảng BỐI CẢNH ÁNH SÁNG

Nguồn: Astra viết 16/09/2026 theo yêu cầu anh Long — *"mô phỏng lại như chụp thực tế ở
hiện trường bằng camera Sony siêu nét 4K, tỉ lệ 9:16 hoặc 16:9 theo yêu cầu, dựng bối
cảnh như chụp ảnh thật mang tính điện ảnh quốc tế tầm cỡ Hollywood"*.

## Thứ tự ráp một prompt hoàn chỉnh

`YÊU CẦU NGƯỜI DÙNG` → `face lock` → `attire + khoá chữ/logo` → **CAMERA & FRAMING**
(đã chạy thật trong code: ngang tầm ngực, cấm góc hắt từ dưới lên) → **CAMERA, LIGHT &
FINISH** (khối dưới đây) → `NEGATIVE`.

## Chọn máy và ống kính — bảng, không để model tự bịa

| Ca chụp | Máy + ống kính |
|---|---|
| Mặc định chân dung ngoài trời / ban đêm, một người | Sony A7R V + Sony FE 50mm f/1.2 GM |
| Cận đầu–vai, tách nền mạnh | Sony A7R V + Sony FE 85mm f/1.4 GM |
| Toàn thân trong khung | vẫn 50mm nhưng khép về f/2 – f/2.8 — f/1.2 cho toàn thân là tự mâu thuẫn: mặt nét thì giày bệt |
| Cặp / đội ngũ khung 16:9 | 35mm f/4 – f/5.6, hoặc 50mm f/4 nếu đủ khoảng lùi |
| Máy khác khi cần | Canon EOS R5 + RF 50mm f/1.2L hoặc RF 85mm f/1.2L — giữ nguyên ngôn ngữ hoàn thiện |

## Khối chèn — bản chuẩn (điền tham số theo preset)

```text
CAMERA, LIGHT & FINISH — PHOTOGRAPHIC REALISM LOCK (append to every image prompt, never replace the identity or logo locks):
- Camera body and lens: {may_anh} with {ong_kinh}. Real on-location camera work: handheld with a stabilized grip, or on a tripod, at the subject's chest height or slightly above, straight-on, level horizon.
- Exposure: aperture {khau_do}, ISO {iso}, shutter {toc_do_manh}, white balance {can_bang_trang}. These are the settings a working photographer would dial in on this exact set, not a synthetic render. {ho_tro_sang}.
- Focus: Eye-AF locked on the nearest eye. At 100% zoom the eyes, eyelashes, pores, stubble and fabric weave must be genuinely sharp — not sharpened in post.
- Depth of field: natural optical falloff, subject crisp, background smoothly defocused. When the whole body must stay sharp, stop the lens down instead of faking sharpness.
- Image quality: the real detail of a 4K full-frame file — navy fabric weave, black mesh, silver reflective tape, orange fluorescent bands, metal snap buttons, concrete dust, brushed steel, glass, wood grain. Micro-contrast preserved, no smeared or mushy regions, no upscaled mush.
- Finish: quiet corporate luxury — clean, expensive-looking and honest. Modern international corporate campaign grading: neutral-warm skin, controlled highlights, gentle highlight rolloff, soft cool lift in the shadows, deep but open blacks, no clipped white, no crushed detail.
- Skin and realism: keep REAL human skin — visible pores, fine natural creases, slight unevenness, faint stubble, natural skin sheen. Absolutely no plastic or waxy skin, no beauty-filter smoothing, no CGI/AI sheen, no cartoon or 3D-render look. The image must read as a real photograph taken on a real site.
- Texture: a very light, fine 35mm film grain and a barely perceptible natural lens character — never a heavy filter preset, never a LUT look.
- Aspect ratio and framing: {ti_le}.
- Do not: plastic skin, waxy faces, HDR halos, neon spill, over-saturated teal-and-orange, faux-bokeh cut-outs, low-angle hero shots, fashion-model posing, reinterpreted or recolored logos, AI-looking artifacts.
```

## Tỉ lệ `{ti_le}` — luật chọn

- `9:16` — dọc, cho Zalo / điện thoại / story. **MẶC ĐỊNH khi ảnh chỉ có MỘT người.**
- `16:9` — ngang, cho báo cáo / slide / ảnh bìa. **MẶC ĐỊNH khi ảnh CẶP hoặc ĐỘI NGŨ.**
- Người dùng nói rõ tỉ lệ thì theo người dùng, kể cả ngược mặc định.
- NEX phải **nói ra tỉ lệ đã chọn** trong câu trả lời ("khung 9:16 nhé") để sửa ngay nếu sai.

## Tám BỐI CẢNH ÁNH SÁNG

Mã preset khớp tên biến trong `_bien_nhan_vat()` để hai tầng không lệch.

| Mã | Kích hoạt (tiếng Việt) | Khẩu · ISO · Màn trập · WB | Ghi chú |
|---|---|---|---|
| `ct_nang_trong` | công trường · thi công · giàn giáo · cẩu tháp · bê tông · ban ngày · nắng | f/2.8 · ISO 200 · 1/500 · 5600K | mặc định khi không có gì khác |
| `ct_gio_vang` | giờ vàng · hoàng hôn · nắng chiều · nắng xiên | f/2 · ISO 200 · 1/320 · 5000K | rim viền nón + dải phản quang |
| `ct_mua_am_u` | mưa · âm u · trời xám · moody · sau mưa · ướt | f/2.8 · ISO 640 · 1/250 · 6500K | 🩸 dễ nuốt chữ trắng trên nền xám |
| `ct_ban_dem` | ban đêm · tăng ca · đèn pha · đèn công trường · night shift | f/1.8 · ISO 1600 · 1/125 · 3800K | 🩸 dải phản quang dễ cháy trắng |
| `vp_cua_kinh` | văn phòng · office · phòng họp · họp · sảnh · bàn làm việc | f/2.2 · ISO 640 · 1/160 · 4800K | tự bỏ gile + nón, chữ in trên sơ mi |
| `studio_3_diem` | studio · nền trắng · phông trắng/xanh | f/6.3 · ISO 100 · 1/160 · 5500K | ba điểm đèn, phông xám giữa |
| `do_thi_dem` | kiểu phim · điện ảnh · Hollywood · phố · rooftop · cinematic | f/1.4 · ISO 2000 · 1/100 · 3400K | 🩸 dễ trôi sang look thời trang — trái luật 16/09 |
| `noi_that_cua_so_lon` | nội thất · trong nhà · cửa sổ lớn · biệt thự · khách sạn | f/2 · ISO 400 · 1/125 · 5000K | 🩸 "nội thất" KHÔNG khớp regex văn phòng ⇒ phải viết kèm "trong nhà" |

Câu chèn mẫu cho từng preset (bản tiếng Anh đầy đủ) nằm trong nhật ký phiên 16/09/2026;
khi cần dùng lại thì chép từ đó hoặc hỏi lại Astra — tiêu chí để tự viết lại: **giờ trong
ngày + nguồn sáng chính + nguồn phụ + một câu bảo vệ chữ trắng trên ngực áo**.
