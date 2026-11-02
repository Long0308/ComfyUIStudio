"""Preflight transitions + icons on synthetic clips: the check refuses BEFORE a render, from source frames and files."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_qa_preflight_support import FFMPEG, config, pre, transitions_run
from test_qa_review_support import make_config, needs_ffmpeg, recipe, sha_of, write_png_rgb
from engine.core.errors import Uncertain
from engine.qa import preflight_icons
from engine.qa.gates import FAIL, PASS, UNCERTAIN
from engine.qa.review_model import build_model

pytestmark = needs_ffmpeg


def test_white_flash_between_same_framing_source_clips_is_refused(tmp_path: Path) -> None:
    result = transitions_run(config(tmp_path, seed_a=3, seed_b=3), tmp_path)
    row = result["rows"][0]
    assert result["status"] == FAIL and row["status"] == FAIL and row["source_ncc"] > 0.9
    assert "same-framing" in result["failures"][0] and row["type"] == "dip_white"


def test_white_flash_at_a_real_framing_change_passes(tmp_path: Path) -> None:
    result = transitions_run(config(tmp_path, seed_a=3, seed_b=4), tmp_path)
    assert result["status"] == PASS and result["rows"][0]["source_ncc"] < 0.25


def test_bloom_between_same_framing_pictures_is_refused_too(tmp_path: Path) -> None:
    result = transitions_run(config(tmp_path, seed_a=3, seed_b=3, kind="bloom", frames=6, start=27, end_exclusive=33), tmp_path)
    assert result["status"] == FAIL and result["rows"][0]["preset"] == "bloom"


def test_a_hard_cut_with_push_between_same_framing_clips_passes(tmp_path: Path) -> None:
    result = transitions_run(config(tmp_path, seed_a=3, seed_b=3, kind="push", frames=12, start=30, end_exclusive=42), tmp_path)
    assert result["status"] == PASS and "source_ncc" not in result["rows"][0]


def test_a_declared_non_change_refuses_without_reading_a_pixel(tmp_path: Path) -> None:
    cfg = config(tmp_path, seed_a=3, seed_b=4, layout_change=False)
    result = transitions_run(cfg, tmp_path)
    assert result["status"] == FAIL and result["rows"][0]["checked"] == ["declared"] and "source_ncc" not in result["rows"][0]
    cfg = config(tmp_path, seed_a=3, seed_b=4)
    assert transitions_run(cfg, tmp_path, declared_same=frozenset({30}))["status"] == FAIL


def test_missing_source_clip_is_uncertain_not_a_pass(tmp_path: Path) -> None:
    cfg = config(tmp_path, seed_a=3, seed_b=3)
    cfg["dialogue"][0]["segments"][0]["path"] = str(tmp_path / "gone.mp4")
    result = transitions_run(cfg, tmp_path)
    assert result["status"] == UNCERTAIN and "unreadable input" in result["failures"][0]


@pytest.mark.parametrize("kind,continuity,status", [("dissolve", "mismatch", FAIL), ("wipe", None, FAIL), ("dissolve", "agree", PASS),
                                                    ("cloud", "unknown", FAIL)])
def test_a_both_shots_type_next_to_a_picture_needs_continuity_agree(tmp_path: Path, kind, continuity, status) -> None:
    extra = {} if continuity is None else {"continuity": continuity}
    result = transitions_run(config(tmp_path, seed_a=3, seed_b=4, kind=kind, frames=10, start=25, end_exclusive=35, **extra), tmp_path)
    assert result["status"] == status
    if status == FAIL:
        assert "continuity" in result["failures"][0]


def test_unknown_transition_type_is_refused(tmp_path: Path) -> None:
    result = transitions_run(config(tmp_path, seed_a=3, seed_b=4, kind="sparkle_wipe"), tmp_path)
    assert result["status"] == FAIL and "unknown transition type" in result["failures"][0]


def test_a_graphic_boundary_is_not_a_framing_question(tmp_path: Path) -> None:
    cfg = config(tmp_path, seed_a=3, seed_b=3, kind="plate_in", frames=4, start=30, end_exclusive=34, **{"from": "CARD_12", "to": "END_PLATE"})
    result = transitions_run(cfg, tmp_path)
    assert result["status"] == PASS and result["rows"][0]["skipped"]


# ---- icons (file level) ----------------------------------------------------------------------
WARM, COLD = (225, 120, 80), (80, 125, 225)


def icon_world(tmp_path: Path, *, same_file: bool = False, cold=COLD, words: list[tuple[str, int]] | None = None):
    a = write_png_rgb(tmp_path / "warm.png", WARM)
    b = a if same_file else write_png_rgb(tmp_path / "cold.png", cold)
    events = [{"id": "IC01", "shot": "S01_A", "word": "warm", "icon_path": str(a), "icon_sha256": sha_of(a), "frame": 20},
              {"id": "IC02", "shot": "S01_A", "word": "cold", "icon_path": str(b), "icon_sha256": sha_of(b), "frame": 80}]
    spoken = words or [("warm", 20), ("cold?", 80)]
    cfg = make_config([], motion={"transitions": [{"boundary": 5, "type": "none", "frames": 0}], "icons": events},
                      outro_cards=[{"term": "Warm and Cold", "start_frame": 300, "duration_frames": 90}])
    cfg["dialogue"][0]["words"] = [{"w": w, "startF": f, "anchor": True} for w, f in spoken]
    return build_model(cfg, recipe())


def run_icons(model, tmp_path: Path, **kw) -> dict:
    return preflight_icons.run(model, recipe(), pre(), tmp_path, FFMPEG, **kw)


def test_distinct_warm_and_cold_files_pass(tmp_path: Path) -> None:
    result = run_icons(icon_world(tmp_path), tmp_path)
    assert result["status"] == PASS, result["failures"]
    assert result["pairs"][0]["delta_e_file"] > 30 and "screen" not in result["pairs"][0]


def test_the_same_png_for_warm_and_cold_is_refused(tmp_path: Path) -> None:
    result = run_icons(icon_world(tmp_path, same_file=True), tmp_path)
    assert result["status"] == FAIL and any("identical icon image" in f for f in result["failures"])


def test_two_nearly_equal_colours_are_not_distinct(tmp_path: Path) -> None:
    result = run_icons(icon_world(tmp_path, cold=(228, 122, 82)), tmp_path)
    assert result["status"] == FAIL and any("too similar" in f for f in result["failures"])


def test_a_spoken_term_without_an_icon_event_is_refused(tmp_path: Path) -> None:
    result = run_icons(icon_world(tmp_path, words=[("warm", 20), ("cold?", 80), ("yummy", 100)]), tmp_path)
    assert result["status"] == FAIL and any("'yummy'" in f and "no icon event" in f for f in result["failures"])


def test_icon_dir_is_the_fallback_for_a_missing_icon_path(tmp_path: Path) -> None:
    model = icon_world(tmp_path)
    moved = tmp_path / "icons"
    moved.mkdir()
    for name in ("warm.png", "cold.png"):
        (moved / name).write_bytes((tmp_path / name).read_bytes())
        (tmp_path / name).unlink()
    with pytest.raises(Uncertain):
        run_icons(model, tmp_path)
    assert run_icons(model, tmp_path, icons_dir=moved)["status"] == PASS


def test_two_different_words_may_not_share_one_image_unless_marked(tmp_path: Path) -> None:
    model = icon_world(tmp_path, words=[("warm", 20), ("cold?", 80)])
    events = tuple({**e, "word": "fresh" if e["id"] == "IC02" else e["word"]} for e in model.icons)
    shared = events[0]["icon_path"]
    events = tuple({**e, "icon_path": shared, "icon_sha256": events[0]["icon_sha256"]} for e in events)
    import dataclasses
    model = dataclasses.replace(model, icons=events, cards=(), words=({"shot": "S01_A", "text": "warm", "startF": 20, "anchor": True, "icon": None},
                                                            {"shot": "S01_A", "text": "fresh", "startF": 80, "anchor": True, "icon": None}))
    result = run_icons(model, tmp_path)
    assert result["status"] == FAIL and result["shared_icon_words"]
    marked = dataclasses.replace(model, icons=tuple({**e, "shared_icon": True} for e in model.icons))
    assert run_icons(marked, tmp_path)["status"] == PASS
