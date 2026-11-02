"""Q4 transition ghost: contact sheets for every window, numeric double-exposure proxy for picture pairs."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from test_qa_review_support import FFMPEG, H, W, gray_of, make_config, needs_ffmpeg, np, recipe, scene, transition, write_video
from engine.qa import review_media as media
from engine.qa.gates import FAIL, PASS, UNCERTAIN, q4_ghost
from engine.qa.review_model import build_model

pytestmark = needs_ffmpeg


def frames_with(mix: list[float], start: int = 60, n: int = 120) -> "np.ndarray":
    """Shot A, then B; frames ``start..`` show ``(1 - w) * A + w * B`` for each weight in ``mix``."""
    a, b = scene(1).astype(np.float64), scene(2).astype(np.float64)
    out = [(a if i < start else b) for i in range(n)]
    for k, w in enumerate(mix):
        out[start + k] = a * (1 - w) + b * w
    return np.stack(out).round().astype(np.uint8)


def run(tmp_path: Path, frames, row: dict, rec: dict | None = None, **kw):
    video = write_video(tmp_path / "v.mp4", frames)
    model = build_model(make_config([row]), recipe())
    gray = media.decode_gray(video, FFMPEG, W, H)
    return q4_ghost.run(model, gray, video, FFMPEG, rec or recipe(), tmp_path / "sheets", (W, H), **kw)


def row(kind: str, frames: int = 8, **extra) -> dict:
    return transition(60, kind, frames, start=60, **extra)


def test_a_hard_cut_is_clean_and_writes_a_full_resolution_sheet(tmp_path: Path) -> None:
    result = run(tmp_path, frames_with([]), row("cut_push"))
    window = result["windows"][0]
    assert result["status"] == PASS and window["ghost_excess"] < 0.05
    sheet = window["sheet"]
    assert Path(sheet["path"]).is_file() and sheet["tile_size"] == [W, H] and sheet["tiles"][0] == 59 and sheet["tiles"][-1] == 68
    size = subprocess.run([media.find_ffprobe(FFMPEG), "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                           sheet["path"]], capture_output=True, text=True).stdout.strip()
    rows = -(-len(sheet["tiles"]) // sheet["columns"])
    assert size == f"{W * sheet['columns']},{H * rows}"  # native tiles, nothing scaled down
    assert len(sheet["sha256"]) == 64 and result["sheets"] == [sheet["path"]]


def test_a_cross_dissolve_between_two_shots_is_a_double_exposure(tmp_path: Path) -> None:
    mix = [(i + 1) / 9 for i in range(8)]
    result = run(tmp_path, frames_with(mix), row("dissolve", continuity="agree"))
    window = result["windows"][0]
    assert result["status"] == FAIL and window["ghost_excess"] >= 0.15
    assert "double exposure" in window["reasons"][0]


def test_a_two_shot_type_needs_agreeing_continuity(tmp_path: Path) -> None:
    mix = [(i + 1) / 9 for i in range(8)]
    result = run(tmp_path, frames_with(mix), row("cloud", continuity="mismatch"))
    assert any("two-shot type 'cloud'" in r for r in result["windows"][0]["reasons"])
    (tmp_path / "b").mkdir()
    clean = run(tmp_path / "b", frames_with([]), row("cloud", continuity="unknown"))  # no ghost, but not 'agree'
    assert clean["status"] == FAIL and "not the same framing" in clean["windows"][0]["reasons"][0]


def test_a_faint_ghost_is_uncertain_and_the_thresholds_are_the_recipes(tmp_path: Path) -> None:
    rec = recipe()
    rec["q4_ghost"].update(ghost_warn=0.02, ghost_fail=0.95)
    result = run(tmp_path, frames_with([0.5, 0.5, 0.5]), row("whip", 3), rec)
    assert result["status"] == UNCERTAIN and "critic must look" in result["windows"][0]["reasons"][0]


def test_graphic_windows_get_a_sheet_but_no_proxy(tmp_path: Path) -> None:
    r = row("plate_in", 4)
    r.update({"from": "CARD_Creamy", "to": "END_PLATE"})
    window = run(tmp_path, frames_with([]), r)["windows"][0]
    assert window["kind"] == "graphic" and window["sheet"] and "ghost_excess" not in window


def test_zero_frame_carries_get_no_window_and_sheets_use_the_window_frames(tmp_path: Path) -> None:
    assert run(tmp_path, frames_with([]), transition(60, "none", 0))["windows"] == []
    assert q4_ghost.sheet_frames(59, 60, 62, 62, 8) == [59, 60, 61, 62]
    long = q4_ghost.sheet_frames(2115, 2116, 2236, 2236, 8)
    assert len(long) == 8 and long[0] == 2115 and long[-1] == 2236


def test_a_clip_with_an_origin_numbers_the_sheet_tiles_globally(tmp_path: Path) -> None:
    result = run(tmp_path, frames_with([])[40:100], row("cut_push"), origin=40)
    assert result["windows"][0]["sheet"]["tiles"][0] == 59
    assert result["status"] == PASS


def test_edge_and_mirror_helpers() -> None:
    half = np.random.default_rng(5).random((12, 10))
    assert q4_ghost.mirror_ncc(np.hstack([half, half[:, ::-1]])) == pytest.approx(1.0)
    edges = q4_ghost.edge_map(gray_of(scene(4)[None])[0], 4)
    assert edges.shape == (44, 79) and q4_ghost.mirror_ncc(edges) < 0.6
