"""CPU-only, serial ffmpeg review build. Input picks require explicit visual review."""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import psutil
from PIL import Image, ImageDraw, ImageFont
from review_sources import ROOT, HERE, V2, frame, sha, tile

FPS = 24
MUSIC = ROOT / 'docs/media-stage/MUSIC-BED-V004-M1/edit_B.wav'
STAGING = ROOT / 'production-local/engine/staging/newtecons-30s'

def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def probe(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], encoding='utf-8'))

def ff(args, log):
    # Other lanes may encode. Never kill them; wait before launching this encoder.
    while any(p.info['name'] and p.info['name'].lower() == 'ffmpeg.exe' for p in psutil.process_iter(['name'])):
        print('Waiting for existing ffmpeg process', flush=True)
        time.sleep(3)
    cmd = ['ffmpeg', '-hide_banner', '-nostdin', '-y', '-threads', '8', '-filter_threads', '8', '-filter_complex_threads', '8'] + list(map(str, args))
    with open(log, 'w', encoding='utf-8') as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'ffmpeg failed: {log}\n' + log.read_text(encoding='utf-8', errors='replace')[-2000:])
    return log.read_text(encoding='utf-8', errors='replace')

def loudness(path, out, prefix):
    log = ff(['-i', path, '-vn', '-af', 'loudnorm=I=-14:TP=-1:LRA=11:print_format=json', '-f', 'null', '-'], out/f'{prefix}-loudness.log')
    matches = re.findall(r'\{\s*"input_i".*?\}', log, re.S)
    if not matches:
        raise ValueError(f'No loudness measurement: {path}')
    value = json.loads(matches[-1])
    dump(out/f'{prefix}-loudness.json', value)
    return value

def rejected_sources():
    hashes = set()
    names = {'S05_FEMALE_THANKS_H3_s20261112.mp4', 'S05_FEMALE_H3_bietroi_s20261102.mp4', 'S03A_REPLY_H3_s2026110301.mp4'}
    def walk(v):
        if isinstance(v, dict):
            if 'reject' in str(v.get('verdict', v.get('status', ''))).lower():
                for h in v.get('sha256', []) if isinstance(v.get('sha256'), list) else [v.get('sha256')]:
                    if isinstance(h, str): hashes.add(h)
                for f in v.get('file', []) if isinstance(v.get('file'), list) else [v.get('file')]:
                    if isinstance(f, str): names.add(Path(f).name)
            for x in v.values(): walk(x)
        elif isinstance(v, list):
            for x in v: walk(x)
    for p in STAGING.glob('USER-DECISIONS-*.json'):
        walk(json.loads(p.read_text(encoding='utf-8-sig')))
    return hashes, names

def prepare(tag):
    out = HERE/tag
    out.mkdir(exist_ok=False)
    # Snapshot at every build, even when picks are unchanged.
    dump(out/'v2-rescan.json', [dict(name=p.name, bytes=p.stat().st_size, modified=p.stat().st_mtime) for p in V2.glob('*.mp4')])
    dump(out/'decisions-snapshot.json', [dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in STAGING.glob('*DECISIONS*.json')])
    config = json.loads((HERE/'picks_v008.json').read_text(encoding='utf-8'))
    expected = [s['shot'] for s in json.loads((ROOT/'docs/handoffs/EDL-DRAFT-V014-2026-11-01.json').read_text(encoding='utf-8-sig'))['timeline']]; expected.insert(expected.index('S03_A')+1, 'S03_A_REPLY')
    if [s['shot'] for s in config['slots']] != expected:
        raise ValueError('Must preserve 16 ordered V014 slots plus S03_A_REPLY after S03_A')
    banned_hashes, banned_names = rejected_sources()
    cursor = 0
    for s in config['slots']:
        path = ROOT/s['path']
        digest = sha(path)
        if digest in banned_hashes or path.name in banned_names or 'MUSIC_YUE_V005' in path.name or 'ASTRA4' in path.name.upper():
            raise ValueError(f'Rejected source: {path}')
        if digest != s['reviewed_sha256']:
            raise ValueError(f'Source changed since 3-frame review: {path}')
        if s.get('approval_sha256') and digest != s['approval_sha256']:
            raise ValueError('Approval hash mismatch')
        s['source_sha256'] = digest
        s['path'] = str(path)
        s['probe'] = probe(path)
        s['duration'] = math.ceil(s['duration']*24 - 1e-7)/24
        s['frames'] = round(s['duration']*24)
        s['start_s'] = cursor/24
        cursor += s['frames']
        if s.get('audio_path'):
            s['audio_path'] = str(ROOT/s['audio_path'])
            s['audio_sha256'] = sha(s['audio_path'])
            if s['audio_sha256'] in banned_hashes or Path(s['audio_path']).name in banned_names:
                raise ValueError('Rejected audio')
        elif s.get('speech_text'):
            raise ValueError(f'Dialogue has no audio source: {s["shot"]}')
        if s.get('timing_receipt'): s['timing_receipt'] = str(ROOT/s['timing_receipt'])
    config.update(tag=tag, created_at=datetime.now().astimezone().isoformat(), total_frames=cursor, total_duration=cursor/24,
                  music_sha256=sha(MUSIC), final_acceptance=False, status='root_picked_review')
    dump(out/'manifest.json', config)
    return out, config

def render(tag):
    out, config = prepare(tag)
    slots = config['slots']
    from timing_ass import prepare_subtitles
    timing = prepare_subtitles(slots, out)
    if timing.get('failed_slots'):
        raise ValueError(f'Required subtitle generation failed: {timing["failed_slots"]}')
    print('SUBTITLES READY', flush=True)
    parts = []
    audio_parts = []
    for i, s in enumerate(slots):
        dest = out/f'{i+1:02d}-{s["shot"]}.mp4'
        dur = s['duration']
        source = s['path']
        vf = [f'trim=start={s.get("in_s", 0)}', 'setpts=PTS-STARTPTS']
        if s.get('source_crop'): vf += [f'crop={s["source_crop"]}']
        if s.get('freeze'):
            vf += ['select=eq(n\\,0)', 'setpts=PTS-STARTPTS']
        vf += ['scale=2560:1440:force_original_aspect_ratio=increase:flags=lanczos', 'crop=2560:1440', 'setsar=1', 'fps=24', f'tpad=stop_mode=clone:stop_duration={dur}', f'trim=end_frame={s["frames"]}']
        # Five-frame fade on either side makes a ten-frame dip at a location boundary.
        if s.get('dip_in'): vf += ['fade=t=in:st=0:d=0.208333333']
        if s.get('dip_out'): vf += [f'fade=t=out:st={dur-5/24:.9f}:d=0.208333333']
        ff(['-i', source, '-vf', ','.join(vf), '-an', '-frames:v', s['frames'], '-c:v', 'libx264', '-threads', '8', '-preset', 'fast', '-crf', '16', '-pix_fmt', 'yuv420p', '-r', '24', dest], out/f'{i+1:02d}-video.log')
        parts.append(dest)
        adest = out/f'{i+1:02d}-{s["shot"]}.wav'
        if s.get('audio_path'):
            af = f'atrim=start={s.get("audio_in_s", s.get("in_s", 0))},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo'
            if s.get('audio_offset_s'): af += f',adelay={round(s["audio_offset_s"]*1000)}:all=1'
            af += f',apad,atrim=duration={dur}'
            if s.get('speech_text'): af += ',loudnorm=I=-18:TP=-2:LRA=11'
            af += f',aresample=48000,atrim=duration={dur}'
            ff(['-i', s['audio_path'], '-vn', '-af', af, '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s24le', '-threads', '8', adest], out/f'{i+1:02d}-audio.log')
        else:
            ff(['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', dur, '-c:a', 'pcm_s24le', '-threads', '8', adest], out/f'{i+1:02d}-audio.log')
        audio_parts.append(adest)
        print('SLOT READY', s['shot'], flush=True)
    def concatfile(name, paths):
        p = out/name
        p.write_text(''.join("file '" + q.as_posix().replace("'", "'\\''") + "'\n" for q in paths), encoding='utf-8')
        return p
    picture = out/'picture.mp4'
    ff(['-f', 'concat', '-safe', '0', '-i', concatfile('picture-concat.txt', parts), '-c', 'copy', picture], out/'picture.log')
    dialogue = out/'dialogue-and-footsteps.wav'
    ff(['-f', 'concat', '-safe', '0', '-i', concatfile('audio-concat.txt', audio_parts), '-c', 'copy', dialogue], out/'dialogue.log')
    total = config['total_duration']
    intervals = [(s['start_s'], s['start_s']+s['duration']) for s in slots if s.get('speech_text')]
    active = '+'.join(f'between(t,{a:.6f},{b:.6f})' for a,b in intervals) or '0'
    # Voice target -18; bed -34 in dialogue (-16 dB relative), -20 between lines.
    music_filter = f"loudnorm=I=-20:TP=-3:LRA=11,aresample=48000,volume='if(gt({active},0),0.1995262315,1)':eval=frame,afade=t=in:d=0.3,afade=t=out:st={total-0.7}:d=0.7"
    raw = out/'mix-before-normalization.wav'
    ff(['-i', dialogue, '-stream_loop', '-1', '-i', MUSIC, '-filter_complex', f'[1:a]{music_filter}[m];[0:a][m]amix=inputs=2:normalize=0:duration=first[a]', '-map', '[a]', '-t', total, '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s24le', '-threads', '8', raw], out/'mix.log')
    measured = loudness(raw, out, 'premix')
    norm = ('loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:print_format=json'
            f':measured_I={measured["input_i"]}:measured_TP={measured["input_tp"]}:measured_LRA={measured["input_lra"]}:measured_thresh={measured["input_thresh"]}:offset={measured["target_offset"]}')
    mix = out/'mix-final.wav'
    ff(['-i', raw, '-af', norm, '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s24le', '-threads', '8', mix], out/'normalize.log')
    final = out/f'PREVIEW_2K_OVERNIGHT_{tag.upper()}.mp4'
    ass_path = (out/'karaoke.ass').as_posix().replace(':', '\\:')
    ff(['-i', picture, '-i', mix, '-vf', f"ass='{ass_path}'", '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'fast', '-crf', '16', '-threads', '8', '-pix_fmt', 'yuv420p', '-r', '24', '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-ac', '2', '-t', total, '-movflags', '+faststart', final], out/'final-2k.log')
    measured_final = loudness(final, out, 'delivery')
    if float(measured_final['input_tp']) > -1 or abs(float(measured_final['input_i']) + 14) > 0.3:
        raise ValueError(f'Delivery loudness outside target: {measured_final}')
    fhd = out/f'PREVIEW_1080P_OVERNIGHT_{tag.upper()}.mp4'
    ff(['-i', final, '-vf', 'scale=1920:1080:flags=lanczos', '-c:v', 'libx264', '-preset', 'fast', '-crf', '16', '-threads', '8', '-c:a', 'copy', '-movflags', '+faststart', fhd], out/'final-1080p.log')
    for p in [final, fhd]:
        dump(out/(p.stem+'-ffprobe.json'), probe(p))
    deliverables = {p.name:dict(sha256=sha(p), bytes=p.stat().st_size) for p in [final, fhd]}
    for s in slots:
        if sha(s['path']) != s['source_sha256']:
            raise ValueError(f'Source changed during build: {s["shot"]}')
        if s.get('audio_path') and sha(s['audio_path']) != s['audio_sha256']:
            raise ValueError(f'Audio changed during build: {s["shot"]}')
    dump(out/'delivery.json', dict(files=deliverables, loudness=measured_final, total_frames=config['total_frames'], root_picked=True))
    contact = contact_sheet(slots, out)
    report(out, config, timing, measured_final, deliverables)
    for p in [final, fhd, contact]:
        target = V2/p.name
        if target.exists(): raise FileExistsError(target)
        shutil.copy2(p, target)
        if sha(target) != sha(p): raise ValueError('Copy hash mismatch')
    shutil.copy2(out/'REPORT.md', HERE/'REPORT_V008.md'); shutil.copy2(out/'REPORT.md', V2/'REPORT_PREVIEW_2K_OVERNIGHT_V008.md')
    print('BUILD COMPLETE', final, flush=True)

def contact_sheet(slots, out):
    sheet = Image.new('RGB', (1440, 260*len(slots)), '#18212d')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 20)
    for i, s in enumerate(slots):
        dur = min(s['duration'], float(s['probe']['format']['duration'])-s.get('in_s',0))
        for j, offset in enumerate([0, dur/2, max(0, dur-0.05)]):
            t = s.get('in_s',0)+offset
            im = frame(Path(s['path']), 0 if s.get('freeze') else t)
            im.thumbnail((480, 228), Image.Resampling.LANCZOS)
            sheet.paste(im, (j*480+(480-im.width)//2, i*260+30))
        draw.text((8, i*260+4), f'{i+1:02d} {s["shot"]} | {s["status"]} | {Path(s["path"]).name}', font=font, fill='white')
    dest = out/f'CONTACT_SHEET_{out.name.upper()}.png'
    sheet.save(dest)
    return dest

def report(out, cfg, timing, measured, deliverables):
    lines = [f'# NEWTECONS — bản review qua đêm {out.name}', '', f'Tạo lúc {cfg["created_at"]}. Đủ 16 slot EDL V014 cộng 1 slot S03_A_REPLY (17 slot), {cfg["total_duration"]:.3f} giây; 2560×1440, 24 fps. Các lựa chọn mới là **root_picked**, chưa phải user_approved.', '',
             'CPU/ffmpeg, mỗi lần một ffmpeg, threads 8; Lanczos + center crop, không thêm thanh đen, không chạy SeedVR2. Nguồn đã upscale được duyệt từ trước vẫn giữ provenance.', '',
             'Cắt thẳng trong cảnh. Dip 10 frame tại các ranh giới địa điểm được ghi dip_in/dip_out trong manifest. Nhạc edit_B, thoại mục tiêu -18 LUFS, nhạc khoảng -34 LUFS dưới thoại trước chuẩn hóa tổng.', '',
             f'Đo file AAC giao: **{measured["input_i"]} LUFS**, **{measured["input_tp"]} dBTP**, LRA {measured["input_lra"]}.', '',
             '| Slot | File | Quyết định / lý do | Còn thiếu |', '|---|---|---|---|']
    for s in cfg['slots']:
        lines.append(f'| {s["shot"]} | `{Path(s["path"]).name}` | {s["status"]}: {s["why"]} | {s.get("missing", "Không ghi nhận ở mẫu 3 frame")} |')
    lines += ['', '## CHỖ NÀO BẠN ĐOÁN — NÓI THẲNG', '',
              '- Ba khung hình chỉ kiểm mẫu: không chứng minh sạch lỗi logo/miệng trong từng frame. Không gọi ASR là đã nghe duyệt.',
              '- Thời lượng slot được nới khi cần giữ trọn hành động/thoại; EDL V014 chỉ giữ thứ tự và đúng 16 slot.',
              '- Timing có nguồn nhận dạng/receipt và mức sai khác trong timing.json; từ thiếu được đánh dấu ước lượng, không coi đã xác minh.',
              '- Ranh giới từ “Mai” ở S03 được điều chỉnh theo năng lượng âm thanh vì ASR bắt muộn; đây là suy luận âm học, chưa phải nghe duyệt. Receipt gốc vẫn được giữ.',
              '- Các vấn đề được nêu ở cột còn thiếu chưa được sửa bằng việc đóng gói bản review.', '',
              '## File và SHA256', '']
    for name, v in deliverables.items(): lines.append(f'- `{name}` — `{v["sha256"]}` ({v["bytes"]} byte).')
    lines += ['', 'Bằng chứng: manifest.json, v2-rescan.json, decisions-snapshot.json, *-ffprobe.json, delivery-loudness.json, timing.json, karaoke.ass và CONTACT_SHEET*.png.', '', 'Đối chiếu timing:', '']
    for s in timing.get('slots', []):
        lines.append(f'- {s["shot"]}: {s["method"]}, {s["status"]}; ASR: {s.get("recognized_transcript", "receipt có hash khớp")}.')
    pt = HERE/'pitch_table_v008.json'
    if pt.exists():
        lines += ['', '## Bảng cao độ (F0 pyin trung vị) mọi nhân vật nói', '', '| Slot | Nhân vật | Profile | F0 trung vị (Hz) | Khoảng nam (<180)? |', '|---|---|---|---|---|']
        for r in json.loads(pt.read_text(encoding='utf-8')): lines.append(f'| {r["shot"]} | {r["character"]} | {r["profile"]} | {r["f0_median_hz"]:.1f} | {r["verdict"]} |')
    (out/'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('tag')
    render(parser.parse_args().tag)
