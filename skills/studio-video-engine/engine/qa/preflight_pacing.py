"""Preflight pacing arithmetic: config only, no pixels.

Reuses the Q5 arithmetic (``q5_pacing.pacing``: logo still, card length, tiling, plate, main + end card, contract)
and closes the holes the audit named:

* EVERY card must last >= ``card_min_frames`` whether the config DECLARES its length or only implies it: the
  length derived from the card start frames (next start - start; the last one runs to the end plate) must agree
  with the declared one and meet the floor.  The build floor applies only when ``ending.card_min_frames`` is set
  (``end_card.py``); here the review-recipe floor ALWAYS applies (a config may only raise it).
* dialogue pieces tile their window; dialogue end + logo hold == first card start (when the config states them).
* total frames == the contract (``--expect-frames`` or ``DELIVERY-CONTRACT.json`` ``master.frames``), and every
  contract section (dialogue, logo hold, cards, end card) matches the config (the "stale contract" defect).
"""

from __future__ import annotations

from typing import Any

from ..core.errors import Refused
from .gates import FAIL, PASS, UNCERTAIN, roll_up
from .gates.q5_pacing import pacing
from .preflight_segments import Piece
from .review_model import Model


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def card_lengths(model: Model, recipe: dict) -> list[dict]:
    floor = recipe["q5_pacing"]["card_min_frames"]
    declared_floor = _int((model.ending or {}).get("card_min_frames"))
    floor = max(floor, declared_floor or 0)
    plate = _int(((model.ending or {}).get("end_plate") or {}).get("start"))
    cards = model.cards
    rows, bad = [], []
    for i, card in enumerate(cards):
        start, declared = _int(card.get("start_frame")), _int(card.get("duration_frames"))
        nxt = _int(cards[i + 1].get("start_frame")) if i + 1 < len(cards) else plate
        derived = None if start is None or nxt is None else nxt - start
        rows.append({"term": card.get("term"), "declared": declared, "derived": derived})
        if declared is not None and derived is not None and declared == derived:
            labelled = [("declared = derived", declared)]
        else:
            labelled = [("declared", declared), ("derived", derived)]
        bad += [f"{card.get('term')}: {label} {value} f < {floor}" for label, value in labelled
                if value is not None and value < floor]
        if declared is not None and derived is not None and declared != derived:
            bad.append(f"{card.get('term')}: declared {declared} f but the next start implies {derived} f")
        if declared is None and derived is None:
            bad.append(f"{card.get('term')}: neither a declared nor a derivable length")
    detail = f"{len(cards)} cards, floor {floor} f (declared or derived)" + (f"; {bad}" if bad else "")
    return [{**_check("card_length_every_card", not bad and bool(cards), detail), "cards": rows}]


def segments_tile(model: Model, pieces: tuple[Piece, ...]) -> list[dict]:
    bad = []
    for entry in model.dialogue:
        mine = [p for p in pieces if p.logical == entry["id"]]
        start, end = entry.get("start_frame"), entry.get("end_frame_exclusive")
        if not mine or not isinstance(start, int) or not isinstance(end, int):
            continue
        cursor = start
        for piece in mine:
            if piece.start != cursor:
                bad.append(f"{entry['id']}: piece {piece.id} starts f{piece.start}, expected f{cursor}")
            cursor = piece.end
        if cursor != end:
            bad.append(f"{entry['id']}: pieces end f{cursor}, window ends f{end}")
    return [_check("pieces_tile_dialogue", not bad, "; ".join(bad) or f"{len(pieces)} source pieces tile their windows")]


def logo_join(config: dict, model: Model) -> list[dict]:
    hold, first = _int(config.get("logo_hold_frames")), _int(model.cards[0].get("start_frame")) if model.cards else None
    rows = [d for d in model.dialogue if isinstance(d.get("end_frame_exclusive"), int)]
    if hold is None or first is None or not rows:
        return []
    end = rows[-1]["end_frame_exclusive"]
    return [_check("dialogue_logo_cards_join", end + hold == first,
                   f"dialogue ends f{end} + logo hold {hold} f vs first card f{first}")]


def contract_sections(contract: dict, config: dict, model: Model, pieces: tuple[Piece, ...]) -> list[dict]:
    """Every contract section against the config (ids and frame counts)."""
    sections = contract.get("sections")
    if not isinstance(sections, list):
        return []
    bad, frames = [], {p.id: p.frames for p in pieces}
    for d in model.dialogue:
        if not any(p.logical == d["id"] for p in pieces) and isinstance(d.get("end_frame_exclusive"), int):
            frames[d["id"]] = d["end_frame_exclusive"] - d["start_frame"]
    kinds = {"dialogue": [s for s in sections if s.get("kind") == "dialogue"]}
    for s in kinds["dialogue"]:
        if s["id"] not in frames:
            bad.append(f"contract section {s['id']} is not in the config")
        elif frames[s["id"]] != s["frames"]:
            bad.append(f"{s['id']}: contract {s['frames']} f, config {frames[s['id']]} f")
    extra = sorted(set(frames) - {s["id"] for s in kinds["dialogue"]})
    bad += [f"config shot {name} is not a contract section" for name in extra]
    cards = [s for s in sections if s.get("kind") == "vocab_card"]
    if cards or model.cards:
        got = [c.get("duration_frames") for c in model.cards]
        want = [s["frames"] for s in cards]
        if got != want:
            bad.append(f"cards: contract {want}, config {got}")
    for kind, value in (("logo_hold", _int(config.get("logo_hold_frames"))), ("end_card", model.end_frames or None)):
        row = next((s for s in sections if s.get("kind") == kind), None)
        if row is not None and value is not None and row["frames"] != value:
            bad.append(f"{kind}: contract {row['frames']} f, config {value} f")
    intro = next((s for s in sections if s.get("kind") == "intro"), None)
    first = next((d["start_frame"] for d in model.dialogue if isinstance(d.get("start_frame"), int)), None)
    if intro is not None and first is not None and intro["frames"] != first:
        bad.append(f"intro: contract {intro['frames']} f, first dialogue starts f{first}")
    return [_check("contract_sections", not bad, "; ".join(bad) or f"{len(sections)} contract sections match the config")]


def domain_checks(config: dict, model: Model, limits: dict | None) -> list[dict]:
    """Upper bounds the domain grants (``domain.delivery.sections.*.max``, ``delivery.end_card``); floors are applied to the recipe."""
    if not limits:
        return []
    bad = []
    top = limits.get("card_max")
    if top is not None:
        bad += [f"{c.get('term')}: {c.get('duration_frames')} f > {top}" for c in model.cards
                if _int(c.get("duration_frames")) is not None and c["duration_frames"] > top]
    hold = _int(config.get("logo_hold_frames"))
    if hold is not None and not limits.get("logo_hold_min", 0) <= hold <= limits.get("logo_hold_max", hold):
        bad.append(f"logo hold {hold} f outside the domain range [{limits.get('logo_hold_min')}, {limits.get('logo_hold_max')}]")
    lo, hi = limits.get("end_card_min"), limits.get("end_card_max")
    if lo is not None and model.end_frames and not lo <= model.end_frames <= hi:
        bad.append(f"end card {model.end_frames} f outside the domain range [{lo}, {hi}]")
    return [_check("domain_section_limits", not bad, "; ".join(bad) or "cards, logo hold and end card are inside the domain ranges")]


def expected_frames(explicit: int | None, contract: dict | None) -> tuple[int | None, str]:
    if explicit is not None:
        return explicit, "--expect-frames"
    master = (contract or {}).get("master") or {}
    if _int(master.get("frames")) is not None:
        return master["frames"], "contract master.frames"
    return None, "none"


def run(config: dict, model: Model, recipe: dict, pieces: tuple[Piece, ...], explicit: int | None = None,
        contract: dict | None = None, episode_total: int | None = None, limits: dict | None = None) -> dict:
    block = (config.get("qa") or {}).get("review") or {}
    expect, source = expected_frames(explicit if explicit is not None else block.get("expect_total_frames"), contract)
    if expect is None and episode_total is not None:
        expect, source = episode_total, "episode contract (rules.timeline_frames)"
    if expect is not None and explicit is not None and contract and _int((contract.get("master") or {}).get("frames")) not in (None, explicit):
        raise Refused(f"--expect-frames {explicit} disagrees with the contract master.frames {contract['master']['frames']}")
    checks, total = pacing(config, model, recipe, expect)
    checks = [c for c in checks if c["name"] != "card_length"] + card_lengths(model, recipe)
    checks += segments_tile(model, pieces) + logo_join(config, model) + domain_checks(config, model, limits)
    if episode_total is not None and contract and _int((contract.get("master") or {}).get("frames")) not in (None, episode_total):
        checks.append(_check("episode_vs_contract_file", False, f"episode contract total {episode_total} f vs DELIVERY-CONTRACT "
                                                              f"master.frames {contract['master']['frames']} f"))
    if contract:
        checks += contract_sections(contract, config, model, pieces)
    failed = [c for c in checks if not c["ok"] and not c.get("uncertain")]
    unsure = [c for c in checks if not c["ok"] and c.get("uncertain")]
    status = roll_up([FAIL] * bool(failed) + [UNCERTAIN] * bool(unsure) + [PASS])
    return {"gate": "PACING", "status": status, "contract_frames": total, "contract_source": source, "checks": checks,
            "warnings": [] if expect is not None else ["no contract frame count given: only the config's own arithmetic was checked"],
            "failures": [f"{c['name']}: {c['detail']}" for c in failed + unsure]}
