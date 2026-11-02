"""Preflight audio contract, from RECEIPTS only (no WAV decoding beyond a hash).

* music: the music bed's vocal-free gate must be ``PASS`` (``music-finalize.json`` ``stem.vocal_gate.status``, or the
  ``music.vocal_gate`` of a ``jjv/audio-mix/v1`` receipt); ``NOT_RUN``, ``FAIL``, ``ERROR`` and an explicit WAV that
  bypassed the gate all FAIL (``jjv audio mix`` refuses the same), unless ``allow_ungated`` is named;
* SFX / ambience are OFF unless the film opted in (``--with-sfx`` or ``episode.audio.sfx.enabled``): a mix receipt
  with SFX enabled and no opt-in FAILs;
* the brand voice, when the mix has one, ends ``brand_voice_guard_s`` before the first speech (first dialogue word).

A hand-built config's own ``mix`` block is NOT interpreted (it is free-form, and the first hand-built episode's carries SFX on purpose); it
is reported as a warning.  No receipt at all is ``SKIPPED`` with a warning, or UNCERTAIN under ``require``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file
from ..core.paths import resolve_data_path
from .gates import FAIL, PASS, UNCERTAIN, roll_up

MIX_SCHEMA = "jjv/audio-mix/v1"


def _doc(path: Path, label: str) -> dict:
    document = read_json(Path(path))
    if not isinstance(document, dict):
        raise Refused(f"{label} {Path(path).name}: not a JSON object")
    return document


def music_receipt(path: Path, required: str, allow_ungated: bool) -> tuple[list[str], list[str], dict]:
    document = _doc(path, "music receipt")
    stem = document.get("stem")
    if not isinstance(stem, dict) or not stem.get("path") or not stem.get("sha256"):
        raise Refused(f"{Path(path).name}: no stem path/sha256 (is it a music-finalize.json?)")
    status = str((stem.get("vocal_gate") or {}).get("status", "NOT_RUN"))
    fails, notes = [], []
    if status != required:
        (notes if allow_ungated else fails).append(f"music bed vocal-free gate is {status}, not {required} (receipt {Path(path).name})")
    target = resolve_data_path(Path(path).parent / stem["path"])   # an absolute stem path under a retired root is remapped
    if not target.is_file():
        raise Uncertain(f"music stem not found: {target}")
    if sha256_file(target) != stem["sha256"]:
        fails.append(f"music stem {target.name} does not hash to the receipt's sha256")
    return fails, notes, {"vocal_gate": status, "stem": target.name}


def mix_receipt(path: Path, required: str, allow_ungated: bool, with_sfx: bool, speech_start_s: float | None,
                guard_s: float) -> tuple[list[str], list[str], dict]:
    document = _doc(path, "mix receipt")
    if document.get("schema") != MIX_SCHEMA:
        raise Refused(f"{Path(path).name}: not a {MIX_SCHEMA} document")
    fails, notes = [], []
    music = document.get("music") or {}
    gate = str(music.get("vocal_gate", "NOT_RUN"))
    if gate != required:
        (notes if allow_ungated else fails).append(
            f"mix receipt: music vocal-free gate is {gate!r} (source {music.get('source')!r}), not {required}")
    if document.get("verdict") not in (None, "PASS"):
        fails.append(f"mix receipt verdict is {document.get('verdict')!r}, not PASS")
    sfx = (document.get("sfx") or {}).get("enabled") or ((document.get("inputs") or {}).get("sfx") or {}).get("enabled")
    if sfx and not with_sfx:
        fails.append("mix receipt has SFX/ambience enabled but the film did not opt in (--with-sfx / episode.audio.sfx.enabled)")
    brand = document.get("brand_voice")
    info: dict[str, Any] = {"music_vocal_gate": gate, "sfx_enabled": bool(sfx), "brand_voice": None}
    if isinstance(brand, dict):
        end = brand.get("end_s")
        info["brand_voice"] = {"end_s": end, "first_speech_s": speech_start_s, "guard_s": guard_s}
        if not isinstance(end, (int, float)) or speech_start_s is None:
            raise Uncertain("brand voice end or the first speech time is unknown: cannot check the guard")
        if end > speech_start_s - guard_s:
            fails.append(f"brand voice ends at {end:.2f} s, inside the {guard_s} s guard before the first speech "
                         f"({speech_start_s:.2f} s)")
    return fails, notes, info


def run(config: dict, pre: dict, *, music_path: Path | None, mix_path: Path | None, with_sfx: bool,
        allow_ungated: bool, require: bool, speech_start_s: float | None) -> dict:
    block = pre["audio"]
    fails: list[str] = []
    warnings: list[str] = []
    detail: dict[str, Any] = {}
    if music_path is not None:
        f, n, detail["music_receipt"] = music_receipt(music_path, block["music_vocal_gate_required"], allow_ungated)
        fails += f
        warnings += n
    if mix_path is not None:
        f, n, detail["mix_receipt"] = mix_receipt(mix_path, block["music_vocal_gate_required"], allow_ungated, with_sfx,
                                                  speech_start_s, block["brand_voice_guard_s"])
        fails += f
        warnings += n
    if isinstance(config.get("mix"), dict):
        warnings.append("the config's own `mix` block is hand-built and free-form: it is not machine-checked here "
                        "(pass --mix-receipt / --music-receipt)")
    if music_path is None and mix_path is None:
        status = UNCERTAIN if require else "SKIPPED"
        warnings.append("no music or mix receipt given: the audio contract was NOT checked")
    else:
        status = roll_up([FAIL] * bool(fails) + [PASS])
    return {"gate": "AUDIO", "status": status, "failures": fails, "warnings": warnings, **detail}
