"""Explicit choices after inspecting 3-frame source tiles on 2026-11-02."""
import json
from pathlib import Path
from review_sources import ROOT, HERE, V2

inv = json.loads((HERE/'source-inventory.json').read_text(encoding='utf-8'))
byname = {Path(x['path']).name:x for x in inv}
edl = json.loads((ROOT/'docs/handoffs/EDL-DRAFT-V014-2026-11-01.json').read_text(encoding='utf-8-sig'))
canon = {s['shot']:s['speech_text'] for s in edl['timeline']}
canon.update(S05_FEMALE_THANKS='Dạ, em cảm ơn anh ạ.', S07_PRE='Anh em vất vả rồi, dùng nước nhé.', S07_A='Anh em đừng lo, dù vất vả nhưng Công ty luôn quan tâm, sẻ chia và đồng hành.')
slots=[]
def add(shot, name, why, duration=None, approved=False, audio=True, missing='', **extra):
    src=byname[name]
    s=dict(shot=shot,path=src['path'],reviewed_sha256=src['sha256'],duration=duration or src['duration'],status='approved' if approved else 'root_picked',why=why,speech_text=canon.get(shot),missing=missing,visual_review='Root viewed first/middle/last tile; source hash bound',tile=src['tile'])
    if approved: s['approval_sha256']=src['sha256']
    if audio and src['audio']: s['audio_path']=src['path']
    if not audio: s['speech_text']=None
    s.update(extra)
    slots.append(s)

add('INTRO_FOOTSTEPS','INTRO_FOOTSTEPS_H3_s20261102_STEPS.mp4','Nguồn có tiếng bước chân theo yêu cầu; đi vào văn phòng công trường.',duration=2.5)
add('INTRO_TIMELAPSE','TIMELAPSE_10S_H3_R7_SMOOTH.mp4','Chưa có ONPLOT; dùng fallback được chỉ định, giữ đủ diễn tiến 10 giây.',audio=False,dip_out=True,missing='Tháp mọc phía trước/bên phải lô đất ban đầu, chưa đúng ONPLOT.')
add('SCENE_01','SCENE_01_HELMET_MACRO_H3_s20261101.mp4','Cận mũ đặt lên bản vẽ, đã có motion thay slot trống.',duration=2.333333,audio=False,dip_in=True,missing='Cận mũ thay bố cục hai người; chưa có cảnh hai nhân vật khác nhau.')
add('S02_A','S02_A_seedvr2_1440_aspect.mp4','Giữ đúng SHA clip user duyệt; người nói hướng vào cuộc họp.',approved=True)
add('S03_A','S03_A_seedvr2_1440_aspect.mp4','Giữ clip chính đã duyệt; loại reply ASTRA4 sai câu.',approved=True,missing='Thiếu câu đáp đúng “Dạ, rõ rồi anh.”; chờ clip mới.')
add('MAP_NORTH','MAP_NORTH_V007.mp4','Ba điểm và nhãn địa danh hiện dần; V007R2 cùng nội dung.',audio=False)
add('S04_A','S04_A_PLUS_TURN_preview_s202611041.mp4','Bản PLUS_TURN được duyệt 22:25; giữ trọn quay về cửa kính.',approved=True,dip_out=True)
add('PAN_TRANSITION','PAN_OFFICE_V004.mp4','Giữ đủ 2 giây để đáp vào văn phòng, tránh cắt mất đích.',audio=False,dip_in=True)
add('S05_A','S05_A_redirect_s20261111.mp4','Motion đã được chọn; nam hướng nói về nữ.',missing='Motion approved_motion_revoice; giọng còn trùng, chờ bản thay giọng. Có dấu N đôi ở cổ áo.')
add('S05_FEMALE','S05_FEMALE_H3_bietroi_R2_s20261121.mp4','R2 sửa biểu cảm: mỉm cười rồi quay gõ; loại bietroi_s20261102 bị bác.',timing_receipt='docs/media-stage/S05-TRIO-FIX-V001/S05F_BIETROI_R2/seed-20261121/decoded-audio-asr.json',missing='Logo cổ áo thiếu; cần xem lại biến dạng tay khi gõ.')
add('S05_SCREEN','s05a_screen_insert_v004.mp4','Giữ insert user duyệt, 5 giây, không đổi hình.',approved=True,audio=False)
add('S05_FEMALE_THANKS','S05_FEMALE_H3_bietroi_R2_s20261121.mp4','Tạm giữ frame đầu nguồn R2 hợp lệ + WAV cảm ơn đúng canon; không dùng hai clip cảm ơn cũ sai câu.',duration=2.6,freeze=True,audio_path='docs/media-stage/S05-TRIO-FIX-V001/S05F_THANKS_R2/S05F_THANKS_R2_take1.wav',timing_receipt='docs/media-stage/S05-TRIO-FIX-V001/S05F_THANKS_R2/best-take.json',missing='Tạm ảnh giữ + thoại, chưa có motion nhép miệng đúng câu.',dip_out=True)
add('S06_A','S06_A_H3_s20261107.mp4','Nguồn lễ bàn giao mới nhất hiện có; không phát câu thoại cũ đã bị thay.',audio=False,dip_in=True,dip_out=True,missing='THIẾU WAV/clip thoại canon mới; slot tạm chỉ có nhạc. Bố cục bàn ký chưa phải phát biểu trên bục.')
add('S07_PRE','S07_PRE_LINE_H3_s202611202.mp4','Bản LINE mới có câu mời nước; nữ hướng về hai nam.',dip_in=True,missing='Mũ nam có logo ở phía bên trong mẫu; chờ sửa front-only. Chữ vai trò còn nhòe.')
add('S07_A','S07_A_H3_s202611071_TRACKED_R11.mp4','Chưa thấy R12; R11 có bánh/nước và role text; dùng WAV canon mới tạm trong bản review.',duration=5.875,audio_path='docs/media-stage/S07-LINES-H3-V002/A/S07_A_LINE_padded_for_H3.wav',missing='Lồng WAV mới trên motion cũ, KHÔNG khẳng định khớp môi; đuôi giữ frame. Chữ nổi/dán còn lộ. Chờ LINE + R12.',dip_out=True)
add('SLOGAN','SLOGAN_V004.mp4','Chữ NEWTECONS = CÙNG NHAU BỨT PHÁ đúng canon; giữ đủ reveal.',audio=False,dip_in=True,missing='Chưa có voice slogan mới; WAV cũ khác lời nên loại, chỉ nhạc.')
(HERE/'picks.json').write_text(json.dumps(dict(slots=slots),ensure_ascii=False,indent=2),encoding='utf-8')
print('Wrote 16 explicit picks')
