"""Model policy: allowed models per role and models banned for anchors, read from the domain ``model_policy`` block.

``banned_models`` are refused when an anchor/still graph loads them (checkpoint, UNet, LoRA, CLIP, VAE loader inputs).
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from ..core.errors import Refused

CODE = "MODEL_POLICY_REFUSED"
_MODEL_KEYS = ("ckpt_name", "unet_name", "model_name", "lora_name", "clip_name", "clip_name1", "clip_name2", "vae_name")


def block(domain: Mapping[str, Any] | None) -> dict | None:
    policy = (domain or {}).get("model_policy")
    return policy if isinstance(policy, Mapping) and policy.get("enabled") is True else None


def _norm(text: str) -> str:
    stem = re.sub(r"\.(safetensors|ckpt|pt|pth|gguf|bin)$", "", str(text).replace("\\", "/").rsplit("/", 1)[-1].lower())
    return re.sub(r"[^a-z0-9]+", "", stem)


def loaded_models(graph: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """``(node_id, input_key, model_file)`` for every string model-loader input in an API graph."""
    rows = []
    for nid, node in graph.items():
        for key in _MODEL_KEYS:
            value = (node.get("inputs") or {}).get(key) if isinstance(node, dict) else None
            if isinstance(value, str) and value:
                rows.append((str(nid), key, value))
    return rows


def check_anchor_graph(domain: Mapping[str, Any] | None, graph: Mapping[str, Any], *, where: str) -> list[str]:
    """Refuse a graph that loads a banned model.  Returns the model files seen (empty when the policy is off)."""
    policy = block(domain)
    if policy is None:
        return []
    banned = {_norm(name): name for name in policy.get("banned_models") or []}
    seen, bad = [], []
    for nid, key, value in loaded_models(graph):
        seen.append(value)
        for token, name in banned.items():
            if token and token in _norm(value):
                bad.append(f"node {nid}.{key}={value!r} is banned ({name})")
    if bad:
        raise Refused(f"{CODE}: {where}: " + "; ".join(bad) + "; use a model from model_policy.roles")
    return seen
