"""Offline group layout: dependency-depth columns inside each group, equal group heights.

Every group gets one HƯỚNG DẪN Note across its top, then its nodes in columns:
column = longest in-group dependency depth (sources left); when a group is deeper
than ``max_cols`` the deeper layers are spread evenly over columns 1..max_cols-1.
Inside a column, nodes are ordered by depth, then by the mean y of their placed
in-group predecessors, so wires run mostly left -> right. Only node ``pos`` and the added Notes/groups change.
"""
from __future__ import annotations

import copy
import json
import re
import textwrap

PAD, TITLE_H, ROW_GAP, COL_GAP, GROUP_GAP, TOP = 30, 30, 40, 70, 180, 80
NOTE_MIN_W = 600
NOTE_LINE_H = 22
NOTE_CHAR_W = 8.2


def _assign(nodes: list[dict], groups: list[dict]) -> dict[int, int]:
    all_ids = {n['id'] for n in nodes}
    assigned: dict[int, int] = {}
    for i, g in enumerate(groups):
        if not isinstance(g.get('title'), str) or not g['title'].strip():
            raise ValueError('Each group needs a title')
        if not isinstance(g.get('note'), str) or not g['note'].strip():
            raise ValueError('Each group needs a Vietnamese INPUT -> OUTPUT note')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', g.get('color', '')):
            raise ValueError('color must be #RRGGBB')
        ids = g.get('node_ids', [])
        if not isinstance(ids, list) or any(type(v) is not int for v in ids):
            raise ValueError('node_ids must be integer array')
        if set(ids) - all_ids:
            raise ValueError('Unknown node id in group ' + g['title'])
        for node_id in ids:
            if node_id in assigned:
                raise ValueError('Node assigned to multiple groups: %s' % node_id)
            assigned[node_id] = i
    if set(assigned) != all_ids:
        raise ValueError('Unassigned nodes: ' + str(sorted(all_ids - assigned.keys())))
    return assigned


def note_size(text: str, width: int) -> list[int]:
    chars = max(20, int((width - 20) / NOTE_CHAR_W))
    lines = sum(max(1, len(textwrap.wrap(line, chars)) or 1) for line in text.split('\n'))
    return [width, 40 + NOTE_LINE_H * lines]


def depth_columns(members: list[dict], links: list, max_cols: int) -> tuple[dict, dict]:
    ids = {n['id'] for n in members}
    preds = {i: sorted({l[1] for l in links if l[3] == i and l[1] in ids}) for i in ids}
    memo: dict[int, int] = {}

    def depth(i: int, stack: frozenset = frozenset()) -> int:
        if i in stack:
            raise ValueError('Cycle inside group at node %s' % i)
        if i not in memo:
            memo[i] = 0 if not preds[i] else 1 + max(depth(p, stack | {i}) for p in preds[i])
        return memo[i]

    raw = {i: depth(i) for i in ids}
    deepest = max(raw.values(), default=0)
    if deepest < max_cols:
        return raw, raw
    # Sources keep column 0; deeper layers are spread evenly over the rest.
    return {i: 0 if d == 0 else 1 + d * (max_cols - 1) // (deepest + 1)
            for i, d in raw.items()}, raw


def layout(source: dict, mapping: dict, max_cols: int = 4) -> dict:
    original = source['nodes']
    groups = mapping['groups']
    assigned = _assign(original, groups)
    out = copy.deepcopy(source)
    nodes = out['nodes']
    links = out['links']
    last = max([source.get('last_node_id', 0)] + [n['id'] for n in original])
    out['groups'] = []
    x = 0
    notes = []
    for gi, g in enumerate(groups):
        members = [n for n in nodes if assigned[n['id']] == gi]
        column, raw = depth_columns(members, links, max_cols)
        used = sorted(set(column.values()))
        remap = {c: k for k, c in enumerate(used)}  # no empty columns
        cols = [[n for n in members if remap[column[n['id']]] == k] for k in range(len(used))]
        widths = [max(n['size'][0] for n in col) for col in cols]
        content_w = sum(widths) + COL_GAP * max(0, len(widths) - 1)
        inner_w = max(NOTE_MIN_W, content_w)
        note_text = g['note']
        nsize = note_size(note_text, inner_w)
        y0 = TOP + TITLE_H
        notes.append({'id': last + gi + 1, 'type': 'Note', 'title': 'HƯỚNG DẪN — ' + g['title'],
                      'pos': [x + PAD, y0], 'size': nsize, 'flags': {}, 'order': len(original) + gi,
                      'mode': 0, 'inputs': [], 'outputs': [], 'properties': {},
                      'widgets_values': [note_text]})
        top = y0 + nsize[1] + ROW_GAP + TITLE_H
        ys: dict[int, float] = {}
        bottom = top
        cx = x + PAD
        for k, col in enumerate(cols):
            def key(n: dict) -> tuple:
                ps = [ys[l[1]] for l in links if l[3] == n['id'] and l[1] in ys]
                return (raw[n['id']], sum(ps) / len(ps) if ps else float('inf'), members.index(n))
            cy = top
            for n in (sorted(col, key=key) if k else col):
                n['pos'] = [cx, cy]
                ys[n['id']] = cy
                cy += n['size'][1] + ROW_GAP + TITLE_H
            bottom = max(bottom, cy)
            cx += widths[k] + COL_GAP
        out['groups'].append({'title': g['title'], 'bounding': [x, 0, inner_w + 2 * PAD, bottom - ROW_GAP - TITLE_H + PAD],
                              'color': g['color'], 'font_size': 28, 'flags': {}})
        x += inner_w + 2 * PAD + GROUP_GAP
    height = max(gr['bounding'][3] for gr in out['groups'])
    for gr in out['groups']:  # equal heights read as one row of steps
        gr['bounding'][3] = height
    nodes.extend(notes)
    out['last_node_id'] = last + len(groups)
    return out


def _box(n: dict) -> tuple:
    x, y = n['pos']
    w, h = n['size']
    return x, y - TITLE_H, x + w, y + h


def check(source: dict, result: dict, mapping: dict, max_cols: int = 4) -> dict:
    before, after = source['nodes'], result['nodes']
    count = len(mapping['groups'])
    if len(after) != len(before) + count or len(result.get('groups', [])) != count:
        raise ValueError('Expected original nodes plus exactly one Note per group')
    if json.dumps(source['links']) != json.dumps(result['links']):
        raise ValueError('Links changed')
    for a, b in zip(before, after):
        if {k: v for k, v in a.items() if k != 'pos'} != {k: v for k, v in b.items() if k != 'pos'}:
            raise ValueError('Original node changed beyond position: %s' % a['id'])
    boxes = []
    for n in after:
        x0, y0, x1, y1 = _box(n)
        inside = [g for g in result['groups']
                  if g['bounding'][0] <= x0 and g['bounding'][1] <= y0
                  and x1 <= g['bounding'][0] + g['bounding'][2] and y1 <= g['bounding'][1] + g['bounding'][3]]
        if len(inside) != 1:
            raise ValueError('Node (incl. title bar) must fit exactly one group: %s' % n['id'])
        boxes.append((n['id'], x0, y0, x1, y1))
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
                raise ValueError('Nodes overlap: %s and %s' % (a[0], b[0]))
    heights = {g['bounding'][3] for g in result['groups']}
    if len(heights) != 1:
        raise ValueError('Group heights differ')
    if json.dumps(result, sort_keys=True) != json.dumps(layout(source, mapping, max_cols), sort_keys=True):
        raise ValueError('Output differs from deterministic layout')
    return {'original_nodes': len(before), 'added_notes': count, 'output_nodes': len(after),
            'links': len(result['links']), 'groups': count, 'group_height': heights.pop(),
            'every_node_inside_exactly_one_group_incl_title_bar': True, 'no_node_overlap': True}
