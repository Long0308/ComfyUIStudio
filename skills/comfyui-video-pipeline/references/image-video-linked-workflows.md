# Workflow ảnh–video NEWTECONS dùng chung

## Endpoint và phạm vi thực thi

Endpoint chuẩn duy nhất cho công việc mới là **http://127.0.0.1:8188**. Người dùng đã khởi động lại worker tại cổng này. Kiểm `/queue`, `/object_info` và model trước khi chạy. Không tự chuyển sang 8189 hay mở hai worker GPU. Receipt lịch sử giữ nguyên endpoint đã chạy thật; không sửa 8189 trong receipt cũ thành 8188. Đổi endpoint của việc mới không chứng minh server mới giữ history cũ.

Goal hiện hành là 160 ảnh, video H3/SeedVR2 còn dừng. Audit/cài dependency, sửa graph và lưu liên kết video được phép; không tự render lại video trong lúc làm ảnh.

Ảnh giao cuối tối thiểu 2K, mục tiêu 4K theo yêu cầu mới: ảnh dọc 3:4 tương ứng 1536×2048 hoặc 3072×4096; tỷ lệ khác giữ đúng bố cục, ghi kích thước pixel thật. Ảnh mặt trung gian 0.5–1 MP chỉ dùng kiểm thử biểu cảm, không ghi thành ảnh giao 2K/4K. Kiểm độ nét mặt, texture, chữ thêu từng ký tự và sọc phản quang trên bản cuối; tăng kích thước đơn thuần không chứng minh tăng chi tiết hay đạt chất lượng.

## Một dự án quản lý 8 CHAR × 20 ảnh

Pack: `production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/production-v2-45s/`.

- `master_image_workflow.py` và `local-image-e2e/master-workflow-v003/` quản lý một catalog đủ 160 task, nhóm 20 task cho mỗi CHAR. Đây là bộ điều phối dự án, không tự nhận một JSON catalog là vòng lặp native ComfyUI.
- Graph GUI/API đơn vị là template chỉnh sửa được; mỗi lần dispatch giữ snapshot tham số thực, seed, source/model hash, request và job ID. Chỉ gửi tuần tự một job GPU; không tạo 160 nhánh cùng chạy.
- `human-expression-performance-v002/manifest-160.json` chứa 160 prompt tiếng Anh với mô tả đầy đủ; `manifest-80.json` chứa 80 mô tả biểu cảm người thật. R044 đã có graph mới lấy từ bộ này, khác r043 cũ.
- Tên hiển thị node/group bằng tiếng Việt. Giữ nguyên `class_type`, tên socket, loại dữ liệu và chuỗi prompt tiếng Anh để bảo toàn khả năng chạy. Không thay tên class bằng bản dịch.
- Không coi technical success, có file PNG hay người dùng chọn mẫu tham chiếu là nghiệm thu sản phẩm. Lưu rõ lỗi, pending và candidate. Không đòi người dùng cho phép lại pilot/batch trong phạm vi goal đã giao.

## Tám workflow nhân vật và nạp qua API

Thư mục đích `ComfyUI/user/default/workflows/NEWTECONS_8_NHAN_VAT/` chứa tám JSON mang mã CHAR và tên đầy đủ từ cast; mỗi file quản lý 10 biểu cảm và 10 hành động. Giữ lịch sử job, graph thực gửi, prompt, seed, tham chiếu và hash trong `extra`; dùng node xem ảnh có đường dẫn thật cho kết quả đã tạo, ghi trạng thái chưa tạo cho ô thiếu. Ảnh thất bại vẫn giữ để đối chiếu nhưng phải có nhãn cần làm lại. Không biến trạng thái tạo file thành production PASS.

Người dùng yêu cầu nạp vào chính trang ComfyUI của họ: sau khi xuất JSON, dùng API hiện hành `POST /userdata/{URL-encoded-path}?overwrite=true` với body là byte JSON gốc, rồi `GET /userdata/{URL-encoded-path}` và đối chiếu SHA256. Đường dẫn là `workflows/NEWTECONS_8_NHAN_VAT/<tên>.json`. Xác nhận đủ tám file qua `GET /userdata?dir=workflows&recurse=true`. Giữ biên nhận publish và readback. Nạp workflow bằng API không khởi chạy GPU và không tự làm mới canvas đang mở. Sau publish, Refresh danh sách và mở đúng file ở trình duyệt người dùng đang dùng; không chỉ mở ở tab trình duyệt khác rồi tuyên bố họ đã thấy.

## Prompt có tác dụng phải đi vào graph thực thi

Ghi chú `MarkdownNote`/`Note` chỉ lưu mô tả; nội dung không trở thành điều kiện sinh ảnh. Nhãn ghi chú phải nói rõ chức năng này. Không gọi một canvas chỉ có ghi chú/ảnh xem trước là workflow sinh đủ 20 ảnh.

Với nhánh FLUX2: prompt tiếng Anh trong `CLIPTextEncode` phải nối qua `ReferenceLatent`/`CFGGuider` đến `SamplerCustomAdvanced`, rồi giải mã và lưu ảnh; ảnh danh tính phải được nạp và nối vào đúng nhánh conditioning. Kiểm reachability ở cả GUI links/backlinks và API graph thực gửi; một đường nối vẽ minh họa không chứng minh model đã nhận dữ liệu.

Với LivePortrait: ảnh nguồn và ảnh/khung biểu cảm driver điều khiển kết quả. Không có socket text-conditioning thì không nối giả ghi chú vào model. Khi người dùng yêu cầu sinh biểu cảm bằng mô tả, dùng nhánh tạo ảnh có bộ mã hóa text để tạo driver phù hợp, rồi nạp driver thật vào LivePortrait và lưu cả hai lần chạy. Mô tả đầy đủ vẫn lưu làm hợp đồng QA nhưng phải phân biệt với prompt được model tiêu thụ.

## Mô tả đầy đủ trong mọi ảnh và cảnh

Mỗi prompt lặp đủ tên/mã CHAR, vai trò kỹ sư hoặc lãnh đạo, tuổi, mặt, tóc/kính, màu da, vóc dáng/tỷ lệ, trang phục đúng bối cảnh, biểu cảm qua mắt–mày–má–miệng–hàm, tư thế, tay/đạo cụ, hành động, camera và ánh sáng. Mô tả người thật, không kế thừa tỷ lệ hoạt hình Alice. Học Alice ở cách phân loại/kiểm trạng thái biểu cảm riêng và icon riêng, không sao chép mặt hoặc phong cách trẻ em.

Nêu **tên file tham chiếu thực** và vai trò trong câu, ví dụ `CHAR_08_MASTER_FACE_LOCKED.png` cho danh tính, tên neutral portrait đúng revision cho nguồn sửa, tên áo gốc cho cấu trúc áo, tên ảnh văn phòng thật cho kiến trúc. Chỉ gọi là ảnh đính kèm/conditioning khi file thực sự được nạp trên nhánh graph chạy. Không chỉ ghi “Image 1”, “same character” hoặc tên người để thay toàn bộ mô tả. File chỉ dùng audit/QA thì ghi rõ vai trò đó. Nguồn trang phục/bối cảnh không cung cấp danh tính.

Lấy tên, vai trò và tuổi từ cast trong screenplay và source pixels; chữ bộ phận từ `vest-lettering-contract-v001.json`. CHAR02/05 dùng **SITE MANAGER**, không tự đổi sang CHỈ HUY TRƯỞNG. Không hardcode tên/tuổi tự nghĩ. Quy tắc sơ mi microgrid + logo cổ mới ưu tiên hơn mô tả cũ trong screenplay lịch sử.

## Sao lưu và nối nguồn ảnh sang video

Trước sửa graph, giữ bản gốc và SHA256. `local-image-e2e/workflow-backup-20261023-v001/manifest.json` giữ bản sao graph và hợp đồng ảnh–video; audit sửa lỗi riêng ở `docs/research/comfyui-github-20261023/local-repair/`. Không chép model/video nặng để giả có backup: giữ nguồn media thật, hash, receipt, và ghi rõ cái gì đã/ chưa sao lưu. Không ghi đè run/archive cũ.

Mỗi cảnh video phải trỏ về đúng ảnh CHAR/wardrobe đã kiểm cùng revision/hash/job. Khi đổi ảnh hoặc trang phục, đánh dấu mọi anchor/cảnh phụ thuộc cần kiểm lại. File `WF01...WF09` có tên đúng chưa chứng minh nội dung đúng; kiểm mọi LoadImage/LoadVideo, prompt, model, output prefix và subgraph. Graph trỏ Alice/animal/video phim khác phải sửa trước dùng NEWTECONS.

## Frame cuối cảnh trước → frame đầu cảnh kế

Theo yêu cầu người dùng, mỗi liên kết cảnh liên tục dùng **frame cuối thực sự được dùng trong timeline** của cảnh N làm ảnh đầu vào và frame0 của cảnh N+1. Ví dụ 120 frame dùng thì lấy chỉ số119, 144 frame thì143. Trích lossless theo chỉ số frame ở kích thước native; không dùng thumbnail hoặc seek gần đúng. Trước khi render cảnh kế, bind path/hash ảnh carry với clip nguồn/hash, FPS và số frame đã dùng.

Graph cảnh kế phải nạp ảnh carry thật và giữ nó làm frame0; kiểm pixel/frame hash rồi xem chuyển động tiếp sau và đường nối AV. Seed giống nhau hay prompt “giữ mặt” không thay liên kết frame thực. Carry là nguồn trạng thái/bố cục trước đó; các nhân vật mới xuất hiện vẫn cần master riêng và mô tả đầy đủ, không lấy mặt người cảnh trước thay mặt người cảnh sau. Chuyển cảnh/đổi diễn viên phải được ghi trong hướng diễn xuất và kế hoạch nối, không âm thầm bỏ carry hoặc ghi PASS từ file kế hoạch.

`local-image-e2e/image-video-links-v001.json` lưu trạng thái liên kết dự kiến. Khi chưa có video mới, path/hash frame thật vẫn null và trạng thái WAITING_ACTUAL_VIDEO_FRAME; không đánh dấu continuity đạt. Đọc thêm [kiểm cảnh liên tục](../../create-video-jenniejoykids/references/continuous-shots.md) và [prompt transport](../../create-video-jenniejoykids/references/comfy-prompt-transport.md).

## Nghiên cứu và sửa dependency

Đọc [audit GitHub của Astra](github-image-workflows-20261023.md) khi chọn node/recipe. Phân biệt local thật, wrapper API/cloud, schema đủ và inference đã kiểm. Cài đúng model theo upstream pin/hash, giữ tỷ lệ ảnh tham chiếu, xác minh node thực đã nạp; model có trên đĩa không chứng minh worker đã reload node. Kiểm pilot ảnh cuối trước batch và trước gắn vào video.
