"""Tạo picks_v008.json từ picks_v007.json: thay S03_A, S05_A (và S06_A nếu có H3 V008) bằng clip giọng nam FLEURS. File mới."""
import copy, hashlib, json, subprocess
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
H3 = ROOT / 'docs/media-stage/OVERNIGHT-V008-H3'
V2REL = 'production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/REVIEW/2026-10-31-CHO-ANH-CHOT/26_DUYET_TUNG_CANH/v2/'
WHY = {'S03_A': 'V008: KKT_TB đổi sang profile nam FLEURS 2aa9b44e (ref 145 Hz); H3 cục bộ ComfyUI, WAV hash-bound.',
       'S05_A': 'V008: CHAR_07 đổi sang profile nam FLEURS 0e31d579 (ref 163 Hz); H3 cục bộ ComfyUI, WAV hash-bound.',
       'S06_A': 'V008: giọng CHT 251e559a, lời đổi biến thể vượt ASR; H3 cục bộ ComfyUI, WAV hash-bound.'}
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dur(p): return float(json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(p)]))['format']['duration'])
cfg = json.loads((HERE/'picks_v007.json').read_text(encoding='utf-8'))
out = []
for s in cfg['slots']:
    shot = s['shot']; rec = H3/shot/'receipt.json'
    if shot in ('S03_A','S05_A','S06_A') and rec.exists():
        prep = json.loads((H3/shot/'preparation.json').read_text(encoding='utf-8'))
        f = H3/shot/f'{shot}_V008VOICE_s{prep["seed"]}.mp4'
        rel = V2REL + f.name
        n = copy.deepcopy(s)
        n.update(path=rel, audio_path=rel, reviewed_sha256=sha(f), status='root_picked', duration=dur(f),
                 visual_review='Root viewed contact tiles of V008VOICE clip; hash bound', why=WHY[shot],
                 missing='Giọng/khẩu hình chưa user nghe duyệt; ASR khớp chữ chứ không chứng minh hợp giọng.')
        if shot == 'S06_A' and (H3/'S06_A'/'text.txt').exists(): n['speech_text'] = (H3/'S06_A'/'text.txt').read_text(encoding='utf-8')
        out.append(n); print('V008', shot, f.name)
    else:
        out.append(s)
cfg['slots'] = out
(HERE/'picks_v008.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
print('OK', [(s['shot'], round(s['duration'], 3)) for s in out])
