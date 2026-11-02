# VoiceStudio Docker (một dịch vụ dùng chung)

- Image `voicestudio:local`, container `VoiceStudio`, `127.0.0.1:8080`, `restart: unless-stopped`, `mem_limit 10g` (không swap).
- Code backend được COPY vào image từ `VS_SRC` (mặc định runtime AppData); không mount code.
- Volume: dữ liệu OmniVoice (rw) -> `/data`; hf_cache trên C: NVMe (ro) -> `/hf_cache`; thư mục Hacht (ro) -> `/models/Hacht_omnivoice-vietnamese`.
- `MODEL_DEVICE` mặc định `cpu` (map sang `OMNIVOICE_DEVICE`). GPU: profile `gpu`, service `voicestudio-gpu`.
- Idle: backend tự unload model sau `OMNIVOICE_IDLE_TIMEOUT_S` (= `IDLE_SECONDS`, mặc định 600). `idle_unload.py` (PID 1) khởi động lại child uvicorn khi model đã `idle` mà RSS vẫn > `IDLE_RESTART_RSS_MB` (1500) để trả RAM thật cho OS.

## Lệnh
```
docker compose build
docker compose up -d                       # CPU
IDLE_SECONDS=120 docker compose up -d      # thử idle 2 phút
docker compose --profile gpu up -d voicestudio-gpu   # GPU (dừng bản cpu trước)
curl http://127.0.0.1:8080/health
```
Chạy được khi RAM vật lý trống >= 12 GB hoặc cả hai server tạm (8081, 18082) đã tắt.
