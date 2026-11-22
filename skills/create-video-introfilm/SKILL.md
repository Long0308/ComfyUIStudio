---
name: "create-video-introfilm"
description: "Dựng video intro / trailer sự kiện 60–120 giây (HTML + GSAP + ffmpeg): kịch bản, lời đọc và sub, tin tức có nguồn, số liệu từng đề tài, nhạc theo phách, nhận giọng ghép nhanh, storyboard và sửa nhanh sub / giọng."
---

# Video intro / trailer sự kiện (kiểu phim bom tấn)

Dùng khi người dùng cần một video mở màn cho workshop, lễ ra mắt, hội nghị: nhịp nhanh, chữ lớn, số liệu nổi, có nhạc + SFX, có lời đọc và phụ đề làm song song ở nơi khác. Sản phẩm: mp4 1080p có phụ đề và không phụ đề, gói kịch bản + lời đọc + sub, bảng kiểm chứng nguồn tin.

## Nguyên tắc đã chốt với người dùng

- **Gửi gói sub + lời đọc TRƯỚC**, rồi mới làm hình. Người ở nhà làm giọng song song nên dòng thời gian phải khoá trước khi gửi.
- **Chữ phải kịp đọc.** Không kéo giãn đều cả video (lệch phách nhạc, mất chất trailer). Giữ hình đúng chỗ cần đọc: tên đề tài + người thực hiện 3 s, con số hiệu quả 3 s, bảng tên lãnh đạo 5–6 s, bảng giờ – địa điểm 4 s.
- **Mỗi đề tài đủ 4 ý, nối nhau:** (1) cách làm cũ / khó khăn gì → (2) tên đề tài, ai thực hiện → (3) cách làm mới giải quyết gì → (4) hiệu quả, có số. Nhịp 1 gắn nhãn đỏ "CÁCH LÀM CŨ", chữ và số của cách cũ màu đỏ, to, đập xuống từng cái (ví dụ 3 người · 5 ngày · 1 báo cáo / tuần; "TỐN 1 người chuyên nhập liệu"); nhịp 3 gắn nhãn "CÁCH LÀM MỚI"; nhịp 4 đối chiếu số cũ đỏ bị gạch → mũi tên → số mới vàng thật to. Lời đọc phải đọc tên đề tài và người thực hiện. Mỗi đề tài dùng từ nối và động từ khác nhau để không trùng.
- **Không viết tắt** trên hình và trong lời (viết đủ "biên bản giao hàng", "đơn đặt hàng", "chạy thử – nghiệm thu", "Ban chỉ huy"). Tên đề tài chính thức có chữ tắt thì viết đủ, để chữ tắt trong ngoặc. Giữ: AI, CAD, PDF, tên sản phẩm.
- **Đề tài nào cũng có số** ở nhịp hiệu quả. Không bịa số; thiếu số đo thì dùng số đếm có thật (1 nguồn, 1 thao tác, 5 bước) và báo người dùng.
- **Lãnh đạo:** chức danh và họ tên do người dùng cung cấp, hiện thành bảng tên riêng; lời đọc chậm, ngắt trước tên, đọc tên rõ và dứt khoát. Không để hiệu ứng nào che mặt. Ảnh chân dung: giữ nền gốc của ảnh, cắt trong một vòng tròn neon, nền làm mờ và tối bớt nhưng vẫn thấy; người tách nền nét nổi lên trên, đầu nhô khỏi vòng. Xuất hiện đúng lúc đèn rọi chụm lại (vòng khoá vào → nền mở kiểu màn trập tròn + loé sáng → người trồi lên, nét dần), sau đó logo các đơn vị mới bay vào lượn quanh. Sóng và tia lửa toả ra từ vành vòng, không quét qua gương mặt; vòng vàng chỉ được loé nhanh khoảng 0,4 giây.
- **Chuyển cảnh không đột ngột:** trước đoạn tin tức có quả cầu thế giới trồi lên + chữ "AI NEWS · BẢN TIN TRONG VÀ NGOÀI NƯỚC" + một câu dẫn.
- **Số thứ tự và tên đề tài phải nổi:** số là khối kim loại chrome đặc (không dùng nét rỗng), có ánh kim quét từ trái sang phải qua số rồi tới tên.
- **Nhiều sản phẩm trong một đề tài:** từng sản phẩm hiện toàn màn hình, tiêu đề số (1, 2, 3…) bay ra, rồi thu gọn về ô của nó trong lưới, mỗi cái khoảng 1 giây; không cho cả lưới ô nhỏ chạy cùng lúc.
- **Khi ở nhà đang làm giọng / sub:** không đổi mốc bắt đầu của các câu. Sửa hình thì chia lại thời gian bên trong cảnh, giữ nguyên ranh giới cảnh và tổng thời lượng; đối chiếu tệp sub đã gửi với phụ đề trong video trước khi trả lời là "khớp".
- **Kịch bản, giọng và video phải cùng một mã bản** (ví dụ v8c). **Bàn giao của bên làm giọng** (ghi rõ trong README của gói, để nhận về là chép vào chạy, không cắt ghép): (1) mỗi câu một tệp `Lxx.wav`, giây 0 của tệp là giây bắt đầu của câu, các mẩu trong câu đã đặt đúng khoảng lặng bên trong tệp — nhịp ngắt nằm sẵn trong tệp; (2) một tệp `.srt` canh theo giọng, đủ số mẩu, giữ nguyên chữ, chỉ đổi giờ; (3) ghi chú: làm theo gói bản nào, chữ nào máy nghe lại sai, mẩu nào phải đọc nhanh hơn tự nhiên. Nhận gói giọng thì đọc ghi chú xem nó làm theo bản nào trước khi ghép, và chuyển danh sách chữ cần người nghe lại cho người dùng.
- **Con số hook do người dùng cung cấp** (ví dụ "4–5 ngày vẽ → 1–2 ngày") đặt làm số chính của nhịp hiệu quả; các số đang có liệt kê lại cho người dùng biết.
- Logo: chỉ dùng tệp người dùng cấp, không vẽ lại. Hình minh hoạ ghi "minh hoạ"; quay màn hình thật ghi "màn hình thật", cắt bỏ cột danh sách và tên tài khoản.
- Luôn nói rõ Claude không nghe được âm thanh; nhạc chỉ kiểm bằng số đo.

## Quy trình

1. **Thu thập:** tên sự kiện, ngày giờ, địa điểm; thứ tự nội dung; chức danh + họ tên người cần nêu; danh sách đề tài (tên chính thức, người trình bày, dự án, khó khăn, giải pháp, số hiệu quả); logo, ảnh, clip thật; ảnh chụp tin bài nếu có.
2. **Khoá dòng thời gian** trên lưới phách (nhạc 120 BPM: cú mạnh mỗi 2 s, mọi mốc cảnh đặt ở giây chẵn). Khung mẫu ~86 s: đèn rọi 0–1,5 · bảng tên lãnh đạo 1,5–8 · ra mắt 8–12 · tin tức 12–20 · tên sự kiện 20–24 · câu móc "N đề tài thực tế" 24–26 · mỗi đề tài 10 s (2 + 3 + 2 + 3), đề tài chốt 12 s · phần 2: 2 s · neon giờ – địa điểm 4 s · kết 2,5 s. Khi mỗi đề tài phải nói rõ cách cũ – cách mới – số liệu thì dùng khung ~122 s: mỗi đề tài 16 s chạy 1× (4 cách cũ + 3 tên + 5 cách mới + 4 hiệu quả), đề tài chốt 24 s (4 + 5 + 8 + 7); đầu mỗi đề tài, nhịp tên và nhịp hiệu quả rơi vào lưới 4 s của nhạc.
3. **Viết lời đọc:** đếm âm tiết, tính 4,2–4,6 âm tiết/giây + 0,2 s mỗi chỗ ngắt (đã có tệp giọng của bản trước thì đo tốc độ thật: số âm tiết / độ dài tệp). Nội dung người dùng đưa dài hơn cửa sổ: lời đọc rút gọn, hình hiện đủ ý, và nói rõ với người dùng chỗ đã rút; mỗi câu phải ngắn hơn cửa sổ của nó. Câu quá dài thì cắt chữ, không tăng tốc.
4. **Đóng gói gửi ngay:** `voice_lines.json` (mã, giây bắt đầu, dài tối đa, phụ đề, câu đọc phiên âm, các mẩu sub), tệp txt `Mã|Câu đọc`, tệp `.srt`, bản kịch bản `.md` có bảng 4 ý từng đề tài, `README.md` kèm prompt mẫu, script kiểm độ dài. Ghi rõ câu nào dùng lại được tệp giọng cũ. Người dùng sửa lời sau khi gói đã gửi: gửi NGAY gói mới có hậu tố (v8 → v8b → v8c), trước cả khi sửa hình; dòng đầu ghi CHỈ mẩu nào đổi, giây bắt đầu và lời mới, để ở nhà chỉ đọc lại đúng mẩu đó. Phụ đề trong video và tệp sub trong gói phải lấy từ cùng một nguồn; so hai bên trước khi gửi.
5. **Dựng hình** (mục Kỹ thuật), **nhạc + SFX** (mục Âm thanh) chạy song song.
6. **Soát bằng khung hình** trước khi render: mỗi cảnh ở lúc nhiều chữ nhất và cuối mỗi khoảng giữ.
7. **Render từng cảnh → ghép → soát lại → gửi.** Gửi bản xem trước sớm; giữ bản trước làm dự phòng. Hình chốt là dựng ngay bản hình gốc (master) và viết sẵn lệnh nhận giọng; không ngồi chờ giọng rồi mới làm.

## Kỹ thuật dựng

- **Màu và kiểu chữ khai báo một chỗ, theo vai trò**, để sau này đổi không kéo theo cả video: biến CSS cho màu (cách cũ = đỏ, cách mới / nền = xanh cyan, hiệu quả và số nhấn = vàng, đạt = xanh lá) và lớp chữ dùng chung (chữ tiêu đề, chữ thân, chữ máy; lớp chữ gradient đỏ / xanh / vàng; lớp số lớn). Mã cảnh chỉ gọi lớp và biến, không gõ mã màu hex hay font riêng lẻ. Đổi cả tông (màu chủ đạo, font) thì sửa biến / lớp rồi render lại toàn bộ; đổi màu một con số thì đổi lớp của đúng phần tử đó (ví dụ "2.000 thiết bị" sang vàng, "376.000 m² sàn" giữ xanh) và chỉ render lại đoạn chứa nó.
- Một trang HTML 1920×1080, GSAP timeline `tl` đứng yên, hàm thuần `seek(T)`; Playwright chụp JPEG từng khung, ffmpeg nén **mỗi cảnh một mp4**, ghép `-c copy`. Sửa cảnh nào render lại cảnh đó.
- **Bảng ánh xạ thời gian** `TSEG = [[T0, T1, τ0, τ1], …]` (giây hiển thị → giây nội bộ). Chèn cảnh mới, đổi thứ tự, giữ hình đều làm ở đây, không sửa mốc trong từng cảnh. Lưu thành tệp json dùng chung cho luồng âm thanh.
- **Giữ hình:** trong một nhịp, chạy 1× cho tới khi mọi thứ vào xong, rồi cho τ gần đứng yên, cuối nhịp chạy 1× cho phần ra. Chuyển động vào phải xong trước khoảng giữ; chuyển động ra không bắt đầu trong khoảng giữ; không để tia lửa, vòng sóng đang bay rơi vào khoảng giữ.
- Phần dài chạy 1× thêm vào sau (ví dụ 5 đề tài, 88 s) thì đặt ở một dải τ mới, xa các cảnh cũ (τ 100–188), không nhồi vào dải cũ bằng khoảng giữ. Cảnh đứng ngay trước dải đó trong τ phải trả tham số nền về mặc định; ranh giới tệp cảnh đặt ở mọi chỗ τ nhảy lùi, mỗi tệp render từ một trang mới.
- **Sửa nhỏ sau khi đã ra video:** chỉ render lại đúng đoạn đổi (thêm 1 giây đệm hai đầu), cắt lại tệp cảnh cũ ở hai bên đoạn đó, ghép lại. Hiệu ứng mới đặt vào nhịp có sẵn, giữ cú chính trùng cú mạnh của nhạc; đổi mốc thì cập nhật mốc SFX và phối lại. Cảnh không đổi so với bản trước thì dùng lại tệp cảnh cũ.
- Cần hoạt cảnh riêng trong đoạn τ chạy chậm (bảng tên): viết mốc theo giây hiển thị rồi chia cho hệ số chậm; cú đánh (rung, chớp) thêm hệ số `rate` để tắt đúng nhịp.
- Lớp nền phải "sống" khi giữ hình (sao, tinh vân, sao băng, hạt nhiễu) thì chạy theo giây hiển thị, không theo τ.
- Hậu kỳ trong ffmpeg, không trong trình duyệt: tách màu RGB theo bảng cú đánh, "bơm" hình theo phách ở đoạn cao trào, dải phụ đề là ảnh PNG chồng lên. Đổi sub không phải render lại hình.
- **Bản hình gốc (master):** ghép cảnh + tách màu + bơm thành một tệp hình chưa tiếng, chưa phụ đề, kèm chữ ký (danh sách tệp cảnh với kích thước và giờ sửa + bảng cú đánh); chữ ký không đổi thì dùng lại. Từ master: bản không phụ đề chỉ ghép tiếng với `-c:v copy` (vài giây), bản có phụ đề nén đúng 1 lần. Đổi tiếng hoặc đổi giờ sub không nén lại hình hai lần (trước đây mất ~9 phút, nay ~4 phút).

## Hiệu ứng đã dùng và được duyệt

Đèn rọi quét tìm rồi bật sáng · chân dung trong vòng tròn neon (nền gốc làm mờ, người nổi ra ngoài vòng) · nền vũ trụ · logo các đơn vị bay quanh rồi hợp lực · bảng tên lower-third có vệt sáng · quả cầu chấm (bản đồ Natural Earth) xoay tới từng nước, có mốc phát sáng · mẩu báo giấy xé đập ra màn hình, phóng từ chữ khoá, bút dạ quang · dấu mộc tên nước · ảnh tròn dán cạnh thẻ tin nóng · chữ ráp từ bi / thẻ · số chrome + ánh kim quét · chữ làm mặt nạ lộ sản phẩm thật · chớp đèn máy ảnh · dải bước có khung ảnh thật · lưới ô sản phẩm · bảng các Agent + chip "Agent 1…5" · số cũ đỏ bị gạch → số mới vàng · "nhanh gấp N lần": chữ lao vào kiểu tốc độ, vệt sáng vụt qua, số đếm, N vạch tăng tốc · tờ giấy rơi sau chữ "bằng giấy" · huy hiệu thiết bị kiểu blueprint (ảnh sản phẩm người dùng gửi → tách nền, giữ khối bằng sắc độ xanh, nét cạnh sáng, lưới ô, cắt tròn, ghi "minh hoạ", tên đầy đủ kèm chữ tắt trong ngoặc) xoay trên quỹ đạo elip quanh con số, rồi thu nhỏ về cạnh con số · bảng neon đổi màu · khung chat gõ lệnh → ENTER → ráp thành logo → cửa mở, lao vào.

## Đoạn tin tức

- Mỗi mẩu ghi **nguồn và ngày đăng** ngay trên thẻ. Ảnh chụp bài báo người dùng gửi phải nhìn ra là ảnh chụp thật: thẻ nền trắng kiểu trang web, có nhãn "ẢNH CHỤP", to hơn và khác hẳn thẻ giấy tự viết lại; không trộn màu ảnh vào nền giấy. Tít tự viết lại ngắn gọn; ảnh chụp do người dùng gửi thì chỉ cắt tít + dòng nguồn / ngày, bỏ nút chia sẻ và đoạn thân bài.
- Kiểm từng mẩu bằng tìm kiếm web trước khi đưa lên hình, kể cả tin người dùng gửi. Lập bảng kiểm chứng 3 mức: A đã thấy bài gốc · B sự kiện có nguồn khác xác nhận · C chỉ dựa tít / ảnh. Mức C phải báo người dùng.
- Tin về cá nhân: chỉ nêu sự kiện chính, không đưa chi tiết đời tư.
- Ảnh bảng logo của bên thứ ba: dùng nguyên trạng, gắn nhãn đúng sự kiện; chưa chắc thuộc sự kiện nào thì hỏi.

## Âm thanh

- Nhạc thư viện CC0, cắt ghép theo phách sao cho cú mạnh đầu phrase rơi vào các mốc cảnh; đẩy dần ở nửa sau, cú lớn nhất ở câu chốt, sau đó hạ.
- Bản dài ~2 phút: dùng các khúc liền mạch của bài (ít điểm nối); khoảng hụt 2 s thật của bài đặt vào nhịp "cách làm cũ" của đề tài giữa, trống vào ngay sau đó, nhịp đôi ở đề tài chốt, hạ một nấc trước bảng neon, cú lớn nhất ở câu chốt. Khi hình chốt, lấy danh sách cú đánh thật của từng đề tài đặt lại mốc SFX rồi phối lại.
- SFX gắn theo mốc hình; có khoảng "nín thở" 0,28 s trước các cú lớn. Đổi nhịp hình thì gửi lại danh sách mốc cho luồng âm thanh.
- Đỉnh WAV để khoảng −4,5 dBFS: nén AAC làm đỉnh đội thêm 3–4 dB.
- **Lời đọc về → một lệnh "nhận giọng"** (viết sẵn trong lúc chờ, nhận thư mục hoặc tệp zip): chép L01…Lnn vào thư mục giọng → đo độ dài từng câu so với cửa sổ, báo câu vượt và câu thiếu → đổi giờ phụ đề theo tệp `.srt` canh theo giọng (số mẩu phải bằng số mẩu trong video; lệch quá 2,5 s thì báo kiểm; chống chồng mẩu) → phối, hạ nhạc 6–8 dB khi có giọng → dải phụ đề → ghép từ master → chụp khung ở đầu mỗi mẩu phụ đề thành bảng để soát sub khớp hình → chép ra thư mục giao. Phối tiếng chạy song song với việc dựng master nếu master chưa xong. Mục tiêu: từ lúc nhận tệp tới lúc có video không quá 7 phút.

## Làm song song

Chỉ tách luồng khi người dùng yêu cầu. Luồng chính giữ lõi, mở màn, tin tức, kết; một luồng lo các cảnh đề tài; một luồng lo âm thanh. Dùng chung tệp SPEC và tệp ánh xạ thời gian; mỗi luồng chỉ sửa tệp của mình và có script chụp riêng. **Khoá dòng thời gian trước khi giao việc âm thanh** — mỗi lần đổi là một lần phối lại.

## Lỗi đã gặp, cần soát

- Chữ gradient cắt mất dấu tiếng Việt → thêm padding / margin âm. Dấu mộc nghiêng: dấu trên cùng chui dưới thanh đen → chừa padding trên.
- Tween filter từ `blur()` sang `brightness()` làm thẻ nháy đen → hai đầu tween phải cùng danh sách hàm.
- Chữ `background-clip:text` + `text-shadow` làm tối chữ → dùng `drop-shadow` trên phần tử cha.
- Cảnh phủ lên cảnh khác phải có `z-index` riêng, nếu không bị phần tử `z-index` cao của cảnh dưới đè.
- Chữ sát mép phải khung (cách dưới 40 px) → xuống dòng.
- Lệnh nền bị dừng sau khi trả lời → chờ render và ghép xong trong cùng lượt rồi mới trả lời.
- Không liệt kê thư mục có hàng nghìn tệp ảnh.
- Tên class tự đặt trùng class khung cảnh của trang (ví dụ `.sc`) làm phần tử bị ẩn → đặt tên riêng, kiểm bằng `getComputedStyle` khi thẻ không hiện.
- Chạy quá 2 tiến trình Chrome chụp khung cùng lúc làm trình duyệt sập giữa chừng → tối đa 2; đoạn lỗi thì chạy lại riêng và kiểm giờ sửa đổi của tệp mp4.
- Khi một luồng khác đang sửa tệp cảnh, render các cảnh không liên quan từ một bản sao trang trỏ tới tệp ổn định.
- Chụp thử nhảy lùi thời gian nội bộ có thể ra khung trống; kiểm cảnh đó bằng cách tua tiến từ đầu.
- Nhận tệp giọng: đo độ dài từng tệp so với cửa sổ, dùng tệp sub đã canh theo giọng để đổi giờ phụ đề, đọc ghi chú những chữ máy nghe lại sai (tên riêng, tên sản phẩm) và báo người dùng nghe lại.
- Luồng chạy nền bị dừng khi phiên khởi động lại, mất hết nếu chưa ghi gì → ghi brief của từng luồng ra tệp, yêu cầu luồng sửa tệp từng bước và ghi tiến độ vào tệp PROGRESS để luồng mới đọc và làm tiếp.
- Cảnh có chữ neon lớn nhiều lớp `text-shadow` chụp rất chậm (khoảng 5 giây một khung) → xếp cảnh đó chạy riêng, đừng để các cảnh khác phải chờ nó.
- Mã chèn thêm dùng hằng `const` khai báo ở phía dưới làm cả trang không dựng được → đặt sau dòng khai báo, chụp thử ngay sau khi sửa.
- Chèn chú thích `//` vào giữa một dòng có nhiều lệnh làm mất các lệnh phía sau (chữ biến mất mà không báo lỗi) → dùng `/* */`, và luôn xem khung hình của đúng chỗ vừa sửa trước khi ghép.
- Nối lệnh bằng `&&` sau một lệnh kiểm tra có thể trả mã lỗi (ví dụ `grep -c` ra 0) làm các bước sau không chạy → tách lệnh kiểm tra ra riêng.
- Chữ bay điểm lại từ khoá ở cảnh kết cũng phải soát chữ viết tắt và cập nhật theo số liệu mới.
- Người dùng thấy khung thử có hiệu ứng lạ (vòng sáng màu khác) có thể tưởng nó đứng lâu → nói rõ nó chỉ loé bao lâu, và giữ các hiệu ứng thoáng qua dưới nửa giây.
- Người dùng đưa đường dẫn trên máy của họ (`C:\…`) mà kết nối tới máy đang lỗi → nói ngay là không đọc được và xin đính kèm tệp zip vào chat; trong lúc chờ làm tiếp phần không cần tệp đó (dựng master, viết lệnh nhận giọng).
- Lệnh chờ dài chạy ở tiền cảnh có thể mất kết quả hoặc bị đẩy ra nền khi người dùng nhắn → việc nặng (phối, ghép, render) chạy nền bằng `nohup`, ghi mốc DONE vào tệp log, rồi thăm bằng các lệnh ngắn dưới 3 phút.
- Hai việc cùng ghi một tệp tạm (hai lần ghép chạy chồng nhau) làm hỏng tệp → xếp hàng: việc sau chờ mốc DONE của việc trước.

## Storyboard và sửa nhanh sub / giọng

### Luôn có storyboard
Lập `storyboard.json` (kèm bản `.md`) ngay khi khoá dòng thời gian, cập nhật mỗi lần đổi nhịp, đưa vào mọi gói kịch bản và giao kèm mỗi bản video.
- Mỗi dòng là một nhịp: mã cảnh, giây vào – giây ra, tệp cảnh đã render (`out/s_XXX.mp4`), mã câu giọng (Lxx) + tệp giọng, chữ từng mẩu phụ đề với giây của nó, cú nhạc / SFX, ghi chú.
- Bảng này là nguồn duy nhất: `voice_lines.json`, `caps.json`, tệp `.srt` trong gói và dải phụ đề trên video đều sinh từ nó, không gõ tay ở hai nơi.
- Giữ sẵn để cắt ghép: bản hình gốc không tiếng không phụ đề (master), từng câu giọng một tệp, nhạc và SFX riêng, dải phụ đề là lớp phủ riêng.
- Sau mỗi lần nhận giọng hoặc đổi nhịp, kiểm tự động: mỗi câu giọng xuất hiện đúng một lần (dò tương quan chéo trên track giọng, cửa sổ 1,2 s, hệ số ≥ 0,9 ở hai chỗ là lặp), không có hai câu chồng nhau, không câu nào cụt đuôi, số mẩu phụ đề và chữ khớp câu giọng cùng khoảng giây.

### Người dùng báo sai / trùng / dư sub hoặc giọng
1. Khoảng giây người dùng nói là gần đúng. Tra storyboard, liệt kê các mẩu phụ đề và các câu giọng trong khoảng đó; "trùng" có thể là giọng lặp nên phải đo, vì Claude không nghe được.
2. Chọn đơn vị nhỏ nhất đúng với lỗi được tả. Khoảng đó có từ hai câu trở lên mà dữ liệu không chỉ ra câu nào lỗi thì hỏi một câu kèm chữ và giây của từng câu. Không đoán rồi cắt cả hai.
3. Trước khi dựng, nhắn một dòng: bỏ hoặc sửa đúng câu nào, giữ câu nào.
4. Đường sửa nhanh, không render lại cảnh:
   - Sai chữ phụ đề: sửa storyboard → sinh lại `caps.json` và `.srt` → dựng lại dải phụ đề → ghép từ master (một lần mã hoá).
   - Sai một câu giọng: thay đúng tệp Lxx đó → phối lại → bản không phụ đề ghép `-c:v copy`, bản có phụ đề mã hoá một lần. Gửi lại gói giọng ghi rõ chỉ câu đó đổi.
   - Bỏ một câu: tắt câu đó trên track giọng với dốc đặt trong khe lặng, bỏ các mẩu phụ đề của nó.
5. "Phần còn lại như cũ" là mặc định: không đổi mức nhạc, không dời nhịp, không sửa thêm chỗ khác; thấy lỗi khác thì báo, người dùng bảo mới sửa.
6. **So với bản đã giao trước khi gửi (bắt buộc):** PSNR từng khung (cả khung và riêng dải phụ đề) → các khoảng giây hình khác; mức âm từng giây → các giây lệch quá 0,5 dB. Cả hai phải nằm gọn trong khoảng định sửa, ngoài khoảng mà khác thì chưa được gửi. Báo người dùng đúng các khoảng đó và hai mốc giây cần nghe lại.
7. Bản mới đặt hậu tố mới, không ghi đè; lưu vào thư mục dự án người dùng chỉ định, không lưu vào Downloads. Bản sai đã ghi lên máy người dùng: nói rõ tên để họ không dùng; không tự xoá hay di chuyển.

## Thư viện hiệu ứng và đường Blender → GLB → phim (đo 15–16/11/2026)

Thư mục làm việc: `revit-live-demo-20261110/INTRO-HYPERFRAMES_v8f_20261115/` trong kho `Long0308/setupagent` (máy công ty `D:\61.SetupAgent`, máy nhà `D:\61.SetupAgent`). Đọc skill `hyperframes-hieu-ung-lp` trước khi dùng.

- **Hiệu ứng có sẵn, đừng viết lại:** 711 hiệu ứng có video xem trước ở http://127.0.0.1:4401/ (14 hiệu ứng `lp-*` lấy từ phim intro + 448 khối kho HyperFrames + cảnh mẫu). Chỉnh tham số ở http://127.0.0.1:4401/tinh-chinh.html rồi dán dòng `data-variable-values`. Trang chạy bằng Docker: `docker compose -f docker-compose.xem.yml up -d`.
- **Mô hình 3D đi từ Blender sang phim bằng GLB:** dựng trong Blender qua Blender MCP (đúng kích thước, vật mới để trong bộ sưu tập riêng, không sửa vật có sẵn) → `bpy.ops.export_scene.gltf(filepath=..., export_format="GLB", use_selection=True)` → nạp bằng `GLTFLoader` trong cảnh three.js của HyperFrames. Mẫu chạy được: `e2e/blender-thu/` (đoạn ống có co 90°).
- **Ba điều bắt buộc khi nạp GLB trong HyperFrames** (đều đã đo): (1) đăng ký `window.__hf.buildReady["<tên>"]` và chỉ báo xong khi mô hình nạp xong, nạp hỏng thì KHÔNG báo xong để lệnh xuất dừng thay vì ra phim trống; (2) vẽ theo `e.detail.time` của sự kiện `hf-seek`, không dùng đồng hồ; (3) thư viện ESM nạp qua `importmap` ở thẻ head của tệp gốc.
- **Cổng đo:** `python -I -X utf8 e2e/do_glb.py <tệp.glb> <X> <Y> <Z>` đo khung bao ngay trong tệp GLB (không cần three.js hay Blender) và so với kích thước đã dựng; glTF dùng trục Y hướng lên nên chiều cao Z của Blender thành Y. Chụp xuôi và ngược rồi so điểm ảnh bằng `e2e/so_anh.py`. Số đo mẫu: khung bao 2,200 × 2,200 × 0,300 m lệch 0 mm; chụp xuôi/ngược ở 0,5 · 1,5 · 3 s khác 0 điểm ảnh.
- **Đặt máy quay cho vật nằm trọn khung:** lấy bán kính = nửa đường chéo khung bao; với góc nhìn 35° lùi khoảng 4 lần bán kính. Lấy nửa cạnh dài nhất thì vật bị cắt khi quay (đã gặp).
- **Với phim intro:** phim intro V8f đã dựng lại trên HyperFrames ở `intro-v8f/` (3.675 khung khớp bản giao, SSIM thấp nhất 0,966). Cú đập theo phách đặt bằng `lp-cu-dap` đúng giây phách do `e2e/e18_librosa.py` dò, rồi đo lại bằng `e2e/do_phim.py`. Giờ từng từ cho phụ đề lấy bằng `e2e/e19_whisperx.py` (phải truyền mô hình căn giờ tiếng Việt, xem bài học 13 của `hyperframes-hieu-ung-lp`).
