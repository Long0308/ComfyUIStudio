"""Legacy node API for compatibility with the existing newtecons_branding pack."""
import json
from pathlib import Path
import re
import uuid

from . import core


class NewteconsProjectPanel:
    @classmethod
    def INPUT_TYPES(cls):
        # ComfyUI validates COMBOs globally, before per-node runtime inputs exist.
        # Union the explicit episode shotlists; runtime and routes revalidate membership.
        scenes, shots = {"ALL"}, {"SELECT"}
        try:
            root = core.project_root()
            for episode in root.iterdir():
                manifest = episode / "project-panel.json"
                if not episode.is_dir() or not manifest.is_file():
                    continue
                manifest = core.confined(manifest, root, kind="file")
                data = json.loads(manifest.read_text(encoding="utf-8-sig"))
                for rel in data.get("shotlists", []):
                    path = core.confined(episode / rel, root, kind="file")
                    for row in core.parse_shotlist(path):
                        scenes.add(row["scene"])
                        shots.add(row["shot"])
        except (OSError, ValueError, json.JSONDecodeError):
            # Empty installation still exposes the node; execution reports a specific error.
            pass
        return {"required": {
            "domain": (list(core.DOMAINS), {"default": core.DOMAINS[0]}),
            "script_path": ("STRING", {"default": ""}),
            "shotlist_path": ("STRING", {"default": ""}),
            "asset_folder": ("STRING", {"default": ""}),
            "run_mode": (list(core.MODES),),
            "scene": (sorted(scenes), {"default": "ALL"}),
            "shot": (sorted(shots), {"default": "SELECT"}),
            "aspect": (list(core.ASPECTS),),
            "generation_size": (list(core.SIZES),),
            "output_resolution": (list(core.OUTPUTS),),
            "style": (list(core.STYLES),),
            "no_image_mode": (["T2V", "I2V"],),
            "min_duration": ("FLOAT", {"default": 4.0, "min": 0.1, "max": 150.0, "step": 0.1}),
        }, "optional": {
            "auto_shot": ("STRING", {"default": ""}),
            "auto_render_key": ("STRING", {"default": ""}),
        }, "hidden": {"unique_id": "UNIQUE_ID", "prompt": "PROMPT"}}

    RETURN_TYPES = ("STRING", "STRING", "FLOAT", "INT", "INT", "FLOAT", "INT", "STRING", "INT", "INT", "STRING")
    RETURN_NAMES = ("prompt", "ref_image_paths_json", "duration_s", "width", "height", "fps",
                    "length", "receipt_json", "output_width", "output_height", "guide_image_paths_json")
    FUNCTION = "select"
    CATEGORY = "NEWTECONS/project"
    DESCRIPTION = "Selectable episode inputs; local CPU path staging only. Approval stays with the engine."

    @classmethod
    def VALIDATE_INPUTS(cls, scene, shot):
        # Dynamic values are validated against THIS shotlist inside select(), not a stale global union.
        return isinstance(scene, str) and isinstance(shot, str)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # External shotlists/assets/completion receipts can change without widget changes.
        return float("nan")

    def select(self, unique_id="", prompt=None, **kwargs):
        import folder_paths
        receipt = core.prepare(root=core.project_root(), input_dir=folder_paths.get_input_directory(),
                               output_dir=folder_paths.get_output_directory(), panel_id=unique_id,
                               render_context_sha256=core.context_hash(prompt or {}), **kwargs)
        if receipt is None:
            raise ValueError("AUTO_COMPLETE: every selected shot already has a hash-verified render")
        paths = json.dumps([x["filename"] for x in receipt["refs"]], ensure_ascii=False)
        return (receipt["prompt"], paths, receipt["duration"], receipt["width"], receipt["height"],
                float(receipt["fps"]), receipt["frames"], json.dumps(receipt, ensure_ascii=False),
                receipt["output_width"], receipt["output_height"],
                json.dumps([x["filename"] for x in receipt["guide"]], ensure_ascii=False))


class NewteconsPanelReference:
    """Load one independently sized reference; never silently provide a black I2V frame."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"ref_image_paths_json": ("STRING", {"forceInput": True}),
                             "index": ("INT", {"default": 0, "min": 0, "max": 8})}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "load"
    CATEGORY = "NEWTECONS/project"

    def load(self, ref_image_paths_json, index):
        import folder_paths
        import numpy as np
        import torch
        from PIL import Image, ImageOps
        names = json.loads(ref_image_paths_json)
        if not isinstance(names, list) or not 0 <= index < len(names):
            raise ValueError("Reference index missing. For T2V remove image loader/guide connections.")
        name = names[index]
        if not isinstance(name, str) or Path(name).name != name or "\\" in name:
            raise ValueError("Only flat staged reference names are accepted")
        root = Path(folder_paths.get_input_directory()).resolve(strict=True)
        image = core.confined(name, root, kind="file")
        domain = next((d for d in core.DOMAINS if name.startswith(d + "__")), None)
        content_sha = core.sha256(image)[:12]
        tail = name[len(domain) + 2:] if domain else ""
        parts = tail.split(f"__{content_sha}__", 1)
        if len(parts) != 2 or not core.SAFE_ID.fullmatch(parts[0]) or not parts[1]:
            raise ValueError("Staged reference name/hash mismatch")
        with Image.open(image) as img:
            array = np.array(ImageOps.exif_transpose(img).convert("RGB"), dtype=np.float32) / 255.0
        return (torch.from_numpy(array)[None],)


class NewteconsPanelSaveVideo:
    """Terminal writer: only successful video.save_to creates a completion marker."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("VIDEO",), "receipt_json": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("render_receipt_json",)
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = "NEWTECONS/project"

    def save(self, video, receipt_json):
        import folder_paths
        from comfy_api.latest import Types
        receipt = json.loads(receipt_json)
        key = receipt.get("render_key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Invalid panel render key")
        root = Path(folder_paths.get_output_directory()).resolve(strict=True)
        directory = root / "newtecons-panel"
        directory.mkdir(exist_ok=True)
        directory = core.confined(directory, root, kind="dir")
        name = f"{key}__{uuid.uuid4().hex}.mp4"
        target = directory / name
        video.save_to(str(target), format=Types.VideoContainer("mp4"), codec=Types.VideoCodec("h264"))
        result = {**receipt, "output": str(target), "sha256": core.sha256(target), "approved": False,
                  "saved_dimensions": list(video.get_dimensions())}
        # Immutable per-render receipt, plus a replaceable completion index for fast lookup.
        history = directory / f"{name}.receipt.json"
        result["receipt_path"] = str(history)
        with history.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        temp = directory / f"{key}.{uuid.uuid4().hex}.tmp"
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(directory / f"{key}.json")
        return {"ui": {"newtecons_panel": [{"panel_id": receipt["panel_id"],
                "shot": receipt["shot"], "run_mode": receipt["run_mode"], "render_key": key}],
                       "images": [{"filename": name, "subfolder": "newtecons-panel", "type": "output"}],
                       "animated": (True,)},
                "result": (json.dumps(result, ensure_ascii=False),)}


class NewteconsPanelH3:
    """Adapter to the installed native H3, allowing zero-to-nine variable references."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"clip": ("CLIP",), "vae": ("VAE",),
                             "prompt": ("STRING", {"forceInput": True}),
                             "ref_image_paths_json": ("STRING", {"forceInput": True}),
                             "width": ("INT", {"forceInput": True}),
                             "height": ("INT", {"forceInput": True}),
                             "length": ("INT", {"forceInput": True})}}

    RETURN_TYPES = ("CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "LATENT")
    FUNCTION = "condition"
    CATEGORY = "NEWTECONS/project"

    def condition(self, clip, vae, prompt, ref_image_paths_json, width, height, length):
        from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo
        names = json.loads(ref_image_paths_json)
        if not isinstance(names, list) or len(names) > 9:
            raise ValueError("Expected zero to nine staged image paths")
        loader = NewteconsPanelReference()
        refs = {f"ref_image_{i}": loader.load(ref_image_paths_json, i)[0] for i in range(len(names))}
        result = MiniMaxH3ReferenceToVideo.execute(
            clip=clip, vae=vae, prompt=prompt, width=width, height=height,
            length=length, ref_images=refs, ref_image_size="match")
        return result.result


NODE_CLASS_MAPPINGS = {"NewteconsProjectPanel": NewteconsProjectPanel,
                       "NewteconsPanelReference": NewteconsPanelReference,
                       "NewteconsPanelH3": NewteconsPanelH3,
                       "NewteconsPanelSaveVideo": NewteconsPanelSaveVideo}
NODE_DISPLAY_NAME_MAPPINGS = {"NewteconsProjectPanel": "NEWTECONS Project Panel",
                              "NewteconsPanelH3": "NEWTECONS Panel • Native H3 Adapter",
                              "NewteconsPanelReference": "NEWTECONS Panel • Load Reference",
                              "NewteconsPanelSaveVideo": "NEWTECONS Panel • Save + Receipt"}
