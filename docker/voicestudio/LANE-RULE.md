# Luật lane: VoiceStudio/OmniVoice

1. Mọi lane gọi **http://127.0.0.1:8080**. Không lane nào tự chạy `uvicorn` riêng (mỗi server tạm ~9 GB commit).
2. Nếu 8080 không trả lời: chạy trong thư mục này `docker compose up -d` (chờ `/health` = 200, tới ~4 phút lần đầu).
3. Không kill tiến trình của lane khác. Server tạm cũ (8081, 18082) do lane sở hữu tự tắt.
4. Model tự nhả sau `IDLE_SECONDS` (mặc định 600 s) không có request; request kế tiếp tự nạp lại (chậm hơn lần đầu).
5. Chỉ bật GPU khi ComfyUI H3 không chạy: `docker compose stop voicestudio && docker compose --profile gpu up -d voicestudio-gpu`.
