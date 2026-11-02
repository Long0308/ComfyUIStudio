# ComfyUI ảnh local — nghiên cứu RMBG và ZHO, 2026-10-23

Áp dụng cho NEWTECONS: 8 CHAR × (10 biểu cảm + 10 hành động), người thật, ảnh so sánh GPT, áo phản quang đúng mẫu và chữ tiếng Việt đúng từng ký tự. Đây là kết quả đọc nguồn và phân tích graph bởi **gpt-6-astra** (model do parent xác nhận từ kết quả spawn); **không phải chứng nhận node đã cài, model đã có hoặc ảnh đã đạt**. Video vẫn dừng theo yêu cầu người dùng. Runtime hiện hành do parent xác nhận đã trở lại `http://127.0.0.1:8188`; mỗi lần thực thi vẫn kiểm `/object_info` và `/queue`. Receipt lịch sử 8189 giữ nguyên endpoint thực tế của chúng.

## Nguồn và phạm vi thực sự đã kiểm

- [1038lab/ComfyUI-RMBG](https://github.com/1038lab/ComfyUI-RMBG): HEAD `a66a5e641a54988d80ed6aad18946081c85f309e`, upstream v3.3.0, changelog 20/10/2026; đọc cây đầy đủ và parse **15/15 JSON example_workflows**. Các source module Python được đọc tĩnh, không import hay thực thi.
- [ZHO-ZHO-ZHO](https://github.com/ZHO-ZHO-ZHO): API liệt kê **88 repo**, page 1 có 88, page 2 rỗng; tải README 88/88 và đọc cây recursive **88/88 repo**. 56 cây dùng GitHub API; 32 cây còn lại dùng public Git shallow/blobless sau khi hết quota REST, không checkout hoặc chạy code/model.
- Tổng hai nguồn: **214/214 file `.json` hiện có đã đọc**, gồm **98 graph JSON trong repository**, cộng graph từ liên kết README thành **100 payload graph trong ledger** sau loại bản linked trùng SHA256. Hai file cấu hình IDE có trailing comma được xem trực tiếp, không phải workflow. Parse cả node trong group definition; 76 liên kết JSON README đã kiểm, 3 liên kết trả 404. Phạm vi này bao trùm JSON trên nhánh mặc định hiện tại; không tuyên bố đã đọc mọi graph lịch sử, workflow nhúng PNG/JPG/GIF hoặc nguồn bên ngoài.
- Bằng chứng tại `docs/research/comfyui-github-20261023/`: `coverage.json`, `commit-heads.json`, `source-inventory.json` (Git blob SHA đối chiếu), `workflow-ledger.json`, `WORKFLOW-LEDGER.md`, `REPOSITORY-INVENTORY.md`, `rmbg-node-map.json`, source text và README. Lần truy xuất UTC được ghi trong JSON.

## Những điều phải phân biệt trước khi dùng

1. **ZHO là một tài khoản, không phải một plugin duy nhất.** Main [ComfyUI-Workflows-ZHO](https://github.com/ZHO-ZHO-ZHO/ComfyUI-Workflows-ZHO) tại HEAD `5748e40d3678a1ca2a436764f29ead379be4061a` có 17 JSON; README trỏ sang nhiều repo khác. Các group `workflow/FLUX`, `workflow>HUNYUAN`, `workflow/StableCascadeInpaintCnet` cần resolve trước khi chuyển sang API. File mở được trong UI chưa chứng minh đủ dependency.
2. **Local app không đồng nghĩa local inference.** BananaFace/banana apps dùng Gemini API key; ComfyUI-Gemini, Qwen-VL-API và StableDiffusion3-API gọi dịch vụ. Chỉ tham khảo cách cấu trúc prompt/UI; không dùng cho route ảnh local của dự án. `fromhub` ở InstantID/PhotoMaker lại là tải model về rồi inference local, không phải hosted image API; vẫn phải quản lý cache và downloads.
3. **InstantID pose_ref chỉ là pose quanh khuôn mặt.** README chính chủ ZHO nói rõ không tương đương OpenPose toàn thân. Động tác tay, chân, tablet, bộ đàm cần pose/control riêng và kiểm ảnh. InstantID/PuLID/PhotoMaker không bảo đảm giống 100%, không khóa chữ hay sọc áo. [Nguồn](https://github.com/ZHO-ZHO-ZHO/ComfyUI-InstantID#节点说明--features).
4. **Có repo chưa có implementation để dùng.** Ví dụ AnyText, MatAnyone, FractalGen, QwQ-32B, SmolVLM2 trong snapshot có README/WIP rất ngắn; không suy ra chúng sửa được chữ thêu hay biểu cảm ngay. Không lựa model theo tên repo.
5. **Tên node tiếng Việt là metadata.** Sửa GUI `title`, tên nhóm, ghi chú và API `_meta.title`; giữ nguyên `type`, `class_type`, tên socket và enum để tương thích. Prompt mô tả bằng tiếng Anh; literal chữ thêu giữ tiếng Việt đúng dấu.

## RMBG: dùng mask đúng nghĩa

| Node class thực tế | Vai trò phù hợp | Điều phải kiểm |
|---|---|---|
| `BiRefNetRMBG` | Tách người/tóc/biên; tạo foreground mask | `background=Alpha` trả IMAGE RGBA, MASK và MASK_IMAGE; màu nền khác trả RGB. `invert_output=false`: mask trắng là phần giữ lại. `refine_foreground` có thể đổi màu RGB, không bật khi cần giữ crop nguyên pixel. |
| `ClothesSegment` | Mask áo theo semantic class | `Upper-clothes` gộp vùng áo, không có class riêng cho gile NEWTECONS/sọc/logo; cần giao với ROI và loại mặt/tay/áo trong. |
| `FaceSegment` | Mask da/mắt/mày/miệng theo bộ phận | Chọn rõ Skin/Nose/Left-eye/Right-eye/eyebrows/Mouth/lips; giữ kính, tóc, nón, quai nón theo mask bảo vệ. Không dùng toàn bộ hình chữ nhật khi tóc/kính nằm trong đó. |
| `Segment`, `SegmentV2`, `SAM2Segment`, `SAM3Segment` | Chọn vật thể/áo bằng prompt hoặc tín hiệu phù hợp | Khác model và schema. Dùng node đang thực sự đăng ký, không thay class bằng một tên giống nhau. |
| `AILab_Florence2` + `AILab_FinegrainBoxSegment` | Phát hiện hộp rồi tinh chỉnh matte của vật thể | Có example `Florence2_Finegrain_box.json`; cần đúng bbox coordinate space và model riêng. |
| `AILab_MaskEnhancer`, `AILab_MaskCombiner`, `AILab_MaskOverlay` | Chỉnh biên/giao-trừ mask/xem vùng tác động | Xem overlay trên ảnh gốc trước queue; loại lỗ mask sai, viền áo bị ăn vào tay. |
| `AILab_ReferenceLatentMask` | Đưa mask vào conditioning/latent cho route Kontext | Đầu vào trắng = vùng inpaint. Node có `noise_mask` khi mask_only; đây không phải cam kết pixel ngoài mask bất biến sau VAE. Compositing ảnh gốc ở cuối vẫn cần. |
| `AILab_LamaRemover` | Xóa vật thể/nền cục bộ | Không phải identity generator hay công cụ sửa chữ có bảo đảm. |
| `AILab_Canvas` | Căn lớp/kiểm bố cục trực quan | Không tự giải phối cảnh, tỷ lệ người, bóng tiếp xúc hoặc ánh sáng khác nhau. |

Nguồn code: [BiRefNet](https://github.com/1038lab/ComfyUI-RMBG/blob/a66a5e641a54988d80ed6aad18946081c85f309e/py/AILab_BiRefNet.py), [ClothesSegment](https://github.com/1038lab/ComfyUI-RMBG/blob/a66a5e641a54988d80ed6aad18946081c85f309e/py/AILab_ClothSegment.py), [FaceSegment](https://github.com/1038lab/ComfyUI-RMBG/blob/a66a5e641a54988d80ed6aad18946081c85f309e/py/AILab_FaceSegment.py), [ReferenceLatentMask](https://github.com/1038lab/ComfyUI-RMBG/blob/a66a5e641a54988d80ed6aad18946081c85f309e/py/AILab_InpaintTools.py).

Contract nội bộ cho mask: `1 = vùng cho phép sửa`, `0 = bảo vệ`; ảnh/mask cùng kích thước và tọa độ. Mask tách người của RMBG phải đảo khi muốn sửa nền. Mask alpha của loader khác có thể đảo nghĩa: xác minh bằng preview và một pixel foreground/background, không nối theo tên. Lưu cả PNG mask và hash. Sau diffusion, lấy ảnh đã sửa ghép qua mask vào parent gốc; kiểm `output == parent` ở mọi pixel bảo vệ. Mọi resize/color transfer trên toàn ảnh phá điều kiện đó.

Model tối thiểu để bổ sung nếu thật sự cần: `models/RMBG/segformer_face/{config.json,model.safetensors,preprocessor_config.json}` từ `1038lab/segformer_face`; tương tự `segformer_clothes` từ `1038lab/segformer_clothes`. BiRefNet adapter dùng các file cấu hình/Python và weights tương ứng trong `models/RMBG/BiRefNet`, không chỉ một safetensors. Việc tải thiếu model có thể tự xảy ra lần chạy đầu. Kiểm file/cache trước queue. Ưu tiên model BiRefNet đã có thay vì cài toàn bộ suite. Thử mask ở 512/1024, batch 1, unload theo schema đã kiểm, rồi mới generator; đây là điểm khởi đầu thử nghiệm, chưa phải benchmark RTX 5080.

`requirements.txt` upstream có cả onnxruntime và onnxruntime-gpu, transformers/diffusers cùng SAM/GroundingDINO/nobg/refiners. Không chạy pip upgrade tràn vào môi trường đang render. Kiểm version hiện tại, CUDA provider, binary compatibility và import node riêng. `__init__.py` có catch lỗi từng module: banner RMBG Loaded không chứng minh mọi node thành công. [Nguồn](https://github.com/1038lab/ComfyUI-RMBG/blob/a66a5e641a54988d80ed6aad18946081c85f309e/__init__.py).

## Những route ZHO có giá trị thực tế

| Route | Graph / dependency đọc được | Cách dùng cho NEWTECONS |
|---|---|---|
| InstantID local V2 | 6 JSON. `IDBaseModelLoader_local`, `IDControlNetLoader`, `Ipadapter_instantidLoader`, `InsightFaceLoader_Zho`, `IDGenerationNode`, SDXL checkpoint, InstantID ControlNet config+weights, ip-adapter.bin, antelopev2. V1 dùng key cũ `InsightFaceLoader`. | Pilot nhận diện khi local đủ model; pose_ref chỉ quanh mặt. Không thay thế action pose hoặc chữ áo. |
| PhotoMaker | 7 JSON; SDXL + photomaker-v1.bin, local/hub loaders, Ref_Image_Preprocessing và NEW_PhotoMaker_Generation; vài graph thêm LoRA/PortraitMaster/DragNUWA. | Thử nhiều ảnh cùng một CHAR để dựng identity. Không trộn CHAR, tránh graph Disney/DragNUWA cho ảnh người thật. |
| PuLID ZHO | Node diffusers, README WIP V0.9; SDXL Lightning 4-step, EVA/InsightFace, tự tải weights; không có JSON example trong tree. | Tham khảo identity. Chưa có đo VRAM/đạt pilot ở máy; không gọi là PuLID Flux hay Klein. |
| UltraEdit | 3 JSON, SD3 UltraEdit global/mask. Local loader cần transformer, 3 text_encoder/tokenizer, VAE, scheduler; mask socket là IMAGE. Code resize về diện tích 512×512. | Tham khảo chỉnh vùng áo; phải MaskToImage đúng nghĩa. Không phù hợp để nhận ngay chữ nhỏ/high-res; phải composite parent cuối và QA. Không phải Qwen Edit. |
| Differential Diffusion | 2 graph Playground2.5; DifferentialDiffusion + InpaintModelConditioning + KSampler + checkpoint tương thích. | Học kiểm độ mạnh mask mềm. Không cắm checkpoint SDXL/EDM vào Flux/Klein vì cùng gọi là inpaint. |
| YoloWorld + EfficientSAM | 2 graph ảnh + 2 graph video; Yoloworld_ModelLoader_Zho + ESAM_ModelLoader_Zho + Yoloworld_ESAM_Zho. | Chọn vật thể/áo rồi inpaint/composite. Nếu RMBG đang đủ chức năng, không cài thêm chỉ để trùng mask. |
| Portrait Master | Bộ sinh prompt/selector, không phải model giữ mặt. | Học cấu trúc mô tả biểu cảm/mắt/miệng/ánh sáng; giữ English prompt và title tiếng Việt. |
| Text_Image-Composite | Chữ → ảnh, ghép ảnh, font. | Có thể tham khảo tạo artwork chữ đã chuẩn hóa. Không coi flat text paste là thêu đạt; cần perspective, nếp vải và crop optical QA. |
| IC-Light / LivePortrait / DepthFM | Repo/graph tham khảo relight, chuyển biểu cảm/pose mặt, depth. | Dùng như bước bổ trợ có kiểm riêng. LivePortrait Animals trong main repo không phải preset người lớn. Chưa kích hoạt video. |
| AuraSR / APISR / SUPIR | Các route restoration riêng; APISR hướng anime. | Không dùng upscale để “chứng minh” mặt tự nhiên, chữ đúng hoặc expression đạt. Giữ original để đối chiếu. |

Nguồn: [PhotoMaker](https://github.com/ZHO-ZHO-ZHO/ComfyUI-PhotoMaker-ZHO), [PuLID](https://github.com/ZHO-ZHO-ZHO/ComfyUI-PuLID-ZHO), [UltraEdit code](https://github.com/ZHO-ZHO-ZHO/ComfyUI-UltraEdit-ZHO/blob/f1237804fbfb390fc1993c6e8fac88b9efa8377c/UltraEdit.py), [Differential Diffusion](https://github.com/ZHO-ZHO-ZHO/ComfyUI-Differential_Diffusion-Workflows), [YoloWorld](https://github.com/ZHO-ZHO-ZHO/ComfyUI-YoloWorld-EfficientSAM), [Text composite](https://github.com/ZHO-ZHO-ZHO/ComfyUI-Text_Image-Composite).

## Recipe áp dụng: một workflow dự án, toàn bộ 160 ảnh

Đọc contract vận hành mới trong [image-video-linked-workflows.md](image-video-linked-workflows.md) và tiêu chuẩn nhân vật/sọc trong [character-quality-and-reflectors.md](../../create-video-newtecons/references/character-quality-and-reflectors.md). Dùng manifest đầy đủ tại `production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/production-v2-45s/local-image-e2e/human-expression-performance-v002/manifest-160.json` (80 biểu cảm riêng: `manifest-80.json`). Backup workflow được đăng ký tại `local-image-e2e/workflow-backup-20261023-v001/manifest.json` trong cùng pack; đối chiếu sự tồn tại/hash lúc dùng, không suy từ tên rằng backup thành công.

Một master GUI có các nhóm tiếng Việt và bảng nhiệm vụ 160 dòng; từng CHAR có 10 expression + 10 action. Các receipt API graph riêng vẫn lưu để replay chính xác. Master là graph có input/task selector và branch thực, không phải 160 file được gom trong một Note. Chỉ bật nhánh/task cần queue để không chạy vô tình tất cả output node. Khi compile phải resolve group và giữ node titles tiếng Việt.

Luồng đề xuất: **Nạp danh tính và mẫu chuẩn → Chọn nhân vật/nhiệm vụ → Mô tả tiếng Anh → Mask/pose đúng nhánh → Tạo ảnh local → Áp trang phục chuẩn → Chữ/logo/sọc → Kiểm vùng bảo vệ → So sánh GPT → Lưu ảnh và receipt**. Đây là thiết kế đề xuất; implementation và pilot thuộc báo cáo runtime riêng.

- **Expression**: parent neutral đạt trước; dùng cùng identity, bố cục và trang phục. Face mask đủ trán/mày/mắt/má/miệng/cằm theo biểu cảm, giữ kính/quai nón. Generate theo facial description; composite tại mask. Kiểm nhìn thấy khác biệt thật ở mắt/mày/miệng, không chỉ smile prompt đổi mà ảnh như cũ. Không hạn chế toàn bộ expression vào miệng nếu trạng thái cần cau mày/mở mắt. Alice trong phim Sữa chỉ dùng học cách phân rã động tác khuôn mặt, không chuyển khuôn mặt/trẻ hóa/cách điệu hoạt hình sang 8 người lớn.
- **Action**: dựng người và bối cảnh có điều kiện cùng phối cảnh trước, kiểm hands/props/body pose. Sau đó chỉnh áo và mặt bằng mask. BiRefNet cutout dán lên `boicanh.jpg` chỉ là bước tạo mask/nháp bố cục; phải kiểm tỷ lệ, chân tiếp đất, shadow, occlusion và camera. Không batch pipeline đã thấy “người dán lên nền”.
- **Trang phục**: đối chiếu front/back đúng canonical image và visible orientation. Theo mẫu người dùng: sọc ngang ngực bạc-xám; dải dưới có thứ tự cam–bạc/xám–cam, ngắt hợp lý bởi khóa kéo; vị trí/tỷ lệ/nếp gấp đúng ảnh chuẩn. Không suy ra mặt sau từ ảnh mặt trước. Vùng bị tay/đạo cụ che cần occlusion thật, không vẽ sọc đè lên tay. CHAR04/08 office không tự thêm PPE.
- **Chữ**: literal `KHỐI KỸ THUẬT`, `SITE MANAGER`, `PHÒNG THIẾT BỊ` theo hợp đồng CHAR hiện hành; `BCH` là biến thể thư viện. CHAR02/05 chỉ dùng `SITE MANAGER`, không tự dịch. Chữ ở image-left trên túi, logo trắng image-right. Chuẩn hóa NFC và so từng ký tự gồm khoảng trắng, dấu, vị trí. Render/chỉnh artwork sau bước sinh gây biến dạng, rồi kiểm crop pixel cuối; OCR confidence không phải bằng chứng tuyệt đối. Chữ bị che/không đọc rõ phải ghi không đủ bằng chứng. Parent crop bất biến chỉ được kế thừa PASS nếu parent có QA bound đúng hash và toàn crop cuối byte-identical.
- **Ảnh người thật**: da có texture và chuyển sắc tự nhiên; mắt/catchlight, răng, tóc, kính và bàn tay đúng; exposure giữ chi tiết áo trắng; không wax/plastic skin, méo kính, răng nhân đôi hoặc halo ghép mặt. So cùng task với GPT; tác vụ không có mẫu lịch sử ghi rõ thiếu baseline, không lấy hình khác để giả so đúng task.

Prompt khung cho biểu cảm (chèn mô tả CHAR và expression đầy đủ):

```text
Photorealistic photograph of the same adult person as the identity reference.
Preserve age, facial proportions, natural skin texture, hairstyle and eyewear.
Expression: [observable eyebrows, eyelids, gaze, cheeks, lips, jaw and intensity].
Keep the approved garment, reflective stripe layout, helmet and background.
Natural asymmetry, realistic catchlights and teeth, coherent daylight and shadows.
Do not stylize, beautify into a different identity, smooth away pores, distort
glasses or duplicate teeth. Protected areas must remain unchanged in compositing.
```

QA ghi `generated`, `technical_valid`, `visual_review`, `lettering_review`, `wardrobe_review`, `user_acceptance` riêng. Không tuyên bố 160/160 hoàn thành từ số file. Người dùng nghiệm thu sau, trạng thái acceptance giữ PENDING. Mỗi output có seed, English prompt, identity/garment/background/mask refs+hash, model/config hash, GUI/API graph thực queue, prompt_id, output hash và revision mới.

Prompt đầy đủ phải sống qua UI Run: theo [prompt transport](../../create-video-jenniejoykids/references/comfy-prompt-transport.md), kiểm literal STRING và prompt thực trong queue, không chỉ text trong template. Khi video được cho phép lại, theo [frame continuity](../../create-video-jenniejoykids/references/continuous-shots.md): dùng frame cuối **được sử dụng thực tế** của shot trước, lưu PNG lossless/native dimensions + hash, phân biệt guide xác suất với composite frame0 bảo toàn tensor; vẫn cần review chuyển động và đường nối. Recipe ảnh hiện tại không kích hoạt video.

## Model license và khả năng triển khai

GPL của custom node không thay license model. RMBG source ghi BiRefNet Apache-2.0/Lucida MIT; kiểm card đúng weights được chọn. BRIA RMBG-2.0 card nêu non-commercial access; InsightFace pretrained model cũng có điều kiện phi thương mại nghiên cứu. Không ghi “open source = đã được phép cho phim doanh nghiệp”. Dùng evidence model cụ thể và quyền có sẵn của dự án khi chọn route. [BRIA card](https://huggingface.co/briaai/RMBG-2.0), [InsightFace model terms](https://github.com/deepinsight/insightface#license).

Các workflow WF01…WF09, HeadSwap/BodySwap, InstantID và LivePortrait do người dùng nêu phải kiểm file/hash và dependency tại máy. Danh sách GitHub này không chứng minh 9 scene ấy đã mở, đang chạy, hoặc cast/áo đã đạt. Không khởi động video trước khi bộ ảnh được kiểm theo yêu cầu.
