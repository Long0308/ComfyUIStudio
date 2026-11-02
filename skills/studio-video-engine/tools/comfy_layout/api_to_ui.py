"""Offline API -> LiteGraph conversion driven by live INPUT_TYPES. Never submits a prompt.

Widget order, defaults, ``control_after_generate`` and upload companions come from
the ComfyUI ``GET /object_info`` cache (object_info_cache.json). The audited
snapshot h3_schema.json supplies node sizes and must agree with the live sockets
and outputs, otherwise conversion is refused. Without a cache the snapshot alone
is used (legacy mode). Unknown node types/inputs fail closed.

A widget that is driven by a link keeps its position in ``widgets_values`` with a
placeholder (the INPUT_TYPES default, '' for a STRING), exactly like the frontend
saves it, so every later positional widget value stays on its own widget.
"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import re
import sys


def _sibling(module, alias):
    # Isolated Python (-I) deliberately excludes the script directory from sys.path.
    spec = importlib.util.spec_from_file_location(alias, Path(__file__).with_name(module + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __package__:
    from . import comfy_groups, depth_layout, object_info as oi
else:
    comfy_groups = _sibling('comfy_groups', 'comfy_layout_groups')
    depth_layout = _sibling('depth_layout', 'comfy_layout_depth')
    oi = _sibling('object_info', 'comfy_layout_object_info')


PALETTE = ['#0B4FD9', '#5B9BF5', '#9D9BF5', '#3E8914', '#134611']
SCHEMA_PATH = Path(__file__).with_name('h3_schema.json')
NOTE_TYPES = ('Note', 'MarkdownNote')
UI_SEED_CONTROL = 'fixed'
CACHE = object()  # sentinel: load object_info_cache.json if present


def is_link(value):
    """API wire syntax; literals for these schemas are scalar values."""
    return (isinstance(value, list) and len(value) == 2
            and isinstance(value[0], str) and type(value[1]) is int)


def _schemas(schemas):
    return schemas if schemas is not None else comfy_groups.read(SCHEMA_PATH)['nodes']


def _info(info):
    return oi.load_cache() if info is CACHE else info


def estimate_size(sockets, outputs, widgets):
    return [340, max(60, 30 + 22 * max(sockets, outputs) + 26 * widgets)]


def _pairs(items):
    return [(i['name'], i['type']) for i in items]


def node_schema(kind, schemas, info):
    """Sockets/outputs/size for one type. Live INPUT_TYPES win; snapshot must agree."""
    base = schemas.get(kind)
    live = (info or {}).get(kind)
    if live is None:
        if base is None:
            raise ValueError('Unsupported node type: ' + kind)
        return {'size': base['size'], 'inputs': base['inputs'], 'autogrow': base.get('autogrow', []),
                'outputs': base['outputs'], 'widgets': base['widgets'], 'live': None}
    inputs, autogrow = [], []
    for sock in oi.socket_inputs(live):
        if 'autogrow' in sock:
            autogrow.append({'prefix': sock['autogrow']['prefix'], 'type': sock['type'],
                             'max': sock['autogrow']['max']})
        else:
            port = {'name': sock['name'], 'type': sock['type']}
            if sock['optional']:
                port['shape'] = 7
            inputs.append(port)
    outputs = oi.outputs(live)
    if base is not None:
        if _pairs(base['inputs']) != _pairs(inputs):
            raise ValueError('Snapshot sockets differ from live INPUT_TYPES: ' + kind)
        if _pairs(base['outputs']) != _pairs(outputs):
            raise ValueError('Snapshot outputs differ from live INPUT_TYPES: ' + kind)
        trio = [(a['prefix'], a['type'], a['max']) for a in base.get('autogrow', [])]
        if trio != [(a['prefix'], a['type'], a['max']) for a in autogrow]:
            raise ValueError('Snapshot autogrow differs from live INPUT_TYPES: ' + kind)
    widgets = oi.walk_widgets(live, lambda s: s['default'])
    size = base['size'] if base else estimate_size(len(inputs), len(outputs), len(widgets))
    return {'size': size, 'inputs': inputs, 'autogrow': autogrow, 'outputs': outputs,
            'widgets': None, 'live': live}


def legacy_slots(widgets):
    return [{'name': w['name'], 'type': w['type'], 'default': oi.TYPE_FALLBACK.get(w['type'], ''),
             'options': None, 'optional': False,
             'extra': ['control'] if 'control_after_generate' in w else []} for w in widgets]


def widget_slots(sch, choose):
    if sch['live'] is not None:
        return oi.walk_widgets(sch['live'], choose)
    return legacy_slots(sch['widgets'])


def input_specs(sch, values):
    """Keep native UI slot order; expand only explicitly supplied autogrow ports."""
    ports = copy.deepcopy(sch['inputs'])
    for grow in sch.get('autogrow', []):
        for index in range(grow['max']):
            name = grow['prefix'] + str(index)
            if name in values:
                ports.append({'name': name, 'type': grow['type'], 'shape': 7})
    return ports


def _widget_value(slot, values, live, omitted):
    """(value, serialize?) for one widget slot."""
    name = slot['name']
    if name not in values:
        if live is None:
            omitted.append(name)
            return None, False
        return slot['default'], True  # frontend materializes the INPUT_TYPES default
    if omitted:
        raise ValueError('Widget order gap before ' + name + ': ' + ', '.join(omitted))
    value = values[name]
    if is_link(value):
        if slot['type'] == oi.DYNAMIC:
            raise ValueError('Dynamic combo cannot be linked: ' + name)
        return slot['default'], True  # positional placeholder for the linked widget
    if isinstance(value, (dict, list)):
        raise ValueError('Unsupported non-scalar widget: ' + name)
    return value, True


def _convert_node(node_id, source, schemas, info, order):
    kind, values = source['class_type'], source['inputs']
    if not isinstance(values, dict):
        raise ValueError('API inputs must be an object')
    sch = node_schema(kind, schemas, info)
    ports = input_specs(sch, values)
    slots = widget_slots(sch, lambda s: values.get(s['name'], s['default']))
    known = {p['name'] for p in ports} | {s['name'] for s in slots if not s.get('companion')}
    if set(values) - known:
        raise ValueError('Unknown inputs: ' + str(sorted(set(values) - known)))
    node = {'id': int(node_id), 'type': kind, 'pos': [0, 0],
            'size': copy.deepcopy(sch['size']), 'flags': {},
            'order': order, 'mode': 0, 'inputs': [],
            'outputs': [dict(o, links=None) for o in sch['outputs']],
            'properties': {'Node name for S&R': kind}, 'widgets_values': []}
    if 'title' in source.get('_meta', {}):
        node['title'] = source['_meta']['title']
    for spec in ports:
        if spec['name'] in values and not is_link(values[spec['name']]):
            raise ValueError('Native port must be linked: ' + spec['name'])
        node['inputs'].append(dict(spec, link=None))
    omitted = []
    for slot in slots:
        if slot.get('companion'):
            node['widgets_values'].append(slot['default'])
            continue
        value, keep = _widget_value(slot, values, sch['live'], omitted)
        if not keep:
            continue
        node['inputs'].append({'name': slot['name'], 'type': slot['type'],
                               'widget': {'name': slot['name']}, 'link': None})
        node['widgets_values'].append(value)
        if 'control' in slot['extra']:
            node['widgets_values'].append(UI_SEED_CONTROL)
    return node


def convert(api, schemas=None, info=CACHE):
    """Return UI nodes in source order, with links numbered in slot order.

Every widget slot of the live schema is serialized, in frontend order:
supplied literal -> value; linked -> placeholder; omitted optional -> INPUT_TYPES
default (what the frontend materializes when it opens the node). Legacy mode
(no live schema) keeps omitted optional widgets omitted and refuses order gaps.
"""
    schemas, info = _schemas(schemas), _info(info)
    if not isinstance(api, dict) or not api:
        raise ValueError('Nonempty API graph required')
    graph = {'last_node_id': 0, 'last_link_id': 0, 'nodes': [], 'links': [],
             'groups': [], 'config': {}, 'extra': {}, 'version': 0.4}
    by_id = {}
    for node_id, source in api.items():
        if not isinstance(node_id, str) or not re.fullmatch(r'0|[1-9][0-9]*', node_id):
            raise ValueError('API node IDs must be canonical nonnegative integer strings')
        node = _convert_node(node_id, source, schemas, info, len(graph['nodes']))
        graph['nodes'].append(node)
        by_id[node_id] = node
    for node in graph['nodes']:
        values = api[str(node['id'])]['inputs']
        for dst_slot, port in enumerate(node['inputs']):
            value = values.get(port['name'])
            if not is_link(value):
                continue
            src_id, src_slot = value
            if src_id not in by_id:
                raise ValueError('Dangling source node: ' + src_id)
            outputs = by_id[src_id]['outputs']
            if not 0 <= src_slot < len(outputs):
                raise ValueError('Invalid source slot: ' + str(value))
            output = outputs[src_slot]
            if not oi.type_accepts(port['type'], output['type']):
                raise ValueError('Link type mismatch: ' + port['name'])
            link_id = len(graph['links']) + 1
            graph['links'].append([link_id, int(src_id), src_slot,
                                   node['id'], dst_slot, output['type']])
            port['link'] = link_id
            if output['links'] is None:
                output['links'] = []
            output['links'].append(link_id)
    graph['last_node_id'] = max(n['id'] for n in graph['nodes'])
    graph['last_link_id'] = len(graph['links'])
    comfy_groups.nodes(graph)
    return graph


def verify_links(graph):
    """Both endpoints of every wire agree with the link table; no stray references."""
    indexed = {n['id']: n for n in comfy_groups.nodes(graph)}
    links = {link[0]: link for link in graph['links']}
    if len(links) != len(graph['links']):
        raise ValueError('Duplicate link IDs')
    for link_id, (_, src_id, src_slot, dst_id, dst_slot, kind) in links.items():
        if src_id not in indexed or dst_id not in indexed:
            raise ValueError('Link references missing node: %s' % link_id)
        dst_inputs = indexed[dst_id]['inputs']
        if not 0 <= dst_slot < len(dst_inputs) or dst_inputs[dst_slot]['link'] != link_id \
                or not oi.type_accepts(dst_inputs[dst_slot]['type'], kind):
            raise ValueError('Link destination mismatch: %s' % link_id)
        outs = indexed[src_id]['outputs']
        if not 0 <= src_slot < len(outs) or outs[src_slot]['type'] != kind \
                or link_id not in (outs[src_slot]['links'] or []):
            raise ValueError('Link source mismatch: %s' % link_id)
    for node in graph['nodes']:
        for port in node.get('inputs', []):
            if port.get('link') is not None and port['link'] not in links:
                raise ValueError('Input references unknown link: %s' % port['link'])
        for slot, output in enumerate(node.get('outputs', [])):
            expected = [k for k, link in links.items() if link[1:3] == [node['id'], slot]]
            if sorted(output['links'] or []) != expected:
                raise ValueError('Output link list mismatch')
    return indexed, links


def resolve_source(indexed, links, src_id, src_slot, seen=()):
    """Frontend bypass (mode 4): pass through the input of the output's type."""
    node = indexed[src_id]
    mode = node.get('mode', 0)
    if mode == 0:
        return [str(src_id), src_slot]
    if mode != 4 or src_id in seen:
        return None  # muted (2) source: the frontend drops the wire
    out_type = node['outputs'][src_slot]['type']
    sockets = [(i, p) for i, p in enumerate(node['inputs']) if 'widget' not in p]
    same = [p for i, p in sockets if i == src_slot and p['type'] == out_type]
    match = same or [p for _, p in sockets if p['type'] == out_type]
    if not match or match[0]['link'] is None:
        return None
    _, up_id, up_slot = links[match[0]['link']][:3]
    return resolve_source(indexed, links, up_id, up_slot, seen + (src_id,))


def _node_api(node, schemas, info, indexed, links):
    sch = node_schema(node['type'], schemas, info)
    wv = node['widgets_values']
    legacy = sch['live'] is None
    slots = legacy_slots(sch['widgets']) if legacy else oi.widget_layout(sch['live'], wv)
    ports = {}
    for port in node['inputs']:
        if port['name'] in ports:
            raise ValueError('Duplicate input: ' + port['name'])
        ports[port['name']] = port
    values = {}
    for port in node['inputs']:
        if 'widget' not in port and port['link'] is not None:
            resolved = resolve_source(indexed, links, *links[port['link']][1:3])
            if resolved is not None:
                values[port['name']] = resolved
    index = 0
    for slot in slots:
        width = 1 + len(slot['extra'])
        if slot.get('companion'):
            index += 1
            continue
        port = ports.get(slot['name'])
        if legacy and port is None:
            continue  # legacy graphs omit unsupplied optional widgets
        if port is not None and port['link'] is not None:
            resolved = resolve_source(indexed, links, *links[port['link']][1:3])
            if resolved is not None:
                values[slot['name']] = resolved
        else:
            if index >= len(wv):
                raise ValueError('Missing widget value: ' + slot['name'])
            values[slot['name']] = wv[index]
        if 'control' in slot['extra'] and wv[index + 1] != UI_SEED_CONTROL:
            raise ValueError('Seed control must remain fixed for API equivalence')
        index += width
    if index != len(wv):
        raise ValueError('Unconsumed widget values on node %s' % node['id'])
    return {'class_type': node['type'], 'inputs': values}


def to_api(graph, schemas=None, info=CACHE):
    """Reconstruct API inputs from UI slots, values and wires (bypass/mute resolved).

No embedded original API payload is used. Layout Note nodes are not executable.
"""
    schemas, info = _schemas(schemas), _info(info)
    indexed, links = verify_links(graph)
    return {str(n['id']): _node_api(n, schemas, info, indexed, links) for n in graph['nodes']
            if n['type'] not in NOTE_TYPES and n.get('mode', 0) == 0}


def materialized(rt, source, info=CACHE):
    """Source inputs must survive exactly; extra keys must equal INPUT_TYPES defaults.

Returns {node_id: [names]} of defaults the UI materialized (frontend behaviour).
"""
    info = _info(info)
    if set(rt) != set(source):
        raise ValueError('API round trip node set differs')
    extra = {}
    for key, node in source.items():
        got = rt[key]
        if got['class_type'] != node['class_type']:
            raise ValueError('API round trip type differs: ' + key)
        for name, value in node['inputs'].items():
            if name not in got['inputs'] or got['inputs'][name] != value:
                raise ValueError('API round trip differs: %s.%s' % (key, name))
        added = sorted(set(got['inputs']) - set(node['inputs']))
        if not added:
            continue
        live = (info or {}).get(node['class_type'])
        if live is None:
            raise ValueError('Unexpected inputs without live schema: ' + key)
        defaults = {s['name']: s['default'] for s in
                    oi.walk_widgets(live, lambda s: got['inputs'].get(s['name'], s['default']))}
        for name in added:
            if name not in defaults or got['inputs'][name] != defaults[name]:
                raise ValueError('Added input is not the INPUT_TYPES default: %s.%s' % (key, name))
        extra[key] = added
    return extra


def build(api, mapping, schemas=None, info=CACHE, modes=None, max_cols=4):
    """Convert, set modes, lay out in depth columns (Blue Web) and check preservation.

``modes`` maps node id -> 0/2/4. Use build_checked() for the API round trip.
"""
    info = _info(info)
    modes = modes or {}
    mapping = copy.deepcopy(mapping)
    if len(mapping['groups']) != len(PALETTE):
        raise ValueError('Exactly five groups required')
    for group, color in zip(mapping['groups'], PALETTE):
        group['color'] = color
    ui = convert(api, schemas, info)
    for node in ui['nodes']:
        mode = modes.get(str(node['id']), 0)
        if mode not in (0, 2, 4):
            raise ValueError('Mode must be 0, 2 or 4')
        node['mode'] = mode
    grouped = depth_layout.layout(ui, mapping, max_cols)
    report = depth_layout.check(ui, grouped, mapping, max_cols)
    return grouped, report


def build_checked(api, mapping, expected_api=None, **kwargs):
    """build() plus API round trip against ``expected_api`` (defaults to ``api``)."""
    grouped, report = build(api, mapping, **kwargs)
    info = _info(kwargs.get('info', CACHE))
    expected = {k: {'class_type': n['class_type'], 'inputs': n['inputs']}
                for k, n in (expected_api or api).items()}
    report['materialized_defaults'] = materialized(
        to_api(grouped, kwargs.get('schemas'), info), expected, info)
    report['api_round_trip_equal'] = True
    return grouped, report


def write_new(path, graph):
    """Exclusive create: never truncate or replace an existing workflow."""
    payload = json.dumps(graph, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('group_map', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--schema', type=Path, default=SCHEMA_PATH)
    parser.add_argument('--check', action='store_true', help='Read-only deterministic check')
    args = parser.parse_args(argv)
    try:
        result, report = build_checked(comfy_groups.read(args.source),
                                       comfy_groups.read(args.group_map),
                                       schemas=comfy_groups.read(args.schema)['nodes'])
        if args.check:
            if not comfy_groups.equal(result, comfy_groups.read(args.output)):
                raise ValueError('Output differs from deterministic conversion')
        else:
            if args.output.resolve() in {args.source.resolve(), args.group_map.resolve(), args.schema.resolve()}:
                raise ValueError('Output must be a new file')
            write_new(args.output, result)
        report.update(source_sha256=comfy_groups.sha(args.source),
                      schema_sha256=comfy_groups.sha(args.schema),
                      group_map_sha256=comfy_groups.sha(args.group_map),
                      output_sha256=comfy_groups.sha(args.output))
        print(json.dumps(report, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
