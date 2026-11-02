"""Offline checks for NEWTECONS IMAGE v005: 02A NEO TRANG PHỤC (wardrobe anchors on both routes) and 02B = the
selected character's own images (reference-library only via the MẪU TẠO NHÂN VẬT MỚI toggle).

Schemas: object_info cache + object_info_extra*.json + codex_lane_bridge_schema_v005.json (DERIVED from the pack;
the server had not restarted). Presets / characters: synthetic dicts in the jjv/wardrobe-presets/v1 and
jjv/character-refs/v1 shapes, plus the real files when present. No server call, no GPU.
"""
import copy
import importlib.util
import itertools
import json
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
TOOL_DIR = ENGINE / 'tools' / 'comfy_layout'
WF = ENGINE.parents[2] / 'production-local' / 'ComfyUI' / 'user' / 'default' / 'workflows'
SAVED = [WF / 'ProjectStudio5 - Film Newtecons' / '01 Workflow Image' / 'NEWTECONS Image v005 - neo trang phuc.json',
         WF / 'NEWTECONS_IMAGE_8STEP' / 'NEWTECONS_IMAGE_8STEP_v005_grouped.json']

spec = importlib.util.spec_from_file_location('img_v005_test', TOOL_DIR / 'image_8step_build_v005.py')
v005 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v005)
V = v005.validate

PRESETS = {'schema': 'jjv/wardrobe-presets/v1', 'default_context': 'cong_truong', 'contexts': {
    'cong_truong': [{'name': 'a', 'file': 'newtecons-wardrobe/a.png'}, {'name': 'b', 'file': 'newtecons-wardrobe/b.png'},
                    {'name': 'c', 'file': 'newtecons-wardrobe/c.png'}],
    'van_phong': [{'name': 'd', 'file': 'newtecons-wardrobe/d.png'}]}}
CHARS = {'schema': 'jjv/character-refs/v1', 'characters': {
    c: {'name': 'N' + c, 'face': [{'file': 'newtecons-characters/%s/f%d.png' % (c, i)} for i in range(4)],
        'action': [{'file': 'newtecons-characters/%s/a%d.png' % (c, i)} for i in range(3)]}
    for c in v005.CHARACTER_IDS}}
FILES = ([r['file'] for rows in PRESETS['contexts'].values() for r in rows]
         + [r['file'] for c in CHARS['characters'].values() for k in ('face', 'action') for r in c[k]]
         + [v005.v003.FACE_VALUE, v005.v003.POSE_VALUE])


@pytest.fixture(scope='module')
def info():
    data = v005.load_info_v005()
    assert data and {'ImageStitch', 'ComfySwitchNode', 'CodexOAuthImageLane'} <= set(data)
    return data


@pytest.fixture(scope='module')
def input_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp('input')
    for f in FILES:
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_bytes(b'png')
    return d


@pytest.fixture(scope='module')
def graph(info, input_dir):
    return v005.build(info, input_dir, PRESETS, CHARS)


def _by(g):
    return {n['id']: n for n in g['nodes']}


def test_valid_mutations_caught_and_group_order(graph, info, input_dir):
    report = V.check(graph, info, input_dir)
    assert report['ok'], report['errors']
    assert report['wardrobe_blocked'] is False and report['character_blocked'] is False
    applied = []
    assert V.selftest(graph, info, applied) == [] and len(applied) == 9
    titles = [g['title'] for g in graph['groups']]
    assert titles.index('02A NEO TRANG PHỤC') == titles.index('01 PROMPT') + 1
    assert titles.index('02B THAM CHIẾU FACE/POSE') == titles.index('02 ASSET 4 GÓC') + 1


def test_combinations_validate(graph, info, input_dir):
    plan = graph['extra']['newtecons_route_plan']
    bad = []
    for order in (('route', 'wardrobe', 'upload', 'boicanh', 'character', 'mau_moi', 'fix08', 'source09'),
                  ('source09', 'fix08', 'mau_moi', 'character', 'boicanh', 'upload', 'wardrobe', 'route')):
        for r, w, u, b, c, mm, f, s in itertools.product(['local', 'codex'], list(plan['wardrobe']['options']),
                                                         ['off', 'on'], ['off', 'on'], ['CHAR_01', 'CHAR_08'],
                                                         ['off', 'on'], ['off', 'on'], ['file', '08']):
            pick = dict(route=r, wardrobe=w, upload=u, boicanh=b, character=c, mau_moi=mm, fix08=f, source09=s)
            g = graph
            for dim in order:
                g = v005.apply_choice(g, dim, pick[dim])
            rep = V.check(g, info, input_dir)
            if not rep['ok']:
                bad.append((pick, rep['errors'][:2]))
    assert bad == []


@pytest.mark.parametrize('route', ['local', 'codex'])
def test_no_route_runs_with_zero_wardrobe_refs(graph, info, input_dir, route):
    g = v005.apply_choice(graph, 'route', route)
    assert V.check(g, info, input_dir)['ok']
    sheet = graph['extra']['newtecons_wardrobe']['sheet']
    cx = next(n for n in graph['nodes'] if n['type'] == 'CodexOAuthImageLane')
    if route == 'local':
        broken = copy.deepcopy(g)
        _by(broken)[sheet]['mode'] = 2
        assert any('ZERO wardrobe refs' in e for e in V.check(broken, info, input_dir)['errors'])
    else:
        empty = copy.deepcopy(g)
        _by(empty)[cx['id']]['widgets_values'][v005.widget_index(cx, 'context')] = ''
        assert any('ZERO wardrobe refs' in e for e in V.check(empty, info, input_dir)['errors'])
        override = copy.deepcopy(g)  # refs would REPLACE the bridge preset (NODE-CONTRACT)
        lid = override['last_link_id'] + 1
        override['last_link_id'] = lid
        override['links'].append([lid, sheet, 0, cx['id'], 0, 'IMAGE'])
        _by(override)[sheet]['outputs'][0]['links'].append(lid)
        next(p for p in _by(override)[cx['id']]['inputs'] if p['name'] == 'refs')['link'] = lid
        assert any('REPLACE the wardrobe preset' in e for e in V.check(override, info, input_dir)['errors'])


def test_context_switch_changes_slot_files_and_codex_context(graph):
    w = graph['extra']['newtecons_wardrobe']
    cx = next(n for n in graph['nodes'] if n['type'] == 'CodexOAuthImageLane')
    site = _by(v005.apply_choice(graph, 'wardrobe', 'cong_truong'))
    office = _by(v005.apply_choice(graph, 'wardrobe', 'van_phong'))
    assert [site[i]['widgets_values'][0] for i in w['slots']] == ['newtecons-wardrobe/a.png', 'newtecons-wardrobe/b.png',
                                                                 'newtecons-wardrobe/c.png']
    assert [office[i]['widgets_values'][0] for i in w['slots']] == ['newtecons-wardrobe/d.png', '', '']
    assert [office[i]['mode'] for i in w['slots']] == [0, 2, 2]
    k = v005.widget_index(cx, 'context')
    assert site[cx['id']]['widgets_values'][k] == 'cong_truong' and office[cx['id']]['widgets_values'][k] == 'van_phong'
    g = v005.apply_choice(graph, 'wardrobe', 'van_phong')
    assert g['extra']['newtecons_wardrobe_context'] == 'van_phong'


def test_upload_and_scene_feed_both_routes(graph):
    w = graph['extra']['newtecons_wardrobe']
    cx = next(n for n in graph['nodes'] if n['type'] == 'CodexOAuthImageLane')
    src = {p['name']: p['link'] for p in cx['inputs']}
    link_src = {l[0]: l[1] for l in graph['links']}
    assert link_src[src['company_wardrobe']] == w['optional'][0] and link_src[src['scene_ref']] == w['optional'][1]
    assert src['refs'] is None  # refs would replace the preset
    stitched = {l[1] for l in graph['links'] if _by(graph)[l[3]]['type'] == 'ImageStitch'}
    assert set(w['optional']) <= stitched  # also in the LOCAL reference sheet
    assert all(_by(graph)[i]['mode'] == 2 for i in w['optional'])  # optional, default OFF


def test_character_switch_uses_own_images_never_reference_library(graph):
    ch = graph['extra']['newtecons_characters']
    assert len(ch['face']) == v005.MAX_FACE and len(ch['pose']) == v005.MAX_POSE
    for char in v005.CHARACTER_IDS:
        g = _by(v005.apply_choice(graph, 'character', char))
        values = [g[i]['widgets_values'][0] for i in ch['slots']]
        assert values == (['newtecons-characters/%s/f%d.png' % (char, i) for i in range(3)]
                          + ['newtecons-characters/%s/a%d.png' % (char, i) for i in range(2)])
        assert not any('newtecons_ref_' in v or 'reference-library' in v for v in values)


def test_mau_moi_is_opt_in_and_reference_library_never_default(graph, info, input_dir):
    plan = graph['extra']['newtecons_route_plan']
    mau = plan['mau_moi']['options']['off']['mute']
    by = _by(graph)
    assert all(by[i]['mode'] == 2 for i in mau)
    assert {by[i]['widgets_values'][0] for i in mau if by[i]['type'] == 'LoadImage'} == {v005.v003.FACE_VALUE,
                                                                                       v005.v003.POSE_VALUE}
    switches = [n for n in graph['nodes'] if n['type'] == 'ComfySwitchNode' and 'MẪU TẠO NHÂN VẬT MỚI' in n['title']]
    assert len(switches) == 2 and all(n['widgets_values'] == [False] for n in switches)
    on = v005.apply_choice(graph, 'mau_moi', 'on')
    assert all(_by(on)[n['id']]['widgets_values'] == [True] for n in switches)
    assert V.check(on, info, input_dir)['ok']


def test_blocked_without_data(info, input_dir):
    no_chars = V.check(v005.build(info, input_dir, PRESETS, None), info, input_dir)
    assert no_chars['ok'] and no_chars['character_blocked'] is True
    no_presets = V.check(v005.build(info, input_dir, None, CHARS), info, input_dir)
    assert no_presets['ok'] and no_presets['wardrobe_blocked'] is True


def test_local_generators_take_wardrobe_and_character_refs(graph):
    nodes, links = _by(graph), {l[0]: l for l in graph['links']}
    ch = set(graph['extra']['newtecons_characters']['face'])
    anchors = {graph['extra']['newtecons_wardrobe']['slots'][0]}
    samplers = [n for n in graph['nodes'] if n['type'] == 'SamplerCustomAdvanced']
    ups = [V._upstream_live(nodes, links, s) for s in samplers]
    assert all(anchors & u for u in ups)  # 02 and 06 both carry the wardrobe sheet
    assert any(ch & u for u in ups)  # 02 carries the character faces


@pytest.mark.parametrize('path', SAVED, ids=['project-tree', 'old-folder'])
def test_saved_artifacts_match_builder(path):
    if not path.is_file():
        pytest.skip('v005 not generated')
    info = v005.load_info_v005()
    built = v005.build(info, V.DEFAULT_INPUT_DIR, v005.load_presets(v005.PRESETS), v005.load_presets(v005.CHARACTERS))
    assert json.loads(path.read_text(encoding='utf-8')) == json.loads(json.dumps(built, ensure_ascii=False))
