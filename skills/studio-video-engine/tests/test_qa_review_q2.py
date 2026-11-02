"""Q2 icons: coverage, hash binding, opposite pairs (file colours + the tile rendered on screen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_qa_review_support import (FFMPEG, H, W, make_config, needs_ffmpeg, np, recipe, scene, sha_of, write_png_rgb,
                                    write_video)
from engine.core.errors import Uncertain
from engine.qa.gates import FAIL, PASS, q2_icons
from engine.qa.review_model import build_model

WARM, COLD = (225, 120, 80), (80, 125, 225)
pytestmark = needs_ffmpeg


def film(tmp_path: Path, tiles: dict[int, tuple[int, int, int]], n: int = 140) -> Path:
    """Static ground; at each pop frame a disc of the given colour sits in the lower right for 30 frames."""
    frames = np.stack([scene(3)] * n)
    yy, xx = np.mgrid[:H, :W]
    disc = (yy - 126) ** 2 + (xx - 272) ** 2 <= 11 ** 2
    for pop, colour in tiles.items():
        for f in range(pop, min(pop + 30, n)):
            frames[f][disc] = colour
    return write_video(tmp_path / "film.mp4", frames)


def world(tmp_path: Path, *, warm=WARM, cold=COLD, shown_warm=WARM, shown_cold=COLD, off: int = 0, same_file: bool = False,
          draw: bool = True):
    a = write_png_rgb(tmp_path / "warm.png", warm)
    b = a if same_file else write_png_rgb(tmp_path / "cold.png", cold)
    events = [{"id": "IC01", "shot": "S01_A", "word": "warm", "term": "warm-cold", "icon_path": str(a), "icon_sha256": sha_of(a),
               "frame": 20 + off, "total_frames": 32},
              {"id": "IC02", "shot": "S01_A", "word": "cold", "term": "warm-cold", "icon_path": str(b), "icon_sha256": sha_of(b),
               "frame": 80, "total_frames": 32}]
    words = [{"w": "warm", "startF": 20, "anchor": True, "icon": "warm.png"},
             {"w": "cold?", "startF": 80, "anchor": True, "icon": "cold.png"}]
    config = make_config([], motion={"transitions": [{"boundary": 5, "type": "none", "frames": 0}], "icons": events},
                         outro_cards=[{"term": "Warm and Cold", "start_frame": 300, "duration_frames": 90}])
    config["dialogue"][0]["words"] = words
    video = film(tmp_path, {20 + off: shown_warm, 80: shown_cold} if draw else {})
    return build_model(config, recipe()), video


def run(model, video, tmp_path: Path, **kw):
    return q2_icons.run(model, recipe(), video, FFMPEG, tmp_path, (W, H), **kw)


def test_a_well_formed_cut_passes_and_measures_the_pair(tmp_path: Path) -> None:
    model, video = world(tmp_path)
    result = run(model, video, tmp_path)
    assert result["status"] == PASS, result["failures"]
    pair = result["pairs"][0]
    assert pair["delta_e_file"] > 30 and pair["screen"][0]["delta_e_screen"] > 30 and pair["hue_distance_deg"] > 100
    assert result["anchors_checked"] == 2 and not result["orphan_events"]


def test_the_same_image_for_both_words_fails(tmp_path: Path) -> None:
    model, video = world(tmp_path, same_file=True, shown_cold=WARM)
    result = run(model, video, tmp_path)
    assert result["status"] == FAIL
    assert any("identical icon image" in f for f in result["failures"])
    assert any("tiles on screen look the same" in f for f in result["failures"])


def test_different_files_but_the_same_tile_on_screen_fails(tmp_path: Path) -> None:
    model, video = world(tmp_path, shown_cold=WARM)
    result = run(model, video, tmp_path)
    assert result["status"] == FAIL and result["failures"] == [f for f in result["failures"] if "tiles on screen" in f]


def test_similar_file_colours_fail_even_when_the_files_differ(tmp_path: Path) -> None:
    near = (230, 125, 80)
    model, video = world(tmp_path, cold=near, shown_cold=near)
    failures = run(model, video, tmp_path)["failures"]
    assert any("too similar" in f for f in failures)


def test_an_icon_off_the_word_start_by_more_than_three_frames_fails(tmp_path: Path) -> None:
    for sub, off, expected in (("a", 0, PASS), ("b", 3, PASS), ("c", 5, FAIL)):  # 3 = exactly the tolerance
        folder = tmp_path / sub
        folder.mkdir()
        model, video = world(folder, off=off)
        result = run(model, video, folder)
        assert result["status"] == expected, (off, result["failures"])
    assert "+5 f away" in result["failures"][0]


def test_a_missing_event_and_an_uncovered_card_term_fail(tmp_path: Path) -> None:
    model, video = world(tmp_path)
    fewer = build_model({**make_config([]), "motion": {"transitions": [{"boundary": 5, "type": "none", "frames": 0}],
                                                       "icons": [dict(model.icons[0])]},
                        "dialogue": [{"id": "S01_A", "start_frame": 0, "end_frame_exclusive": 300, "segments": [],
                                      "words": [{"w": "warm", "startF": 20, "anchor": True},
                                                {"w": "cold", "startF": 80, "anchor": True}]}],
                        "outro_cards": [{"term": "Warm and Cold", "start_frame": 300, "duration_frames": 90}]}, recipe())
    failures = run(fewer, video, tmp_path)["failures"]
    assert any("'cold" in f and "no icon event" in f for f in failures)
    assert any("vocabulary term 'Cold'" in f and "no icon event" in f for f in failures)


def test_a_file_that_does_not_hash_to_the_event_fails_and_a_missing_file_is_uncertain(tmp_path: Path) -> None:
    model, video = world(tmp_path)
    model.icons[0]["icon_sha256"] = "0" * 64
    assert any("sha256 on disk differs" in f for f in run(model, video, tmp_path)["failures"])
    model.icons[0]["icon_path"] = str(tmp_path / "gone.png")
    with pytest.raises(Uncertain):
        run(model, video, tmp_path)


def test_an_icon_that_never_appears_on_screen_fails(tmp_path: Path) -> None:
    model, video = world(tmp_path, draw=False)
    assert any("not visible at pop+9" in f for f in run(model, video, tmp_path)["failures"])


def test_a_clip_with_an_origin_uses_global_event_frames(tmp_path: Path) -> None:
    model, video = world(tmp_path)
    clip = tmp_path / "clip.mp4"
    import subprocess
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{10 / 30:.6f}", "-i", str(video), "-frames:v", "90", "-c:v", "libx264",
                    "-crf", "6", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip)], check=True)
    result = run(model, clip, tmp_path, origin=10)
    assert result["status"] == PASS and result["pairs"][0]["screen"][0]["delta_e_screen"] > 30


def test_colour_helpers() -> None:
    assert q2_icons.delta_e(WARM, WARM) == 0 and q2_icons.delta_e(WARM, COLD) > 40
    assert q2_icons.hue_distance(350, 10) == pytest.approx(20)
    assert q2_icons.stem("Cows,") == "cow" and q2_icons.tokens("Dairy Cow") == {"dairy", "cow"}


def test_config_can_add_pairs_but_not_loosen_thresholds() -> None:
    from engine.core.errors import Refused
    from engine.qa.review_recipe import effective_recipe
    merged, sources = effective_recipe(recipe(), {"qa": {"review": {"opposite_pairs": [["big", "small"], ["warm", "cold"]],
                                                                   "q2_icons": {"min_delta_e_file": 20}}}})
    assert merged["q2_icons"]["min_delta_e_file"] == 20 and ["big", "small"] in merged["q2_icons"]["opposite_pairs"]
    assert sum(1 for p in merged["q2_icons"]["opposite_pairs"] if sorted(p) == ["cold", "warm"]) == 1
    for bad in ({"q2_icons": {"min_delta_e_file": 1}}, {"q2_icons": {"frame_tolerance": 9}}, {"q2_icons": {"nope": 1}},
                {"q9": {}}, {"q3_flash": {"spike_excess_min": float("nan")}}):
        with pytest.raises(Refused):
            effective_recipe(recipe(), {"qa": {"review": bad}})
