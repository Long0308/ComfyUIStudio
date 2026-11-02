"""``jjv deliver init``: write the delivery sidecar from domain policy, the locked episode contract and machine facts.

Write-once (an existing file is refused, never replaced) and stamped with the engine provenance header.

Every value comes from a data source: the domain and contract (film_2k, master, contract), machine.json
(tool paths, studio URL), the brand kit's per-episode files (names from ``recipes/deliver/brand-kit.json``),
or the episode root (output folders). A value with no source is written as an explicit marker
``{"missing": "MISSING_MACHINE_KEY:<key>"}`` or ``{"missing": "MISSING_EPISODE_KEY:<key>"}``; the brand and
publish verbs refuse on that marker by name, and the names are listed in the result under ``unresolved``.
No literal path is ever invented.

Placement: the default target is the episode's canonical ``<episode>/engine/delivery.json`` (``canonical``
true). An explicit ``--delivery-config`` must lie outside every episode tree and is marked ``canonical``
false; consumers refuse a non-canonical sidecar unless it is named explicitly.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from ..config.loader import REPO_ROOT, SKILL_ROOT, find_episode_file
from ..config.rules import timeline_frames
from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_once
from ..core.paths import resolve_data_path
from .guard import canonical_placement, contained_write

SCHEMA = "jjv/delivery-config/v1"
RESULT_SCHEMA = "jjv/deliver-init/v1"
KIT_RECIPE = SKILL_ROOT / "recipes" / "deliver" / "brand-kit.json"
KIT_RECIPE_SCHEMA = "jjv/deliver-brand-kit/v1"
FILM_2K = (2560, 1440, "lanczos")
PROPS_KEYS = ("titleEn", "titleVi", "subtitle", "brandLine", "background", "logo")
MISSING_FILM = "MISSING_EPISODE_KEY:brand.film"
MISSING_ARTIFACTS = "MISSING_EPISODE_KEY:publish.artifacts"
MISSING_PROPS = "MISSING_EPISODE_KEY:brand.props"
MISSING_INTRO = "MISSING_EPISODE_KEY:brand.intro"
MISSING_TITLE = "MISSING_EPISODE_KEY:brand.title"


def _kit_names() -> dict:
    """Brand-kit file-name patterns from the recipe; refuses a missing or malformed recipe by name."""
    if not KIT_RECIPE.is_file():
        raise Refused(f"brand kit recipe missing: {KIT_RECIPE}")
    data = read_json(KIT_RECIPE)
    if not isinstance(data, dict) or data.get("schema") != KIT_RECIPE_SCHEMA:
        raise Refused(f"brand kit recipe {KIT_RECIPE} must declare schema {KIT_RECIPE_SCHEMA!r}")
    names = {key: data.get(key) for key in ("props", "intro", "title")}
    if any(not isinstance(v, str) or not v for v in names.values()):
        raise Refused(f"brand kit recipe {KIT_RECIPE} must declare non-empty props, intro and title")
    if names["title"].count("{slug}") != 1 or "{" in names["intro"] or "{" in names["props"]:
        raise Refused(f"brand kit recipe {KIT_RECIPE}: only title may hold one {{slug}} placeholder")
    return names


def _relative(base: Path, target: Path) -> str:
    """Path of ``target`` relative to ``base`` (delivery.json directory), POSIX form."""
    try:
        return Path(os.path.relpath(target, base)).as_posix()
    except ValueError:  # different drive on Windows: fall back to an absolute path
        return target.as_posix()


def _marker(name: str) -> dict:
    return {"missing": name}


def _load_domain(skill_root: Path, domain_id: str) -> dict:
    file = Path(skill_root) / "domains" / f"{domain_id}.json"
    if not file.is_file():
        raise Refused(f"domain file missing for {domain_id!r}: {file}")
    domain = read_json(file)
    if domain.get("domain_id") != domain_id:
        raise Refused(f"domain file {file} declares domain_id {domain.get('domain_id')!r}")
    return domain


def _lookup(machine: dict, keys: tuple) -> str | None:
    node = machine
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, str) and node.strip() else None


def _machine_path(machine: dict, keys: tuple, repo_root: Path, *, file: bool = False):
    """Absolute path from machine.json; a marker names the absent key, or the key whose path is not on disk."""
    raw = _lookup(machine, keys)
    dotted = ".".join(keys)
    if raw is None:
        return _marker(f"MISSING_MACHINE_KEY:{dotted}")
    candidate = resolve_data_path(Path(raw) if Path(raw).is_absolute() else Path(repo_root) / raw, machine)
    present = candidate.is_file() if file else candidate.is_dir()
    return str(candidate) if present else _marker(f"MISSING_PATH:{dotted}")


def _brand_kit_files(kit, episode_id: str, names: dict) -> dict:
    """props, intro and title of this episode from the brand kit; markers when the kit or a file is absent."""
    if isinstance(kit, dict):  # kit itself unresolved: everything that depends on it is blocked by that key
        return {"props": kit, "intro": kit, "title": kit}
    folder = Path(kit) / "episodes" / episode_id
    slug = re.sub(r"^\d+-", "", episode_id)
    props_file = folder / names["props"]
    props = read_json(props_file) if props_file.is_file() else None
    if isinstance(props, dict) and all(isinstance(props.get(k), str) and props[k] for k in PROPS_KEYS):
        props = {key: props[key] for key in PROPS_KEYS}
    else:
        props = _marker(MISSING_PROPS)
    intro = folder / names["intro"]
    title = folder / names["title"].format(slug=slug)
    return {"props": props,
            "intro": str(intro) if intro.is_file() else _marker(MISSING_INTRO),
            "title": str(title) if title.is_file() else _marker(MISSING_TITLE)}


def _brand_block(episode: dict, machine: dict, *, target: Path, episode_root: Path, repo_root: Path) -> dict:
    kit = _machine_path(machine, ("brand", "kit"), repo_root)
    files = _brand_kit_files(kit, episode["episode_id"], _kit_names())

    def out(name: str) -> str:
        return _relative(target.parent, episode_root / "delivery" / "v001" / name)

    return {
        "kit": kit,
        "workspace": str(Path(repo_root).resolve()),
        "packages": _machine_path(machine, ("node_modules",), repo_root),
        "browser": _machine_path(machine, ("remotion", "browser"), repo_root, file=True),
        "props": files["props"],
        "intro": files["intro"],
        "title": files["title"],
        "film": _marker(MISSING_FILM),
        "title_out": out("brand-title"),
        "join_out": out("brand-join"),
    }


def _publish_block(machine: dict, *, target: Path, episode_root: Path, repo_root: Path) -> dict:
    url = _lookup(machine, ("studio", "url"))
    return {
        "library": _machine_path(machine, ("publish", "film_library"), repo_root, file=True),
        "studio_url": url if url is not None else _marker("MISSING_MACHINE_KEY:studio.url"),
        "artifacts": _marker(MISSING_ARTIFACTS),
        "out": _relative(target.parent, episode_root / "delivery" / "v001" / "publish"),
    }


def build_document(episode: dict, domain: dict, *, target: Path, episode_root: Path,
                   machine: dict | None = None, repo_root: Path = REPO_ROOT, canonical: bool = True) -> dict:
    """The unstamped sidecar document; every refusal happens here, before anything is written."""
    spec = domain.get("delivery", {}).get("film_2k")
    if not spec or (spec.get("width"), spec.get("height"), spec.get("method")) != FILM_2K:
        raise Refused(f"domain {domain['domain_id']!r} declares no 2560x1440 lanczos delivery.film_2k; "
                      "deliver init refuses it (live-action film_2k needs its own qualification)")
    contract = episode.get("contract")
    if not isinstance(contract, dict) or not isinstance(contract.get("revision"), str):
        raise Refused("episode has no locked contract with a revision; lock it with `jjv config contract --write`")
    master = domain["delivery"]["master"]
    frames = timeline_frames(episode, domain)
    out = episode_root / "delivery" / "v001" / "2k"
    machine = machine or {}
    return {
        "schema": SCHEMA,
        "canonical": canonical,
        "episode_id": episode["episode_id"],
        "domain": episode["domain"],
        "film_2k": {"out": _relative(target.parent, out)},
        "master": {"width": master["width"], "height": master["height"], "fps": master["fps"],
                   "total_frames": frames["total_frames"]},
        "contract": {"revision": contract["revision"], "main_frames": frames["main_frames"],
                     "end_card_frames": frames["end_card_frames"]},
        "brand": _brand_block(episode, machine, target=target, episode_root=episode_root, repo_root=repo_root),
        "publish": _publish_block(machine, target=target, episode_root=episode_root, repo_root=repo_root),
    }


def _unresolved(node, found: list) -> list:
    """Every marker name in the document, first occurrence order, without duplicates."""
    if isinstance(node, dict):
        if set(node) == {"missing"} and isinstance(node["missing"], str):
            if node["missing"] not in found:
                found.append(node["missing"])
        else:
            for value in node.values():
                _unresolved(value, found)
    elif isinstance(node, list):
        for value in node:
            _unresolved(value, found)
    return found


def init_delivery(episode, *, delivery_config=None, repo_root=REPO_ROOT, skill_root=SKILL_ROOT,
                  machine_path=None) -> dict:
    """Write ``<episode>/engine/delivery.json`` (default, canonical) or an explicit non-canonical path, once."""
    ep_file = find_episode_file(str(episode), Path(repo_root)).resolve()
    ep = read_json(ep_file)
    if not isinstance(ep.get("episode_id"), str) or not isinstance(ep.get("domain"), str):
        raise Refused("episode.json must declare string episode_id and domain")
    domain = _load_domain(Path(skill_root), ep["domain"])
    own = ep_file.parent / "delivery.json"
    target = contained_write(Path(delivery_config) if delivery_config else own, Path(repo_root),
                             "delivery config")
    canonical = canonical_placement(target, own, "delivery config")
    machine_file = Path(machine_path) if machine_path else Path(repo_root) / "production-local" / "engine" / "machine.json"
    machine = read_json(machine_file) if machine_file.is_file() else {}
    document = build_document(ep, domain, target=target, episode_root=ep_file.parent.parent,
                              machine=machine, repo_root=Path(repo_root), canonical=canonical)
    if target.exists():
        raise Refused(f"delivery config already exists (write-once): {target}")
    digest = write_json_once(target, document, mode="ascii", stamp=True)
    return {
        "schema": RESULT_SCHEMA,
        "target": str(target),
        "canonical": canonical,
        "sha256": digest,
        "unresolved": _unresolved(document, []),
        "binding": {"episode_sha256": sha256_file(ep_file),
                    "domain_sha256": sha256_file(Path(skill_root) / "domains" / f"{ep['domain']}.json"),
                    "machine_sha256": sha256_file(machine_file) if machine_file.is_file() else None},
        "document": read_json(target),
    }
