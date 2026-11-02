"""Loading and selecting audio recipes (``recipes/audio/<name>.json``) plus the optional config accessors.

The machine/domain/episode schemas are frozen, so the audio stage reads its optional keys
(``episode.audio``, ``domain.audio``) through :func:`optional_block`; see ``CONFIG-PATCH.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config.loader import SKILL_ROOT, ResolvedConfig
from ..config.schema import validate
from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from .limits import require_cinema, require_music
from .recipe_schema import SCHEMAS

FAMILY_KEYS = {"audio-music": "music", "audio-sfx": "sfx", "audio-mix": "mix"}


@dataclass(frozen=True)
class AudioRecipe:
    recipe_id: str
    family: str
    path: Path
    sha256: str
    data: dict


def optional_block(document: object, key: str) -> dict:
    value = document.get(key) if isinstance(document, dict) else None
    return value if isinstance(value, dict) else {}


def _check_graph_slots(data: dict) -> None:
    graph = data["graph"]
    for model in data["models"]:
        bind = model["graph_binding"]
        node = graph.get(bind["node"])
        if not isinstance(node, dict) or node.get("inputs", {}).get(bind["input"]) != bind["value"]:
            raise Refused(f"recipe {data['recipe_id']!r}: model {model['role']!r} is not bound to graph "
                          f"node {bind['node']}.{bind['input']}={bind['value']!r}")
        if not model["path"].replace("\\", "/").endswith(bind["value"]):
            raise Refused(f"recipe {data['recipe_id']!r}: model path {model['path']!r} does not end in {bind['value']!r}")
        if model["licence_id"] not in data["licences"]:
            raise Refused(f"recipe {data['recipe_id']!r}: licence {model['licence_id']!r} is not declared")
    pairs = [pair for slot in data["slots"].values() for pair in slot] + [[data["output"]["node"], "filename_prefix"]]
    for node, field in pairs:
        if node not in graph or field not in graph[node].get("inputs", {}):
            raise Refused(f"recipe {data['recipe_id']!r}: slot {node}.{field} does not exist in the graph")


def load_recipe(recipe_id: str, family: str, *, skill_root: Path = SKILL_ROOT, domain: dict | None = None) -> AudioRecipe:
    if not recipe_id.startswith("audio/") or ".." in recipe_id:
        raise Refused(f"audio recipe id must be audio/<name>, got {recipe_id!r}")
    path = skill_root / "recipes" / f"{recipe_id}.json"
    if not path.is_file():
        raise Refused(f"audio recipe not found: {path}")
    data = read_json(path)
    errors = validate(data, SCHEMAS[family], label=f"recipe[{recipe_id}]")
    if errors:
        raise Refused("; ".join(errors))
    if data["recipe_id"] != recipe_id:
        raise Refused(f"recipe file declares recipe_id {data['recipe_id']!r}, expected {recipe_id!r}")
    if family != "audio-mix":
        _check_graph_slots(data)
        if family == "audio-music":
            require_music(data)
    elif data["profile"] == "cinema":
        require_cinema(data, sfx_default_on_allowed=optional_block(domain or {}, "audio").get("sfx_default_on") is True)
    return AudioRecipe(recipe_id, family, path, sha256_file(path), data)


def select_recipe_id(config: ResolvedConfig, family: str, explicit: str | None, *,
                     skill_root: Path = SKILL_ROOT) -> tuple[str, str]:
    """``--recipe`` > ``episode.audio.<music|sfx|mix>.recipe`` > the single recipe of the family for the domain."""
    if explicit:
        return explicit, "cli"
    declared = optional_block(optional_block(config.episode, "audio"), FAMILY_KEYS[family]).get("recipe")
    if isinstance(declared, str) and declared:
        return declared, f"episode.audio.{FAMILY_KEYS[family]}.recipe"
    domain_id = config.domain["domain_id"]
    candidates: list[str] = []
    for path in sorted((skill_root / "recipes" / "audio").glob("*.json")):
        data = read_json(path)
        if isinstance(data, dict) and data.get("family") == family and data.get("domain") == domain_id:
            if family == "audio-mix" and (data.get("profile") != "cinema" or data.get("selectable_by_default") is False):
                continue  # a legacy (parity) or episode-pinned recipe is never a default: it is named explicitly
            candidates.append(str(data.get("recipe_id")))
    if len(candidates) == 1:
        return candidates[0], "unique recipe for the domain"
    raise Refused(f"no {family} recipe selected for domain {domain_id!r}: pass --recipe or set "
                  f"episode.audio.{FAMILY_KEYS[family]}.recipe (candidates: {candidates})")


def resolve_recipe(config: ResolvedConfig, family: str, explicit: str | None, *,
                   skill_root: Path = SKILL_ROOT) -> tuple[AudioRecipe, str]:
    recipe_id, origin = select_recipe_id(config, family, explicit, skill_root=skill_root)
    recipe = load_recipe(recipe_id, family, skill_root=skill_root, domain=config.domain)
    if recipe.data["domain"] != config.domain["domain_id"]:
        raise Refused(f"recipe {recipe_id!r} belongs to domain {recipe.data['domain']!r}, "
                      f"episode domain is {config.domain['domain_id']!r}")
    allowed = optional_block(config.domain, "audio").get("allowed_recipes")
    if isinstance(allowed, list) and recipe_id not in allowed:
        raise Refused(f"domain {config.domain['domain_id']!r} does not list audio recipe {recipe_id!r}")
    return recipe, origin
