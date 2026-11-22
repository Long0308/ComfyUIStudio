# Prompt ĐÃ DUYỆT 16/11/2026 — mẫu dùng lại cho cảnh NEWTECONS sau

User duyệt Cảnh 2: «cảnh này đẹp quá, áo đạt mọi thứ» ⇒ dùng đúng cấu trúc này. Nguyên văn prompt ở thư mục `approved-prompts-2026-11-16/`.

## Công thức ảnh khung đầu (Codex `jjv images`, acct4/acct5 song song)
1. Mở đầu cố định: `Use your built-in image generation tool (image_gen) to create exactly ONE image…`
2. Liệt kê `Image N: … [tên file]` ĐÚNG thứ tự `--ref`: `set` (ảnh bối cảnh thật — người thật KHÔNG phải nhân vật, bỏ timestamp) → `set` (shot đã duyệt liền trước = neo liền mạch) → `identity` (mặt CẮT SẠCH, không nón/chữ) → `wardrobe_only` (gile SITE MANAGER trước/sau, vải lưới rất nhỏ, N cổ áo, nón V004 trước + 6 mặt) → `identity` (cùng nhân vật ở cảnh đã duyệt).
3. Khối SHOT: máy quay (cỡ cảnh, tiêu cự, độ cao), hành động 1 câu, trang phục nhắc lại theo Image số, đạo cụ nối cảnh (nón lệch trên bàn).
4. Khối người phụ: «invented people (not the people of Image 1)», cùng đồng phục; luật nón: logo CHỈ mặt trước, ai quay lưng nón trơn; lưng gile đúng NEWTECONS.
5. Màn chiếu/màn hình: «no readable words or numbers» (chữ thật ghép sau bằng font).
6. LOOK chống vẻ AI + `No subtitles… no timestamp` + `16:9, ≥1536×864`.

## Công thức video (Topview WAN 3.0, 720p, audio:true)
Máy quay + chuyển động cụ thể → thoại tiếng Việt trong ngoặc kép kèm «northern accent, strong… voice, every word clear, lips in sync, the whole sentence» → «Only he speaks» → giữ nguyên mặt/gile/nón như ảnh → dòng `Sound:` liệt kê từng tiếng (+ «no music»). Thoại dài ~20 âm tiết cần 5 s.

## Cảnh 2 — họp BCH (DUYỆT «đẹp quá, áo đạt mọi thứ»)
Thư mục: `docs/media-stage/S02-MEETING-V001/`

| Shot | Prompt ảnh | Vai |
|---|---|---|
| S02-K1-V001 | `approved-prompts-2026-11-16/S02_PROMPT_K1_STAND_POINT_V001.txt` | toàn cảnh đứng chỉ bảng |
| S02-K2-V001 | `approved-prompts-2026-11-16/S02_PROMPT_K2_GDDA_SPEAK_V001.txt` | cận trung nói |

Prompt video WAN (nguyên văn):

- **SH1_STAND**: "Wide locked-off shot with a very slow push-in. The Project Director, standing at the head of the long table, plants his " "hand hard on the table and jabs his finger at the red delayed bars of the projected progress chart, his face hard with " "pressure. The command team around the table goes quiet and tense: one engineer stops writing, another exchanges a " "worried look with his neighbour, one leans back. Nobody speaks. Keep every face, the SITE MANAGER vest, the NEWTECONS " "vests, the white hard hats on the table (logo only on the front) and the room exactly as in the image. Sound: " + ROOM + "."
- **SH2_SPEAK**: "Medium close-up from a slightly low angle, subtle handheld tension, very slow push-in. The Project Director leans over the " "table with his fist pressed down and speaks to the command team in Vietnamese, northern accent, with a strong, forceful, " "tense voice, every word clear, lips in sync, the whole sentence: \"Tiến độ đang gấp, chúng ta phải nhanh chóng huy động " "thêm nhân công mới đảm bảo tiến độ!\" On the last words he presses his fist on the table once. Only he speaks. Keep his " "face, the SITE MANAGER vest, the fine grid shirt, the Gantt chart on the screen behind and the white NEWTECONS hard hat at " "the bottom of the frame exactly as in the image. Sound: his powerful voice close to the microphone in a quiet, tense room, " "faint construction noise outside; no music."

## Cảnh 3 — cuộc gọi chia đôi (DUYỆT)
Thư mục: `docs/media-stage/S03-CALL-SPLIT-V001/`

| Shot | Prompt ảnh | Vai |
|---|---|---|
| S03-K1-V001 | `approved-prompts-2026-11-16/S03_PROMPT_K1_OFFICE_RING_V001.txt` | văn phòng GĐ Khối KT, điện thoại reo |
| S03-K2-V001 | `approved-prompts-2026-11-16/S03_PROMPT_K2_PICKUP_V001.txt` | nhấc máy (neo K1) |
| S03-K3L-V001 | `approved-prompts-2026-11-16/S03_PROMPT_K3L_GDDA_SITE_V001.txt` | nửa trái GĐDA hầm thi công |
| S03-K3L-V002 | `approved-prompts-2026-11-16/S03_PROMPT_K3L_GAZE_EDIT_V002.txt` | sửa hướng nhìn |
| S03-K3R-V001 | `approved-prompts-2026-11-16/S03_PROMPT_K3R_GDK_ANSWER_V001.txt` | nửa phải trả lời |
| S03-K3R-V002 | `approved-prompts-2026-11-16/S03_PROMPT_K3R_GAZE_EDIT_V002.txt` | sửa hướng nhìn |

Prompt video WAN (nguyên văn):

- **SH1_RING**: "Locked-off medium-wide shot with a very slow push-in. The Technical Block Director types on the silver MacBook, focused. " "The black smartphone lying face-up on the wooden desk is ringing: its screen glows with an incoming call and it buzzes " "on the wood. On the last ring he stops typing and glances down at the phone. Nobody speaks. Keep the room, the desk, the " "MacBook, the phone, his glasses and his fine blue-white grid shirt exactly as in the image. " "Sound: the classic iPhone ringtone (bright marimba melody) ringing clearly, about two cycles, the phone vibrating on the wooden desk, soft keyboard typing, " + OFFICE + "."
- **SH2_PICKUP**: "The camera pushes in smoothly from the medium-wide desk view to a medium close-up of the Technical Block Director. " "The phone keeps ringing; he picks the black smartphone up from the desk with his right hand and raises it to his right " "ear in one natural motion, his left hand staying on the MacBook keyboard; the ringing stops the moment he answers and he " "says quietly in Vietnamese: \"A lô.\" Keep his face, glasses, shirt, desk and office exactly as in the images. " "Sound: the iPhone marimba ringtone playing and cut off the moment he picks up, a soft rustle of the shirt sleeve, one quiet natural northern Vietnamese \"A lô\", " + OFFICE + "."
- **SH3L_GDDA_V2**: "Medium close-up, handheld with a slight natural sway, the busy basement softly out of focus behind him. The Project Director, " "phone pressed to his right ear, sweat on his temple, speaks into the phone firmly, clearly and at a brisk pace in Vietnamese, " "northern accent, every word audible, lips in sync, the whole sentence from the first word to the last: " "\"Mai em xuống công trường rồi rà soát phương án thực hiện biện pháp thi công cùng anh nhé.\" He keeps looking toward the " "right of the frame and finishes with one short nod. HELMETS: every hard hat in the shot is WHITE (no yellow helmets); the " "NEWTECONS logo is only on the FRONT of a hard hat; the backs of the workers' helmets are plain white. Keep his face, hard hat, " "SITE MANAGER vest and shirt exactly as in the image. Only he speaks. Sound: his clear voice close to the microphone, " "with " + SITE + " low in the background."
- **SH3R_GDK**: "Medium close-up, almost static, the office softly out of focus behind him. The Technical Block Director holds the phone " "to his ear and listens attentively for the first three seconds, silent, with two small nods, looking toward the left of " "the frame. Then he answers calmly and briefly in Vietnamese, northern accent, lips in sync: \"Ok em biết rồi anh.\" " "and gives one decisive nod. The caller's voice is not heard. Keep his face, glasses, fine blue-white grid shirt with the " "tiny collar N, and the office exactly as in the image. Sound: silence of the office while he listens, then his calm " "short reply, " + OFFICE + "."
