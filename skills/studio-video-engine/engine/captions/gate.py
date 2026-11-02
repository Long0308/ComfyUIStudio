"""Receipt-bound timing authorization shared by captions build and burn."""

from pathlib import Path

from ..config.loader import resolve_episode
from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from ..timing.recipe import resolve_recipe


def object_field(document: dict, key: str) -> dict:
    value = document.get(key, {})
    if not isinstance(value, dict):
        raise Refused(f"receipt field {key!r} must be an object")
    return value


def require_timing(episode: str, timing_path: Path, receipt_path: Path | None = None) -> tuple:
    if not episode:
        raise Refused("captions requires --episode and a qualified timing receipt")
    config = resolve_episode(episode)
    timing = read_json(timing_path)
    receipt_path = Path(receipt_path or timing_path.parent / "timing-receipt.json")
    receipt = read_json(receipt_path)
    if not isinstance(timing, dict) or not isinstance(receipt, dict):
        raise Refused("timing and timing receipt must be JSON objects")
    declared = timing.get("recipe")
    if not isinstance(declared, dict) or not isinstance(declared.get("id"), str):
        raise Refused("WORD-TIMING has no recipe id")
    # This checks the resolved domain's timing.allowed_recipes, including narrowing.
    recipe, _ = resolve_recipe(config, declared["id"])
    expected = {"id": recipe.recipe_id, "sha256": recipe.sha256}
    if (declared != expected or object_field(receipt, "inputs").get("recipe") != expected
            or timing.get("episode_id") != config.episode["episode_id"]):
        raise Refused("timing recipe hash/domain/episode binding mismatch")
    digest = sha256_file(timing_path)
    if (receipt.get("schema") != "jjv/timing-words-receipt/v1"
            or object_field(receipt, "outputs").get("WORD-TIMING.json") != digest
            or receipt.get("ok") is not True or receipt.get("verdict") != "PASS"):
        raise Refused("WORD-TIMING receipt is stale or not PASS")
    return config, timing, {"path": str(timing_path), "sha256": digest,
                            "receipt_path": str(receipt_path), "receipt_sha256": sha256_file(receipt_path),
                            "recipe": expected, "domain": config.domain["domain_id"]}
