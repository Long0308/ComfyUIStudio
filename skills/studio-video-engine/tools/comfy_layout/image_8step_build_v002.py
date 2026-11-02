"""Build NEWTECONS IMAGE 8 STEP v002 (ComfyUI UI format), offline. v001 is left untouched.

Same steps, wiring, values and layout as image_8step_build.py (v001), with every
node's sockets, widget inputs and outputs taken from live INPUT_TYPES
(object_info_cache.json, fetched with GET /object_info from ComfyUI 0.41.0)
instead of saved-template copies and guesses. Fixes measured by validate_live.py:
  * CLIPTextEncode.text is a STRING widget driven by a link -> widget input + '' placeholder
  * SaveImage has a live output 'images' (IMAGE) -> kept, not dropped
  * LoadImageMask carries the trailing upload companion 'image'
The result must pass validate_live.check() before it is written (exclusive create).
Never calls POST /prompt, never touches the GPU, never overwrites a file.

Usage:  python -I image_8step_build_v002.py OUTPUT.json
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def _load(module, alias):
    spec = importlib.util.spec_from_file_location(alias, HERE / (module + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


v001 = _load('image_8step_build', 'image_8step_v001')
oi = _load('object_info', 'comfy_layout_object_info')
validate = _load('validate_live', 'comfy_layout_validate_live')

# Live-measured corrections to v001 widget lists (key -> widgets_values).
WIDGET_FIX = {
    't1': [''],  # CLIPTextEncode.text linked from the PROMPT node: positional placeholder
    't5': [''],
    'lm8': ['', 'red', 'image'],  # LoadImageMask: image, channel, upload companion
}

NEED_APPROVAL = v001.NEED_APPROVAL
MISSING_V002 = dict(v001.MISSING)
MISSING_V002.update({
    'm3a': ('CHƯA CÓ WEIGHTS — Trellis 2',
            'ĐO 31/10 (GET /object_info, ComfyUI 0.41.0): node lõi Trellis2Conditioning / Trellis2ShapeStage / '
            'Trellis2TextureStage / VaeDecodeShapeTrellis … CÓ trên server. Weights Trellis 2: 0 file trong '
            'J:\\2.Model-AI-Local\\ComfyUI (tìm *trellis*). Chưa đặt node Trellis vào graph.\n' + NEED_APPROVAL),
    'm3b': ('CHƯA CÓ — CLIP Vision cho Hunyuan3D v2',
            'ĐO 31/10: CLIPVisionLoader và CLIPVisionEncode CÓ trên server, nhưng clip_name có 0 lựa chọn '
            '(thư mục clip_vision\\ chỉ có placeholder). Hunyuan3Dv2Conditioning cần clip_vision_output. '
            'hunyuan3d-dit-v2_fp16.safetensors có trong danh sách ckpt_name nhưng CHƯA TỪNG CHẠY.\n' + NEED_APPROVAL),
    'm3c': ('ĐÃ ĐO — xuất mesh .glb (chưa nối)',
            'ĐO 31/10: VAEDecodeHunyuan3D → VOXEL; VoxelToMesh (voxel, algorithm, threshold) → MESH; SaveGLB (mesh) '
            'CÓ trên server. Tên output VOXEL / positive / negative đã khớp object_info. Chưa nối VoxelToMesh/SaveGLB '
            'vì cả nhánh 3D đang TẮT và thiếu CLIP Vision.'),
    'm5a': ('CHƯA CÓ — ControlNet cho Z-Image Turbo',
            'ĐO 31/10: ControlNetLoader / ControlNetApplyAdvanced / ModelPatchLoader / ZImageFunControlnet CÓ trên server, '
            'nhưng control_net_name và model_patches có 0 lựa chọn (controlnet\\, model_patches\\ chỉ placeholder) '
            '⇒ thiếu weights.\n' + NEED_APPROVAL),
    'm5b': ('CHƯA CÓ — bộ tách pose',
            'ĐO 31/10: không có node DWPose/OpenPose (không có comfyui_controlnet_aux). Lõi có SDPoseKeypointExtractor / '
            'SDPoseDrawKeypoints nhưng chưa đo model của chúng. Depth lấy từ pass Blender bước 04.\n' + NEED_APPROVAL),
    'm8': ('CHƯA NỐI — upscale / inpaint crop',
           'RTX VSR là tính năng driver NVIDIA, KHÔNG phải node ComfyUI. ĐO 31/10: UpscaleModelLoader có lựa chọn '
           'RealESRGAN_x4plus.pth; ImageUpscaleWithModel có. Chưa đặt vào graph. InpaintCropImproved/Stitch: thiếu.\n'
           + NEED_APPROVAL),
})


def make_node(info, kind, title, widgets, mode, size=None):
    if kind == 'Note':
        return {'id': 0, 'type': 'Note', 'title': title, 'pos': [0, 0], 'size': list(size or [600, 200]),
                'flags': {}, 'order': 0, 'mode': mode, 'inputs': [], 'outputs': [], 'properties': {},
                'widgets_values': list(widgets)}
    live = info[kind]
    inputs = []
    for sock in oi.socket_inputs(live):
        if 'autogrow' in sock:
            raise ValueError('autogrow not used in the image graph: ' + kind)
        port = {'name': sock['name'], 'type': sock['type'], 'link': None}
        if sock['optional']:
            port['shape'] = 7
        inputs.append(port)
    slots = oi.widget_layout(live, list(widgets))
    for slot in slots:
        if not slot.get('companion'):
            inputs.append({'name': slot['name'], 'type': slot['type'], 'widget': {'name': slot['name']},
                           'link': None})
    outputs = [{'name': o['name'], 'type': o['type'], 'links': [], 'slot_index': i}
               for i, o in enumerate(oi.outputs(live))]
    return {'id': 0, 'type': kind, 'title': title, 'pos': [0, 0], 'size': list(size or [340, 190]),
            'flags': {}, 'order': 0, 'mode': mode, 'inputs': inputs, 'outputs': outputs,
            'properties': {'Node name for S&R': kind}, 'widgets_values': list(widgets)}


def build(info):
    N, L = v001.spec()
    spec_rows = [(g, k, kind, t, WIDGET_FIX.get(k, wv), mode, size) for g, k, kind, t, wv, mode, size in N]
    original = (v001.spec, v001.make_node, v001.MISSING, v001.load_templates)
    v001.spec = lambda: (spec_rows, L)
    v001.make_node = lambda _templates, kind, title, wv, mode, size=None: make_node(info, kind, title, wv, mode, size)
    v001.MISSING = MISSING_V002
    v001.load_templates = lambda _w: ({}, {})
    try:
        graph = v001.build(None)
    finally:
        v001.spec, v001.make_node, v001.MISSING, v001.load_templates = original
    meta = graph['extra']['newtecons_image_8step']
    meta.pop('template_sources_sha256', None)
    meta.pop('static_node_defs', None)
    meta['schema_source'] = 'object_info_cache.json (GET /object_info, ComfyUI 0.41.0)'
    meta['object_info_cache_sha256'] = hashlib.sha256(oi.CACHE_PATH.read_bytes()).hexdigest()
    meta['supersedes'] = 'NEWTECONS_IMAGE_8STEP_v001_grouped.json (kept, not overwritten)'
    graph['extra']['workflow_metadata'] = {
        'title': 'NEWTECONS IMAGE 8 STEP v002 — template, chưa chạy, chưa qualified', 'version': 2}
    return graph


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        info = oi.load_cache()
        if info is None:
            raise ValueError('object_info_cache.json missing')
        graph = build(info)
        report = validate.check(graph, info)
        if not report['ok']:
            raise ValueError('live validation failed: %s' % report['errors'])
        payload = json.dumps(graph, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        with a.output.open('x', encoding='utf-8', newline='\n') as stream:  # refuse overwrite
            stream.write(payload)
        print(json.dumps({'output': str(a.output), 'nodes': len(graph['nodes']), 'links': len(graph['links']),
                          'groups': len(graph['groups']), 'validation_warnings': len(report['warnings']),
                          'sha256': hashlib.sha256(a.output.read_bytes()).hexdigest()}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        print('REFUSED: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
