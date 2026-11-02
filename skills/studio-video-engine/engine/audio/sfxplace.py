"""Physical-action SFX never start on a spoken word (the speech-free window rule of the music/SFX skill).

Cues whose source is ``keyword`` or ``manual`` (an action on screen, placed by a default offset) are moved
LATER to the first frame outside every speech window (+ ``pad_s`` each side).  Event cues (icon pop, card, pan
whoosh, logo chime, bed) belong to a picture event and keep their frame.  Every move is returned for the receipt.
"""

from __future__ import annotations

import math

from ..core.errors import Refused

PHYSICAL = ("keyword", "manual")


def avoid_speech(placements: list[dict], windows: list[dict], fps: int, rate: int, total_samples: int,
                 pad_s: float) -> tuple[list[dict], list[dict]]:
    """(placements, moves): ``moves`` rows ``{cue_id, from_frame, to_frame, speech}``."""
    if pad_s <= 0:
        return [dict(p) for p in placements], []
    pad = int(round(pad_s * rate))
    spans = sorted((w["start_sample"] - pad, w["end_sample"] + pad, w["id"]) for w in windows)
    rows, moves = [], []
    for placement in placements:
        row = dict(placement)
        if row.get("source") in PHYSICAL:
            start, hit = row["frame"] * rate // fps, None
            moved = True
            while moved:
                moved = False
                for low, high, name in spans:
                    if low <= start < high:
                        start, hit, moved = high, name, True
            if hit is not None:
                frame = math.ceil(start * fps / rate)
                if frame * rate // fps >= total_samples:
                    raise Refused(f"cue {row['cue_id']} cannot be placed: speech covers the rest of the film after frame {row['frame']}")
                moves.append({"cue_id": row["cue_id"], "from_frame": row["frame"], "to_frame": frame, "speech": hit})
                row["frame"] = frame
        rows.append(row)
    return rows, moves
