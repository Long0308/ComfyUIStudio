"""Script-driven music brief: tempo, key and instruments derived from the script and the timeline.

No hand-written prompt: the dialogue rows of the review config give a speech density (words per second) per
section, which maps to an energy label (``calm`` / ``gentle`` / ``lively``); the overall energy picks the
tempo, the episode id picks a major key from the recipe list (deterministic), and the shot texts pick an
instrument palette by keyword.  Every table lives in the recipe (``derivation``).  The result is only the
LOWEST layer of the brief: ``episode.audio.music.brief``, ``--brief`` and flags override it.
"""

from __future__ import annotations

import hashlib
import re

from ..core.errors import Refused

WORD = re.compile(r"[\w']+")


def row_seconds(row: dict, fps: int) -> float:
    spoken = row.get("speech_end_in_window_s")
    return float(spoken) if isinstance(spoken, (int, float)) and spoken > 0 else int(row["duration_frames"]) / fps


def energy_label(wps: float, cfg: dict) -> str:
    if wps <= cfg["calm_max_wps"]:
        return "calm"
    return "lively" if wps >= cfg["lively_min_wps"] else "gentle"


def section_energies(review_config: dict, sections: list[dict], fps: int, cfg: dict) -> list[dict]:
    rows = [r for r in review_config.get("dialogue", []) if isinstance(r, dict) and r.get("speech_text") and "duration_frames" in r]
    out = []
    for section in sections:
        inside = [r for r in rows if section["start_frame"] <= int(r["start_frame"]) < section["end_frame_exclusive"]]
        words = sum(len(WORD.findall(r["speech_text"])) for r in inside)
        seconds = sum(row_seconds(r, fps) for r in inside)
        if seconds > 0:
            wps = words / seconds
            out.append({"section": section["name"], "words_per_second": round(wps, 3), "energy": energy_label(wps, cfg),
                        "basis": f"{len(inside)} dialogue lines"})
        else:
            out.append({"section": section["name"], "words_per_second": None,
                        "energy": cfg["default_by_section"].get(section["name"], cfg["default_by_section"]["*"]),
                        "basis": "no dialogue: recipe default for this section"})
    return out


def pick_palette(derivation: dict, texts: list[str], energy: str) -> tuple[dict, dict]:
    palettes = derivation["instrument_palettes"]
    blob = " ".join(texts).lower()
    scored = [(sum(len(re.findall(r"\b" + k + r"\b", blob)) for k in p.get("keywords", [])), p) for p in palettes]
    best = max(scored, key=lambda s: s[0])
    if best[0] > 0:
        return best[1], {"palette": best[1]["id"], "by": "keyword hits", "hits": best[0]}
    for palette in palettes:
        if energy in palette.get("energy", []):
            return palette, {"palette": palette["id"], "by": f"energy {energy}"}
    default = next((p for p in palettes if p["id"] == derivation["default_palette"]), None)
    if default is None:
        raise Refused(f"derivation.default_palette {derivation['default_palette']!r} is not a palette id")
    return default, {"palette": default["id"], "by": "recipe default"}


def derive(recipe: dict, review_config: dict, sections: list[dict], fps: int, episode_id: str,
           texts: list[str]) -> tuple[dict, dict]:
    """``(brief, evidence)``: bpm, key, instruments + the numbers they came from."""
    spec = recipe["derivation"]
    energies = section_energies(review_config, sections, fps, spec["energy"])
    rows = [r for r in review_config.get("dialogue", []) if isinstance(r, dict) and r.get("speech_text") and "duration_frames" in r]
    if not rows:
        raise Refused("review config has no dialogue[].speech_text: cannot derive a brief from the script")
    words = sum(len(WORD.findall(r["speech_text"])) for r in rows)
    overall_wps = words / sum(row_seconds(r, fps) for r in rows)
    overall = energy_label(overall_wps, spec["energy"])
    tempo = spec["tempo"]
    bpm = min(tempo["max"], max(tempo["min"], tempo["by_energy"][overall]))
    keys = spec["keys"]
    key_index = int(hashlib.sha256(episode_id.encode("utf-8")).hexdigest()[:8], 16) % len(keys)
    palette, palette_why = pick_palette(spec, texts, overall)
    evidence = {"overall_words_per_second": round(overall_wps, 3), "overall_energy": overall, "section_energy": energies,
                "bpm_rule": f"tempo.by_energy[{overall}] clamped to [{tempo['min']}, {tempo['max']}]",
                "key_rule": f"keys[sha256(episode_id) mod {len(keys)}] = index {key_index}", "instruments": palette_why}
    return {"bpm": bpm, "key": keys[key_index], "instruments": palette["instruments"]}, evidence
