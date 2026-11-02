"""Parity: the config data equals the constants of the frozen v004 sources.

The v004 files are parsed with ``ast`` only (never imported, never written), so a drift
between the v004 tools and the recipe/machine/domain data fails here.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path, PureWindowsPath

import pytest

from engine.config import loader
from engine.core.io import sha256_file

EP = loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom"
PREPARE = EP / "tools" / "prepare_seedvr2_production_v004.py"
EXECUTE = EP / "tools" / "execute_seedvr2_production_v004.py"
HELPER = loader.REPO_ROOT / ".agents" / "skills" / "comfyui-video-pipeline" / "scripts" / "comfy_guarded_submit.py"
V003 = "seedvr2/v003-7b-int8-tile768-int17-raw21"


class _Unevaluable(Exception):
    pass


def _eval(node: ast.AST, known: dict):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in known:
        return known[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand, known)
    if isinstance(node, ast.Dict):
        return {_eval(k, known): _eval(v, known) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Set):
        return {_eval(item, known) for item in node.elts}
    if isinstance(node, (ast.Tuple, ast.List)):
        return [_eval(item, known) for item in node.elts]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "frozenset":
        return frozenset(_eval(node.args[0], known))
    raise _Unevaluable(ast.dump(node)[:60])


def _strings(node: ast.AST) -> list[str]:
    """String literals of a ``Path(...) / "a" / "b"`` expression, left to right."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.BinOp):
        return _strings(node.left) + _strings(node.right)
    if isinstance(node, ast.Call):
        return [text for arg in node.args for text in _strings(arg)]
    return []


def _parse(path: Path) -> tuple[dict, dict]:
    """(evaluable constants, module-level expression nodes) of a source file, read-only."""
    tree = ast.parse(path.read_bytes().decode("utf-8"), filename=str(path))
    values: dict = {}
    nodes: dict = {}
    for item in tree.body:
        if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
            name = item.targets[0].id
            nodes[name] = item.value
            try:
                values[name] = _eval(item.value, values)
            except _Unevaluable:
                pass
    return values, nodes


@pytest.fixture(scope="module")
def config():
    return loader.resolve_episode("04-milk-and-mom")


@pytest.fixture(scope="module")
def recipe(config):
    return config.recipes["seedvr2"]


@pytest.fixture(scope="module")
def prepare():
    return _parse(PREPARE)


@pytest.fixture(scope="module")
def execute():
    return _parse(EXECUTE)


GEOMETRY_NAMES = {
    "FPS": "fps", "PADDING_ALIGNMENT": "padding_alignment", "PADDING_FORMULA": "padding_formula",
    "CORE_FRAMES": "core_frames", "CONTEXT_FRAMES_EACH_SIDE": "context_frames_each_side",
    "MAX_RAW_SEGMENT_FRAMES": "max_raw_segment_frames",
    "INTERNAL_SAMPLER_MAX_PIXEL_FRAMES": "internal_sampler_max_pixel_frames",
    "TILE_SIZE": "tile_size", "TILE_OVERLAP": "tile_overlap",
    "PROCESSING_WIDTH": "processing_width", "PROCESSING_HEIGHT": "processing_height",
    "FINAL_WIDTH": "final_width", "FINAL_HEIGHT": "final_height",
    "FINAL_CROP_LEFT": "final_crop_left", "FINAL_CROP_TOP": "final_crop_top",
}


def test_the_stated_v003_numbers_are_in_the_recipe(recipe) -> None:
    geo = recipe["geometry"]
    assert (geo["core_frames"], geo["context_frames_each_side"], geo["max_raw_segment_frames"]) == (13, 4, 21)
    assert geo["internal_sampler_max_pixel_frames"] == 17
    assert (geo["tile_size"], geo["tile_overlap"]) == (768, 64)
    assert (geo["processing_width"], geo["processing_height"]) == (3888, 2160)
    assert (geo["final_width"], geo["final_height"], geo["final_crop_left"], geo["final_crop_top"]) == (3840, 2160, 24, 0)
    assert geo["fps"] == "24/1"
    assert recipe["native"] == {"width": 864, "height": 480}
    assert recipe["domain"] == "jenniejoy_cartoon_3d"


@pytest.mark.parametrize("constant,key", sorted(GEOMETRY_NAMES.items()))
def test_prepare_geometry_constants_equal_recipe(prepare, recipe, constant, key) -> None:
    assert prepare[0][constant] == recipe["geometry"][key]


def test_prepare_geometry_constants_are_all_present_and_evaluable(prepare) -> None:
    assert set(GEOMETRY_NAMES) <= set(prepare[0])


@pytest.mark.parametrize("constant,key", [
    (c, k) for c, k in sorted(GEOMETRY_NAMES.items())
    if c in {"FPS", "PADDING_ALIGNMENT", "PROCESSING_WIDTH", "PROCESSING_HEIGHT",
             "FINAL_WIDTH", "FINAL_HEIGHT"}
])
def test_execute_geometry_constants_equal_recipe(execute, recipe, constant, key) -> None:
    assert execute[0][constant] == recipe["geometry"][key]


def test_execute_crop_and_encoding_equal_recipe(execute, recipe) -> None:
    geo = recipe["geometry"]
    assert (execute[0]["CROP_LEFT"], execute[0]["CROP_TOP"]) == (geo["final_crop_left"], geo["final_crop_top"])
    assert execute[0]["CORE_ENCODING"] == geo["core_encoding"]


def test_qualified_recipe_dict_equals_graph_recipe(prepare, recipe) -> None:
    assert json.loads(json.dumps(prepare[0]["QUALIFIED_RECIPE"])) == recipe["graph_recipe"]
    assert prepare[0]["QUALIFIED_RECIPE"]["sampler_seed"] == 2_026_101_806


def test_prepare_pilot_evidence_equals_recipe(prepare, recipe, config) -> None:
    pilot, values = recipe["pilot"], prepare[0]
    assert values["PILOT_API_FILE_SHA256"] == pilot["graph_file_sha256"]
    assert values["PILOT_API_CANONICAL_SHA256"] == pilot["graph_canonical_sha256"]
    assert values["PILOT_API_RECIPE_SHA256"] == pilot["graph_recipe_sha256"]
    assert values["PILOT_GUI_FILE_SHA256"] == pilot["gui_file_sha256"]
    assert values["PILOT_GPU_SECONDS"] == pilot["server_execution_s"]
    assert values["PILOT_SAMPLED_PEAK_RAM_BYTES"] == pilot["sampled_peak_container_memory_bytes"]
    assert values["PILOT_SAMPLED_PEAK_GPU_MIB"] == pilot["sampled_peak_gpu_mib"]
    assert set(values["ALLOWED_API_DIFF_PATHS"]) == set(recipe["allowed_api_diff_paths"])
    assert values["PRODUCTION_DOMAIN"] == recipe["domain"]
    assert values["FILM_ID"] == config.episode["film_id"]
    assert pilot["graph_file_sha256"].startswith("75f436c8") and pilot["prompt_id"].startswith("43f87ebe")


def test_qualification_receipt_matches_recipe(recipe) -> None:
    receipt_path = loader.REPO_ROOT / recipe["pilot"]["qualification_receipt"]
    assert sha256_file(receipt_path) == recipe["pilot"]["qualification_receipt_sha256"]
    receipt = json.loads(receipt_path.read_text("utf-8"))
    assert receipt["status"] == "PASS" and receipt["production_domain"] == recipe["domain"]
    assert receipt["prompt_id"] == recipe["pilot"]["prompt_id"]
    assert receipt["graph"]["file_sha256"] == recipe["pilot"]["graph_file_sha256"]
    assert receipt["graph"]["canonical_sha256"] == recipe["pilot"]["graph_canonical_sha256"]
    assert receipt["graph"]["recipe_sha256"] == recipe["pilot"]["graph_recipe_sha256"]
    for ours, theirs in (("diffusion", "model"), ("vae", "vae")):
        for field in ("size_bytes", "sha256"):
            assert receipt[theirs][field] == recipe["models"][ours][field]
        assert PureWindowsPath(receipt[theirs]["path"]).name == recipe["models"][ours]["file"]
    assert (receipt["tile"]["size"], receipt["tile"]["overlap"]) == (768, 64)
    assert receipt["qualifies_only"]["internal_sampler_max_pixel_frames"] == 17
    assert receipt["server_execution_s"] == recipe["pilot"]["server_execution_s"]
    assert receipt["sampled_peak_gpu_mib"] == recipe["pilot"]["sampled_peak_gpu_mib"]
    assert receipt["sampled_peak_container_memory_bytes"] == recipe["pilot"]["sampled_peak_container_memory_bytes"]
    assert (receipt["raw"]["width"], receipt["raw"]["height"], receipt["raw"]["frames"]) == (3888, 2160, 21)
    assert (receipt["preview"]["width"], receipt["preview"]["height"], receipt["preview"]["frames"]) == (3840, 2160, 13)


def _lock_parts(config) -> tuple[PureWindowsPath, PureWindowsPath]:
    lock = PureWindowsPath(config.machine["gpu_lock_path"])
    return lock, lock.parent.parent  # (lock file, episode root)


def test_machine_equals_execute_constants(execute, config) -> None:
    machine, (values, nodes) = config.machine, execute
    assert values["DEFAULT_COMFY_URL"] == machine["comfy"]["url"]
    assert values["DEFAULT_CONTAINER"] == machine["comfy"]["container"]
    lock, episode_root = _lock_parts(config)
    assert _strings(nodes["SHARED_SUBMIT_LOCK"]) == list(lock.parts[-2:])
    assert values["FILM_ID"] == episode_root.name
    comfy_root = PureWindowsPath(machine["comfy"]["root"])
    assert _strings(nodes["COMFY_ROOT"]) == [comfy_root.name]
    assert comfy_root.parent == episode_root.parents[1]  # EPISODE_ROOT.parents[1] / "ComfyUI"


def test_machine_equals_guarded_helper_constants(config) -> None:
    values, nodes = _parse(HELPER)
    machine = config.machine
    assert values["DEFAULT_BASE_URL"] == machine["comfy"]["url"]
    assert values["CONTAINER_NAME"] == machine["comfy"]["container"]
    lock, episode_root = _lock_parts(config)
    assert PureWindowsPath(_strings(nodes["EPISODE04"])[0]) == episode_root
    assert _strings(nodes["DEFAULT_LOCK_PATH"]) == list(lock.parts[-2:])
    assert PureWindowsPath(_strings(nodes["DEFAULT_OUTPUT_DIR"])[0]) == PureWindowsPath(machine["comfy"]["output_dir"])
    forbidden = {name.lower() for name in config.domain["forbidden_node_classes"]}
    assert set(values["PARTNER_DENY_LIST"]) <= forbidden


def test_parity_reads_never_wrote_the_frozen_files() -> None:
    from engine import frozen
    results = frozen.verify_files(frozen.load_manifest())
    assert results and all(item.match for item in results)
