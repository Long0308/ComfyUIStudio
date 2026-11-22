# Shot prompts — Navy–Cyan, lắp ráp MEP

Chỉ dẫn dựng từ asset thật, không receipt generation/render hoặc phê duyệt. Xem `../references/REFERENCE-STATUS.md`. Master 20 giây/60 fps/1200 frame; proof 30 fps dùng frame bằng một nửa. Bind artwork từ manifest thật.

## Quy tắc chung

Hero Navy–Cyan giữ palette/vật liệu/ánh sáng. A01–A04 là tái dựng theo hero, không cắt pixel chính xác. A02 là base sạch; bản cuối dùng compound branded `assets/brand/A02-engineers-branded.svg` và PNG branded đã có, cùng `assets/brand/brand-placement.json` ghi nguồn/phép đặt; cần kiểm logo tại pixel video cuối. Không dùng `evidence/A02-draft-branding-unverified.png` bị loại. Người/mặt/tay đứng yên, không lipsync.

Ribbon A05 liên tục qua 120/300/480/660/780/960. Assembly M01–M06 là part native 2.5D, căn→kẹp giữ→khóa→kích hoạt; không Revit 3D thật hoặc xoay PNG A03 giả 3D. Typography animate bằng frame. SVG chữ hiện có **một whole-phrase `*_RUN_01`**; dùng mask cụm nguyên vẹn. Stagger từ chỉ khi dựng native Unicode bằng font đã kiểm; không nhận có sẵn outline từng từ, không tách dấu Việt.

Một logo nguồn đầy đủ, giữ N/NEWTECONS/®/dòng kẻ/**Build on trust**, khoảng thở và tỷ lệ; không morph hoặc gõ wordmark lần hai. `KHỐI CƠ ĐIỆN` là lớp header riêng; chữ áo độc lập. Soi từng mũ/áo, thiếu pixel tagline/® ghi `UNCERTAIN`.

## S01 — Hero đọc được ngay · 0–2s · [0,120)

> Frame 0 là bố cục công trường Navy–Cyan hoàn chỉnh. T01_WORKSHOP/T02_AI hiện trọn WORKSHOP AI như hai layer độc lập. A01 push nhỏ; compound người branded tĩnh; A06 thấp tương phản. Ribbon đến tablet. Highlight sau frame 0 hỗ trợ title đã đọc được; không blank hook, burst, zoom giật hoặc logo bay xuyên máy quay.

**Dọc:** người giữa/dưới, title trên. **Kiểm:** title frame 0, không logo trùng, không cắt mặt/tay.

## S02 — Người làm công trường · 2–5s · [120,300)

> Reframe tablet bằng 2D, không thay động tác. T04_FIELD_APPLICATION: ỨNG DỤNG AI THỰC TẾ Ở CÔNG TRƯỜNG, whole-phrase mask 120–144, hạ cánh 144, giữ xuyên scene sau. Ribbon rời tablet tới anchor MEP. Phóng người theo content bounds thật; không che thiếu pixel bằng sharpen.

**Dọc:** wrap đã đo, không stretch câu. **Kiểm:** từng logo người; entry và hold đọc được.

## S03 — Căn chỉnh, khóa, kích hoạt · 5–8s · [300,480)

> Giữ nguyên T04 từ S02, không reset ở 300, hold tới 462. M01-base neo; M02-frame căn trục; M03-duct trượt tới mối nối; M04-pipes và M05-tray gài vào vị trí; M07-fixture.svg/.png (1000×800) đã có như reference pose. Timeline tính hai tay kẹp hai khớp riêng: căn/kẹp duct và tray, rút tay, lẫy kim loại khóa rồi activation; M07 là fixture phụ, sáu part MEP không đổi. M06-control-panel hạ cánh rồi activation cyan chạy theo hệ thống. Part có chiều sâu/bóng tiếp xúc/trước-sau nhất quán. Lấy cơ chế suit-up, không nhân vật/bộ giáp/footage Iron Man. A03 chỉ là chuẩn vật liệu; không rotateY hoặc bẻ raster. Ribbon từ module hoàn tất tới panel.

**Dọc:** module đủ lớn, title trên, bớt tertiary detail. **Kiểm:** part tách→căn→khóa rõ, không xuyên nhau; gọi geometry là minh họa.

## S04 — Thông tin tập trung · 8–11s · [480,660)

> T33_DASHBOARD_HOOK: THÔNG TIN TRONG TẦM TAY, dấu ầ đúng. Hạ cánh trước 504, hold tới 642. Tối đa hai panel chính, một dẫn mắt/một hỗ trợ. Assembly hoàn tất là nguồn nhìn, ribbon dẫn tới panel. A04 minh họa; không zoom microtext raster hoặc thêm KPI/% tiết kiệm giả. Chữ có vùng yên và khoảng thở.

**Dọc:** panel xếp dọc, bỏ dư. **Kiểm:** tối đa hai reading targets, dấu đúng, không dữ liệu vận hành bịa.

## S05 — AI × BIM · 11–13s · [660,780)

> T34_AI_BIM_HOOK: AI × BIM, hạ cánh trước 684, hold tới 762. Cụm MEP nối đường cyan ngắn có hai đầu rõ. Học connector/packet từ reference AI–BIM nhưng giữ Navy–Cyan. Không chuyển sang intro trắng 18 giây; không tự nhận Connected/live MCP/tool-call. Không nhồi agenda/icon orbit.

**Dọc:** title lớn, module dưới. **Kiểm:** dấu ×; kết nối là minh họa.

## S06 — Có trách nhiệm · 13–16s · [780,960)

> Nền công trường dịu; T05_RESPONSIBLE_AI thành một nhóm ỨNG DỤNG AI / CÓ TRÁCH NHIỆM. Entry whole-phrase 780–804, hold sắc nét 804–942. Ribbon dưới dấu, không xuyên chữ. Không khiên/chứng nhận/claim tuân thủ mới. Nền chuyển động nhẹ; chữ không rung hoặc scale thở.

**Dọc:** đo wrap/safe area. **Kiểm:** mute đọc trọn trong hold; không ép méo font.

## S07 — End card · 16–20s · [960,1200)

> T01/T02 có display window thứ hai 960–1199, đọc được ngay 960. Một logo NEWTECONS nguyên nguồn, Build on trust; T03_DEPARTMENT = KHỐI CƠ ĐIỆN riêng. T06_DATE/T07_LOCATION/T08_TIME: 14.11.2026 · 12A NEWTECONS và 08:30 – 11:00, hạ cánh trước 990, hold 990–1199. Hai nhóm đọc brand/đơn vị và title/metadata. Đo khoảng thở; không gõ wordmark/tagline mới che raster mờ. Không fade đen.

**Dọc:** brand trên, title giữa, metadata dưới xa mép đáy. **Kiểm:** tagline/® ở pixel cuối; lịch theo canon, chưa xác nhận độc lập.

## Ngôn ngữ hình và nguồn hiện có

Assembly là minh họa editorial 2.5D để đọc part/cơ chế, không phải footage cơ khí photoreal hoặc hình học Revit thật. A01/A02/A03 cung cấp nền/người/vật liệu photoreal tĩnh; ghép với part native bằng ánh sáng, tỷ trọng và khoảng thở. Không gọi proof 1080p là master/native 4K. M07 đã có trong proof render lại; receipt video đã đo, visual audit cuối đã có, không có blocker lớn trong phạm vi kiểm mẫu; xem báo cáo bên dưới.

Đủ **34 cặp SVG/PNG chữ**. [Audit độc lập](../evidence/independent-text-audit.md) APPROVE text/generator, đo 68/68 hash rerender khớp; không duyệt toàn phim. AI–BIM có sáu file nguồn nguyên byte tại `references/ai-bim-source/`, 6/6 SHA-256 đã đối chiếu, prompt chỉ là dữ liệu tham chiếu.

## Artifact và kiểm

Đường dẫn thực lấy từ `../references/REFERENCE-STATUS.md` và README. Master samples: 0/119/120/144/299/300/462/479/480/504/659/660/684/779/780/804/942/959/960/990/1199; proof 30 fps kiểm thời điểm tương ứng. Đo ffprobe, so seek cùng frame theo thứ tự khác nhau, đưa render cho critic độc lập. Source scan không chứng minh determinism; file video tồn tại không có nghĩa đã được duyệt. Nếu scope sau cần image-to-video, giữ geometry/logo thật, soi frame và bỏ clip méo thay vì che lỗi.

## Delivered proof — measured receipts

[Video intro](../exports/workshop-ai-intro-1080p.mp4): H.264, **1920×1080, 30/1 fps, 600 frames, 20.000000s, 3,841,629 bytes**, silent. Actual file SHA-256 matches [media receipt](../evidence/motion-preview-video.json): `42576bf13437c787d89a05fb64ed5c8d9a4c7bf53928d871cb6ea853d66e495b`; full decode exit **0**. [Assembly clip](../exports/mechanical-assembly-3s.mp4): 3s,90frames,1920×1080,H.26430fps. [Intro poster](../exports/workshop-ai-intro-poster.png) and [assembly poster](../exports/mechanical-assembly-poster.png) are separate stills.

[Landscape HTML](../animation/index.html) and [portrait HTML](../animation/portrait.html) exist. Portrait delivery is HTML + seven sampled1080×1920stills; **no portrait MP4** or final4K60master is claimed. [Render receipt](../evidence/motion-preview-render.json) records **0 required-resource failures** and **5 matching repeated-seek pixel hashes**; this is sampled pixel determinism, not all-frame/cross-machine proof. [Native asset receipt](../evidence/motion-preview-assets.json) records dimensions/alpha/bounds.

[Independent code audit](../evidence/independent-motion-code-audit.md) and [package audit](../evidence/independent-package-audit.md) approve their bounded scopes. [Independent visual audit](../evidence/independent-visual-audit.md) found no major blocker for handoff as a 2.5D technical/editorial intro; this is bounded sampling, not every-frame or physical-contact certification. The auditor decoded and inspected actual MP4 samples at 5.2/5.6/6.0/6.4/6.9/7.4s, confirming staged assembly and later activation without headline collision. Latch details are subtle, not a large dramatic physical-locking action. Portrait decorative gripper bases can reach/crop the edges; main module/text remain intact.

Bounded quality limits from the final visual audit: editorial 2.5D assembly with subtle latch cues; cropped portrait outer gripper bases with central module/text intact; preserved PPE tagline too small for reliable final-video prose readability; minor pale source contour noise at close inspection. No further production edit was requested by that audit.
