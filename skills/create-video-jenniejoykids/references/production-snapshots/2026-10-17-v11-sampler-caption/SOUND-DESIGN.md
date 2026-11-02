# JennieKidJoys — kế hoạch âm thanh phim 60 giây

Đây là kế hoạch hậu kỳ, chưa phải bản mix đã duyệt nghe. Tài liệu từng cảnh nằm
ở `scenes/scene-01` đến `scene-06`, mỗi thư mục có `SCENE.md/JSON` và
`SOUND-PLAN.md/JSON`. Kế hoạch hiện tại dùng production-request-v9.json và canonical Alice v2;
render Scene 1 v9 dùng nguồn v8 đã khóa; B còn lỗi chớp sáng cần kiểm tra trước khi đo cue cuối cùng.

| Cảnh | Hành động, âm thanh và khoảng nghỉ |
| --- | --- |
| Scene1,0–10s | Bé cùng ba mẹ bước thẳng vào cổng đang mở. Lớp không gian nhẹ, lá và chim xa; bước giày theo từng tiếp đất. Nhạc gảy/marimba vui nhẹ. Lời Alice được đặt riêng; đầu phim có JennieKidJoys / Let's Go to the Zoo! |
| Scene2,10–20s | Bé chỉ chim trên cây và nói tiếng Anh đơn giản với mẹ; ba mẹ nhìn theo, gật đầu. Một chirp ngắn gắn với mỏ/chuyển động chim; lá nhẹ, bước chân giảm khi dừng. Giữ khoảng cho bé đọc theo. |
| Scene3,20–30s | Bé nhìn và chỉ hươu cao cổ; cử động cổ/lá và tiếng chân tự nhiên nếu hình có. Không tự thêm tiếng gầm sai loài; không gian thoáng và nhạc vẫn nhẹ. |
| Scene4,30–40s | Hổ chớp mắt, thở và cử động nhẹ; một tiếng chuff/gừ rừ rất ngắn trong khoảng không có lời. Chân hổ/cỏ chỉ có âm nếu thấy tiếp xúc. Không dùng tiếng gầm đột ngột. |
| Scene5,40–50s | Gấu trúc nhai tre; mẹ mở bình và đỡ bé uống, ba đưa một miếng chuối nhỏ. Bé nói xong mới uống/ăn. Chỉ dùng lá tre, nắp bình, một tiếng nhấp nước hoặc tiếp xúc nhẹ; tránh tiếng nhai/phụ âm bị lẫn. |
| Scene6,50–60s | Bé nuốt xong trước lời tiếp; cả nhà tiếp tục đi và chào tạm biệt. Tiếng bước chân/áo/lá chuyển tiếp liên tục; nhạc kết nhẹ và đủ thời gian đọc phụ đề. |

Sáu stem chỉnh riêng: giọng Alice, nhạc, không gian, bước chân, con vật, đồ vật.
Giọng lấy từ profile Alice đã lưu; 12 waveform gốc giữ nguyên. Ba mẹ hiện phản
ứng bằng nét mặt/cử chỉ; thêm lời của ba mẹ cần profile riêng đã duyệt.

Lịch ăn uống dự kiến: Scene5A lời1.00–2.99s, nhấp nước3.25–4.35s;
Scene5B lời0.35–3.29s, miếng chuối3.55–3.95s. Lời tiếp ở master51.00s;
còn2.05s sau khi cắn, nhưng vẫn phải xem hình xác nhận miệng đã sẵn sàng.
Canonical v2 đã được kiểm tra PCM độc lập, không kéo giãn hay thay timbre.

Sau khi hình đạt: xem2ảnh/giây và các frame liên tiếp quanh bước chân, mỏ,
chân hổ, tre, nắp bình, nhấp nước và miếng ăn. Ghi sourcePTS, frame local,
frame master và điểm transient thật của WAV. Không biến các mốc dự kiến thành
số đo. Mỗi khoảng nghỉ tối đa một điểm nhấn nhỏ; dành phần còn lại cho đọc theo.

Phối âm ưu tiên phụ âm đầu/cuối, không nhạc có lời hoặc tiếng khách nói rõ;
nhạc giảm mềm dưới lời. Đo loudness/truepeak và nghe tốc độ thường, tai nghe
và loa nhỏ.17 nguồn hiện có là Foley tổng hợp gốc, không phải bản thu động vật
thật; giữ thông tin nguồn và hash. Bản mix-v1 cũ chưa đúng lịch Scene5 mới.
Phụ đề tiếng Anh được thêm ở Remotion/Hyperframes sau hình, không để model
tự vẽ chữ. Bản nháp720p chờ duyệt trước1080p.

Kiểm tra mốc 11: cả sáu SOUND-PLAN đã trỏ đến script v9 SHA256 3dd21650d1a9c3ab247a2aaf1748672c38d80619aa7676ed4aadecbef7ccb643. Đủ sáu stem và hành động nói/ăn/uống; không cần thêm cue giả để lấp mọi khoảng nghỉ. Bed preview v2 60s chưa có event cues, chưa duyệt nghe. Bản nhạc unducked mới đã được kiểm tra PCM; khi chọn nguồn phải ghi đúng phiên bản và đo lại ducking, không áp chồng envelope từ bản nhạc cũ.
