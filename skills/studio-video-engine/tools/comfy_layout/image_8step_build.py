"""Build the NEWTECONS 8-step IMAGE workflow (ComfyUI UI/LiteGraph format), offline.

Never calls a ComfyUI server, never touches the GPU, never overwrites a file.
Node port/size templates are read (read-only) from saved NEWTECONS UI graphs so
input names, output types and widget order match graphs this install produced.
Five node types that no saved NEWTECONS graph contains are defined statically
from docs/handoffs/2026-10-23-COMFYUI-LOCAL-CAPABILITIES.json (inputs); their
output names are an assumption and say so in the node's group Note.

Usage:  python -I image_8step_build.py OUTPUT.json [--workflows DIR]
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

WORKFLOWS = Path(__file__).resolve().parents[5] / 'production-local' / 'ComfyUI' / 'user' / 'default' / 'workflows'
TEMPLATE_FILES = [
    'NEWTECONS_CHAR08_V007/CHAR_08_FACE_01_NEUTRAL_FOCUS_V007R4_MASKED_BASE.json',
    'NEWTECONS_8_NHAN_VAT/CHAR_01_Nguyen_Van_Minh_10_Bieu_Cam_10_Hanh_Dong.json',
    'NEWTECONS_8_NHAN_VAT/CHAR_08_Tran_Thao_Mai_10_Bieu_Cam_10_Hanh_Dong.json',
]
MUTED = 2  # LiteGraph mode NEVER: shown greyed, not executed.

# Capability JSON 10-23 lists these inputs; output names are not in that JSON.
STATIC = {
    'EmptyFlux2LatentImage': {'inputs': [], 'outputs': [('LATENT', 'LATENT')], 'size': [340, 130]},
    'CheckpointLoaderSimple': {'inputs': [], 'outputs': [('MODEL', 'MODEL'), ('CLIP', 'CLIP'), ('VAE', 'VAE')], 'size': [340, 120]},
    'Hunyuan3Dv2Conditioning': {'inputs': [('clip_vision_output', 'CLIP_VISION_OUTPUT')],
                                'outputs': [('positive', 'CONDITIONING'), ('negative', 'CONDITIONING')], 'size': [340, 90]},
    'EmptyLatentHunyuan3Dv2': {'inputs': [], 'outputs': [('LATENT', 'LATENT')], 'size': [340, 110]},
    'VAEDecodeHunyuan3D': {'inputs': [('samples', 'LATENT'), ('vae', 'VAE')], 'outputs': [('VOXEL', 'VOXEL')], 'size': [340, 130]},
}

GROUPS = [
    ('01 PROMPT', '#0B4FD9'),
    ('02 ASSET 4 GÓC', '#5B9BF5'),
    ('03 3D', '#9D9BF5'),
    ('04 SET 3D 3×3', '#3E8914'),
    ('05 CONTROLNET', '#134611'),
    ('06 KHOÁ ASSET', '#5C6795'),
    ('07 9 ẢNH', '#78B54F'),
    ('08 SỬA GÓC', '#96E072'),
]

PROMPT = ('Photorealistic live-action NEWTECONS corporate photo. [CHARACTER: approved NEWTECONS '
          'character ID and identity from the approved reference]. [WARDROBE: from the approved '
          'wardrobe registry only, e.g. very fine blue-white grid shirt with small NEWTECONS collar '
          'logo, helmet, reflective vest or executive suit]. [VIEW: front | back | left | right | '
          'pose p x angle g]. Neutral even studio light, realistic skin and fabric. Keep approved '
          'logos and lettering unchanged; do not invent them. No cartoon styling.')

NEED_APPROVAL = 'Cài thêm = tải weights / chạy mã bên thứ ba + restart container ⇒ CẦN USER DUYỆT từng mục. Không thay bằng partner node cloud.'

HELP = {
    '01 PROMPT': 'INPUT → Mô tả nhân vật NEWTECONS + trang phục theo registry đã duyệt.\nOUTPUT → STRING prompt + điều kiện dương/âm (Qwen3 4B, FLUX.2).\nTHAO TÁC → Gõ prompt ở node PROMPT; thay [VIEW] theo bước. Bước CPU,\nkhông cần GPU. Dùng chung cho bước 02, 05, 06.',
    '02 ASSET 4 GÓC': 'INPUT → Prompt bước 01 + 1 ảnh nhân vật NEWTECONS đã duyệt.\nOUTPUT → 1 ảnh asset (1 góc) mỗi lần chạy, lưu SaveImage.\nTHAO TÁC → FLUX.2 Klein 4B + ReferenceLatent. 4 góc = chạy 4 lần với\n[VIEW] front / back / left / right. Cần GPU + user duyệt lần chạy.',
    '03 3D': 'INPUT → 4 ảnh asset đã duyệt (bước 02).\nOUTPUT MỤC TIÊU → mesh 3D (.glb) cho Blender.\nCHƯA CÓ → Trellis 2; CLIP Vision cho Hunyuan3D. Nhánh Hunyuan3D v2\nbên dưới đang TẮT (mode Never): weights có nhưng chưa từng chạy.',
    '04 SET 3D 3×3': 'INPUT → mesh .glb + pose tham chiếu nội bộ.\nOUTPUT → 9 cặp ảnh: 3 pose × 3 góc (beauty + depth + mask).\nTHAO TÁC → Blender, ngoài ComfyUI: jjv layout render --passes\nbeauty,depth,mask. Depth/mask chạy CPU; beauty cần GPU lock.',
    '05 CONTROLNET': 'INPUT → Prompt bước 01 + depth/pose bước 04.\nOUTPUT MỤC TIÊU → ảnh đúng dáng (pose + depth) bằng Z-Image Turbo.\nCHƯA CÓ → ControlNet Z-Image, bộ tách pose. Nhánh Z-Image T2I bên\ndưới đang TẮT (mode Never), chưa nối ControlNet.',
    '06 KHOÁ ASSET': 'INPUT → ảnh đúng dáng (bước 05) + asset đã duyệt (bước 02).\nOUTPUT → ảnh đã khoá mặt / trang phục theo asset.\nTHAO TÁC → FLUX.2 Klein 4B local, ReferenceLatent từ asset, khử nhiễu\nmột phần (SplitSigmasDenoise 0.5). FLUX.3 Klein local: không có.',
    '07 9 ẢNH': 'INPUT → ảnh đã khoá asset (bước 06).\nOUTPUT → 9 ảnh: 3 pose × 3 góc, mỗi lần chạy = 1 take.\nTHAO TÁC → ComfyUI không có --n ⇒ 9 lần chạy. Sau đó CPU:\njjv images compare (sheet) → jjv images approve (sha).',
    '08 SỬA GÓC': 'INPUT → 1 trong 9 ảnh + mask vùng hỏng.\nOUTPUT → ảnh đã sửa, chỉ đổi pixel trong mask.\nTHAO TÁC → Krea2 Turbo + LoRA general_edit_v2, VAEEncodeForInpaint,\nImageCompositeMasked giữ nguyên ngoài mask. Cần GPU + user duyệt.',
}

MISSING = {
    'm3a': ('CHƯA CÓ — Trellis 2', 'Trellis 2: KHÔNG có custom node và KHÔNG có weights trên máy (0 hit trong capability JSON 10-23, custom_nodes/ không có pack Trellis).\n' + NEED_APPROVAL),
    'm3b': ('CHƯA CÓ — CLIP Vision cho Hunyuan3D v2', 'Thư mục J:\\2.Model-AI-Local\\ComfyUI\\clip_vision\\ RỖNG (chỉ placeholder). Hunyuan3Dv2Conditioning cần clip_vision_output ⇒ thiếu model CLIP Vision + node CLIPVisionLoader/CLIPVisionEncode (chưa đo). hunyuan3d-dit-v2_fp16.safetensors 4,93 GB có file nhưng CHƯA TỪNG CHẠY.\n' + NEED_APPROVAL),
    'm3c': ('CHƯA ĐO — xuất mesh .glb', 'VAEDecodeHunyuan3D → VoxelToMesh → SaveGLB: hai node cuối không có trong capability JSON 10-23 (bản lọc 158/1008 node) ⇒ chưa đo. Tên output VOXEL / positive / negative là giả định, chưa đo trên server.'),
    'm4': ('CHƯA CÓ — nhập GLB vào layout Blender (G8)', 'jjv layout plan/render chưa nhận --asset GLB (G8). Custom node ComfyUI-Blender / jennie_blender_renderer có trong custom_nodes/ nhưng tên node chưa đo ⇒ không đặt node Blender vào graph. 3 pose × 3 góc = 9 camera là thiết kế, chưa thử.'),
    'm5a': ('CHƯA CÓ — ControlNet cho Z-Image Turbo', 'J:\\2.Model-AI-Local\\ComfyUI\\controlnet\\ và model_patches\\ chỉ có placeholder ⇒ thiếu weights ControlNet (depth/pose) cho Z-Image Turbo. Node ControlNetLoader / ControlNetApplyAdvanced chưa đo khi server tắt.\n' + NEED_APPROVAL),
    'm5b': ('CHƯA CÓ — bộ tách pose DWPose / OpenPose', 'Không có pack comfyui_controlnet_aux; detection\\ chỉ có mediapipe_face_fp32. Depth không cần estimator vì lấy pass depth Blender bước 04.\n' + NEED_APPROVAL),
    'm6': ('CHƯA CÓ — FLUX.3 Klein local', 'FLUX.3 chỉ có dạng partner/API node (Flux3ImageNode …) = cloud ⇒ CẤM (--disable-partner-nodes, luật không fallback cloud). Weights FLUX.3 Klein local: không thấy. Bước này dùng FLUX.2 Klein 4B đã có (flux-2-klein-4b-fp8.safetensors 4,07 GB).\n' + NEED_APPROVAL),
    'm8': ('CHƯA CÓ — RTX VSR / upscale / inpaint crop', 'RTX VSR là tính năng driver NVIDIA, KHÔNG phải node ComfyUI. Thay thế local: RealESRGAN_x4plus.pth (có file) qua UpscaleModelLoader + ImageUpscaleWithModel (chưa đo, chưa đặt vào graph). InpaintCropImproved/Stitch: thiếu. Mask tự động RMBG + BiRefNet: có model, chưa nối.\n' + NEED_APPROVAL),
}


def load_templates(workflows):
    found, sources = {}, {}
    for rel in TEMPLATE_FILES:
        path = workflows / rel
        data = path.read_bytes()
        sources[rel] = hashlib.sha256(data).hexdigest()
        graph = json.loads(data.decode('utf-8-sig'))
        for node in graph['nodes']:
            found.setdefault(node['type'], node)
    return found, sources


def make_node(templates, kind, title, widgets, mode, size=None):
    if kind == 'Note':  # core frontend Note: no sockets, one text widget
        inputs, outputs, base = [], [], [600, 200]
    elif kind in STATIC:
        spec = STATIC[kind]
        inputs = [{'name': n, 'type': t, 'link': None} for n, t in spec['inputs']]
        outputs = [{'name': n, 'type': t, 'links': [], 'slot_index': i} for i, (n, t) in enumerate(spec['outputs'])]
        base = list(spec['size'])
    else:
        tpl = templates[kind]
        inputs = [{k: v for k, v in p.items() if k != 'link'} | {'link': None} for p in tpl.get('inputs', [])]
        outputs = [{'name': o['name'], 'type': o['type'], 'links': [], 'slot_index': i}
                   for i, o in enumerate(tpl.get('outputs', []))]
        if kind == 'SaveImage':
            outputs = []  # core SaveImage is an output node; drop the stray saved socket
        base = [340, 190]
    node = {'id': 0, 'type': kind, 'title': title, 'pos': [0, 0], 'size': list(size or base),
            'flags': {}, 'order': 0, 'mode': mode, 'inputs': copy.deepcopy(inputs),
            'outputs': outputs, 'properties': {} if kind in ('Note', 'MarkdownNote') else {'Node name for S&R': kind},
            'widgets_values': list(widgets)}
    return node


def spec():
    """(group, key, type, title, widgets, mode, size) in flow order, then links."""
    seed = 20261031
    N = []
    def add(g, key, kind, title, wv=(), mode=0, size=None):
        N.append((g, key, kind, title, wv, mode, size))
    g = '01 PROMPT'
    add(g, 'p1', 'PrimitiveStringMultiline', 'ĐIỀN: PROMPT NEWTECONS live-action', [PROMPT], size=[340, 300])
    add(g, 'c1', 'CLIPLoader', 'Bộ mã hoá chữ Qwen3 4B (FLUX.2)', ['qwen_3_4b.safetensors', 'flux2', 'default'], size=[340, 130])
    add(g, 't1', 'CLIPTextEncode', 'Mã hoá prompt → điều kiện dương', size=[340, 90])
    add(g, 'z1', 'ConditioningZeroOut', 'Điều kiện âm trung tính', size=[340, 70])
    g = '02 ASSET 4 GÓC'
    add(g, 'li2', 'LoadImage', 'ĐIỀN: ảnh nhân vật NEWTECONS đã duyệt', ['', 'image'], size=[340, 320])
    add(g, 'u2', 'UNETLoader', 'FLUX.2 Klein 4B (local)', ['flux-2-klein-4b-fp8.safetensors', 'default'], size=[340, 110])
    add(g, 'sc2', 'ImageScaleToTotalPixels', 'Chuẩn hoá cỡ ảnh tham chiếu', ['lanczos', 1.0, 16], size=[340, 130])
    add(g, 'v2', 'VAELoader', 'VAE FLUX.2 Klein', ['flux2-klein-4b-vae.safetensors'], size=[340, 80])
    add(g, 'e2', 'VAEEncode', 'Mã hoá ảnh tham chiếu', size=[340, 70])
    add(g, 'r2p', 'ReferenceLatent', 'Tham chiếu → điều kiện dương', size=[340, 70])
    add(g, 'r2n', 'ReferenceLatent', 'Tham chiếu → điều kiện âm', size=[340, 70])
    add(g, 'g2', 'CFGGuider', 'Guider cfg 1.0', [1.0], size=[340, 110])
    add(g, 'rn2', 'RandomNoise', 'Seed cố định', [seed, 'fixed'], size=[340, 110])
    add(g, 'ks2', 'KSamplerSelect', 'Sampler euler', ['euler'], size=[340, 80])
    add(g, 'fs2', 'Flux2Scheduler', 'Lịch 8 bước 1024×1024', [8, 1024, 1024], size=[340, 130])
    add(g, 'el2', 'EmptyFlux2LatentImage', 'Khung trống 1024×1024', [1024, 1024, 1])
    add(g, 'sa2', 'SamplerCustomAdvanced', 'Tạo ảnh asset (GPU)', size=[340, 130])
    add(g, 'd2', 'VAEDecodeTiled', 'Giải mã theo ô', [256, 64, 64, 8], size=[340, 150])
    add(g, 's2', 'SaveImage', 'Lưu asset 1 góc — chưa nghiệm thu', ['NEWTECONS/IMAGE_8STEP/02_ASSET_4_GOC/CHAR_XX_VIEW'], size=[340, 320])
    g = '03 3D'
    add(g, 'm3a', 'Note', None)
    add(g, 'm3b', 'Note', None)
    add(g, 'ck3', 'CheckpointLoaderSimple', 'Hunyuan3D v2 DiT (chưa từng chạy)', ['hunyuan3d-dit-v2_fp16.safetensors'], MUTED)
    add(g, 'hc3', 'Hunyuan3Dv2Conditioning', 'Điều kiện 3D — thiếu CLIP Vision', (), MUTED)
    add(g, 'hl3', 'EmptyLatentHunyuan3Dv2', 'Latent 3D trống', [3072, 1], MUTED)
    add(g, 'k3', 'KSampler', 'Lấy mẫu 3D (TẮT)', [seed, 'fixed', 30, 5.0, 'euler', 'normal', 1.0], MUTED, size=[340, 270])
    add(g, 'vd3', 'VAEDecodeHunyuan3D', 'Giải mã voxel 3D', [8000, 256], MUTED)
    add(g, 'm3c', 'Note', None)
    g = '04 SET 3D 3×3'
    add(g, 'm4', 'Note', None)
    add(g, 'lp4', 'LoadImage', 'ĐIỀN: pose tham chiếu nội bộ (reference-library/by-type/pose)', ['', 'image'], size=[340, 320])
    add(g, 'ld4', 'LoadImage', 'ĐIỀN: depth pass Blender — pose p × góc g', ['', 'image'], size=[340, 320])
    add(g, 'pv4a', 'PreviewImage', 'Xem pose tham chiếu', size=[340, 260])
    add(g, 'pv4b', 'PreviewImage', 'Xem depth pass', size=[340, 260])
    g = '05 CONTROLNET'
    add(g, 'm5a', 'Note', None)
    add(g, 'm5b', 'Note', None)
    add(g, 'u5', 'UNETLoader', 'Z-Image Turbo int8 (TẮT)', ['z_image_turbo_int8_convrot.safetensors', 'default'], MUTED, size=[340, 110])
    add(g, 'c5', 'CLIPLoader', 'Qwen3 4B cho Z-Image (type chưa đo)', ['qwen_3_4b.safetensors', 'lumina2', 'default'], MUTED, size=[340, 130])
    add(g, 'v5', 'VAELoader', 'VAE ae (Z-Image)', ['ae.safetensors'], MUTED, size=[340, 80])
    add(g, 't5', 'CLIPTextEncode', 'Mã hoá prompt cho Z-Image', (), MUTED, size=[340, 90])
    add(g, 'z5', 'ConditioningZeroOut', 'Điều kiện âm trung tính', (), MUTED, size=[340, 70])
    add(g, 'el5', 'EmptySD3LatentImage', 'Khung trống 1024×1024', [1024, 1024, 1], MUTED, size=[340, 130])
    add(g, 'k5', 'KSampler', 'Lấy mẫu Z-Image — CHƯA có ControlNet', [seed, 'fixed', 8, 1.0, 'res_multistep', 'simple', 1.0], MUTED, size=[340, 270])
    add(g, 'd5', 'VAEDecode', 'Giải mã ảnh đúng dáng', (), MUTED, size=[340, 70])
    g = '06 KHOÁ ASSET'
    add(g, 'm6', 'Note', None)
    add(g, 'la6', 'LoadImage', 'ĐIỀN: asset 4 góc đã duyệt (sha ở images approve)', ['', 'image'], size=[340, 320])
    add(g, 'sc6', 'ImageScaleToTotalPixels', 'Chuẩn hoá cỡ asset', ['lanczos', 1.0, 16], size=[340, 130])
    add(g, 'e6a', 'VAEEncode', 'Mã hoá asset đã duyệt', size=[340, 70])
    add(g, 'e6b', 'VAEEncode', 'Mã hoá ảnh đúng dáng (bước 05)', size=[340, 70])
    add(g, 'r6p', 'ReferenceLatent', 'Khoá asset → điều kiện dương', size=[340, 70])
    add(g, 'r6n', 'ReferenceLatent', 'Khoá asset → điều kiện âm', size=[340, 70])
    add(g, 'g6', 'CFGGuider', 'Guider cfg 1.0', [1.0], size=[340, 110])
    add(g, 'rn6', 'RandomNoise', 'Seed cố định', [seed, 'fixed'], size=[340, 110])
    add(g, 'ks6', 'KSamplerSelect', 'Sampler euler', ['euler'], size=[340, 80])
    add(g, 'fs6', 'Flux2Scheduler', 'Lịch 8 bước 1024×1024', [8, 1024, 1024], size=[340, 130])
    add(g, 'sp6', 'SplitSigmasDenoise', 'Khử nhiễu một phần 0.5', [0.5], size=[340, 110])
    add(g, 'sa6', 'SamplerCustomAdvanced', 'Khoá asset (GPU)', size=[340, 130])
    add(g, 'd6', 'VAEDecodeTiled', 'Giải mã theo ô', [256, 64, 64, 8], size=[340, 150])
    g = '07 9 ẢNH'
    add(g, 's7', 'SaveImage', 'Lưu 1 take (pose p × góc g) — chưa nghiệm thu', ['NEWTECONS/IMAGE_8STEP/07_9_ANH/CHAR_XX_POSEp_GOCg'], size=[340, 320])
    add(g, 'pv7', 'PreviewImage', 'Xem take vừa tạo', size=[340, 260])
    g = '08 SỬA GÓC'
    add(g, 'm8', 'Note', None)
    add(g, 'li8', 'LoadImage', 'ĐIỀN: 1 trong 9 ảnh cần sửa', ['', 'image'], size=[340, 320])
    add(g, 'lm8', 'LoadImageMask', 'ĐIỀN: mask vùng cần sửa', ['', 'red'], size=[340, 130])
    add(g, 'u8', 'UNETLoader', 'Krea2 Turbo int8 (local)', ['krea2_turbo_int8_convrot.safetensors', 'default'], size=[340, 110])
    add(g, 'lo8', 'LoraLoaderModelOnly', 'LoRA krea2_general_edit_v2', ['krea2_general_edit_v2.safetensors', 1.0], size=[340, 110])
    add(g, 'c8', 'CLIPLoader', 'Qwen3-VL 4B (Krea2)', ['qwen3vl_4b_fp8_scaled.safetensors', 'krea2', 'default'], size=[340, 130])
    add(g, 'v8', 'VAELoader', 'VAE Qwen Image', ['qwen_image_vae.safetensors'], size=[340, 80])
    add(g, 'e8', 'VAEEncode', 'Mã hoá ảnh nguồn', size=[340, 70])
    add(g, 'ei8', 'VAEEncodeForInpaint', 'Chỉ vùng mask (grow 4)', [4], size=[340, 110])
    add(g, 'ke8', 'Krea2EditGroundedEncode', 'ĐIỀN: mô tả chỗ sửa trong mask',
        ['edit: [ĐIỀN: chỗ cần sửa trong vùng mask]. Keep the same person, face, wardrobe and NEWTECONS logo outside the mask unchanged.', 768, ''], size=[340, 190])
    add(g, 'z8', 'ConditioningZeroOut', 'Điều kiện âm trung tính', size=[340, 70])
    add(g, 'mp8', 'Krea2EditModelPatch', 'Giữ ảnh nguồn', [4.0, 1.0, 'fit', 'beside (right of target)', 'aligned (trained)'], size=[340, 270])
    add(g, 'k8', 'KSampler', 'Sửa trong mask (GPU)', [seed, 'fixed', 12, 1.0, 'euler', 'simple', 1.0], size=[340, 270])
    add(g, 'd8', 'VAEDecode', 'Giải mã ảnh sửa', size=[340, 70])
    add(g, 'cm8', 'ImageCompositeMasked', 'Giữ nguyên mọi pixel ngoài mask', [0, 0, False], size=[340, 150])
    add(g, 's8', 'SaveImage', 'Lưu ảnh đã sửa — chưa nghiệm thu', ['NEWTECONS/IMAGE_8STEP/08_SUA_GOC/CHAR_XX_FIX'], size=[340, 320])
    L = [
        ('p1', 'STRING', 't1', 'text'), ('c1', 'CLIP', 't1', 'clip'), ('t1', 'CONDITIONING', 'z1', 'conditioning'),
        ('li2', 'IMAGE', 'sc2', 'image'), ('sc2', 'IMAGE', 'e2', 'pixels'), ('v2', 'VAE', 'e2', 'vae'),
        ('t1', 'CONDITIONING', 'r2p', 'conditioning'), ('e2', 'LATENT', 'r2p', 'latent'),
        ('z1', 'CONDITIONING', 'r2n', 'conditioning'), ('e2', 'LATENT', 'r2n', 'latent'),
        ('u2', 'MODEL', 'g2', 'model'), ('r2p', 'CONDITIONING', 'g2', 'positive'), ('r2n', 'CONDITIONING', 'g2', 'negative'),
        ('rn2', 'NOISE', 'sa2', 'noise'), ('g2', 'GUIDER', 'sa2', 'guider'), ('ks2', 'SAMPLER', 'sa2', 'sampler'),
        ('fs2', 'SIGMAS', 'sa2', 'sigmas'), ('el2', 'LATENT', 'sa2', 'latent_image'),
        ('sa2', 'output', 'd2', 'samples'), ('v2', 'VAE', 'd2', 'vae'), ('d2', 'IMAGE', 's2', 'images'),
        ('ck3', 'MODEL', 'k3', 'model'), ('hc3', 'positive', 'k3', 'positive'), ('hc3', 'negative', 'k3', 'negative'),
        ('hl3', 'LATENT', 'k3', 'latent_image'), ('k3', 'LATENT', 'vd3', 'samples'), ('ck3', 'VAE', 'vd3', 'vae'),
        ('lp4', 'IMAGE', 'pv4a', 'images'), ('ld4', 'IMAGE', 'pv4b', 'images'),
        ('p1', 'STRING', 't5', 'text'), ('c5', 'CLIP', 't5', 'clip'), ('t5', 'CONDITIONING', 'z5', 'conditioning'),
        ('u5', 'MODEL', 'k5', 'model'), ('t5', 'CONDITIONING', 'k5', 'positive'), ('z5', 'CONDITIONING', 'k5', 'negative'),
        ('el5', 'LATENT', 'k5', 'latent_image'), ('k5', 'LATENT', 'd5', 'samples'), ('v5', 'VAE', 'd5', 'vae'),
        ('la6', 'IMAGE', 'sc6', 'image'), ('sc6', 'IMAGE', 'e6a', 'pixels'), ('v2', 'VAE', 'e6a', 'vae'),
        ('d5', 'IMAGE', 'e6b', 'pixels'), ('v2', 'VAE', 'e6b', 'vae'),
        ('t1', 'CONDITIONING', 'r6p', 'conditioning'), ('e6a', 'LATENT', 'r6p', 'latent'),
        ('z1', 'CONDITIONING', 'r6n', 'conditioning'), ('e6a', 'LATENT', 'r6n', 'latent'),
        ('u2', 'MODEL', 'g6', 'model'), ('r6p', 'CONDITIONING', 'g6', 'positive'), ('r6n', 'CONDITIONING', 'g6', 'negative'),
        ('fs6', 'SIGMAS', 'sp6', 'sigmas'),
        ('rn6', 'NOISE', 'sa6', 'noise'), ('g6', 'GUIDER', 'sa6', 'guider'), ('ks6', 'SAMPLER', 'sa6', 'sampler'),
        ('sp6', 'low_sigmas', 'sa6', 'sigmas'), ('e6b', 'LATENT', 'sa6', 'latent_image'),
        ('sa6', 'output', 'd6', 'samples'), ('v2', 'VAE', 'd6', 'vae'),
        ('d6', 'IMAGE', 's7', 'images'), ('d6', 'IMAGE', 'pv7', 'images'),
        ('u8', 'MODEL', 'lo8', 'model'), ('li8', 'IMAGE', 'e8', 'pixels'), ('v8', 'VAE', 'e8', 'vae'),
        ('li8', 'IMAGE', 'ei8', 'pixels'), ('v8', 'VAE', 'ei8', 'vae'), ('lm8', 'MASK', 'ei8', 'mask'),
        ('c8', 'CLIP', 'ke8', 'clip'), ('li8', 'IMAGE', 'ke8', 'image'), ('ke8', 'CONDITIONING', 'z8', 'conditioning'),
        ('lo8', 'MODEL', 'mp8', 'model'), ('e8', 'LATENT', 'mp8', 'source_latent'), ('v8', 'VAE', 'mp8', 'vae'),
        ('li8', 'IMAGE', 'mp8', 'source_image'), ('ei8', 'LATENT', 'mp8', 'target_latent'),
        ('mp8', 'MODEL', 'k8', 'model'), ('ke8', 'CONDITIONING', 'k8', 'positive'), ('z8', 'CONDITIONING', 'k8', 'negative'),
        ('ei8', 'LATENT', 'k8', 'latent_image'), ('k8', 'LATENT', 'd8', 'samples'), ('v8', 'VAE', 'd8', 'vae'),
        ('li8', 'IMAGE', 'cm8', 'destination'), ('d8', 'IMAGE', 'cm8', 'source'), ('lm8', 'MASK', 'cm8', 'mask'),
        ('cm8', 'IMAGE', 's8', 'images'),
    ]
    return N, L


def note_size(text, width=720):
    chars = max(20, int(width / 9.2))
    lines = sum(max(1, -(-len(line) // chars)) for line in text.split('\n'))
    return [width, 44 + 22 * lines]


# Layout constants (graph units). Title bar of a LiteGraph node is 30 px above pos.
PAD, COL_W, COL_GAP, GROUP_GAP, TOP, ROW_GAP, TITLE_H, COLS = 30, 340, 60, 160, 80, 50, 30, 3
GROUP_W = PAD + COLS * COL_W + (COLS - 1) * COL_GAP + PAD


def depth_columns(members, links):
    """Column = longest in-group dependency depth, clamped to COLS-1 (sources left)."""
    ids = {n['id'] for n in members}
    preds = {i: [l[1] for l in links if l[3] == i and l[1] in ids] for i in ids}
    memo = {}
    def depth(i):
        if i not in memo:
            memo[i] = 0 if not preds[i] else 1 + max(depth(p) for p in preds[i])
        return memo[i]
    return {i: min(depth(i), COLS - 1) for i in ids}


def build(workflows):
    templates, sources = load_templates(workflows)
    N, L = spec()
    nodes, by_key, group_members = [], {}, {t: [] for t, _ in GROUPS}
    next_id = 1
    for title, _ in GROUPS:  # help note first in every group
        text = HELP[title]
        node = make_node(templates, 'Note', 'HƯỚNG DẪN — ' + title, [text], 0, note_size(text, GROUP_W - 2 * PAD))
        node['id'] = next_id; next_id += 1
        nodes.append(node); group_members[title].append(node)
    for g, key, kind, title, wv, mode, size in N:
        if kind == 'Note':
            title, text = MISSING[key]
            node = make_node(templates, 'Note', title, [text], 0, note_size(text, GROUP_W - 2 * PAD))
        else:
            node = make_node(templates, kind, title, wv, mode, size)
        node['id'] = next_id; next_id += 1
        nodes.append(node); by_key[key] = node; group_members[g].append(node)
    links = []
    for src_key, out_name, dst_key, in_name in L:
        src, dst = by_key[src_key], by_key[dst_key]
        s_slot = next(i for i, o in enumerate(src['outputs']) if o['name'] == out_name)
        d_slot = next(i for i, p in enumerate(dst['inputs']) if p['name'] == in_name)
        kind = src['outputs'][s_slot]['type']
        if dst['inputs'][d_slot]['type'] != kind:
            raise ValueError('type mismatch %s.%s -> %s.%s' % (src_key, out_name, dst_key, in_name))
        if dst['inputs'][d_slot]['link'] is not None:
            raise ValueError('input already linked: %s.%s' % (dst_key, in_name))
        link_id = len(links) + 1
        links.append([link_id, src['id'], s_slot, dst['id'], d_slot, kind])
        src['outputs'][s_slot]['links'].append(link_id)
        dst['inputs'][d_slot]['link'] = link_id
    groups, x = [], 0
    for title, color in GROUPS:
        members = group_members[title]
        first = next((i for i, n in enumerate(members) if n['type'] != 'Note'), len(members))
        pre = members[:first]  # help + "CHƯA CÓ" notes above the grid
        grid = [n for n in members[first:] if n['type'] != 'Note']
        post = [n for n in members[first:] if n['type'] == 'Note']  # notes about outputs go below
        y = TOP + TITLE_H
        for node in pre:
            node['pos'] = [x + PAD, y]
            y += node['size'][1] + ROW_GAP + TITLE_H
        column = depth_columns(grid, links)
        cols = [y] * COLS
        for node in grid:  # spec order = flow order inside each column
            c = column[node['id']]
            node['pos'] = [x + PAD + c * (COL_W + COL_GAP), cols[c]]
            cols[c] += node['size'][1] + ROW_GAP + TITLE_H
        y = max(cols)
        for node in post:
            node['pos'] = [x + PAD, y]
            y += node['size'][1] + ROW_GAP + TITLE_H
        cols = [y]
        groups.append({'title': title, 'bounding': [x, 0, GROUP_W, max(cols) + PAD], 'color': color,
                       'font_size': 28, 'flags': {}})
        x += GROUP_W + GROUP_GAP
    height = max(gr['bounding'][3] for gr in groups)
    for gr in groups:  # equal heights read as one row of steps
        gr['bounding'][3] = height
    order = {n['id']: i for i, n in enumerate(sorted(nodes, key=lambda n: (n['pos'][0], n['pos'][1])))}
    for n in nodes:
        n['order'] = order[n['id']]
    return {
        'last_node_id': max(n['id'] for n in nodes), 'last_link_id': len(links),
        'nodes': nodes, 'links': links, 'groups': groups, 'config': {},
        'extra': {'ds': {'scale': 0.45, 'offset': [0, 0]},
                  'workflow_metadata': {'title': 'NEWTECONS IMAGE 8 STEP v001 — template, chưa chạy, chưa qualified', 'version': 1},
                  'newtecons_image_8step': {
                      'domain': 'newtecons_live_action', 'status': 'TEMPLATE_NOT_RUN',
                      'spec': 'docs/specs/2026-10-31-image-engine-prompt-router.md §4',
                      'muted_groups': ['03 3D', '05 CONTROLNET'],
                      'template_sources_sha256': sources,
                      'static_node_defs': sorted(STATIC)}},
        'version': 0.4,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    p.add_argument('--workflows', type=Path, default=WORKFLOWS)
    a = p.parse_args(argv)
    try:
        graph = build(a.workflows)
        payload = json.dumps(graph, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        with a.output.open('x', encoding='utf-8', newline='\n') as stream:  # refuse overwrite
            stream.write(payload)
        print(json.dumps({'output': str(a.output), 'nodes': len(graph['nodes']), 'links': len(graph['links']),
                          'groups': len(graph['groups']),
                          'sha256': hashlib.sha256(a.output.read_bytes()).hexdigest()}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        print('REFUSED: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
