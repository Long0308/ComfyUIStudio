"""Library first: score the gated beds of the shared library against an episode's music brief and pick one.

Inputs: the brief (bpm, key, instruments, energy) the script produced (``engine.audio.brief`` + ``music.resolve_brief``),
the film length and the registry (``engine.audio.library``).  Every number (weights, thresholds, the instrument
vocabulary) is data of the ``audio/music-pick-v001`` recipe.

A bed is ELIGIBLE only when all of these hold (the reason of every refusal is recorded per bed):
status approved, vocal-free numbers recomputed from the registry (RMS-relative <= limit AND no 1 s window over the
window limit), same domain, the file exists with the registered bytes, 48 kHz stereo PCM16 and the registered length,
length >= the film + ``target_extra_s`` (the length AFTER loop-extension: registry beds are finished beds), and not used
by the previous episode (the highest episode number below the current one that any bed lists in ``used_in``).
An eligible bed FITS when its instrument match and its content score reach the recipe thresholds, or when the SAME episode
already used it (``fit.own_use_is_fit``: a re-run keeps the bed the film shipped with and never generates a second one; the
content score and ``fits_by_content`` stay in the table, so what a fresh episode would get is visible).  The best fitting bed
is picked (one this episode already used first: a re-run is stable), otherwise the decision is ``generate``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config.loader import SKILL_ROOT, ResolvedConfig
from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from . import library
from .recipe import AudioRecipe

PICK_FAMILY = "audio-music-pick"
DEFAULT_PICK_RECIPE = "audio/music-pick-v001"
REQUIRED_SECTIONS = ("library", "fit", "instrument_vocabulary", "energy_by_instrument", "generation", "vocal_step")
BPM = re.compile(r"(\d{2,3})\s*BPM", re.IGNORECASE)
KEY = re.compile(r"\b([A-G][#b]?)\s*(?:major|trưởng)", re.IGNORECASE)
EPISODE_NUMBER = re.compile(r"^(\d+)-")
ENERGY_ORDER = ("calm", "gentle", "lively")


def check_pick_allowed(domain: dict, recipe_id: str) -> None:
    """The picker id must be in ``domain.audio.allowed_recipes`` (exact match).  Missing block/key = disabled, a
    malformed list is Refused, and the empty list refuses everything (never "allow all")."""
    domain_id = domain.get("domain_id")
    block = domain.get("audio")
    if block is None or (isinstance(block, dict) and "allowed_recipes" not in block):
        raise Refused(f"domain {domain_id!r} is missing audio.allowed_recipes; music pick is disabled")
    allowed = block.get("allowed_recipes") if isinstance(block, dict) else None
    if (not isinstance(allowed, list) or len(set(map(str, allowed))) != len(allowed)
            or not all(isinstance(i, str) and i.startswith("audio/") for i in allowed)):
        raise Refused(f"domain {domain_id!r} has invalid audio.allowed_recipes; expected unique audio recipe IDs")
    if recipe_id not in allowed:
        raise Refused(f"domain {domain_id!r} does not list music-pick recipe {recipe_id!r} in audio.allowed_recipes")


def load_pick_recipe(config: ResolvedConfig, recipe_id: str | None = None, *, skill_root: Path = SKILL_ROOT) -> AudioRecipe:
    recipe_id = recipe_id or DEFAULT_PICK_RECIPE
    if not recipe_id.startswith("audio/") or ".." in recipe_id:
        raise Refused(f"pick recipe id must be audio/<name>, got {recipe_id!r}")
    check_pick_allowed(config.domain, recipe_id)
    path = Path(skill_root) / "recipes" / f"{recipe_id}.json"
    if not path.is_file():
        raise Refused(f"music pick recipe not found: {path}")
    data = read_json(path)
    if not isinstance(data, dict) or data.get("family") != PICK_FAMILY or data.get("recipe_id") != recipe_id:
        raise Refused(f"{path}: not a {PICK_FAMILY} recipe named {recipe_id!r}")
    missing = [key for key in REQUIRED_SECTIONS if key not in data]
    if missing:
        raise Refused(f"{path}: lacks {missing}")
    if data.get("domain") != config.domain["domain_id"]:
        raise Refused(f"pick recipe {recipe_id!r} belongs to domain {data.get('domain')!r}, "
                      f"episode domain is {config.domain['domain_id']!r}")
    weights = data["fit"]["weights"]
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise Refused(f"{path}: fit.weights must sum to 1.0, got {sum(weights.values())}")
    return AudioRecipe(recipe_id, PICK_FAMILY, path, sha256_file(path), data)


# ---- attributes of a bed (registry rows carry a prose description; new rows carry a ``brief``) -----------------
def instruments_in(text: str, vocabulary: dict[str, list[str]]) -> list[str]:
    low = text.lower()
    return sorted(name for name, aliases in vocabulary.items() if any(re.search(r"\b" + re.escape(a), low) for a in aliases))


def infer_energy(instruments: list[str], by_instrument: dict[str, list[str]]) -> str | None:
    votes = {label: sum(1 for i in instruments if i in names) for label, names in by_instrument.items()}
    best = max(votes.values(), default=0)
    leaders = [label for label, count in votes.items() if count == best]
    return leaders[0] if best > 0 and len(leaders) == 1 else None


def bed_attributes(row: dict, data: dict) -> dict:
    """``{bpm, key, instruments, energy, basis}``: the row's own ``brief`` first, else parsed from its description/take."""
    brief = row.get("brief") if isinstance(row.get("brief"), dict) else {}
    text = " ".join(str(row.get(k, "")) for k in ("description_vi", "take", "description"))
    vocabulary = data["instrument_vocabulary"]
    bpm = brief.get("bpm")
    if bpm is None and (found := BPM.search(text)):
        bpm = float(found.group(1))
    key = brief.get("key")
    if key is None and (found := KEY.search(text)):
        key = f"{found.group(1).upper()} major"
    instruments = instruments_in(str(brief.get("instruments", "")) + " " + text, vocabulary)
    energy = brief.get("energy") or infer_energy(instruments, data["energy_by_instrument"])
    basis = "registry brief" if brief else "parsed from description/take"
    return {"bpm": None if bpm is None else float(bpm), "key": key, "instruments": instruments, "energy": energy, "basis": basis}


def wanted_attributes(brief: dict, evidence: dict | None, data: dict) -> dict:
    instruments = instruments_in(str(brief["instruments"]), data["instrument_vocabulary"])
    energy = (evidence or {}).get("overall_energy") or infer_energy(instruments, data["energy_by_instrument"])
    return {"bpm": float(brief["bpm"]), "key": str(brief["key"]), "instruments": instruments, "energy": energy}


# ---- scoring ------------------------------------------------------------------------------------------------
def energy_score(want: str | None, have: str | None, credit: float) -> float:
    if want not in ENERGY_ORDER or have not in ENERGY_ORDER:
        return credit
    return {0: 1.0, 1: 0.5}.get(abs(ENERGY_ORDER.index(want) - ENERGY_ORDER.index(have)), 0.0)


def components(want: dict, have: dict, fit: dict) -> dict:
    credit = float(fit["unknown_credit"])
    wanted = set(want["instruments"])
    shared = sorted(wanted & set(have["instruments"]))
    instruments = (len(shared) / len(wanted)) if wanted and have["instruments"] else (credit if not wanted else 0.0)
    tempo = (max(0.0, 1.0 - abs(want["bpm"] - have["bpm"]) / float(fit["tempo_tolerance_bpm"]))
             if have["bpm"] is not None else credit)
    key = (1.0 if str(have["key"]).lower() == want["key"].lower() else 0.0) if have["key"] else credit
    return {"instruments": round(instruments, 4), "tempo": round(tempo, 4), "key": round(key, 4),
            "energy": round(energy_score(want["energy"], have["energy"], credit), 4), "shared_instruments": shared}


def film_number(film: object) -> int | None:
    found = EPISODE_NUMBER.match(film) if isinstance(film, str) else None
    return int(found.group(1)) if found else None


def used_films(row: dict) -> list[str]:
    return [u["film"] for u in row["used_in"] if isinstance(u, dict) and isinstance(u.get("film"), str)]


def previous_film(document: dict, current_film: str) -> str | None:
    """The highest-numbered episode below ``current_film`` that any bed lists in ``used_in`` (brand/other ids ignored)."""
    now = film_number(current_film)
    if now is None:
        return None
    earlier = {f for row in document["beds"] for f in used_films(row) if (n := film_number(f)) is not None and n < now}
    return max(earlier, key=lambda f: (film_number(f), f)) if earlier else None


def refusals(row: dict, *, lib_dir: Path, data: dict, domain_id: str, target_s: float, previous: str | None,
             verify: bool) -> list[str]:
    settings, why = data["library"], []
    if row["status"] not in settings["status_ok"]:
        why.append(f"status {row['status']!r} is not approved")
    gate = row["vocal_gate"]
    limit = float(data["vocal_step"].get("gate_limit_db", -35.0))
    if not (gate["pass"] is True and gate["vocal_minus_bed_rms_db"] <= limit and gate["windows_over_-40dBFS"] == 0):
        why.append(f"vocal-free numbers do not pass (rms {gate['vocal_minus_bed_rms_db']} dB, "
                   f"{gate['windows_over_-40dBFS']} windows over -40 dBFS)")
    if row.get("domain", domain_id) != domain_id:
        why.append(f"bed belongs to domain {row['domain']!r}")
    why.extend(library.check_file(lib_dir, row, rate=settings["sample_rate"], channels=settings["channels"],
                                  hash_file=verify and settings["verify_sha256"]))
    if float(row["duration_s"]) < target_s:
        why.append(f"lasts {row['duration_s']} s, the film needs {target_s:g} s (film + extra)")
    if settings["exclude_previous_episode"] and previous and previous in used_films(row):
        why.append(f"used by the previous episode {previous}")
    return why


def rank(data: dict, document: dict, *, lib_dir: Path, brief: dict, evidence: dict | None, target_s: float,
         film: str, domain_id: str, verify: bool = True) -> tuple[list[dict], str | None]:
    """Every bed with its attributes, components, score and refusals; best first.  Also the previous film id."""
    fit, previous = data["fit"], previous_film(document, film)
    want = wanted_attributes(brief, evidence, data)
    rows = []
    for row in document["beds"]:
        have = bed_attributes(row, data)
        parts = components(want, have, fit)
        base = sum(fit["weights"][k] * parts[k] for k in fit["weights"])
        own = film in used_films(row)
        others = len([f for f in used_films(row) if f != film])
        score = max(0.0, base + (fit["own_use_bonus"] if own else 0.0) - fit["reuse_penalty_per_film"] * others)
        why = refusals(row, lib_dir=lib_dir, data=data, domain_id=domain_id, target_s=target_s, previous=previous, verify=verify)
        content = base - fit["reuse_penalty_per_film"] * others
        by_content = (not why and parts["instruments"] >= fit["min_instrument_score"] and content >= fit["min_total_score"])
        fits = by_content or (not why and own and bool(fit.get("own_use_is_fit", False)))
        rows.append({"id": row["id"], "eligible": not why, "fits": fits, "fits_by_content": by_content, "refused_because": why,
                     "score": round(score, 4), "score_without_own_use": round(content, 4),
                     "components": parts, "attributes": have, "already_used_by_this_episode": own,
                     "used_in_other_films": others, "duration_s": row["duration_s"]})
    rows.sort(key=lambda r: (not r["fits"], not r["eligible"], not r["already_used_by_this_episode"], -r["score"],
                            r["used_in_other_films"], r["id"]))
    return rows, previous


def explain(winner: dict, ranking: list[dict], want: dict) -> str:
    parts = winner["components"]
    text = (f"{winner['id']}: score {winner['score']} (instruments {parts['instruments']} sharing {parts['shared_instruments']}, "
            f"tempo {parts['tempo']}, key {parts['key']}, energy {parts['energy']})")
    if winner["already_used_by_this_episode"]:
        text += (f"; this episode already used it (+bonus, a re-run is stable; content score without the bonus "
                 f"{winner['score_without_own_use']}, fits by content: {winner['fits_by_content']})")
    others = [r for r in ranking if r["fits"] and r["id"] != winner["id"]]
    if others:
        text += f"; next best {others[0]['id']} {others[0]['score']}"
    return text + f"; wanted {want['instruments']} at {want['bpm']:g} BPM, {want['key']}, {want['energy']}"


def pick(data: dict, document: dict, *, lib_dir: Path, brief: dict, evidence: dict | None, target_s: float, film: str,
         domain_id: str, verify: bool = True) -> dict:
    """``{decision: library|generate, bed_id, reason, ranking, previous_film, wanted}``."""
    ranking, previous = rank(data, document, lib_dir=lib_dir, brief=brief, evidence=evidence, target_s=target_s,
                             film=film, domain_id=domain_id, verify=verify)
    want = wanted_attributes(brief, evidence, data)
    fitting = [r for r in ranking if r["fits"]]
    if fitting:
        return {"decision": "library", "bed_id": fitting[0]["id"], "reason": explain(fitting[0], ranking, want),
                "ranking": ranking, "previous_film": previous, "wanted": want}
    eligible = [r for r in ranking if r["eligible"]]
    if eligible:
        best = eligible[0]
        reason = (f"no bed fits: {len(eligible)} eligible, best {best['id']} scored {best['score']} with instrument match "
                  f"{best['components']['instruments']} (needs >= {data['fit']['min_instrument_score']} and total >= "
                  f"{data['fit']['min_total_score']})")
    else:
        reason = "no bed is eligible: " + "; ".join(f"{r['id']}: {r['refused_because'][0]}" for r in ranking) if ranking else \
            "the library has no beds"
    return {"decision": "generate", "bed_id": None, "reason": reason, "ranking": ranking, "previous_film": previous,
            "wanted": want}


def library_stem(lib_dir: Path, row: dict) -> dict:
    """The ``stem`` block the mix reads from a music receipt: an absolute path (the bed stays in the library) + sha256 +
    the vocal-free numbers the bed was registered with (its file sha256 is re-verified by the mix on load)."""
    gate = row["vocal_gate"]
    return {"take": row["id"], "path": str(library.bed_path(lib_dir, row)), "sha256": row["sha256"],
            "duration_s": row["duration_s"], "picked_by": "library pick",
            "vocal_gate": {"status": "PASS" if gate["pass"] is True else "FAIL", "source": "library registry",
                           "note": "measured when the bed was registered; the file sha256 is re-verified now and by the mix",
                           **{k: v for k, v in gate.items() if k != "pass"}}}


def used_entry(film: str, *, receipt: str, brief: dict, reason: str) -> dict[str, Any]:
    return {"film": film, "where": "film bed (jjv audio music pick)", "receipt": receipt, "brief": brief,
            "reason": reason, "mix": None}
