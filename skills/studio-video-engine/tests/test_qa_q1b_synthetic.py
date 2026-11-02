"""Q1b caption gate on a SYNTHETIC caption video (numpy -> ffmpeg h264) whose per-word light frame is chosen by the test,
so the gate is proven to follow the PICTURE and not the config: a picture that lights early/late/never, a config that lies
by +-5 f, an unreadable layout and a recipe too loose for the negative control all have to be flagged."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from test_qa_review_support import FFMPEG, needs_ffmpeg, np
from engine.qa.gates import FAIL, PASS, UNCERTAIN, q1b_caption as q1b

pytestmark = needs_ffmpeg

W, H, FPS, FRAMES = 960, 540, 30, 90
PAPER, INK, MUTED, MINT = (255, 253, 248), (23, 58, 52), (124, 150, 144), (207, 239, 201)
PALE, PINK = (255, 227, 238), (255, 46, 126)
RECIPE, SHA = q1b.load_recipe()


def _geo() -> dict:
    return q1b.geometry(RECIPE, W, H)


def _paint_word(frame: "np.ndarray", box: tuple[int, int, int, int], keyword: bool, dt: int) -> None:
    x0, y0, x1, y1 = box
    if keyword:
        k = min(max(dt / 2, 0.0), 1.0)
        frame[y0:y1, x0:x1] = [round(a + (b - a) * k) for a, b in zip(PALE, PINK)]
        return
    if dt >= 0:  # mint highlight from dt 0, ink text (two bars) from dt 1 on
        frame[y0 - 3:y1 + 3, x0 - 3:x1 + 3] = MINT
    bars = INK if dt >= 1 else MUTED
    frame[y0 + 3:y0 + 7, x0:x1] = bars
    frame[y1 - 7:y1 - 3, x0:x1] = bars


def _layout(lines: list[int]) -> list[tuple[int, int, int, int]]:
    """Word boxes of a caption with ``lines`` words per EN line (top line first); positions inside the real EN line spans."""
    geo = _geo()
    boxes, spans = [], list(reversed(geo["spans"][:len(lines)]))
    for count, (lo, hi) in zip(lines, spans):
        for i in range(count):
            x = 60 + i * 130
            boxes.append((x, geo["y"] + lo + 2, x + 90, geo["y"] + hi - 2))
    return boxes


def render(path: Path, words: list[dict], lit_frame: dict[int, int | None], *, lines: list[int], first: int = 0,
           frames: int = FRAMES) -> Path:
    """Write a video of ``frames`` frames starting at global frame ``first``.  ``lit_frame[i]`` = global frame word i lights
    (None = never).  The panel is opaque from the first frame, so the test shots start ``panel_fade_in`` before ``first``."""
    geo = _geo()
    boxes = _layout(lines)
    raw = bytearray()
    for n in range(first, first + frames):
        frame = np.full((H, W, 3), (70, 120, 70), np.uint8)
        top = geo["y"] + geo["spans"][len(lines) - 1][0] - 4
        frame[top:H - 20, 20:W - 20] = PAPER
        for i, (word, box) in enumerate(zip(words, boxes)):
            lit = lit_frame.get(i)
            _paint_word(frame, box, word["keyword"], -99 if lit is None else n - lit)
        raw += frame.tobytes()
    result = subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                             "-i", "-", "-c:v", "libx264", "-crf", "8", "-preset", "ultrafast", "-pix_fmt", "yuv444p", str(path)],
                            input=bytes(raw), capture_output=True)
    assert result.returncode == 0, result.stderr.decode()[:300]
    return path


def words(starts: list[int], keywords: tuple[int, ...] = ()) -> list[dict]:
    return [{"w": f"w{i}", "startF": s, "endF": s + 6, "keyword": i in keywords} for i, s in enumerate(starts)]


def config(ws: list[dict], first: int = 0) -> dict:
    return {"fps": FPS, "dialogue": [{"id": "S01", "start_frame": first - 10, "duration_frames": FRAMES + 40,
                                      "speech_end_in_window_s": 10.0, "words": ws}]}


STARTS = [30, 42, 54, 66]
KEYWORDS = (1,)


def lit_of(starts: list[int], keywords: tuple[int, ...] = KEYWORDS) -> dict[int, int]:
    """The frame the picture first SHOWS each word lit: keywords ramp over 2 f, so the first clearly pink frame is dt +1."""
    return {i: s for i, s in enumerate(starts)}


@pytest.fixture(scope="module")
def good(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return render(tmp_path_factory.mktemp("q1b") / "good.mp4", words(STARTS, KEYWORDS), lit_of(STARTS), lines=[4])


def run(cfg: dict, video: Path, recipe: dict | None = None, origin: int = 0) -> dict:
    return q1b.run_q1b(cfg, video, ffmpeg=FFMPEG, recipe=recipe or copy.deepcopy(RECIPE), recipe_sha256=SHA, origin=origin)


def test_a_picture_that_follows_the_config_passes_and_keywords_light_one_frame_after_startf(good: Path) -> None:
    result = run(config(words(STARTS, KEYWORDS)), good)
    rows = result["words"]
    assert result["status"] == PASS and result["summary"]["tested"] == 4 and result["failures"] == []
    assert [r["delta_f"] for r in rows] == [0, 1, 0, 0]  # plain: mint at dt 0; keyword: pink ramp -> first lit at dt +1
    assert result["control"]["detected"] is True and result["control"]["words_checked"] == 4


@pytest.mark.parametrize("shift,status", [(5, "FAIL-early"), (-5, "FAIL-late")])
def test_a_config_that_lies_by_five_frames_fails_every_word(good: Path, shift: int, status: str) -> None:
    result = run(config(words([s + shift for s in STARTS], KEYWORDS)), good)
    assert result["status"] == FAIL and {r["status"] for r in result["words"]} == {status}
    assert len(result["failures"]) == 4


def test_a_picture_that_lights_one_word_early_flags_exactly_that_word(tmp_path: Path) -> None:
    lit = lit_of(STARTS)
    lit[2] -= 4
    video = render(tmp_path / "early.mp4", words(STARTS, KEYWORDS), lit, lines=[4])
    result = run(config(words(STARTS, KEYWORDS)), video)
    assert result["status"] == FAIL and result["summary"]["early"] == ["S01:w2"]
    row = result["words"][2]
    assert row["first_lit"] == STARTS[2] - 4 and row["delta_f"] == -4


def test_a_word_that_never_lights_fails_late(tmp_path: Path) -> None:
    lit = lit_of(STARTS)
    lit[3] = None
    video = render(tmp_path / "never.mp4", words(STARTS, KEYWORDS), lit, lines=[4])
    result = run(config(words(STARTS, KEYWORDS)), video)
    assert result["status"] == FAIL and result["words"][3]["status"] == "FAIL-late" and result["words"][3]["first_lit"] is None


def test_a_word_that_lights_after_the_word_spoken_after_it_is_an_order_failure(tmp_path: Path) -> None:
    recipe = copy.deepcopy(RECIPE)
    recipe["timing"]["plain_late_max_frames"] = 15  # both words stay inside their own (wide) window ...
    starts = [30, 34, 54, 66]
    lit = {0: 36, 1: 34, 2: 54, 3: 66}  # ... but word 0 lights at f36, after word 1 (f34)
    ws = words(starts, ())
    result = run(config(ws), render(tmp_path / "order.mp4", ws, lit, lines=[4]), recipe)
    assert result["words"][0]["status"] == "FAIL-order" and "after the next word" in result["words"][0]["why"]
    assert result["status"] == FAIL


def test_two_en_lines_are_read_top_line_first(tmp_path: Path) -> None:
    starts = [30, 40, 50, 60, 70]
    ws = words(starts, (3,))
    video = render(tmp_path / "two.mp4", ws, lit_of(starts), lines=[3, 2])
    result = run(config(ws), video)
    assert result["status"] == PASS and [r["delta_f"] for r in result["words"]] == [0, 0, 0, 1, 0]


def test_a_box_count_that_differs_from_the_word_count_is_uncertain_not_a_guess(good: Path) -> None:
    result = run(config(words(STARTS + [78], KEYWORDS)), good)
    assert result["status"] == UNCERTAIN and result["summary"]["uncertain"] == 5
    assert "layout not recognised" in result["failures"][0]


def test_a_recipe_too_loose_for_the_negative_control_is_uncertain(good: Path) -> None:
    recipe = copy.deepcopy(RECIPE)
    recipe["timing"]["plain_late_max_frames"] = 8  # a 5 f late picture would still pass
    result = run(config(words(STARTS, KEYWORDS)), good, recipe)
    assert result["control"]["detected"] is False and result["status"] == UNCERTAIN
    assert any("negative control" in f for f in result["failures"])


def test_words_inside_the_panel_fade_in_are_not_testable_and_are_listed(good: Path) -> None:
    cfg = config(words([14] + STARTS[1:], KEYWORDS))  # shot starts at -10: frame 14 is local 24 -> opaque; move shot start to 10
    cfg["dialogue"][0]["start_frame"] = 10
    result = run(cfg, good)
    first = result["words"][0]
    assert first["status"] == "n/a" and "fading in" in first["why"] and result["summary"]["n/a"] == 1


def test_a_shot_outside_the_file_is_not_applicable_and_a_clip_with_an_origin_still_passes(tmp_path: Path) -> None:
    first = 100
    starts = [s + first for s in STARTS]
    ws = words(starts, KEYWORDS)
    video = render(tmp_path / "clip.mp4", ws, lit_of(starts), lines=[4], first=first)
    cfg = config(ws, first)
    cfg["dialogue"].append({"id": "S99", "start_frame": 5000, "duration_frames": 100, "speech_end_in_window_s": 3.0,
                            "words": words([5030, 5040])})
    result = run(cfg, video, origin=first)
    assert result["status"] == PASS and result["summary"]["tested"] == 4 and result["summary"]["n/a"] == 2


def test_sample_every_keeps_words_after_a_pause(good: Path) -> None:
    recipe = copy.deepcopy(RECIPE)
    recipe["sample_every"] = 3
    recipe["timing"]["pause_min_frames"] = 8  # gaps are 6 f (endF = start + 6, next start +12): 6 f < 8, only the first follows a pause
    result = run(config(words(STARTS, KEYWORDS)), good, recipe)
    tested = [r["index"] for r in result["words"] if r["status"] == PASS]
    assert tested == [0, 3] and all("sample_every" in r["why"] for r in result["words"] if r["status"] == "n/a")


@pytest.mark.parametrize("first,start,late,early,expect", [
    (30, 30, 1, 0, PASS), (31, 30, 1, 0, PASS), (32, 30, 1, 0, "FAIL-late"), (29, 30, 1, 0, "FAIL-early"),
    (31, 30, 2, 0, PASS), (32, 30, 2, 0, PASS), (33, 30, 2, 0, "FAIL-late"), (None, 30, 1, 0, "FAIL-late"), (29, 30, 1, 1, PASS)])
def test_judge_table(first: int | None, start: int, late: int, early: int, expect: str) -> None:
    assert q1b.judge(first, start, late, early)[0] == expect


def test_is_lit_colours() -> None:
    c = RECIPE["classify"]
    solid = lambda rgb: np.full((10, 10, 3), rgb, np.uint8)  # noqa: E731
    assert q1b.is_lit(solid(MINT), False, c) and q1b.is_lit(solid(INK), False, c)
    assert not q1b.is_lit(solid(MUTED), False, c) and not q1b.is_lit(solid(PAPER), False, c)
    assert q1b.is_lit(solid(PINK), True, c) and not q1b.is_lit(solid(PALE), True, c)
    half = tuple(round((a + b) / 2) for a, b in zip(PALE, PINK))
    assert q1b.is_lit(solid(half), True, c)  # dt +1 of the 2 f ramp


def test_cli_exit_codes_and_report_file(good: Path, tmp_path: Path) -> None:
    cfg_ok, cfg_bad = tmp_path / "ok.json", tmp_path / "bad.json"
    cfg_ok.write_text(json.dumps(config(words(STARTS, KEYWORDS))), encoding="utf-8")
    cfg_bad.write_text(json.dumps(config(words([s + 5 for s in STARTS], KEYWORDS))), encoding="utf-8")
    out = tmp_path / "report.json"
    assert q1b.main(["--config", str(cfg_ok), "--video", str(good), "--ffmpeg", FFMPEG, "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == PASS
    assert q1b.main(["--config", str(cfg_bad), "--video", str(good), "--ffmpeg", FFMPEG]) == 1
    assert q1b.main(["--config", str(cfg_ok), "--video", str(tmp_path / "missing.mp4"), "--ffmpeg", FFMPEG]) == 2
