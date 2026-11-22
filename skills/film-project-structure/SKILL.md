---
name: film-project-structure
description: Tạo và kiểm cây thư mục chuẩn cho mọi loại dự án phim (AI, 3D/Blender, motion, quay thật, quay màn hình) theo giai đoạn sản xuất, đặt tên cảnh/shot bước 10, ảnh đầu–cuối, luật hiệu ứng tối đa 2 lần, QC và giao bản.
---

# Khung dự án phim chuẩn (mọi loại phim, mở rộng được)

Dùng khi bắt đầu một phim mới, khi người dùng hỏi "để file ở đâu", hoặc khi cần audit cấu trúc một dự án phim.

## Cây chuẩn (theo giai đoạn sản xuất, không theo phần mềm)
```
<MÃ>_<TênPhim>\
├─ 00_MUC_LUC.md
├─ 00_ADMIN\        project.json (mã, loại phim, khổ, fps, luật), lịch–chi phí/credit, bản quyền nhạc–font–logo, người duyệt
├─ 01_DEVELOPMENT\  kịch bản, treatment–prompt, tài liệu gốc
├─ 02_PREPRO\       01_Storyboard (SHOT_LIST, CHUOI_ANH_DAU_CUOI), 02_Ho_so_phim, 03_Nhan_vat_CHR, 04_Boi_canh_LOC, 05_Dao_cu_PRP, 06_Previs
├─ 03_PRODUCTION\   SQxxx_<TenCanh>\SHxxx\<thư mục theo loại>
├─ 04_POST\         01_EDIT (HyperFrames, Premiere) · 02_VFX_GFX · 03_SOUND\{Dialogue,Music,SFX,Mix} · 04_COLOR · 05_TITLES_SUBS
├─ 05_REVIEW\       01_Dailies · 02_Benchmark · GHI_CHU_DUYET.csv
├─ 06_DELIVERY\     01_Review · 02_Version · 03_Upscale · 04_FINAL (+FINAL_NOTE.md) · 05_Stems_DME · 06_QC (QC_CHECKLIST.md)
├─ 07_PIPELINE\     01_Skill · 02_Script · 03_Quy_uoc · 04_Template
└─ 99_ARCHIVE\      bản cũ, bản bỏ (không xoá)
```
Thư mục trong mỗi shot theo loại: ai `ref · anchor · gen · workflow` · 3d `layout · anim · render` · motion `design · comp` · live `plate · audio_set · notes` · screen `capture · cut`. Một phim có thể trộn nhiều loại; mỗi shot chỉ mở thư mục mình cần.

## Luật
1. **Số cảnh/shot bước 10:** `SQ010, SQ020…`, `SH010, SH020…`; chèn thêm là `SH015`, không đánh số lại.
2. **Tên tệp:** `<MÃ>_<SQ>_<SH>_<congdoan>_v<NNN>.<ext>` (phiên bản 3 chữ số, không ghi đè; bản cũ sang `99_ARCHIVE`).
3. **Ảnh đầu–cuối:** ảnh chốt đánh số theo cảnh `SQxxx_Knn`; shot = `Kaa → Kbb`; cùng mạch (cùng nhân vật, bối cảnh, máy liền) thì shot sau bắt đầu bằng ĐÚNG ảnh cuối shot trước (chung mã K); cắt trong cảnh: K mới + lý do; đổi cảnh: đánh lại K01 + chuyển cảnh đã chọn. Ghi ở `CHUOI_ANH_DAU_CUOI`.
4. **Hiệu ứng / chuyển cảnh / SFX nghe rõ như nhau: tối đa 2 lần mỗi phim**; chọn theo bối cảnh (cùng mạch: nối liền; đổi góc: cắt + đẩy nhẹ; cùng mạch bay đổi địa điểm: shot nối tốc độ cao; đổi hẳn bối cảnh: chuyển cảnh đồ hoạ). Ghi cột `chuyen_canh`, `hieu_ung` trong SHOT_LIST để script đếm.
5. **Tài liệu (kịch bản, storyboard, hồ sơ phim) nằm ngoài thư mục project của phần mềm dựng** (app HyperFrames hoàn tác thay đổi từ ngoài có thể xoá tệp trong project của nó).
6. **Mọi góp ý duyệt** thành một dòng `GHI_CHU_DUYET.csv` (ngày, người, shot, thời điểm, nội dung, quyết định, sửa ở bản nào).
7. **QC trước FINAL** theo `06_QC/QC_CHECKLIST.md`; người duyệt + ngày ghi `04_FINAL/FINAL_NOTE.md`.
8. Từ "Bible" không dùng với người dùng: gọi là **hồ sơ phim**.

## Script `scripts/tao_du_an_phim.py`
```
python tao_du_an_phim.py tao  <thư mục gốc> <MÃ> <TênPhim> --loai ai,3d,motion --kho 2560x1440 --fps 24
python tao_du_an_phim.py shot <dự án> SQ010 SH010 --ten-canh MoDau --loai ai
python tao_du_an_phim.py kiem <dự án>     # thiếu thư mục, tên cảnh/shot sai mẫu, phiên bản không 3 chữ số, thư mục rỗng, hiệu ứng lặp > 2
```
Chỉ tạo mới, không xoá, không ghi đè. Script tự chép chính nó vào `07_PIPELINE/02_Script`.

## Phim đang làm dở
Không đổi số shot giữa chừng khi timeline (HyperFrames `index.html`, Premiere XML, workflow ComfyUI) đã gắn với tên cũ: chỉ đổi tên thư mục giai đoạn (mức A), số shot bước 10 áp dụng từ phim sau. Đóng app dựng trước khi dời thư mục, tạo lại XML Premiere sau khi dời.
