"""Where the brand voice sits in a film: ``episode.audio.brand_voice`` is ``intro`` | ``film`` | ``none`` (default ``intro``).

* ``intro``: the voice is inside the channel's brand intro, so the FILM mix has NO brand voice layer;
* ``film``: the film mix plays the voice alone first (``--brand-voice``); without the flag the library's brand-voice
  registry pick is used (``<library>/brand-voice/REGISTRY.json``: ``file`` + ``sha256``, re-verified here);
* ``none``: no brand voice anywhere in the film mix.

``intro`` and ``none`` REFUSE an explicit ``--brand-voice`` (two instructions that contradict each other are an error, not a
silent override).  The key is read through ``optional_block`` until the episode schema carries it (CONFIG-PATCH).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config.loader import ResolvedConfig
from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from .recipe import optional_block

MODES = ("intro", "film", "none")
DEFAULT_MODE = "intro"
BRAND_DIR = "brand-voice"
REGISTRY_FILE = "REGISTRY.json"


@dataclass(frozen=True)
class BrandChoice:
    mode: str
    path: str | None
    sha256: str | None
    source: str


def episode_mode(config: ResolvedConfig) -> str:
    value = optional_block(config.episode, "audio").get("brand_voice", DEFAULT_MODE)
    if value not in MODES:
        raise Refused(f"episode.audio.brand_voice must be one of {MODES}, got {value!r}")
    return value


def registry_pick(library: Path) -> tuple[Path, str, str]:
    """``(wav path, sha256, pick id)`` of the library's brand voice; the file must still hold the registered bytes."""
    folder = Path(library) / BRAND_DIR
    registry = folder / REGISTRY_FILE
    if not registry.is_file():
        raise Refused(f"brand voice registry not found: {registry}")
    document = read_json(registry)
    name, sha = document.get("file"), document.get("sha256")
    if not isinstance(name, str) or Path(name).name != name or not isinstance(sha, str):
        raise Refused(f"{registry}: needs a plain 'file' name and a 'sha256'")
    wav = folder / name
    if not wav.is_file() or sha256_file(wav) != sha:
        raise Refused(f"brand voice {wav} is missing or differs from the registered sha256 {sha[:12]}")
    return wav, sha, str(document.get("pick", name))


def resolve(config: ResolvedConfig, *, cli_wav: str | None, cli_sha256: str | None, library: Path | None) -> BrandChoice:
    mode = episode_mode(config)
    if mode in ("intro", "none"):
        if cli_wav:
            reason = ("the voice is inside the brand intro" if mode == "intro" else "the film has no brand voice")
            raise Refused(f"--brand-voice given but episode.audio.brand_voice is {mode!r} ({reason}); set it to 'film' "
                          "or drop the flag")
        return BrandChoice(mode, None, None, f"episode.audio.brand_voice={mode}")
    if cli_wav:
        return BrandChoice(mode, cli_wav, cli_sha256, "--brand-voice")
    if library is None:
        raise Refused("episode.audio.brand_voice is 'film' but no --brand-voice and no library to take the registry pick from")
    wav, sha, pick = registry_pick(library)
    return BrandChoice(mode, str(wav), sha, f"library registry pick {pick}")
