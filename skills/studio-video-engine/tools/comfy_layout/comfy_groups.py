"""Offline ComfyUI UI layout; API conversion and overwrite are refused."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import textwrap


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def equal(a, b):
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)


def pair(value):
    if isinstance(value, dict):
        value = [value.get('0'), value.get('1')]
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('Expected two coordinates')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise ValueError('Coordinates must be finite numbers')
    return value


def nodes(graph):
    if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), list) or not isinstance(graph.get('links'), list):
        raise ValueError('UI export required (nodes + links arrays); API-only graph refused')
    ids = set()
    for n in graph['nodes']:
        if type(n.get('id')) is not int or n['id'] < 0 or n['id'] in ids:
            raise ValueError('Node IDs must be unique nonnegative integers')
        ids.add(n['id'])
        if not isinstance(n.get('type'), str):
            raise ValueError('Missing node type')
        pair(n.get('pos'))
        if any(v <= 0 for v in pair(n.get('size'))):
            raise ValueError('Positive measured UI sizes required')
    return graph['nodes']


def layout(source, mapping):
    original = nodes(source)
    groups = mapping['groups']
    if not isinstance(groups, list) or not groups:
        raise ValueError('Nonempty groups array required')
    assigned = {}
    all_ids = {n['id'] for n in original}
    all_types = {n['type'] for n in original}
    for i, g in enumerate(groups):
        if not isinstance(g.get('title'), str) or not g['title'].strip() or not isinstance(g.get('note'), str) or not g['note'].strip():
            raise ValueError('Each group needs a title and Vietnamese INPUT -> OUTPUT note')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', g.get('color', '')):
            raise ValueError('color must be #RRGGBB')
        ids, types = g.get('node_ids', []), g.get('node_types', [])
        if not isinstance(ids, list) or any(type(v) is not int for v in ids):
            raise ValueError('node_ids must be integer array')
        if not isinstance(types, list) or any(not isinstance(v, str) for v in types):
            raise ValueError('node_types must be string array')
        if set(ids) - all_ids or set(types) - all_types:
            raise ValueError('Unknown ID/type selector: ' + g['title'])
        for n in original:
            if n['id'] in ids or n['type'] in types:
                if n['id'] in assigned:
                    raise ValueError('Node assigned to multiple groups')
                assigned[n['id']] = i
    if set(assigned) != all_ids:
        raise ValueError('Unassigned nodes: ' + str(sorted(all_ids - assigned.keys())))
    last = source.get('last_node_id', 0)
    if type(last) is not int or last < 0:
        raise ValueError('last_node_id must be nonnegative integer')
    last = max([last] + list(all_ids))
    out = copy.deepcopy(source)
    out['groups'] = []
    x = 0
    for i, g in enumerate(groups):
        members = [n for n in out['nodes'][:len(original)] if assigned[n['id']] == i]
        width = max([600] + [pair(n['size'])[0] for n in members])
        note = '\n'.join(textwrap.fill(line, 70, replace_whitespace=False) for line in g['note'].split('\n'))
        height = max(200, 60 + 24 * len(note.splitlines()))
        out['nodes'].append({'id': last+i+1, 'type': 'Note', 'title': 'HƯỚNG DẪN — '+g['title'], 'pos': [x+40,80], 'size': [width,height], 'flags': {}, 'order': len(original)+i, 'mode': 0, 'inputs': [], 'outputs': [], 'properties': {}, 'widgets_values': [note]})
        y = 80 + height + 70
        for n in members:
            n['pos'] = [x+40,y]
            y += pair(n['size'])[1] + 70
        out['groups'].append({'title': g['title'], 'bounding': [x,0,width+80,y+40], 'color': g['color'], 'font_size': 28, 'flags': {}})
        x += width + 220
    out['last_node_id'] = last + len(groups)
    return out


def check(source, result, mapping):
    before, after = nodes(source), nodes(result)
    count = len(mapping['groups'])
    if len(after) != len(before)+count or len(result.get('groups', [])) != count:
        raise ValueError('Expected original nodes plus exactly one Note per group')
    if not equal(source['links'], result['links']):
        raise ValueError('Links changed')
    for a,b in zip(before, after):
        if not equal({k:v for k,v in a.items() if k != 'pos'}, {k:v for k,v in b.items() if k != 'pos'}):
            raise ValueError('Original node changed beyond position: '+str(a['id']))
    for n in after:
        x,y = pair(n['pos'])
        w,h = pair(n['size'])
        contains = sum(gx <= x and gy <= y and x+w <= gx+gw and y+h <= gy+gh for gx,gy,gw,gh in (g['bounding'] for g in result['groups']))
        if contains != 1:
            raise ValueError('Node must fit exactly one group: '+str(n['id']))
    if not equal(result, layout(source, mapping)):
        raise ValueError('Output differs from deterministic layout (including metadata and notes)')
    return {'original_nodes': len(before), 'preserved_nodes': len(before), 'added_notes': count, 'output_nodes': len(after), 'source_links': len(source['links']), 'output_links': len(result['links']), 'widgets_values_unchanged': True, 'all_original_fields_except_pos_unchanged': True, 'groups': count, 'every_node_inside_exactly_one_group': True}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('group_map', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--check', action='store_true', help='Read-only acceptance check')
    a = p.parse_args()
    try:
        source, mapping = read(a.source), read(a.group_map)
        if not a.check:
            if not re.search(r'(?:^|_)v\d+(?:_|\.)', a.output.name):
                raise ValueError('Output filename must include _v002_ or another version')
            if a.output.resolve() in (a.source.resolve(), a.group_map.resolve()):
                raise ValueError('Output must be a new file')
        result = read(a.output) if a.check else layout(source, mapping)
        report = check(source, result, mapping)
        if not a.check:
            payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
            with a.output.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(payload)
        report.update(source_sha256=sha(a.source), group_map_sha256=sha(a.group_map), output_sha256=sha(a.output))
        print(json.dumps(report, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('REFUSED: '+str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
