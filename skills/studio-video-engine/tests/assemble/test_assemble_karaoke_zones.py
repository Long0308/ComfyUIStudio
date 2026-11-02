"""Per-segment caption zones: the karaoke line moves (ASS alignment) while a segment such as a screen insert is on screen."""

from __future__ import annotations

import pytest

from engine.assemble.edl import Refused, code_of
from engine.assemble.karaoke import apply_caption_zones

FPS = 24
SEGMENTS = [
    {"id": "P1", "start_f": 0, "dur_f": 48},     # 0.00-2.00 s
    {"id": "INS", "start_f": 48, "dur_f": 48},   # 2.00-4.00 s
    {"id": "P2", "start_f": 96, "dur_f": 48},    # 4.00-6.00 s
]
HEAD = "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
ZONE = [{"segment": "INS", "alignment": 8}]


def ass(*lines):
    return HEAD + "\n".join(lines) + "\n"


def event(start, end, text="{\\k100}Xin {\\k100}chao"):
    return f"Dialogue: 0,{start},{end},Karaoke,,0,0,0,,{text}"


def events(text):
    return [line for line in text.splitlines() if line.startswith("Dialogue:")]


def test_line_outside_zone_is_byte_identical():
    src = ass(event("0:00:00.20", "0:00:01.80"), event("0:00:04.50", "0:00:05.50"))
    out, notes = apply_caption_zones(src, ZONE, SEGMENTS, FPS)
    assert out == src and notes[0]["events_split"] == 0


def test_line_inside_zone_gets_alignment_only():
    out, _ = apply_caption_zones(ass(event("0:00:02.50", "0:00:03.50")), ZONE, SEGMENTS, FPS)
    (line,) = events(out)
    assert line.startswith("Dialogue: 0,0:00:02.50,0:00:03.50,Karaoke,,0,0,0,,{\\an8}{\\k100}Xin")


def test_line_spanning_zone_is_split_in_three_with_karaoke_offsets():
    out, notes = apply_caption_zones(ass(event("0:00:01.00", "0:00:05.00")), ZONE, SEGMENTS, FPS)
    before, inside, after = events(out)
    assert before.startswith("Dialogue: 0,0:00:01.00,0:00:02.00,Karaoke,,0,0,0,,{\\k100}Xin")      # untouched text
    assert inside.startswith("Dialogue: 0,0:00:02.00,0:00:04.00,Karaoke,,0,0,0,,{\\an8}{\\k100}{\\k100}Xin")  # 1.00 s already elapsed
    assert after.startswith("Dialogue: 0,0:00:04.00,0:00:05.00,Karaoke,,0,0,0,,{\\k300}{\\k100}Xin")      # 3.00 s already elapsed
    assert notes[0]["events_split"] == 1 and notes[0]["segment"] == "INS"


def test_margin_v_override_sets_the_event_margin():
    zone = [{"segment": "INS", "alignment": 8, "margin_v": 140}]
    out, _ = apply_caption_zones(ass(event("0:00:02.50", "0:00:03.50")), zone, SEGMENTS, FPS)
    assert ",Karaoke,,0,0,140,,{\\an8}" in out


@pytest.mark.parametrize("zone", [
    {"segment": "NOPE", "alignment": 8},
    {"segment": "INS", "alignment": 0},
    {"segment": "INS", "alignment": 10},
    {"segment": "INS", "alignment": "top"},
    {"segment": "INS", "alignment": 8, "margin_v": -1},
])
def test_bad_zone_is_refused_with_a_named_code(zone):
    with pytest.raises(Refused) as caught:
        apply_caption_zones(ass(event("0:00:02.50", "0:00:03.50")), [zone], SEGMENTS, FPS)
    assert code_of(caught.value) == "EDL_CAPTION_ZONE"


def test_no_zones_is_a_no_op():
    src = ass(event("0:00:02.50", "0:00:03.50"))
    assert apply_caption_zones(src, None, SEGMENTS, FPS) == (src, [])
