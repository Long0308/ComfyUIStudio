# CHAR08: batch r063 đã dừng, giữ4ảnh hành động —2026-10-23

**Phản hồi mới nhất ưu tiên:** r063 đã sinh9PNG rồi dừng theo phản hồi người dùng.5ảnhFACE bị loại vì lệch danh tính, làm già và biểu cảm quá mức; người dùng chọn giữ **ACTION01–04**. Đọc `r063/batch-user-keep-actions01-04-v002.json` và QA gắn hash từng ảnh. Giữ4ứng viên này, không chạy lại; chưa phải nghiệm thu mọi chi tiết đồng phục. Không tiếp tục nhánhFACEfreshnoise/denoise1 chỉ vì môi đã đổi được. Tăngtexture/đổiexpression không được đánh đổi tuổi và nét mặt mẫu.

Snapshot chuẩn bị/chạy dưới đây giữ để truy vết, không phải lệnh tiếp tục batch.

Người dùng yêu cầu phân tích nguồn Z-Image/Rumble rồi chạy lại20ảnh. Audit và graph thật63nodes/72links nằm ở [báo cáo nguồn](../../../../docs/research/comfyui-acceleration-bilibili-20261023/REPORT.md). Chưa có transcript đầy đủ. Firecrawl CLI thiếucredit; AgentReach thiếuproviderkeys; browser MCP đọc được mô tả, nguồn và tải JSON.

Pack: `production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/production-v2-45s`.

- `local-image-e2e/r061`:20graph đã chuẩn bị;4job đã sinh, dừng gửi tiếp khi neutral01 vẫn cười. Không tiếp tục recipe này. Toàn bộ nguồn/receipt/PNG giữ nguyên; báo cáoFAIL gắn hash.
- `r062`: một neutral thử khởi tạo noise mới,8steps, ba tham chiếu thực. Môi khép đúng, texture tự nhiên hơn; crop còn rộng và thiếu xác minh logo cổ, nên chưa productionPASS.
- `r063/manifest.json`:20job riêng, xen kẽ face01/action01…face10/action10,1536×2048. Portrait dùng fresh-noise/denoise1 và nguồn mặt riêng0.4MP, body context0.08MP. Action dùng crop người đầu tiên→pad hai bên giữ tỷ lệ→initHD,denoise0.85,bodyref0.5MP. Đây là batch thử theo yêu cầu người dùng; kiểm ảnh thực, không tự gọi đủ20PASS.

Đọc `r063/batch-state.json`, từng `dispatch-receipt.json`, `/queue` và hash trước mọi thao tác. Bộ chạy hiện hành `run_char08_batch20.py` giữ lock, chạy tuần tự, bỏ qua output đã kiểm, dừng lỗi kỹ thuật, không tự gửi lại receipt mơ hồ. `batch-run.log` lưu tiến trình. Không khởi chạy một bộ chạy thứhai.

Mỗi collect tự publish8workflow và POST/GEThash8188. Extension chỉ tự thay các ô kết quả; giữ prompt và bố cục người dùng. Nhánh đang chọn không tự đổi theo mỗi job; graph/API/GUI riêng của mỗi tác vụ nằm trong lịch sử workflow. Nạp đầy đủ khi cần đổi nhánh thực thi. Chỉ kiểm API chưa đủ: đã thấy ảnh r061 tự đổi trên đúng Chrome8188 mà không refresh.

Thiếu route face-swap/RMBG/áp dụng đồng phục đã nghiệm thu; không đặt tên reference-conditioned generation là face-swap. LoRA screenshot thuộc ZImageTurbo không lắp vào FLUX2. CK có sẵn nhưng chưa bật/benchmark. SeedVR2 7B đã có, không tải lại; không chạy4K trước QA và không chạy video.
