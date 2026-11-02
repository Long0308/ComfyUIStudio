"""Read-only verification of a recipe's pins against the evidence files on disk.

A recipe is only as good as its qualification.  At load we check, without writing anything:
the qualification receipt sha256 and its content against the recipe, the pilot API graph file
sha256, its canonical sha256 and its recipe sha256, and the canonical pin of the
``graph_recipe`` value block.  Paths in the recipe are relative to ``repo_root``.
"""

from __future__ import annotations

from pathlib import Path

from ..core.errors import EngineError, Refused
from ..core.io import canonical_sha256, read_json, sha256_file
from ..seedvr2.recipe import extract_graph_recipe, graph_recipe_sha256


def _read(path: Path) -> dict | None:
    try:
        value = read_json(path)  # strict reader: NaN/Infinity and malformed JSON are unreadable
    except EngineError:
        return None
    return value if isinstance(value, dict) else None


def check_recipe_self_pins(recipe: dict) -> list[str]:
    """Pins that need no disk: the value blocks must equal their canonical-ascii pins.

    The receipt proves the envelope (raw frames, tile, internal frames) but not core/context,
    so the whole ``geometry`` block is pinned as well as ``graph_recipe``.
    """
    rid, pilot = recipe["recipe_id"], recipe["pilot"]
    problems: list[str] = []
    for block, pin in (("graph_recipe", "graph_recipe_block_sha256"), ("geometry", "geometry_block_sha256")):
        actual = canonical_sha256(recipe[block], mode="ascii")
        if actual != pilot[pin]:
            problems.append(f"recipe {rid}: {block} canonical sha256 {actual} != pinned {pilot[pin]}")
    return problems


def check_recipe_pins(recipe: dict, repo_root: Path) -> list[str]:
    rid, pilot = recipe["recipe_id"], recipe["pilot"]
    problems = check_recipe_self_pins(recipe)
    problems.extend(_check_receipt(rid, recipe, pilot, Path(repo_root)))
    problems.extend(_check_graph(rid, pilot, recipe["graph_recipe"], Path(repo_root)))
    return problems


def _check_receipt(rid: str, recipe: dict, pilot: dict, repo_root: Path) -> list[str]:
    path = repo_root / pilot["qualification_receipt"]
    if not path.is_file():
        return [f"recipe {rid}: qualification receipt not found: {path}"]
    actual = sha256_file(path)
    if actual != pilot["qualification_receipt_sha256"]:
        return [f"recipe {rid}: qualification receipt sha256 {actual} != pinned "
                f"{pilot['qualification_receipt_sha256']}"]
    receipt = _read(path)
    if receipt is None:
        return [f"recipe {rid}: qualification receipt is not a JSON object"]
    graph = receipt.get("graph") or {}
    expected = {
        "status": ("PASS", receipt.get("status")),
        "prompt_id": (pilot["prompt_id"], receipt.get("prompt_id")),
        "graph.file_sha256": (pilot["graph_file_sha256"], graph.get("file_sha256")),
        "graph.canonical_sha256": (pilot["graph_canonical_sha256"], graph.get("canonical_sha256")),
        "graph.recipe_sha256": (pilot["graph_recipe_sha256"], graph.get("recipe_sha256")),
        "model.sha256": (recipe["models"]["diffusion"]["sha256"], (receipt.get("model") or {}).get("sha256")),
        "vae.sha256": (recipe["models"]["vae"]["sha256"], (receipt.get("vae") or {}).get("sha256")),
        "frames.raw": (recipe["geometry"]["max_raw_segment_frames"], (receipt.get("frames") or {}).get("raw")),
    }
    qualifies = receipt.get("qualifies_only") or {}
    for key, want in (("raw_frames", recipe["geometry"]["max_raw_segment_frames"]),
                      ("tile_size", recipe["geometry"]["tile_size"]),
                      ("tile_overlap", recipe["geometry"]["tile_overlap"]),
                      ("internal_sampler_max_pixel_frames", recipe["geometry"]["internal_sampler_max_pixel_frames"])):
        expected[f"qualifies_only.{key}"] = (want, qualifies.get(key))
    return [f"recipe {rid}: qualification receipt {key} {got!r} != recipe {want!r}"
            for key, (want, got) in expected.items() if want != got]


def _check_graph(rid: str, pilot: dict, recipe_block: dict, repo_root: Path) -> list[str]:
    path = repo_root / pilot["graph_file"]
    if not path.is_file():
        return [f"recipe {rid}: pilot graph file not found: {path}"]
    problems: list[str] = []
    actual = sha256_file(path)
    if actual != pilot["graph_file_sha256"]:
        problems.append(f"recipe {rid}: pilot graph file sha256 {actual} != pinned {pilot['graph_file_sha256']}")
    graph = _read(path)
    if graph is None:
        return problems + [f"recipe {rid}: pilot graph file is not a JSON object"]
    if canonical_sha256(graph, mode=pilot["graph_canonical_mode"]) != pilot["graph_canonical_sha256"]:
        problems.append(f"recipe {rid}: pilot graph canonical sha256 differs from the pin")
    try:
        derived = graph_recipe_sha256(graph, mode=pilot["graph_recipe_sha256_canonical_mode"])
    except Refused:
        return problems + [f"recipe {rid}: pilot graph lacks node 1 file / node 15 filename_prefix"]
    if derived != pilot["graph_recipe_sha256"]:
        problems.append(f"recipe {rid}: pilot graph recipe sha256 {derived} != pinned {pilot['graph_recipe_sha256']}")
    return problems + _check_block_binding(rid, recipe_block, graph)


def _check_block_binding(rid: str, block: dict, graph: dict) -> list[str]:
    """The graph_recipe block must equal the values the pinned pilot graph actually carries,
    so rewriting a value together with its own pin is still refused."""
    try:
        extracted = extract_graph_recipe(graph)
    except Refused:
        return [f"recipe {rid}: pilot graph lacks a qualified recipe key"]
    return [f"recipe {rid}: graph_recipe.{key} {block.get(key)!r} != pilot graph value {extracted.get(key)!r}"
            for key in sorted(set(extracted) | set(block)) if extracted.get(key) != block.get(key)]
