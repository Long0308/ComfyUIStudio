"""Read-only check of a grouped ComfyUI UI workflow (default: NEWTECONS IMAGE 8 STEP).

Checks: exact group titles in order, Blue Web colours (no orange/yellow/beige),
every node (incl. its 30 px title bar) inside exactly one group, every link
references existing nodes/slots with matching types on both ends, no JennieJoy
text. --selftest breaks copies of the graph and requires every break to be caught.

Usage:  python -I check_image_8step.py GRAPH.json [--titles video] [--selftest]
"""
import argparse
import colorsys
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

IMAGE_TITLES = ['01 PROMPT', '02 ASSET 4 GÓC', '03 3D', '04 SET 3D 3×3',
                '05 CONTROLNET', '06 KHOÁ ASSET', '07 9 ẢNH', '08 SỬA GÓC']
VIDEO_TITLES = ['01 ĐỌC SHOTLIST', '02 VIẾT PROMPT', '03 AI QUAY VIDEO', '04 LÊN 1080P', '05 LƯU & QUAY TIẾP']
TITLE_BAR = 30


def warm(color: str) -> bool:
    """Orange / yellow / beige: hue 15-70 degrees with any visible saturation."""
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, _, s = colorsys.rgb_to_hls(r, g, b)
    return 15 <= h * 360 <= 70 and s > 0.08


def check(graph: dict, titles: list) -> dict:
    errors = []
    groups = graph.get('groups', [])
    got = [g.get('title') for g in groups]
    if got != titles:
        errors.append('group titles %r != %r' % (got, titles))
    for g in groups:
        c = g.get('color', '')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', c) or warm(c):
            errors.append('bad colour %s in %s' % (c, g.get('title')))
    nodes = {}
    for n in graph['nodes']:
        if n['id'] in nodes:
            errors.append('duplicate node id %s' % n['id'])
        nodes[n['id']] = n
    per_group = {g.get('title'): 0 for g in groups}
    for n in graph['nodes']:
        x, y = n['pos'][0], n['pos'][1] - TITLE_BAR
        w, h = n['size'][0], n['size'][1] + TITLE_BAR
        inside = [g['title'] for g in groups
                  if g['bounding'][0] <= x and g['bounding'][1] <= y
                  and x + w <= g['bounding'][0] + g['bounding'][2]
                  and y + h <= g['bounding'][1] + g['bounding'][3]]
        if len(inside) != 1:
            errors.append('node %s (%s) inside %d groups' % (n['id'], n['type'], len(inside)))
        else:
            per_group[inside[0]] += 1
    for title, count in per_group.items():
        if not any(n['type'] in ('Note', 'MarkdownNote') and str(n.get('title', '')).endswith(title)
                   for n in graph['nodes']):
            errors.append('group %s has no HƯỚNG DẪN note' % title)
    ids = [l[0] for l in graph['links']]
    if len(ids) != len(set(ids)):
        errors.append('duplicate link ids')
    for link in graph['links']:
        lid, src, s_slot, dst, d_slot, kind = link
        if src not in nodes or dst not in nodes:
            errors.append('link %s references missing node' % lid)
            continue
        outs, ins = nodes[src].get('outputs', []), nodes[dst].get('inputs', [])
        if not 0 <= s_slot < len(outs) or not 0 <= d_slot < len(ins):
            errors.append('link %s references missing slot' % lid)
            continue
        if lid not in (outs[s_slot].get('links') or []):
            errors.append('link %s missing from source output list' % lid)
        if ins[d_slot].get('link') != lid:
            errors.append('link %s not set on destination input' % lid)
        if not (outs[s_slot]['type'] == ins[d_slot]['type'] == kind):
            errors.append('link %s type mismatch %s/%s/%s' % (lid, outs[s_slot]['type'], ins[d_slot]['type'], kind))
    known = set(ids)
    for n in graph['nodes']:
        for p in n.get('inputs', []):
            if p.get('link') is not None and p['link'] not in known:
                errors.append('node %s input %s -> unknown link %s' % (n['id'], p['name'], p['link']))
        for o in n.get('outputs', []):
            for lid in o.get('links') or []:
                if lid not in known:
                    errors.append('node %s output %s -> unknown link %s' % (n['id'], o['name'], lid))
    if graph.get('last_node_id', -1) < max(nodes):
        errors.append('last_node_id below max node id')
    if ids and graph.get('last_link_id', -1) < max(ids):
        errors.append('last_link_id below max link id')
    for n in graph['nodes']:  # prompts / file anchors live in executable widgets, not in Notes
        if n['type'] not in ('Note', 'MarkdownNote') and \
                'jennie' in json.dumps(n.get('widgets_values'), ensure_ascii=False).lower():
            errors.append('JennieJoy text in node %s widgets' % n['id'])
    return {'ok': not errors, 'errors': errors, 'groups': len(groups), 'nodes': len(nodes),
            'links': len(ids), 'nodes_per_group': per_group}


def selftest(graph: dict, titles: list) -> list:
    """Each mutation must be reported; returns names of breaks the checker missed."""
    def rename(g): g['groups'][0]['title'] += 'X'
    def orange(g): g['groups'][0]['color'] = '#FF8C00'
    def outside(g): g['nodes'][-1]['pos'] = [-5000, -5000]
    def straddle(g):
        b = g['groups'][0]['bounding']; g['nodes'][0]['pos'] = [b[0] + b[2] - 10, g['nodes'][0]['pos'][1]]
    def dangling(g): g['links'][0][3] = 999999
    def bad_slot(g): g['links'][0][2] = 99
    def type_flip(g): g['links'][0][5] = 'MODEL' if g['links'][0][5] != 'MODEL' else 'CLIP'
    def unlinked_dst(g):
        lid, _, _, dst, slot, _ = g['links'][0]
        next(n for n in g['nodes'] if n['id'] == dst)['inputs'][slot]['link'] = None
    def jennie(g):
        next(n for n in g['nodes'] if n['type'] not in ('Note', 'MarkdownNote'))['widgets_values'] = ['JennieJoy anchor']
    missed = []
    for f in (rename, orange, outside, straddle, dangling, bad_slot, type_flip, unlinked_dst, jennie):
        broken = copy.deepcopy(graph)
        f(broken)
        if check(broken, titles)['ok']:
            missed.append(f.__name__)
    return missed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('graph', type=Path)
    p.add_argument('--titles', choices=['image', 'video'], default='image')
    p.add_argument('--selftest', action='store_true')
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    raw = a.graph.read_bytes()
    graph = json.loads(raw.decode('utf-8-sig'))
    titles = IMAGE_TITLES if a.titles == 'image' else VIDEO_TITLES
    report = check(graph, titles)
    report['sha256'] = hashlib.sha256(raw).hexdigest()
    if a.selftest:
        report['selftest_missed'] = selftest(graph, titles)
        report['ok'] = report['ok'] and not report['selftest_missed']
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
