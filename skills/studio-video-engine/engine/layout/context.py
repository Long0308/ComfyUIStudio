"""Episode context and recipe loading shared by ``jjv layout`` and ``jjv images``.

Deliberately lighter than ``config.loader.resolve_episode``: these stages run before the episode has
shots/mouth-boxes of its own, so only the episode, its domain and the machine file are read (no schema
gate on the machine file; a missing optional key is simply absent).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.loader import DEFAULT_MACHINE_PATH, REPO_ROOT, SKILL_ROOT, find_episode_file
from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file

RECIPE_DIR = SKILL_ROOT / "recipes" / "images"
ROUTES_RECIPE = "routes-v002"  # user 2026-10-30: live-action images hybrid; routes-v001.json is kept byte for byte


@dataclass(frozen=True)
class Context:
    episode_file: Path
    root: Path
    episode: dict[str, Any]
    domain_id: str
    domain: dict[str, Any]
    machine: dict[str, Any]
    machine_path: Path

    @property
    def episode_id(self) -> str:
        return str(self.episode["episode_id"])


def load_context(ref: str, machine_path: str | Path | None = None) -> Context:
    episode_file = find_episode_file(ref)
    episode = read_json(episode_file)
    if not isinstance(episode, dict) or not isinstance(episode.get("domain"), str) or "episode_id" not in episode:
        raise Uncertain(f"{episode_file}: not an episode document (needs episode_id and domain)")
    domain_file = SKILL_ROOT / "domains" / f"{episode['domain']}.json"
    if not domain_file.is_file():
        raise Refused(f"episode names domain {episode['domain']!r} but {domain_file.name} does not exist")
    machine_file = Path(machine_path) if machine_path else DEFAULT_MACHINE_PATH
    return Context(episode_file, episode_file.parent.parent, episode, episode["domain"],
                   read_json(domain_file), read_json(machine_file), machine_file)


def load_recipe(name: str, schema: str | None = None) -> tuple[dict[str, Any], str]:
    """``(recipe, sha256 of the file)`` from ``recipes/images/<name>.json``."""
    path = RECIPE_DIR / f"{name}.json"
    recipe = read_json(path)
    if not isinstance(recipe, dict) or (schema and recipe.get("schema") != schema):
        raise Uncertain(f"{path.name}: not a {schema or 'recipe'} document")
    return recipe, sha256_file(path)


def domain_policy(ctx: Context) -> dict[str, Any]:
    """The routes-recipe row for this domain; an unlisted domain gets NO provider (refuse everything)."""
    routes, _ = load_recipe(ROUTES_RECIPE, "jjv/images-routes/v1")
    row = dict(routes["domains"].get(ctx.domain_id) or {"allowed_providers": [], "brief_status": "draft",
                                                         "cast_ref_in_brief": False})
    tighter = (ctx.domain.get("images") or {}).get("allowed_providers")
    if isinstance(tighter, list):  # a domain file may only narrow the list
        row["allowed_providers"] = [p for p in row["allowed_providers"] if p in tighter]
    return row


def require_provider(ctx: Context, provider: str) -> None:
    allowed = domain_policy(ctx)["allowed_providers"]
    if provider not in allowed:
        raise Refused(f"provider {provider!r} is not allowed for domain {ctx.domain_id!r} (allowed: {allowed}); "
                      "nothing was sent")


def default_provider(ctx: Context) -> str:
    """First provider of the domain's ``preferred_order`` that the domain also allows (routes recipe data)."""
    policy = domain_policy(ctx)
    for provider in policy.get("preferred_order", policy["allowed_providers"]):
        if provider in policy["allowed_providers"] and provider != "codex-adopt":
            return provider
    raise Refused(f"domain {ctx.domain_id!r} has no submit provider (allowed: {policy['allowed_providers']})")


def rel(path: Path | str, base: Path) -> str:
    """POSIX path relative to ``base`` when inside it, else the absolute POSIX path."""
    resolved, root = Path(path).resolve(), Path(base).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


__all__ = ["Context", "REPO_ROOT", "SKILL_ROOT", "RECIPE_DIR", "ROUTES_RECIPE", "load_context", "load_recipe", "domain_policy", "default_provider",
           "require_provider", "rel"]
