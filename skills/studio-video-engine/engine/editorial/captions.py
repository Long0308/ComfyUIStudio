"""Captions (G-CAP) and vocabulary icon events (G-ICON) from a word-timing document.

Hard failures (``Refused``): a dialogue entry without word timing, words that do not spell the
script, non-monotonic words, a word that starts or ends outside its window, a word method other than
``whisper-*`` or ``estimated``, an anchor whose icon is outside the declared term list, and a
declared term that no anchor word covers.  A missing icon file is ``Uncertain`` (unreadable input).
Estimated words are allowed but marked (``estimated: true`` on the icon event).
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file

RAW_START_DELTA_S = 0.3  # raw-vs-calibrated start gap above which the audible raw start wins
ESTIMATED = "estimated"
_WHISPER = re.compile(r"^whisper(-|$)")


def is_allowed_method(method: object) -> bool:
    return isinstance(method, str) and (method == ESTIMATED or _WHISPER.match(method) is not None)


def entries_by_id(timing: dict) -> dict[str, dict]:
    entries = timing.get("entries")
    if not isinstance(entries, list) or not entries:
        raise Refused("word timing has no entries")
    found: dict[str, dict] = {}
    for entry in entries:
        if entry.get("id") in found:
            raise Refused(f"word timing: duplicate entry {entry.get('id')!r}")
        found[entry.get("id")] = entry
    return found


def caption_words(entry: dict) -> list[dict]:
    """Validated word rows of one dialogue entry (G-CAP)."""
    name = entry.get("id")
    words = entry.get("words")
    if not words:
        raise Refused(f"G-CAP: no word timing for {name}")
    first, end = entry["start_frame"], entry["end_frame_exclusive"]
    script = " ".join(word["raw_text"] for word in words)
    if script != " ".join(entry["speech_text"].split()):
        raise Refused(f"G-CAP: words != speech_text for {name}: {script!r} vs {entry['speech_text']!r}")
    rows, previous = [], first - 1
    for word in words:
        if word["start_frame"] < previous or word["end_frame_exclusive"] < word["start_frame"]:
            raise Refused(f"G-CAP: non-monotonic words in {name} at {word['text']!r}")
        if not first <= word["start_frame"] < end or word["end_frame_exclusive"] > end:
            raise Refused(f"G-CAP: word outside its window in {name}: {word['text']!r} "
                          f"(f{word['start_frame']}-f{word['end_frame_exclusive']}, window f{first}-f{end})")
        if not is_allowed_method(word["method"]):
            raise Refused(f"G-CAP: word {word['text']!r} in {name} has timing method {word['method']!r}; "
                          "only whisper-* and 'estimated' are accepted")
        previous = word["start_frame"]
        rows.append({"w": word["raw_text"], "startF": word["start_frame"], "endF": word["end_frame_exclusive"],
                     "keyword": bool(word["is_keyword"]), "method": word["method"],
                     "icon": word["vocab_icon"], "anchor": bool(word["vocab_anchor"])})
    return rows


def pop_frame(entry: dict, word: dict, fps: int, offset_frames: int | None = None) -> tuple[int, str]:
    """Frame an icon pops on: the calibrated start, or the raw whisper start when it differs by
    more than ``RAW_START_DELTA_S`` (the audible syllable).  Both are relative to the WAV start, so
    the WAV's offset in its window is added.  ``offset_frames`` is the shots.json binding offset
    (single source of truth, see ``sources.check_offset``); only a direct caller that passes none
    falls back to the timing entry's own ``audio.offset_frames``."""
    if offset_frames is None:
        offset_frames = int((entry.get("audio") or {}).get("offset_frames") or 0)
    raw = word.get("raw_whisper_start_s")
    if raw is not None and abs(raw - word["start_s"]) > RAW_START_DELTA_S:
        return entry["start_frame"] + int(math.floor(raw * fps + 0.5)) + offset_frames, "raw_whisper_start_s"
    return word["start_frame"] + offset_frames, "start_frame"


def icon_events(entries: list[dict], icons: dict, icon_root: Path, fps: int,
                rel: Any, offsets: dict[str, int] | None = None) -> tuple[list[dict], list[str]]:
    """One event per anchor word, plus warnings; every declared term must be covered.  ``offsets``
    maps an entry id to its WAV offset in frames (from the shots.json binding)."""
    declared = {item["icon"]: item["term"] for item in icons["terms"]}
    events: list[dict] = []
    for entry in entries:
        for word in entry["words"]:
            if not (word["vocab_icon"] and word["vocab_anchor"]):
                continue
            name = word["vocab_icon"]
            if name not in declared:
                raise Refused(f"G-ICON: anchor word {word['text']!r} in {entry['id']} uses icon {name!r}, "
                              f"which is not in the declared term list")
            path = icon_root / name
            if not path.is_file():
                raise Uncertain(f"G-ICON: icon missing on disk: {path.name}")
            frame, source = pop_frame(entry, word, fps, (offsets or {}).get(entry['id']))
            frame += icons["lead_frames"]
            events.append({
                "id": f"IC{len(events) + 1:02d}", "shot": entry["id"], "word": word["text"],
                "term": word["vocab_term"], "icon": name, "icon_path": rel(path),
                "icon_sha256": sha256_file(path), "word_start_frame": word["start_frame"],
                "frame": frame, "frame_source": source, "word_method": word["method"],
                "estimated": word["method"] == ESTIMATED, "hold_frames": icons["hold_frames"],
                "fade_frames": icons["fade_frames"],
                "total_frames": icons["hold_frames"] + icons["fade_frames"] + icons["pop_frames"],
                "lead_frames": icons["lead_frames"]})
    uncovered = sorted(set(declared) - {event["icon"] for event in events})
    if uncovered:
        raise Refused(f"G-ICON: declared terms without an icon event: {uncovered}")
    warnings = [f"icon overlap {a['id']}->{b['id']} f{a['frame']}->f{b['frame']}"
                for a, b in zip(events, events[1:])
                if b["frame"] < a["frame"] + a["hold_frames"] + a["fade_frames"] - 2]
    warnings += [f"icon {e['id']} ({e['term']}) pops on an ESTIMATED word time" for e in events if e["estimated"]]
    return events, warnings


def check_vocabulary_list(timing: dict, icons: dict) -> None:
    """The word-timing document's own icon list must equal the declared terms (drift guard)."""
    listed = timing.get("vocabulary_icons")
    if listed is None:
        return
    theirs = {item["icon"] for item in listed}
    ours = {item["icon"] for item in icons["terms"]}
    if theirs != ours:
        raise Refused(f"word timing vocabulary_icons differ from the declared terms: "
                      f"only in timing {sorted(theirs - ours)}, only declared {sorted(ours - theirs)}")
