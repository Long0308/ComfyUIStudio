"""Offline H3 conversion checks; the root session owns final acceptance.

Live INPUT_TYPES come from tools/comfy_layout/object_info_cache.json (GET /object_info,
ComfyUI 0.41.0). No server call is made by these tests.
"""
import copy
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

ENGINE = Path(__file__).resolve().parents[1]
TOOL_DIR = ENGINE / 'tools' / 'comfy_layout'


def _load(name, alias):
    spec = importlib.util.spec_from_file_location(alias, TOOL_DIR / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


converter = _load('api_to_ui.py', 'wf_ui_converter')
validate = _load('validate_live.py', 'wf_ui_validate')
v003 = _load('h3_v003_build.py', 'wf_ui_h3_v003')
PROJECT = ENGINE.parents[2]
ALL_WORKFLOWS = PROJECT / 'production-local/ComfyUI/user/default/workflows'
WORKFLOWS = ALL_WORKFLOWS / 'NEWTECONS_H3'
API_PATH = WORKFLOWS / 'NEWTECONS_H3_R2V_LIVE_ACTION_v001.api.json'
MAP_PATH = WORKFLOWS / 'NEWTECONS_H3_R2V_LIVE_ACTION_v002_group-map.json'
MAP_V003 = TOOL_DIR / 'NEWTECONS_H3_R2V_LIVE_ACTION_v003_group-map.json'
V002 = WORKFLOWS / 'NEWTECONS_H3_R2V_LIVE_ACTION_v002_grouped.json'
V003 = WORKFLOWS / 'NEWTECONS_H3_R2V_LIVE_ACTION_v003_grouped.json'
IMAGE_V002 = ALL_WORKFLOWS / 'NEWTECONS_IMAGE_8STEP' / 'NEWTECONS_IMAGE_8STEP_v002_grouped.json'
FRONTEND_SAVED = ALL_WORKFLOWS / 'JennieJoyKids - APP ENGINE SAN XUAT PHIM 60S (TIENG VIET).json'
TITLES = ['01 ĐỌC SHOTLIST', '02 VIẾT PROMPT', '03 AI QUAY VIDEO',
          '04 LÊN 1080P', '05 LƯU & QUAY TIẾP']
H3_WIDGETS = ['', 864, 480, 124, 'match']  # prompt is linked -> '' placeholder first
MATERIALIZED = {'17': ['bit_depth', 'codec', 'color_space'], '18': ['codec', 'format.codec.encoding']}


@pytest.fixture
def source():
    return converter.comfy_groups.read(API_PATH)


@pytest.fixture
def mapping():
    return converter.comfy_groups.read(MAP_PATH)


@pytest.fixture
def info():
    cache = converter.oi.load_cache()
    assert cache is not None, 'object_info_cache.json missing'
    return cache


def test_real_h3_round_trip_connections_groups(source, mapping):
    original, original_map = copy.deepcopy(source), copy.deepcopy(mapping)
    graph, report = converter.build_checked(source, mapping)
    assert report['materialized_defaults'] == MATERIALIZED
    api = converter.to_api(graph)
    assert set(api) == set(source)
    for key, node in source.items():
        assert api[key]['class_type'] == node['class_type']
        assert {k: api[key]['inputs'][k] for k in node['inputs']} == node['inputs']
    # Independently enumerate both endpoint sets, including destination port names.
    expected = {(int(src), slot, int(dst), name) for dst, n in source.items()
                for name, val in n['inputs'].items() if converter.is_link(val)
                for src, slot in [val]}
    indexed = {n['id']: n for n in graph['nodes']}
    actual = {(src, slot, dst, indexed[dst]['inputs'][target]['name'])
              for _, src, slot, dst, target, _ in graph['links']}
    assert actual == expected
    assert len(graph['nodes']) == 24
    assert len(graph['links']) == len(expected) == 25
    assert [g['title'] for g in graph['groups']] == TITLES
    assert [g['color'] for g in graph['groups']] == converter.PALETTE
    for node in graph['nodes']:
        x, y = node['pos']
        w, h = node['size']
        assert sum(gx <= x and gy <= y - 30 and x + w <= gx + gw and y + h <= gy + gh
                   for gx, gy, gw, gh in (g['bounding'] for g in graph['groups'])) == 1
    assert len({g['bounding'][3] for g in graph['groups']}) == 1
    assert source == original and mapping == original_map
    assert graph == converter.build(source, mapping)[0]


def test_linked_widget_keeps_placeholder_and_order(source):
    # Input dict insertion order is not widget/slot order.
    for node in source.values():
        node['inputs'] = dict(reversed(list(node['inputs'].items())))
    nodes = {n['id']: n for n in converter.convert(source)['nodes']}
    assert nodes[6]['widgets_values'] == H3_WIDGETS
    names = [p['name'] for p in nodes[6]['inputs'] if 'widget' in p]
    assert names == ['prompt', 'width', 'height', 'length', 'ref_image_size']
    prompt = next(p for p in nodes[6]['inputs'] if p['name'] == 'prompt')
    assert prompt['widget'] == {'name': 'prompt'} and prompt['link'] is not None
    assert nodes[17]['widgets_values'] == [24.0, 'auto', 'sRGB', 'none']
    assert nodes[18]['widgets_values'] == ['NEWTECONS/H3/Shot', 'mp4', 'h264', 'auto', 'auto']
    assert nodes[11]['widgets_values'] == [20261030, 'fixed']
    assert nodes[5]['widgets_values'] == ['', 'image'] and nodes[7]['widgets_values'] == ['', '']
    assert [p['name'] for p in nodes[9]['inputs'][:6]] == [
        'positive', 'latent', 'vae', 'audio_vae', 'image', 'audio']
    assert nodes[19]['widgets_values'] == [source['19']['inputs']['value']]


def test_to_api_reads_link_not_placeholder(source):
    api = converter.to_api(converter.convert(source))
    assert api['6']['inputs']['prompt'] == ['19', 0]
    assert [api['6']['inputs'][k] for k in ('width', 'height', 'length', 'ref_image_size')] == H3_WIDGETS[1:]


def test_legacy_snapshot_mode_also_keeps_placeholder(source):
    nodes = {n['id']: n for n in converter.convert(source, info=None)['nodes']}
    assert nodes[6]['widgets_values'] == H3_WIDGETS
    assert nodes[17]['widgets_values'] == [24.0]  # legacy: unsupplied optionals omitted
    api = converter.to_api(converter.convert(source, info=None), info=None)
    assert {k: v['inputs'] for k, v in api.items()} == {k: v['inputs'] for k, v in source.items()}


def test_widget_slots_match_frontend_saved_h3_node(info):
    if not FRONTEND_SAVED.is_file():
        pytest.skip('frontend-saved reference workflow not on this machine')
    graph = converter.comfy_groups.read(FRONTEND_SAVED)
    node = next(n for n in graph['nodes'] if n['type'] == 'MiniMaxH3ReferenceToVideo')
    prompt = next(p for p in node['inputs'] if p['name'] == 'prompt')
    assert prompt['link'] is not None and node['widgets_values'][0] == ''
    slots = converter.oi.widget_layout(info['MiniMaxH3ReferenceToVideo'], node['widgets_values'])
    assert [s['name'] for s in slots] == ['prompt', 'width', 'height', 'length', 'ref_image_size']
    assert len(node['widgets_values']) == len(slots) == len(H3_WIDGETS)


def test_snapshot_disagreeing_with_live_schema_refused(source, info):
    tampered = copy.deepcopy(info)
    tampered['BasicGuider']['input']['required']['model'] = ['CLIP', {}]
    with pytest.raises(ValueError, match='Snapshot sockets differ'):
        converter.convert(source, info=tampered)


@pytest.mark.parametrize('mutation', ['dangling', 'slot', 'type', 'unknown_input', 'unknown_node'])
def test_invalid_graph_refused(source, mutation):
    if mutation == 'dangling':
        source['6']['inputs']['clip'] = ['999', 0]
    elif mutation == 'slot':
        source['6']['inputs']['clip'] = ['2', -1]
    elif mutation == 'type':
        source['6']['inputs']['clip'] = ['3', 0]
    elif mutation == 'unknown_input':
        source['6']['inputs']['made_up'] = 123
    else:
        source['6']['class_type'] = 'UnknownNode'
    with pytest.raises(ValueError):
        converter.convert(source)


@pytest.mark.parametrize('mutation', ['orphan', 'duplicate', 'unknown'])
def test_bad_group_mapping_refused(source, mapping, mutation):
    if mutation == 'orphan':
        mapping['groups'][0]['node_ids'].remove(7)
    elif mutation == 'duplicate':
        mapping['groups'][1]['node_ids'].append(7)
    else:
        mapping['groups'][0]['node_ids'].append(999)
    with pytest.raises(ValueError):
        converter.build(source, mapping)


def test_existing_file_never_overwritten(source):
    before = API_PATH.read_bytes()
    with pytest.raises(FileExistsError):
        converter.write_new(API_PATH, converter.convert(source))
    assert API_PATH.read_bytes() == before


def test_write_uses_exclusive_creation():
    with patch.object(Path, 'open', side_effect=FileExistsError) as opened:
        with pytest.raises(FileExistsError):
            converter.write_new(Path('unused.json'), {})
    assert opened.call_args.args == ('x',)


def test_wire_tampering_detected(source):
    ui = converter.convert(source)
    ui['links'][0][4] += 1
    with pytest.raises(ValueError, match='destination mismatch'):
        converter.to_api(ui)


def test_optional_widget_gap(source):
    source['17']['inputs']['color_space'] = 'HDR'
    # Legacy positional mode would assign HDR to bit_depth: refused.
    with pytest.raises(ValueError, match='Widget order gap before color_space: bit_depth'):
        converter.convert(source, info=None)
    # Live mode materializes bit_depth's default, so HDR stays on color_space.
    node = next(n for n in converter.convert(source)['nodes'] if n['id'] == 17)
    assert node['widgets_values'] == [24.0, 'auto', 'HDR', 'none']


def test_v002_defect_is_caught_by_live_validator(info):
    if not V002.is_file():
        pytest.skip('historic v002 not installed')
    report = validate.check(converter.comfy_groups.read(V002), info)
    assert not report['ok']
    assert any(e.startswith('6(MiniMaxH3ReferenceToVideo) widgets_values len 4 != live widget slots 5')
               for e in report['errors'])


def test_v003_artifact_deterministic_bypass_and_live_valid(source, info):
    assert V003.is_file(), 'v003 grouped artifact has not been generated'
    saved = converter.comfy_groups.read(V003)
    built, report = v003.build(source, converter.comfy_groups.read(MAP_V003))
    assert saved == built
    assert [g['title'] for g in saved['groups']] == TITLES
    assert len(saved['nodes']) == 27 and len(saved['links']) == 28 and len(saved['groups']) == 5
    assert report['bypassed_materialized_defaults'] == MATERIALIZED
    nodes = {n['id']: n for n in saved['nodes']}
    assert [nodes[i]['mode'] for i in (20, 21, 22)] == [2, 4, 4]  # CR-V003: loader muted, not bypassed
    assert nodes[20]['widgets_values'] == ['RealESRGAN_x4plus.pth']
    assert nodes[22]['widgets_values'] == ['lanczos', 1920, 1080, 'center']
    assert nodes[6]['widgets_values'] == H3_WIDGETS
    note04 = next(n for n in saved['nodes'] if n.get('title') == 'HƯỚNG DẪN — 04 LÊN 1080P')
    assert note04['widgets_values'][0].startswith('Chưa nghiệm thu cho NEWTECONS — cần pilot GPU user duyệt')
    # Bypassed as saved: the executed graph is v001 (17.images resolves to VAEDecode 15).
    assert converter.to_api(saved)['17']['inputs']['images'] == ['15', 0]
    group03 = next(g for g in saved['groups'] if g['title'] == '03 AI QUAY VIDEO')
    xs = {nodes[i]['pos'][0] for i in (1, 2, 3, 4, 6, 9, 10, 11, 12, 13, 14, 15, 16)}
    assert 3 <= len(xs) <= 4 and all(group03['bounding'][0] < x for x in xs)
    report = validate.check(saved, info)
    assert report['ok'], report['errors']
    assert validate.selftest(saved, info) == []


def test_image_v002_live_valid(info):
    if not IMAGE_V002.is_file():
        pytest.skip('image v002 not generated')
    graph = converter.comfy_groups.read(IMAGE_V002)
    report = validate.check(graph, info)
    # kept as shipped: only the step-06 mute defect (VAEEncode.pixels fed by muted step-05 VAEDecode; fixed in v004)
    assert len(report['errors']) == 1 and 'required input pixels is fed by MUTED node' in report['errors'][0], report['errors']
    assert validate.selftest(graph, info) == []
    text = next(n for n in graph['nodes'] if n['type'] == 'CLIPTextEncode')
    assert text['widgets_values'] == [''] and next(p for p in text['inputs'] if p['name'] == 'text')['widget']
