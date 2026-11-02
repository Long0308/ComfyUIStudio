"""F5: how pilot.graph_recipe_sha256 is derived, reproduced read-only from the pilot graph.

The v001 executor's ``graph_recipe_sha256`` is the canonical sha (sort_keys, compact,
ensure_ascii) of the WHOLE API graph after node 1 ``inputs.file`` and node 15
``inputs.filename_prefix`` are replaced by placeholders.  The v003 pilot qualification stored
that value as ``graph.recipe_sha256``; it is NOT a hash of the ``graph_recipe`` value block.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from engine.config import loader
from engine.core.io import canonical_sha256, sha256_file

V003 = "seedvr2/v003-7b-int8-tile768-int17-raw21"
V001_EXECUTOR = loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom" / "tools" / "execute_seedvr2_production_v001.py"


def _recipe_sha_of_graph(graph: dict) -> str:
    normalized = copy.deepcopy(graph)
    normalized["1"]["inputs"]["file"] = "<SOURCE_INPUT>"
    normalized["15"]["inputs"]["filename_prefix"] = "<OUTPUT_PREFIX>"
    return canonical_sha256(normalized, mode="ascii")


# v004 `extract_qualified_recipe` field -> (node id, input name), restated for the test.
_EXTRACT = {
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


@pytest.fixture(scope="module")
def recipe() -> dict:
    return json.loads((loader.SKILL_ROOT / "recipes" / f"{V003}.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def graph(recipe) -> dict:
    return json.loads((loader.REPO_ROOT / recipe["pilot"]["graph_file"]).read_text("utf-8"))


def test_pilot_graph_recipe_sha256_is_reproducible_from_the_pilot_graph(recipe, graph) -> None:
    pilot = recipe["pilot"]
    assert sha256_file(loader.REPO_ROOT / pilot["graph_file"]) == pilot["graph_file_sha256"]
    assert canonical_sha256(graph, mode="ascii") == pilot["graph_canonical_sha256"]
    assert _recipe_sha_of_graph(graph) == pilot["graph_recipe_sha256"]
    assert pilot["graph_recipe_sha256"].startswith("24091fde")


def test_the_v001_executor_really_uses_that_derivation() -> None:
    source = V001_EXECUTOR.read_text(encoding="utf-8")
    body = source[source.index("def graph_recipe_sha256"):source.index("def is_sha256")]
    assert '"<SOURCE_INPUT>"' in body and '"<OUTPUT_PREFIX>"' in body
    assert re.search(r'\["1"\]\["inputs"\]\["file"\]', body)
    assert re.search(r'\["15"\]\["inputs"\]\["filename_prefix"\]', body)


def test_the_value_block_hash_is_a_different_thing(recipe) -> None:
    assert canonical_sha256(recipe["graph_recipe"], mode="ascii") != recipe["pilot"]["graph_recipe_sha256"]


def test_graph_recipe_block_equals_the_values_inside_the_pilot_graph(recipe, graph) -> None:
    extracted = {key: graph[node]["inputs"][name] for key, (node, name) in _EXTRACT.items()}
    extracted["model"] = "7b" if "7b" in extracted["model_file"] else "unknown"
    assert extracted == recipe["graph_recipe"]


def test_graph_recipe_block_pin_is_the_canonical_ascii_sha(recipe) -> None:
    pilot = recipe["pilot"]
    assert canonical_sha256(recipe["graph_recipe"], mode="ascii") == pilot["graph_recipe_block_sha256"]
    assert pilot["graph_recipe_sha256_method"].startswith("canonical-ascii sha256 of the full API graph")


def test_flipping_one_value_in_the_graph_changes_the_recipe_sha(graph) -> None:
    tampered = copy.deepcopy(graph)
    tampered["10"]["inputs"]["denoise"] = 0.5
    assert _recipe_sha_of_graph(tampered) != _recipe_sha_of_graph(graph)
    renamed = copy.deepcopy(graph)
    renamed["1"]["inputs"]["file"] = "other.mp4"
    assert _recipe_sha_of_graph(renamed) == _recipe_sha_of_graph(graph)  # placeholders absorb the runtime inputs
