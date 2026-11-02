"""Dò seed box tự động phải fail-closed: có dấu => tìm đúng bbox; không dấu / hai dấu / sai màu / lệch frame => từ chối có tên."""
from __future__ import annotations

import numpy as np
import pytest

from engine.core.errors import Refused
from engine.post.logo import detect as detect_mod
from engine.post.logo.policy import detect_config

SIZE = 256
BG = (210, 205, 200)          # BGR: light fabric
MARK_RGB = (50, 55, 103)      # declared thread colour (navy); BGR below
ICON_ASPECT = 0.84
RECT_A = (100, 110, 20, 26)   # x, y, w, h of the drawn mark (aspect 0.77)
RECT_B = (170, 60, 20, 26)


def config(**changes) -> dict:
    cfg = {"search_region": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "mark_height_frac": {"min": 0.06, "max": 0.16},
           "aspect_tolerance": 0.4, "mark_rgb": list(MARK_RGB), "dark_threshold": 50, "fill_range": [0.2, 0.95],
           "color_min_similarity": 0.5, "box_pad_frac": 0.2, "search_frames": 6, "min_score": 0.15,
           "min_margin": 0.05, "min_agreement": 0.5}
    cfg.update(changes)
    return detect_config(cfg)


def frame(marks: list[tuple[int, int, int, int]], colour_rgb=MARK_RGB, hollow: int = 6, bg=BG) -> np.ndarray:
    img = np.empty((SIZE, SIZE, 3), dtype=np.uint8)
    img[...] = bg
    bgr = tuple(int(v) for v in colour_rgb[::-1])
    for x, y, w, h in marks:
        img[y:y + h, x:x + w] = bgr
        if hollow:
            img[y + hollow:y + h - hollow, x + hollow:x + w - hollow] = bg  # embroidered mark has a hollow centre
    return img


def test_single_mark_is_found_with_its_exact_bbox_and_padded_box() -> None:
    frames = [frame([RECT_A])] * 4
    found = detect_mod.detect_seed(frames, config(), ICON_ASPECT)
    assert found.rect == RECT_A
    pad = round(0.2 * RECT_A[3])
    assert found.box == (RECT_A[0] - pad, RECT_A[1] - pad, RECT_A[2] + 2 * pad, RECT_A[3] + 2 * pad)
    assert found.score > 0.4 and found.margin == pytest.approx(found.score) and found.agreement == 1.0
    assert found.as_dict()["per_frame"][0]["best"]["rect_xywh"] == list(RECT_A)


def test_absent_mark_refuses_not_found() -> None:
    with pytest.raises(detect_mod.SeedBoxError) as caught:
        detect_mod.detect_seed([frame([])] * 3, config(), ICON_ASPECT)
    assert caught.value.code == detect_mod.NOT_FOUND and isinstance(caught.value, Refused)
    assert "--seed-box" in str(caught.value)


def test_two_equal_marks_refuse_ambiguous() -> None:
    with pytest.raises(detect_mod.SeedBoxError) as caught:
        detect_mod.detect_seed([frame([RECT_A, RECT_B])] * 3, config(), ICON_ASPECT)
    assert caught.value.code == detect_mod.AMBIGUOUS
    assert caught.value.details["margin"] == pytest.approx(0.0, abs=1e-6)


def test_wrong_colour_mark_is_gated_out() -> None:
    reddish = frame([RECT_A], colour_rgb=(120, 40, 40))
    with pytest.raises(detect_mod.SeedBoxError) as caught:
        detect_mod.detect_seed([reddish] * 3, config(), ICON_ASPECT)
    assert caught.value.code == detect_mod.NOT_FOUND
    neutral_cfg = config(mark_rgb=[60, 60, 60])  # near-grey declared colour: chroma gate is off
    assert detect_mod.detect_seed([reddish] * 3, neutral_cfg, ICON_ASPECT).rect == RECT_A


def test_faint_mark_is_rejected_by_the_dark_threshold() -> None:
    faint = frame([RECT_A], colour_rgb=(170, 172, 190))  # black-hat response ~30 < dark_threshold 50: no candidate
    with pytest.raises(detect_mod.SeedBoxError) as caught:
        detect_mod.detect_seed([faint] * 3, config(), ICON_ASPECT)
    assert caught.value.code == detect_mod.NOT_FOUND and "no candidate" in str(caught.value)


def test_mark_on_a_dim_surround_scores_below_min_score() -> None:
    dim = frame([RECT_A], bg=(130, 128, 125))  # candidate passes the gates, but contrast x ring brightness < 0.15
    with pytest.raises(detect_mod.SeedBoxError) as caught:
        detect_mod.detect_seed([dim] * 3, config(), ICON_ASPECT)
    assert caught.value.code == detect_mod.NOT_FOUND and "min_score" in str(caught.value)
    assert 0 < caught.value.details["best"]["score"] < 0.15
    assert detect_mod.detect_seed([dim] * 3, config(min_score=0.05), ICON_ASPECT).rect == RECT_A


def test_mark_jumping_between_frames_fails_agreement() -> None:
    frames = [frame([RECT_A]) if i % 2 == 0 else frame([RECT_B]) for i in range(4)]
    assert detect_mod.detect_seed(frames, config(min_agreement=0.5), ICON_ASPECT).agreement == 0.5
    with pytest.raises(detect_mod.SeedBoxError) as caught:
        detect_mod.detect_seed(frames, config(min_agreement=0.75), ICON_ASPECT)
    assert caught.value.code == detect_mod.AMBIGUOUS and "agree" in str(caught.value)


def test_search_region_excludes_a_mark_outside_it() -> None:
    cfg = config(search_region={"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0})  # left half only
    assert detect_mod.detect_seed([frame([RECT_A])] * 2, cfg, ICON_ASPECT).rect == RECT_A
    with pytest.raises(detect_mod.SeedBoxError) as caught:
        detect_mod.detect_seed([frame([RECT_B])] * 2, cfg, ICON_ASPECT)  # x=170 is in the right half
    assert caught.value.code == detect_mod.NOT_FOUND


def test_iou_helper() -> None:
    assert detect_mod.iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert detect_mod.iou((0, 0, 10, 10), (5, 0, 10, 10)) == pytest.approx(50 / 150)
    assert detect_mod.iou((0, 0, 10, 10), (20, 20, 5, 5)) == 0.0
