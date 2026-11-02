"""Configuration layer: machine -> domain -> recipe -> episode, with no loosening.

Precedence is machine, then domain, then recipe, then episode.  The episode is the last
layer but it is *not* allowed to win a conflict: every domain, recipe and machine value is
locked, and an episode may only restate it or tighten the list rules in
:data:`engine.config.rules.SUPERSET_ONLY` / ``SUBSET_ONLY``.  All violations are collected
so one run reports everything wrong.

Nothing here names a domain, film or lock file; those facts live in the data files.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import canonical_sha256, read_json, sha256_file
from ..core.paths import require_inside
from ..core.provenance import engine_tree_sha256
from . import contract as contract_rules
from . import hashes, pins, rules
from .schema import validate

SKILL_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SKILL_ROOT.parents[2]
DEFAULT_MACHINE_PATH = REPO_ROOT / "production-local" / "engine" / "machine.json"
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SKELETON_SCHEMA = "jjv/shots-skeleton/v1"   # `jjv script ingest` output: shot list BEFORE any clip or WAV exists
_SHOT_ID = re.compile(r"^S[0-9]{2}_[A-Z][0-9]?$")


@dataclass(frozen=True)
class ResolvedConfig:
    machine: dict
    domain: dict
    recipes: dict
    episode: dict
    shots: list
    mouth_boxes: dict | None                # None when the episode names no files.mouth_boxes (no engine verb reads them)
    episode_root: str
    sources: dict
    config_sha256: str
    config_core_sha256: str = ""            # see engine/config/HASHES.md: which stage binds which hash
    delivery_contract_sha256: str | None = None

    def as_dict(self) -> dict:
        return copy.deepcopy({
            "machine": self.machine, "domain": self.domain, "recipes": self.recipes,
            "episode": self.episode, "shots": self.shots, "mouth_boxes": self.mouth_boxes,
            "episode_root": self.episode_root, "sources": self.sources,
            "config_sha256": self.config_sha256, "config_core_sha256": self.config_core_sha256,
            "delivery_contract_sha256": self.delivery_contract_sha256,
        })


@dataclass(frozen=True)
class ConfigReport:
    episode_file: str
    config: ResolvedConfig | None
    violations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


class ConfigViolation(Refused):
    """Config is invalid or tries to loosen a locked rule (exit 1, nothing was sent)."""

    def __init__(self, violations: tuple[str, ...]) -> None:
        super().__init__("; ".join(violations))
        self.violations = violations


def find_episode_file(ref: str, repo_root: Path = REPO_ROOT) -> Path:
    """Resolve ``ref`` (episode.json, engine dir, episode root or slug) to episode.json."""
    given = Path(ref)
    candidates = [given, given / "engine" / "episode.json", given / "episode.json"]
    for candidate in candidates:
        if candidate.is_file() and candidate.name == "episode.json":
            return candidate
    if not _SLUG.match(ref):
        raise Refused(f"no episode.json at {ref!r}")
    found = sorted((repo_root / "production-local").glob(f"*/{ref}/engine/episode.json"))
    if not found:
        raise Refused(f"no episode named {ref!r} under production-local/*/{ref}/engine/")
    if len(found) > 1:
        raise Refused(f"episode slug {ref!r} is ambiguous: {[str(p) for p in found]}")
    return found[0]


def _schema(skill_root: Path, name: str) -> dict:
    return read_json(skill_root / "schemas" / f"{name}.schema.json")


def _load(path: Path, schema_name: str, label: str, skill_root: Path,
          problems: list[str], sources: dict[str, str]) -> Any | None:
    """Read + schema-check one data file; record problems instead of raising on content."""
    if not path.is_file():
        problems.append(f"{label}: file not found: {path}")
        return None
    data = read_json(path)
    errors = validate(data, _schema(skill_root, schema_name), label=label)
    problems.extend(f"schema: {error}" for error in errors)
    sources[label] = sha256_file(path)
    return None if errors else data


def _load_recipes(episode: dict, skill_root: Path, repo_root: Path,
                  problems: list[str], sources: dict[str, str]) -> dict:
    recipes: dict[str, dict] = {}
    for family, rid in episode["recipes"].items():
        if rid.split("/", 1)[0] != family:
            problems.append(f"episode.recipes.{family}: recipe {rid!r} belongs to another family")
            continue
        recipe = _load(skill_root / "recipes" / f"{rid}.json", "recipe", f"recipe[{rid}]",
                       skill_root, problems, sources)
        if recipe is None:
            continue
        if recipe["recipe_id"] != rid:
            problems.append(f"recipe file for {rid!r} declares recipe_id {recipe['recipe_id']!r}")
        problems.extend(rules.check_recipe(recipe))
        problems.extend(pins.check_recipe_pins(recipe, repo_root))
        recipes[family] = recipe
    return recipes


def _load_skeleton(path: Path, label: str, problems: list[str], sources: dict[str, str]) -> dict | None:
    """A pre-render shot list (``jjv/shots-skeleton/v1``): shape-checked only; clip/WAV evidence does not exist yet."""
    data = read_json(path)
    rows = data.get("shots") if isinstance(data, dict) else None
    ids = [r.get("shot") for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    if not isinstance(rows, list) or not rows or len(ids) != len(rows) or len(set(ids)) != len(ids)             or not all(isinstance(i, str) and _SHOT_ID.match(i) for i in ids):
        problems.append(f"{label}: a {SKELETON_SCHEMA} document needs a non-empty shots list of unique shot ids")
        return None
    sources[label] = sha256_file(path)
    return data


def _is_skeleton(path: Path) -> bool:
    if not path.is_file():
        return False
    data = read_json(path)
    return isinstance(data, dict) and data.get("schema") == SKELETON_SCHEMA


def build_config(episode_file: Path, *, skill_root: Path = SKILL_ROOT,
                 machine_path: Path | None = None, repo_root: Path = REPO_ROOT,
                 prerender: bool = False) -> ConfigReport:
    """Load and check every layer; return a report instead of raising on bad content.

    ``prerender=True`` (stages that run BEFORE any clip exists, e.g. voice) also accepts a ``jjv/shots-skeleton/v1``
    shot list: it is shape-checked, the clip/WAV rules are skipped, and a real ``jjv/shots/v1`` is still fully
    validated exactly as before."""
    episode_file = Path(episode_file)
    problems: list[str] = []
    sources: dict[str, str] = {}
    episode = _load(episode_file, "episode", "episode", skill_root, problems, sources)
    if episode is None:
        return ConfigReport(str(episode_file), None, tuple(problems))
    if episode_file.parent.name != "engine":
        problems.append("episode.json must live in <episode root>/engine/")
    machine = _load(Path(machine_path or DEFAULT_MACHINE_PATH), "machine", "machine",
                    skill_root, problems, sources)
    if machine is not None:
        problems.extend(rules.check_machine(machine))
    domain = _load(skill_root / "domains" / f"{episode['domain']}.json", "domain",
                   f"domain[{episode['domain']}]", skill_root, problems, sources)
    if domain is not None:
        problems.extend(rules.check_domain(domain, episode["domain"]))
    recipes = _load_recipes(episode, skill_root, repo_root, problems, sources)
    names = episode["files"]
    shots_path = episode_file.parent / names["shots"]
    skeleton = prerender and _is_skeleton(shots_path)
    shots_doc = (_load_skeleton(shots_path, "shots", problems, sources) if skeleton
                 else _load(shots_path, "shots", "shots", skill_root, problems, sources))
    # mouth-boxes are OPTIONAL (M8b-e2): loaded and checked only when named; a named but missing file is a violation.
    named_boxes = names.get("mouth_boxes")
    boxes = _load(episode_file.parent / named_boxes, "mouth-boxes", "mouth-boxes",
                  skill_root, problems, sources) if named_boxes else None
    if None in (machine, domain, shots_doc) or (named_boxes and boxes is None):
        return ConfigReport(str(episode_file), None, tuple(problems))

    override_problems = rules.check_overrides(
        episode["overrides"], {"machine": machine, "domain": domain, "recipe": recipes})
    problems.extend(override_problems)
    problems.extend(_check_episode(episode, domain, shots_doc, boxes, skeleton=skeleton))
    delivery_sha = _check_contract_files(episode, domain, episode_file, skill_root, problems, sources)
    # The allow-list is judged AFTER tightening, so an episode cannot narrow it under a recipe.
    resolved_domain = domain if override_problems else rules.apply_tightening(domain, episode["overrides"])
    problems.extend(rules.check_domain(resolved_domain, episode["domain"]))
    for recipe in recipes.values():
        problems.extend(rules.check_recipe_in_domain(recipe, resolved_domain))
    if problems:
        return ConfigReport(str(episode_file), None, tuple(dict.fromkeys(problems)))
    body = {"machine": machine, "domain": resolved_domain, "recipes": recipes, "episode": episode,
            "shots": shots_doc["shots"], "mouth_boxes": boxes}
    config = ResolvedConfig(
        **{key: copy.deepcopy(value) for key, value in body.items()},
        episode_root=str(episode_file.parent.parent), sources=sources,
        config_sha256=canonical_sha256(hashes.full_body(body, delivery_sha), mode="ascii"),
        config_core_sha256=hashes.config_core_sha256(machine, resolved_domain, recipes, episode),
        delivery_contract_sha256=delivery_sha,
    )
    return ConfigReport(str(episode_file), config, ())


def _check_contract_files(episode: dict, domain: dict, episode_file: Path, skill_root: Path,
                          problems: list[str], sources: dict[str, str]) -> str | None:
    """Contract-bound files and the engine pin; returns the sha256 of DELIVERY-CONTRACT.json (or None)."""
    root = episode_file.parent.parent
    pinned = episode["engine_tree_sha256"]
    if pinned is not None and pinned != engine_tree_sha256(skill_root)["engine_tree_sha256"]:
        problems.append("episode.engine_tree_sha256 differs from the engine tree on disk "
                        "(run `jjv frozen verify --tree`; re-pin only after the episode is re-verified)")
    if episode.get("contract") is None:
        return None
    named = root / (episode.get("delivery_contract") or "DELIVERY-CONTRACT.json")
    delivery_sha = None
    if not named.is_file():
        problems.append(f"episode.contract is set but {named.name} does not exist: run `jjv config contract --write`")
    else:
        delivery_sha = sources["delivery_contract"] = sha256_file(named)
        problems.extend(contract_rules.check_delivery_file(named, episode, domain))
    review = (episode["files"] or {}).get("review_config")
    if review:
        path = (episode_file.parent / review).resolve()
        try:
            require_inside(path, root, "files.review_config")
        except Refused as error:
            problems.append(str(error))
        else:
            problems.extend(contract_rules.check_review_config(path, episode["contract"]) if path.is_file()
                            else [f"files.review_config not found: {path}"])
    return delivery_sha


def _check_episode(episode: dict, domain: dict, shots_doc: dict, boxes: dict | None, *,
                   skeleton: bool = False) -> list[str]:
    problems: list[str] = []
    docs = [("shots.json", shots_doc)] + ([("mouth-boxes.json", boxes)] if boxes is not None else [])
    for label, doc in docs:
        if doc["episode_id"] != episode["episode_id"]:
            problems.append(f"{label}: episode_id {doc['episode_id']!r} != {episode['episode_id']!r}")
    problems.extend(rules.check_timeline(episode, domain))
    if skeleton:  # no clip frames / wav bindings yet: the contract-vs-clips and shot rules need real evidence
        return problems
    problems.extend(contract_rules.check_contract(episode, domain, shots_doc["shots"]))
    problems.extend(rules.check_shots(episode, domain, shots_doc["shots"], boxes))
    return problems


def resolve_episode(ref: str, *, repo_root: Path = REPO_ROOT, skill_root: Path = SKILL_ROOT,
                    machine_path: Path | None = None, prerender: bool = False) -> ResolvedConfig:
    """Resolve ``ref`` to a config or raise :class:`ConfigViolation` (``prerender``: see :func:`build_config`)."""
    report = build_config(find_episode_file(ref, repo_root), skill_root=skill_root,
                          machine_path=machine_path, repo_root=repo_root, prerender=prerender)
    if report.config is None:
        raise ConfigViolation(report.violations)
    return report.config


def require_recipe(config: ResolvedConfig, family: str) -> dict:
    """The recipe a plan may use for ``family``, or ``Refused`` if none is qualified."""
    recipe = config.recipes.get(family)
    if recipe is None:
        raise Refused(
            f"domain {config.domain['domain_id']!r} has no qualified {family} recipe selected by "
            f"episode {config.episode['episode_id']!r}; a user-authorised GPU pilot must qualify one"
        )
    return copy.deepcopy(recipe)
