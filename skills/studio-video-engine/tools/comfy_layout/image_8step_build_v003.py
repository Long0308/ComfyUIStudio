"""Build NEWTECONS IMAGE 8 STEP v003 (ComfyUI UI format), offline. v001/v002 stay untouched.

v003 = v002 + group "02B THAM CHIẾU FACE/POSE" (inserted after 02; groups 03..08 move one
slot right) + a route note in 01. 02B holds LoadImage nodes for an internal face reference
and an internal pose (manikin) reference, copied by step_ui_assets.py into
input/reference-library/ AND top-level input/newtecons_ref_* (the frontend's LoadImage combo lists
only top-level files and marks subfolder values as errors, measured on frontend 1.55.17). They are wired into step 02's FLUX.2 Klein ReferenceLatent chain:

    02 cond(+/-) -> ReferenceLatent(face) -> ReferenceLatent(pose) -> 02 CFGGuider(+/-)

Both ReferenceLatent pairs are BYPASSED (mode 4, CONDITIONING passes through) and their VAEEncode
nodes are MUTED (mode 2: no LATENT input to pass through; critic CR-V003) by default, so v003
behaves exactly like v002 until a user enables them for a NEW female character. Enabling them
for an approved character would mix identities, the note says so. ControlNet weights are 0,
so no pose control is claimed. Krea2 (step 08) edits ONE source image; references are not
wired there.

Every node is built from live INPUT_TYPES (object_info_cache.json) and the graph must pass
validate_live.check() with the ComfyUI input dir (LoadImage subfolder values must exist)
before it is written with exclusive create. Never calls POST /prompt, never touches the GPU.

Usage:  python -I image_8step_build_v003.py OUTPUT.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def _load(module: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, HERE / (module + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


v002 = _load('image_8step_build_v002', 'image_8step_v002_for_v003')
oi = v002.oi
validate = _load('validate_live', 'comfy_layout_validate_live_v003')

SLOT = 1360  # GROUP_W 1200 + GROUP_GAP 160 (image_8step_build.py layout constants)
GROUP_X = 2720  # 02B takes the slot that 03 had
GROUP_TITLE = '02B THAM CHIẾU FACE/POSE'
GROUP_COLOR = '#0B4FD9'
FACE_VALUE = 'newtecons_ref_face_f01d89535c5.webp'  # top-level copy of reference-library/face/…
POSE_VALUE = 'newtecons_ref_pose_full_single_P017_front.png'  # copy of reference-library/pose/…
BYPASS = 4
MUTE = 2
ROUTE_TEXT = ('Ảnh tạo bằng LAN GPT (Codex OAuth) chạy ngoài ComfyUI qua jjv; ComfyUI chỉ chạy model local '
              '(Flux2/Krea2/H3 trên RTX 5080).\n'
              'Lệnh engine: jjv images ... --provider codex-exec (toàn bộ ảnh r005f đến từ đường này, '
              'receipt provider=codex-exec). Không có node cloud/partner trong graph này '
              '(container chạy --disable-partner-nodes).')
HELP_02B = (
    'Ảnh tham chiếu NỘI BỘ cho nhân vật nữ MỚI (chưa có ảnh đã duyệt).\n'
    '• Mặt: LoadImage newtecons_ref_face_… (bản sao của input/reference-library/face/…) — CC0, người AI hư cấu; chỉ có thumbnail 200×250 (độ phân giải thấp).\n'
    '• Dáng: LoadImage newtecons_ref_pose_… (bản sao của input/reference-library/pose/…) — manikin nét vẽ từ pose-db-01; user cho GIỮ dùng nội bộ (31/10). '
    'Cấm phân phối lại / commit / đăng.\n'
    '• Nối: điều kiện ± của bước 02 → ReferenceLatent mặt → ReferenceLatent dáng → CFGGuider bước 02.\n'
    '• MẶC ĐỊNH TẮT: 2 ReferenceLatent BYPASS (tím), VAEEncode MUTE (xám). Bật mặt (hoặc dáng): chọn VAEEncode → '
    'Ctrl+M, chọn 2 ReferenceLatent → Ctrl+B.\n'
    '• KHÔNG bật khi làm asset cho nhân vật ĐÃ DUYỆT — sẽ trộn danh tính.\n'
    '• 2 PreviewImage chỉ để xem tham chiếu (không tốn GPU).')
LIMITS_02B = (
    'ĐO 31/10 (GET /object_info, ComfyUI 0.41.0): ReferenceLatent nhận (conditioning, latent) ⇒ chuỗi nhiều '
    'tham chiếu hợp lệ về KIỂU. FLUX.2 Klein KHÔNG có điều khiển dáng: ReferenceLatent chỉ là tham chiếu ảnh — '
    'model có thể chép luôn nét vẽ manikin thay vì chỉ lấy dáng. CHƯA CHẠY THỬ, chưa đo chất lượng.\n'
    'ControlNet: ControlNetLoader có trên server nhưng control_net_name 0 lựa chọn (thiếu weights) ⇒ bước 05 '
    'vẫn TẮT; ở đây KHÔNG giả vờ có pose control.\n'
    'Krea2 (bước 08) sửa MỘT ảnh nguồn — không nối tham chiếu mặt/dáng vào đó.')


def _node(graph: dict, info: dict, kind: str, title: str, widgets, mode: int, pos, size=None) -> dict:
    node = v002.make_node(info, kind, title, widgets, mode, size)
    node['id'] = graph['last_node_id'] + 1
    graph['last_node_id'] = node['id']
    node['pos'] = [pos[0], pos[1]]
    graph['nodes'].append(node)
    return node


def _note(graph: dict, info: dict, title: str, text: str, pos, width: int = 1140) -> dict:
    return _node(graph, info, 'Note', title, [text], 0, pos, v002.v001.note_size(text, width))


def _link(graph: dict, src: dict, out_name: str, dst: dict, in_name: str) -> int:
    s = next(i for i, o in enumerate(src['outputs']) if o['name'] == out_name)
    d = next(i for i, p in enumerate(dst['inputs']) if p['name'] == in_name)
    kind = src['outputs'][s]['type']
    if not oi.type_accepts(dst['inputs'][d]['type'], kind):
        raise ValueError('type mismatch %s.%s -> %s.%s' % (src['title'], out_name, dst['title'], in_name))
    if dst['inputs'][d]['link'] is not None:
        raise ValueError('input already linked: %s.%s' % (dst['title'], in_name))
    lid = graph['last_link_id'] + 1
    graph['last_link_id'] = lid
    graph['links'].append([lid, src['id'], s, dst['id'], d, kind])
    src['outputs'][s]['links'].append(lid)
    dst['inputs'][d]['link'] = lid
    return lid


def _unlink(graph: dict, src: dict, dst: dict, in_name: str) -> None:
    d = next(i for i, p in enumerate(dst['inputs']) if p['name'] == in_name)
    lid = dst['inputs'][d]['link']
    link = next(l for l in graph['links'] if l[0] == lid)
    if link[1] != src['id']:
        raise ValueError('%s.%s is not fed by %s' % (dst['title'], in_name, src['title']))
    graph['links'].remove(link)
    src['outputs'][link[2]]['links'].remove(lid)
    dst['inputs'][d]['link'] = None


def _find(graph: dict, kind: str, title: str) -> dict:
    hits = [n for n in graph['nodes'] if n['type'] == kind and n.get('title') == title]
    if len(hits) != 1:
        raise ValueError('expected one %s %r, found %d' % (kind, title, len(hits)))
    return hits[0]


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def build(info: dict, input_dir: Path | None = None) -> dict:
    graph = v002.build(info)
    for n in graph['nodes']:
        if n['pos'][0] >= GROUP_X:
            n['pos'][0] += SLOT
    for g in graph['groups']:
        if g['bounding'][0] >= GROUP_X:
            g['bounding'][0] += SLOT
    height = graph['groups'][0]['bounding'][3]
    graph['groups'].insert(2, {'title': GROUP_TITLE, 'bounding': [GROUP_X, 0, 1200, height],
                               'color': GROUP_COLOR, 'font_size': 28, 'flags': {}})

    rl_pos = _find(graph, 'ReferenceLatent', 'Tham chiếu → điều kiện dương')
    rl_neg = _find(graph, 'ReferenceLatent', 'Tham chiếu → điều kiện âm')
    vae = _find(graph, 'VAELoader', 'VAE FLUX.2 Klein')
    guider = next(n for n in graph['nodes'] if n['type'] == 'CFGGuider'
                  and any(l[1] == rl_pos['id'] and l[3] == n['id'] for l in graph['links']))

    x0, x1, x2 = GROUP_X + 30, GROUP_X + 430, GROUP_X + 830
    help_note = _note(graph, info, 'HƯỚNG DẪN — ' + GROUP_TITLE, HELP_02B, (x0, 110))
    y = 110 + help_note['size'][1] + 80
    face = _node(graph, info, 'LoadImage', 'THAM CHIẾU MẶT — nội bộ (bản sao reference-library/face)',
                 [FACE_VALUE, 'image'], 0, (x0, y), [340, 400])
    pose = _node(graph, info, 'LoadImage', 'THAM CHIẾU DÁNG — manikin nội bộ (bản sao reference-library/pose)',
                 [POSE_VALUE, 'image'], 0, (x0, y + 480), [340, 400])
    face_px = _node(graph, info, 'ImageScaleToTotalPixels', 'Chuẩn hoá cỡ ảnh mặt', ['lanczos', 1.0, 16], 0,
                    (x1, y))
    face_view = _node(graph, info, 'PreviewImage', 'Xem tham chiếu mặt', [], 0, (x1, y + 150), [340, 280])
    pose_px = _node(graph, info, 'ImageScaleToTotalPixels', 'Chuẩn hoá cỡ ảnh dáng', ['lanczos', 1.0, 16], 0,
                    (x1, y + 480))
    pose_view = _node(graph, info, 'PreviewImage', 'Xem tham chiếu dáng', [], 0, (x1, y + 630), [340, 280])
    face_lat = _node(graph, info, 'VAEEncode', 'Mã hoá mặt — TẮT (mute)', [], MUTE, (x2, y))
    face_rp = _node(graph, info, 'ReferenceLatent', 'Mặt → điều kiện dương — TẮT (bypass)', [], BYPASS,
                    (x2, y + 150))
    face_rn = _node(graph, info, 'ReferenceLatent', 'Mặt → điều kiện âm — TẮT (bypass)', [], BYPASS,
                    (x2, y + 300))
    pose_lat = _node(graph, info, 'VAEEncode', 'Mã hoá dáng — TẮT (mute)', [], MUTE, (x2, y + 480))
    pose_rp = _node(graph, info, 'ReferenceLatent', 'Dáng → điều kiện dương — TẮT (bypass, thử nghiệm)', [],
                    BYPASS, (x2, y + 630))
    pose_rn = _node(graph, info, 'ReferenceLatent', 'Dáng → điều kiện âm — TẮT (bypass, thử nghiệm)', [],
                    BYPASS, (x2, y + 780))
    _note(graph, info, 'GIỚI HẠN — đọc trước khi bật', LIMITS_02B, (x0, y + 980))

    _link(graph, face, 'IMAGE', face_px, 'image')
    _link(graph, face, 'IMAGE', face_view, 'images')
    _link(graph, pose, 'IMAGE', pose_px, 'image')
    _link(graph, pose, 'IMAGE', pose_view, 'images')
    for px, lat in ((face_px, face_lat), (pose_px, pose_lat)):
        _link(graph, px, 'IMAGE', lat, 'pixels')
        _link(graph, vae, 'VAE', lat, 'vae')
    _unlink(graph, rl_pos, guider, 'positive')
    _unlink(graph, rl_neg, guider, 'negative')
    for head, f_rl, p_rl, port in ((rl_pos, face_rp, pose_rp, 'positive'), (rl_neg, face_rn, pose_rn, 'negative')):
        _link(graph, head, 'CONDITIONING', f_rl, 'conditioning')
        _link(graph, face_lat, 'LATENT', f_rl, 'latent')
        _link(graph, f_rl, 'CONDITIONING', p_rl, 'conditioning')
        _link(graph, pose_lat, 'LATENT', p_rl, 'latent')
        _link(graph, p_rl, 'CONDITIONING', guider, port)

    _note(graph, info, 'ĐƯỜNG CHẠY — LAN GPT (Codex OAuth) vs ComfyUI local', ROUTE_TEXT, (430, 1100), 740)

    order = {n['id']: i for i, n in enumerate(sorted(graph['nodes'], key=lambda n: (n['pos'][0], n['pos'][1])))}
    for n in graph['nodes']:
        n['order'] = order[n['id']]
    meta = graph['extra']['newtecons_image_8step']
    meta['supersedes'] = 'NEWTECONS_IMAGE_8STEP_v002_grouped.json (kept, not overwritten)'
    meta['bypassed_by_default'] = [n['title'] for n in (face_rp, face_rn, pose_rp, pose_rn)]
    meta['muted_by_default_02b'] = [n['title'] for n in (face_lat, pose_lat)]
    meta['reference_inputs'] = [
        {'loadimage_value': v, 'sha256': _sha(input_dir / v) if input_dir else None} for v in (FACE_VALUE, POSE_VALUE)]
    meta['step_ui_extension'] = 'custom_nodes/newtecons_step_ui (tab bar + VÀO/RA panel)'
    graph['extra']['workflow_metadata'] = {
        'title': 'NEWTECONS IMAGE 8 STEP v003 — template, chưa chạy, chưa qualified', 'version': 3}
    return graph


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('output', type=Path)
    p.add_argument('--input-dir', type=Path, default=validate.DEFAULT_INPUT_DIR)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        info = oi.load_cache()
        if info is None:
            raise ValueError('object_info_cache.json missing')
        graph = build(info, a.input_dir)
        report = validate.check(graph, info, a.input_dir)
        if not report['ok']:
            raise ValueError('live validation failed: %s' % report['errors'])
        payload = json.dumps(graph, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        with a.output.open('x', encoding='utf-8', newline='\n') as stream:  # refuse overwrite
            stream.write(payload)
        print(json.dumps({'output': str(a.output), 'nodes': len(graph['nodes']), 'links': len(graph['links']),
                          'groups': [g['title'] for g in graph['groups']], 'modes': report['modes'],
                          'validation_warnings': len(report['warnings']),
                          'sha256': hashlib.sha256(a.output.read_bytes()).hexdigest()}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        print('REFUSED: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
