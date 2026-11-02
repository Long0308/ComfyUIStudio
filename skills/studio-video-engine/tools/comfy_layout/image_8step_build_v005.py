"""Build NEWTECONS IMAGE 8 STEP v005 (ComfyUI UI format), offline. v001..v004 stay untouched.

v005 = v004 + group "02A NEO TRANG PHỤC" right after 01 (user 31/10: every NEWTECONS workflow anchors wardrobe,
by context CÔNG TRƯỜNG / VĂN PHÒNG; company wardrobe upload; optional scene reference):
  * NEO 1..N: LoadImage slots filled per context from the presets JSON
    custom_nodes/newtecons_step_ui/web/data/wardrobe/newtecons_live_action.json (schema jjv/wardrobe-presets/v1,
    written by another lane: contexts.<ctx> = [{name, file, sha256, role}], files under input/newtecons-wardrobe/).
    N = the largest context. NEO 1 is REQUIRED (image1 of the first stitch): with no presets it stays '' and the
    server refuses every generation output (blank LoadImage = 'Invalid image file') — the Run block. NEO 2..N are
    the optional image2 of the next stitches; a context with k refs mutes NEO k+1..N.
  * UPLOAD TRANG PHỤC CÔNG TY and BỐI CẢNH THAM CHIẾU: optional LoadImages, MUTED until the user enables them.
  * Every slot is stitched (core ImageStitch, aspect kept; measured frontend 1.55.17 drops a muted optional image2)
    into ONE reference sheet that feeds BOTH routes:
      CODEX -> CodexOAuthImageLane.refs (ref_role 'wardrobe');
      LOCAL -> ImageScaleToTotalPixels -> VAEEncode -> ReferenceLatent (+/-) before the CFGGuider of step 02 and of
               step 06 (06 makes the 07 images). Those nodes are local-route nodes (muted on CODEX).
  * plan dimensions: wardrobe (one option per presets context; sets NEO files + mutes unused slots, extra key
    newtecons_wardrobe_context), upload (off|on), boicanh (off|on). They only touch the slot LoadImages, never the
    route lists, so every combination stays valid (tests apply all of them).
  * extra.newtecons_wardrobe marks the graph; validate_live's wardrobe rule then requires every active generator
    (CodexOAuthImageLane, SamplerCustomAdvanced) to have an active REQUIRED anchor upstream, and reports
    wardrobe_blocked when it is blank.

Never calls POST /prompt, never touches the GPU, never overwrites a file.
Usage:  python -I image_8step_build_v005.py OUTPUT.json [OUTPUT2.json ...] [--presets PATH]
        python -I image_8step_build_v005.py --refresh-extra
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


v004 = _load('image_8step_build_v004', 'image_8step_v004_for_v005')
v003 = v004.v003
oi = v004.oi
validate = v004.validate

SLOT = v004.SLOT
MUTE = v004.MUTE
GROUP = '02A NEO TRANG PHỤC'
EXTRA_V005 = HERE / 'object_info_extra_v005.json'
EXTRA_CLASSES_V005 = ('ImageStitch',)
CODEX_SCHEMA = HERE / 'codex_lane_bridge_schema_v005.json'  # derived from the pack (restart pending)
CHARACTERS = (HERE.parents[4] / 'production-local' / 'ComfyUI' / 'custom_nodes' / 'newtecons_step_ui' / 'web' / 'data'
              / 'characters' / 'newtecons_live_action.json')
CHARACTER_IDS = tuple('CHAR_%02d' % i for i in range(1, 9))
MIN_FACE, MIN_POSE = 2, 2
MAX_FACE, MAX_POSE = 3, 2  # one ~1 MP reference sheet: more tiles = each face too small (judgment, 31/10)
HELP_02B_V005 = (
    'v005 — THAM CHIẾU = ẢNH CỦA CHÍNH NHÂN VẬT ĐANG CHỌN (user 31/10: không đưa ảnh người lạ).\n'
    '• Chọn CHAR_01..CHAR_08 ở tab 02B: ô MẶT ← ảnh FACE trong library của nhân vật, ô DÁNG ← ảnh ACTION toàn thân '
    '(data/characters/newtecons_live_action.json).\n'
    '• Ô MẶT 1 / DÁNG 1 TRỐNG = chưa có ảnh nhân vật ⇒ server từ chối Run luồng LOCAL. KHÔNG tự lấy ảnh reference-library.\n'
    '• MẪU TẠO NHÂN VẬT MỚI (mặt reference-library + manikin) chỉ là tuỳ chọn, mặc định TẮT; bật ở tab 02B.\n'
    '• CODEX: hợp đồng node — refs THAY bộ neo trang phục, nên ảnh nhân vật KHÔNG gửi sang Codex.')
PRESETS = (HERE.parents[4] / 'production-local' / 'ComfyUI' / 'custom_nodes' / 'newtecons_step_ui' / 'web' / 'data'
           / 'wardrobe' / 'newtecons_live_action.json')
CONTEXT_LABELS = {'cong_truong': 'CÔNG TRƯỜNG', 'van_phong': 'VĂN PHÒNG'}
FALLBACK_CONTEXTS = ('cong_truong', 'van_phong')
MIN_SLOTS = 2
STITCH = ['right', True, 16, 'white']
HELP_02A = (
    'NEO TRANG PHỤC — bắt buộc cho mọi ảnh NEWTECONS (user 31/10), cả 2 luồng.\n'
    '• Bối cảnh: CÔNG TRƯỜNG / VĂN PHÒNG / VĂN PHÒNG — VEST — bấm ở tab 02A; NEO 1..N tự điền từ bộ neo '
    'data/wardrobe/newtecons_live_action.json (file trong input/newtecons-wardrobe/).\n'
    '• NEO 1 TRỐNG = server từ chối Run (Invalid image file) — chưa có bộ neo thì không chạy được.\n'
    '• UPLOAD TRANG PHỤC CÔNG TY / BỐI CẢNH THAM CHIẾU: tuỳ chọn, mặc định TẮT — bật ở tab 02A sau khi chọn file.\n'
    '• Ghép 1 TẤM THAM CHIẾU (ImageStitch, giữ tỉ lệ) → CODEX: refs của node Codex (ref_role wardrobe); '
    'LOCAL: ReferenceLatent trước guider bước 02 và bước 06.')
LIMITS_02A = (
    'CHƯA ĐO CHẤT LƯỢNG: FLUX.2 Klein nhận tấm ghép như 1 ảnh và thu về ~1 MP — với 7 ảnh neo, mỗi ô chỉ còn vài '
    'trăm px (lưới áo rất mịn có thể mất); model có thể chép bố cục tấm ghép. GPT (Codex) nhận tấm ghép làm 1 ref. '
    'Bối cảnh tham chiếu nằm cùng tấm với trang phục. Chưa chạy GPU với nhánh này.\n'
    'Node Codex chưa có widget bối cảnh — bối cảnh chỉ đi qua tấm ref + prompt. Combo LoadImage của frontend chỉ '
    'liệt kê file gốc input/: giá trị newtecons-wardrobe/... server nhận (VALIDATE_INPUTS) nhưng frontend có thể tô đỏ.')


def refresh_extra_v005(url: str) -> dict:
    raw = urlopen(url.rstrip('/') + '/object_info', timeout=60).read()  # noqa: S310 - local server, GET only
    full = json.loads(raw.decode('utf-8'))
    missing = [c for c in EXTRA_CLASSES_V005 if c not in full]
    if missing:
        raise ValueError('not on the server: %s' % missing)
    doc = {'provenance': {'url': url.rstrip('/') + '/object_info',
                          'fetched_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                          'full_response_sha256': hashlib.sha256(raw).hexdigest(), 'full_class_count': len(full),
                          'kept_classes': list(EXTRA_CLASSES_V005), 'note': 'v005 additions; GET only.'},
           'nodes': {c: full[c] for c in EXTRA_CLASSES_V005}}
    EXTRA_V005.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return doc


_STAGE = None


def _stage():
    global _STAGE
    if _STAGE is None:
        _STAGE = _load('stage_toplevel_refs_v005', 'stage_toplevel_refs_v005_for_build')
    return _STAGE


def toplevel(row, input_dir: Path | None, char: str | None = None) -> str:
    """The registry file, or its top-level copy when it exists in input_dir with the registry sha256 (frontend
    1.55.17 lists only top-level files in the LoadImage combo; subfolder values raise its error overlay)."""
    if isinstance(row, str):
        return row
    rel = row.get('file') or row.get('input') or row.get('path') or ''
    digest = row.get('sha256')
    if not (rel and digest and input_dir):
        return rel
    name = _stage().toplevel_name(rel, digest, char)
    target = Path(input_dir) / name
    return name if target.is_file() and _stage().sha(target) == digest else rel


def contexts_of(presets: dict | None) -> list[str]:
    ctx = (presets or {}).get('contexts')
    return list(ctx) if isinstance(ctx, dict) and ctx else list(FALLBACK_CONTEXTS)


def preset_files(presets: dict | None, context: str, input_dir: Path | None = None) -> list[str]:
    """Input-relative files of one context (jjv/wardrobe-presets/v1: a list of {name, file, sha256, role})."""
    rows = ((presets or {}).get('contexts') or {}).get(context) or []
    if isinstance(rows, dict):  # tolerate {refs|slots|files: [...]}
        rows = rows.get('refs') or rows.get('slots') or rows.get('files') or []
    return [v for v in (toplevel(row, input_dir) for row in rows) if v]


def load_presets(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding='utf-8-sig')) if Path(path).is_file() else None


def _group_guider(graph: dict, title: str) -> dict:
    hits = [n for n in v004._members(graph, title) if n['type'] == 'CFGGuider']
    if len(hits) != 1:
        raise ValueError('expected one CFGGuider in %s, found %d' % (title, len(hits)))
    return hits[0]


def _shift_and_insert(graph: dict) -> tuple[int, float]:
    x02 = next(g for g in graph['groups'] if g['title'] == '02 ASSET 4 GÓC')['bounding'][0]
    for n in graph['nodes']:
        if n['pos'][0] >= x02:
            n['pos'][0] += SLOT
    for g in graph['groups']:
        if g['bounding'][0] >= x02:
            g['bounding'][0] += SLOT
    height = graph['groups'][0]['bounding'][3]
    index = next(i for i, g in enumerate(graph['groups']) if g['title'] == '01 PROMPT') + 1
    graph['groups'].insert(index, {'title': GROUP, 'bounding': [x02, 0, v004.GROUP_W, height], 'color': '#134611',
                                   'font_size': 28, 'flags': {}})
    return x02, height


def _slots(graph: dict, info: dict, x02: int, y: int, n_slots: int, first: list) -> dict:
    node, link = v004._node, v003._link
    x0, x1, x2 = x02 + 30, x02 + 430, x02 + 830
    slots = []
    for i in range(n_slots):
        value = first[i] if i < len(first) else ''
        mode = 0 if i == 0 or value else MUTE
        col, row = (x0, i) if i < 4 else (x1, i - 4)
        title = 'NEO %d — %s' % (i + 1, 'BẮT BUỘC (bộ neo theo bối cảnh)' if i == 0 else 'theo bối cảnh')
        slot = node(graph, info, 'LoadImage', title, [value, 'image'], mode, (col, y + row * 330), [340, 290])
        slot['properties']['nt_wardrobe_anchor'] = 'required' if i == 0 else 'context'
        slots.append(slot)
    oy = y + 4 * 330
    upload = node(graph, info, 'LoadImage', 'UPLOAD TRANG PHỤC CÔNG TY — tuỳ chọn (TẮT)', ['', 'image'], MUTE,
                  (x1, oy - 330), [340, 290])
    scene = node(graph, info, 'LoadImage', 'BỐI CẢNH THAM CHIẾU — tuỳ chọn (TẮT)', ['', 'image'], MUTE,
                 (x1, oy), [340, 290])
    upload['properties']['nt_wardrobe_anchor'] = 'optional'
    scene['properties']['nt_wardrobe_anchor'] = 'optional'
    chain, prev, sy = [], slots[0], y
    for i, extra in enumerate(slots[1:] + [upload, scene]):
        last = extra in (upload, scene)
        wv = ['down', True, 16, 'white'] if last else list(STITCH)
        title = ('Ghép + %s (bỏ qua khi TẮT)' % ('UPLOAD' if extra is upload else 'BỐI CẢNH') if last
                 else 'Ghép NEO 1..%d (bỏ qua ô TẮT)' % (i + 2))
        st = node(graph, info, 'ImageStitch', title, wv, 0, (x2, sy), [340, 200])
        sy += 250
        link(graph, prev, 'IMAGE', st, 'image1')
        link(graph, extra, 'IMAGE', st, 'image2')
        chain.append(st)
        prev = st
    return {'slots': slots, 'upload': upload, 'scene': scene, 'chain': chain, 'sheet': prev, 'bottom': max(sy, oy + 330)}


def _local_refs(graph: dict, info: dict, x02: int, y: int, sheet: dict) -> list:
    node, link = v004._node, v003._link
    vae = v003._find(graph, 'VAELoader', 'VAE FLUX.2 Klein')
    scale = node(graph, info, 'ImageScaleToTotalPixels', 'Chuẩn hoá tấm tham chiếu (LOCAL)', ['lanczos', 1.0, 16], 0,
                 (x02 + 30, y), [340, 130])
    enc = node(graph, info, 'VAEEncode', 'Mã hoá tấm tham chiếu (LOCAL)', [], 0, (x02 + 30, y + 180), [340, 70])
    link(graph, sheet, 'IMAGE', scale, 'image')
    link(graph, scale, 'IMAGE', enc, 'pixels')
    link(graph, vae, 'VAE', enc, 'vae')
    out, ry = [scale, enc], y
    for step in ('02 ASSET 4 GÓC', '06 KHOÁ ASSET'):
        guider = _group_guider(graph, step)
        for port in ('positive', 'negative'):
            head = v004._src(graph, guider, port)
            rl = node(graph, info, 'ReferenceLatent', 'NEO trang phục → %s %s (LOCAL)' % (port, step[:2]), [], 0,
                      (x02 + 430, ry), [340, 70])
            ry += 120
            v003._unlink(graph, head, guider, port)
            link(graph, head, 'CONDITIONING', rl, 'conditioning')
            link(graph, enc, 'LATENT', rl, 'latent')
            link(graph, rl, 'CONDITIONING', guider, port)
            out.append(rl)
    return out


def _wardrobe_plan(contexts: list, files: dict, slots: list, default: str) -> dict:
    options = {}
    for key in contexts:
        values = files.get(key, [])
        widgets = {str(s['id']): {'image': values[i] if i < len(values) else ''} for i, s in enumerate(slots)}
        used = [s for i, s in enumerate(slots) if i == 0 or i < len(values)]
        options[key] = {'label': CONTEXT_LABELS.get(key, key.upper()), 'refs': len(values), 'widgets': widgets,
                        'mute': [s['id'] for s in slots if s not in used],
                        'restore': {str(s['id']): 0 for s in used[1:]}, 'switches': {}}
    return {'default': default, 'extra_key': 'newtecons_wardrobe_context',
            'presets': 'custom_nodes/newtecons_step_ui/web/data/wardrobe/' + PRESETS.name, 'options': options}


def load_info_v005() -> dict | None:
    """cache + object_info_extra*.json, then the DERIVED Codex schema (overrides the pre-restart live entry)."""
    info = validate.load_cache_with_extra()
    if info is not None and CODEX_SCHEMA.is_file():
        info = {**info, **json.loads(CODEX_SCHEMA.read_text(encoding='utf-8-sig'))['nodes']}
    return info


def widget_index(node: dict, name: str) -> int:
    names = [q['name'] for q in node['inputs'] if 'widget' in q]
    return names.index(name)


def set_widget(node: dict, name: str, value) -> None:
    node['widgets_values'][widget_index(node, name)] = value


def character_files(characters: dict | None, char: str, input_dir: Path | None = None) -> tuple[list, list]:
    """(FACE files, ACTION files) of one character; tolerant to {characters:{CHAR_xx:{FACE|face:[..], ACTION|action|pose:[..]}}}
    with rows as strings or {file|input|path}. The schema is not fixed yet (another lane writes it)."""
    entry = ((characters or {}).get('characters') or {}).get(char) or {}

    def files(*keys):
        rows = next((entry[k] for k in keys if isinstance(entry.get(k), list)), [])
        return [toplevel(r, input_dir, char) for r in rows if r]
    return [f for f in files('FACE', 'face', 'faces') if f], [f for f in files('ACTION', 'action', 'pose', 'actions') if f]


def _rework_02b(graph: dict, info: dict, characters: dict | None, input_dir: Path | None = None) -> dict:
    node, link, find = v004._node, v003._link, v003._find
    face = find(graph, 'LoadImage', 'THAM CHIẾU MẶT — nội bộ (bản sao reference-library/face)')
    pose = find(graph, 'LoadImage', 'THAM CHIẾU DÁNG — manikin nội bộ (bản sao reference-library/pose)')
    views = [find(graph, 'PreviewImage', 'Xem tham chiếu mặt'), find(graph, 'PreviewImage', 'Xem tham chiếu dáng')]
    face_px, pose_px = find(graph, 'ImageScaleToTotalPixels', 'Chuẩn hoá cỡ ảnh mặt'), find(graph, 'ImageScaleToTotalPixels', 'Chuẩn hoá cỡ ảnh dáng')
    lats = [find(graph, 'VAEEncode', 'Mã hoá mặt — TẮT (mute)'), find(graph, 'VAEEncode', 'Mã hoá dáng — TẮT (mute)')]
    rls = [find(graph, 'ReferenceLatent', t) for t in ('Mặt → điều kiện dương — TẮT (bypass)', 'Mặt → điều kiện âm — TẮT (bypass)',
                                                         'Dáng → điều kiện dương — TẮT (bypass, thử nghiệm)',
                                                         'Dáng → điều kiện âm — TẮT (bypass, thử nghiệm)')]
    face['title'] = 'MẪU TẠO NHÂN VẬT MỚI — mặt reference-library (TẮT)'
    pose['title'] = 'MẪU TẠO NHÂN VẬT MỚI — manikin (TẮT)'
    for n in (face, pose, *views):
        n['mode'] = MUTE
    views[0]['title'], views[1]['title'] = 'Xem MẪU mặt (TẮT)', 'Xem MẪU dáng (TẮT)'
    for n, title in zip(lats + rls, ('Mã hoá MẶT nhân vật', 'Mã hoá DÁNG nhân vật', 'MẶT nhân vật → điều kiện dương',
                                     'MẶT nhân vật → điều kiện âm', 'DÁNG nhân vật → điều kiện dương',
                                     'DÁNG nhân vật → điều kiện âm')):
        n['title'], n['mode'] = title, 0
    box = next(g for g in graph['groups'] if g['title'] == '02B THAM CHIẾU FACE/POSE')['bounding']
    counts = [character_files(characters, c, input_dir) for c in CHARACTER_IDS]
    n_face = min(MAX_FACE, max([MIN_FACE] + [len(f) for f, _ in counts]))
    n_pose = min(MAX_POSE, max([MIN_POSE] + [len(a) for _, a in counts]))
    first_face, first_pose = character_files(characters, CHARACTER_IDS[0], input_dir)
    y = v004._bottom(v004._members(graph, '02B THAM CHIẾU FACE/POSE')) + 80
    note = v004._note(graph, info, 'v005 — ẢNH NHÂN VẬT ĐANG CHỌN (không dùng ảnh người lạ)', HELP_02B_V005, (box[0] + 30, y))
    y += note['size'][1] + 80
    out, col2 = {}, [y]
    for kind, n_slots, first, px, source, col in (('face', n_face, first_face, face_px, face, 0),
                                                  ('pose', n_pose, first_pose, pose_px, pose, 1)):
        x = box[0] + 30 + col * 400
        slots, sy = [], y
        for i in range(n_slots):
            value = first[i] if i < len(first) else ''
            label = 'MẶT' if kind == 'face' else 'DÁNG'
            slot = node(graph, info, 'LoadImage', '%s %d — nhân vật đang chọn%s' % (label, i + 1, ' (BẮT BUỘC)' if i == 0 else ''),
                        [value, 'image'], 0 if i == 0 or value else MUTE, (x, sy), [340, 290])
            slot['properties']['nt_character_slot'] = 'required' if i == 0 else 'optional'
            slots.append(slot)
            sy += 330
        prev = slots[0]
        for extra in slots[1:]:
            st = node(graph, info, 'ImageStitch', 'Ghép %s nhân vật (bỏ qua ô TẮT)' % ('MẶT' if kind == 'face' else 'DÁNG'),
                      ['right', True, 16, 'white'], 0, (box[0] + 830, col2[0]), [340, 200])
            col2[0] += 250
            link(graph, prev, 'IMAGE', st, 'image1')
            link(graph, extra, 'IMAGE', st, 'image2')
            prev = st
        sw = v004._switch(graph, info, '%s — true: MẪU TẠO NHÂN VẬT MỚI / false: ảnh nhân vật' % ('MẶT' if kind == 'face' else 'DÁNG'),
                          False, (box[0] + 830, col2[0]))
        col2[0] += 170
        v003._unlink(graph, source, px, 'image')
        link(graph, source, 'IMAGE', sw, 'on_true')
        link(graph, prev, 'IMAGE', sw, 'on_false')
        link(graph, sw, 'output', px, 'image')
        view = node(graph, info, 'PreviewImage', 'Xem %s nhân vật' % ('MẶT' if kind == 'face' else 'DÁNG'), [], 0,
                    (x, sy), [340, 290])
        link(graph, prev, 'IMAGE', view, 'images')
        out[kind] = {'slots': slots, 'switch': sw, 'view': view, 'source': source}
        y_end = sy + 330
    out['bottom'] = max(y_end, y)
    out['mau'] = [face, pose, *views]
    out['managed'] = lats + rls
    return out


def _character_plan(graph: dict, plan: dict, chars: dict, characters: dict | None, input_dir: Path | None = None) -> None:
    route = plan['route']['options']
    mau_ids = {n['id'] for n in chars['mau']}
    route['codex']['mute'] = [i for i in route['codex']['mute'] if i not in mau_ids]
    route['local']['restore'] = {k: v for k, v in route['local']['restore'].items() if int(k) not in mau_ids}
    for n in chars['managed']:
        route['local']['restore'][str(n['id'])] = 0
    local_new = [chars['face']['switch'], chars['pose']['switch'], chars['face']['view'], chars['pose']['view']]
    route['codex']['mute'] = route['codex']['mute'] + [n['id'] for n in local_new]
    route['local']['restore'] = {**route['local']['restore'], **{str(n['id']): 0 for n in local_new}}
    options = {}
    for char in CHARACTER_IDS:
        faces, poses = character_files(characters, char, input_dir)
        widgets, mute, restore = {}, [], {}
        for kind, values in (('face', faces), ('pose', poses)):
            for i, slot in enumerate(chars[kind]['slots']):
                widgets[str(slot['id'])] = {'image': values[i] if i < len(values) else ''}
                if i == 0:
                    continue
                if i < len(values):
                    restore[str(slot['id'])] = 0
                else:
                    mute.append(slot['id'])
        name = (((characters or {}).get('characters') or {}).get(char) or {}).get('name')
        options[char] = {'label': char + (' ' + name if name else ''), 'faces': len(faces), 'poses': len(poses),
                         'used': [min(len(faces), len(chars['face']['slots'])), min(len(poses), len(chars['pose']['slots']))],
                         'widgets': widgets, 'mute': mute,
                         'restore': restore, 'switches': {}}
    plan['character'] = {'default': CHARACTER_IDS[0], 'extra_key': 'newtecons_character', 'options': options,
                         'source': 'custom_nodes/newtecons_step_ui/web/data/characters/' + CHARACTERS.name}
    sw = sorted({str(chars['face']['switch']['id']), str(chars['pose']['switch']['id'])})  # sorted: byte-deterministic
    plan['mau_moi'] = {'default': 'off', 'label': 'MẪU TẠO NHÂN VẬT MỚI', 'options': {
        'off': {'label': 'TẮT', 'mute': sorted(mau_ids), 'restore': {}, 'switches': {i: False for i in sw}},
        'on': {'label': 'BẬT', 'mute': [], 'restore': {str(i): 0 for i in sorted(mau_ids)}, 'switches': {i: True for i in sw}}}}
    graph['extra']['newtecons_character'] = CHARACTER_IDS[0]
    graph['extra']['newtecons_characters'] = {
        'version': 1, 'source': plan['character']['source'], 'found': characters is not None,
        'slots': [s['id'] for s in chars['face']['slots'] + chars['pose']['slots']],
        'required': [chars['face']['slots'][0]['id'], chars['pose']['slots'][0]['id']], 'optional': [],
        'face': [s['id'] for s in chars['face']['slots']], 'pose': [s['id'] for s in chars['pose']['slots']]}


def build(info: dict, input_dir: Path | None = None, presets: dict | None = None,
          characters: dict | None = None) -> dict:
    graph = v004.build(info, input_dir)
    x02, height = _shift_and_insert(graph)
    contexts = contexts_of(presets)
    default = (presets or {}).get('default_context') if (presets or {}).get('default_context') in contexts else contexts[0]
    files = {c: preset_files(presets, c, input_dir) for c in contexts}
    n_slots = max([MIN_SLOTS] + [len(v) for v in files.values()])
    help_note = v004._note(graph, info, 'HƯỚNG DẪN — ' + GROUP, HELP_02A, (x02 + 30, 110))
    y = 110 + help_note['size'][1] + 80
    w = _slots(graph, info, x02, y, n_slots, files[default])
    view = v004._node(graph, info, 'PreviewImage', 'RA — tấm tham chiếu đính kèm', [], 0,
                      (x02 + 830, w['bottom'] + 40), [340, 400])
    v003._link(graph, w['sheet'], 'IMAGE', view, 'images')
    local = _local_refs(graph, info, x02, w['bottom'] + 40, w['sheet'])
    codex = next((n for n in graph['nodes'] if n['type'] == 'CodexOAuthImageLane'), None)
    codex_ports = {q['name'] for q in codex['inputs']} if codex else set()
    if codex is not None and 'context' in codex_ports:
        # NODE-CONTRACT: non-empty refs REPLACE the bridge's sha-checked preset -> wardrobe goes through `context`
        set_widget(codex, 'context', default)
        if 'company_wardrobe' in codex_ports:
            v003._link(graph, w['upload'], 'IMAGE', codex, 'company_wardrobe')
        if 'scene_ref' in codex_ports:
            v003._link(graph, w['scene'], 'IMAGE', codex, 'scene_ref')
    elif codex is not None:
        v003._link(graph, w['sheet'], 'IMAGE', codex, 'refs')  # pre-preset bridge: refs carry the sheet
    chars = _rework_02b(graph, info, characters, input_dir)
    v004._note(graph, info, 'GIỚI HẠN — chưa nghiệm thu', LIMITS_02A, (x02 + 30, w['bottom'] + 520))

    height = max(height, v004._bottom(graph['nodes']) + 60)
    for g in graph['groups']:
        g['bounding'][3] = height
    order = {n['id']: i for i, n in enumerate(sorted(graph['nodes'], key=lambda n: (n['pos'][0], n['pos'][1])))}
    for n in graph['nodes']:
        n['order'] = order[n['id']]

    plan = graph['extra']['newtecons_route_plan']
    route = plan['route']['options']
    route['codex']['mute'] = route['codex']['mute'] + [n['id'] for n in local]
    route['local']['restore'] = {**route['local']['restore'], **{str(n['id']): 0 for n in local}}
    plan['wardrobe'] = _wardrobe_plan(contexts, files, w['slots'], default)
    if codex is not None and 'context' in codex_ports:
        for key, opt in plan['wardrobe']['options'].items():
            opt['widgets'][str(codex['id'])] = {'context': key}
    _character_plan(graph, plan, chars, characters, input_dir)
    for dim, slot, label in (('upload', w['upload'], 'UPLOAD TRANG PHỤC CÔNG TY'),
                             ('boicanh', w['scene'], 'BỐI CẢNH THAM CHIẾU')):
        plan[dim] = {'default': 'off', 'label': label, 'options': {
            'off': {'label': 'TẮT', 'mute': [slot['id']], 'restore': {}, 'switches': {}},
            'on': {'label': 'BẬT', 'mute': [], 'restore': {str(slot['id']): 0}, 'switches': {}}}}
    graph['extra']['newtecons_wardrobe_context'] = default
    graph['extra']['newtecons_wardrobe'] = {
        'version': 1, 'group': GROUP, 'presets': plan['wardrobe']['presets'], 'presets_found': presets is not None,
        'presets_schema': (presets or {}).get('schema'),
        'slots': [s['id'] for s in w['slots']], 'required': [w['slots'][0]['id']],
        'optional': [w['upload']['id'], w['scene']['id']], 'sheet': w['sheet']['id'], 'preview': view['id'],
        'local_reference_latents': [n['id'] for n in local[2:]]}
    meta = graph['extra']['newtecons_image_8step']
    meta['supersedes'] = 'NEWTECONS_IMAGE_8STEP_v004_grouped.json (kept, not overwritten)'
    meta['object_info_extra_v005'] = {'file': EXTRA_V005.name, 'classes': list(EXTRA_CLASSES_V005),
                                      'sha256': hashlib.sha256(EXTRA_V005.read_bytes()).hexdigest()
                                      if EXTRA_V005.is_file() else None}
    graph['extra']['workflow_metadata'] = {
        'title': 'NEWTECONS Image v005 — + 02A NEO TRANG PHỤC, template, chưa qualified', 'version': 5}
    return graph


def apply_choice(graph: dict, dimension: str, option: str) -> dict:
    """Python mirror of the extension (tests): v004 rule + widget edits + extra keys."""
    out = v004.apply_choice(graph, dimension, option)
    dim = out['extra']['newtecons_route_plan'][dimension]
    nodes = {n['id']: n for n in out['nodes']}
    for nid, widgets in dim['options'][option].get('widgets', {}).items():
        for name, value in widgets.items():
            set_widget(nodes[int(nid)], name, value)
    if dim.get('extra_key'):
        out['extra'][dim['extra_key']] = option
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('outputs', type=Path, nargs='*')
    p.add_argument('--input-dir', type=Path, default=validate.DEFAULT_INPUT_DIR)
    p.add_argument('--presets', type=Path, default=PRESETS)
    p.add_argument('--characters', type=Path, default=CHARACTERS)
    p.add_argument('--refresh-extra', action='store_true')
    p.add_argument('--url', default=oi.DEFAULT_URL)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        if a.refresh_extra:
            print(json.dumps(refresh_extra_v005(a.url)['provenance'], ensure_ascii=False))
            return 0
        if not a.outputs:
            raise ValueError('OUTPUT.json required')
        if any(o.exists() for o in a.outputs):
            raise ValueError('refusing to overwrite: %s' % [str(o) for o in a.outputs if o.exists()])
        info = load_info_v005()
        if info is None or 'ImageStitch' not in info or 'ComfySwitchNode' not in info:
            raise ValueError('object_info cache / sidecars missing (run --refresh-extra)')
        presets = load_presets(a.presets)
        characters = load_presets(a.characters)
        graph = build(info, a.input_dir, presets, characters)
        report = validate.check(graph, info, a.input_dir)
        if not report['ok']:
            raise ValueError('live validation failed: %s' % report['errors'])
        payload = json.dumps(graph, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        shas = []
        for out in a.outputs:
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open('x', encoding='utf-8', newline='\n') as stream:  # refuse overwrite
                stream.write(payload)
            shas.append(hashlib.sha256(out.read_bytes()).hexdigest())
        print(json.dumps({'outputs': [str(o) for o in a.outputs], 'nodes': len(graph['nodes']),
                          'links': len(graph['links']), 'groups': [g['title'] for g in graph['groups']],
                          'modes': report['modes'], 'presets_found': presets is not None,
                          'wardrobe_blocked': report.get('wardrobe_blocked'), 'sha256': shas}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        print('REFUSED: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
