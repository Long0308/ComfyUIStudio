"""Build NEWTECONS IMAGE 8 STEP v004 (ComfyUI UI format), offline. v001..v003 stay untouched.

v004 = v003 +
  * group "00 CHỌN LUỒNG" before 01: LOCAL (Flux2/Krea2 on RTX 5080) vs CODEX LAN GPT (cloud, not local GPU).
    The Codex branch is the node "Codex OAuth Image Lane (cloud GPT — not local GPU)" of pack codex_lane_bridge
    when /object_info has it; otherwise a labelled placeholder LoadImage (engine copies land in input/codex-lane/).
  * junction "ẢNH TẠO RA" (core ComfySwitchNode, lazy) in 07: switch=true -> local step 06 image,
    switch=false -> Codex image. 07 save/preview, and 09, read the junction, so every step after generation
    works for either route.
  * step 06 fix: v002/v003 wire step 05's MUTED VAEDecode into a REQUIRED VAEEncode.pixels (the frontend drops
    the link, the server refuses 06/07; found by validate_live's mute rule). v004 feeds it through a switch:
    true -> step 05 (needs ControlNet weights, still muted), false (default) -> a ĐIỀN LoadImage.
  * group "09 DUYỆT & UPSCALE" after 08: source = approved file (default) | 08 result | 07 junction, via two
    switches; PreviewImage VÀO; RealESRGAN_x4plus -> ImageScale (lanczos, width 0 = keep aspect) to
    1080x1440 / 1536x2048 / 2880x3840 for 3:4 stills -> SaveImage NEWTECONS/upscale/{1080,2K,4K};
    2K/4K muted by default. Approval is recorded by the ENGINE (jjv images approve), never by ComfyUI.

Why switches and not file hand-off only: ComfySwitchNode's sides are optional + lazy (measured in
comfy_extras/nodes_logic.py, ComfyUI 0.41.0): the unselected side is not executed, and when it is muted the
frontend deletes it from the prompt (measured: graphToPrompt on frontend 1.55.17), so a muted branch never
breaks a REQUIRED input downstream. ComfySoftSwitchNode is not registered on this server (GET /object_info).

Mode changes are DATA: graph.extra.newtecons_route_plan lists, per choice, which node ids are muted, which are
restored (with their default mode) and which switch values are set. The step-UI extension only applies that
data; tests apply every combination (2 routes x 3 sources x 3 targets) and run validate_live.check on each.

ComfySwitchNode is not in object_info_cache.json (frozen measurement); its live schema is kept in
object_info_extra.json (own provenance; --refresh-extra re-fetches it with GET only).
Never calls POST /prompt, never touches the GPU, never overwrites a file.

Usage:  python -I image_8step_build_v004.py OUTPUT.json [--input-dir DIR]
        python -I image_8step_build_v004.py --refresh-extra [--url http://127.0.0.1:8188]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent


def _load(module: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, HERE / (module + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


v003 = _load('image_8step_build_v003', 'image_8step_v003_for_v004')
oi = v003.oi
validate = _load('validate_live', 'comfy_layout_validate_live_v004')

SLOT = 1360  # GROUP_W 1200 + GROUP_GAP 160
GROUP_W = 1200
MUTE, BYPASS = 2, 4
EXTRA_CLASSES = ('ComfySwitchNode',)
CODEX_DISPLAY = 'Codex OAuth Image Lane (cloud GPT — not local GPU)'
CODEX_PACK = 'codex_lane_bridge'
ROUTE_GROUP = '00 CHỌN LUỒNG'
APPROVE_GROUP = '09 DUYỆT & UPSCALE'
LOCAL_GEN_GROUPS = ('02 ASSET 4 GÓC', '02B THAM CHIẾU FACE/POSE', '03 3D', '05 CONTROLNET', '06 KHOÁ ASSET')
TARGETS = (('1080', 1440, '1080×1440'), ('2K', 2048, '1536×2048'), ('4K', 3840, '2880×3840'))
UPSCALE_MODEL = 'RealESRGAN_x4plus.pth'
JJV = 'python -I .agents/skills/studio-video-engine/bin/jjv.py'
APPROVE_CMD = ('jjv images approve --episode <EPISODE> --out <IMAGES_OUT> --library-out <LIBRARY_DIR> '
               '--prompt-id <PROMPT_ID> --sha <sha> --reviewer <user> --scope <SCOPE>')
CODEX_WIDGET_OVERRIDES: dict = {}  # count stays the node default 10 (coordinator 31/10); each Run spends quota per image
ROUTE_LABELS = {'local': 'LOCAL — Flux2/Krea2 trên RTX 5080',
                'codex': 'CODEX LAN GPT — cloud, không phải GPU local'}

HELP_00 = (
    'CHỌN LUỒNG TẠO ẢNH trước bước 01. Bấm tab 00 trên thanh bước → 1 trong 2 nút lớn.\n'
    '• LOCAL — Flux2/Krea2 trên RTX 5080: bước 02/02B/06 chạy, nhánh Codex TẮT (mute). Nút "ẢNH TẠO RA" ở 07 = ảnh bước 06.\n'
    '• CODEX LAN GPT — cloud, KHÔNG phải GPU local: node Codex chạy, các node tạo ảnh local (02, 02B, 03, 05, 06) TẮT. '
    '"ẢNH TẠO RA" ở 07 = ảnh Codex.\n'
    '• Sau bước tạo ảnh (07 lưu, 08 sửa góc, 09 duyệt & upscale) dùng chung cho cả 2 luồng.\n'
    '• Lựa chọn lưu trong workflow (extra.newtecons_route); banner tab 01 hiện luồng đang chọn.\n'
    '• Làm tay không có bảng bước: mute/unmute đúng các node trong extra.newtecons_route_plan và đổi '
    'switch "ẢNH TẠO RA" (true = LOCAL).')
CODEX_WAIT = (
    'CHỜ NODE — "' + CODEX_DISPLAY + '" (pack ' + CODEX_PACK + ', lane BRIDGE).\n'
    'ĐO 31/10 (GET /object_info): node này CHƯA có trên server. Giữ chỗ: LoadImage bên dưới đọc ảnh mà bridge '
    '(jjv bridge serve, POST /v1/images/codex) chép vào input/codex-lane/<job_id>/. '
    'Đây là ảnh cloud GPT (Codex OAuth), có receipt engine; KHÔNG phải GPU local.\n'
    'Khi node có trên server: build lại bằng image_8step_build_v004.py — builder tự thay chỗ giữ bằng node thật.\n'
    'Lưu ý: combo LoadImage của frontend chỉ liệt kê file ở thư mục gốc input/; giá trị codex-lane/... server '
    'nhận (VALIDATE_INPUTS) nhưng frontend có thể tô đỏ.')
CODEX_LIVE = (
    'NODE THẬT — "' + CODEX_DISPLAY + '" (pack ' + CODEX_PACK + '). Cloud GPT qua Codex OAuth, KHÔNG phải GPU '
    'local. Prompt nối từ node PROMPT bước 01. Ảnh có receipt engine (provider codex-exec).\n'
    '• count = 10 (mặc định node, chốt điều phối 31/10): MỖI LẦN RUN TỐN QUOTA ChatGPT cho 10 ảnh — giảm count khi chỉ thử.\n'
    '• Cần bridge trên máy host đang chạy (jjv bridge serve, 127.0.0.1:8797) — node gọi bridge, bridge chạy '
    'codex-exec trên các lane account được phép.\n'
    '• kind (SHOT/FACE/ACTION/ASSET/SET/FIX; FACE/ACTION khoá 3:4 — prompt phải có "3:4" đúng 1 lần) / episode / '
    'ref_role giữ mặc định của node — ĐIỀN theo việc. refs (IMAGE, tuỳ chọn, ≤ 8 ảnh) chưa nối. '
    'Hợp đồng: custom_nodes/codex_lane_bridge/NODE-CONTRACT.md.')
HELP_09 = (
    'INPUT → ảnh cuối: FILE ĐÃ DUYỆT (mặc định) | kết quả bước 08 | "ẢNH TẠO RA" bước 07.\n'
    'OUTPUT → ảnh upscale theo ĐÍCH: 1080 (1080×1440) · 2K (1536×2048) · 4K (2880×3840) cho ảnh tĩnh 3:4 dọc.\n'
    'THAO TÁC → tab 09: chọn NGUỒN + ĐÍCH (bảng bước đổi mute/switch cho đúng), Run. 2K/4K mặc định TẮT (mute).\n'
    'ĐÍCH tính theo CHIỀU CAO (ImageScale width 0 = giữ tỉ lệ): ảnh ngang sẽ ra rộng hơn số ghi.\n'
    'DUYỆT không làm trong ComfyUI: ComfyUI không ghi được approval của engine.')
APPROVE_NOTE = (
    'DUYỆT = ENGINE ghi, ComfyUI không ghi được. Lệnh (jjv = ' + JJV + '):\n'
    + APPROVE_CMD + '\n'
    '• --sha: sha256 của file ảnh (≥ 8 ký tự hex). Nút "Ghi duyệt (engine)" ở tab 09 tự tính sha của ảnh VÀO '
    'và chép lệnh — không gửi gì lên engine (bridge 31/10 không có endpoint approve).\n'
    '• Engine chỉ duyệt ảnh CÓ receipt (take trong library, vd. ảnh Codex) và khi checklist '
    '`jjv images compare` đã pass mọi mục. Ảnh do ComfyUI tạo (08, luồng LOCAL) chưa có receipt engine ⇒ '
    'approve sẽ từ chối cho tới khi được nhận vào engine.\n'
    '• Ví dụ (CHƯA chạy): pilot CHAR_01 --library-out production-local/engine/staging/newtecons-30s/pilot-r005g/library '
    '--prompt-id CHAR_01_ACTION_01_FRONT_FULL_BODY_r005g_v3 --sha e4a81961f88e61ea320c494e8657857cc99525d465d78e8c6b30304097d88be9')
UPSCALE_NOTE = ('RealESRGAN x4 cho ảnh tĩnh, chưa nghiệm thu chất lượng NEWTECONS — cần xem kết quả.\n'
                'ĐO 31/10 (GET /object_info): UpscaleModelLoader chỉ có 1 lựa chọn ' + UPSCALE_MODEL + '. '
                'x4 rồi ImageScale lanczos xuống đích; với ảnh nguồn ~1086×1448, đích 1080 thực chất là thu nhỏ '
                '(chỉ thêm độ nét của RealESRGAN). Không dùng cho video (video 864×480 tới khi H3 ổn).')
TOGGLE_08 = ('Bước 08 (Krea2 sửa trong mask, GPU local) TẮT mặc định ở CẢ 2 luồng — để Run ở luồng CODEX không nạp Krea2.\n'
             'Bật: tab 08 → SỬA GÓC: BẬT (khi đã chọn ảnh cần sửa + mask), hoặc tab 09 → NGUỒN = BƯỚC 08. '
             'Tắt lại: SỬA GÓC: TẮT — nguồn nối dây của 09 tự về bước 07.')
FIX_06 = ('SỬA v004: bản v002/v003 nối VAEDecode bước 05 (đang MUTE) vào pixels BẮT BUỘC của VAEEncode bước 06 ⇒ '
          'frontend bỏ dây, server từ chối 06/07. Nay qua switch: true = ảnh bước 05 (cần weights ControlNet, vẫn '
          'TẮT), false (mặc định) = LoadImage ĐIỀN ảnh đúng dáng (render pose/depth hoặc ảnh dáng đã duyệt).')


def refresh_extra(url: str, path: Path = validate.EXTRA_SCHEMA) -> dict:
    """GET /object_info, keep EXTRA_CLASSES, write object_info_extra.json with provenance (GET only)."""
    raw = urlopen(url.rstrip('/') + '/object_info', timeout=60).read()  # noqa: S310 - local server
    full = json.loads(raw.decode('utf-8'))
    stats = oi.get_json(url.rstrip('/') + '/system_stats')
    missing = [c for c in EXTRA_CLASSES if c not in full]
    if missing:
        raise ValueError('not on the server: %s' % missing)
    kept = list(EXTRA_CLASSES) + ([codex_class(full)] if codex_class(full) else [])
    doc = {'provenance': {'url': url.rstrip('/') + '/object_info',
                          'fetched_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                          'comfyui_version': stats.get('system', {}).get('comfyui_version'),
                          'full_response_sha256': hashlib.sha256(raw).hexdigest(), 'full_class_count': len(full),
                          'kept_classes': kept,
                          'note': 'Classes missing from object_info_cache.json; GET only.'},
           'nodes': {c: full[c] for c in kept}}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return doc


def codex_class(info: dict) -> str | None:
    hits = [k for k, v in info.items() if v.get('display_name') == CODEX_DISPLAY
            or CODEX_PACK in str(v.get('python_module', ''))]
    return sorted(hits)[0] if hits else None


def _node(graph, info, kind, title, widgets, mode, pos, size=None):
    return v003._node(graph, info, kind, title, widgets, mode, pos, size)


def _note(graph, info, title, text, pos, width=1140):
    return v003._note(graph, info, title, text, pos, width)


def _switch(graph: dict, info: dict, title: str, value: bool, pos, mode: int = 0) -> dict:
    """ComfySwitchNode saved like frontend 1.55.17 does once wired: MATCHTYPE ports carry IMAGE."""
    node = _node(graph, info, 'ComfySwitchNode', title, [bool(value)], mode, pos, [340, 110])
    for port in node['inputs']:
        if port['type'] == validate.MATCHTYPE:
            port['type'] = 'IMAGE'
    for out in node['outputs']:
        out['type'] = 'IMAGE'
    return node


def _src(graph: dict, dst: dict, in_name: str) -> dict:
    lid = next(p['link'] for p in dst['inputs'] if p['name'] == in_name)
    sid = next(l[1] for l in graph['links'] if l[0] == lid)
    return next(n for n in graph['nodes'] if n['id'] == sid)


def _group(graph: dict, title: str) -> dict:
    return next(g for g in graph['groups'] if g['title'] == title)


def _inside(node: dict, box: list) -> bool:
    return box[0] <= node['pos'][0] < box[0] + box[2] and box[1] <= node['pos'][1] < box[1] + box[3]


def _members(graph: dict, title: str) -> list:
    box = _group(graph, title)['bounding']
    return [n for n in graph['nodes'] if _inside(n, box)]


def _bottom(nodes: list) -> float:
    return max((n['pos'][1] + n['size'][1] for n in nodes), default=0)


def _add_route_group(graph: dict, info: dict, p1: dict) -> dict:
    x0, x1 = 30, 430
    help_note = _note(graph, info, 'HƯỚNG DẪN — ' + ROUTE_GROUP, HELP_00, (x0, 110))
    y = 110 + help_note['size'][1] + 80
    local = _note(graph, info, 'LUỒNG A — ' + ROUTE_LABELS['local'],
                  'Mặc định. Tạo ảnh bằng model local: FLUX.2 Klein 4B (bước 02/06), sửa Krea2 (bước 08), '
                  'upscale RealESRGAN (bước 09). Không có node cloud/partner (--disable-partner-nodes).', (x0, y))
    y += local['size'][1] + 80
    real = codex_class(info)
    if real:
        note = _note(graph, info, 'LUỒNG B — ' + ROUTE_LABELS['codex'], CODEX_LIVE, (x0, y))
        y += note['size'][1] + 80
        live = info[real]
        widgets = [CODEX_WIDGET_OVERRIDES.get(s['name'], s['default'])
                   for s in oi.walk_widgets(live, lambda s: s['default'])]
        codex = _node(graph, info, real, 'CODEX LAN GPT — cloud, không phải GPU local', widgets, MUTE,
                      (x0, y), [400, 360])
        names = {p['name'] for p in codex['inputs']}
        if 'prompt' in names:
            v003._link(graph, p1, 'STRING', codex, 'prompt')
        out = next(o['name'] for o in codex['outputs'] if o['type'] == 'IMAGE')
        return {'nodes': [codex], 'out': (codex, out), 'kind': 'node:' + real}
    note = _note(graph, info, 'LUỒNG B — ' + ROUTE_LABELS['codex'] + ' — CHỜ NODE', CODEX_WAIT, (x0, y))
    y += note['size'][1] + 80
    hold = _node(graph, info, 'LoadImage', 'GIỮ CHỖ CODEX — ĐIỀN ảnh từ input/codex-lane/<job_id>/ (cloud GPT)',
                 ['', 'image'], MUTE, (x0, y), [340, 400])
    view = _node(graph, info, 'PreviewImage', 'Xem ảnh Codex (giữ chỗ)', [], MUTE, (x1, y), [340, 400])
    v003._link(graph, hold, 'IMAGE', view, 'images')
    return {'nodes': [hold, view], 'out': (hold, 'IMAGE'), 'kind': 'placeholder:LoadImage codex-lane/'}


def _fix_step06(graph: dict, info: dict) -> list:
    e6b = v003._find(graph, 'VAEEncode', 'Mã hoá ảnh đúng dáng (bước 05)')
    d5 = v003._find(graph, 'VAEDecode', 'Giải mã ảnh đúng dáng')
    box = _group(graph, '06 KHOÁ ASSET')['bounding']
    y = _bottom(_members(graph, '06 KHOÁ ASSET')) + 80
    x0, x1 = box[0] + 30, box[0] + 430
    note = _note(graph, info, 'SỬA v004 — đầu vào "ảnh đúng dáng"', FIX_06, (x0, y))
    y += note['size'][1] + 80
    load = _node(graph, info, 'LoadImage', 'ĐIỀN: ảnh đúng dáng (render pose/depth hoặc ảnh dáng đã duyệt)',
                 ['', 'image'], 0, (x0, y), [340, 400])
    sw = _switch(graph, info, 'ẢNH ĐÚNG DÁNG — true: bước 05 (TẮT) / false: file', False, (x1, y))
    v003._unlink(graph, d5, e6b, 'pixels')
    v003._link(graph, d5, 'IMAGE', sw, 'on_true')
    v003._link(graph, load, 'IMAGE', sw, 'on_false')
    v003._link(graph, sw, 'output', e6b, 'pixels')
    return [note, load, sw]


def _junction07(graph: dict, info: dict, codex_out) -> dict:
    s7 = v003._find(graph, 'SaveImage', 'Lưu 1 take (pose p × góc g) — chưa nghiệm thu')
    pv7 = v003._find(graph, 'PreviewImage', 'Xem take vừa tạo')
    d6 = _src(graph, s7, 'images')
    box = _group(graph, '07 9 ẢNH')['bounding']
    y = s7['pos'][1]
    jn = _switch(graph, info, 'ẢNH TẠO RA — true: LOCAL (bước 06) / false: CODEX', True, (box[0] + 30, y))
    s7['pos'] = [box[0] + 430, y]
    pv7['pos'] = [box[0] + 830, y]
    for dst, port in ((s7, 'images'), (pv7, 'images')):
        v003._unlink(graph, d6, dst, port)
        v003._link(graph, jn, 'output', dst, port)
    v003._link(graph, d6, 'IMAGE', jn, 'on_true')
    v003._link(graph, codex_out[0], codex_out[1], jn, 'on_false')
    return jn


def _add_approve_group(graph: dict, info: dict, x: int, jn: dict) -> dict:
    cm8 = v003._find(graph, 'ImageCompositeMasked', 'Giữ nguyên mọi pixel ngoài mask')
    x0, x1, x2 = x + 30, x + 430, x + 830
    help_note = _note(graph, info, 'HƯỚNG DẪN — ' + APPROVE_GROUP, HELP_09, (x0, 110))
    y = 110 + help_note['size'][1] + 80
    appr = _note(graph, info, 'DUYỆT (engine) — lệnh ghi duyệt', APPROVE_NOTE, (x0, y))
    y += appr['size'][1] + 80
    load = _node(graph, info, 'LoadImage', 'NGUỒN FILE — ĐIỀN: ảnh cuối ĐÃ DUYỆT (sha) trong input/',
                 ['', 'image'], 0, (x0, y), [340, 400])
    wire = _switch(graph, info, 'NGUỒN NỐI DÂY — true: bước 08 / false: bước 07', False, (x0, y + 480), MUTE)
    pick = _switch(graph, info, 'NGUỒN 09 — true: FILE ĐÃ DUYỆT / false: NỐI DÂY 08-07', True, (x1, y))
    vao = _node(graph, info, 'PreviewImage', 'VÀO — ảnh sẽ duyệt / upscale', [], 0, (x2, y), [340, 400])
    v003._link(graph, cm8, 'IMAGE', wire, 'on_true')
    v003._link(graph, jn, 'output', wire, 'on_false')
    v003._link(graph, load, 'IMAGE', pick, 'on_true')
    v003._link(graph, wire, 'output', pick, 'on_false')
    v003._link(graph, pick, 'output', vao, 'images')
    y2 = y + 480 + 190
    model = _node(graph, info, 'UpscaleModelLoader', 'RealESRGAN x4 (model upscale duy nhất trên server)',
                  [UPSCALE_MODEL], 0, (x0, y2), [340, 90])
    up = _node(graph, info, 'ImageUpscaleWithModel', 'Upscale x4 (GPU)', [], 0, (x1, y + 190), [340, 90])
    v003._link(graph, model, 'UPSCALE_MODEL', up, 'upscale_model')
    v003._link(graph, pick, 'output', up, 'image')
    targets = {}
    ty = y + 480
    for code, height, label in TARGETS:
        mode = 0 if code == '1080' else MUTE
        scale = _node(graph, info, 'ImageScale', 'ĐÍCH %s — %s (cao %d, rộng theo tỉ lệ)%s'
                      % (code, label, height, '' if mode == 0 else ' — TẮT'),
                      ['lanczos', 0, height, 'disabled'], mode, (x1, ty), [340, 170])
        save = _node(graph, info, 'SaveImage', 'LƯU %s — chưa nghiệm thu%s' % (code, '' if mode == 0 else ' — TẮT'),
                     ['NEWTECONS/upscale/' + code], mode, (x2, ty), [340, 330])
        v003._link(graph, up, 'IMAGE', scale, 'image')
        v003._link(graph, scale, 'IMAGE', save, 'images')
        targets[code] = (scale, save)
        ty += 380
    _note(graph, info, 'CHƯA NGHIỆM THU — upscale', UPSCALE_NOTE, (x0, ty + 40))
    return {'load': load, 'wire': wire, 'pick': pick, 'vao': vao, 'targets': targets}


def _plan(route_local: list, codex_nodes: list, jn: dict, g9: dict, defaults: dict, fix08: list) -> dict:
    ids = lambda nodes: [n['id'] for n in nodes]  # noqa: E731
    restore = lambda nodes: {str(n['id']): defaults[n['id']] for n in nodes}  # noqa: E731
    targets = g9['targets']
    return {
        'version': 1,
        'note': 'Applied by custom_nodes/newtecons_step_ui: mute = mode 2 (current mode saved in '
                'properties.nt_mode_saved), restore = saved mode or the default given here, switches = '
                'ComfySwitchNode widget value. Every combination is validated by tests.',
        'route': {'default': 'local', 'extra_key': 'newtecons_route', 'options': {
            'local': {'label': ROUTE_LABELS['local'], 'mute': ids(codex_nodes), 'restore': restore(route_local),
                      'switches': {str(jn['id']): True}},
            'codex': {'label': ROUTE_LABELS['codex'], 'mute': ids(route_local), 'restore': restore(codex_nodes),
                      'switches': {str(jn['id']): False}}}},
        'source09': {'default': 'file', 'options': {
            'file': {'label': 'FILE ĐÃ DUYỆT', 'mute': [g9['wire']['id']], 'restore': restore([g9['load']]),
                     'switches': {str(g9['pick']['id']): True}},
            '08': {'label': 'BƯỚC 08 SỬA GÓC', 'mute': [g9['load']['id']],
                   'restore': {str(g9['wire']['id']): 0, **restore(fix08)},  # source 08 turns step 08 on
                   'switches': {str(g9['pick']['id']): False, str(g9['wire']['id']): True}},
            '07': {'label': 'BƯỚC 07 ẢNH TẠO RA', 'mute': [g9['load']['id']], 'restore': {str(g9['wire']['id']): 0},
                   'switches': {str(g9['pick']['id']): False, str(g9['wire']['id']): False}}}},
        'fix08': {'default': 'off', 'options': {  # critic CR-V004-ROUTE: 08 (Krea2, local GPU) is opt-in on both routes
            'off': {'label': 'TẮT', 'mute': ids(fix08), 'restore': {},
                    'switches': {str(g9['wire']['id']): False}},  # 09 wire falls back to 07 when 08 is skipped
            'on': {'label': 'BẬT', 'mute': [], 'restore': restore(fix08), 'switches': {}}}},
        'target09': {'default': '1080', 'options': {
            code: {'label': code, 'prefix': 'NEWTECONS/upscale/' + code,
                   'mute': [n['id'] for c, pair in targets.items() if c != code for n in pair],
                   'restore': {str(n['id']): 0 for n in targets[code]}, 'switches': {}}
            for code in targets}},
    }


def build(info: dict, input_dir: Path | None = None) -> dict:
    graph = v003.build(info, input_dir)
    for n in graph['nodes']:
        n['pos'][0] += SLOT
    for g in graph['groups']:
        g['bounding'][0] += SLOT
    height = graph['groups'][0]['bounding'][3]
    graph['groups'].insert(0, {'title': ROUTE_GROUP, 'bounding': [0, 0, GROUP_W, height], 'color': '#0A2540',
                               'font_size': 28, 'flags': {}})
    p1 = v003._find(graph, 'PrimitiveStringMultiline', 'ĐIỀN: PROMPT NEWTECONS live-action')
    route_note = v003._find(graph, 'Note', 'ĐƯỜNG CHẠY — LAN GPT (Codex OAuth) vs ComfyUI local')
    route_note['widgets_values'] = [v003.ROUTE_TEXT + '\nv004: chọn luồng ở bước 00 CHỌN LUỒNG (LOCAL / CODEX LAN GPT).']
    codex = _add_route_group(graph, info, p1)
    _fix_step06(graph, info)
    jn = _junction07(graph, info, codex['out'])
    x9 = max(g['bounding'][0] for g in graph['groups']) + SLOT
    g9 = _add_approve_group(graph, info, x9, jn)
    graph['groups'].append({'title': APPROVE_GROUP, 'bounding': [x9, 0, GROUP_W, height], 'color': '#3E8914',
                            'font_size': 28, 'flags': {}})
    box08 = _group(graph, '08 SỬA GÓC')['bounding']
    fix08 = [n for n in _members(graph, '08 SỬA GÓC') if n['type'] not in validate.NOTE_TYPES]
    _note(graph, info, 'v004 — BƯỚC 08 TẮT MẶC ĐỊNH (cả 2 luồng)', TOGGLE_08,
          (box08[0] + 30, _bottom(_members(graph, '08 SỬA GÓC')) + 80))
    height = max(height, _bottom(graph['nodes']) + 60)
    for g in graph['groups']:
        g['bounding'][3] = height
    encoders01 = [n for n in _members(graph, '01 PROMPT') if n['type'] not in validate.NOTE_TYPES and n['id'] != p1['id']]
    local = encoders01 + [n for title in LOCAL_GEN_GROUPS for n in _members(graph, title)
                          if n['type'] not in validate.NOTE_TYPES]
    defaults = {n['id']: n.get('mode', 0) for n in graph['nodes']}
    for n in codex['nodes'] + fix08:
        defaults[n['id']] = 0  # active default of the Codex branch / step 08 when chosen
    for n in fix08:
        n['mode'] = MUTE  # step 08 is opt-in (fix08=off)
    order = {n['id']: i for i, n in enumerate(sorted(graph['nodes'], key=lambda n: (n['pos'][0], n['pos'][1])))}
    for n in graph['nodes']:
        n['order'] = order[n['id']]
    graph['extra']['newtecons_route'] = 'local'
    graph['extra']['newtecons_route_plan'] = _plan(local, codex['nodes'], jn, g9, defaults, fix08)
    meta = graph['extra']['newtecons_image_8step']
    meta['supersedes'] = 'NEWTECONS_IMAGE_8STEP_v003_grouped.json (kept, not overwritten)'
    meta['codex_branch'] = codex['kind']
    meta['fixed_in_v004'] = ['step 06 VAEEncode.pixels was fed by muted step-05 VAEDecode (mute rule)',
                             'CR-V004-ROUTE: step 08 (Krea2 local GPU) stayed active on the CODEX route -> fix08 toggle, '
                             'default off; group 01 text encoders muted on CODEX']
    meta['object_info_extra'] = {'file': validate.EXTRA_SCHEMA.name, 'classes': list(EXTRA_CLASSES),
                                 'sha256': hashlib.sha256(validate.EXTRA_SCHEMA.read_bytes()).hexdigest()
                                 if validate.EXTRA_SCHEMA.is_file() else None}
    graph['extra']['workflow_metadata'] = {
        'title': 'NEWTECONS IMAGE 8 STEP v004 — 00 CHỌN LUỒNG + 09 DUYỆT & UPSCALE, template, chưa qualified',
        'version': 4}
    return graph


def apply_choice(graph: dict, dimension: str, option: str) -> dict:
    """Python mirror of the extension's plan application (tests only): returns a new graph."""
    import copy
    out = copy.deepcopy(graph)
    entry = out['extra']['newtecons_route_plan'][dimension]['options'][option]
    nodes = {n['id']: n for n in out['nodes']}
    for nid in entry['mute']:
        node = nodes[nid]
        if node.get('mode', 0) != MUTE:
            node.setdefault('properties', {})['nt_mode_saved'] = node.get('mode', 0)
        node['mode'] = MUTE
    for nid, default in entry['restore'].items():
        node = nodes[int(nid)]
        node['mode'] = node.get('properties', {}).pop('nt_mode_saved', default)
    for nid, value in entry['switches'].items():
        nodes[int(nid)]['widgets_values'][0] = bool(value)
    if dimension == 'route':
        out['extra']['newtecons_route'] = option
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('output', type=Path, nargs='?')
    p.add_argument('--input-dir', type=Path, default=validate.DEFAULT_INPUT_DIR)
    p.add_argument('--refresh-extra', action='store_true', help='re-fetch object_info_extra.json (GET only)')
    p.add_argument('--url', default=oi.DEFAULT_URL)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        if a.refresh_extra:
            doc = refresh_extra(a.url)
            print(json.dumps(doc['provenance'], ensure_ascii=False))
            return 0
        if a.output is None:
            raise ValueError('OUTPUT.json required')
        info = validate.load_cache_with_extra()
        if info is None or 'ComfySwitchNode' not in info:
            raise ValueError('object_info cache or object_info_extra.json (ComfySwitchNode) missing')
        graph = build(info, a.input_dir)
        report = validate.check(graph, info, a.input_dir)
        if not report['ok']:
            raise ValueError('live validation failed: %s' % report['errors'])
        payload = json.dumps(graph, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        with a.output.open('x', encoding='utf-8', newline='\n') as stream:  # refuse overwrite
            stream.write(payload)
        print(json.dumps({'output': str(a.output), 'nodes': len(graph['nodes']), 'links': len(graph['links']),
                          'groups': [g['title'] for g in graph['groups']], 'modes': report['modes'],
                          'codex_branch': graph['extra']['newtecons_image_8step']['codex_branch'],
                          'validation_warnings': len(report['warnings']),
                          'sha256': hashlib.sha256(a.output.read_bytes()).hexdigest()}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        print('REFUSED: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
