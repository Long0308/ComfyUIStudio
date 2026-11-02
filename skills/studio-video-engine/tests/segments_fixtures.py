"""Shared helpers of the segments tests (T-E45 P2, engine side): constants, the derived-timeline switch, the invariants written
independently of the implementation, and the synthetic timeline generator."""

from __future__ import annotations

import random
import shutil

import pytest

from editorial_fixtures import Inputs
from engine.config import loader

KIT = loader.SKILL_ROOT / "remotion-kit"
SCHEMA = loader.SKILL_ROOT / "schemas" / "segments.schema.json"
NODE = shutil.which("node")
KINDS = {"intro", "shot_span", "transition", "card", "plate", "ending", "logo_hold"}


@pytest.fixture()
def inputs(tmp_path) -> Inputs:
    return Inputs(tmp_path)


def _derive(inputs: Inputs, **ending) -> Inputs:
    """Switch the ep04 table to the derived timeline (see test_editorial_ending_params)."""
    doc = inputs.boundaries
    doc["ending"].update({"derive_timeline": True, **ending})
    del doc["ending"]["end_plate"]["start"]
    del doc["ending"]["logo_disc"]["fade_start"]
    for card in doc["cards"]:
        del card["start_frame"], card["duration_frames"]
    for row in doc["boundaries"]:
        if row["to_shot"].startswith("CARD_") or row["to_shot"] in ("END_PLATE", "ENDLOGO"):
            del row["frame"]
        if row["type"] == "iris":
            del row["params"]["disc_fade_start_f"]
    return inputs


def _table(doc: dict) -> list[tuple]:
    return [(s["id"], s["kind"], s["start"], s["end_exclusive"]) for s in doc["segments"]]


# ---- the invariants, written independently of the implementation -------------------------------------
def _assert_valid(doc: dict, windows: list[tuple]) -> None:
    rows = doc["segments"]
    assert rows and rows[0]["start"] == 0 and rows[-1]["end_exclusive"] == doc["total_frames"]
    for a, b in zip(rows, rows[1:]):
        assert a["end_exclusive"] == b["start"], f"gap or overlap between {a['id']} and {b['id']}"
    assert len({s["id"] for s in rows}) == len(rows), "segment ids are unique"
    for s in rows:
        assert s["frames"] == s["end_exclusive"] - s["start"] >= 1
        assert s["kind"] in KINDS
    cuts = [s["start"] for s in rows[1:]]
    assert doc["cut_points"] == [0, *cuts, doc["total_frames"]]
    for start, end, name in windows:
        inside = [c for c in cuts if start < c < end]
        assert not inside, f"cut(s) {inside} inside the window of {name} f{start}..f{end - 1}"


def _windows(built_or_records) -> list[tuple]:
    out = []
    for rec in built_or_records:
        if rec["end_exclusive"] > rec["start"]:
            out.append((rec["start"], rec["end_exclusive"], rec["id"]))
    return out


# ---- synthetic timelines (property test) -------------------------------------------------------------
def _synthetic(seed: int, derived: bool):
    rng = random.Random(seed)
    fps = 30
    intro_end = rng.choice([0, 60, 90])
    cursor, shots = intro_end, []
    for i in range(rng.randint(3, 9)):
        frames = rng.randint(40, 200)
        shots.append({"id": f"S{i + 1:02d}", "start": cursor, "end": cursor + frames})
        cursor += frames
    dialogue_end = cursor
    transitions = []
    names = (["INTRO"] if intro_end else []) + [s["id"] for s in shots]
    starts = ([0] if intro_end else []) + [s["start"] for s in shots]
    for k in range(1, len(names)):
        frame = starts[k]
        kind = rng.choice(["carry", "cut", "from", "centred", "tail"])
        if kind in ("carry", "cut"):
            start = end = frame
        elif kind == "from":
            start, end = frame, frame + rng.randint(6, 14)
        elif kind == "centred":
            half = rng.randint(2, 6)
            start, end = frame - half, frame + half
        else:
            start, end = frame - 2, frame + rng.randint(4, 12)
        rec = {"id": f"T{frame}", "boundary": frame, "from": names[k - 1], "to": names[k],
               "start": start, "end_exclusive": end}
        if kind == "tail":
            rec["outgoing_tail"] = {"tail_output_frames": end - frame}
        transitions.append(rec)
    hold = rng.choice([0, 60, 70]) if derived else 0
    card_start = dialogue_end + hold
    cards = []
    for i in range(rng.randint(2, 5)):
        frames = rng.choice([24, 47, 90])
        cards.append({"term": f"c{i}", "start": card_start, "frames": frames})
        card_start += frames
    for a, b in zip(cards, cards[1:]):
        transitions.append({"id": f"T{b['start']}", "boundary": b["start"], "from": f"CARD_{a['term']}",
                            "to": f"CARD_{b['term']}", "start": b["start"], "end_exclusive": b["start"] + 6})
    cards_end = card_start
    plate_start = cards_end if derived else cards_end - rng.randint(5, 20)
    main = (plate_start + 4) if derived else cards_end
    join = None
    if rng.random() < 0.6:
        iris_to = dialogue_end
        join = dialogue_end - rng.randint(5, 15)
        transitions.append({"id": f"T{iris_to}", "boundary": iris_to, "from": shots[-1]["id"], "to": "OUTRO",
                            "start": join - 30, "end_exclusive": cards[0]["start"] + 6, "renders_as": "iris"})
    return dict(fps=fps, total_frames=main + 60, main_frames=main, intro_end=intro_end, dialogue_end=dialogue_end,
                shots=shots, transitions=transitions, cards=cards, plate_start=plate_start, join_frame=join,
                icons=[])
