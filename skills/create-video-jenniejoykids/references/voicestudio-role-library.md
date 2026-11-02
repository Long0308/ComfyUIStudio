# VoiceStudio, thư viện vai và các phép thử thực — 2026-10-18

## Hệ đang chạy

| Thành phần | Địa chỉ | Vai trò |
| --- | --- | --- |
| JennieJoy Studio | http://127.0.0.1:5050 | 5 bước sản xuất, state/manifest theo tập |
| Thư viện giọng | http://127.0.0.1:5050/voice-library.html | Lọc vai/ngôn ngữ; nghe reference, clone cùng câu và câu phim |
| VoiceStudio v0.5.6 | http://127.0.0.1:8080 | Profile clone và TTS thật |
| ComfyUI | http://127.0.0.1:8188 | H3, SeedVR2 và graph hậu kỳ |

Máy đã đo: RTX5080,16303MiB. VoiceStudio dùng Torch2.8.0+cu128; ComfyUI
dùng Torch2.14.1+cu130/sm120. Không cài lại môi trường vì đổi card.
Launcher đã có: `production-local/Start-JennieJoyStudio.ps1`.
Các đường dẫn tương đối dưới đây tính từ `J:/1.JennieHomeSchool/03 Voice`.

## Nguồn và profile

Nguồn chỉ đọc: `J:/1.JennieHomeSchool/JennieJoyKids-KhoaHoc-Classmagic`.
Thư viện/provenance: `production-local/voice-library-classmagic-20261018`.
Danh mục chính: `clone-catalog.json`; bằng chứng cuối:
`verification-summary.json`, `independent-review.json`, `coverage-summary.json`.

Đã kiểm kê7916media/3963hash. Đã tạo23profile mới:8ID được metadata ghi rõ,
13nhóm kể chuyện và2nhóm từ vựng/ngữ pháp chưa xác nhận người nói độc lập.
Sáu alias Alice tái sử dụng là các biến thể cũ, không phải sáu giọng nguồn mới.
VoiceStudio có33profile; gallery có30mục=23mới+6alias+Alice gốc.
Không coi số tệp/hash/profile/nhóm âm học là số người nói.

| Vai ứng viên | Profile thật | ID nguồn |
| --- | --- | --- |
| Ba | 1ae57068 | English_Gentle-voiced_man |
| Mẹ Graceful | 767cedad | English_Graceful_Lady |
| Mẹ Jenny | 5159d6e5 | en-US-JennyNeural |
| Mẹ Emma | 292408a4 | bf_emma |
| Mẹ Bella | ece858dd | af_bella |
| Trẻ em Sweet Girl | 9023c263 | Sweet_Girl |
| Alice gốc | 8f1145d7 | Profile đã lưu, giữ nguyên |

Đây là gợi ý vai từ nguồn/tên model, chưa phải nghiệm thu nghe. Chilli/Nana/
Bluey/Bingo cùng dùngSweet_Girl; Bandit dùngGentle-man trong60bài.
Không tạo bản clone trùng chỉ vì nhân vật khác tên. Tên profile/API gốc giữ nguyên;
nhãn vai của gallery không thay cấu hình phim. Thư viện có Ba không thay cast
Mẹ–Alice của tập Sữa; thêm vai vào một tập cần yêu cầu kịch bản tương ứng.

**Tên và ưu tiên được người dùng xác nhận trong phiên:** Mai=Graceful767cedad,
giọng Mẹ ưu tiên1; Linh=Bellaece858dd,giọng Mẹ ưu tiên2; Hà=Emma292408a4 và
Ngọc=Jenny5159d6e5 dành cho các nhân vật khác. `voice-names.json` là registry
hiện hành, `naming-v1/rename-receipt.json` chứng minh đổi tên đúng4profile mới,
giữ nguyên ID/reference/transcript/33profile và các profile khác. Không tái tạo
clone vì đổi tên. Có4file nghe đặt tên riêng tại `auditions/named-roles-v1`.
Đã chuẩn bị5câu thoại Mẹ với Mai tại `auditions/selected-mother-mai-v1`;
ASR cả5khớp chữ,0clipping,vừa5s không time-stretch. Đây chưa phải bằng chứng
nhép miệng/acceptance của Master mới.

## Luồng thêm giọng

1. Kiểm kê source/hash, bỏ bản sao, đối chiếu structured metadata/provider/role.
2. Chọn câu hoàn chỉnh3–12s; giữ source/hash/start/end/text; tránh ghép người nói.
3. Đo độ dài, clipping, âm lượng và tín hiệu có giọng. Cờ kỹ thuật không thay nghe.
4. Trích embedding và nhóm tương tự để tìm nguồn còn thiếu; kiểm các ngưỡng,
   lấy nhiều ví dụ cho mỗi nhóm. Không gán danh tính người hoặc tự đếm speaker.
5. Đối chiếu ASR đúng reference. Nếu VAD bỏ đầu câu, kiểm lại chính WAV với
   VAD tắt trước khi kết luận thiếu chữ hoặc tạo lại giọng.
6. Lưu reference/profile qua `/profiles` với `ref_text` rõ. Ghi dispatch intent
   trước POST; reconcile tên/hash/text sau kết quả không rõ, không gửi lại mù.
7. Đọc lại byte audio và transcript trên server; thử cùng câu và câu phim.
8. So nghe rõ chữ/thoải mái/nhịp, chọn WAV cuối rồi sửa nhép/caption theo đúng WAV.

Luồng khám phá thực nằm ở `discovery-v1/discover.py`: queue, extraction,
quality-results, model/runtime provenance, nearest-neighbors và provisional
acoustic groups. Lượt đầu đã chạy128đoạn, không phải toàn bộ kho đã được phân
tách speaker. CAMPPlus/CPU phục vụ gom tương tự; các nhóm còn cần kiểm và ASR.
Xem `discovery-v1/run-summary.json` để biết trạng thái cuối thay vì sao chép số cũ.

## Mẫu thử và số đo

`auditions/common-en-v1`:30profile cùng câu,Omnivoice/seed5080.
`auditions/movie-lines-v1`:7mẫu đúng thoại phim cho Ba/Mẹ/Alice/SweetGirl.
Giữ native24k mono và preview48k stereo cân gain, không đổi pitch/tốc độ.
`auditions/quality-metrics.json`:37mẫu,0sample clipping.
`level-matched-validation.json`:37preview đạt headroom/clipping.
`asr-quality.json`:36/37khớp chữ ở lượt VAD; riêng Alice được kiểm lại đúng
WAV khôngVAD, khôi phục đủ“Yummy milk! Thank you, Mommy!” tại
`alice-movie-vad-recheck.json`. Không dùng prompt/hotword để ép kết quả.

Cùng câu Mẹ S01_A, từ cuối:Graceful4.18s/129từ-phút,Bella4.12s/131,
Emma3.98s/136,Jenny2.72s/199. `duration=4.6` là yêu cầu cho model, không bảo
đảm độ dài lời thực. Đo timestamp và khoảng lặng, không chỉ xem thời lượng file.
ASR/LUFS không chứng nhận chất giọng chuyên nghiệp hoặc khớp phoneme.

Gallery build: `build_voice_gallery.py` xuất staticHTML/JSON và WAV được kiểm
hash vào `production-local/studio-app`. Bước3 có liên kết thư viện và dropdown
theo nhóm vai, giữ profileID/binding thật. Không regenerate khi mở trang.
Đã có incident cũ: Codex in-app browser crash khi bấm WAV; Chrome từng phát
được chính các WAV. Nếu gặp lại, kiểm host/Chrome và ghi giới hạn, không kết luận
nguồn WAV hỏng chỉ từ lỗi trình duyệt tích hợp.

## Nhép miệng, nâng nét và xuất bản

H3 sinh chuyển động; SeedVR2 là phục hồi/nâng nét, không sửa đúng nhép chỉ từ sub.
Baseline đã lưu làH3→SeedVR2→Master; ứng viên có thay voice phải đặt sửa nhép
theo WAV cuối trước nâng nét. Caption dùng timestamp đúng hashWAV; giữ pause.

SeedVR2 3B: cùng24frame,tile1024,78.534s; tile512 là131.573s.
SeedVR2 7B INT8: đã chạy đúng24frame/cùngseed/tile,87.902s,đỉnh tổngGPU quan
sát15103MiB. Đây là tổng gồm app khác, không phải allocation riêng model.
Workflow/hash/history/telemetry nằm tại
`docs/handoffs/model-comparison-20261018/seedvr2-7b-int8-24f`.
Không suy luận7B tốt hơn từ kích thước; phải kiểm mặt/tóc/mắt/temporal.

RealESRGANx4plus cũng đã chạy cùng24frame:32.765s,đỉnh tổngGPU12856MiB.
`model-comparison.json`/`.csv` lưu cả3model và provenance. Hai reviewer mù độc
lập chỉ xem5frame mẫu cho Mẹ/Alice, không biết tên/model/tốc độ/ý thích người
dùng: cảhai xếp7B>3B>RealESRGAN,7B và3B sát nhau. 7B mềm hơn và giữ biểu cảm;
3B rõ texture nhưng có chỗ gắt/lấm tấm; RealESRGAN phẳng hơn. Kết luận chỉ áp
dụng ảnh mẫu1s, không chứng nhận chuyển động/toànphim. Người dùng nghiêng về3B
trên ảnh tĩnh đã gửi; chưa coi đó là nghiệm thu toàn bộ phim.

MuseTalk1.5 đã chạyS01_A120frame/5s trong55.269s,peakCUDAallocated khoảng2.30GiB.
Filelossless không đổi bất kỳ channel pixel nào ngoài vùng miệng được mask;
toàn bộ15input/model/provenance giữ nguyên. Modelcore chính thức nhưng ROI/LK/
mask/fps là biến thể thử nghiệm. Contact cho thấy vùng miệng mềm hơn nguồn;
chưa được nghiệm thu hoặc đưa vào Master. Lab/receipt ở
`production-local/lipsync-lab-20261018/results/musetalk15-S01_A-seed1247`.

FlashVSR/Real-ESRGAN/LatentSync không được ghi đã test nếu chỉ mới đọc tài liệu
hoặc tải weight. Masterv004 vẫn giữ nguyên byte nhưng renderer/caption mới
làm digest hiện hành khác; Studio có thể báostale. Không sửa receipt thành pass
để che trạng thái; xuất phiên bản mới sau khi các lớp được chọn và kiểm.
