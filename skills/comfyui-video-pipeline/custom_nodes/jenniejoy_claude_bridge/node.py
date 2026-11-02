"""ComfyUI node ``JJClaudeBridge``: authoring/QA only, never part of a render graph.

It reaches Claude without an Anthropic API key, either through the Claude Code chat (MCP
inbox/outbox files) or through the user's own OpenAI-compatible gateway (New-API / 9Router).
See README.md. All logic lives in ``bridge_core`` so it can be tested without ComfyUI.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import bridge_core as core

PACKAGE_DIR = Path(__file__).resolve().parent
NODE_CLASS = "JJClaudeBridge"


def _check_interrupt() -> None:
    """Let the ComfyUI Cancel button stop a long chat wait (no-op outside ComfyUI)."""
    try:
        import comfy.model_management as model_management  # type: ignore[import-not-found]
    except Exception:
        return
    model_management.throw_exception_if_processing_interrupted()


def tensor_to_images(image: Any) -> list[core.ImageBlob]:
    """ComfyUI IMAGE ([B,H,W,C] float 0..1) -> PNG blobs hashed over their uint8 pixels."""
    if image is None:
        return []
    import numpy as np
    from PIL import Image

    array = image.cpu().numpy() if hasattr(image, "cpu") else np.asarray(image)
    if array.ndim == 3:
        array = array[None, ...]
    if array.ndim != 4:
        raise core.BridgeError(f"IMAGE must be [B,H,W,C]; got shape {tuple(array.shape)}")
    blobs: list[core.ImageBlob] = []
    for frame in array:
        pixels = np.clip(255.0 * frame, 0, 255).astype(np.uint8)
        if pixels.shape[-1] == 1:
            pixels = pixels[..., 0]
        digest = hashlib.sha256()
        digest.update(f"{pixels.shape}:".encode("ascii"))
        digest.update(pixels.tobytes())
        buffer = io.BytesIO()
        Image.fromarray(pixels).save(buffer, format="PNG", compress_level=1)
        blobs.append(core.ImageBlob(digest.hexdigest(), buffer.getvalue()))
    return blobs


def _paths(env: Mapping[str, str] | None = None) -> core.BridgePaths:
    environment = os.environ if env is None else env
    return core.BridgePaths.from_shared(core.default_shared_dir(environment, PACKAGE_DIR))


class JJClaudeBridge:
    """Ask Claude from an authoring graph. Deterministic: the first answer is cached forever."""

    CATEGORY = "JennieJoy/Authoring"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("answer", "receipt")
    DESCRIPTION = (
        "Authoring/QA only. cache first, then the Claude Code chat (MCP inbox/outbox) or your "
        "own New-API/9Router gateway. Never use in a render graph."
    )

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "system": ("STRING", {"multiline": True, "default": ""}),
                "mode": (list(core.MODES), {"default": "auto"}),
                "timeout_s": (
                    "INT",
                    {
                        "default": core.DEFAULT_TIMEOUT_S,
                        "min": core.MIN_TIMEOUT_S,
                        "max": core.MAX_TIMEOUT_S,
                    },
                ),
            },
            "optional": {"image": ("IMAGE",)},
        }

    @classmethod
    def IS_CHANGED(
        cls,
        prompt: str,
        system: str,
        mode: str,
        timeout_s: int,
        image: Any = None,
    ) -> str:
        """The cache key: ComfyUI re-runs only when what can change the answer changes."""
        hashes = [blob.sha256 for blob in tensor_to_images(image)]
        return core.cache_key(system, prompt, hashes)

    def run(
        self,
        prompt: str,
        system: str,
        mode: str,
        timeout_s: int,
        image: Any = None,
    ) -> tuple[str, str]:
        images: Sequence[core.ImageBlob] = tensor_to_images(image)
        resolution = core.resolve(
            _paths(),
            system=system,
            prompt=prompt,
            images=images,
            mode=mode,
            timeout_s=timeout_s,
            on_poll=_check_interrupt,
        )
        origin = "cache hit" if resolution.cache_hit else f"route={resolution.receipt['route']}"
        print(f"[JJClaudeBridge] {origin} key={resolution.key[:12]}")  # noqa: T201
        return (resolution.answer, resolution.receipt_text)


NODE_CLASS_MAPPINGS = {NODE_CLASS: JJClaudeBridge}
NODE_DISPLAY_NAME_MAPPINGS = {NODE_CLASS: "JJ Claude Bridge (authoring only)"}
