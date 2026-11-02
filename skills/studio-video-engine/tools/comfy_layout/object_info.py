"""Read-only helpers over ComfyUI ``GET /object_info`` (INPUT_TYPES of every node).

Derives, from the live server's own schema, what the LiteGraph frontend serializes:
the ordered widget slots of a node (incl. ``control_after_generate`` and upload
companions, dynamic-combo children), its socket inputs and its outputs.
Only GET endpoints are ever called; nothing is queued, posted or installed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator
from urllib.request import urlopen

CACHE_PATH = Path(__file__).with_name('object_info_cache.json')
DEFAULT_URL = 'http://127.0.0.1:8188'
WIDGET_TYPES = frozenset({'INT', 'FLOAT', 'STRING', 'BOOLEAN', 'COMBO'})
DYNAMIC = 'COMFY_DYNAMICCOMBO_V3'
AUTOGROW = 'COMFY_AUTOGROW_V3'
# Upload companions are frontend-only widgets appended after all real widgets.
# Measured on frontend-saved UI workflows of this machine:
#   LoadImage -> [file, 'image'] (649 nodes), LoadAudio -> [file, ''] (136 nodes).
UPLOAD_COMPANION = {'image_upload': 'image', 'audio_upload': ''}
TYPE_FALLBACK = {'INT': 0, 'FLOAT': 0.0, 'STRING': '', 'BOOLEAN': False}


def get_json(url: str, timeout: float = 60.0) -> dict:
    """GET only. Callers pass read-only endpoints (/object_info, /system_stats)."""
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - local server URL
        return json.loads(response.read().decode('utf-8'))


def refresh_cache(classes: list[str], base_url: str = DEFAULT_URL,
                  path: Path = CACHE_PATH) -> dict:
    """Fetch /object_info, keep the requested classes, record provenance, write cache."""
    raw = urlopen(base_url + '/object_info', timeout=60).read()  # noqa: S310
    full = json.loads(raw.decode('utf-8'))
    stats = get_json(base_url + '/system_stats')
    missing = sorted(set(classes) - set(full))
    cache = {
        'provenance': {
            'url': base_url + '/object_info',
            'fetched_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'comfyui_version': stats.get('system', {}).get('comfyui_version'),
            'full_response_sha256': hashlib.sha256(raw).hexdigest(),
            'full_class_count': len(full),
            'kept_classes': sorted(set(classes) & set(full)),
            'missing_on_server': missing,
            'note': 'Subset of the live response; only GET was used.',
        },
        'nodes': {name: full[name] for name in sorted(set(classes) & set(full))},
    }
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return cache


def load_cache(path: Path = CACHE_PATH) -> dict | None:
    if not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))['nodes']


def _opts(spec: list) -> dict:
    return spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}


def kind_of(spec: list) -> str:
    head = spec[0]
    if isinstance(head, list):
        return 'widget'
    if head == DYNAMIC:
        return 'dynamic'
    if head == AUTOGROW:
        return 'autogrow'
    if head in WIDGET_TYPES and not _opts(spec).get('forceInput'):
        return 'widget'
    return 'socket'


def combo_options(spec: list) -> list | None:
    if isinstance(spec[0], list):
        return list(spec[0])
    if spec[0] == 'COMBO':
        return list(_opts(spec).get('options', []))
    if spec[0] == DYNAMIC:
        return [o['key'] for o in _opts(spec).get('options', [])]
    return None


def default_of(spec: list):
    opts = _opts(spec)
    if 'default' in opts:
        return opts['default']
    options = combo_options(spec)
    if options:
        return options[0]
    head = 'COMBO' if isinstance(spec[0], list) else spec[0]
    return TYPE_FALLBACK.get(head, '')


def _sections(block: dict, order: dict | None) -> Iterator[tuple[str, list, bool]]:
    for section in ('required', 'optional'):
        specs = block.get(section) or {}
        names = (order or {}).get(section) or list(specs)
        for name in names:
            yield name, specs[name], section == 'optional'


def walk_widgets(node: dict, choose: Callable[[dict], object]) -> list[dict]:
    """Ordered widget slots as the frontend serializes them into widgets_values.

``choose(slot)`` is called for every dynamic combo in order and returns the
selected option key, so children are expanded exactly for that selection.
Each slot: name, type, default, options, optional, extra (['control'] when a
control_after_generate value follows it). Upload companions come last with
``companion: True``.
"""
    slots: list[dict] = []
    trailing: list[dict] = []

    def visit(block: dict, order: dict | None, prefix: str) -> None:
        for name, spec, optional in _sections(block, order):
            kind = kind_of(spec)
            full = prefix + name
            if kind not in ('widget', 'dynamic'):
                continue
            opts = _opts(spec)
            extra = ['control'] if opts.get('control_after_generate') else []
            for flag, value in UPLOAD_COMPANION.items():
                if opts.get(flag):
                    trailing.append({'name': '<upload:%s>' % full, 'type': 'UPLOAD', 'default': value,
                                     'options': None, 'optional': True, 'extra': [],
                                     'companion': True})
            slot = {'name': full, 'type': 'COMBO' if isinstance(spec[0], list) else spec[0],
                    'default': default_of(spec), 'options': combo_options(spec),
                    'optional': optional, 'extra': extra}
            slots.append(slot)
            if kind == 'dynamic':
                key = choose(slot)
                option = next((o for o in opts['options'] if o['key'] == key), None)
                if option is None:
                    raise ValueError('Unknown dynamic option %r for %s' % (key, full))
                visit(option.get('inputs', {}), None, full + '.')

    visit(node['input'], node.get('input_order'), '')
    return slots + trailing


def socket_inputs(node: dict) -> list[dict]:
    """Non-widget inputs in frontend order (autogrow templates reported, not expanded)."""
    out = []
    for name, spec, optional in _sections(node['input'], node.get('input_order')):
        kind = kind_of(spec)
        if kind == 'socket':
            out.append({'name': name, 'type': spec[0], 'optional': optional})
        elif kind == 'autogrow':
            tpl = _opts(spec)['template']
            inner = next(iter(tpl['input'].get('required', {}).items()))
            out.append({'name': name, 'type': inner[1][0], 'optional': optional,
                        'autogrow': {'prefix': name + '.' + tpl['prefix'], 'max': tpl['max']}})
    return out


def outputs(node: dict) -> list[dict]:
    return [{'name': n, 'type': t} for n, t in zip(node['output_name'], node['output'])]


def type_accepts(socket_type: str, link_type: str) -> bool:
    """Frontend rule: comma lists accept any member; '*' accepts all."""
    if socket_type == '*' or link_type == '*':
        return True
    return link_type in socket_type.split(',')


def widget_layout(node: dict, values: list) -> list[dict]:
    """Slots for a saved node, resolving dynamic combos from the values themselves."""
    # Two-pass: positions depend on earlier slots only, so resolve greedily.
    resolved: dict[str, object] = {}
    while True:
        slots = walk_widgets(node, lambda s: resolved.get(s['name'], s['default']))
        position, changed = 0, False
        for slot in slots:
            if slot['type'] == DYNAMIC and position < len(values):
                if resolved.get(slot['name'], slot['default']) != values[position]:
                    resolved[slot['name']] = values[position]
                    changed = True
                    break
            position += 1 + len(slot['extra'])
        if not changed:
            return slots
