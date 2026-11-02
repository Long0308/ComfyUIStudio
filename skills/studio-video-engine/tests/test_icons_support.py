"""Shared fixtures of the icon registry / episode text tests (no tests in here).

A tiny fake episode in tmp_path: a vocabulary asset set with real RGBA PNGs (drawn with numpy, written
with zlib), a script with vocabulary cards (one compound card ``Warm and Cold``) and an episode.json.
Colours: warm orange disc, cold blue square, creamy white triangle, farm green disc.
"""

from __future__ import annotations

import copy
import json
import struct
import zlib
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from engine.core.io import sha256_file  # noqa: E402
from engine.editorial import episode_text as et  # noqa: E402
from engine.editorial import icons as reg  # noqa: E402
from engine.editorial import icons_build as build  # noqa: E402
from engine.seedvr2.seam_media import find_ffmpeg  # noqa: E402

try:
    FFMPEG: str | None = find_ffmpeg()
except Exception:  # noqa: BLE001 - a machine without ffmpeg skips the decoding tests
    FFMPEG = None
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not available")

REAL_EP = Path(Path(__file__).resolve().parents[4], r"production-local\JennieJoyKids-Story\04-milk-and-mom")
KIT_TEXT = reg.SKILL_ROOT / "remotion-kit" / "episodes" / "ep04" / "episode-text.json"
needs_real_ep = pytest.mark.skipif(not (REAL_EP / "technical" / "icons-registry-v001" / "icons.json").is_file()
                                   or not KIT_TEXT.is_file(), reason="real ep04 registry / kit text not on this machine")
EPISODE_ID = "09-test-episode"
WARM, COLD, CREAMY, FARM = (225, 120, 80), (80, 125, 225), (245, 245, 235), (60, 170, 70)


def recipe() -> dict:
    """The real icons recipe with a small size floor (the fixtures are 64 px)."""
    return {**reg.load_recipe()[0], "min_side_px": 32}


def shape(kind: str, side: int = 64):
    yy, xx = np.mgrid[:side, :side]
    c = side // 2
    if kind == "disc":
        return (yy - c) ** 2 + (xx - c) ** 2 <= (side // 3) ** 2
    if kind == "square":
        return (abs(yy - c) <= side // 4) & (abs(xx - c) <= side // 4)
    if kind == "triangle":
        return (yy >= side // 5) & (abs(xx - c) <= (yy - side // 5) // 2)
    raise ValueError(kind)


def write_png(path: Path, rgb: tuple, kind: str = "disc", side: int = 64, alpha: bool = True) -> Path:
    mask = shape(kind, side)
    rgba = np.zeros((side, side, 4), np.uint8)
    rgba[mask, :3] = rgb
    rgba[mask, 3] = 255
    data = rgba if alpha else rgba[:, :, :3]
    raw = b"".join(b"\x00" + row.tobytes() for row in data)

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    header = struct.pack(">IIBBBBB", side, side, 8, 6 if alpha else 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(reg.PNG_MAGIC + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


ICONS = {  # id -> (label, colour, shape)
    "creamy": ("Creamy", CREAMY, "triangle"), "warm": ("Warm", WARM, "disc"), "cold": ("Cold", COLD, "square"),
    "warm-cold": ("Warm and Cold", (150, 150, 150), "disc"), "farm": ("Farm", FARM, "disc")}


class World:
    """A fake episode: root, asset manifest, script, episode.json."""

    def __init__(self, tmp: Path, *, per_word: bool = True) -> None:
        self.root = tmp / "ep"
        self.assets = self.root / "assets" / "vocab-v1"
        self.script_path = self.root / "script" / "script.json"
        ids = [i for i in ICONS if per_word or i not in ("warm", "cold")]
        rows = []
        for icon_id in ids:
            label, colour, kind = ICONS[icon_id]
            png = write_png(self.assets / "png" / f"{icon_id}.png", colour, kind)
            rows.append({"id": icon_id, "term": label, "png_path": f"x/png/{icon_id}.png",
                         "png_sha256": sha256_file(png), "status": "CANDIDATE", "production_approved": False})
        self.manifest_path = self.assets / "manifest.json"
        self.manifest_path.write_text(json.dumps({"terms": rows}), encoding="utf-8")
        self.script = {
            "film_id": EPISODE_ID, "title": "Milk and Mom",
            "structure": {"intro": {"title_card": "Milk and Mom"}},
            "shots": [
                {"id": "S01_A", "speech_text": "Creamy milk!", "dialogue_vi": "Sữa béo ngậy!"},
                {"id": "S01_B", "speech_text": "Warm or cold?", "dialogue_vi": "x" * 70}],
            "vocabulary_cards": [
                {"term": "Creamy", "ipa": "/ˈkriːmi/", "vi": "Béo ngậy", "example_en": "Milk is creamy.",
                 "example_vi": "Sữa béo.", "icon": "creamy", "aliases": ["creamy"]},
                {"term": "Warm and Cold", "ipa": "/w/", "vi": "Ấm và lạnh", "example_en": "Warm and cold.",
                 "icon": "warm-cold", "aliases": ["warm or cold", "warm", "cold"]},
                {"term": "Farm", "ipa": "/f/", "vi": "Nông trại", "example_en": "A farm.", "icon": "farm",
                 "aliases": ["green farm", "farms"]}]}
        self.write_script()
        engine = self.root / "engine"
        engine.mkdir(parents=True, exist_ok=True)
        (engine / "episode.json").write_text(json.dumps({"episode_id": EPISODE_ID, "files": {}}), encoding="utf-8")
        self.recipe = recipe()
        self.recipe_sha = "r" * 64
        self.recipe_path = self.root / "icons-recipe-test.json"
        self.recipe_path.write_text(json.dumps(self.recipe), encoding="utf-8")

    def write_script(self) -> None:
        self.script_path.parent.mkdir(parents=True, exist_ok=True)
        self.script_path.write_text(json.dumps(self.script, ensure_ascii=False), encoding="utf-8")

    def registry(self, *, attributes: dict | None = None, allow_shared: tuple = ()) -> dict:
        return build.build_registry(
            episode_id=EPISODE_ID, root=self.root, manifest_path=self.manifest_path, script_path=self.script_path,
            recipe=self.recipe, recipe_sha=self.recipe_sha, ffmpeg=FFMPEG or "ffmpeg",
            attributes={"warm": "orange mug with steam", "cold": "blue mug with ice", **(attributes or {})},
            allow_shared=allow_shared)

    def validate(self, registry: dict, **kw) -> dict:
        from engine.editorial.icons_check import validate_registry
        return validate_registry(registry, root=self.root, recipe=self.recipe, ffmpeg=FFMPEG or "ffmpeg", **kw)

    def new_png(self, name: str, rgb: tuple, kind: str = "disc") -> Path:
        return write_png(self.root / "assets" / "swap" / name, rgb, kind)

    def text(self, registry: dict, **kw):
        trec = et.load_recipe()[0]
        copy_doc = {"intro": {"pill": "Cùng bé"}}
        return et.build_text(self.script, registry, trec, copy=kw.pop("copy", copy_doc), **kw)


def codes(report: dict, kind: str = "errors") -> set[str]:
    return {e["code"] for e in report[kind]}


def tampered(registry: dict, mutate) -> dict:
    """A deep copy changed by ``mutate`` and re-sealed (so only the content rule under test can fire)."""
    clone = copy.deepcopy(registry)
    mutate(clone)
    return reg.sealed(clone)
