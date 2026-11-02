"""codex_lane_bridge: a ComfyUI node that makes images through the CLOUD GPT Codex OAuth lanes (not local GPU).

The node asks the host bridge (`jjv bridge serve`, studio-video-engine) to run N `codex-exec` takes of one prompt, waits
for the job, and outputs the landed PNGs as an IMAGE batch.  The ComfyUI Run click is recorded by the bridge as the
user's prompt confirmation (`by=comfyui-run:<client_id>`).  Contract: NODE-CONTRACT.md next to this file.
"""
from __future__ import annotations

import base64
import io
import json

from . import client

KINDS = ["SHOT", "FACE", "ACTION", "ASSET", "SET", "FIX"]
CONTEXTS = [client.DEFAULT_CONTEXT, "cong_truong", "van_phong"]  # wardrobe presets of the host bridge
DEFAULT_EPISODE = "Newtecons-TienDo-KichTinh-30s"


def _ids() -> tuple[str, str]:
    try:
        import server

        instance = server.PromptServer.instance
        return str(getattr(instance, "client_id", None) or "api"), str(getattr(instance, "last_prompt_id", None) or "")
    except Exception:  # noqa: BLE001 - outside a running ComfyUI there is no PromptServer
        return "api", ""


def _png_b64(image) -> str:
    import numpy as np
    from PIL import Image

    array = (image.cpu().numpy().clip(0, 1) * 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array[..., :3]).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _tensor(paths):
    import numpy as np
    import torch
    from PIL import Image

    frames, size = [], None
    for path in paths:
        picture = Image.open(path).convert("RGB")
        size = size or picture.size
        if picture.size != size:  # an IMAGE batch needs one size; keep the first image's size
            picture = picture.resize(size, Image.LANCZOS)
        frames.append(torch.from_numpy(np.array(picture).astype(np.float32) / 255.0))
    return torch.stack(frames, dim=0)


class CodexOAuthImageLane:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"multiline": True, "default": ""}),
            "count": ("INT", {"default": 10, "min": 1, "max": 10}),
            "episode": ("STRING", {"default": DEFAULT_EPISODE}),
            "kind": (KINDS, {"default": "SHOT"}),
        }, "optional": {
            "refs": ("IMAGE",),
            "ref_role": ("STRING", {"default": "identity"}),
            "prompts": ("STRING", {"multiline": True, "default": ""}),
            "timeout_seconds": ("INT", {"default": 3600, "min": 60, "max": 14400}),
            "context": (CONTEXTS, {"default": client.DEFAULT_CONTEXT}),
            "company_wardrobe": ("IMAGE",),
            "scene_ref": ("IMAGE",),
        }}

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "job_info")
    FUNCTION = "run"
    CATEGORY = "NEWTECONS/codex (cloud GPT)"
    DESCRIPTION = ("Cloud GPT image tool through Codex OAuth lanes on the host bridge: NOT local GPU inference. "
                   "Each Run spends ChatGPT quota (count images).")

    def run(self, prompt, count, episode, kind, refs=None, ref_role="identity", timeout_seconds=3600, prompts="",
            context=client.DEFAULT_CONTEXT, company_wardrobe=None, scene_ref=None):
        import comfy.model_management
        import comfy.utils
        import folder_paths

        client_id, prompt_id = _ids()
        body = client.build_body(prompt, count, episode, kind, f"{client_id}:{prompt_id}" if prompt_id else client_id, prompts,
                                 context)
        asked = len(body.get("prompts") or []) or int(count)  # `prompts` (one per line) overrides prompt + count
        secret = client.read_secret()
        if refs is not None:
            body["refs"] = [{"role": ref_role, "png_base64": _png_b64(refs[i])} for i in range(min(int(refs.shape[0]), 8))]
        if company_wardrobe is not None:  # the user's own company wardrobe frames: ADDED to the domain preset
            body["wardrobe_refs"] = [{"role": "company_wardrobe", "png_base64": _png_b64(company_wardrobe[i])}
                                     for i in range(min(int(company_wardrobe.shape[0]), client.MAX_EXTRA_REFS))]
        if scene_ref is not None:
            body["scene_ref"] = {"role": "scene_location", "png_base64": _png_b64(scene_ref[0])}
        started = client.call("POST", "/v1/images/codex", secret, body)
        bar = comfy.utils.ProgressBar(asked)

        def on_poll(doc):
            bar.update_absolute(len(doc.get("images") or []), asked)
            comfy.model_management.throw_exception_if_processing_interrupted()

        doc = client.wait_job(started["job_id"], secret, float(timeout_seconds), on_poll=on_poll)
        paths = client.landed_paths(doc, folder_paths.get_input_directory())
        info = {"job_id": doc.get("job_id"), "state": doc.get("state"), "made": len(paths), "asked": asked,
                "route": doc.get("route"), "ref_set": client.ref_set_summary(doc), "items": doc.get("items"),
                "images": [{k: i.get(k) for k in ("index", "input_relpath", "sha256", "account_label", "prompt_sha256")}
                                                     for i in doc.get("images") or []], "errors": doc.get("errors")}
        if not paths:
            raise RuntimeError(f"Codex lane job {doc.get('job_id')} made no image ({doc.get('state')}): "
                               f"{json.dumps(doc.get('errors'), ensure_ascii=False)[:600]}")
        return (_tensor(paths), json.dumps(info, ensure_ascii=False, indent=1))


try:  # same-origin proxy for a UI panel (video jobs, job status); the secret stays server-side
    import server as _server

    from . import routes as _routes

    _routes.register(_server.PromptServer.instance.routes)
except Exception as _error:  # noqa: BLE001 - outside ComfyUI (tests) there is no PromptServer
    print(f"[codex_lane_bridge] proxy routes not registered: {_error}")

NODE_CLASS_MAPPINGS = {"CodexOAuthImageLane": CodexOAuthImageLane}
NODE_DISPLAY_NAME_MAPPINGS = {"CodexOAuthImageLane": "Codex OAuth Image Lane (cloud GPT — not local GPU)"}
