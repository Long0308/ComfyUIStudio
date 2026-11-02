"""Voice recipe loading and the optional, defaulted config accessor.

The machine/domain/episode schemas are frozen until the planned config landing
(see ``CONFIG-PATCH.md`` next to this file), so the voice stage reads its settings
through ``optional_block``: every key is optional today, nothing here edits or
re-hashes the resolved config, and ``config_sha256`` stays what ``config validate``
reports.  No URL, profile id, pitch or language is a code constant: they come from
the machine config, the episode ``cast`` document or the recipe file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config.loader import SKILL_ROOT, ResolvedConfig
from ..config.schema import validate
from ..core.errors import Refused
from ..core.io import read_json, sha256_file

RECIPE_FAMILY = "voice"
RECIPE_SCHEMA_ID = "jjv/voice-recipe/v1"

VOICE_RECIPE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "recipe_id", "family", "domain", "engine", "language", "effect_preset",
                 "wav_bits", "editorial", "clipped_samples_max", "requires_ffmpeg_filters"],
    "properties": {
        "schema": {"const": RECIPE_SCHEMA_ID},
        "recipe_id": {"type": "string", "pattern": "^voice/[a-z0-9][a-z0-9._-]*$"},
        "family": {"const": RECIPE_FAMILY},
        "domain": {"type": "string", "minLength": 1},
        "note": {"type": "string"},
        # synth (default): editorial conversion + speaker transform + the single trim (``transform`` and ``trim``
        # are then required).  passthrough: the bound take IS the receipt WAV (bytes kept, sha256 unchanged);
        # ``transform`` and ``trim`` must be ABSENT.  The mode switch is checked in ``load_voice_recipe``.
        "mode": {"enum": ["synth", "passthrough"]},
        "engine": {"type": "string", "minLength": 1},
        "language": {"type": "string", "minLength": 1},
        "effect_preset": {"type": "string", "minLength": 1},
        "allowed_effect_presets": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "wav_bits": {"type": "string", "pattern": "^(16|24|32)$"},
        "editorial": {
            "type": "object", "additionalProperties": False,
            "required": ["sample_rate", "channels", "sample_width_bytes"],
            "properties": {
                "sample_rate": {"type": "integer", "minimum": 8000},
                "channels": {"type": "integer", "minimum": 1, "maximum": 2},
                "sample_width_bytes": {"const": 2},
            },
        },
        "transform": {
            "type": "object", "additionalProperties": False,
            "required": ["method", "formant", "pitchq", "channels"],
            "properties": {
                "method": {"const": "rubberband"},
                "formant": {"enum": ["preserved", "shifted"]},
                "pitchq": {"enum": ["quality", "speed", "consistency"]},
                "channels": {"enum": ["together", "apart"]},
            },
        },
        "trim": {
            "type": "object", "additionalProperties": False,
            "required": ["threshold_dbfs", "window_ms", "pre_roll_s", "post_roll_s", "onset"],
            "properties": {
                "threshold_dbfs": {"type": "number", "maximum": 0},
                "window_ms": {"type": "integer", "minimum": 1, "maximum": 100},
                "pre_roll_s": {"type": "number", "minimum": 0, "maximum": 1},
                "post_roll_s": {"type": "number", "minimum": 0, "maximum": 1},
                "onset": {
                    "type": "object", "additionalProperties": False,
                    "required": ["merge_gap_s", "min_run_s", "isolated_gap_s"],
                    "properties": {
                        "merge_gap_s": {"type": "number", "minimum": 0, "maximum": 1},
                        "min_run_s": {"type": "number", "minimum": 0, "maximum": 2},
                        "isolated_gap_s": {"type": "number", "minimum": 0, "maximum": 5},
                        "quiet_burst_db": {"type": "number", "minimum": 3, "maximum": 60},
                    },
                },
            },
        },
        "clipped_samples_max": {"type": "integer", "minimum": 0},
        "requires_ffmpeg_filters": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
}


@dataclass(frozen=True)
class VoiceRecipe:
    recipe_id: str
    path: Path
    sha256: str
    data: dict

    @property
    def passthrough(self) -> bool:
        return self.data.get("mode", "synth") == "passthrough"


@dataclass(frozen=True)
class VoiceSettings:
    """Everything the voice verbs need; every field traces to a config file or a CLI flag."""

    recipe: VoiceRecipe
    gpu_lock_path: Path | None
    comfy_url: str | None
    voicestudio_url: str | None
    require_listen_approval: bool
    lock_timeout_seconds: float = 30.0
    http_timeout_seconds: float = 300.0
    sources: dict | None = None  # where each value came from (for receipts)


def optional_block(document: dict, key: str) -> dict:
    """An optional object-valued key; absent or non-object reads as ``{}`` (never raises)."""
    value = document.get(key) if isinstance(document, dict) else None
    return value if isinstance(value, dict) else {}


def _recipe_files(skill_root: Path) -> list[Path]:
    return sorted((skill_root / "recipes" / RECIPE_FAMILY).glob("*.json"))


def load_voice_recipe(recipe_id: str, *, skill_root: Path = SKILL_ROOT) -> VoiceRecipe:
    """Read and schema-check ``recipes/voice/<id>.json``; a bad recipe is Refused."""
    if "/" not in recipe_id or recipe_id.split("/", 1)[0] != RECIPE_FAMILY:
        raise Refused(f"voice recipe id must be 'voice/<name>', got {recipe_id!r}")
    path = skill_root / "recipes" / f"{recipe_id}.json"
    if not path.is_file():
        raise Refused(f"voice recipe not found: {path}")
    data = read_json(path)
    errors = validate(data, VOICE_RECIPE_SCHEMA, label=f"recipe[{recipe_id}]")
    if errors:
        raise Refused("; ".join(errors))
    if data["recipe_id"] != recipe_id:
        raise Refused(f"recipe file {path.name} declares recipe_id {data['recipe_id']!r}, expected {recipe_id!r}")
    _check_mode(data, recipe_id)
    return VoiceRecipe(recipe_id=recipe_id, path=path, sha256=sha256_file(path), data=data)


def _check_mode(data: dict, recipe_id: str) -> None:
    """synth needs ``transform`` + ``trim``; passthrough must carry neither (a passthrough that names a trim is a lie)."""
    present = [key for key in ("transform", "trim") if key in data]
    if data.get("mode", "synth") == "passthrough":
        if present:
            raise Refused(f"recipe[{recipe_id}]: mode passthrough must not declare {present}")
    else:
        missing = [key for key in ("transform", "trim") if key not in data]
        if missing:
            raise Refused(f"recipe[{recipe_id}]: mode synth requires {missing}")


def select_recipe_id(config: ResolvedConfig, explicit: str | None, *,
                     skill_root: Path = SKILL_ROOT) -> tuple[str, str]:
    """Recipe id and where it came from: ``--recipe`` > ``episode.voice.recipe`` > the single
    recipe file declared for the episode's domain.  Several candidates or none: Refused."""
    if explicit:
        return explicit, "cli"
    episode_voice = optional_block(config.episode, "voice")
    declared = episode_voice.get("recipe")
    if isinstance(declared, str) and declared:
        return declared, "episode.voice.recipe"
    domain_id = config.domain["domain_id"]
    candidates = []
    for path in _recipe_files(skill_root):
        data = read_json(path)
        if isinstance(data, dict) and data.get("domain") == domain_id and data.get("family") == RECIPE_FAMILY:
            candidates.append(str(data.get("recipe_id")))
    if len(candidates) == 1:
        return candidates[0], "unique recipe for the domain"
    raise Refused(
        f"no voice recipe selected for domain {domain_id!r}: pass --recipe or set episode.voice.recipe "
        f"(candidates: {candidates})")


def _check_domain_allows(config: ResolvedConfig, recipe: VoiceRecipe) -> None:
    if recipe.data["domain"] != config.domain["domain_id"]:
        raise Refused(f"recipe {recipe.recipe_id!r} belongs to domain {recipe.data['domain']!r}, "
                      f"episode domain is {config.domain['domain_id']!r}")
    allowed = optional_block(config.domain, "voice").get("allowed_recipes")
    if isinstance(allowed, list) and recipe.recipe_id not in allowed:
        raise Refused(f"domain {config.domain['domain_id']!r} does not list voice recipe {recipe.recipe_id!r}")


def voice_settings(config: ResolvedConfig, *, recipe_id: str | None = None,
                   voicestudio_url: str | None = None, lock_timeout_seconds: float | None = None,
                   skill_root: Path = SKILL_ROOT) -> VoiceSettings:
    """Build the settings from the resolved config plus the optional (not yet schema'd) keys."""
    chosen, origin = select_recipe_id(config, recipe_id, skill_root=skill_root)
    recipe = load_voice_recipe(chosen, skill_root=skill_root)
    _check_domain_allows(config, recipe)
    machine_vs = optional_block(config.machine, "voicestudio")
    url = voicestudio_url or machine_vs.get("url")
    url_origin = "cli" if voicestudio_url else ("machine.voicestudio.url" if url else "unset")
    comfy_url = (config.machine.get("comfy") or {}).get("url")
    lock = str(config.machine.get("gpu_lock_path") or "").strip()
    domain_voice = optional_block(config.domain, "voice")
    return VoiceSettings(
        recipe=recipe,
        gpu_lock_path=Path(lock) if lock else None,
        comfy_url=str(comfy_url).rstrip("/") if comfy_url else None,
        voicestudio_url=str(url).rstrip("/") if url else None,
        require_listen_approval=bool(domain_voice.get("require_listen_approval", False)),
        lock_timeout_seconds=float(lock_timeout_seconds if lock_timeout_seconds is not None else 30.0),
        sources={"recipe": origin, "voicestudio_url": url_origin, "gpu_lock_path": "machine.gpu_lock_path",
                 "comfy_url": "machine.comfy.url"},
    )
