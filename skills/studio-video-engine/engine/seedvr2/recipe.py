"""SeedVR2 recipe helpers: extract recipe values from an API graph and clone it per chunk.

Domain-neutral.  The recipe (a config file) owns every number; this module only knows which
graph node/input carries which recipe value.  Node ids are those of the qualified pilot graph.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import canonical_sha256, sha256_file

# recipe.graph_recipe key -> (node id, input name) in the qualified pilot API graph.
EXTRACT_TABLE: dict[str, tuple[str, str]] = {
    "model_file": ("7", "unet_name"), "vae": ("5", "vae_name"),
    "upscale_method": ("3", "upscale_method"), "processing_width": ("3", "width"),
    "processing_height": ("3", "height"), "image_scale_crop": ("3", "crop"),
    "tile_size": ("6", "tile_size"), "tile_overlap": ("6", "overlap"),
    "vae_temporal_size": ("6", "temporal_size"), "vae_temporal_overlap": ("6", "temporal_overlap"),
    "temporal_chunk_overlap": ("8", "temporal_overlap"), "chunking_mode": ("8", "chunking_mode"),
    "internal_sampler_max_pixel_frames": ("8", "chunking_mode.frames_per_chunk"),
    "sampler_seed": ("10", "seed"), "sampler_steps": ("10", "steps"), "sampler_cfg": ("10", "cfg"),
    "sampler_name": ("10", "sampler_name"), "scheduler": ("10", "scheduler"),
    "denoise": ("10", "denoise"), "post_color_correction_method": ("13", "color_correction_method"),
    "save_format": ("15", "format"), "save_codec": ("15", "format.codec"),
    "save_encoding": ("15", "format.codec.encoding"), "save_crf": ("15", "format.codec.encoding.crf"),
}
INPUT_PORT = ("1", "file")  # LoadVideo: the per-chunk source segment
OUTPUT_PORT = ("15", "filename_prefix")  # SaveVideo: the per-chunk output prefix
_MODEL_NODE = ("7", "unet_name")
# The only two inputs a per-chunk clone may change (node ids are those of the qualified pilot
# graph; they are hard-coded here and in EXTRACT_TABLE on purpose).
ALLOWED_PORT_PATHS = frozenset({f"$.{INPUT_PORT[0]}.inputs.{INPUT_PORT[1]}",
                                f"$.{OUTPUT_PORT[0]}.inputs.{OUTPUT_PORT[1]}"})


def extract_graph_recipe(graph: dict) -> dict:
    """Recipe values carried by ``graph`` (same table as the v004 ``extract_qualified_recipe``)."""
    try:
        values = {key: graph[node]["inputs"][name] for key, (node, name) in EXTRACT_TABLE.items()}
        model_file = graph[_MODEL_NODE[0]]["inputs"][_MODEL_NODE[1]]
    except (KeyError, TypeError) as error:
        raise Refused("pilot graph is missing a qualified recipe key") from error
    values["model"] = "7b" if "7b" in model_file else "unknown"
    return values


def graph_recipe_sha256(graph: dict, *, mode: str = "ascii") -> str:
    """Canonical sha of the whole API graph with the per-chunk runtime inputs masked.

    This is the derivation behind ``pilot.graph_recipe_sha256`` (the v001 executor's
    ``graph_recipe_sha256``; that helper used the utf8 canonical form, which equals the ascii
    form for a pure-ASCII graph).  It is not a hash of the ``graph_recipe`` value block.
    """
    masked = copy.deepcopy(graph)
    try:
        masked[INPUT_PORT[0]]["inputs"][INPUT_PORT[1]] = "<SOURCE_INPUT>"
        masked[OUTPUT_PORT[0]]["inputs"][OUTPUT_PORT[1]] = "<OUTPUT_PREFIX>"
    except (KeyError, TypeError) as error:
        raise Refused("API graph lacks the input/output port nodes") from error
    return canonical_sha256(masked, mode=mode)  # type: ignore[arg-type]


def padded_frame_count(raw_frames: int, alignment: int) -> int:
    """Frames SeedVR2 pre-processing pads a raw segment to: ``n + ((1 - n) % alignment)``."""
    if raw_frames < 1:
        raise Refused("raw segment frame count must be positive")
    return raw_frames + ((1 - raw_frames) % alignment)


def changed_json_paths(left: Any, right: Any, path: str = "$") -> list[dict]:
    """Every JSON path whose value differs, as ``{"path", "before", "after"}``."""
    if type(left) is not type(right):
        return [{"path": path, "before": left, "after": right}]
    if isinstance(left, dict):
        changes: list[dict] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in left:
                changes.append({"path": child, "before": None, "after": right[key]})
            elif key not in right:
                changes.append({"path": child, "before": left[key], "after": None})
            else:
                changes.extend(changed_json_paths(left[key], right[key], child))
        return changes
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": path, "before": left, "after": right}]
        return [c for i, (a, b) in enumerate(zip(left, right))
                for c in changed_json_paths(a, b, f"{path}[{i}]")]
    return [] if left == right else [{"path": path, "before": left, "after": right}]


def load_pilot_graph(recipe: dict, repo_root: Path) -> dict:
    """Read the pinned pilot API graph; ``Refused`` unless its file sha matches the recipe pin."""
    import json

    path = Path(repo_root) / recipe["pilot"]["graph_file"]
    if not path.is_file():
        raise Refused(f"pilot graph not found: {path}")
    actual = sha256_file(path)
    if actual != recipe["pilot"]["graph_file_sha256"]:
        raise Refused(f"pilot graph sha256 {actual} != recipe pin {recipe['pilot']['graph_file_sha256']}")
    graph = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(graph, dict):
        raise Refused("pilot graph is not a JSON object")
    return graph


def clone_api_graph(pilot_graph: dict, recipe: dict, *, input_name: str,
                    output_prefix: str) -> tuple[dict, list[dict]]:
    """Clone the pilot graph for one chunk: only the two allowed ports may change."""
    if set(recipe["allowed_api_diff_paths"]) != ALLOWED_PORT_PATHS:
        raise Refused(f"allowed_api_diff_paths must be exactly {sorted(ALLOWED_PORT_PATHS)}")
    graph = copy.deepcopy(pilot_graph)
    graph[INPUT_PORT[0]]["inputs"][INPUT_PORT[1]] = input_name
    graph[OUTPUT_PORT[0]]["inputs"][OUTPUT_PORT[1]] = output_prefix
    changes = changed_json_paths(pilot_graph, graph)
    allowed = set(recipe["allowed_api_diff_paths"])
    stray = sorted({c["path"] for c in changes} - allowed)
    if stray:
        raise Refused(f"API graph changed unqualified keys: {stray}")
    if extract_graph_recipe(graph) != recipe["graph_recipe"]:
        raise Refused("cloned API graph recipe differs from the qualified recipe")
    return graph, changes
