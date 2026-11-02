"""The editorial timeline derived from the episode (shots.json + timeline) and the word timing.

Everything that places something on a frame (dialogue windows, physical shot starts, card starts,
boundary frames) is checked against it, so a boundary table cannot drift from the audio.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.errors import Refused

INTRO, OUTRO, END_PLATE, END_LOGO = "INTRO", "OUTRO", "END_PLATE", "ENDLOGO"
CARD_PREFIX = "CARD_"


@dataclass(frozen=True)
class PhysicalShot:
    shot: str
    logical: str
    start: int
    delivery_frames: int
    editorial_frames: int
    entry_kind: str
    entry_from: str | None
    clip: dict
    wav_binding: dict

    @property
    def end(self) -> int:
        return self.start + self.delivery_frames


@dataclass(frozen=True)
class Timeline:
    fps: int
    native_fps: int
    intro_end: int
    dialogue_end: int
    main_frames: int
    end_card_frames: int
    shots: tuple[PhysicalShot, ...]
    starts: dict


def delivery_frames(native: int, domain: dict) -> int:
    mapping = domain["frame_rates"]["mapping"]
    return round(native * mapping["num"] / mapping["den"])


def synthetic_entries(config) -> dict[str, dict]:
    """Dialogue windows read off shots.json itself (no word timing): for tools that only need the shot grid."""
    fps = config.domain["frame_rates"]["delivery_fps"]
    cursor = round(fps * config.episode["timeline"]["intro_s"])
    entries: dict[str, dict] = {}
    for shot in config.shots:
        entry = entries.setdefault(shot["logical_shot"], {"start_frame": cursor, "end_frame_exclusive": cursor})
        cursor += delivery_frames(shot["clip"]["frames"], config.domain)
        entry["end_frame_exclusive"] = cursor
    return entries


def build_timeline(config, timing_entries: dict[str, dict], cards: list[dict], rules_module,
                   plate_start: int | None = None, totals: dict | None = None) -> Timeline:
    """Dialogue windows must tile [intro, intro + dialogue] with no gap; shots tile their window.

    ``totals`` (main_frames / end_card_frames, plus logo_hold_frames / cards_end when derived) overrides the
    episode contract for a DERIVED timeline (ending.derive_timeline); without it the contract totals apply,
    exactly as before."""
    domain, episode = config.domain, config.episode
    fps = domain["frame_rates"]["delivery_fps"]
    totals = totals or rules_module.timeline_frames(episode, domain)
    line = episode["timeline"]
    intro_end = round(fps * line["intro_s"])
    dialogue_end = round(fps * (line["intro_s"] + line["dialogue_s"]))
    shots: list[PhysicalShot] = []
    cursor = intro_end
    logical_seen: list[str] = []
    for position, shot in enumerate(config.shots):
        name = shot["logical_shot"]
        entry = timing_entries.get(name)
        if entry is None:
            raise Refused(f"G-CAP: no word timing entry for dialogue {name!r} (every dialogue entry needs timing)")
        if name not in logical_seen:
            if entry["start_frame"] != cursor:
                raise Refused(f"dialogue {name!r} starts at f{entry['start_frame']} in the word timing but the "
                              f"timeline puts it at f{cursor}")
            logical_seen.append(name)
        frames = delivery_frames(shot["clip"]["frames"], domain)
        shots.append(PhysicalShot(
            shot=shot["shot"], logical=name, start=cursor, delivery_frames=frames,
            editorial_frames=shot["clip"]["frames"], entry_kind=shot["entry"]["kind"],
            entry_from=shot["entry"].get("from_shot"), clip=shot["clip"], wav_binding=shot["wav_binding"]))
        cursor += frames
        last_of_logical = all(s["logical_shot"] != name for s in config.shots[position + 1:])
        if last_of_logical and cursor != entry["end_frame_exclusive"]:
            raise Refused(f"dialogue {name!r}: its shots end at f{cursor} but the word timing window ends at "
                          f"f{entry['end_frame_exclusive']}")
    if cursor != dialogue_end:
        raise Refused(f"dialogue ends at f{cursor} but timeline.intro_s + dialogue_s is f{dialogue_end}")
    starts = {INTRO: 0, OUTRO: dialogue_end, END_LOGO: totals["main_frames"]}
    starts.update({s.shot: s.start for s in shots})
    if plate_start is not None:
        starts[END_PLATE] = plate_start
    previous_end = dialogue_end + totals.get("logo_hold_frames", 0)   # the still logo hold precedes card 1
    for card in cards:
        if card["start_frame"] != previous_end:
            raise Refused(f"card {card['term']!r} starts at f{card['start_frame']}, expected f{previous_end} "
                          "(cards tile the outro without a gap)")
        starts[CARD_PREFIX + card["term"]] = card["start_frame"]
        previous_end = card["start_frame"] + card["duration_frames"]
    cards_end = totals.get("cards_end", totals["main_frames"])   # a derived end plate may follow the last card
    if cards and previous_end != cards_end:
        raise Refused(f"cards end at f{previous_end} but the main film ends at f{totals['main_frames']}"
                      + (f" (cards should end at f{cards_end})" if cards_end != totals["main_frames"] else ""))
    return Timeline(fps=fps, native_fps=domain["frame_rates"]["native_fps"], intro_end=intro_end,
                    dialogue_end=dialogue_end, main_frames=totals["main_frames"],
                    end_card_frames=totals["end_card_frames"], shots=tuple(shots), starts=starts)


def required_pairs(timeline: Timeline, cards: list[dict]) -> list[tuple[str, str]]:
    """Every adjacency that is a cut or carry: intro->first, shot->shot, last->outro, card->card."""
    names = [s.shot for s in timeline.shots]
    pairs = [(INTRO, names[0])] if timeline.intro_end > 0 else []
    pairs += list(zip(names, names[1:])) + [(names[-1], OUTRO)]
    pairs += [(CARD_PREFIX + a["term"], CARD_PREFIX + b["term"]) for a, b in zip(cards, cards[1:])]
    return pairs
