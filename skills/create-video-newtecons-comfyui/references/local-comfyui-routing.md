# NEWTECONS — tạo/sửa ảnh và video bằng ComfyUI local

Quyết định mới nhất của người dùng ngày 2026-10-23: dùng RTX 5080 và workflow ComfyUI có sẵn để tạo ảnh, giữ mặt, thay trang phục và tạo video có thể chỉnh sửa lại. GPT/Gemini phụ trách kịch bản, prompt, điều phối và review; không mặc định gọi model ảnh GPT. Quyết định này thay ưu tiên Image Gen 2 trước đó cho công việc NEWTECONS tiếp theo. Không đổi nhãn engine của ảnh lịch sử. Không tự fallback cloud khi local thiếu dependency.

## Bằng chứng local đã kiểm

Runtime: `production-local/ComfyUI`, API `http://127.0.0.1:8188`. Báo cáo máy đọc: `docs/handoffs/2026-10-23-COMFYUI-LOCAL-CAPABILITIES.json`, gồm hash workflow, node có/thiếu và model file. Đây là kiểm schema/inventory, chưa phải chạy pilot.

- Có workflow Head Swap/Body Swap Krea2, Qwen Edit, Qwen2.1, Flux2 Klein; InstantID; LivePortrait; Hunyuan T2V và FLUX T2I trong `user/default/workflows/`.
- InstantID gọi các node `IDGenerationNode`, `IDBaseModelLoader_local`, `Ipadapter_instantidLoader`, `IDControlNetLoader`, InsightFace; các node đó chưa được đăng ký ở runtime đang chạy. SDXL base và ip-adapter cũng không thấy trong model inventory hiện tại.
- Krea/Qwen/Flux swap còn thiếu node xử lý ảnh hoặc model/encoder/VAE/LoRA theo từng graph. Qwen3-VL32B đang có là encoder H3, không phải model Qwen Image Edit. Không suy ra node Qwen/Flux core có sẵn đồng nghĩa weights đã cài.
- Hunyuan T2V lưu sẵn còn thiếu nhóm/node như `workflow>HUNYUAN`, `VHS_VideoCombine` và weights theo graph. FLUX template có group chưa được resolve. Cần kiểm phần group mở rộng trong UI, không chỉ tên node.
- Model đang thấy: H3 ref2va/fl2va, encoder Qwen3-VL32B và hai VAE H3; SeedVR2 3B/7B và VAE; Wan2.2 **low-noise**14B + UMT5 + VAE; Hunyuan3D; RealESRGAN. Không coi riêng checkpoint low-noise là một pipeline Wan hoàn chỉnh đã chạy.
- Node có tên API/Cloud/partner trong ComfyUI có thể gọi dịch vụ ngoài. Chúng không phải bằng chứng CUDA local và không thỏa lựa chọn local chỉ vì mở trong ComfyUI. Container chạy `--disable-partner-nodes` và `ClaudeNode` bị cấm trong graph render; chi tiết ở [SKILL.md](../SKILL.md).
- Snapshot GPU: RTX5080 16303MiB, khoảng15482MiB sử dụng,100%GPU, H3 cũ đang chạy +5pending. Không cài nóng/restart/ngắt queue hoặc chồng model ảnh lên H3 trong bước bàn giao.

## Công việc bắt buộc ở session tiếp theo

1. Gemini3.8Flash kiểm dependency từng graph trong báo cáo, tìm model đã có ở nơi khác nếu được cấu hình và kiểm đường dẫn trước tải. Chọn **một** đường ảnh local phù hợp giữ nhận diện/thay trang phục; không cài mọi model chỉ vì có template. Tra nguồn chính thức của custom node/model, kiểm tương thích/license, dung lượng và recipe16GB trước bổ sung. Nếu cần restart, lưu queue/history/job IDs và chờ quyền sở hữu/điểm an toàn, không bỏ job.
2. Chuẩn hóa graph GUI và API, phân biệt model ảnh, adapter giữ mặt, pose, mask/inpaint, logo/text và model video. Dùng ảnh mặt riêng từng CHAR, nguồn áo/nón/gile/suit và nội thất thật. T2V thuần không thay bước tham chiếu danh tính/trang phục của cast; dùng ảnh đã kiểm làm guide cho I2V/R2V khi cần.
3. Khi GPU rảnh, chạy pilot một nhân vật với mặt + áo sửa chuẩn (bao gồm lưới vải nhỏ, logo cổ, gile đúng chữ và vị trí) và một action. Lưu job ID thật, actual queued graph, model file/hash, seed, prompt đầy đủ, references/hash, mask/pose, sampler/steps/CFG, kích thước, output/hash, peakVRAM/thời gian và QA. Một graph hợp schema chưa phải pilot đạt.
4. Tạo/kiểm bộ trang phục lookup dùng lại, rồi áp dụng vào tất cả ảnh sai theo `qa/wardrobe-rebuild-required.json`. Chỉnh vùng áo có mask phù hợp và bảo toàn mặt/tóc; kiểm cả sau chỉnh, không hứa giữ mặt tuyệt đối chỉ nhờ prompt. Cập nhật scene/anchor và revision/hash thay thế. Chỉ batch8×20 sau pilot và QA thực.
5. VoiceStudio WAV cuối → ComfyUI H3 diễn/nhép → SeedVR2 7B → ASR theo exactWAV → HyperFramesgraphic/Remotion24fps. Không dùng ảnh tĩnh zoompan làm bằng chứng phim chuyển động.

## Contract để chỉnh sửa lại

Mỗi asset/shot có `workflow.gui.json`, `workflow.api.json`, receipt/job ID và nguồn bất biến. Lưu **graph thực được queue**, không chỉ template. Mỗi tham chiếu có vai trò cụ thể (identity / wardrobe / architecture / audio). Output có revision riêng, không đổi seed/ref mà giữ receipt cũ. Registry cấp mã trang phục, bind vào CHAR/scene; prompt từng ảnh/shot vẫn mô tả đầy đủ người, áo, hành động, camera, ánh sáng. Khi chỉ sửa áo hoặc chữ/graphic, dùng nguồn ảnh/clip đã lưu và nhánh chỉnh phù hợp; không render lại toàn phim vô điều kiện. Thay identity/wardrobe anchor kéo theo đối chiếu các shot phụ thuộc. Gửi graph qua helper có khóa chung `comfy_guarded_submit.py`, không gửi thô; xem [SKILL.md](../SKILL.md).

Lựa chọn local không đồng nghĩa không tốn token: GPT/Gemini vẫn dùng token cho nội dung/điều phối/review; inference ảnh/video local dùng GPU. Không tuyên bố engine hoặc face lock đã đạt trước bằng chứng hình/AV đúng hash.
