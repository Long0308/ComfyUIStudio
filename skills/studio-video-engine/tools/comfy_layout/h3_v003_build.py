"""Build NEWTECONS_H3_R2V_LIVE_ACTION_v003_grouped.json offline (v001 API + 1080p branch).

Adds group 04 LÊN 1080P with real core nodes: 21/22 BYPASSED (mode 4, IMAGE passes through),
20 UpscaleModelLoader MUTED (mode 2: it has no input to pass through; critic CR-V003):
  VAEDecode(15) -> ImageUpscaleWithModel(21) <- UpscaleModelLoader(20, RealESRGAN_x4plus.pth)
               -> ImageScale(22, lanczos 1920x1080, crop center) -> CreateVideo(17).images
Bypassed, the frontend passes 15's frames straight to 17, so the executed API
equals v001 (checked below); enabled, frames go through the upscale.
No v003 API file is written on purpose: an API JSON cannot carry 'bypass' and
would run the upscale if submitted. Exclusive create; never POSTs, never queues.

Usage: python -I h3_v003_build.py V001_API.json GROUP_MAP.json OUTPUT.json [--check]
"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys

_spec = importlib.util.spec_from_file_location('wf_ui_converter', Path(__file__).with_name('api_to_ui.py'))
conv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conv)

BYPASS = 4
UPSCALE_MODEL = 'RealESRGAN_x4plus.pth'
UPSCALE_NODES = {
    '20': {'class_type': 'UpscaleModelLoader', 'inputs': {'model_name': UPSCALE_MODEL},
           '_meta': {'title': 'RealESRGAN x4 — TẮT (mute), chưa nghiệm thu NEWTECONS'}},
    '21': {'class_type': 'ImageUpscaleWithModel', 'inputs': {'upscale_model': ['20', 0], 'image': ['15', 0]},
           '_meta': {'title': 'Upscale x4 864×480 → 3456×1920 — TẮT (bypass)'}},
    '22': {'class_type': 'ImageScale',
           'inputs': {'image': ['21', 0], 'upscale_method': 'lanczos', 'width': 1920, 'height': 1080,
                      'crop': 'center'},
           '_meta': {'title': 'Về 1920×1080, crop center — TẮT (bypass)'}},
}
MUTE = 2
# 20 has no UPSCALE_MODEL input: bypass would silently drop its wire, so it is muted.
MODES = {'20': MUTE, '21': BYPASS, '22': BYPASS}


def v003_api(v001):
    """v001 + upscale nodes inserted before CreateVideo; CreateVideo.images <- 22."""
    out = {}
    for key, node in v001.items():
        if key == '17':
            out.update(copy.deepcopy(UPSCALE_NODES))
        out[key] = copy.deepcopy(node)
    out['17']['inputs']['images'] = ['22', 0]
    return out


def build(v001, mapping):
    api = v003_api(v001)
    graph, report = conv.build(api, mapping, modes=MODES)
    info = conv.oi.load_cache()
    # 1) Bypassed (as saved): executed API == v001 (+ INPUT_TYPES defaults only).
    expected = {k: {'class_type': n['class_type'], 'inputs': n['inputs']} for k, n in v001.items()}
    report['bypassed_materialized_defaults'] = conv.materialized(conv.to_api(graph), expected, info)
    # 2) Enabled: frames VAEDecode -> upscale -> scale -> CreateVideo.
    enabled = copy.deepcopy(graph)
    for node in enabled['nodes']:
        node['mode'] = 0
    rt = conv.to_api(enabled)
    full = {k: {'class_type': n['class_type'], 'inputs': n['inputs']} for k, n in api.items()}
    report['enabled_materialized_defaults'] = conv.materialized(rt, full, info)
    chain = [rt['21']['inputs']['image'], rt['22']['inputs']['image'], rt['17']['inputs']['images']]
    if chain != [['15', 0], ['21', 0], ['22', 0]]:
        raise ValueError('Enabled upscale chain not wired 15 -> 21 -> 22 -> 17: %s' % chain)
    report['enabled_chain'] = '15 VAEDecode -> 21 ImageUpscaleWithModel -> 22 ImageScale -> 17 CreateVideo'
    graph['extra'] = {
        'ds': {'scale': 0.42, 'offset': [0, 0]},
        'workflow_metadata': {'title': 'NEWTECONS H3 R2V LIVE ACTION v003 — template, chưa chạy, chưa qualified',
                              'version': 3},
        'newtecons_h3': {'domain': 'newtecons_live_action', 'status': 'TEMPLATE_NOT_RUN',
                         'upscale_1080p': 'OFF_NOT_QUALIFIED_FOR_NEWTECONS (20 muted, 21/22 bypassed)',
                         'supersedes': 'NEWTECONS_H3_R2V_LIVE_ACTION_v002_grouped.json (kept; its H3 node '
                                       'widgets_values lacked the linked-prompt placeholder)'}}
    return graph, report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('group_map', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--check', action='store_true')
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        graph, report = build(conv.comfy_groups.read(a.source), conv.comfy_groups.read(a.group_map))
        if a.check:
            if not conv.comfy_groups.equal(graph, conv.comfy_groups.read(a.output)):
                raise ValueError('Output differs from deterministic build')
        else:
            conv.write_new(a.output, graph)
        report.update(source_sha256=conv.comfy_groups.sha(a.source),
                      group_map_sha256=conv.comfy_groups.sha(a.group_map),
                      output_sha256=conv.comfy_groups.sha(a.output),
                      nodes=len(graph['nodes']), links_total=len(graph['links']))
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
