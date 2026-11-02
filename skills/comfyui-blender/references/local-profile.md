# Hồ sơ môi trường và phạm vi cá nhân

**Applies to:** máy/ứng dụng dùng chung (mọi domain); mục "Cá nhân hóa JennieJoy Kids" và "Bài học mesh và proxy" chỉ thuộc `jenniejoy_cartoon_3d`. NEWTECONS (`newtecons_live_action`) và AEC không kế thừa cast, preset hay bài học trong các mục đó.

> **Cập nhật 2026-10-27 (canonical copy trong `.agents/skills/comfyui-blender`):** GPU hiện tại xác nhận **RTX 5080 16 GB** (một GPU dùng chung với ComfyUI/VoiceStudio; bản Codex gốc từng ghi 5070 12 GB). Các hàng "Bridge trong Blender/ComfyUI" bên dưới là ảnh chụp 2026-10-18; **hôm nay bridge ComfyUI-Blender không hoạt động** vì node chưa nằm trong whitelist của container, xem mục "Live ComfyUI bridge status" trong `SKILL.md`. Danh sách model là ảnh chụp 2026-10-18 và đã cũ (Krea2, Wan, SeedVR2 7B... đã thay đổi); luôn đọc `search_models`/`/object_info` trực tiếp.

> Cập nhật tối18/10/2026: máy **đã thay RTX5080 16GB**, không còn là5070/12GB.
> Driver617.42; ComfyUI PyTorch2.14.1/cu130 và VoiceStudio2.8/cu128 đều có sm_120,
> FP16 GPU đạt. Cycles OptiX đã render thật trên5080. Dùng bản đo và launcher tại
> `J:/1.JennieHomeSchool/03 Voice/docs/handoffs/2026-10-18-SYSTEM-RESTORE-AND-REMAINING.md`.
> Các phép đo5070 bên dưới là lịch sử. VAE video24frame cùng nguồn trên5080:
> tile512/overlap128/tempOverlap8 mất131.573s; tile1024/64/4 mất78.534s,
> đỉnh dùng toànGPU quan sát13680MiB, SSIM với512 là0.987236. Đây là mẫu1s;
> cần đo thêm đoạn đầy đủ trước khi coi mọi video đều vừa16GB. NVENC1080p đã chạy.

Bản ghi 2026-10-18, lấy bằng MCP thực tế. Kiểm tra lại trước khi submit; không dùng bản ghi này thay live health check.

## Máy và kết nối

| Mục | Giá trị đã đọc |
| --- | --- |
| Project root | `J:/1.JennieHomeSchool/03 Voice` |
| Blender MCP | `127.0.0.1:9876`; Blender `5.2.2 LTS`; MCP addon `1.8`, protocol `13` |
| Scene hiện hành đã lưu | `Milk_ApprovedCast_v3_Inspection`; file approved-cast-v3 bên dưới; bản unsaved cũ đã lưu riêng |
| ComfyUI | `http://127.0.0.1:8188`; core commit `e087d8f6` / báo latest0.41.3; comfy-cli `1.22.0` |
| Workspace ComfyUI | `J:/1.JennieHomeSchool/03 Voice/production-local/ComfyUI` |
| GPU / RAM | RTX 5080, 16303MiB (~16GB) VRAM; khoảng64GiB RAM; đã kiểm tối18/10/2026 |
| Bridge trong Blender | (snapshot 2026-10-18, lịch sử) `comfyui_blender`4.5.1 đã cài/bật, kết nối loopback8188; workflow ảnh đã gửi từ Blender |
| Bridge trong ComfyUI | (snapshot 2026-10-18, lịch sử; **không còn đúng ngày 2026-10-27**: node không nằm trong whitelist) Upstream19node đã nạp; thêm project `JennieBlenderRender` đọc GLB/packedBLEND và chạy Blender script riêng |
| Manager | `server_info`: `manager_mode="not-installed"`, `manager_detected="none"` |

Cấu hình endpoint user đã đọc ở `C:/Users/Admin/.codex/config.toml`: `BLENDER_HOST=127.0.0.1`, `BLENDER_PORT=9876`, `COMFY_LOCAL_URL=http://127.0.0.1:8188`. Không copy toàn bộ config hoặc secrets vào manifest.

Đã kiểm MCP và cài bridge khi user yêu cầu đấu nối. Ảnh roundtrip từ Blender,
10GLB vật dụng nhập/render thật và GLB→Blender→H3 đã chạy. Xem evidence
`production-local/blender-bridge/verification.json`, workflows/scripts ở cùng
thư mục. Không dùng trạng thái bridge ban đầu count0 để mô tả cài đặt hiện tại.

## Model được server liệt kê

Đã duyệt 27 nhóm bằng `search_models`; chỉ 7 file weights sau được thấy. Không bao gồm YAML configs hay mã custom node vào số model.

| Nhóm | Filename |
| --- | --- |
| diffusion_models | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` |
| diffusion_models | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` |
| diffusion_models | `seedvr2_3b_int8_convrot.safetensors` |
| text_encoders | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| vae | `minimax_h3_audio_vae_fp32.safetensors` |
| vae | `minimax_h3_video_vae_int8_convrot.safetensors` |
| vae | `seedvr2_ema_vae_fp16.safetensors` |

`checkpoints`, `loras`, `controlnet`, `clip_vision`, `upscale_models` rỗng tại lần kiểm tra. Không vì có KSampler mà cho rằng các ví dụ SDXL/Flux/Qwen/Z-Image chạy được. Không tự tải model mới khi đánh giá skill. SeedVR2 đang nằm ở `diffusion_models`, không tự di chuyển theo hướng dẫn cũ.

## Cá nhân hóa JennieJoy Kids

Nguồn dự án ưu tiên, chỉ đọc phần liên quan:

- `J:/1.JennieHomeSchool/03 Voice/.agents/skills/create-video-jenniejoykids/SKILL.md`
- `J:/1.JennieHomeSchool/03 Voice/.agents/skills/create-video-jenniejoykids/references/character-bible.md`
- `J:/1.JennieHomeSchool/03 Voice/.agents/skills/create-video-jenniejoykids/schemas/project.schema.json`
- `J:/1.JennieHomeSchool/03 Voice/.agents/skills/comfyui-video-pipeline/SKILL.md`

Nếu làm ở máy khác, tìm skill/project tương đương; đường dẫn không tồn tại phải được báo là thiếu, không tự tạo reference giả. Brief Blender là bản bổ sung camera/control, không thay project schema hiện có.

Alice là nhân vật hoạt hình 2 tuổi; giữ nơ/đuôi tóc ở bên phải giải phẫu, không mirror reference. ~~Phong cách mặc định của dự án là preschool 2D, nền storybook mềm, pastel vừa phải.~~ **[Đính chính 2026-10-27: câu bị gạch là chữ cũ. JennieJoyKids là `jenniejoy_cartoon_3d`, phim hoạt hình 3D điện ảnh cách điệu khớp cast đã duyệt; xem `create-video-jenniejoykids/SKILL.md`.]** Trang phục, người tham gia và lời thoại lấy từ tập/shot đang làm.

Các tài liệu hiện có chứa preset khác nhau: character bible có tập đi sở thú với cả Ba/Mẹ; pipeline có preset bedtime với Mẹ và đồ ngủ hồng. Không trộn preset hoặc áp quy định bedtime lên mọi tập. Ưu tiên yêu cầu hiện tại và project JSON đã duyệt; nếu cùng một tập có xung đột về danh tính/trang phục/cast thì làm rõ trước khi sinh.

Thành phẩm JennieJoy hiện dùng VoiceStudio, phụ đề Anh động + Việt bên dưới, hoàn thiện Remotion, output `production-local/JennieJoyKids-Story/{topic}/comfyui-out-render/`. Giữ yêu cầu hiện có của tập. Resolve FPS từ project và dựng/chuyển FPS có chủ đích; không kéo giãn audio để ghép hai FPS khác nhau.

Giữ nguyên launch flags đang dùng. Không tự `free_memory`, unload model của tiến trình khác, restart Blender/ComfyUI hoặc chỉnh workflow để làm đẹp báo cáo kiểm tra.

## Bài học mesh và proxy 2026-10-18

Đây là trường hợp JennieJoy đã đo, không phải preset cho asset khác. AliceGLB job
`4605304f-d7e8-42d2-ae70-b7d34098908f` đã nhập548636đỉnh/1162226mặt; MomGLB job
`d5efccf8-2708-46dc-868b-1c192f5339f9` đã nhập266078đỉnh/546816mặt. Cả hai gộp
tóc/quần áo/cơ thể,0UV, không armature/shape keys. Kiểm4góc thấy geometry mặt sàn
thừa dưới chân và tay/mắt cần topology diễn xuất. Không tính chúng là asset modular/rigged.

Proxy Decimate ratio0.06 cho Alice203850mặt, Mom46288mặt thực sau evaluate; mặt/ngón
tay mất chi tiết rõ. Đã ẩn proxy mặc định và phục hồi source high-detail để kiểm.
Tỷ lệ cấu hình không phải tỷ lệ polygon thực; đọc evaluated geometry. Không dùng
Decimate thay retopology, không đánh dấu giảm polygon là tăng chất lượng.

File hiện hành: `J:/1.JennieHomeSchool/03 Voice/production-local/JennieJoyKids-Story/03-drinking-milk/assets3d/approved-cast-v3/Milk-Approved-Cast-v3-Inspection.blend`;
scene `Milk_ApprovedCast_v3_Inspection`. MeshAlice cũ giữ ở scene riêng và bản sao lưu.
`blender-inventory.json` và `modular-pipeline.json` cạnh file lưu trạng thái thật.
Kiểm lại live scene trước khi sửa. FilmH3, iconPNG và geometry trung gian không chứng
minh Blender đã có rig hay asset game. Blueprint artifact reuse trong
[asset mô-đun/game](reusable-assets-and-game.md) áp dụng cho các dự án khác theo brief riêng.


## Dự kiến đổi GPU — 2026-10-18

> **Đã hoàn tất** (xác nhận 2026-10-27: RTX 5080 16 GB). Mục này là lịch sử; không còn là việc chờ làm.

User sắp đổi RTX5070 sang AORUS RTX5080 MASTER16G, chưa xác nhận đã lắp. Bàn giao tại `J:/1.JennieHomeSchool/03 Voice/docs/handoffs/2026-10-18-RTX5080-HANDOVER.md`. Baseline thực:driver617.42,PyTorch2.14.1+cu130/runtime13.0,Toolkit13.1.115,sm120,CUDA FP16 probe đạt. Giữ venv/model; không cài lại Toolkit chỉ vì đổi card. Sau đổi chạy `production-local/studio-app/gpu_runtime_probe.py` bằng Python ComfyUI, kiểm device/VRAM và job nhỏ; kiểm Cycles/OptiX nếu dùng GPU. Không hứa speedup hoặc tăng batch trước khi đo lại.

Cập nhật model inventory:đã tải Wan2.2 T2V low-noise14B FP8,umt5 FP8,wan2.1VAE để so với SeedVR2 theo yêu cầu user; chưa có output Wan được nghiệm thu. Model có trên đĩa không chứng minh inference được.
