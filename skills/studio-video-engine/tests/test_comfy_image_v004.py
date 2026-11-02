"""Offline checks for NEWTECONS IMAGE 8 STEP v004 (00 CHỌN LUỒNG, 09 DUYỆT & UPSCALE) and the validator's
mute / switch / MATCHTYPE rules.

Schemas: tools/comfy_layout/object_info_cache.json + object_info_extra.json (ComfySwitchNode,
CodexOAuthImageLane; both fetched with GET /object_info from ComfyUI 0.41.0). No server call, no GPU.
"""
import copy
import itertools
import json
from pathlib import Path
import importlib.util

import pytest

ENGINE = Path(__file__).resolve().parents[1]
TOOL_DIR = ENGINE / 'tools' / 'comfy_layout'
SAVED = (ENGINE.parents[2] / 'production-local' / 'ComfyUI' / 'user' / 'default' / 'workflows'
         / 'NEWTECONS_IMAGE_8STEP' / 'NEWTECONS_IMAGE_8STEP_v004r1_grouped.json')


def _load(name, alias):
    spec = importlib.util.spec_from_file_location(alias, TOOL_DIR / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v004 = _load('image_8step_build_v004.py', 'img_v004_test')
validate = v004.validate
GROUPS = ['00 CHỌN LUỒNG', '01 PROMPT', '02 ASSET 4 GÓC', '02B THAM CHIẾU FACE/POSE', '03 3D', '04 SET 3D 3×3',
          '05 CONTROLNET', '06 KHOÁ ASSET', '07 9 ẢNH', '08 SỬA GÓC', '09 DUYỆT & UPSCALE']


@pytest.fixture(scope='module')
def info():
    data = validate.load_cache_with_extra()
    assert data and 'ComfySwitchNode' in data, 'object_info_extra.json missing'
    return data


@pytest.fixture(scope='module')
def input_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp('input')
    for value in (v004.v003.FACE_VALUE, v004.v003.POSE_VALUE):
        (d / value).write_bytes(b'ref')
    return d


@pytest.fixture(scope='module')
def graph(info, input_dir):
    return v004.build(info, input_dir)


def _t(graph, title):
    hits = [n for n in graph['nodes'] if n.get('title') == title]
    assert len(hits) == 1, title
    return hits[0]


def _startswith(graph, prefix):
    hits = [n for n in graph['nodes'] if str(n.get('title', '')).startswith(prefix)]
    assert len(hits) == 1, prefix
    return hits[0]


def _src(graph, dst, port):
    lid = next(p['link'] for p in dst['inputs'] if p['name'] == port)
    if lid is None:
        return None
    sid = next(l[1] for l in graph['links'] if l[0] == lid)
    return next(n for n in graph['nodes'] if n['id'] == sid)


def test_valid_and_every_mutation_caught(graph, info, input_dir):
    report = validate.check(graph, info, input_dir)
    assert report['ok'], report['errors']
    applied = []
    assert validate.selftest(graph, info, applied) == []
    assert {'mute_required_source', 'switch_selects_muted', 'bypass_no_passthrough'} <= set(applied)


ORDERS = (('route', 'fix08', 'source09', 'target09'), ('route', 'source09', 'fix08', 'target09'))
LOCAL_GPU = {'UNETLoader', 'CLIPLoader', 'VAELoader', 'LoraLoaderModelOnly', 'CheckpointLoaderSimple', 'KSampler',
             'SamplerCustomAdvanced', 'Krea2EditModelPatch', 'UpscaleModelLoader', 'ImageUpscaleWithModel'}


@pytest.mark.parametrize('order', ORDERS)
@pytest.mark.parametrize('route,fix,source,target', list(itertools.product(
    ['local', 'codex'], ['off', 'on'], ['file', '08', '07'], ['1080', '2K', '4K'])))
def test_every_plan_combination_validates(graph, info, input_dir, order, route, fix, source, target):
    pick = {'route': route, 'fix08': fix, 'source09': source, 'target09': target}
    g = graph
    for dim in order:
        g = v004.apply_choice(g, dim, pick[dim])
    report = validate.check(g, info, input_dir)
    assert report['ok'], report['errors']
    assert g['extra']['newtecons_route'] == route


def _active_local_gpu_outside_09(g):
    box = next(x for x in g['groups'] if x['title'] == '09 DUYỆT & UPSCALE')['bounding']
    return sorted({n['type'] for n in g['nodes'] if n.get('mode', 0) == 0 and n['type'] in LOCAL_GPU
                   and not box[0] <= n['pos'][0] < box[0] + box[2]})


def test_codex_route_runs_no_local_model_unless_08_on(graph):
    # critic CR-V004-ROUTE: on CODEX no local loader/sampler stays active (09 upscale is the shared post step,
    # fed by an approved file; it is the only local model left and lives in group 09)
    codex = v004.apply_choice(graph, 'route', 'codex')
    assert _active_local_gpu_outside_09(codex) == []
    on = v004.apply_choice(codex, 'fix08', 'on')
    assert {'UNETLoader', 'KSampler', 'Krea2EditModelPatch'} <= set(_active_local_gpu_outside_09(on))
    assert _active_local_gpu_outside_09(v004.apply_choice(on, 'fix08', 'off')) == []
    p1 = _t(codex, 'ĐIỀN: PROMPT NEWTECONS live-action')
    assert p1['mode'] == 0  # the Codex node's prompt source stays live


def test_step08_default_off_and_source08_turns_it_on(graph):
    plan = graph['extra']['newtecons_route_plan']
    ids08 = set(plan['fix08']['options']['off']['mute'])
    assert ids08 and all(n['mode'] == 2 for n in graph['nodes'] if n['id'] in ids08)
    assert 'Krea2EditModelPatch' in {n['type'] for n in graph['nodes'] if n['id'] in ids08}
    g = v004.apply_choice(graph, 'source09', '08')
    assert all(n['mode'] == 0 for n in g['nodes'] if n['id'] in ids08)
    g = v004.apply_choice(g, 'fix08', 'off')  # skipping 08 again: the 09 wire falls back to 07
    assert _startswith(g, 'NGUỒN NỐI DÂY')['widgets_values'] == [False]


def test_route_round_trip_and_partition(graph):
    plan = graph['extra']['newtecons_route_plan']['route']['options']
    local_ids = set(plan['codex']['mute'])
    codex_ids = set(plan['local']['mute'])
    assert local_ids and codex_ids and not local_ids & codex_ids
    assert set(map(int, plan['local']['restore'])) == local_ids
    assert set(map(int, plan['codex']['restore'])) == codex_ids
    back = v004.apply_choice(v004.apply_choice(graph, 'route', 'codex'), 'route', 'local')
    assert [n['mode'] for n in back['nodes']] == [n['mode'] for n in graph['nodes']]
    kinds = {n['type'] for n in graph['nodes'] if n['id'] in local_ids}
    assert {'SamplerCustomAdvanced', 'UNETLoader', 'ReferenceLatent'} <= kinds  # local FLUX generation
    assert 'Krea2EditModelPatch' not in kinds and 'ImageUpscaleWithModel' not in kinds  # 08/09 shared by both


def test_codex_node_real_contract(graph):
    cx = next(n for n in graph['nodes'] if n['type'] == 'CodexOAuthImageLane')
    assert cx['mode'] == 2  # LOCAL is the default route
    # live contract after the 19:38 recreate: prompts sits BEFORE timeout_seconds, context last (8 widgets)
    assert cx['widgets_values'] == ['', 10, 'Newtecons-TienDo-KichTinh-30s', 'SHOT', 'identity', '', 3600, '(default)']
    assert [q['name'] for q in cx['inputs'] if 'widget' in q] == ['prompt', 'count', 'episode', 'kind', 'ref_role',
                                                              'prompts', 'timeout_seconds', 'context']
    assert _src(graph, cx, 'prompt')['title'] == 'ĐIỀN: PROMPT NEWTECONS live-action'
    jn = _startswith(graph, 'ẢNH TẠO RA')
    assert _src(graph, jn, 'on_false')['id'] == cx['id']
    assert graph['extra']['newtecons_image_8step']['codex_branch'] == 'node:CodexOAuthImageLane'


def test_placeholder_when_codex_node_absent(info, input_dir):
    no_codex = {k: v for k, v in info.items() if k != 'CodexOAuthImageLane'}
    g = v004.build(no_codex, input_dir)
    assert g['extra']['newtecons_image_8step']['codex_branch'] == 'placeholder:LoadImage codex-lane/'
    hold = _startswith(g, 'GIỮ CHỖ CODEX')
    assert hold['type'] == 'LoadImage' and hold['mode'] == 2
    assert validate.check(g, no_codex, input_dir)['ok']


def test_junction07_feeds_save_and_09(graph):
    jn = _startswith(graph, 'ẢNH TẠO RA')
    assert jn['widgets_values'] == [True]
    assert _src(graph, jn, 'on_true')['type'] == 'VAEDecodeTiled'
    save7 = _t(graph, 'Lưu 1 take (pose p × góc g) — chưa nghiệm thu')
    assert _src(graph, save7, 'images')['id'] == jn['id']
    wire = _startswith(graph, 'NGUỒN NỐI DÂY')
    assert _src(graph, wire, 'on_false')['id'] == jn['id']
    assert _src(graph, wire, 'on_true')['title'] == 'Giữ nguyên mọi pixel ngoài mask'


def test_step06_mute_defect_fixed(graph):
    e6b = _t(graph, 'Mã hoá ảnh đúng dáng (bước 05)')
    sw = _src(graph, e6b, 'pixels')
    assert sw['type'] == 'ComfySwitchNode' and sw['widgets_values'] == [False]
    assert _src(graph, sw, 'on_true')['title'] == 'Giải mã ảnh đúng dáng' and _src(graph, sw, 'on_true')['mode'] == 2
    assert _src(graph, sw, 'on_false')['type'] == 'LoadImage'


def test_group09_upscale_branches(graph):
    model = next(n for n in graph['nodes'] if n['type'] == 'UpscaleModelLoader')
    assert model['widgets_values'] == ['RealESRGAN_x4plus.pth']
    scales = sorted((n for n in graph['nodes'] if n['type'] == 'ImageScale'), key=lambda n: n['widgets_values'][2])
    assert [n['widgets_values'] for n in scales] == [['lanczos', 0, 1440, 'disabled'], ['lanczos', 0, 2048, 'disabled'],
                                                    ['lanczos', 0, 3840, 'disabled']]
    assert [n['mode'] for n in scales] == [0, 2, 2]
    saves = {n['widgets_values'][0]: n for n in graph['nodes'] if n['type'] == 'SaveImage'
             and n['widgets_values'][0].startswith('NEWTECONS/upscale/')}
    assert {k: v['mode'] for k, v in saves.items()} == {'NEWTECONS/upscale/1080': 0, 'NEWTECONS/upscale/2K': 2,
                                                         'NEWTECONS/upscale/4K': 2}
    for scale in scales:
        assert _src(graph, scale, 'image')['type'] == 'ImageUpscaleWithModel'
    note = _t(graph, 'CHƯA NGHIỆM THU — upscale')['widgets_values'][0]
    assert note.startswith('RealESRGAN x4 cho ảnh tĩnh, chưa nghiệm thu chất lượng NEWTECONS — cần xem kết quả')
    appr = _t(graph, 'DUYỆT (engine) — lệnh ghi duyệt')['widgets_values'][0]
    assert v004.APPROVE_CMD in appr and '--scope' in v004.APPROVE_CMD


def test_groups_order_and_new_nodes_inside(graph):
    assert [g['title'] for g in graph['groups']] == GROUPS
    xs = [g['bounding'][0] for g in graph['groups']]
    assert xs == sorted(xs) and len(set(xs)) == len(xs)
    for title in ('00 CHỌN LUỒNG', '09 DUYỆT & UPSCALE'):
        box = next(g for g in graph['groups'] if g['title'] == title)['bounding']
        members = [n for n in graph['nodes'] if box[0] <= n['pos'][0] < box[0] + box[2]]
        assert members
        for n in members:
            assert n['pos'][0] + n['size'][0] <= box[0] + box[2] and n['pos'][1] + n['size'][1] <= box[1] + box[3]


def test_switch_saved_like_frontend(graph):
    # measured on frontend 1.55.17: inputs [on_false, on_true, switch(widget)], MATCHTYPE ports carry IMAGE
    for sw in (n for n in graph['nodes'] if n['type'] == 'ComfySwitchNode'):
        assert [(p['name'], p['type']) for p in sw['inputs']] == [('on_false', 'IMAGE'), ('on_true', 'IMAGE'),
                                                                   ('switch', 'BOOLEAN')]
        assert [o['type'] for o in sw['outputs']] == ['IMAGE']


def test_mute_rule_catches_required_input_from_muted_node(graph, info, input_dir):
    g = copy.deepcopy(graph)
    up = next(n for n in g['nodes'] if n['type'] == 'UpscaleModelLoader')
    up['mode'] = 2  # ImageUpscaleWithModel.upscale_model is REQUIRED
    errors = validate.check(g, info, input_dir)['errors']
    assert any('required input upscale_model is fed by MUTED node' in e for e in errors), errors


def test_switch_rule_catches_selected_dead_side(graph, info, input_dir):
    g = v004.apply_choice(graph, 'route', 'codex')
    _startswith(g, 'ẢNH TẠO RA')['widgets_values'][0] = True  # selects the muted local side
    errors = validate.check(g, info, input_dir)['errors']
    assert any('selects on_true' in e and 'MUTED' in e for e in errors), errors


def test_matchtype_disagreement_caught(graph, info, input_dir):
    g = copy.deepcopy(graph)
    sw = _startswith(g, 'NGUỒN 09')
    sw['outputs'][0]['type'] = 'LATENT'
    assert any('MATCHTYPE ports disagree' in e for e in validate.check(g, info, input_dir)['errors'])


def test_builder_refuses_overwrite(tmp_path):
    out = tmp_path / 'v004.json'
    out.write_text('keep', encoding='utf-8')
    assert v004.main([str(out)]) == 1
    assert out.read_text(encoding='utf-8') == 'keep'


def test_saved_artifact_matches_builder(info):
    if not SAVED.is_file():
        pytest.skip('v004 not generated')
    saved = json.loads(SAVED.read_text(encoding='utf-8'))
    built = v004.build(info, validate.DEFAULT_INPUT_DIR)
    assert saved == json.loads(json.dumps(built, ensure_ascii=False))
