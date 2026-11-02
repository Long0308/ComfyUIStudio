"""API graph of the local Krea2 edit route (guide -> storyboard frame) and its LoRA gate.

Wiring follows the comfyui-krea2edit README (UNETLoader -> task LoRA -> Krea2EditModelPatch -> KSampler; both
Krea2EditGroundedEncode nodes see the images; EmptySD3LatentImage feeds KSampler and target_latent). The edit LoRA
sits RIGHT AFTER the UNETLoader (error-db storyboard-v014-v016-missing-edit-lora-liveaction-leak): the identity LoRA
restages a person, the general LoRA edits by instruction; the gate refuses a graph whose patch model does not come
through the task's LoRA. Only stock + comfyui-krea2edit classes are used: no partner/API node can appear.
"""

from __future__ import annotations

import math
from typing import Any

from ..core.errors import Refused

TASKS = ("general", "identity")


def fit_size(width: int, height: int, max_pixels: int, multiple: int) -> tuple[int, int]:
    """Largest size with the guide's aspect ratio, at most ``max_pixels``, both sides multiples of ``multiple``."""
    scale = min(1.0, math.sqrt(max_pixels / (width * height)))
    w = max(multiple, int(width * scale) // multiple * multiple)
    h = max(multiple, int(height * scale) // multiple * multiple)
    while w * h > max_pixels and (w > multiple or h > multiple):
        w, h = (w - multiple, h) if w >= h else (w, h - multiple)
    return w, h


def build_graph(recipe: dict[str, Any], *, task: str, guide_name: str, sheet_name: str | None, prompt: str,
                seed: int, width: int, height: int, prefix: str) -> dict[str, Any]:
    if task not in TASKS:
        raise Refused(f"--task must be one of {TASKS}, got {task!r}")
    m, p, s = recipe["models"], recipe["patch"], recipe["sampler"]
    two = sheet_name is not None
    g: dict[str, Any] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": m["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": m["clip"], "type": "krea2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "4": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": recipe["loras"][task],
                                                              "strength_model": recipe["lora_strength"]}},
        "5": {"class_type": "LoadImage", "inputs": {"image": guide_name}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},
        "9": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
    }
    encode = {"clip": ["2", 0], "prompt": prompt, "grounding_px": recipe["grounding_px"], "system_prompt": "",
              "image": ["5", 0]}
    patch = {"model": ["4", 0], "source_latent": ["6", 0], "ref_boost": p["ref_boost"], "ref_boost_a": p["ref_boost_a"],
             "fit_mode": p["fit_mode"], "ref_position_a": p["ref_position_a"], "vae": ["3", 0],
             "source_image": ["5", 0], "target_latent": ["9", 0]}
    if two:
        g["7"] = {"class_type": "LoadImage", "inputs": {"image": sheet_name}}
        g["8"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["7", 0], "vae": ["3", 0]}}
        encode["image_b"] = ["7", 0]
        patch.update(source_latent_b=["8", 0], source_image_b=["7", 0], ref_position=p["ref_position"])
    g["10"] = {"class_type": "Krea2EditGroundedEncode", "inputs": encode}
    g["11"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["10", 0]}}
    g["12"] = {"class_type": "Krea2EditModelPatch", "inputs": patch}
    g["13"] = {"class_type": "KSampler", "inputs": {"seed": seed, "steps": s["steps"], "cfg": s["cfg"],
               "sampler_name": s["sampler_name"], "scheduler": s["scheduler"], "denoise": s["denoise"],
               "model": ["12", 0], "positive": ["10", 0], "negative": ["11", 0], "latent_image": ["9", 0]}}
    g["14"] = {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["3", 0]}}
    g["15"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["14", 0]}}
    return g


def lora_gate(graph: dict[str, Any], recipe: dict[str, Any], task: str) -> dict[str, str]:
    """E_LORA_GATE: the Krea2EditModelPatch model must come from the task's LoRA, which sits right after UNETLoader."""
    by_class: dict[str, list[str]] = {}
    for node_id, node in graph.items():
        by_class.setdefault(node["class_type"], []).append(node_id)
    for needed in ("UNETLoader", "LoraLoaderModelOnly", "Krea2EditModelPatch"):
        if len(by_class.get(needed, [])) != 1:
            raise Refused(f"E_LORA_GATE: the graph needs exactly one {needed}, found {len(by_class.get(needed, []))}")
    unet, lora, patch = (by_class[c][0] for c in ("UNETLoader", "LoraLoaderModelOnly", "Krea2EditModelPatch"))
    if graph[lora]["inputs"].get("model") != [unet, 0]:
        raise Refused("E_LORA_GATE: the edit LoRA is not wired to the UNETLoader output (it must follow it directly)")
    if graph[patch]["inputs"].get("model") != [lora, 0]:
        raise Refused("E_LORA_GATE: Krea2EditModelPatch does not take its model from the edit LoRA")
    expected = recipe["loras"][task]
    if graph[lora]["inputs"].get("lora_name") != expected:
        raise Refused(f"E_LORA_GATE: task {task!r} needs LoRA {expected}, the graph names "
                      f"{graph[lora]['inputs'].get('lora_name')!r}")
    return {"unet_node": unet, "lora_node": lora, "patch_node": patch, "lora_name": expected}


def lora_listed(object_info: dict[str, Any], lora_name: str) -> bool:
    """True if ``/object_info/LoraLoaderModelOnly`` lists ``lora_name`` (the file is installed where ComfyUI looks)."""
    entry = next(iter(object_info.values()), {}) if isinstance(object_info, dict) else {}
    spec = (((entry.get("input") or {}).get("required") or {}).get("lora_name")) or []
    return bool(spec) and isinstance(spec[0], list) and lora_name in spec[0]
