"""Icon registry (T-E44): one icon per spoken vocabulary word, as DATA.

The registry is the only place an episode names its icon images.  ``jjv editorial build-config`` and the
Remotion kit read icons from it, so changing an icon (or its status) is a registry edit followed by a
composite-only re-render, never a hand edit and never a shot re-render (the icon brief rules, G-ICON-ART, live in the
episode-creation skill of the domain).

Document ``jjv/icon-registry/v1`` (``icons.json``; every version is also kept in ``versions/``):

* ``icons``  ``{id: {label, kind, file, png, sha256, bytes, size, palette, attribute, pair, status, approved, shared}}``
  ``png`` is episode-root relative; ``palette`` = mean RGB of the opaque pixels, hue, saturation, Lab.
* ``terms``  ``{spoken term: {icon, aliases, card}}``: exactly one icon per spoken word.
* ``cards``  ``{card term: {icon, spoken, phrases}}``: the outro card's own icon and the spoken words it teaches.
* ``version`` / ``previous`` / ``history``: a change appends a version, the old file stays.

No timestamps: a rebuild from the same inputs is byte-identical.  Colour maths is shared with QA gate Q2.
"""

from __future__ import annotations

import re
import struct
import subprocess
from pathlib import Path
from typing import Any

from ..config.loader import SKILL_ROOT
from ..core.errors import Refused, Uncertain
from ..core.io import canonical_sha256, pretty_json, read_json, sha256_file, write_atomic, write_once
from ..qa.gates.q2_icons import delta_e, hue_sat, rgb_to_lab, stem
from ..qa.review_media import numpy_module
from ..seedvr2.seam_media import ffmpeg_flags

SCHEMA = "jjv/icon-registry/v1"
RECIPE_SCHEMA = "jjv/icons-recipe/v1"
DEFAULT_RECIPE = SKILL_ROOT / "recipes" / "editorial" / "icons-v001.json"
REGISTRY_NAME, VERSIONS_DIR, JSON_MODE = "icons.json", "versions", "utf8"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def load_recipe(path: Path | None = None) -> tuple[dict, str]:
    """(recipe, sha256 of the file); a missing or foreign document is an unreadable input."""
    target = Path(path) if path else DEFAULT_RECIPE
    recipe = read_json(target)
    if not isinstance(recipe, dict) or recipe.get("schema") != RECIPE_SCHEMA:
        raise Uncertain(f"{target.name}: not a {RECIPE_SCHEMA} document")
    return recipe, sha256_file(target)


# ---- names ---------------------------------------------------------------------------------------------
def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def norm(text: Any) -> str:
    """A spoken term compared the way QA Q2 does: letters only, trailing plural s dropped per token."""
    return " ".join(stem(t) for t in re.split(r"[^A-Za-z]+", str(text or "")) if t)


def split_compound(term: str, separators: list[str]) -> list[str]:
    """``Warm and Cold`` -> [Warm, Cold]; a term without a separator stays whole."""
    pattern = "|".join(re.escape(s) for s in separators)
    return [p.strip() for p in re.split(pattern, term, flags=re.I) if p.strip()]


def episode_relative(path: Path, root: Path) -> str:
    """Episode-root relative POSIX path; an icon outside the episode is refused (the kit binds episode paths)."""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        raise Refused(f"{path} is outside the episode root {root}: put the image under the episode") from None


# ---- image facts ---------------------------------------------------------------------------------------
def png_info(path: Path) -> dict:
    """Width, height, bit depth and colour type from the IHDR chunk (no decoding)."""
    try:
        head = Path(path).open("rb").read(33)
    except OSError as error:
        raise Uncertain(f"cannot read {path}: {error}") from error
    if head[:8] != PNG_MAGIC or head[12:16] != b"IHDR":
        raise Refused(f"{Path(path).name} is not a PNG file")
    width, height, depth, colour = struct.unpack(">IIBB", head[16:26])
    return {"width": width, "height": height, "bit_depth": depth, "colour_type": colour,
            "has_alpha": colour in (4, 6)}


def decode_rgba(path: Path, ffmpeg: str, side: int) -> Any:
    """``side x side x 4`` uint8, area-scaled by ffmpeg (the way QA Q2 reads an icon)."""
    np = numpy_module()
    cmd = [ffmpeg, "-v", "error", "-i", str(path), "-vf", f"scale={side}:{side}:flags=area",
           "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    try:
        result = subprocess.run(cmd, capture_output=True, creationflags=ffmpeg_flags())
    except OSError as error:
        raise Uncertain(f"cannot run ffmpeg: {error}") from error
    if result.returncode != 0 or len(result.stdout) != side * side * 4:
        raise Uncertain(f"cannot decode icon {Path(path).name}: {result.stderr.decode(errors='replace')[:160]}")
    return np.frombuffer(result.stdout, np.uint8).reshape(side, side, 4)


def measure(path: Path, recipe: dict, ffmpeg: str) -> dict:
    """Facts of one icon file: size, alpha, mean opaque colour (palette)."""
    np = numpy_module()
    info = png_info(path)
    pixels = decode_rgba(path, ffmpeg, recipe["decode_side"]).reshape(-1, 4)
    opaque = pixels[pixels[:, 3] >= recipe["alpha_min"]]
    rgb = [float(v) for v in (opaque if len(opaque) else pixels)[:, :3].mean(axis=0)]
    hue, sat = hue_sat(rgb)
    return {"size": [info["width"], info["height"]], "has_alpha": info["has_alpha"],
            "palette": {"rgb": [round(v, 1) for v in rgb], "hue": round(hue, 1), "saturation": round(sat, 3),
                        "lab": [round(float(v), 1) for v in rgb_to_lab(np.asarray(rgb))]},
            "opaque_fraction": round(len(opaque) / len(pixels), 4)}


def silhouette(path: Path, recipe: dict, ffmpeg: str) -> Any:
    """Boolean alpha mask at ``silhouette_side`` (the shape of the icon)."""
    return decode_rgba(path, ffmpeg, recipe["silhouette_side"])[:, :, 3] >= recipe["alpha_min"]


def iou(a: Any, b: Any) -> float:
    union = int((a | b).sum())
    return float((a & b).sum()) / union if union else 1.0


# ---- registry file -------------------------------------------------------------------------------------
def registry_sha256(registry: dict) -> str:
    """Canonical sha256 of the registry without its own ``sha256`` field (a hand edit is detectable)."""
    return canonical_sha256({k: v for k, v in registry.items() if k != "sha256"}, mode="utf8")


def sealed(registry: dict) -> dict:
    body = {k: v for k, v in registry.items() if k != "sha256"}
    return {**body, "sha256": registry_sha256(body)}


def load_registry(path: Path) -> dict:
    """The registry at ``path``; a foreign schema or a hand-edited file (sha256 mismatch) is Refused."""
    registry = read_json(Path(path))
    if not isinstance(registry, dict) or registry.get("schema") != SCHEMA:
        raise Refused(f"{path}: not a {SCHEMA} document")
    if registry.get("sha256") != registry_sha256(registry):
        raise Refused(f"{path}: sha256 does not match the content (hand-edited?); change it with `jjv icons set`")
    return registry


def write_registry(out_dir: Path, registry: dict, *, dry_run: bool = False) -> dict:
    """``versions/icons-vNNN.json`` (write-once) and ``icons.json`` (the current version, replaced atomically)."""
    payload = pretty_json(registry, mode=JSON_MODE)
    version_file = Path(out_dir) / VERSIONS_DIR / f"icons-v{registry['version']:03d}.json"
    current = Path(out_dir) / REGISTRY_NAME
    if version_file.exists() and version_file.read_bytes() != payload:
        raise Refused(f"refusing to overwrite {version_file}: version {registry['version']} already exists")
    if current.is_file() and registry["version"] > 1:
        have = read_json(current).get("version")
        if have != registry["previous"]["version"]:
            raise Refused(f"{current} is at version {have}, the new version {registry['version']} was derived from "
                          f"{registry['previous']['version']}")
    if current.is_file() and registry["version"] == 1 and current.read_bytes() != payload:
        raise Refused(f"refusing to overwrite {current}: it differs from the rebuilt registry (use `jjv icons set`)")
    summary = {"icons.json": {"path": str(current), "sha256": registry["sha256"]},
               "version_file": {"path": str(version_file)}, "written": not dry_run}
    if not dry_run:
        write_once(version_file, payload)
        write_atomic(current, payload)
    return summary


# ---- consumer API (build-config and the kit read icons through these) ----------------------------------
def term_lookup(registry: dict) -> dict[str, str]:
    """normalised spoken word / alias -> term key."""
    table: dict[str, str] = {}
    for key, row in registry["terms"].items():
        for name in (key, *row.get("aliases", [])):
            table[norm(name)] = key
    return table


def icon_for_word(registry: dict, word: str) -> dict | None:
    """The one icon entry for a spoken word (term or alias); None when the word is not a vocabulary word."""
    key = term_lookup(registry).get(norm(word))
    return None if key is None else registry["icons"][registry["terms"][key]["icon"]]


def icon_for_card(registry: dict, card_term: str) -> dict:
    row = registry["cards"].get(card_term)
    if row is None:
        raise Refused(f"icon registry has no card {card_term!r}")
    return registry["icons"][row["icon"]]


def icon_ref(entry: dict) -> dict:
    """``{path, sha256}``: how the kit's episode text and the build-config bind an icon."""
    return {"path": entry["png"], "sha256": entry["sha256"]}
