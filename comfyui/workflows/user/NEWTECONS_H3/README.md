# NEWTECONS — MiniMax H3 R2V live-action

`NEWTECONS_H3_R2V_LIVE_ACTION_v001.api.json` là mẫu graph API cho một shot người thật có thoại. Các ô file để trống có chủ ý; graph chưa sẵn sàng queue hoặc validate đầy đủ cho đến khi đã gắn asset. Không dùng file, prompt, cast hoặc output của JennieJoyKids.

## Ô cần điền cho từng shot

| Thông tin | Giá trị |
| --- | --- |
| ID shot NEWTECONS | |
| Ảnh nhân vật đã duyệt, node `5.inputs.image` | |
| SHA256 ảnh nhân vật và bằng chứng duyệt | |
| Ảnh cảnh/khung hình đầu đã duyệt, node `8.inputs.image` | |
| SHA256 ảnh cảnh và bằng chứng duyệt | |
| WAV thoại đã nghe duyệt, node `7.inputs.audio` | |
| Đường dẫn receipt `preparation.json` của shot | |
| SHA256 `preparation.json → wav.sha256` | |
| Hành động/camera của shot, bổ sung vào node `19.inputs.value` | |

Đặt bản sao nguyên byte của các asset vào thư mục `ComfyUI/input/` mà server đang dùng, kiểm tra SHA256 bản sao, rồi điền **tên file ở input root** vào các node tương ứng. Node 5 cấp ảnh nhân vật cho `ref_images.ref_image_0` (`<Picture 1>` trong prompt); node 8 cấp ảnh cảnh cho guide frame 0. Hai ảnh có thể khác nhau: ảnh chân dung nhân vật không tự chứng minh đã có bố cục shot. Guide resize/crop ảnh cảnh theo canvas, nên chọn bố cục và tỷ lệ phù hợp.

## WAV và receipt

Chọn đúng thoại NEWTECONS đã được nghe duyệt; hợp đồng pipeline chỉ định WAV 48 kHz, stereo, PCM16. Nếu cần cắt im lặng, thực hiện **một lần trước H3**, sau đó tạo receipt cho đúng bản WAV cuối. Khi `preparation.json` của shot đã được tạo, SHA256 của WAV thực tế trong `ComfyUI/input/` phải bằng `wav.sha256` trong receipt, trước khi gửi graph; dùng cùng WAV và offset trong khâu dựng. Không thay bằng bản cắt khác sau H3. Mẫu kiểm tra PowerShell, điền hai đường dẫn trước khi chạy:

```powershell
$h3ReceiptPath = '' # preparation.json của shot
$h3WavPath = ''     # WAV thực tế trong ComfyUI/input
$h3Receipt = Get-Content -Raw -Encoding UTF8 -LiteralPath $h3ReceiptPath | ConvertFrom-Json
$h3WavHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $h3WavPath).Hash
if (-not $h3Receipt.wav.sha256 -or $h3WavHash -ne $h3Receipt.wav.sha256) {
    throw 'WAV không khớp preparation.json → wav.sha256'
}
'WAV SHA256 khớp receipt'
```

Graph này không tạo receipt và không tự kiểm tra hash hoặc trạng thái duyệt. `LoadAudio` → `MiniMaxH3AddGuide` cấp WAV làm điều kiện từ frame 0; audio ghép vào MP4 được **H3 sinh và VAE giải mã**, không phải bản sao WAV nguồn. Kiểm tra nhép, thời gian và âm thanh của kết quả sau pilot.

## Thông số và kiểm tra

- Node 6 mặc định 864×480, `length=124`; node 17 là 24 fps. Node H3 làm tròn số frame lên lưới `17k+5`; 124 frame tương ứng khoảng 5,167 giây, không phải 120 frame/5 giây. Điều chỉnh length theo shot và bảo đảm toàn bộ WAV cùng offset nằm trong thời lượng sinh: guide sẽ cắt latent audio nếu dài hơn phần video còn lại. Node 9 hiện đặt offset `frame_idx=0`.
- `res_multistep`, `beta`, 20 bước, seed `20261030` và kích thước trên là cấu hình khởi đầu để thiết kế, **chưa được kiểm định cho live-action NEWTECONS**. Bổ sung hành động, camera và thông tin shot thật vào prompt; không suy ra nhân vật hay trang phục từ tên file.
- Node 18 dùng `filename_prefix=NEWTECONS/H3/Shot`, `format=mp4`, `format.codec=h264`. Có thể đặt prefix riêng cho shot dưới `NEWTECONS/`. Graph không tự xuất carry frame; shot nối cảnh phải xác định và lưu frame cuối thực sự được dùng theo kế hoạch dựng.
- Root cần validate graph đã gắn file trên server `:8188`; mẫu gốc để trống file nên không thể coi là đã qua validation đầy đủ. Validate không chứng minh chất lượng hay khả năng chạy GPU. Chỉ pilot khi có phê duyệt GPU và đầu vào đã duyệt theo quy trình sản xuất.

## Tích hợp engine hiện tại

Graph là **template độc lập**, chưa phải recipe H3 đã được nghiệm thu. Tại thời điểm thiết kế, `studio-video-engine/recipes/h3/routes-v001.json` chỉ cho `jenniejoy_cartoon_3d`: `jjv h3 inputs/prepare` từ chối `newtecons_live_action`. Ngoài ra `engine/h3/prepare.py` hiện ghi lại các `output_ports` theo prefix `h3/...`, không giữ prefix `NEWTECONS/...` của template. Root cần xử lý cả domain/qualification và prefix trước khi dùng đường prepare đó; không mặc định bỏ qua cổng hoặc tự sửa engine trong task này.

Khi đường prepare NEWTECONS được hỗ trợ, ánh xạ dự kiến là anchor `8.image`, WAV `7.audio`, face ref `5.image`, editorial sink `18`; phải kiểm lại prefix và receipt của graph đã chuẩn bị. Đây là ánh xạ đề xuất, chưa phải bằng chứng tích hợp thành công.
