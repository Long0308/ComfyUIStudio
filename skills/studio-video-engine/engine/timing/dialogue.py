"""Input of ``jjv timing words``: the dialogue lines, the vocabulary, and the word rows of a recognised line.

A line is ``{id, start_frame, end_frame_exclusive, speech_text, audio{path, sha256}}`` (the shape of an
engine review config's ``dialogue[]`` rows; ``speaker``, ``en_markup``, ``target_keywords`` and
``audio.offset_frames`` are carried through).  Every WAV is bound by sha256 (receipt-WAV rule).
Vocabulary is data: ``[{term, icon, anchor: "first"|"all"}]`` (a multi-word term anchors on its first
word by default, a single word on itself).
"""

from __future__ import annotations

import re
from typing import Any

from ..core.errors import Refused
from .recognise import Heard, normalize_word, script_tokens
from .sound import frame_of

SHA = re.compile(r"^[0-9a-f]{64}$")
CARRIED = ("speaker", "en_markup", "target_keywords")


def _int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Refused(f"{label} must be an integer, got {value!r}")
    return value


def parse_lines(document: Any) -> list[dict]:
    """Validated dialogue rows in document order; a malformed row or duplicate id is Refused."""
    rows = document.get("dialogue") if isinstance(document, dict) else None
    if not isinstance(rows, list) or not rows:
        raise Refused("dialogue document needs a non-empty 'dialogue' list")
    lines, seen = [], set()
    for row in rows:
        name = row.get("id") if isinstance(row, dict) else None
        if not isinstance(name, str) or not name or name in seen:
            raise Refused(f"dialogue row without a unique string id: {name!r}")
        seen.add(name)
        start, end = _int(row.get("start_frame"), f"{name}.start_frame"), _int(row.get("end_frame_exclusive"), f"{name}.end_frame_exclusive")
        text, audio = row.get("speech_text"), row.get("audio")
        if end <= start or not isinstance(text, str):
            raise Refused(f"{name}: needs end_frame_exclusive > start_frame and a speech_text string")
        if not isinstance(audio, dict) or not isinstance(audio.get("path"), str) or not SHA.match(str(audio.get("sha256"))):
            raise Refused(f"{name}: audio needs a path and a 64-hex sha256 (every WAV is hash-bound)")
        offset = audio.get("offset_frames", 0)
        lines.append({"id": name, "start_frame": start, "end_frame_exclusive": end, "speech_text": " ".join(text.split()),
                      "audio": {"path": audio["path"], "sha256": audio["sha256"], "offset_frames": _int(offset, f"{name}.audio.offset_frames"),
                                **({"duration_seconds": audio["duration_seconds"]} if "duration_seconds" in audio else {})},
                      **{k: row[k] for k in CARRIED if k in row}})
    return lines


def parse_vocabulary(items: Any) -> list[dict]:
    """``[{term, icon, anchor}]`` with defaults filled; empty/None is no vocabulary."""
    if not items:
        return []
    out = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("term"), str) or not isinstance(item.get("icon"), str):
            raise Refused(f"vocabulary item needs string term and icon: {item!r}")
        parts = [normalize_word(p) for p in item["term"].split() if normalize_word(p)]
        anchor = item.get("anchor", "first")
        if not parts or anchor not in ("first", "all"):
            raise Refused(f"vocabulary item {item!r}: term must have a word and anchor be 'first' or 'all'")
        out.append({"term": item["term"], "icon": item["icon"], "parts": parts, "anchor": anchor})
    return out


def keyword_positions(normalized: list[str], keywords: list[str]) -> set[int]:
    """Script positions covered by any ``target_keywords`` phrase."""
    found: set[int] = set()
    for keyword in keywords:
        parts = [normalize_word(p) for p in keyword.split() if normalize_word(p)]
        for start in range(len(normalized) - len(parts) + 1 if parts else 0):
            if normalized[start:start + len(parts)] == parts:
                found.update(range(start, start + len(parts)))
    return found


def vocabulary_marks(normalized: list[str], vocabulary: list[dict]) -> dict[int, dict]:
    """Per script position the icon/term/anchor/span of the longest vocabulary term covering it."""
    marks: dict[int, dict] = {}
    for item in sorted(vocabulary, key=lambda i: -len(i["parts"])):
        width = len(item["parts"])
        for start in range(len(normalized) - width + 1):
            if normalized[start:start + width] != item["parts"]:
                continue
            if any(pos in marks for pos in range(start, start + width)):
                continue
            for k in range(width):
                marks[start + k] = {"vocab_icon": item["icon"], "vocab_term": item["term"], "vocab_span": item["term"],
                                    "vocab_anchor": item["anchor"] == "all" or k == 0}
    return marks


def word_rows(line: dict, heard: list[Heard], vocabulary: list[dict], fps: float, duration_s: float,
              method: str) -> list[dict]:
    """Rows of one recognised line: script text authoritative, times monotonic and inside the WAV and window."""
    tokens = script_tokens(line["speech_text"])
    normalized = [t["normalized"] for t in tokens]
    keywords = keyword_positions(normalized, line.get("target_keywords") or [])
    marks = vocabulary_marks(normalized, vocabulary)
    first, window_end = line["start_frame"], line["end_frame_exclusive"]
    rows, previous_end = [], 0.0
    for index, (token, word) in enumerate(zip(tokens, heard)):
        start = min(max(word.start_s, 0.0), duration_s - 0.020)
        start = max(start, previous_end)
        end = min(max(word.end_s, start + 0.020), duration_s)
        if end <= start:
            end = min(duration_s, start + 0.020)
        previous_end = end
        start_f = first + frame_of(start, fps)
        end_f = min(max(first + frame_of(end, fps), start_f + 1), window_end)
        mark = marks.get(index, {})
        rows.append({
            "index": index + 1, **token, "start_s": start, "end_s": end, "start_frame": start_f, "end_frame": end_f,
            "end_frame_exclusive": end_f, "is_keyword": index in keywords,
            "vocab_icon": mark.get("vocab_icon"), "vocab_term": mark.get("vocab_term"),
            "vocab_anchor": mark.get("vocab_anchor", False), "vocab_span": mark.get("vocab_span"),
            "method": method, "recognition_confidence": round(word.probability, 6), "recognized_text": word.raw.strip(),
            "raw_whisper_start_s": word.start_s if index == 0 else None,
            "raw_whisper_end_s": word.end_s if index == len(tokens) - 1 else None,
            "boundary_calibrated_start": False, "boundary_calibrated_end": False})
    return rows
