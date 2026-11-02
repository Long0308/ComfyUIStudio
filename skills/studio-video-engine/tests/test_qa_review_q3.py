"""Q3 flash scan on synthetic films (numpy arrays, no ffmpeg)."""

from __future__ import annotations

import pytest

from test_qa_review_support import FPS, gray_of, make_config, np, recipe, scene, transition
from engine.qa.gates import FAIL, PASS, q3_flash
from engine.qa.review_model import build_model
from engine.qa.review_recipe import normalise_type

WHITE = [0.15, 0.5, 0.85, 1.0, 0.62, 0.35, 0.15, 0.04]


def film(*, second: "np.ndarray | None" = None, flash_at: int | None = None, n: int = 200, cut: int = 100,
         gain: float = 1.0) -> "np.ndarray":
    """Shot A then shot B (switch at ``cut``); optionally the 8-frame white dip starting at ``flash_at``."""
    a, b = scene(1), scene(2) if second is None else second
    frames = np.stack([(a if i < cut else (b * gain).clip(0, 255).astype(np.uint8)) for i in range(n)]).astype(np.float64)
    if flash_at is not None:
        for k, white in enumerate(WHITE):
            frames[flash_at + k] = frames[flash_at + k] * (1 - white) + 255 * white
    return gray_of(frames)


def run(frames, rows, **kw):
    model = build_model(make_config(rows), recipe())
    return q3_flash.run(model, frames, recipe(), **kw)


def dip_row(kind: str = "dip") -> dict:
    return transition(100, kind, 8, start=96)


def test_deviation_ignores_ramps_and_finds_a_flash() -> None:
    luma = np.linspace(100, 160, 100)
    assert q3_flash.spike_deviation(luma, 8).max() < 10
    luma[50] = 250.0
    dev = q3_flash.spike_deviation(luma, 8)
    assert dev.argmax() == 50 and dev[50] > 80


def test_a_white_dip_between_different_layouts_passes() -> None:
    result = run(film(flash_at=96), [dip_row()])
    row = result["boundaries"][0]
    assert result["status"] == PASS and row["spike_frames"] and row["same_framing_ncc"] < 0.35


def test_a_white_dip_between_same_framing_shots_fails_with_the_frame_list() -> None:
    same = np.roll(scene(1), 2, axis=1)  # same seat, only a small shift
    result = run(film(second=same, flash_at=96), [dip_row()])
    row = result["boundaries"][0]
    assert result["status"] == FAIL and row["status"] == FAIL
    assert "same-framing" in row["reasons"][0] and str(row["spike_frames"][0]) in row["reasons"][0]
    assert result["failures"][0].startswith("T100:")


def test_a_declared_non_change_beats_a_favourable_measurement() -> None:
    frames = film(flash_at=96)
    assert run(frames, [dip_row()])["status"] == PASS
    assert run(frames, [dip_row()], layout_declared_false=frozenset({100}))["status"] == FAIL
    row = dip_row()
    row["layout_change"] = False
    assert run(frames, [row])["status"] == FAIL
    row["layout_change"] = True  # a declared change can never excuse a measured same-framing pair
    same = np.roll(scene(1), 2, axis=1)
    assert run(film(second=same, flash_at=96), [row])["status"] == FAIL


@pytest.mark.parametrize("kind", ["push", "cut", "none", "iris", "dissolve", "card-slide"])
def test_a_flash_at_a_non_flash_boundary_fails(kind: str) -> None:
    result = run(film(flash_at=96), [transition(100, kind, 8 if kind != "none" else 0, start=96)])
    assert result["status"] == FAIL and "luma spike" in result["boundaries"][0]["reasons"][0]


def test_a_whip_or_bloom_may_flash_without_a_layout_rule() -> None:
    for kind in ("whip", "bloom"):
        assert run(film(flash_at=96), [transition(100, kind, 8, start=96)])["status"] == PASS


def test_a_spike_outside_every_boundary_fails() -> None:
    result = run(film(flash_at=20), [dip_row()])
    assert result["status"] == FAIL and result["stray_spike_frames"] and "outside every boundary" in result["failures"][-1]


def test_a_big_luma_step_at_a_hard_cut_fails_but_a_small_one_passes() -> None:
    row = [transition(100, "push", 12, start=100)]
    assert run(film(gain=1.0), row)["status"] == PASS
    brighter = film(second=np.full_like(scene(2), 235), gain=1.0)  # B much brighter than A
    result = run(brighter, row)
    assert result["status"] == FAIL and "luma step" in result["boundaries"][0]["reasons"][0]


def test_a_clip_with_an_origin_is_judged_in_global_frames_and_other_boundaries_are_skipped() -> None:
    frames = film(flash_at=96)[60:150]
    rows = [dip_row(), transition(500, "none", 0)]
    result = run(frames, rows, origin=60)
    assert [b["id"] for b in result["boundaries"]] == ["T100"] and result["status"] == PASS
    assert result["boundaries"][0]["spike_frames"][0] >= 97  # global numbering


def test_boundaries_whose_window_starts_before_the_file_are_not_judged() -> None:
    frames = film(flash_at=96)[97:130]
    assert run(frames, [dip_row()], origin=97)["boundaries"] == []


def test_type_names_are_normalised() -> None:
    r = recipe()
    assert [normalise_type(t, r) for t in ("dip", "Dip-White", "push", "card-slide", "plate-in", None, "iris")] == \
        ["dip_white", "dip_white", "cut_push", "card_slide", "plate_in", "none", "iris"]
    assert FPS == 30
