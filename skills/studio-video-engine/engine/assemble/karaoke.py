"""Karaoke captions for the assembled film: measured word timing (+ first-word snap) or a labelled estimate."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..captions import ass as caption_ass
from ..core.io import sha256_file
from .edl import abs_path, refuse
from .timing import EDL_TIMING_MISMATCH, first_word_snap, load_timing_entry


def estimate_word_times(text: str, first_s: float, last_s: float) -> list[dict]:
    """Deterministic fallback word timing inside a declared speech window (placeholder rows only)."""
    words = [unicodedata.normalize("NFC", word) for word in text.split()]
    weights = [max(2, len(word)) for word in words]
    cursor, out = first_s, []
    total = sum(weights) or 1
    for word, weight in zip(words, weights):
        span = (last_s - first_s) * weight / total
        out.append({"text": word, "start_s": round(cursor, 3), "end_s": round(cursor + span, 3)})
        cursor += span
    return out


def build_caption_ass(edl: Mapping[str, Any], segments: Sequence[Mapping[str, Any]], work: Path,
                      policy: Any, base: Path) -> tuple[str, list[dict]]:
    """One karaoke entry per dialogue row with text.  Measured rows use the engine WORD-TIMING receipt (and, with
    ``timing.qa``, the first-word snap); rows without timing are ``ESTIMATED(placeholder)`` and say so in the receipt."""
    by_id = {row["id"]: row for row in segments}
    entries, notes = [], []
    for dialogue in edl.get("dialogue", []):
        if not dialogue.get("text"):
            continue
        segment = by_id[dialogue["segment"]]
        start = segment["start_f"] / policy.fps + float(dialogue.get("at_s", 0.0))
        segment_end = (segment["start_f"] + segment["dur_f"]) / policy.fps
        measured = load_timing_entry(dialogue, base)
        if measured is not None:
            words = [{"text": w["text"], "raw_text": w.get("raw_text", w["text"]),
                      "start_s": w["start_s"], "end_s": w["end_s"]} for w in measured["words"]]
            snaps: list[dict] = []
            qa = dialogue["timing"].get("qa")
            if qa:
                qa_path = abs_path(qa["receipt"], base)
                if sha256_file(qa_path) != qa.get("sha256"):
                    refuse(EDL_TIMING_MISMATCH, f"{dialogue['id']}: QA receipt sha does not match {qa_path.name}")
                words, snaps = first_word_snap(words, dialogue["timing"].get("entry_id", dialogue["id"]),
                                               json.loads(qa_path.read_text(encoding="utf-8")), qa["sha256"])
            notes.append({"id": dialogue["id"], "timing": "measured", "receipt_sha256": dialogue["timing"]["sha256"],
                          "words": len(words), "first_word_s": words[0]["start_s"], "last_end_s": words[-1]["end_s"],
                          "abs_start_s": round(start, 3), "snaps": snaps})
        else:
            window = dialogue.get("speech_window_s") or [0.15, max(0.6, segment_end - start - 0.25)]
            first_s, last_s = float(window[0]), float(window[1])
            words = estimate_word_times(str(dialogue["text"]), first_s, last_s)
            notes.append({"id": dialogue["id"], "timing": "ESTIMATED(placeholder)", "window_s": [first_s, last_s],
                          "abs_start_s": round(start, 3)})
        entries.append({"id": dialogue["id"], "start_frame": 0, "audio": {"offset_seconds": start}, "words": words})
    cues = caption_ass.words_to_cues({"fps": policy.fps, "entries": entries})
    title = str(edl.get("caption_title") or f"{edl['film_id']} karaoke")
    text = caption_ass.cues_to_ass(cues, title=title)
    text, zone_notes = apply_caption_zones(text, edl.get("caption_zones"), segments, policy.fps)
    (work / "captions.ass").write_text(text, encoding="utf-8")
    return text, notes + zone_notes


EDL_CAPTION_ZONE = "EDL_CAPTION_ZONE"
_ASS_TIME = re.compile(r"^(\d+):(\d\d):(\d\d)\.(\d\d)$")


def _cs(stamp: str) -> int:
    match = _ASS_TIME.match(stamp)
    if not match:
        refuse(EDL_CAPTION_ZONE, f"cannot read the ASS time {stamp!r}")
    h, m, s, c = (int(x) for x in match.groups())
    return ((h * 60 + m) * 60 + s) * 100 + c


def _stamp(cs: int) -> str:
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def apply_caption_zones(ass_text: str, zones: Sequence[Mapping[str, Any]] | None, segments: Sequence[Mapping[str, Any]],
                        fps: int) -> tuple[str, list[dict]]:
    """Move the karaoke line while a named segment is on screen (EDL ``caption_zones``).

    A zone is ``{"segment": id, "alignment": 1..9, "margin_v": int >= 0 (optional)}``: for the frames of that segment the
    line is shown with ASS ``\\an<alignment>`` (and ``MarginV`` when given), the style is unchanged.  A caption line that
    crosses a zone border is split at the border; every later piece starts with an empty ``\\k`` syllable that skips the time
    already elapsed, so the word highlight stays on the audio.  Lines outside every zone are left byte-identical.
    """
    if not zones:
        return ass_text, []
    by_id = {row["id"]: row for row in segments}
    spans = []   # (start_cs, end_cs, zone)
    for zone in zones:
        sid = zone.get("segment") if isinstance(zone, Mapping) else None
        align, margin = zone.get("alignment") if isinstance(zone, Mapping) else None, zone.get("margin_v") if isinstance(zone, Mapping) else None
        if sid not in by_id:
            refuse(EDL_CAPTION_ZONE, f"caption_zones: unknown segment {sid!r}")
        if isinstance(align, bool) or not isinstance(align, int) or not 1 <= align <= 9:
            refuse(EDL_CAPTION_ZONE, f"caption_zones[{sid}]: alignment must be an integer 1..9, got {align!r}")
        if margin is not None and (isinstance(margin, bool) or not isinstance(margin, int) or margin < 0):
            refuse(EDL_CAPTION_ZONE, f"caption_zones[{sid}]: margin_v must be an integer >= 0, got {margin!r}")
        seg = by_id[sid]
        spans.append((round(seg["start_f"] / fps * 100), round((seg["start_f"] + seg["dur_f"]) / fps * 100), dict(zone)))
    out, split = [], {id(z): 0 for _, _, z in spans}
    for line in ass_text.split("\n"):
        if not line.startswith("Dialogue:"):
            out.append(line)
            continue
        head, text = line.split(",", 9)[:9], line.split(",", 9)[9]
        start, end = _cs(head[1]), _cs(head[2])
        cuts = sorted({start, end} | {c for a, b, _ in spans for c in (a, b) if start < c < end})
        pieces = []
        for lo, hi in zip(cuts, cuts[1:]):
            zone = next((z for a, b, z in spans if a <= lo and hi <= b), None)
            pieces.append((lo, hi, zone))
        if all(z is None for _, _, z in pieces):
            out.append(line)
            continue
        for lo, hi, zone in pieces:
            fields = list(head)
            fields[1], fields[2] = _stamp(lo), _stamp(hi)
            if zone is not None and zone.get("margin_v") is not None:
                fields[7] = str(zone["margin_v"])
            body = (f"{{\\an{zone['alignment']}}}" if zone is not None else "") + \
                   (f"{{\\k{lo - start}}}" if lo > start else "") + text
            out.append(",".join(fields) + "," + body)
        if len(pieces) > 1:
            for _, _, z in spans:
                if any(p[2] is z for p in pieces):
                    split[id(z)] += 1
    notes = [{"zone": True, "segment": z["segment"], "alignment": z["alignment"], "margin_v": z.get("margin_v"),
              "events_split": split[id(z)]} for _, _, z in spans]
    return "\n".join(out), notes
