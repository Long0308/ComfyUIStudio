---
name: nhan-vat-ai-newtecons
description: Tạo và sửa ảnh bốn nhân vật AI Newtecons, gồm "ảnh kỹ sư nam nhân vật AI newtecons" (newtecons_engineer_character), "ảnh kỹ sư nữ nhân vật AI newtecons" (newtecons_engineer_female), "ảnh cặp nam nữ kỹ sư newtecons" hay "ảnh đôi kỹ sư newtecons" (newtecons_cap_nam_nu), "ảnh đội ngũ one team newtecons 5 người" (newtecons_team_oneteam); kèm bảng BIẾN đổi bối cảnh công trường sang văn phòng hoặc studio, bỏ áo phản quang và nón bảo hộ, đổi chữ KHỐI KỸ THUẬT in trên ngực áo. Dùng cả khi sửa app/tools/tao_anh.py của NEX.
---

# Nhân vật AI Newtecons

Anh Long duyệt 16/09/2026. Chữ đã chốt nằm ở tệp con — đọc trước khi viết prompt.

## Khi nào chạy

- Khách gọi một trong bốn nhân vật, hoặc đổi bối cảnh, đổi chữ trên ngực áo.
- Sửa prompt / ảnh tham chiếu trong `app/tools/tao_anh.py` của NEX.

| Câu gọi | Domain |
|---|---|
| ảnh kỹ sư nam nhân vật AI newtecons | `newtecons_engineer_character` |
| ảnh kỹ sư nữ nhân vật AI newtecons | `newtecons_engineer_female` |
| ảnh cặp nam nữ kỹ sư newtecons · ảnh đôi kỹ sư newtecons | `newtecons_cap_nam_nu` |
| ảnh đội ngũ one team newtecons 5 người | `newtecons_team_oneteam` |
| ảnh **2 nam 2 nữ** · **3 nam 2 nữ** … (câu có SỐ kèm giới tính) | `newtecons_nhom_theo_gioi` |

🩸 Dò giới tính theo RANH GIỚI TỪ: `nữ` nằm trong `nữa`, `chị` nằm trong `chịu`.
🩸 **ĐẾM ĐƯỢC SỐ thì dựng theo SỐ** (`dem_nam_nu`): "2 nam 3 nữ" ⇒ `EXACTLY 5 people: 2 men and 3 women`.
Chỉ có **2 tấm mặt thật** cho N người ⇒ người nam ĐẦU TIÊN khoá `AI HUMAN FACE.png`, người nữ
ĐẦU TIÊN khoá `FaceNu.png`, còn lại là đồng nghiệp KHÁC — câu *"Do NOT clone, duplicate or
reuse the reference faces"* là BẮT BUỘC, thiếu là model nhân bản mặt.

## 5 ĐIỂM KHỞI ĐẦU CHUẨN MỰC (THE 5 STARTING POINTS — BẢNG 01)

Mọi yêu cầu tạo hoặc sửa ảnh nhân vật AI Newtecons bắt buộc phải phân loại ngay vào 1 trong 5 dạng:

| Điểm khởi đầu | Bản chất & Mục tiêu | Dữ liệu đầu vào | Quy cách viết Prompt |
|---|---|---|---|
| **1. New image** *(Tạo mới hoàn toàn)* | Dựng ảnh từ hư vô, chưa có ảnh tham chiếu cụ thể | Yêu cầu / Ý tưởng | Phải đủ 5 thành tố: **Purpose** (xem ở đâu, ai xem) · **Canvas** (tỷ lệ 16:9, 9:16, 4:5) · **Contents** (vật thể đếm được) · **Relationships** (vị trí tương đối) · **Appearance & Checks**. |
| **2. Recreation** *(Tái tạo chuẩn hóa)* | Dựng lại ảnh tham chiếu nhưng đạt chất lượng cao hơn hoặc phối cảnh khác | 1 ảnh gốc sạch (*clean source*) | Lập **Visual Inventory** (danh mục thực thể) + **Reconstruction JSON** (tọa độ chuẩn hóa `0.000 – 1.000`) + danh sách phần tử bảo toàn (*Preserve*). |
| **3. Remix / Multi-ref** *(Hợp nhất đa nguồn)* | Ghép nhiều ảnh: mặt ảnh A + trang phục ảnh B + bối cảnh ảnh C | ≥ 2 ảnh tham chiếu sạch | Gán vai trò độc quyền (`INPUT ROLES`): Ảnh A chỉ lấy mặt, Ảnh B chỉ lấy phom áo; lập danh sách **LOẠI TRỪ** rõ ràng khỏi từng ảnh. |
| **4. Layout / Sketch** *(Từ bản vẽ phác)* | Đi từ wireframe, sketch tay hoặc hình khối thô | Ảnh sketch / layout | Mô tả khối không gian, chú giải ngắn gọn vị trí nhãn, đặc tả chất liệu bề mặt và ánh sáng hoàn thiện. |
| **5. Local edit** *(Sửa đổi cục bộ)* | Sửa một vài chi tiết trên ảnh đã đạt chuẩn mà không phá vỡ tổng thể | 1 ảnh cần chỉnh sửa | Áp dụng hợp đồng 4 thành phần: **Target — Change — Preserve — Allow**. |


## CẤU TRÚC PHÂN RÃ BỐI CẢNH PHỨC TẠP (BẢNG 02: TỪ VĨ MÔ ĐẾN VI MÔ)

Khi dựng ảnh nhân vật trong không gian phức hợp (văn phòng khối kỹ thuật, phòng họp dự án, công trường đang thi công, sảnh đón trụ sở), prompt phải tuân thủ 6 tầng phân rã:

1. **Main Structure (Khung kết cấu tổng thể)**:
   - Tỷ lệ: 9:16 (chân dung đơn), 16:9 (cặp nam nữ / đội ngũ One Team).
   - Góc máy: Ngang tầm ngực hoặc cao hơn một chút (seated/standing eye-level), đường chân trời thẳng tuyệt đối, không méo phối cảnh (no fisheye, straight architectural verticals).
2. **Distinct Zones (Các phân vùng rõ rệt)**:
   - *Vùng chủ thể (Hero Action Zone)*: Kỹ sư nam/nữ đang trong tư thế làm việc thực tế, thảo luận, xem hồ sơ.
   - *Vùng công cụ/đạo cụ (Working Props Zone)*: Bàn làm việc gỗ sồi/đá vôi, bản vẽ kỹ thuật, tablet, laptop, mô hình BIM 3D.
   - *Vùng hậu cảnh (Architectural Background Zone)*: Vách kính nhìn ra đại công trường cao tầng hoặc không gian văn phòng mở hiện đại.
3. **Spatial & Entity Relationships (Quan hệ vị trí & thực thể)**:
   - Kỹ sư đứng/ngồi tương tác tự nhiên, hai tay không đối xứng, một tay trỏ bản vẽ hoặc cầm tablet.
   - Chân tiếp xúc sàn vững vàng, bóng đổ tiếp xúc (contact shadow) sắc nét và tự nhiên.
   - Cặp nam nữ: đứng cạnh nhau phối hợp nhịp nhàng, khoảng cách đồng nghiệp chuyên nghiệp, không chen chúc.
4. **Material Behavior (Hành vi quang học của vật liệu)**:
   - *Văn phòng*: Áo sơ mi dệt caro ô vuông trắng-xanh nhạt (fine gingham) thấy rõ sợi vải; quần tây đen xếp ly phẳng; giày cao gót nhọn da đen mờ (nữ) / giày da công sở (nam).
   - *Công trường*: Áo gile vải navy dày, dải phản quang cam-bạc phản chiếu ánh sáng nhẹ, nón bảo hộ nhựa bóng tự nhiên.
5. **Visual Hierarchy (Thứ bậc thị giác)**:
   - Điểm nhấn thị giác chính (visual anchor): Thần thái tự tin, ánh mắt tập trung của kỹ sư.
   - Hậu cảnh và nội thất đóng vai trò nền tôn vinh nhân vật, không lấn át chủ thể.
6. **Deliberate Freedom (Khoảng tự do có chủ đích)**:
   - Cho phép AI tự nhiên hóa hướng đổ bóng phụ, phản xạ mờ trên mặt kính, hoặc các tòa nhà mờ nhẹ ngoài cửa sổ.

## HỢP ĐỒNG SỬA TRANG PHỤC & PHỤ KIỆN (TARGET — CHANGE — PRESERVE — ALLOW)

Khi người dùng yêu cầu đổi quần áo, thay váy, đổi giày, thêm phụ kiện cho nhân vật:
- **TARGET**: Xác định cụ thể bộ phận (ví dụ: áo khoác ngoài, quần tây, chân váy, giày, túi xách, kính mắt).
- **CHANGE**: Lệnh thay đổi dứt khoát theo mẫu chuẩn (xem `references/prompt-sua-anh.md` từ E1 đến E6).
- **PRESERVE**: Khóa 100% nhân dạng khuôn mặt (`AI HUMAN FACE.png` / `FaceNu.png`), dáng người, màu da, biểu cảm và bối cảnh.
- **ALLOW**: Cho phép hệ quả vật lý tự nhiên (độ rủ của vải, bóng đổ tiếp xúc của giày mới).


## Các bước

1. Chọn nhân vật theo bảng trên, đọc chữ đầy đủ ở `references/prompt-nhan-vat.md`.
2. Chạy `_bien_nhan_vat(mo_ta)` để lấy năm biến: `boi_canh` (mặc định `cong_truong`; `van_phong` khi câu có *văn phòng · office · phòng họp · họp · sảnh · bàn làm việc · hội thảo*; `studio` khi có *studio · nền trắng · phông trắng/xanh*), `dong_phuc` (công trường `phan_quang` — áo gile + dải cam; văn phòng/studio `so_mi`), `mu` (`True` ở công trường, `False` ở văn phòng/studio), `chu_nguc` (mặc định `KHỐI KỸ THUẬT`, in trên gile ngực trái; đổi nếu câu khai tên đơn vị khác, phải IN HOA), `vi_tri_chu` (mặc định `ngực trái`; không bao giờ trỏ vào TÚI áo — cấm logo trên túi, không ngoại lệ).
3. Bối cảnh VĂN PHÒNG (chốt 16/09/2026, chạy thật đã duyệt): áo sơ mi TRƠN đúng như tệp `ÁO PHẢN TRONG.png` — caro ô vuông trắng-xanh (fine white-and-blue gingham): ô trắng xen ô xanh nhạt trên lưới dệt dày, gần thấy từng ô, xa ra tổng thể xanh nhạt. Cả ba ca nam, nữ, cặp nam nữ đều dùng áo này. KHÔNG chữ, KHÔNG logo, KHÔNG phù hiệu, KHÔNG thêu, KHÔNG name tag ở bất cứ đâu trên áo. KHÔNG thẻ nhân viên, KHÔNG dây đeo cổ. KHÔNG nón bảo hộ ở bất cứ đâu trong khung, kể cả đặt trên bàn/ghế/sàn. KHÔNG áo phản quang trong cảnh. Người phải TRÔNG ĐANG LÀM VIỆC: dáng tự nhiên, hai tay không đối xứng, bắt được giữa lúc trao đổi, mắt KHÔNG nhìn ống kính mà nhìn vào bản vẽ/tablet/đồng nghiệp. Cặp: ĐÚNG HAI NGƯỜI, không người thứ ba kể cả phản chiếu.
4. Ảnh tham chiếu ở `AI-Newteons/` — máy dev `L:\61.SetupAgent\awesome-gpt-image-2\AI-Newteons\`, VPS `/home/ubuntu/zalo-kkt/AI-Newteons/`: `FaceNu.png` (mặt nữ) · `AI HUMAN FACE.png` (mặt nam) · `ÁO PHẢN TRONG.png` (áo caro, dùng cho văn phòng) · `ÁO PHẢN QUANG 1.png` · `ÁO PHẢN QUANG 2.png` (gile) · `Nón bảo hộ.png` · `logo nguyen ban.png` (logo nón 3 màu) · `logo trang.png` (logo trắng ngực phải).
   🩸 NỮ ở văn phòng — anh Long chốt 16/09/2026: **đi giày cao gót đen** (mũi nhọn, gót 7–9 cm) và **có thần thái cuốn hút**. Dịch đúng ý đó sang chuẩn ảnh doanh nghiệp: hút ở **dáng đứng, sự tự tin và ánh mắt** — KHÔNG hở hang. Nam đi giày da công sở. Câu chặn đi kèm bắt buộc: *"the charm comes from posture, confidence and the eyes, NOT from revealing clothing"*.
   🩸 **KHÔNG ÁO NGOÀI** (chốt 16/09): sơ mi mặc một mình — không gile, không blazer, không cardigan, không vest, không áo choàng, trên MỌI người trong khung.
   🩸 **NỮ mặc gì**: quần tây đen **HOẶC** váy/xuýp dài tới gối trở xuống (midi/maxi) — luôn đi gót cao. Cấm váy ngắn, cấm ôm sát.
5. 🩸 HAI TỆP MẶT đang ĐỘI NÓN có logo ⇒ ở bối cảnh văn phòng phải ghi rõ: chỉ lấy MẶT, cấm chép nón và cấm chép logo từ ảnh tham chiếu; tóc/chân tóc trên trán dựng lại tự nhiên cho khớp người thật.
6. 🩸 Văn phòng/studio gửi ĐÚNG 3 tấm: 2 mặt + `ÁO PHẢN TRONG.png` (bỏ gile/nón/logo). Công trường gửi kèm gile + nón + logo.
7. Máy ảnh: Sony A7R V + Sony FE 50mm f/1.2 GM (cận đầu–vai 85mm f/1.4 GM; toàn thân khép f/2–f/2.8; cặp/đội ngũ khung ngang khép sâu để CẢ HAI mặt nét). Ngang tầm ngực hoặc cao hơn một chút, chân trời thẳng.
8. Tỉ lệ: một người 9:16, cặp/đội ngũ 16:9. Người dùng nói rõ thì theo. Phải NÓI RA tỉ lệ đã chọn trong câu trả lời. Model KHÔNG tự cắt theo lời dặn — tool gửi `image_config.aspect_ratio` VÀ tự cắt ở máy mình.
9. Chạy thật: NEX (bot Zalo) gọi tool `tao_anh` → OpenRouter → `openai/gpt-5.4-image-2`. Ảnh sinh xong đẩy qua `outbox` cho listener gửi Zalo. Một lượt kèm ảnh tham chiếu đo được 136–147 giây.

Chi tiết máy ảnh: `references/camera-anh-sang.md`. Chữa ảnh đã ra: `references/prompt-sua-anh.md`. Thêm bối cảnh MỚI: thêm hằng `BOI_CANH_<TÊN>` + một dòng regex trong `_bien_nhan_vat()`, khai `dong_phuc`/`mu`/hậu cảnh, thêm một ca vào test.

## 🩸 CẤM

| Cấm | Vì sao |
|---|---|
| Nhắc tên ảnh tham chiếu trong prompt mà payload KHÔNG gửi tấm đó | Model bị hỏi về ảnh nó không nhận ⇒ tự bịa mặt khác. Đã trả giá 16/09 với hai tệp logo. |
| Bỏ câu cấm quay về `BAN TRUYỀN THÔNG` ở prompt công trường | Áo gốc trong skill mang chữ đó — bỏ câu cấm là model quay lại nó. |
| Để OpenDesign thắng khi nhánh cần ảnh tham chiếu | API đó chỉ nhận chữ ⇒ câu "dùng ảnh đính kèm" thành lời nói dối, mà ảnh vẫn ra nên không ai phát hiện. |
| Mô tả vải bằng "micro-checkered" trơ trọi | Model vẽ ra ÁO XANH TRƠN. Phải tả caro ô vuông trắng-xanh như bước 3. |
| Kho Q&A bốc lại câu RA LỆNH (tạo/gửi/vẽ…) | Bot tự nhận đã gửi ảnh trong khi không gửi gì. |
| Góc hắt từ dưới lên · dáng tạo hình kiểu người mẫu · áo bó/hở | Giữ tư thế kỹ sư đang làm việc, máy ngang tầm ngực hoặc cao hơn một chút. |
| Hiểu "gợi cảm" thành HỞ HANG (áo bó, xẻ sâu, hở vai/eo) | Nữ kỹ sư đẹp phải đến từ dáng đứng, sự tự tin và ánh mắt. Ảnh này là bộ mặt Khối Kỹ Thuật — hở hang là sai nhận diện, không phải "đẹp hơn". |
| Đổi thiết kế đồng phục/logo cho "đẹp hơn" | Nhân vật là bộ mặt thương hiệu; sai logo là làm lại cả series. |
| Trông chờ tuyến OAuth sinh ảnh | GPT/Gemini qua Codex, 9router, bridge ChatGPT web chỉ phục vụ model CHỮ — không có đường sinh ảnh. |
| Để chữ **`đứng`** trong danh sách khoá TỈ LỆ | `đứng` là TƯ THẾ. Ca thật 16/09: model tự viết *"…đang đứng cùng xem bản vẽ"* ⇒ ảnh NHÓM 4 người bị ép về 9:16 mà không ai nhìn ra. Chỉ khoá NÓI VỀ KHUNG (khung dọc · khung ngang · 9:16 · 16:9) mới được đổi tỉ lệ. |
| Khai domain mới mà QUÊN `_BO_ANH` | `_ten_anh_cho_domain` trả rỗng ⇒ prompt nhắc "attached reference" mà không gửi tấm nào ⇒ model tự bịa mặt. Đúng lỗi 16/09 với `newtecons_nhom_theo_gioi`. |

## Cửa nghiệm thu

1. `python -m pytest tests/test_tao_anh_nhan_vat.py -q` phải xanh.
2. Chạy thật một lượt rồi XEM ẢNH BẰNG MẮT: mặt khớp ảnh gốc · áo caro ô vuông rõ · không chữ/logo/thẻ trên áo văn phòng · không nón trong khung · đúng tỉ lệ.
3. Kiểm `outbox` phải `sent`.

## Thư viện prompt theo thể loại (user, 2026-10-30)

Nguồn: [USER-PROMPT-NOTES-2026-10-30.md](J:/1.JennieHomeSchool/03%20Voice/docs/prompts/USER-PROMPT-NOTES-2026-10-30.md), mục **A** (sửa trang phục), **C** (Identity Lock), **D** (câu khoá mặt và negative), **E** (da thật). Chi tiết đầy đủ: [prompt-library-2026-10-30.md](references/prompt-library-2026-10-30.md).

**Phạm vi:** chỉ dùng cho nhân vật hoặc diễn viên đã được duyệt. Không dùng khoá mặt để ghép người thật chưa đồng ý.

- **Mục A:** mẫu "Put this [NEWTECONS uniform shirt…] on him…" cho sửa áo NEWTECONS. Ảnh áo chuẩn: `production-local/character-library/newtecons/wardrobe/v001/user-feedback/SHIRT_APPROVED_FINE_GRID_COLLAR_LOGO_REFERENCE.png` (gốc repo 03 Voice).
- **Mục C và D:** Identity Lock ID / REF / LOCK / DETAIL / LIMIT; câu khoá mặt; danh sách negative.
- **Mục E:** da thật. Nâng nét và chữa da nhựa đã có ở [nang-cap-anh.md](references/nang-cap-anh.md) mục ② và ③.
- Liên kết: [tao-anh-prompt-as-code SKILL](../tao-anh-prompt-as-code/SKILL.md) · [gpt-image-2-style-library SKILL](../gpt-image-2-style-library/SKILL.md).

## QUY TRÌNH SẢN XUẤT 2 BƯỚC CHUẨN ĐIỆN ẢNH & TÀI NGUYÊN 3D BLENDER (UPDATE 2026-11-03)

### 1. Phân định rõ 2 bước:
- **Bước 1 (`01_Tao_Nhan_Vat_Chinh_Real_NoctQ.json`)**: Dựng ảnh nhân vật đơn lẻ chân thực nhất (Narrative Action Pose: ngồi bệt, làm việc hiện trường...). Áp dụng công cụ vector typography `tools/apply_branding_auto.py` để đè chữ Unicode (`BAN TRUYỀN THÔNG` / `KHỐI KỸ THUẬT`) và logo 3D Blender lên nón/áo trong 0.1 giây.
- **Bước 2 (`02_Master_Sheet_NEWTECONS_PPE_360_4K.json`)**: Tạo Bản Hồ Sơ Tham Chiếu 360° (Turnaround 3 góc đứng tự nhiên + 6 biểu cảm + 4 bối cảnh lối sống công trường 1024×1024) xuất ra 4K trong 30 giây.

### 2. Bộ tài nguyên 3D Blender đã nạp sẵn trong ComfyUI input:
- `BLENDER_HELMET_FRONT.png`: Nón bảo hộ 3D Blender v004 chính xác milimét, logo đỏ/cyan chuẩn #00ADED, không có quai nón xe máy.
- `BLENDER_VEST_SITE_MALE_FRONT.png`: Áo phản quang kỹ sư 3D Blender v002, dải cam huỳnh quang eo, sọc bạc ngực.
- `BLENDER_VEST_SITE_MALE_BACK.png`: Áo phản quang mặt sau 3D Blender v002.
- `BLENDER_SHIRT_COMPANY_FRONT.png`: Sơ mi sọc caro ô vuông trắng xanh chìm 3D Blender.

### 3. Lệnh chạy 1-Click tự động toàn diện:
```powershell
python tools/run_master_character_pipeline.py "BAN TRUYỀN`nTHÔNG"
# Hoặc: "KHỐI`nKỸ THUẬT"
```
