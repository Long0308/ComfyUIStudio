"""Section budget of one film: how many frames each section needs, derived from the script.

Pure functions (no filesystem).  The inputs are facts measured elsewhere: each dialogue line's
receipt-WAV length (and, when the H3 clip already exists, its frame count), each vocabulary
card's WAV length, the end line's WAV length.  The domain owns the floors and maxima
(``domain.delivery.sections`` / ``end_card``); nothing here names a domain or a film.

Rules (user 2026-10-27: a shorter or longer film must be BALANCED, not just pass):

* no section is ever squeezed below its floor, and speech is never time-stretched;
* a target SHORTER than the sum of floors is refused with the numbers of every way out;
* a target LONGER than the floors is met only by extending holds and pauses, each capped by its
  maximum, in the order declared by the domain (line pauses first, then its extensible sections);
* a target LONGER than the sum of maxima is refused too (add declared beats or lines is the way out).
* fixed section kinds (for example a live-action B-roll beat) use the beat's authored duration,
  never an allocator range, and are charged to the same frame budget.

A dialogue line lives in the native frame rate (the H3 clip) and is delivered as
``clip_frames * num / den`` frames; clip lengths are multiples of ``den`` so the mapping is exact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..core.errors import Refused

PIN_KINDS = ("logo_hold", "end_plate", "end_card")

def section_kinds(domain: dict) -> tuple[str, ...]:
    """The section vocabulary declared by this domain, in film-order preference."""
    delivery = domain["delivery"]
    declared = delivery.get("section_kinds")
    if declared is not None:
        if not isinstance(declared, list) or not declared or not all(isinstance(k, str) and k for k in declared):
            raise Refused(f"domain {domain['domain_id']!r} delivery.section_kinds must be a non-empty list of names")
        if len(set(declared)) != len(declared):
            raise Refused(f"domain {domain['domain_id']!r} delivery.section_kinds contains duplicates")
        return tuple(declared)
    # Legacy domains without an explicit list already declare their section
    # ranges in JSON order. Keep that exact vocabulary and ordering when no explicit list exists.
    kinds = ["intro", "dialogue"]
    kinds.extend(kind for kind in (delivery.get("sections") or {}) if kind != "pause_native")
    if delivery.get("end_card"):
        kinds.append("end_card")
    return tuple(kinds)

def fixed_section_kinds(domain: dict) -> tuple[str, ...]:
    """Kinds whose length comes from an authored beat, not from allocator min/max growth."""
    declared = set(section_kinds(domain))
    return tuple(kind for kind, block in (domain["delivery"].get("sections") or {}).items()
                 if block.get("fixed") is True and kind in declared)

def extend_order(domain: dict) -> tuple[str, ...]:
    """Extensible kinds in the domain's declared order; fixed kinds never stretch."""
    fixed = set(fixed_section_kinds(domain))
    return tuple(kind for kind in section_kinds(domain) if kind not in fixed and kind not in ("intro", "end_card"))


class BudgetRefused(Refused):
    """The target cannot be met without breaking a floor or a maximum; carries the options."""

    def __init__(self, message: str, options: list[dict], table: list[dict] | None = None) -> None:
        super().__init__(message)
        self.options = options
        self.table = table or []


@dataclass(frozen=True)
class Section:
    id: str
    kind: str
    low: int        # floor in delivery frames
    high: int       # maximum in delivery frames
    frames: int     # allocated (starts at the floor)
    step: int = 1   # extension granularity in delivery frames
    note: str = ""
    unpinned_low: int | None = None  # the domain floor, when a pin raised ``low``
    recut_low: int | None = None     # an existing clip's length if it were re-made at the floor pause

    def with_frames(self, frames: int) -> "Section":
        return Section(self.id, self.kind, self.low, self.high, frames, self.step, self.note, self.unpinned_low,
                       self.recut_low)


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def _seconds_to_frames(seconds: float, fps: int) -> int:
    return math.ceil(seconds * fps - 1e-9)


def _need(domain: dict, kind: str) -> dict:
    block = (domain["delivery"].get("sections") or {}).get(kind)
    if block is None:
        raise Refused(f"domain {domain['domain_id']!r} defines no delivery.sections.{kind} range")
    return block


def _line_section(line: dict, domain: dict, pause: dict) -> Section:
    rates = domain["frame_rates"]
    native, fps = rates["native_fps"], rates["delivery_fps"]
    num, den = rates["mapping"]["num"], rates["mapping"]["den"]
    wav_native = _seconds_to_frames(line["wav_s"], native)
    clip = line.get("clip_frames")
    if clip is not None:
        if clip % den or clip < wav_native:
            raise Refused(f"line {line['id']}: clip {clip} native frames must be a multiple of {den} "
                          f"and hold the WAV ({wav_native} frames)")
        fixed = clip * num // den
        floor_clip = _ceil_div(wav_native + pause["min"], den) * den
        return Section(line["id"], "dialogue", fixed, fixed, fixed, 1, f"existing H3 clip, WAV {wav_native} f native",
                       None, floor_clip * num // den if floor_clip < clip else None)
    low_clip = _ceil_div(wav_native + pause["min"], den) * den
    high_clip = max(low_clip, _ceil_div(wav_native + pause["max"], den) * den)
    return Section(line["id"], "dialogue", low_clip * num // den, high_clip * num // den,
                   low_clip * num // den, num, f"planned clip, WAV {wav_native} f native")

def _fixed_section(item: dict, domain: dict, fps: int) -> Section:
    """One authored film-sequence beat, fixed to ``duration_s`` in delivery frames."""
    kind = item["kind"]
    block = _need(domain, kind)
    if block.get("fixed") is not True:
        raise Refused(f"film_sequence beat {item['id']}: section kind {kind!r} is not declared fixed by the domain")
    source = block.get("duration_source")
    if source is not None and source != "beat.duration_s":
        raise Refused(f"film_sequence beat {item['id']}: unsupported duration_source {source!r}")
    seconds = item.get("duration_s")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
        raise Refused(f"film_sequence beat {item['id']}: duration_s must be a finite positive number")
    frames = round(seconds * fps)
    if frames < 1:
        raise Refused(f"film_sequence beat {item['id']}: duration_s rounds to fewer than one frame")
    if not block["min"] <= frames <= block["max"]:
        raise Refused(f"film_sequence beat {item['id']}: {frames} f is outside the domain range "
                      f"{block['min']}..{block['max']} for {kind}")
    return Section(item["id"], kind, frames, frames, frames, 1, f"film_sequence fixed {seconds:g} s")


def _pinned(section: Section, pins: dict) -> Section:
    value = pins.get(section.kind)
    if value is None:
        return section
    if not section.low <= value <= section.high:
        raise Refused(f"pin {section.kind}={value} is outside the allowed {section.low}..{section.high} frames")
    return Section(section.id, section.kind, value, value, value, 1, section.note + " (pinned)", section.low)


def build_sections(domain: dict, inputs: dict) -> list[Section]:
    """Every section with its floor/maximum, in film order (the end card last)."""
    fps = domain["frame_rates"]["delivery_fps"]
    pins = inputs.get("pins") or {}
    out: list[Section] = []
    pause = _need(domain, "pause_native")
    sequence = inputs.get("sequence")
    if sequence is not None:
        lines = {line["id"]: line for line in inputs["lines"]}
        for item in sequence:
            if item["kind"] == "dialogue":
                line_id = item.get("line_id", item["id"])
                if line_id not in lines:
                    raise Refused(f"section sequence names unknown dialogue line {line_id!r}")
                out.append(_line_section(lines[line_id], domain, pause))
            else:
                out.append(_fixed_section(item, domain, fps))
    else:
        intro = inputs.get("intro_frames", 0)
        if intro:
            out.append(Section("INTRO", "intro", intro, intro, intro, 1, "title; fixed by the script"))
        out.extend(_line_section(line, domain, pause) for line in inputs["lines"])
    hold = _need(domain, "logo_hold")
    out.append(_pinned(Section("LOGO_HOLD", "logo_hold", hold["min"], hold["max"], hold["min"]), pins))
    if "vocab_card" in section_kinds(domain):
        card = _need(domain, "vocab_card")
        for index, item in enumerate(inputs.get("vocab") or [], start=1):
            low = max(card["min"], _seconds_to_frames(item["wav_s"], fps))
            out.append(Section(f"CARD_{index:02d}", "vocab_card", low, max(low, card["max"]), low, 1,
                               f"{item['term']}: WAV {item['wav_s']:.2f} s"))
    end_line = inputs.get("end_line")
    if end_line:
        plate = _need(domain, "end_plate")
        speech = _seconds_to_frames(end_line["wav_s"], fps)
        low = speech + plate["lead_min"] + plate["tail_min"]
        out.append(_pinned(Section("END_PLATE", "end_plate", low, max(low, plate["max"]), low, 1,
                                   f"end line {speech} f + lead/tail"), pins))
    card_end = domain["delivery"].get("end_card")
    if card_end and inputs.get("end_card", True):
        out.append(_pinned(Section("END_CARD", "end_card", card_end["frames_min"], card_end["frames_max"],
                                   card_end["frames_min"], 1, "logo card after the main film"), pins))
    return out


def _spread(items: list[Section], amount: int) -> tuple[list[Section], int]:
    """Give ``amount`` frames to ``items`` round-robin (one step each), never above a maximum."""
    items = list(items)
    progressed = True
    while amount > 0 and progressed:
        progressed = False
        for index, section in enumerate(items):
            if amount >= section.step and section.frames + section.step <= section.high:
                items[index] = section.with_frames(section.frames + section.step)
                amount -= section.step
                progressed = True
    return items, amount


def totals(sections: list[Section]) -> dict:
    main = sum(s.frames for s in sections if s.kind != "end_card")
    end = sum(s.frames for s in sections if s.kind == "end_card")
    return {"main_frames": main, "end_card_frames": end, "total_frames": main + end}


def _floor_options(sections: list[Section], deficit: int, target: int, domain: dict) -> list[dict]:
    floor_total = sum(s.low for s in sections)
    options: list[dict] = []
    cards = [s for s in sections if s.kind == "vocab_card"]
    saved = 0
    for count, card in enumerate(reversed(cards), start=1):
        saved += card.low
        if saved >= deficit:
            options.append({"option": f"drop {count} vocab card(s)", "frames": -saved,
                            "new_floor_total": floor_total - saved, "sufficient": True})
            break
    else:
        if cards:
            options.append({"option": f"drop all {len(cards)} vocab cards", "frames": -saved,
                            "new_floor_total": floor_total - saved, "sufficient": floor_total - saved <= target})
    for kind in fixed_section_kinds(domain):
        beats = [s for s in sections if s.kind == kind]
        saved = 0
        for count, beat in enumerate(reversed(beats), start=1):
            saved += beat.low
            if saved >= deficit:
                options.append({"option": f"drop {count} {kind} beat(s)", "kind": kind, "frames": -saved,
                                "new_floor_total": floor_total - saved, "sufficient": True})
                break
        else:
            if beats:
                options.append({"option": f"drop all {len(beats)} {kind} beat(s)", "kind": kind, "frames": -saved,
                                "new_floor_total": floor_total - saved,
                                "sufficient": floor_total - saved <= target})
    pinned = [s for s in sections if s.unpinned_low is not None]
    if pinned:
        free = sum(s.low - s.unpinned_low for s in pinned)
        options.append({"option": "unpin " + ", ".join(f"{s.kind}={s.frames}" for s in pinned),
                        "frames": -free, "new_floor_total": floor_total - free,
                        "sufficient": floor_total - free <= target})
    recut = [s for s in sections if s.recut_low is not None]
    if recut:
        saving = sum(s.frames - s.recut_low for s in recut)
        options.append({"option": f"re-make {len(recut)} existing H3 clip(s) with the floor pause (new H3 render + trim, "
                                  "not a config edit)", "frames": -saving, "new_floor_total": floor_total - saving,
                        "sufficient": floor_total - saving <= target, "costs": "GPU re-render"})
    return options


def allocate(domain: dict, inputs: dict, *, target_frames: int | None = None,
             min_frames: int | None = None, max_frames: int | None = None) -> list[Section]:
    """Sections with their allocated frames, or :class:`BudgetRefused` (never squeezes a floor)."""
    sections = build_sections(domain, inputs)
    floor, ceiling = sum(s.low for s in sections), sum(s.high for s in sections)
    want = target_frames
    if want is None and (min_frames is not None or max_frames is not None):
        want = floor if min_frames is None else max(floor, min_frames)
        if max_frames is not None and want > max_frames:
            raise _too_short(sections, floor, max_frames, domain)
    if want is None:
        return sections
    if want < floor:
        raise _too_short(sections, floor, want, domain)
    if want > ceiling:
        raise _too_long(sections, ceiling, want, domain)
    remaining = want - floor
    result = list(sections)
    for kind in extend_order(domain):
        group = [s for s in result if s.kind == kind]
        if not group or remaining <= 0:
            continue
        grown, remaining = _spread(group, remaining)
        by_id = {s.id: s for s in grown}
        result = [by_id.get(s.id, s) for s in result]
    if remaining:
        raise _too_long(sections, ceiling - remaining, want, domain)
    return result


def _table(sections: list[Section]) -> list[dict]:
    return [{"id": s.id, "kind": s.kind, "floor": s.low, "max": s.high, "frames": s.frames, "note": s.note}
            for s in sections]


def _too_short(sections: list[Section], floor: int, want: int, domain: dict) -> BudgetRefused:
    options = _floor_options(sections, floor - want, want, domain)
    return BudgetRefused(
        f"target {want} frames is below the sum of floors {floor} (short by {floor - want}); "
        "no section is squeezed below its floor", options, _table(sections))


def _too_long(sections: list[Section], reachable: int, want: int, domain: dict) -> BudgetRefused:
    declared = section_kinds(domain)
    sections_by_kind = domain["delivery"].get("sections") or {}
    options: list[dict] = []
    if "vocab_card" in declared and sections_by_kind.get("vocab_card"):
        card = sections_by_kind["vocab_card"]["min"]
        options.append({"option": "add vocab cards", "kind": "vocab_card", "frames": card, "each": True,
                        "needed": _ceil_div(want - reachable, card)})
    for kind in fixed_section_kinds(domain):
        options.append({"option": f"add {kind} beat(s) to film_sequence (script change)",
                        "kind": kind, "frames": 0, "each": True})
    if "dialogue" in declared:
        options.append({"option": "add dialogue lines (script change)", "kind": "dialogue",
                        "frames": 0, "each": True})
    return BudgetRefused(
        f"target {want} frames is above what holds and pauses can reach ({reachable}); speech is never stretched",
        options, _table(sections))
