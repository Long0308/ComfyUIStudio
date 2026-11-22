#!/usr/bin/env python3
"""Tạo / kiểm cây thư mục dự án phim theo khung chuẩn (mọi loại phim).

Tạo dự án mới:
  python tao_du_an_phim.py tao  <thư mục gốc> <MÃ> <TênPhim> [--loai ai,3d,motion,live,screen] [--kho 1920x1080] [--fps 24]
Thêm cảnh / shot (bước 10):
  python tao_du_an_phim.py shot <thư mục dự án> SQ010 SH010 [--loai ai] [--ten-canh MoDau]
Kiểm cấu trúc, tên tệp, phiên bản, hiệu ứng lặp:
  python tao_du_an_phim.py kiem <thư mục dự án>
Chỉ tạo mới, không xoá, không ghi đè tệp đã có.
"""
import argparse, csv, json, os, re, sys
from datetime import date

GIAI_DOAN = {
    '00_ADMIN': ['01_Lich_Chi_phi', '02_Ban_quyen', '03_Lien_he_duyet'],
    '01_DEVELOPMENT': ['01_Kich_ban', '02_Treatment_Prompt', '03_Tai_lieu_goc'],
    '02_PREPRO': ['01_Storyboard', '02_Ho_so_phim', '03_Nhan_vat_CHR', '04_Boi_canh_LOC', '05_Dao_cu_PRP', '06_Previs'],
    '03_PRODUCTION': [],
    '04_POST': ['01_EDIT', '02_VFX_GFX', '03_SOUND/01_Dialogue', '03_SOUND/02_Music', '03_SOUND/03_SFX', '03_SOUND/04_Mix',
                '04_COLOR', '05_TITLES_SUBS'],
    '05_REVIEW': ['01_Dailies', '02_Benchmark'],
    '06_DELIVERY': ['01_Review', '02_Version', '03_Upscale', '04_FINAL', '05_Stems_DME', '06_QC'],
    '07_PIPELINE': ['01_Skill', '02_Script', '03_Quy_uoc', '04_Template'],
    '99_ARCHIVE': [],
}
MO_TA = {
    '00_ADMIN': 'project.json, mục lục, lịch, chi phí/credit, bản quyền nhạc–font–logo, người duyệt',
    '01_DEVELOPMENT': 'kịch bản, treatment, prompt, tài liệu gốc',
    '02_PREPRO': 'storyboard + SHOT_LIST, chuỗi ảnh đầu–cuối, hồ sơ phim, nhân vật, bối cảnh, đạo cụ, previs',
    '03_PRODUCTION': 'tạo hình theo cảnh/shot: SQxxx_<TenCanh>/SHxxx/… (thư mục con theo loại phim)',
    '04_POST': 'dựng (HyperFrames/Premiere), hiệu ứng, âm thanh, màu, chữ/phụ đề',
    '05_REVIEW': 'bản xem hằng ngày, trang benchmark, GHI_CHU_DUYET.csv',
    '06_DELIVERY': 'Review → Version → Upscale → FINAL; stems Dialogue/Music/Effects; báo cáo QC',
    '07_PIPELINE': 'skill, script, quy ước đặt tên, mẫu',
    '99_ARCHIVE': 'bản cũ, bản bỏ (không xoá)',
}
SHOT_THEO_LOAI = {
    'ai': ['ref', 'anchor', 'gen', 'workflow'],
    '3d': ['layout', 'anim', 'render'],
    'motion': ['design', 'comp'],
    'live': ['plate', 'audio_set', 'notes'],
    'screen': ['capture', 'cut'],
}
COT_SHOT = ['sq', 'sh', 'ma_shot', 'loai', 'tc_vao', 'tc_ra', 'giay', 'boi_canh_LOC', 'nhan_vat_CHR', 'dao_cu_PRP',
            'anh_dau_K', 'anh_cuoi_K', 'noi_voi_shot_truoc', 'chuyen_canh', 'hieu_ung', 'chu_tren_hinh', 'sfx',
            'model_cong_cu', 'phien_ban_dung', 'trang_thai', 'ghi_chu']
RE_SQ = re.compile(r'^SQ\d{3}(_[A-Za-z0-9]+)?$')
RE_SH = re.compile(r'^SH\d{3}(_[A-Za-z0-9]+)?$')
RE_VER = re.compile(r'_v(\d+)\b')

def mk(*p):
    d = os.path.join(*p); os.makedirs(d, exist_ok=True); return d

def ghi(path, text):
    if os.path.exists(path): return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig' if path.endswith('.csv') else 'utf-8', newline='') as f: f.write(text)
    return True

def tao(a):
    goc = mk(a.goc, f'{a.ma}_{a.ten}')
    for gd, subs in GIAI_DOAN.items():
        mk(goc, gd)
        for s in subs: mk(goc, gd, *s.split('/'))
        ghi(os.path.join(goc, gd, '_README.md'), f'# {gd}\n\n{MO_TA[gd]}\n')
    w, h = a.kho.split('x')
    pj = {'ma': a.ma, 'ten': a.ten, 'loai': a.loai.split(','), 'kho': {'w': int(w), 'h': int(h)}, 'fps': a.fps,
          'ngay_tao': date.today().isoformat(), 'phien_ban_hien_tai': 'v001',
          'luat': {'buoc_so_shot': 10, 'chu_so_phien_ban': 3, 'hieu_ung_toi_da_moi_phim': 2},
          'mau_ten': '{MA}_{SQ}_{SH}_{congdoan}_v{NNN}.{ext}'}
    ghi(os.path.join(goc, '00_ADMIN', 'project.json'), json.dumps(pj, ensure_ascii=False, indent=2))
    ghi(os.path.join(goc, '02_PREPRO', '01_Storyboard', f'SHOT_LIST_{a.ma}.csv'), ';'.join(COT_SHOT) + '\n')
    ghi(os.path.join(goc, '02_PREPRO', '01_Storyboard', f'CHUOI_ANH_DAU_CUOI_{a.ma}.md'),
        '# Chuỗi Cảnh → Shot → Ảnh đầu / cuối\n\nẢnh chốt đánh số theo cảnh `SQxxx_Knn`. Shot `SQxxx_SHxxx` = `Kaa → Kbb`. '
        'Cùng mạch (cùng nhân vật, bối cảnh, máy liền): shot sau bắt đầu bằng ĐÚNG ảnh cuối shot trước (chung mã K). '
        'Cắt trong cảnh: K mới + lý do. Đổi cảnh: đánh lại K01 + chuyển cảnh đã chọn trong bảng hiệu ứng.\n\n'
        '| Cảnh | Shot | Ảnh đầu → ảnh cuối | Nối với shot trước | Chuyển cảnh |\n|---|---|---|---|---|\n')
    ghi(os.path.join(goc, '05_REVIEW', f'GHI_CHU_DUYET_{a.ma}.csv'), 'ngay;nguoi;shot;thoi_diem;noi_dung;quyet_dinh;sua_o_ban;trang_thai\n')
    ghi(os.path.join(goc, '06_DELIVERY', '06_QC', 'QC_CHECKLIST.md'),
        '# QC trước khi giao FINAL\n\n- [ ] Số khung = tổng storyboard\n- [ ] Khổ, fps, codec đúng project.json\n'
        '- [ ] Tiếng: tích hợp −14 LUFS (web) / −23 LUFS (phát sóng), đỉnh ≤ −1 dBTP\n- [ ] Không khung đen / khung trắng lạc ở chỗ nối\n'
        '- [ ] Chữ không cắt mép, không lỗi dấu tiếng Việt\n- [ ] Bảng kiểm hiệu ứng: không mục nào > 2 lần (hoặc có lý do)\n'
        '- [ ] Bản quyền nhạc, font, logo đã ghi trong 00_ADMIN/02_Ban_quyen\n- [ ] Người duyệt + ngày ghi vào 06_DELIVERY/04_FINAL/FINAL_NOTE.md\n')
    ghi(os.path.join(goc, '00_MUC_LUC.md'), '# ' + f'{a.ma} · {a.ten}\n\n' + '\n'.join(f'- `{k}` — {v}' for k, v in MO_TA.items()) + '\n')
    tool = os.path.abspath(__file__)
    ghi(os.path.join(goc, '07_PIPELINE', '02_Script', 'tao_du_an_phim.py'), open(tool, encoding='utf-8').read())
    print('Tao xong:', goc)

def shot(a):
    goc = a.du_an
    pj = json.load(open(os.path.join(goc, '00_ADMIN', 'project.json'), encoding='utf-8'))
    sq = a.sq if not a.ten_canh else f"{a.sq.split('_')[0]}_{a.ten_canh}"
    if not RE_SQ.match(sq) or not RE_SH.match(a.sh): sys.exit('Sai mau: SQ 3 chu so (SQ010), SH 3 chu so (SH010)')
    loai = (a.loai or pj['loai'][0]).split(',')
    for l in loai:
        for s in SHOT_THEO_LOAI.get(l, []): mk(goc, '03_PRODUCTION', sq, a.sh, s)
    print('Them shot:', sq, a.sh, loai)

def kiem(a):
    goc = a.du_an; loi = []; canh = []
    for gd in GIAI_DOAN:
        if not os.path.isdir(os.path.join(goc, gd)): loi.append(f'THIEU thu muc {gd}')
    if not os.path.isfile(os.path.join(goc, '00_ADMIN', 'project.json')): loi.append('THIEU 00_ADMIN/project.json')
    prod = os.path.join(goc, '03_PRODUCTION')
    if os.path.isdir(prod):
        for sq in sorted(os.listdir(prod)):
            p = os.path.join(prod, sq)
            if not os.path.isdir(p) or sq.startswith('_'): continue
            if not RE_SQ.match(sq): loi.append(f'TEN CANH sai mau: {sq}')
            for sh in sorted(os.listdir(p)):
                if os.path.isdir(os.path.join(p, sh)) and not RE_SH.match(sh): loi.append(f'TEN SHOT sai mau: {sq}/{sh}')
    for dp, dn, fn in os.walk(goc):
        if '99_ARCHIVE' in dp or '/.' in dp.replace('\\', '/'): continue
        if not dn and not fn: canh.append('Thu muc rong: ' + os.path.relpath(dp, goc))
        for f in fn:
            m = RE_VER.search(f)
            if m and len(m.group(1)) != 3: canh.append(f'Phien ban khong 3 chu so: {os.path.relpath(os.path.join(dp, f), goc)}')
    sl = [os.path.join(dp, f) for dp, _, fn in os.walk(os.path.join(goc, '02_PREPRO')) for f in fn if f.startswith('SHOT_LIST') and f.endswith('.csv')]
    for s in sl:
        rows = list(csv.DictReader(open(s, encoding='utf-8-sig'), delimiter=';'))
        dem = {}
        for r in rows:
            for k in ('chuyen_canh', 'hieu_ung'):
                for e in filter(None, (x.strip() for x in (r.get(k) or '').split(','))):
                    dem[e] = dem.get(e, 0) + 1
        for e, n in sorted(dem.items(), key=lambda x: -x[1]):
            if n > 2: loi.append(f'HIEU UNG lap {n} lan (> 2): {e}')
    print('\n'.join(['== LOI =='] + (loi or ['khong co']) + ['== CANH BAO =='] + (canh[:60] or ['khong co'])))
    sys.exit(1 if loi else 0)

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sp = ap.add_subparsers(dest='lenh', required=True)
p = sp.add_parser('tao'); p.add_argument('goc'); p.add_argument('ma'); p.add_argument('ten')
p.add_argument('--loai', default='ai'); p.add_argument('--kho', default='1920x1080'); p.add_argument('--fps', type=int, default=24)
p = sp.add_parser('shot'); p.add_argument('du_an'); p.add_argument('sq'); p.add_argument('sh'); p.add_argument('--loai'); p.add_argument('--ten-canh')
p = sp.add_parser('kiem'); p.add_argument('du_an')
a = ap.parse_args(); {'tao': tao, 'shot': shot, 'kiem': kiem}[a.lenh](a)
