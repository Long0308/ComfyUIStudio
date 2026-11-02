# NEWTECONS RMBG stage contract

## Mục đích

Dùng `BiRefNetRMBG` để tạo foreground/mask một người, làm lớp bảo vệ mặt, tóc và pixel trang phục trước khi chỉnh sửa đồng phục. Route này không tự tách áo, tóc, da hoặc từng chi tiết logo; đó là mask người tổng hợp.

## Artifact canonical

- Stage: `J:/1.JennieHomeSchool/03 Voice/docs/research/comfyui-github-20261023/rmbg-integration/`
- API: `workflow.api.json`
- GUI: `workflow.gui.json`
- Contract và receipt: `stage-plan.json`, `stage-receipt.json`, `dependency-receipt.json`, `provenance.json`.

## Trạng thái runtime

- Custom node on disk: `1038lab/ComfyUI-RMBG`, commit `a66a5e641a54988d80ed6aad18946081c85f309e`.
- Live `/object_info` chưa có `RMBG`, `BiRefNetRMBG`, `ClothesSegment`, `BodySegment` hoặc `AILab_MaskPreview`.
- Không có reload và không có GPU submit trong lần chuẩn bị.
- Chỉ chuyển khỏi `STAGED_OFFLINE_NOT_LIVE_TESTED` sau khi ComfyUI reload, `/object_info` có đúng node/schema và một pilot CHAR_08 thật trả output RGB/mask có receipt/hash.

## Model

`BiRefNet-general` dùng weight Comfy-Org/BiRefNet MIT đã có sẵn. Cache hard-link nằm trong `models/RMBG/BiRefNet`. Không dùng BRIA RMBG-2.0 CC BY-NC cho sản xuất thương mại. Mọi file code, config và weight phải khớp SHA256 trong `provenance.json`.

## Ba role CHAR_08 phải giữ

1. Identity: `CHAR_08_MASTER_FACE_LOCKED.png`.
2. Approved office silhouette/posture: `CHAR_08_6_GOC_XOAY_GOI_CAM_4K.png`.
3. Primary architecture: `NEWTECONS_OPEN_OFFICE_EMPTY_ORIGINAL.jpg`.

Không thay, trộn hoặc bỏ các role này khi bind stage vào face/uniform pipeline. Một ảnh candidate đã sinh chỉ là subject của mask; nó không thay identity/wardrobe/environment contract.

## Pipeline

1. `LoadImage` đọc một ảnh chỉ có một người.
2. `BiRefNetRMBG` xuất `IMAGE`, `MASK`, `MASK_IMAGE`.
3. Lưu RGB foreground và mask PNG; preview cả hai.
4. Dùng mask người như vùng bảo vệ tổng hợp.
5. Chỉnh áo/đồng phục trong branch riêng, composite trở lại ảnh gốc.
6. So mask biên tóc, kính, tay và quần áo với ảnh nguồn; kiểm pixel ngoài vùng sửa và QA nhận diện/trang phục.

Mask `1` nghĩa là người hiện; `0` là nền. `BiRefNet-general` không chứng minh hair alpha, clothes segmentation, logo hoặc sọc phản quang đúng.

