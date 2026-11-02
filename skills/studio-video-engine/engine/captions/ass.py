"""Pure ASS/SRT caption transforms extracted from the review fallback generator.

The module deliberately has no file, network, or process side effects. Callers
load a WORD-TIMING document, convert it to cues, then render either ASS or SRT.
The defaults keep the fallback's geometry and typography; the karaoke highlight
defaults to the v002 Blue Web accent.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

PLAY_W = 1920
PLAY_H = 1080
FONT = "Arial"
FONT_PX = 60
MARGIN_V = 72
MARGIN_LR = 96
LINE_GAP_S = 0.40
MAX_WORDS_PER_LINE = 9
DEFAULT_HIGHLIGHT = "#0B4FD9"
UNLIT_COLOUR = "#FFFFFF"
OUTLINE_COLOUR = "#000000"
BACK_COLOUR = "#000000"


@dataclass(frozen=True, slots=True)
class Word:
    """One NFC-normalized visible word with absolute cue time."""

    text: str
    start_s: float
    end_s: float


@dataclass(frozen=True, slots=True)
class Cue:
    """One fallback cue (one visible ASS/SRT line)."""

    number: int
    entry_id: str
    start_s: float
    end_s: float
    words: tuple[Word, ...]


def _normalize_hex_colour(value: str) -> str:
    raw = value.removeprefix("#").upper()
    if len(raw) != 6 or any(ch not in "0123456789ABCDEF" for ch in raw):
        raise ValueError(f"expected RRGGBB colour, got {value!r}")
    return raw


def ass_colour(rrggbb: str, alpha: int = 0) -> str:
    """Convert RRGGBB (with or without '#') to ASS '&HAABBGGRR'."""

    if not 0 <= alpha <= 0xFF:
        raise ValueError("alpha must be in 0..255")
    raw = _normalize_hex_colour(rrggbb)
    rr, gg, bb = raw[0:2], raw[2:4], raw[4:6]
    return f"&H{alpha:02X}{bb}{gg}{rr}".upper()


def _ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    hours, rem = divmod(cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    whole_seconds, centiseconds = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def _srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1_000))
    hours, rem = divmod(milliseconds, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    whole_seconds, milliseconds = divmod(rem, 1_000)
    return (
        f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"
    )


def words_to_cues(
    timing: Mapping[str, Any],
    *,
    line_gap_s: float = LINE_GAP_S,
    max_words_per_line: int = MAX_WORDS_PER_LINE,
) -> tuple[Cue, ...]:
    """Split timed words into deterministic caption cues.

    A cue break occurs at a pause of at least ``line_gap_s`` or when the current
    line reaches ``max_words_per_line``. The behavior matches the accepted
    fallback generator.
    """

    if line_gap_s < 0:
        raise ValueError("line_gap_s must be non-negative")
    if max_words_per_line < 1:
        raise ValueError("max_words_per_line must be positive")

    fps = float(timing["fps"])
    if fps <= 0:
        raise ValueError("fps must be positive")

    cues: list[Cue] = []
    for entry in timing.get("entries", ()):
        source_words = entry.get("words", ())
        if not source_words:
            continue

        audio = entry.get("audio") or {}
        offset_s = float(audio.get("offset_seconds", 0.0))
        offset_s += float(entry.get("start_frame", 0)) / fps

        lines: list[list[Mapping[str, Any]]] = [[]]
        for word in source_words:
            if lines[-1]:
                gap = float(word["start_s"]) - float(lines[-1][-1]["end_s"])
                if gap >= line_gap_s or len(lines[-1]) >= max_words_per_line:
                    lines.append([])
            lines[-1].append(word)

        for line in (candidate for candidate in lines if candidate):
            first_start = float(line[0]["start_s"]) + offset_s
            last_end = float(line[-1]["end_s"]) + offset_s
            cue_words = tuple(
                Word(
                    text=unicodedata.normalize(
                        "NFC", str(word.get("raw_text", word["text"]))
                    ),
                    start_s=float(word["start_s"]) + offset_s,
                    end_s=float(word["end_s"]) + offset_s,
                )
                for word in line
            )
            cues.append(
                Cue(
                    number=len(cues) + 1,
                    entry_id=str(entry["id"]),
                    start_s=first_start,
                    end_s=last_end,
                    words=cue_words,
                )
            )

    return tuple(cues)


def _karaoke_text(words: Sequence[Word]) -> str:
    parts: list[str] = []
    for index, word in enumerate(words):
        next_start = words[index + 1].start_s if index + 1 < len(words) else word.end_s
        duration_cs = max(1, int(round((next_start - word.start_s) * 100)))
        parts.append(f"{{\\k{duration_cs}}}{word.text}")
    return " ".join(parts)


def cues_to_ass(
    cues: Sequence[Cue],
    *,
    highlight: str = DEFAULT_HIGHLIGHT,
    title: str = "karaoke review",
    title_suffix: str = "",
) -> str:
    """Render cues as deterministic ASS text using the fallback's geometry; ``title`` names the shot."""

    events = [
        "Dialogue: 0,"
        f"{_ass_time(cue.start_s)},{_ass_time(cue.end_s)},Karaoke,,0,0,0,,"
        f"{_karaoke_text(cue.words)}"
        for cue in cues
    ]
    style = (
        f"Style: Karaoke,{FONT},{FONT_PX},{ass_colour(highlight)},"
        f"{ass_colour(UNLIT_COLOUR)},{ass_colour(OUTLINE_COLOUR)},"
        f"{ass_colour(BACK_COLOUR, 0x80)},"
        f"-1,0,0,0,100,100,0,0,1,3,1,2,"
        f"{MARGIN_LR},{MARGIN_LR},{MARGIN_V},1"
    )
    return "\n".join(
        (
            "[Script Info]",
            f"Title: {title}{title_suffix}",
            "ScriptType: v4.00+",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            f"PlayResX: {PLAY_W}",
            f"PlayResY: {PLAY_H}",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            style,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            "Effect, Text",
            *events,
            "",
        )
    )


def cues_to_srt(cues: Sequence[Cue]) -> str:
    """Render plain SRT text from the same cues; no karaoke tags are added."""

    if not cues:
        return ""
    blocks = [
        f"{number}\n{_srt_time(cue.start_s)} --> {_srt_time(cue.end_s)}\n"
        f"{' '.join(word.text for word in cue.words)}\n"
        for number, cue in enumerate(cues, start=1)
    ]
    return "\n".join(blocks) + "\n"
