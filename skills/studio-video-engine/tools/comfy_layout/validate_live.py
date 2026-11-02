"""Validate a ComfyUI UI workflow against live INPUT_TYPES (GET /object_info only).

Per node: type exists on the server; outputs equal the live outputs; every socket
input is a live socket (or autogrow port) of the same type; widgets_values length
equals the live widget slot count (linked placeholders, seed control and upload
companions included); combo values are live options ('' = blank ĐIỀN placeholder,
reported as a warning). Per link: both endpoints exist and the link type equals
the source output type and is accepted by the destination input.
--selftest breaks copies of the graph and requires every break to be reported.

Usage: python -I validate_live.py GRAPH.json [--live URL | --cache PATH] [--selftest]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

_spec = importlib.util.spec_from_file_location('comfy_layout_object_info',
                                               Path(__file__).with_name('object_info.py'))
oi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oi)

NOTE_TYPES = ('Note', 'MarkdownNote')
MATCHTYPE = 'COMFY_MATCHTYPE_V3'
MUTE, BYPASS = 2, 4
SWITCH_TYPES = ('ComfySwitchNode',)  # lazy If/Else: only the selected side runs (comfy_extras/nodes_logic.py)
CONTROL_VALUES = ('fixed', 'increment', 'decrement', 'randomize')
# Widgets the SERVER validates with VALIDATE_INPUTS instead of the combo list (measured in
# ComfyUI 0.41.0 source: nodes.py LoadImage.VALIDATE_INPUTS(s, image) -> exists_annotated_filepath;
# LoadImageMask inherits it; execution.py:1032 skips the combo check for such inputs).
# /object_info does not expose this, so the rule is opt-in: only with an input dir, and the
# file must really exist inside it (path traversal refused), else it stays an error.
FILE_VALIDATED_WIDGETS = {('LoadImage', 'image'), ('LoadImageMask', 'image')}
DEFAULT_INPUT_DIR = Path(__file__).resolve().parents[5] / 'production-local' / 'ComfyUI' / 'input'


def file_in_input_dir(value: str, input_dir: Path | None) -> bool:
    if input_dir is None or not isinstance(value, str) or not value or value.endswith(']'):
        return False
    base = input_dir.resolve()
    target = (base / value).resolve()
    return target.is_relative_to(base) and target.is_file()


def _match(live_type: str, ui_type: str, matched: list) -> bool:
    """MATCHTYPE ports (ComfySwitchNode) are saved by frontend 1.55.17 as the connected concrete type
    ('*' while free; measured 2026-10-31). Every such port of one node must agree on that type."""
    if live_type != MATCHTYPE:
        return live_type == ui_type
    if ui_type != '*':
        matched.append(ui_type)
    return True


def _node_errors(n: dict, live: dict, linked: set, errors: list, warnings: list,
                 input_dir: Path | None = None) -> None:
    nid = '%s(%s)' % (n['id'], n['type'])
    matched: list = []
    want_out = [(o['name'], o['type']) for o in oi.outputs(live)]
    got_out = [(o['name'], o['type']) for o in n.get('outputs', [])]
    if len(got_out) != len(want_out) or any(g[0] != w[0] or not _match(w[1], g[1], matched)
                                            for g, w in zip(got_out, want_out)):
        errors.append('%s outputs %s != live %s' % (nid, got_out, want_out))
    socks = {s['name']: s for s in oi.socket_inputs(live)}
    grows = [s['autogrow'] | {'type': s['type']} for s in socks.values() if 'autogrow' in s]
    wv = n.get('widgets_values') or []
    try:
        slots = oi.widget_layout(live, wv)
    except (ValueError, KeyError) as exc:
        errors.append('%s widget layout: %s' % (nid, exc))
        return
    by_name = {s['name']: s for s in slots if not s.get('companion')}
    for port in n.get('inputs', []):
        name, kind = port['name'], port['type']
        if 'widget' in port:
            if name not in by_name:
                errors.append('%s widget input %s not a live widget' % (nid, name))
            elif by_name[name]['type'] != kind:
                errors.append('%s widget %s type %s != live %s' % (nid, name, kind, by_name[name]['type']))
            continue
        if name in socks and 'autogrow' not in socks[name]:
            if not _match(socks[name]['type'], kind, matched):
                errors.append('%s socket %s type %s != live %s' % (nid, name, kind, socks[name]['type']))
        elif not any(name.startswith(g['prefix']) and name[len(g['prefix']):].isdigit()
                     and int(name[len(g['prefix']):]) < g['max'] and g['type'] == kind for g in grows):
            errors.append('%s socket %s not in live INPUT_TYPES' % (nid, name))
    if len(set(matched)) > 1:
        errors.append('%s MATCHTYPE ports disagree: %s' % (nid, sorted(set(matched))))
    count = sum(1 + len(s['extra']) for s in slots)
    if count != len(wv):
        errors.append('%s widgets_values len %d != live widget slots %d %s'
                      % (nid, len(wv), count, [s['name'] for s in slots]))
        return
    index = 0
    for slot in slots:
        value = wv[index]
        if slot.get('companion'):
            if value != slot['default']:
                warnings.append('%s upload companion %r != %r' % (nid, value, slot['default']))
        elif (n['id'], slot['name']) in linked:
            pass  # placeholder for a linked widget; its value is never used
        elif (slot['options'] is not None and value not in slot['options']
              and (n['type'], slot['name']) in FILE_VALIDATED_WIDGETS and file_in_input_dir(value, input_dir)):
            warnings.append('%s %s=%r not in the top-level combo list; accepted because the server validates it '
                            'with VALIDATE_INPUTS and the file exists under %s' % (nid, slot['name'], value, input_dir))
        elif slot['options'] is not None and value not in slot['options']:
            msg = '%s %s=%r not in live options (%d)' % (nid, slot['name'], value, len(slot['options']))
            (warnings if value == '' else errors).append(msg + (' — blank ĐIỀN placeholder' if value == '' else ''))
        if 'control' in slot['extra'] and wv[index + 1] not in CONTROL_VALUES:
            errors.append('%s control value %r' % (nid, wv[index + 1]))
        index += 1 + len(slot['extra'])


def bypass_errors(n: dict) -> list:
    """A bypassed (mode 4) node forwards, for each wired output, a LINKED socket input of the same
    type (frontend bypass). Without one the wire is silently dropped: such a node must be muted
    (mode 2) instead, which states the intent. (Critic CR-V003, 2026-10-31.)"""
    linked_types = {p['type'] for p in n.get('inputs', []) if 'widget' not in p and p.get('link') is not None}
    return ['%s(%s) bypassed (mode 4) but output %s (%s) has no linked same-type input to pass through — '
            'use mode 2 (mute)' % (n['id'], n['type'], o['name'], o['type'])
            for o in n.get('outputs', []) if o.get('links') and o['type'] not in linked_types]


def _resolve_source(nodes: dict, links: dict, lid: int) -> dict | None:
    """Node that really feeds link ``lid`` after frontend bypass forwarding (mode 4 passes the first
    LINKED input of the output's type). None = the chain dead-ends in a bypassed node."""
    seen = set()
    link = links.get(lid)
    while link is not None:
        node = nodes.get(link[1])
        if node is None or node.get('mode', 0) != BYPASS:
            return node
        if node['id'] in seen:
            return None
        seen.add(node['id'])
        kind = node['outputs'][link[2]]['type']
        port = next((p for p in node.get('inputs', []) if 'widget' not in p and p['type'] == kind
                     and p.get('link') is not None), None)
        link = links.get(port['link']) if port else None
    return None


def _required_names(live: dict, wv: list) -> set:
    names = {s['name'] for s in oi.socket_inputs(live) if not s['optional']}
    try:
        names |= {s['name'] for s in oi.widget_layout(live, wv) if not s['optional'] and not s.get('companion')}
    except (ValueError, KeyError):
        pass
    return names


def mute_errors(graph: dict, info: dict) -> list:
    """Measured on frontend 1.55.17 (graphToPrompt, 2026-10-31): an input linked from a MUTED (mode 2)
    node is deleted from the API prompt. On a REQUIRED input of an active node the server then refuses
    the output ('Required input is missing'); on an OPTIONAL input (switch sides) it is simply absent."""
    nodes = {n['id']: n for n in graph['nodes']}
    links = {l[0]: l for l in graph['links']}
    errors = []
    for n in graph['nodes']:
        live = info.get(n['type'])
        if n.get('mode', 0) != 0 or n['type'] in NOTE_TYPES or live is None:
            continue
        required = _required_names(live, n.get('widgets_values') or [])
        for port in n.get('inputs', []):
            if port.get('link') is None or port['name'] not in required:
                continue
            src = _resolve_source(nodes, links, port['link'])
            if src is not None and src.get('mode', 0) == MUTE:
                errors.append('%s(%s) required input %s is fed by MUTED node %s(%s) %r — the frontend drops the '
                              'link and the server refuses the output' % (n['id'], n['type'], port['name'],
                                                                          src['id'], src['type'], src.get('title')))
    return errors


def switch_errors(graph: dict) -> list:
    """An active ComfySwitchNode returns None when its SELECTED side is absent (unlinked, or fed by a muted
    node); the next node then fails at run time. The unselected side may be muted (lazy + optional)."""
    nodes = {n['id']: n for n in graph['nodes']}
    links = {l[0]: l for l in graph['links']}
    errors = []
    for n in graph['nodes']:
        if n['type'] not in SWITCH_TYPES or n.get('mode', 0) != 0:
            continue
        ports = {p['name']: p for p in n.get('inputs', [])}
        if ports.get('switch', {}).get('link') is not None:
            continue  # switch driven by a link: not decidable offline
        value = bool((n.get('widgets_values') or [False])[0])
        side = 'on_true' if value else 'on_false'
        lid = ports.get(side, {}).get('link')
        src = _resolve_source(nodes, links, lid) if lid is not None else None
        if src is None or src.get('mode', 0) == MUTE:
            errors.append('%s(%s) %r switch=%s selects %s, which is %s — output would be None'
                          % (n['id'], n['type'], n.get('title'), value, side,
                             'unlinked' if src is None else 'fed by MUTED node %s' % src['id']))
    return errors


GENERATORS = ('CodexOAuthImageLane', 'SamplerCustomAdvanced')


def _upstream_live(nodes: dict, links: dict, start: dict) -> set:
    """Ids reachable upstream of ``start`` through links whose source is not muted; a bypassed node only
    forwards its linked input of the followed output's type (frontend bypass)."""
    seen, stack = set(), [(start, None)]
    while stack:
        node, kind = stack.pop()
        if node['id'] in seen and kind is None:
            continue
        seen.add(node['id'])
        bypassed = node.get('mode', 0) == BYPASS
        for port in node.get('inputs', []):
            if port.get('link') is None or (bypassed and port['type'] != kind):
                continue
            link = links.get(port['link'])
            src = nodes.get(link[1]) if link else None
            if src is None or src.get('mode', 0) == MUTE:
                continue
            stack.append((src, src['outputs'][link[2]]['type'] if src.get('mode', 0) == BYPASS else None))
    return seen


def wardrobe_errors(graph: dict) -> tuple[list, bool]:
    """NEWTECONS wardrobe rule (user 31/10, graphs with extra.newtecons_wardrobe): every ACTIVE generator must
    have an active REQUIRED wardrobe anchor (LoadImage, properties.nt_wardrobe_anchor='required') upstream.
    Returns (errors, blocked); blocked = a required anchor is blank (the server will refuse the run)."""
    nodes = {n['id']: n for n in graph['nodes']}
    links = {l[0]: l for l in graph['links']}
    anchors = {n['id'] for n in graph['nodes'] if n.get('properties', {}).get('nt_wardrobe_anchor') == 'required'}
    errors = []
    if not anchors:
        return ['NEWTECONS wardrobe graph has no required wardrobe anchor (nt_wardrobe_anchor)'], True
    for n in graph['nodes']:
        if n['type'] not in GENERATORS or n.get('mode', 0) != 0:
            continue
        ports = {p['name']: p for p in n.get('inputs', [])}
        if n['type'] == 'CodexOAuthImageLane' and 'context' in ports:
            # NODE-CONTRACT (codex_lane_bridge 31/10): the bridge attaches the sha-checked preset of `context`;
            # non-empty refs REPLACE that preset, so refs must stay unlinked for the preset to count.
            names = [p['name'] for p in n['inputs'] if 'widget' in p]
            value = (n.get('widgets_values') or [])[names.index('context')] if 'context' in names else ''
            if ports.get('refs', {}).get('link') is not None:
                errors.append('%s(%s) refs linked: they REPLACE the wardrobe preset of context %r'
                              % (n['id'], n['type'], value))
            elif not value:
                errors.append('%s(%s) runs with ZERO wardrobe refs (context empty)' % (n['id'], n['type']))
            continue
        live = [a for a in _upstream_live(nodes, links, n) & anchors if nodes[a].get('mode', 0) == 0]
        if not live:
            errors.append('%s(%s) %r runs with ZERO wardrobe refs (no active required anchor upstream)'
                          % (n['id'], n['type'], n.get('title')))
    blocked = any(not (nodes[a].get('widgets_values') or [''])[0] for a in anchors)
    return errors, blocked


def check(graph: dict, info: dict, input_dir: Path | None = None) -> dict:
    errors, warnings = [], []
    nodes = {}
    for n in graph['nodes']:
        if n['id'] in nodes:
            errors.append('duplicate node id %s' % n['id'])
        nodes[n['id']] = n
        if n.get('mode', 0) not in (0, 2, 4):
            errors.append('node %s mode %r' % (n['id'], n.get('mode')))
    linked = set()
    for link in graph['links']:
        lid, src, s_slot, dst, d_slot, kind = link
        if src not in nodes or dst not in nodes:
            errors.append('link %s references missing node' % lid)
            continue
        outs, ins = nodes[src].get('outputs', []), nodes[dst].get('inputs', [])
        if not 0 <= s_slot < len(outs) or not 0 <= d_slot < len(ins):
            errors.append('link %s references missing slot' % lid)
            continue
        if outs[s_slot]['type'] != kind or not oi.type_accepts(ins[d_slot]['type'], kind):
            errors.append('link %s type %s: out %s -> in %s' % (lid, kind, outs[s_slot]['type'], ins[d_slot]['type']))
        if ins[d_slot].get('link') != lid or lid not in (outs[s_slot].get('links') or []):
            errors.append('link %s not mirrored on both endpoints' % lid)
        if 'widget' in ins[d_slot]:
            linked.add((dst, ins[d_slot]['name']))
    for n in graph['nodes']:
        if n.get('mode', 0) == 4 and n['type'] not in NOTE_TYPES:
            errors.extend(bypass_errors(n))
    types = {}
    for n in graph['nodes']:
        if n['type'] in NOTE_TYPES:
            continue
        types[n['type']] = types.get(n['type'], 0) + 1
        live = info.get(n['type'])
        if live is None:
            errors.append('node %s type %s does not exist on the server' % (n['id'], n['type']))
            continue
        _node_errors(n, live, linked, errors, warnings, input_dir)
    errors.extend(mute_errors(graph, info))
    errors.extend(switch_errors(graph))
    blocked = None
    if (graph.get('extra') or {}).get('newtecons_wardrobe'):
        w_errors, blocked = wardrobe_errors(graph)
        errors.extend(w_errors)
        if blocked:
            warnings.append('wardrobe: chưa có bộ neo — a required anchor (NEO A/B) is blank; the server refuses '
                            'every generation output until the presets fill it')
    char_blocked = None
    chars = (graph.get('extra') or {}).get('newtecons_characters')
    if chars:
        by_id = {n['id']: n for n in graph['nodes']}
        char_blocked = any(not (by_id[i].get('widgets_values') or [''])[0] for i in chars.get('required', []) if i in by_id)
        if char_blocked:
            warnings.append('characters: chưa có ảnh nhân vật — MẶT 1 / DÁNG 1 blank; the server refuses the LOCAL '
                            'generation (never filled from reference-library)')
    return {'wardrobe_blocked': blocked, 'character_blocked': char_blocked,'ok': not errors, 'errors': errors, 'warnings': warnings,
            'nodes': len(nodes), 'executable_nodes': sum(types.values()),
            'notes': len(nodes) - sum(types.values()), 'links': len(graph['links']),
            'groups': len(graph.get('groups', [])), 'node_types': len(types),
            'modes': {str(m): sum(1 for n in graph['nodes'] if n.get('mode', 0) == m) for m in (0, 2, 4)}}


def selftest(graph: dict, info: dict, applied: list | None = None) -> list:
    """Every mutation must be reported; returns names of breaks that slipped through. Names of the
    mutations that could be applied to this graph are appended to ``applied`` (others are n/a)."""
    execs = [n for n in graph['nodes'] if n['type'] not in NOTE_TYPES]
    with_wv = next(n for n in execs if n.get('widgets_values'))
    combo = next((n for n in execs for s in oi.widget_layout(info[n['type']], n['widgets_values'])
                  if s['options'] and not s.get('companion') and n['widgets_values']), None)

    def drop_widget(g):
        next(n for n in g['nodes'] if n['id'] == with_wv['id'])['widgets_values'].pop()

    def extra_widget(g):
        next(n for n in g['nodes'] if n['id'] == with_wv['id'])['widgets_values'].append(0)

    def unknown_type(g):
        next(n for n in g['nodes'] if n['id'] == execs[0]['id'])['type'] = 'NoSuchNodeXYZ'

    def link_type(g):
        g['links'][0][5] = 'NOSUCHTYPE'

    def output_rename(g):
        node = next(n for n in g['nodes'] if n.get('outputs'))
        node['outputs'][0]['type'] = 'NOSUCHTYPE'

    def bad_combo(g):
        node = next(n for n in g['nodes'] if n['id'] == combo['id'])
        slots = oi.widget_layout(info[node['type']], node['widgets_values'])
        index = 0
        for s in slots:
            if s['options'] and not s.get('companion'):
                node['widgets_values'][index] = 'no-such-option.safetensors'
                return
            index += 1 + len(s['extra'])

    def bypass_no_passthrough(g):
        node = next(n for n in g['nodes'] if n['type'] not in NOTE_TYPES and any(
            o.get('links') and o['type'] not in {p['type'] for p in n.get('inputs', []) if 'widget' not in p}
            for o in n.get('outputs', [])))
        node['mode'] = 4

    def mute_required_source(g):
        """Mute an active node that feeds a REQUIRED input of another active node."""
        nodes = {n['id']: n for n in g['nodes']}
        for lid, src, _s, dst, d_slot, _k in g['links']:
            s, d = nodes[src], nodes[dst]
            if (s.get('mode', 0) == 0 and d.get('mode', 0) == 0 and d['type'] not in NOTE_TYPES
                    and d['inputs'][d_slot]['name'] in _required_names(info[d['type']], d.get('widgets_values') or [])):
                s['mode'] = MUTE
                return True
        return False

    def switch_selects_muted(g):
        """Flip an active switch whose other side is muted/unlinked, so the dead side is selected."""
        for n in g['nodes']:
            if n['type'] in SWITCH_TYPES and n.get('mode', 0) == 0 and n.get('widgets_values'):
                n['widgets_values'][0] = not n['widgets_values'][0]
                if switch_errors(g):
                    return True
                n['widgets_values'][0] = not n['widgets_values'][0]
        return False  # no switch with a dead side in this graph: mutation not applicable

    missed = []
    for f in (drop_widget, extra_widget, unknown_type, link_type, output_rename, bad_combo, bypass_no_passthrough,
              mute_required_source, switch_selects_muted):
        broken = copy.deepcopy(graph)
        if f(broken) is False:
            continue
        if applied is not None:
            applied.append(f.__name__)
        if check(broken, info)['ok']:
            missed.append(f.__name__)
    return missed


EXTRA_SCHEMA = Path(__file__).with_name('object_info_extra.json')


def load_cache_with_extra(cache: Path = oi.CACHE_PATH, extra: Path = EXTRA_SCHEMA) -> dict | None:
    """object_info_cache.json plus the classes in object_info_extra.json (fetched later from the same
    server, own provenance). The main cache is never rewritten: its LoadImage option list is a frozen
    measurement other tests rely on."""
    info = oi.load_cache(cache)
    if info is None:
        return None
    extra = Path(extra)
    # object_info_extra.json first, then object_info_extra_<tag>.json (each builder version pins its own file)
    for path in [extra] + sorted(extra.parent.glob(extra.stem + '_*' + extra.suffix)):
        if not path.is_file():
            continue
        add = json.loads(path.read_text(encoding='utf-8-sig'))['nodes']
        clash = sorted(set(add) & set(info))
        if clash:
            raise ValueError('%s repeats known classes: %s' % (path.name, clash))
        info = {**info, **add}
    return info


def load_info(args) -> tuple[dict, str]:
    if args.live:
        return oi.get_json(args.live.rstrip('/') + '/object_info'), 'live ' + args.live
    return load_cache_with_extra(Path(args.cache)), 'cache ' + str(args.cache) + ' + ' + EXTRA_SCHEMA.name


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('graph', type=Path)
    p.add_argument('--live', help='ComfyUI base URL, e.g. http://127.0.0.1:8188 (GET only)')
    p.add_argument('--cache', type=Path, default=oi.CACHE_PATH)
    p.add_argument('--selftest', action='store_true')
    p.add_argument('--input-dir', type=Path, default=DEFAULT_INPUT_DIR,
                   help='host path of ComfyUI input/ for LoadImage subfolder values (VALIDATE_INPUTS rule)')
    p.add_argument('--no-input-dir', action='store_true', help='disable the VALIDATE_INPUTS file rule')
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    raw = a.graph.read_bytes()
    graph = json.loads(raw.decode('utf-8-sig'))
    info, source = load_info(a)
    input_dir = None if a.no_input_dir or not a.input_dir.is_dir() else a.input_dir
    report = check(graph, info, input_dir)
    report.update(graph=str(a.graph), sha256=hashlib.sha256(raw).hexdigest(), object_info=source,
                  object_info_classes=len(info), input_dir=str(input_dir) if input_dir else None)
    if a.selftest:
        applied: list = []
        report['selftest_missed'] = selftest(graph, info, applied)
        report['selftest_applied'] = applied
        report['ok'] = report['ok'] and not report['selftest_missed']
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
