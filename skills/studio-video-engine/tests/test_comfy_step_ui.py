"""Offline checks for the NEWTECONS step UI additions (image v003, VALIDATE_INPUTS rule, assets).

Uses tools/comfy_layout/object_info_cache.json (GET /object_info, ComfyUI 0.41.0) and tmp dirs.
No ComfyUI server call, no GPU.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
TOOL_DIR = ENGINE / 'tools' / 'comfy_layout'


def _load(name, alias):
    spec = importlib.util.spec_from_file_location(alias, TOOL_DIR / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate = _load('validate_live.py', 'step_ui_validate')
v003 = _load('image_8step_build_v003.py', 'step_ui_image_v003')
assets = _load('step_ui_assets.py', 'step_ui_assets')
REF_VALUES = (v003.FACE_VALUE, v003.POSE_VALUE)


@pytest.fixture
def info():
    cache = v003.oi.load_cache()
    assert cache is not None, 'object_info_cache.json missing'
    return cache


@pytest.fixture
def input_dir(tmp_path):
    for value in REF_VALUES:
        target = tmp_path / value
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'ref:' + value.encode())
    return tmp_path


@pytest.fixture
def graph(info, input_dir):
    return v003.build(info, input_dir)


def _by_title(graph, title):
    return next(n for n in graph['nodes'] if n.get('title') == title)


V003_MUTE_DEFECT = ("55(VAEEncode) required input pixels is fed by MUTED node 50(VAEDecode) 'Giải mã ảnh đúng dáng'")


def test_v003_valid_only_because_reference_files_exist(graph, info, input_dir, tmp_path_factory):
    report = validate.check(graph, info, input_dir)
    # v003 is kept as shipped: its only error is the step-06 mute defect (fixed in v004), found by the mute rule
    assert len(report['errors']) == 1 and report['errors'][0].startswith(V003_MUTE_DEFECT), report['errors']
    assert validate.selftest(graph, info) == []
    accepted = [w for w in report['warnings'] if 'VALIDATE_INPUTS' in w]
    assert len(accepted) == 2
    without = validate.check(graph, info)  # rule off: the same values are errors
    assert not without['ok'] and len(without['errors']) == 3
    empty = tmp_path_factory.mktemp('empty_input')
    missing = validate.check(graph, info, empty)  # rule on, files absent: still errors
    assert not missing['ok'] and all('newtecons_ref_' in e or e.startswith(V003_MUTE_DEFECT) for e in missing['errors'])
    assert sum('newtecons_ref_' in e for e in missing['errors']) == 2


def test_rule_limited_to_loadimage_and_inside_input_dir(input_dir, graph, info):
    assert not validate.file_in_input_dir('../outside.png', input_dir)
    (input_dir / 'reference-library' / 'face').mkdir(parents=True)
    assert not validate.file_in_input_dir('reference-library/face', input_dir)  # a directory, not a file
    assert not validate.file_in_input_dir(REF_VALUES[0], None)
    broken = copy.deepcopy(graph)
    prim = next(n for n in broken['nodes'] if n['type'] == 'UNETLoader')
    prim['widgets_values'][0] = REF_VALUES[0]  # a real file, but UNETLoader is combo-validated
    assert not validate.check(broken, info, input_dir)['ok']


def test_v003_groups_and_02b_membership(graph):
    titles = [g['title'] for g in graph['groups']]
    assert titles == ['01 PROMPT', '02 ASSET 4 GÓC', '02B THAM CHIẾU FACE/POSE', '03 3D', '04 SET 3D 3×3',
                      '05 CONTROLNET', '06 KHOÁ ASSET', '07 9 ẢNH', '08 SỬA GÓC']
    xs = [g['bounding'][0] for g in graph['groups']]
    assert xs == sorted(xs) and len(set(xs)) == len(xs)
    g02b = graph['groups'][2]['bounding']
    inside = [n for n in graph['nodes']
              if g02b[0] <= n['pos'][0] < g02b[0] + g02b[2] and g02b[1] <= n['pos'][1] < g02b[1] + g02b[3]]
    kinds = sorted(n['type'] for n in inside)
    assert kinds.count('LoadImage') == 2 and kinds.count('ReferenceLatent') == 4 and kinds.count('PreviewImage') == 2
    for n in inside:  # every 02B node fits inside the group box
        assert n['pos'][0] + n['size'][0] <= g02b[0] + g02b[2]
        assert n['pos'][1] + n['size'][1] <= g02b[1] + g02b[3]
    loads = {n['widgets_values'][0] for n in inside if n['type'] == 'LoadImage'}
    assert loads == set(REF_VALUES)


def _collapse_bypass(graph):
    """Edges (src_title, dst_title, dst_input) after removing mode-4 nodes like the frontend does
    (a bypassed node forwards its first input of the output's type)."""
    nodes = {n['id']: n for n in graph['nodes']}
    links = {l[0]: l for l in graph['links']}

    def resolve(src_id, slot):
        node = nodes[src_id]
        while node.get('mode') == 4:
            kind = node['outputs'][slot]['type']
            port = next(p for p in node['inputs'] if p['type'] == kind and p.get('link') is not None)
            link = links[port['link']]
            node, slot = nodes[link[1]], link[2]
        return node

    edges = set()
    for lid, src, slot, dst, d_slot, _ in graph['links']:
        if nodes[dst].get('mode') == 4:
            continue
        edges.add((resolve(src, slot)['title'], nodes[dst]['title'], nodes[dst]['inputs'][d_slot]['name']))
    return edges


def test_v003_default_bypass_equals_v002_flow(graph, info):
    bypassed = [n for n in graph['nodes'] if n.get('mode') == 4]
    assert len(bypassed) == 4 and all(n['type'] == 'ReferenceLatent' for n in bypassed)
    muted = {n['title'] for n in graph['nodes'] if n.get('mode') == 2 and n['type'] == 'VAEEncode'}
    assert muted == {'Mã hoá mặt — TẮT (mute)', 'Mã hoá dáng — TẮT (mute)'}
    assert all(not validate.bypass_errors(n) for n in bypassed)
    v2 = v003.v002.build(info)
    v2_edges = _collapse_bypass(v2)
    v3_edges = _collapse_bypass(graph)
    new_titles = {n['title'] for n in graph['nodes']} - {n['title'] for n in v2['nodes']}
    assert {e for e in v3_edges if e[0] not in new_titles and e[1] not in new_titles} == v2_edges
    assert ('Tham chiếu → điều kiện dương', 'Guider cfg 1.0', 'positive') in v3_edges
    assert ('Tham chiếu → điều kiện âm', 'Guider cfg 1.0', 'negative') in v3_edges


def test_v003_enabled_chain_reaches_guider(graph):
    guider = next(n for n in graph['nodes'] if n['type'] == 'CFGGuider'
                  and any(p['name'] == 'positive' and p['link'] for p in n['inputs']))
    links = {l[0]: l for l in graph['links']}
    nodes = {n['id']: n for n in graph['nodes']}
    pos = next(p for p in guider['inputs'] if p['name'] == 'positive')
    chain, node = [], nodes[links[pos['link']][1]]
    while node['type'] == 'ReferenceLatent':
        chain.append(node['title'])
        node = nodes[links[next(p for p in node['inputs'] if p['name'] == 'conditioning')['link']][1]]
    assert chain == ['Dáng → điều kiện dương — TẮT (bypass, thử nghiệm)', 'Mặt → điều kiện dương — TẮT (bypass)',
                     'Tham chiếu → điều kiện dương']


def test_route_note_and_metadata(graph, input_dir):
    route = _by_title(graph, 'ĐƯỜNG CHẠY — LAN GPT (Codex OAuth) vs ComfyUI local')
    assert 'chạy ngoài ComfyUI qua jjv' in route['widgets_values'][0]
    meta = graph['extra']['newtecons_image_8step']
    assert meta['domain'] == 'newtecons_live_action'
    want = {v: hashlib.sha256((input_dir / v).read_bytes()).hexdigest() for v in REF_VALUES}
    assert {r['loadimage_value']: r['sha256'] for r in meta['reference_inputs']} == want
    limits = _by_title(graph, 'GIỚI HẠN — đọc trước khi bật')['widgets_values'][0]
    assert 'control_net_name 0 lựa chọn' in limits and 'KHÔNG giả vờ' in limits


def test_builder_refuses_overwrite(tmp_path, input_dir):
    out = tmp_path / 'v003.json'
    out.write_text('keep', encoding='utf-8')
    assert v003.main([str(out), '--input-dir', str(input_dir)]) == 1
    assert out.read_text(encoding='utf-8') == 'keep'


def test_copy_exclusive_never_overwrites(tmp_path):
    src = tmp_path / 'a.png'
    src.write_bytes(b'one')
    dst = tmp_path / 'in' / 'a.png'
    assert assets.copy_exclusive(src, dst) == 'copied'
    assert assets.copy_exclusive(src, dst) == 'identical'
    src.write_bytes(b'two')
    with pytest.raises(ValueError):
        assets.copy_exclusive(src, dst)
    assert dst.read_bytes() == b'one' and src.exists()


def test_engine_library_manifest_hash_bound(tmp_path):
    pil = pytest.importorskip('PIL.Image')
    lib = tmp_path / 'lib'
    (lib / 'CHAR_01' / 'FACE').mkdir(parents=True)
    png = lib / 'CHAR_01' / 'FACE' / '02_01_NEUTRAL__abc.png'
    pil.new('RGB', (1024, 768), (10, 37, 64)).save(png)
    receipt = tmp_path / 'r.json'
    receipt.write_text(json.dumps({'provider': 'codex-exec', 'route': 'codex-exec',
                                   'domain': 'newtecons_live_action', 'status': 'ok'}), encoding='utf-8')
    sha = hashlib.sha256(png.read_bytes()).hexdigest()
    (lib / 'INDEX.json').write_text(json.dumps({'characters': {'CHAR_01': {'FACE': [
        {'file': 'CHAR_01/FACE/02_01_NEUTRAL__abc.png', 'sha256': sha, 'receipt': str(receipt), 'rev': 'r005d'}]}},
        'current_revs': {}}), encoding='utf-8')
    manifest = assets.build_engine_library(lib, tmp_path / 'input')
    item = manifest['items'][0]
    assert manifest['count'] == 1 and manifest['sha_mismatches'] == 0 and manifest['providers'] == ['codex-exec']
    thumb = tmp_path / 'input' / item['subfolder'] / item['filename']
    assert hashlib.sha256(thumb.read_bytes()).hexdigest() == item['thumb_sha256']
    assert max(pil.open(thumb).size) == assets.THUMB_MAX and png.exists()
    assert assets.build_engine_library(lib, tmp_path / 'input')['items'][0]['thumb_state'] == 'identical'
    png.write_bytes(png.read_bytes() + b'x')  # source drift vs INDEX sha is reported, not hidden
    assert assets.build_engine_library(lib, tmp_path / 'input')['sha_mismatches'] == 1
    pil.new('RGB', (1024, 768), (200, 0, 0)).save(png)  # different pixels: old thumbnail never overwritten
    with pytest.raises(ValueError):
        assets.build_engine_library(lib, tmp_path / 'input')
