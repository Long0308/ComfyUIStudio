"""``jjv editorial boundaries write``: build ``boundaries.json`` from the storyboard check, the ingest boundaries input,
the delivery contract and (optionally) the measured ``boundaries suggest`` rows.

Deterministic (no clock, no network).  Refuses when the storyboard check is not green or the contract is missing.
What cannot be known yet (card WAVs, icon files, a whip direction) is never invented: it is listed under
``pending`` and the result is a DRAFT (``versions/boundaries-draft-vNNN.json``); ``boundaries.json`` is written only
when the document is complete and valid against ``schemas/boundaries.schema.json``.  Versions are write-once.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..config.loader import SKILL_ROOT
from ..config.schema import validate
from ..core.errors import Refused
from ..core.io import pretty_json, read_json
from . import boundaries_current as current
from . import end_card, presets

SCHEMA_PATH = SKILL_ROOT / "schemas" / "boundaries.schema.json"
DRAFT_SCHEMA = "jjv/boundaries-draft/v1"
INTRO, OUTRO, END_PLATE, END_LOGO, CARD = "INTRO", "OUTRO", "END_PLATE", "ENDLOGO", "CARD_"
BLOOM_FRAMES, CARD_SLIDE_FRAMES, PLATE_IN_FRAMES = 6, 6, 4


def _pair(a: str, b: str) -> str:
    return f"{a} -> {b}"


def _check_green(check: dict) -> dict[tuple[str, str], dict]:
    pairs = check.get("pairs") if isinstance(check, dict) else None
    if (not isinstance(check, dict) or check.get("schema") != "jjv/storyboard-check/v1" or check.get("ok") is not True
            or not isinstance(pairs, list) or any(p.get("problems") for p in pairs)):
        raise Refused("storyboard check is not green (need jjv/storyboard-check/v1 with ok true and no pair problems); "
                      "run `jjv storyboard check` and fix it first")
    return {(p["from_shot"], p["to_shot"]): p for p in pairs}


def _section_frames(contract: dict, kind: str) -> list[dict]:
    return [s for s in contract.get("sections", []) if s.get("kind") == kind]


def _picture_row(pair: dict, kind: str, pending: list[str]) -> dict | None:
    label = _pair(pair["from_shot"], pair["to_shot"])
    framing = (pair.get("framing") or {}).get("framing")
    row: dict[str, Any] = {"from_shot": pair["from_shot"], "to_shot": pair["to_shot"],
                           "continuity": pair.get("continuity", "unknown")}
    if kind == "carry":
        row.update({"class": "carry", "type": "none", "frames": 0, "direction": 0,
                    "motivation": "pixel-continuous carry (shots entry kind carry)"})
        return row
    name = pair["preset"]
    if presets.get(name, label=label).direction == "required":
        pending.append(f"{label}: preset {name} needs a direction (-1 or +1); run `boundaries suggest` on the "
                       "measured clips or declare it")
        return None
    row.update({"class": "cut", "type": name, "direction": 0,
                "motivation": f"storyboard {pair.get('rule')} ({framing or 'framing unknown'}, declared, unmeasured)"})
    if framing in ("same_framing", "near_same", "new_framing"):
        row["framing"] = "new_framing" if framing == "new_framing" else "same_framing"
    return row


def _graphic_rows(contract: dict, first: str, last: str, terms: list[str]) -> list[dict]:
    def graphic(a: str, b: str, kind: str, name: str, frames: int, direction: int, why: str) -> dict:
        return {"from_shot": a, "to_shot": b, "class": kind, "type": name, "frames": frames, "direction": direction,
                "motivation": why, "continuity": "agree"}
    rows = []
    if any(s["frames"] > 0 for s in _section_frames(contract, "intro")):
        rows.append(graphic(INTRO, first, "cut", "bloom", BLOOM_FRAMES, 0, "title -> first shot: warm bloom (R8_intro_bloom)"))
    if not terms:
        return rows
    rows.append(graphic(last, OUTRO, "cut", "iris", 44, 0, "dialogue -> logo hold: iris out (derived from the outro start)"))
    names = [CARD + t for t in terms]
    rows += [graphic(a, b, "cut", "card_slide", CARD_SLIDE_FRAMES, -1, "swap between two flashcards of the same layout")
             for a, b in zip(names, names[1:])]
    if _section_frames(contract, "end_plate"):
        rows.append(graphic(names[-1], END_PLATE, "cut", "plate_in", PLATE_IN_FRAMES, 0, "the plate must not cover the last word"))
        if _section_frames(contract, "end_card"):
            rows.append(graphic(END_PLATE, END_LOGO, "carry", "none", 0, 0, "end plate carries into the end card"))
    return rows


def _ending(contract: dict, domain: dict, media: dict) -> dict:
    ending: dict[str, Any] = {"derive_timeline": True}
    hold, cards, tail = (_section_frames(contract, k) for k in ("logo_hold", "vocab_card", "end_card"))
    if hold:
        ending["logo_hold_frames"] = hold[0]["frames"]
    if cards:
        ending["card_min_frames"] = min(s["frames"] for s in cards)
    if tail:
        ending["end_card_frames"] = tail[0]["frames"]
    if media.get("logo"):
        ending["logo"] = media["logo"]
    end_card.check_params(ending, domain)   # the DOMAIN floors are the only floors
    return ending


def _suggested_rows(suggested: dict | None, episode_id: str) -> dict[tuple[str, str], dict]:
    if not suggested:
        return {}
    if suggested.get("episode_id") != episode_id:
        raise Refused(f"suggested rows are for episode {suggested.get('episode_id')!r}, not {episode_id!r}")
    return {(r["from_shot"], r["to_shot"]): r for r in suggested.get("rows", [])}


def build_document(*, check: dict, bounds_input: dict, contract: dict | None, domain: dict,
                   media: dict | None = None, suggested: dict | None = None) -> tuple[dict, list[str]]:
    """``(boundaries document, pending)``; ``pending`` empty means the document is complete and schema-valid."""
    if not contract:
        raise Refused("delivery contract missing: boundaries need the episode contract (jjv script ingest writes "
                      "DELIVERY-CONTRACT.json)")
    pairs = _check_green(check)
    episode_id = check["episode_id"]
    for source, other in (("boundaries input", bounds_input.get("episode_id")), ("contract", contract.get("film_id"))):
        if other != episode_id:
            raise Refused(f"episode_id mismatch: storyboard check {episode_id!r} but {source} {other!r}")
    media = media or {}
    measured = _suggested_rows(suggested, episode_id)
    wanted = [r for r in bounds_input["boundaries"] if r["kind"] in ("cut", "carry")]
    missing = [_pair(r["from_shot"], r["to_shot"]) for r in wanted if (r["from_shot"], r["to_shot"]) not in pairs]
    if missing:
        raise Refused("storyboard check does not cover " + ", ".join(missing))
    pending: list[str] = []
    rows: list[dict] = []
    for item in wanted:
        key = (item["from_shot"], item["to_shot"])
        row = dict(measured[key]) if key in measured else _picture_row(pairs[key], item["kind"], pending)
        if row is not None:
            rows.append(row)
    shots = [wanted[0]["from_shot"]] + [r["to_shot"] for r in wanted] if wanted else []
    terms = [s["term"] for s in _section_frames(contract, "vocab_card")]
    rows += _graphic_rows(contract, shots[0] if shots else "", shots[-1] if shots else "", terms)
    document: dict[str, Any] = {"schema": "jjv/boundaries/v1", "episode_id": episode_id, "boundaries": rows,
                                "ending": _ending(contract, domain, media)}
    audio = media.get("cards_audio") or {}
    absent = [t for t in terms if t not in audio]
    if terms and absent:
        pending.append("cards audio missing for: " + ", ".join(absent) + " (pass --media with cards_audio {term: {path, sha256}})")
    elif terms:
        document["cards"] = [{"term": t, "audio": audio[t]} for t in terms]
    if media.get("icons"):
        document["icons"] = media["icons"]
    else:
        pending.append("icons missing (pass --media with an icons object: dir, terms, hold/fade/pop/lead frames)")
    if media.get("expect_silent"):
        document["expect_silent"] = media["expect_silent"]
    if not pending:
        errors = validate(document, read_json(SCHEMA_PATH), label="boundaries")
        if errors:
            raise Refused("written boundaries.json would be invalid: " + "; ".join(errors))
    return document, pending


def write_outputs(out: Path, document: dict, pending: list[str]) -> dict:
    """Write the version file (write-once) and, when complete, ``boundaries.json`` + ``boundaries.current.json``.

    A draft never touches ``boundaries.json`` or the receipt; it reports ``current_version`` / ``current_is_stale``."""
    out = Path(out)
    complete = not pending
    value = document if complete else {**document, "schema": DRAFT_SCHEMA, "pending": pending}
    prefix = "boundaries" if complete else "boundaries-draft"
    version, reused, target, digest = current.write_version(out / "versions", prefix, pretty_json(value, mode="utf8"))
    if complete:
        current.publish(out, document, version=version, version_path=f"versions/{target.name}", writer="boundaries-write")
    return {"version": version, "reused": reused, "file": str(target), "sha256": digest, "complete": complete,
            "pending": pending, "current": str(out / "boundaries.json") if complete else None,
            **current.staleness(out, document)}


def register(actions: Any) -> None:
    write = actions.add_parser("write", help="build boundaries.json from storyboard check + contract (+ measured rows)")
    write.add_argument("--storyboard-check", required=True, help="storyboard-check.json (must be green)")
    write.add_argument("--boundaries-input", required=True, help="boundaries-input.json from `script ingest`")
    write.add_argument("--contract", required=True, help="DELIVERY-CONTRACT.json (production_domain + sections)")
    write.add_argument("--suggested", help="boundaries-suggested.json (measured rows replace the storyboard choice)")
    write.add_argument("--media", help="JSON with cards_audio {term: {path, sha256}}, icons, logo, expect_silent")
    write.add_argument("--out", required=True, help="folder: versions/ (write-once), boundaries.json when complete")


def _read_required(path: str, what: str) -> dict:
    if not Path(path).is_file():
        raise Refused(f"{what} missing: {path}")
    return read_json(Path(path))


def run_write(args: argparse.Namespace) -> int:
    contract = _read_required(args.contract, "delivery contract")
    domain = read_json(SKILL_ROOT / "domains" / f"{contract.get('production_domain')}.json")
    document, pending = build_document(
        check=_read_required(args.storyboard_check, "storyboard check"),
        bounds_input=_read_required(args.boundaries_input, "boundaries input"), contract=contract, domain=domain,
        media=_read_required(args.media, "media file") if args.media else None,
        suggested=_read_required(args.suggested, "suggested rows") if args.suggested else None)
    result = write_outputs(Path(args.out), document, pending)
    print(json.dumps({"ok": True, "boundary_rows": len(document["boundaries"]), **result}, indent=2, ensure_ascii=True))
    return 0
