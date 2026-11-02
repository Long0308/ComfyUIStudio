> Current2026-10-19: user selected **SeedVR2 7B**. Milk v005 now uses all12 restored7B clips. The3B/5070 notes below are dated baselines. As of 2026-10-19 the production invocation used `--model 7b --tile-size 1024 --tile-overlap 64 --temporal-overlap 4`; preserve the recipe and saved job IDs. **Superseded 2026-10-27 R27:** production no longer uses tile 1024; use the v003 qualified recipe tile 768 / overlap 64 / internal 17 / raw 21 (prompt `43f87ebe…`) via `production-local/JennieJoyKids-Story/04-milk-and-mom/tools/execute_seedvr2_production_v004.py`; see the [SeedVR2 section](../../comfyui-video-pipeline/SKILL.md#seedvr2-7b-bounded-4k-restoration). Read the production hub current-state and fullfilm delivery receipt before any regeneration.

# SeedVR2 local — phục hồi chi tiết từ clip đã lưu

Chạy nhánh riêng từ video đã chọn, không sinh lại H3. 1080p container hoặc scale
Lanczos không chứng minh model phục hồi chi tiết đã chạy. Giữ native AV bất biến;
chỉ nạp derivative qua `/api/picture/register` sau khi kiểm output thật.

## Model và graph đã dùng

- `ComfyUI/models/diffusion_models/seedvr2_3b_int8_convrot.safetensors`.
- `ComfyUI/models/vae/seedvr2_ema_vae_fp16.safetensors`.
- LoadVideo → GetVideoComponents → ImageScale → SeedVR2Preprocess → VAEEncodeTiled
  → SeedVR2TemporalChunk → SeedVR2Conditioning + KSampler → SeedVR2TemporalMerge
  → VAEDecodeTiled → SeedVR2PostProcessing → CreateVideo → SaveVideo.
- Sampler thử:1step,euler,simple,CFG1,denoise1. Color correction `lab`.
  Giữ cùng target ảnh gốc ở postprocess để bỏ padding và đối chiếu màu.
- Script có receipt/resume:`production-local/blender-bridge/upscale_saved_shots.py`.
  `--shots S01_A` chạy một shot; không tự mở lô lớn trước khi xem và đo.

Giữ tỷ lệ native. Với864×480, target1944×1080; Remotion crop vào1920×1080 khi
 ghép Master. Preprocess pad thời gian4n+1 và không gian; postprocess phải trả về
đúng số frame và kích thước gốc đã resize. Kiểm124frame nguồn vẫn124frame output;
finishing chỉ dùng120frame đầu cho shot5s@24fps, không chèn frame pad vào phim.

## Bằng chứng đo trên5070 ngày18/10/2026

- Một frame S01_A index60:1944×1080,job`865b827e-b5f6-4e2f-a122-cbe2fa2b8c09`,
  Comfy execution5.11s. Đã so crop mặt Alice/Mẹ; tóc/mắt rõ hơn. Đây chỉ là một ảnh.
- Cả clip S01_A:124frame/24fps/5.166667s,1944×1080,
  job`b7d4b6f3-3f35-4249-a42b-93564c1170f9`,2304s khoảng38phút.
  Cấu hình tile512/overlap128,temporal_size32/temporal_overlap8;
  chunk21pixel-frame,overlap1latent-frame. Chưa nghiệm thu nhấp nháy/khẩu hình.
- File/receipt ở episode `picture-derivatives/seedvr2-v1/S01_A/`; so ảnh ở
  `qa/alice-sharpness/`. Chưa ghép clip này vào Master và chưa chạy toàn12shot.

Không dùng kết quả một ảnh để ước lượng tốc độ cả video, không hứa VRAM cố định,
không hứa không offload hoặc giữ nguyên pixel/chi tiết danh tính. Sau đổi5080,
giữ recipe để đo baseline rồi mới thay tile/chunk; xem bàn giaoGPU của workspace.

## Nghiệm thu derivative

Kiểm fps, sốframe, thời lượng, tỷ lệ và decode đầy đủ. So các frame trước/sau và
biên chunk, mắt/răng/tóc/ngón tay, nơ/heart, màu da/đèn và nhấp nháy khi chuyển động.
Nét hơn có thể do chi tiết model thêm vào; không coi độ sắc cạnh là chứng minh giữ mặt.
SaveVideo có thể encode lại âm thanh; không gọi waveform bit-identical chỉ vì
sample rate/thời lượng giống. Native audio giữ riêng và editorial voice/SFX không
đổi theo nhánh hình. Không nạp kết quả lỗi hoặc tạo thêm job trùng khi job cũ còn chạy.

User yêu cầu thêm phép so **Wan2.2**, đã tải low-noise14B FP8+UMT5+VAE và kiểm SHA
publisher. Phép thử refiner img2img cần ghi rõ sampler/denoise/prompt và cùng frame
nguồn; đây không phải so đầy đủ mọi chế độ Wan2.2 với model chuyên phục hồi SeedVR2.
Chỉ cập nhật nhận xét theo output thực, không suy model thắng từ thông số hoặc quảng cáo.


## Kết quả thử Wan2.2 cùng frame

Job`b042a0c7-a08f-4877-86ce-49051aa8108a` đã hoàn tất98.052s:low-noise14B FP8,6step,CFG3.5,denoise0.2. So crop cùng frame thấy nơ/tóc và nét mặt thay đổi; recipe chưa được chọn để phục hồi phim. SeedVR2 rõ hơn và gần source hơn trên frame đã xem. Xem `qa/alice-sharpness/model-comparison-report.json`; không suy ra kết quả cho mọi cấu hình Wan hoặc toàn bộ video.
