"""Bảng F0 (pyin, trung vị khung hữu thanh) cho mọi slot có thoại trong picks_v008.json. Ghi pitch_table_v008.json (file mới)."""
import json, subprocess, sys, tempfile
from pathlib import Path
import numpy as np, librosa
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[2]
CHAR = {'S02_A': ('GDDA đạo diễn', 'd9d994a3 (theo brief)'), 'S03_A': ('KKT_TB (nam)', '2aa9b44e FLEURS_M_145Hz_K'),
        'S03_A_REPLY': ('Người đeo kính (nam)', '0e61ba93 FLEURS_M_adult'), 'S04_A': ('Người nói S04_A (chưa rõ; đoán GDDA)', 'clip user đã duyệt, profile không ghi ở slot'),
        'S05_A': ('CHAR_07 (nam, kỹ sư trẻ)', '0e31d579 FLEURS_M_163Hz_J'), 'S05_FEMALE': ('Nữ nhân viên', 'clip đã duyệt, profile không ghi ở slot'),
        'S05_FEMALE_THANKS': ('Nữ nhân viên', 'clip đã duyệt, profile không ghi ở slot'), 'S06_A': ('CHT (nam)', '251e559a FLEURS_M_deep'),
        'S07_PRE': ('Lan Anh (nữ)', 'e02a9343'), 'S07_A': ('Nhân vật S07_A (chưa rõ)', 'không ghi ở slot')}
def verdict(c, med):
    if 'chưa rõ' in c: return ('CẦN ROOT KIỂM: F0 %.0f Hz thuộc dải nữ, chưa biết nhân vật nam hay nữ' % med) if med >= 180 else 'chưa rõ nhân vật; F0 <180'
    if any(k in c for k in ('(nam', 'GDDA', 'KKT', 'CHT')): return 'nam <180: ĐẠT' if med < 180 else 'NAM NHƯNG >180: LỖI'
    return 'nữ (không áp tiêu chí nam)'

cfg = json.loads((HERE/'picks_v008.json').read_text(encoding='utf-8')); rows = []
for s in cfg['slots']:
    if not s.get('speech_text'): continue
    src = ROOT/s['audio_path']
    with tempfile.TemporaryDirectory() as t:
        w = Path(t)/'a.wav'
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(src),'-vn','-ac','1','-ar','16000',str(w)], check=True)
        y, sr = librosa.load(str(w), sr=16000)
    v, vf, _ = librosa.pyin(y, fmin=60, fmax=450, sr=sr, frame_length=1024)
    x = v[vf & ~np.isnan(v)]; med = float(np.median(x))
    c, p = CHAR[s['shot']]
    rows.append(dict(shot=s['shot'], character=c, profile=p, f0_median_hz=med, voiced_frames=int(len(x)),
                     verdict=verdict(c, med)))
    print(rows[-1], flush=True)
(HERE/'pitch_table_v008.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
