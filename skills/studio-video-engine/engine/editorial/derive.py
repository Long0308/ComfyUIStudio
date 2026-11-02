"""The derived editorial timeline (``ending.derive_timeline``): card lengths come from the card WAVs.

Opt-in and editorial only.  The domain master contract (``engine/config/rules``, ``domains/``) is never
touched: a derived film that is longer than the master only produces build WARNINGS.  Without
``derive_timeline`` none of this runs and the declared card frames stay the single source.

What the derived timeline decides (every number is recorded in ``ending.derived_timeline``):

* ``logo_hold_frames`` (default: the domain's ``delivery.sections.logo_hold.min``): the STILL LOGO between the dialogue end and card 1.  Card 1 starts at
  ``dialogue end + logo_hold_frames``; the cards follow back to back (each ``max(card_min_frames, WAV)``).
* the end plate: ``placement`` ``card_end`` (default) starts it on the first frame after the last card window
  (never before the measured speech end) and the main film ends ``frames_after_card_window`` (default 4)
  frames later; ``speech_end`` keeps the earlier rule (the plate sits inside the last card window).
* ``end_card_frames`` (default: the episode timeline's): the end card (EndLogo) after the main film.
* the logo disc layout and the iris row follow the outro start: the disc steps aside on
  ``[outro - 8, outro - 1]`` and shrinks from ``outro``; the iris row carries ``hold_frames`` so its window
  reaches the end of the shrink.  A value written by the author wins when it is consistent and is refused
  when it contradicts the derived outro start.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.errors import Refused
from . import end_card

DEFAULT_PLATE_FRAMES_AFTER = 4
DISC_STEP_FRAMES = 8           # the full disc slides aside during the 8 frames before card 1
DISC_SETTLE_FRAMES = 14        # the disc spring needs 14 frames after it appears to be full size and still


@dataclass(frozen=True)
class Derived:
    document: dict   # boundaries document with cards[] filled, plate start / disc layout / iris row derived
    totals: dict     # main_frames / end_card_frames / total_frames / logo_hold_frames / cards_end
    summary: dict    # what was derived, recorded in ending.derived_timeline


def card_duration(*, samples: int, rate: int, fps: int, card_min: int) -> int:
    """``max(card_min, ceil(wav_seconds x fps))`` in integer arithmetic (never rounds a word short)."""
    return max(card_min, -(-samples * fps // rate))


def _contract_warnings(config, rules_module, main: int, end_card_frames: int) -> list[str]:
    contract = rules_module.timeline_frames(config.episode, config.domain)
    total = main + end_card_frames
    out = []
    if main > contract["main_frames"]:
        out.append(f"derived main film {main} frames exceeds the episode/domain master main film "
                   f"{contract['main_frames']} frames (the master contract is unchanged; extend it before a "
                   "master render)")
    allowance = ((config.domain.get("delivery") or {}).get("end_card") or {}).get("frames_max")
    if allowance is None:
        out.append(f"derived end card {end_card_frames} frames but the domain delivery has no end_card allowance")
    elif end_card_frames > allowance:
        out.append(f"derived end card {end_card_frames} frames exceeds the domain end_card.frames_max {allowance}")
    if total > contract["total_frames"]:
        out.append(f"derived total {total} frames exceeds the episode master total {contract['total_frames']} "
                   "frames")
    return out


def _agree(value, derived, where: str, why: str) -> None:
    if value is not None and value != derived:
        raise Refused(f"{where} is {value} but the derived timeline gives {derived} ({why}); leave it out")


def _derive_disc(ending: dict, outro: int) -> tuple[dict, dict]:
    """(ending with the derived disc numbers, the disc summary); a declared layout wins when it is in order."""
    new = dict(ending)
    disc = dict(ending["logo_disc"]) if isinstance(ending.get("logo_disc"), dict) else None
    if disc is not None:
        _agree(disc.get("fade_start"), outro, "ending.logo_disc.fade_start", "the disc shrinks when card 1 starts")
        disc["fade_start"] = outro
        new["logo_disc"] = disc
    layout = dict(ending.get("logo_disc_layout") or {})
    layout.setdefault("slide_start", outro - DISC_STEP_FRAMES)
    layout.setdefault("slide_end", outro - 1)
    if layout["slide_start"] > layout["slide_end"]:
        raise Refused(f"ending.logo_disc_layout: slide_start {layout['slide_start']} is after slide_end "
                      f"{layout['slide_end']}")
    if layout["slide_end"] >= outro:
        raise Refused(f"ending.logo_disc_layout: slide_end {layout['slide_end']} must be before fade_start "
                      f"{outro} (the first frame of card 1)")
    new["logo_disc_layout"] = layout
    summary = {"slide_start": layout["slide_start"], "slide_end": layout["slide_end"], "fade_start": outro,
               "still_last_f": layout["slide_start"] - 1}
    appears = layout.get("disc_in") if layout.get("disc_in") is not None else (disc or {}).get("in")
    if appears is not None:
        summary["still_first_f"] = appears + DISC_SETTLE_FRAMES
    return new, summary


def _derive_iris_rows(rows: list[dict], ending: dict, outro: int, hold: int) -> list[dict]:
    """The iris row carries the hold and the disc fade start; its window then ends with the disc shrink."""
    out = []
    iris = ending.get("iris") if isinstance(ending.get("iris"), dict) else {}
    disc = ending.get("logo_disc") if isinstance(ending.get("logo_disc"), dict) else {}
    for row in rows:
        if row.get("type") != "iris":
            out.append(row)
            continue
        params = dict(row.get("params") or {})
        label = f"boundary {row.get('from_shot')} -> {row.get('to_shot')} (iris)"
        _agree(params.get("disc_fade_start_f"), outro, f"{label}: params.disc_fade_start_f",
               "the disc shrinks when card 1 starts")
        _agree(params.get("hold_frames"), hold, f"{label}: params.hold_frames", "ending.logo_hold_frames")
        params["disc_fade_start_f"], params["hold_frames"] = outro, hold
        if "iris_close_f" not in params and iris.get("closed") is not None:
            params["iris_close_f"] = iris["closed"]
        if "logo_in_f" not in params and disc.get("in") is not None:
            params["logo_in_f"] = disc["in"]
        out.append({**row, "params": params})
    return out


def plan(ctx, document: dict, config, rules_module, warnings: list) -> Derived | None:
    """None unless ``ending.derive_timeline``; otherwise the document with derived cards, plate and disc."""
    ending = document.get("ending") or {}
    if not ending.get("derive_timeline"):
        return None
    cards = document.get("cards") or []
    if not cards:
        raise Refused("ending.derive_timeline needs cards[] (the card WAVs decide the lengths)")
    fps = config.domain["frame_rates"]["delivery_fps"]
    line = config.episode["timeline"]
    card_min = ending.get("card_min_frames") or end_card.domain_floor(config.domain, "card_min_frames")
    hold = ending.get("logo_hold_frames") or end_card.domain_floor(config.domain, "logo_hold_frames")
    contract = rules_module.timeline_frames(config.episode, config.domain)
    end_card_frames = ending.get("end_card_frames", contract["end_card_frames"])
    dialogue_end = round(fps * (line["intro_s"] + line["dialogue_s"]))
    outro = dialogue_end + hold
    cursor, filled, listed = outro, [], []
    for card in cards:
        wav = ctx.file(card["audio"]["path"], f"card {card['term']!r} WAV")
        samples, rate = end_card.wav_samples(wav)
        frames = card_duration(samples=samples, rate=rate, fps=fps, card_min=card_min)
        for key, value in (("start_frame", cursor), ("duration_frames", frames)):
            if key in card and card[key] != value:
                raise Refused(f"card {card['term']!r} declares {key} {card[key]} but the derived timeline gives "
                              f"{value} (leave it out, or change card_min_frames / logo_hold_frames / the WAV)")
        filled.append({**card, "start_frame": cursor, "duration_frames": frames})
        listed.append({"term": card["term"], "start_frame": cursor, "duration_frames": frames,
                       "wav_seconds": round(samples / rate, 3)})
        cursor += frames
    cards_end, main = cursor, cursor
    new_ending, disc_summary = _derive_disc(ending, outro)
    summary = {"card_min_frames": card_min, "logo_hold_frames": hold, "end_card_frames": end_card_frames,
               "dialogue_end_frame": dialogue_end, "outro_start_frame": outro, "cards_end_frame": cards_end,
               "logo_disc": disc_summary, "cards": listed}
    plate = ending.get("end_plate")
    if plate is not None:
        placement = plate.get("placement", "card_end")
        after = plate.get("frames_after_card_window", DEFAULT_PLATE_FRAMES_AFTER)
        last = filled[-1]
        measured = end_card.speech_end_seconds(ctx.file(last["audio"]["path"], "last card WAV"))
        spoken = math.ceil(last["start_frame"] + measured * fps)
        if placement == "card_end":
            start, main = max(cards_end, spoken), max(cards_end, spoken) + after
        else:
            start = spoken
            if start >= main:
                raise Refused(f"derived end plate would start at f{start}, at or after the end of the main film "
                              f"(f{main}); lengthen card_min_frames")
        summary.update({"plate_placement": placement, "plate_start": start,
                        "plate_frames_after_card_window": after if placement == "card_end" else 0})
        new_plate = {**plate, "placement": placement}
        if "start" not in plate:
            new_plate["start"] = start
        if placement == "card_end":
            new_plate["frames_after_card_window"] = after
        new_ending = {**new_ending, "end_plate": new_plate}
    summary.update({"main_frames": main, "total_frames": main + end_card_frames})
    rows = _derive_iris_rows(document.get("boundaries", []), new_ending, outro, hold)
    warnings.extend(_contract_warnings(config, rules_module, main, end_card_frames))
    totals = {"main_frames": main, "end_card_frames": end_card_frames, "total_frames": main + end_card_frames,
              "logo_hold_frames": hold, "cards_end": cards_end}
    return Derived(document={**document, "cards": filled, "ending": new_ending, "boundaries": rows},
                   totals=totals, summary=summary)
