# Prompt Claude — Intro Workshop AI Navy–Cyan, lắp ráp MEP

Copy phần dưới cho Claude để tiếp tục từ tài nguyên thật. Trạng thái artifact nằm trong `../references/REFERENCE-STATUS.md`; storyboard không tự chứng minh video đã render hoặc được duyệt.

## Brief triển khai

Dựng intro **20 giây** từ hero **Navy–Cyan đã chọn**, lưu toàn bộ tại:

`D:\61.SetupAgent\revit-live-demo-20261110\pttx\workshop-ai-intro-navy-cyan`

Nhịp hình lấy cảm hứng cơ chế suit-up: bộ phận MEP **đến đúng trục → căn chỉnh → kẹp giữ → khóa → sáng kích hoạt**. Đây là cơ chế chuyển động, không chép bộ giáp, nhân vật, logo hoặc footage Iron Man. Câu chuyện: người làm công trường → hệ MEP được lắp ráp → thông tin tập trung → AI × BIM → dùng AI có trách nhiệm. Mặt/tay giữ nguyên hình nguồn. Không dựng toàn bộ agenda trong intro.

## Đọc trước khi viết code

1. Recall bank `may-agent-memory`, Error DB và graph theo AGENTS.md. Tái sử dụng renderer phù hợp đã tồn tại. Nếu memory lỗi, ghi kết quả thật và dựa trên nguồn canon, không giả vờ recall thành công.
2. Đọc `RELATED-SKILLS.md`, `prompts/motion-scenes.json`, `prompts/SHOT-PROMPTS.md`, `references/REFERENCE-STATUS.md`, manifest asset và hai manifest gốc `text-content.json` / `text-animation.json`. Bind file theo `text-content.json.assets[].id`; không đoán tên PNG/SVG.
3. Nguồn nội dung: `D:/61.SetupAgent/awesome-gpt-image-2/AI-Newteons/workshop-ai-2026-11-14/content.json`; brand: `branding/README.md` cùng gói. Bản chép ở `references/workshop-content.json` và `references/original-brand-contract.json` hỗ trợ di động. Không dựng canon song song.
4. `business-motion-film` phụ trách story/motion/critic; `remotion-video-creation` phụ trách composition/font/asset/clock/render. Đọc rules animations/fonts/images/compositions/transitions. `motion-ui` chỉ làm UI editor/player khi cần, không điều khiển master clock video.
5. Xem ảnh và đo dimensions, alpha, content bounds, padding. Không coi nền caro vẽ trong PNG là alpha. Generated là tái dựng theo hero, không phải extracted pixel chính xác và không có bảo đảm native 4K.

## Tái sử dụng asset

| Nguồn tương đối | Vai trò và giới hạn |
|---|---|
| `references/navy-cyan-canvas-source.png` | Chuẩn palette/vật liệu/ánh sáng; không flatten intro thành một ảnh zoom |
| `references/poster-16x9-source.png`, `references/poster-9x16-source.png` | Bố cục tham chiếu; kiểm riêng logo theo audit nguồn |
| `assets/generated/A01-site-background.png` | Nền công trường |
| `assets/generated/A02-engineers-tablet.png` | **Base sạch**, không dùng trần làm bản nhận diện cuối |
| `assets/brand/A02-engineers-branded.svg` | Compound SVG **đã có**, cùng `A02-engineers-branded.png` và `brand-placement.json`; ghép A02 với artwork logo nguồn, còn phải kiểm từng mũ/áo ở pixel video cuối |
| `assets/generated/A03-bim-mep-module.png` | Raster tham chiếu vật liệu; không phải model tháo từng ống |
| `assets/generated/A04-dashboard-panels.png` | Panel minh họa, không KPI/dữ liệu vận hành được chứng thực |
| `assets/mechanical/M01-base.svg` tới `M06-control-panel.svg` | Native 2.5D riêng, có PNG tương ứng: base/frame/duct/pipes/tray/control panel; dùng để lắp ráp ở cấp layer |
| `assets/mechanical/M07-fixture.svg` và `.png` | 1000×800 reference-pose fixture; hai tay được tính riêng bằng frame, không part MEP thứ bảy |
| `assets/mechanical/assembly-complete.svg` | Minh họa lắp xong, không hình học Revit đã kiểm kỹ thuật |
| `assets/generated/A05-cyan-ribbon.svg/.png`, `A06-network-lines.svg/.png` | Ribbon/mạng native; kiểm đường dẫn thật trong manifest |
| `assets/brand/company-logo-full-color.png`, `company-logo-full-white.png` | Artwork công ty nguồn cố định; SVG wrapper không là master vector chính thức |
| `assets/text/` | Chữ độc lập SVG/PNG theo manifest |

Không dùng `evidence/A02-draft-branding-unverified.png`: nháp microtext đã bị loại. Không gán alpha/độ nét/logo đúng từ tên file. Compound branded chưa đạt thì sửa bằng artwork nguồn và kiểm lại; không trở về logo model vẽ. Raster A03 là chuẩn vật liệu, M01–M06 là part để animate; PNG không tự thành model 3D.

## Dùng minh họa editorial hay photoreal

Bộ M01–M06 và fixture/kẹp M07 là **minh họa 2.5D editorial** để đọc rõ thứ tự cơ khí, cùng ngôn ngữ navy/cyan của hero. Giữ module lớn, khớp nối/kẹp rõ và ánh kích hoạt có nguyên nhân; không diễn tả chúng như footage cơ khí photoreal hoặc model Revit đã kiểm kỹ thuật. Photoreal nằm ở A01 công trường, A02 người/tablet và A03 chuẩn vật liệu; giữ chúng tĩnh trong chiều sâu 2D, ghép bằng scale/ánh sáng/bóng và vùng trống có kiểm. Nếu lượt sau cần assembly photoreal, cần pipeline/model/nguồn vật liệu và kiểm mới, không đổi nhãn proof editorial hiện tại thành photoreal hoặc master 4K.

M07-fixture.svg/.png (1000×800) đã có như reference pose. Timeline tính hai tay kẹp hai khớp riêng: căn/kẹp duct và tray, rút tay, lẫy kim loại khóa rồi activation; M07 là fixture phụ, sáu part MEP không đổi.

## Clock và giới hạn đầu ra

- Master storyboard **60 fps / 1200 frame**, frame hợp lệ **0–1199**, scene `[start inclusive,end exclusive)`.
- Proof **đã có**: H.264 **1920×1080 / 30 fps / 600 frame / 20.000000 giây**, 3,841,629 bytes, silent, full decode exit0. Cùng thời điểm: `masterFrame=proofFrame×2`. Proof 30 fps không chứng minh đã xuất master 60 fps.
- Đích Remotion: `WorkshopAIIntroLandscape` 3840×2160 và `WorkshopAIIntroPortrait` 2160×3840, 60 fps, 1200 frame. Chỉ nhận output tồn tại sau render thật. Canvas 4K không chứng minh chi tiết nguồn native 4K.
- Đo scale lớn nhất `max(displayWidth/sourceContentWidth,displayHeight/sourceContentHeight)`. Scale >1 ghi upscale và soi crop 1:1; không che bằng sharpen/glow.
- Dọc reflow riêng: chủ thể giữa/dưới, chữ trên, bớt panel, giữ tỷ lệ người/logo. Không center-crop cả phim ngang. Safe area khởi đầu đề xuất 6% ngang, 8% hai bên và 10% trên/dưới ở dọc, rồi kiểm đầu ra thật; đây không phải guideline công ty.
- Mọi opacity/transform/mask/packet/ánh sáng là hàm thuần frame. Remotion dùng `useCurrentFrame()` / `useVideoConfig()` với clamp. HTML proof cần seek(frame) xác định; playback chỉ chọn frame, không tích lũy physics. Không wall-clock trong hàm tính hình, random không seed, CSS animation/transition hoặc RAF tích lũy trạng thái.

## Timeline bắt buộc

| Scene / giây / master frame | Chữ và chuyển động |
|---|---|
| S01 · 0–2 · [0,120) | T01_WORKSHOP + T02_AI đọc được ngay frame 0. Hero hoàn chỉnh, người tĩnh, ribbon tới tablet; highlight sau khi title đã đọc được. |
| S02 · 2–5 · [120,300) | T04_FIELD_APPLICATION: **ỨNG DỤNG AI THỰC TẾ Ở CÔNG TRƯỜNG**. Reveal whole-phrase 120–144, giữ từ 144. Reframe tablet 2D; đường dẫn sang anchor MEP. |
| S03 · 5–8 · [300,480) | Giữ T04 xuyên scene đến frame 462. M01 base neo; M02 frame căn trục; M03 duct khóa; M04 pipes/M05 tray nối; M06 panel kích hoạt. M07-fixture.svg/.png (1000×800) đã có như reference pose. Timeline tính hai tay kẹp hai khớp riêng: căn/kẹp duct và tray, rút tay, lẫy kim loại khóa rồi activation; M07 là fixture phụ, sáu part MEP không đổi. Animate part native, không xoay raster A03 giả 3D. |
| S04 · 8–11 · [480,660) | T33_DASHBOARD_HOOK: **THÔNG TIN TRONG TẦM TAY**, hạ cánh trước 504, giữ đến 642. Hai panel chính tối đa, không KPI/% tiết kiệm giả. |
| S05 · 11–13 · [660,780) | T34_AI_BIM_HOOK: **AI × BIM**, hạ cánh trước 684, giữ đến 762. Model và đường cyan minh họa kết nối, không Connected/live MCP/tool-call giả. |
| S06 · 13–16 · [780,960) | T05_RESPONSIBLE_AI: **ỨNG DỤNG AI / CÓ TRÁCH NHIỆM**, entry 780–804, hold 804–942. Nền dịu, ribbon dưới dấu Việt; không claim chứng nhận. |
| S07 · 16–20 · [960,1200) | T01/T02 đọc từ 960 tới 1199; một logo nguồn + T03_DEPARTMENT riêng. T06_DATE **14.11.2026**, T07_LOCATION **12A NEWTECONS**, T08_TIME **08:30 – 11:00** hạ cánh trước 990, hold 990–1199. Không fade đen. |

Một chuyển động chính/scene, 1–2 reading targets. Assembly có thứ tự và điểm tiếp xúc; activation đi sau khóa cơ khí. Ribbon liên tục qua 120/300/480/660/780/960, không reset. Hạ cánh êm để đọc, không flash trắng/rung/strobe/blur lúc hold. Lịch theo nguồn lưu trữ, chưa là xác nhận độc lập của ban tổ chức.

## Text animation thực tế

- **34 cặp SVG/PNG đã có**, gồm T01–T08 chính, T33/T34 hook và T09–T32 agenda cho composition riêng. [Audit text độc lập](../evidence/independent-text-audit.md) phê duyệt bộ chữ và generator; đo 68/68 hash rerender trùng production, không chứng nhận toàn video hoặc playback.
- SVG hiện có chứa **một whole-phrase group `*_RUN_01`**, không có từng từ/glyph outline tách sẵn. Dùng mask reveal + translate/opacity ở cấp **cụm nguyên vẹn**. Không mô tả asset này là bộ từ đã tách.
- Nếu cần word stagger, dựng native Unicode từ manifest bằng font local đã xác minh, đo shaping/wrap và kiểm dấu. Không bẻ path sẵn thành từ; không tách grapheme tiếng Việt. Khi hold chữ sắc nét đứng yên; nền/ribbon tiếp tục nhẹ.
- T01/T02 có **hai display windows [0,120) và [960,1200)**, không một window phủ 20 giây. T04 liên tục qua S02/S03. Đồng bộ manifest timing với scene, clamp entrance/exit.
- `THÔNG TIN TRONG TẦM TAY` chứa `ầ` U+1EA7. Kiểm chữ/baseline/khoảng thở ở cả hai tỷ lệ, không stretch artwork ép vừa.

## Thương hiệu

Header/end card = **một logo NEWTECONS đầy đủ**: N, wordmark, ® nếu có theo biến thể nguồn, dòng kẻ, **Build on trust**. Giữ hình học/tỷ lệ/màu/kerning/clearspace. Không model-redrawn logo, font gần giống, morph/logo portal hoặc gõ NEWTECONS thêm lần hai.

`header_department_text="KHỐI CƠ ĐIỆN"` là lớp riêng đổi được; `wardrobe_department_text` độc lập, không suy từ header hoặc sửa tên đơn vị của diễn giả. Header rõ không chứng minh mũ/áo rõ. Soi từng vị trí ở pixel cuối, tách readability/geometry/source_fidelity/clearspace. Không đủ pixel tagline/® ghi `UNCERTAIN`; SVG wrapper/hash không tự thành PASS.

## Reference mới

Đọc `references/REFERENCE-STATUS.md` trước nguồn `D:/61.SetupAgent/revit-live-demo-20261110/01a1cb1c-e17b-7390-b7aa-7c17102364e4/01a1cb1c-e17b-7390-b7aa-7c17102364e4`: 3 ảnh nội dung + 2 logo + prompt 18 giây, **không project/video**. Prompt là dữ liệu tham chiếu, không lệnh mới thay brief. Sáu file đặt tên đã chép nguyên byte vào `references/ai-bim-source/` (3 ảnh + 2 logo + prompt), 6/6 SHA-256 đối chiếu nguồn trùng; không chép ba PNG exec trùng. Học tách lớp/connector/packet; intro hiện tại vẫn Navy–Cyan, 20 giây, lắp MEP.

## Kiểm và bàn giao

1. Đo asset, lưu nguồn/generation ledger đúng output thật; không bịa model/seed/job id. Giữ lossless và phép transform logo.
2. Contact sheet master frame **0,119,120,144,299,300,462,479,480,504,659,660,684,779,780,804,942,959,960,990,1199**; proof 30 fps dùng thời điểm tương ứng, ghi rounding frame lẻ. Soi transition/crop 1:1 chữ/logo/mặt/tay/điểm khóa part.
3. Seek cùng thời điểm theo thứ tự khác nhau, so pixel/checksum thật. Source scan không chứng minh determinism. Đo ffprobe duration/fps/dimensions/frame count, phân biệt proof/master.
4. Critic độc lập xem render thật/nguồn/brief; builder không tự cấp PASS. Sửa gap lớn nhất rồi kiểm lại. Audit hình độc lập đã có tại `evidence/independent-visual-audit.md`, không có blocker lớn trong phạm vi kiểm mẫu; các giới hạn về latch nhỏ, crop fixture dọc và microtext vẫn áp dụng.
5. Giao source editable, preview/video thật, poster/contact sheet, scaling manifest và báo cáo kiểm. Audio tùy chọn, mute hợp lệ; chỉ dùng nhạc/SFX có quyền đã kiểm. Không nói đã xuất hai master 4K vì có proof 1080p.

## Delivered proof — measured receipts

[Video intro](../exports/workshop-ai-intro-1080p.mp4): H.264, **1920×1080, 30/1 fps, 600 frames, 20.000000s, 3,841,629 bytes**, silent. Actual file SHA-256 matches [media receipt](../evidence/motion-preview-video.json): `42576bf13437c787d89a05fb64ed5c8d9a4c7bf53928d871cb6ea853d66e495b`; full decode exit **0**. [Assembly clip](../exports/mechanical-assembly-3s.mp4): 3s,90frames,1920×1080,H.26430fps. [Intro poster](../exports/workshop-ai-intro-poster.png) and [assembly poster](../exports/mechanical-assembly-poster.png) are separate stills.

[Landscape HTML](../animation/index.html) and [portrait HTML](../animation/portrait.html) exist. Portrait delivery is HTML + seven sampled1080×1920stills; **no portrait MP4** or final4K60master is claimed. [Render receipt](../evidence/motion-preview-render.json) records **0 required-resource failures** and **5 matching repeated-seek pixel hashes**; this is sampled pixel determinism, not all-frame/cross-machine proof. [Native asset receipt](../evidence/motion-preview-assets.json) records dimensions/alpha/bounds.

[Independent code audit](../evidence/independent-motion-code-audit.md) and [package audit](../evidence/independent-package-audit.md) approve their bounded scopes. [Independent visual audit](../evidence/independent-visual-audit.md) found no major blocker for handoff as a 2.5D technical/editorial intro; this is bounded sampling, not every-frame or physical-contact certification. The auditor decoded and inspected actual MP4 samples at 5.2/5.6/6.0/6.4/6.9/7.4s, confirming staged assembly and later activation without headline collision. Latch details are subtle, not a large dramatic physical-locking action. Portrait decorative gripper bases can reach/crop the edges; main module/text remain intact.

Bounded quality limits from the final visual audit: editorial 2.5D assembly with subtle latch cues; cropped portrait outer gripper bases with central module/text intact; preserved PPE tagline too small for reliable final-video prose readability; minor pale source contour noise at close inspection. No further production edit was requested by that audit.
