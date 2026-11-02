# NEWTECONS — bản review qua đêm v008

Tạo lúc 2026-11-02T06:05:56.070489+07:00. Đủ 16 slot EDL V014 cộng 1 slot S03_A_REPLY (17 slot), 64.500 giây; 2560×1440, 24 fps. Các lựa chọn mới là **root_picked**, chưa phải user_approved.

CPU/ffmpeg, mỗi lần một ffmpeg, threads 8; Lanczos + center crop, không thêm thanh đen, không chạy SeedVR2. Nguồn đã upscale được duyệt từ trước vẫn giữ provenance.

Cắt thẳng trong cảnh. Dip 10 frame tại các ranh giới địa điểm được ghi dip_in/dip_out trong manifest. Nhạc edit_B, thoại mục tiêu -18 LUFS, nhạc khoảng -34 LUFS dưới thoại trước chuẩn hóa tổng.

Đo file AAC giao: **-14.09 LUFS**, **-1.46 dBTP**, LRA 6.20.

| Slot | File | Quyết định / lý do | Còn thiếu |
|---|---|---|---|
| INTRO_FOOTSTEPS | `INTRO_FOOTSTEPS_H3_s20261102_STEPS.mp4` | root_picked: Nguồn có tiếng bước chân theo yêu cầu; đi vào văn phòng công trường. |  |
| INTRO_TIMELAPSE | `TIMELAPSE_3S_ONPLOT_V001_R5.mp4` | root_picked: ROOT-DECISIONS 01:59 chọn ONPLOT R5 bản 3 giây cho edit. Đã xem đầu/giữa/cuối: tháp nằm trên ô đất trống bên trái, pha bàn giao thêm mảng xanh sau tháp; hash khớp assembly_REVIEW_R5.json. | Vị trí đánh giá bằng mắt, không phải đo đạc; mặt dựng đổi sắc, chi tiết cẩu có thể méo, mép ghép cỏ có thể mềm. Pha đầu và mảng xanh cuối có CPU reveal, chưa được user duyệt. |
| SCENE_01 | `SCENE_01_HELMET_MACRO_H3_s20261101.mp4` | root_picked: Cận mũ đặt lên bản vẽ, đã có motion thay slot trống. | Cận mũ thay bố cục hai người; chưa có cảnh hai nhân vật khác nhau. |
| S02_A | `S02_A_seedvr2_1440_aspect.mp4` | approved: Giữ đúng SHA clip user duyệt; người nói hướng vào cuộc họp. |  |
| S03_A | `S03_A_V008VOICE_s20261031.mp4` | root_picked: V008: KKT_TB đổi sang profile nam FLEURS 2aa9b44e (ref 145 Hz); H3 cục bộ ComfyUI, WAV hash-bound. | Giọng/khẩu hình chưa user nghe duyệt; ASR khớp chữ chứ không chứng minh hợp giọng. |
| S03_A_REPLY | `S03_A_REPLY_V2VOICE_s2026110302.mp4` | root_picked: Câu đáp đúng "Dạ, rõ rồi anh." — người đàn ông đeo kính, giọng 0e61ba93. | Chưa user duyệt. |
| MAP_NORTH | `MAP_NORTH_V007.mp4` | root_picked: Ba điểm và nhãn địa danh hiện dần; V007R2 cùng nội dung. |  |
| S04_A | `S04_A_PLUS_TURN_preview_s202611041.mp4` | approved: Bản PLUS_TURN được duyệt 22:25; giữ trọn quay về cửa kính. |  |
| PAN_TRANSITION | `PAN_OFFICE_V004.mp4` | root_picked: Giữ đủ 2 giây để đáp vào văn phòng, tránh cắt mất đích. |  |
| S05_A | `S05_A_V008VOICE_s20261111.mp4` | root_picked: V008: CHAR_07 đổi sang profile nam FLEURS 0e31d579 (ref 163 Hz); H3 cục bộ ComfyUI, WAV hash-bound. | Giọng/khẩu hình chưa user nghe duyệt; ASR khớp chữ chứ không chứng minh hợp giọng. |
| S05_FEMALE | `S05_FEMALE_H3_bietroi_R2_s20261121.mp4` | root_picked: R2 sửa biểu cảm: mỉm cười rồi quay gõ; loại bietroi_s20261102 bị bác. | Logo cổ áo thiếu; cần xem lại biến dạng tay khi gõ. |
| S05_SCREEN | `s05a_screen_insert_v004.mp4` | approved: Giữ insert user duyệt, 5 giây, không đổi hình. |  |
| S05_FEMALE_THANKS | `S05_FEMALE_THANKS_R2_s20261121.mp4` | root_picked: R2 mới đến 00:34, sửa đúng câu cảm ơn và có chuyển động hướng về người đối diện. | Logo cổ áo còn thiếu; bố trí bàn khác cảnh biết rồi. |
| S06_A | `S06_A_V008VOICE_s20261107.mp4` | root_picked: V008: giọng CHT 251e559a, lời đổi biến thể vượt ASR; H3 cục bộ ComfyUI, WAV hash-bound. | Giọng/khẩu hình chưa user nghe duyệt; ASR khớp chữ chứ không chứng minh hợp giọng. |
| S07_PRE | `S07_PRE_LINE_H3_s202611201.mp4` | root_picked: ROOT-DECISIONS cập nhật 00:45 chọn chính xác file này; bỏ 0,5 giây đầu trong edit, giữ WAV H3 gốc. Đã xem ba khung hình. | Logo mũ/chữ vai trò còn lỗi; nguồn được root chọn cho bản review, chưa được người dùng duyệt. |
| S07_A | `S07_A_LINE_H3_s202611211.mp4` | root_picked: ROOT-DECISIONS cập nhật 00:45 chọn chính xác file này; bỏ 0,5 giây đầu trong edit, giữ WAV H3 gốc. Đã xem ba khung hình. | Logo mũ/chữ vai trò còn lỗi; nguồn được root chọn cho bản review, chưa được người dùng duyệt. |
| SLOGAN | `SLOGAN_V004.mp4` | root_picked: Chữ NEWTECONS = CÙNG NHAU BỨT PHÁ đúng canon; giữ đủ reveal. | Chưa có voice slogan mới; WAV cũ khác lời nên loại, chỉ nhạc. |

## CHỖ NÀO BẠN ĐOÁN — NÓI THẲNG

- Ba khung hình chỉ kiểm mẫu: không chứng minh sạch lỗi logo/miệng trong từng frame. Không gọi ASR là đã nghe duyệt.
- Thời lượng slot được nới khi cần giữ trọn hành động/thoại; EDL V014 chỉ giữ thứ tự và đúng 16 slot.
- Timing có nguồn nhận dạng/receipt và mức sai khác trong timing.json; từ thiếu được đánh dấu ước lượng, không coi đã xác minh.
- Ranh giới từ “Mai” ở S03 được điều chỉnh theo năng lượng âm thanh vì ASR bắt muộn; đây là suy luận âm học, chưa phải nghe duyệt. Receipt gốc vẫn được giữ.
- Các vấn đề được nêu ở cột còn thiếu chưa được sửa bằng việc đóng gói bản review.

## File và SHA256

- `PREVIEW_2K_OVERNIGHT_V008.mp4` — `2e0017da0e11bafdce872b092b4d0511f0c3abd6b902c55e1bb53b6b64363880` (154677828 byte).
- `PREVIEW_1080P_OVERNIGHT_V008.mp4` — `8e315668d4c17e972cbd237a9967db8f6890fc43830ff615e1f0eb73abacd5cb` (99001730 byte).

Bằng chứng: manifest.json, v2-rescan.json, decisions-snapshot.json, *-ffprobe.json, delivery-loudness.json, timing.json, karaoke.ass và CONTACT_SHEET*.png.

Đối chiếu timing:

- S02_A: hash_bound_receipt, timed; ASR: receipt có hash khớp.
- S03_A: local_faster_whisper_cpu_int8, review_required; ASR: Mai em xuống công trường, cùng anh ra xoát, chốt ngày phương án nhé!.
- S03_A_REPLY: local_faster_whisper_cpu_int8, timed; ASR: Dạ, rõ rồi anh..
- S04_A: hash_bound_receipt, review_required; ASR: receipt có hash khớp.
- S05_A: local_faster_whisper_cpu_int8, timed; ASR: Giờ mà em không biết dùng AI hỗ trợ công việc là sẽ bị chậm hơn người ta nhiều đó..
- S05_FEMALE: hash_bound_receipt, timed; ASR: receipt có hash khớp.
- S05_FEMALE_THANKS: hash_bound_receipt, timed; ASR: receipt có hash khớp.
- S06_A: local_faster_whisper_cpu_int8, review_required; ASR: Dự án đạt chất lượng và bàn giao đúng tiến độ. Cả bàn chỉ huy chúng ta xứng đáng được phân danh..
- S07_PRE: hash_bound_receipt, timed; ASR: receipt có hash khớp.
- S07_A: hash_bound_receipt, timed; ASR: receipt có hash khớp.

## Bảng cao độ (F0 pyin trung vị) mọi nhân vật nói

| Slot | Nhân vật | Profile | F0 trung vị (Hz) | Khoảng nam (<180)? |
|---|---|---|---|---|
| S02_A | GDDA đạo diễn | d9d994a3 (theo brief) | 141.9 | nam <180: ĐẠT |
| S03_A | KKT_TB (nam) | 2aa9b44e FLEURS_M_145Hz_K | 158.3 | nam <180: ĐẠT |
| S03_A_REPLY | Người đeo kính (nam) | 0e61ba93 FLEURS_M_adult | 111.3 | nam <180: ĐẠT |
| S04_A | Người nói S04_A (chưa rõ; đoán GDDA) | clip user đã duyệt, profile không ghi ở slot | 229.2 | CẦN ROOT KIỂM: F0 229 Hz thuộc dải nữ, chưa biết nhân vật nam hay nữ |
| S05_A | CHAR_07 (nam, kỹ sư trẻ) | 0e31d579 FLEURS_M_163Hz_J | 163.0 | nam <180: ĐẠT |
| S05_FEMALE | Nữ nhân viên | clip đã duyệt, profile không ghi ở slot | 175.7 | nữ (không áp tiêu chí nam) |
| S05_FEMALE_THANKS | Nữ nhân viên | clip đã duyệt, profile không ghi ở slot | 227.8 | nữ (không áp tiêu chí nam) |
| S06_A | CHT (nam) | 251e559a FLEURS_M_deep | 115.9 | nam <180: ĐẠT |
| S07_PRE | Lan Anh (nữ) | e02a9343 | 280.5 | nữ (không áp tiêu chí nam) |
| S07_A | Nhân vật S07_A (chưa rõ) | không ghi ở slot | 288.7 | CẦN ROOT KIỂM: F0 289 Hz thuộc dải nữ, chưa biết nhân vật nam hay nữ |