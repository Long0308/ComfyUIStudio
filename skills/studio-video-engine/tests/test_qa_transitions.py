"""``jjv qa transitions`` (T-E34): synthetic dips / dissolves / cuts (every rule has a red case and a green case),
the pinned ep04 negative controls (v012 same-seat flashes, v005 double exposure) and the retained v015 positive control."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from test_qa_review_support import (EP, FFMPEG, FFPROBE, FPS, RECIPE_SHA, H, W, ep_config, make_config, needs_ep, needs_ffmpeg, np,
                                    recipe, review_clip, scene, transition, write_video)
from engine.qa import cli as qa_cli, review_media, transitions_cli, transitions_load, transitions_run
from engine.qa.gates import FAIL, PASS, UNCERTAIN

pytestmark = [needs_ffmpeg]
SCHEDULE = [(-2, "out", 0.15), (-1, "out", 0.5), (0, "out_tail", 0.85), (1, "none", 1.0), (2, "in", 0.62), (3, "in", 0.35),
            (4, "in", 0.15), (5, "in", 0.04)]  # preset dip_white (v010)
WHITE = np.full((H, W, 3), 255.0)


def film(a: "np.ndarray", b: "np.ndarray", boundary: int = 50, total: int = 100, dip: bool = False, **over) -> "np.ndarray":
    frames = [a if f < boundary else b for f in range(total)]
    if dip:
        for t, shot, white in SCHEDULE:
            base = a if shot.startswith("out") or shot == "none" else b
            frames[boundary + t] = (base * (1 - white) + WHITE * white).astype(np.uint8)
    return np.stack(frames)


def judge(tmp_path: Path, config: dict, video: Path, *, timing: dict | None = None, origin: int = 0, declared=frozenset()) -> dict:
    rows, kind, rec = transitions_load.load_rows(config, recipe())
    info = review_media.probe(video, FFPROBE)
    return transitions_run.run_transitions(
        rows=rows, recipe=rec, video=video, ffmpeg=FFMPEG, native=(info.width, info.height), origin=origin,
        spoken=transitions_load.spoken_index(timing, config if kind == "review-config" else None, float(FPS)),
        declared=declared, out_dir=tmp_path / "out")


def dip_config(first_word: int | None, **row) -> dict:
    config = make_config([transition(50, "dip_white", 8, start=48, continuity="mismatch", **row)])
    config["dialogue"][1]["words"] = [] if first_word is None else [{"w": "Hi", "startF": first_word, "endF": first_word + 5}]
    return config


@pytest.fixture(scope="module")
def two_scenes(tmp_path_factory) -> tuple["np.ndarray", "np.ndarray"]:
    return scene(1), scene(2)


def test_dip_peak_clear_of_the_first_spoken_frame_passes(tmp_path: Path, two_scenes) -> None:
    video = write_video(tmp_path / "v.mp4", film(*two_scenes, dip=True))
    gate = judge(tmp_path, dip_config(60), video)
    row = gate["rows"][0]
    dip = row["checks"]["dip"]
    assert gate["status"] == PASS, gate["failures"]
    assert dip["scheduled_peak_frames"] == [51] and dip["measured_peak_frame"] == 51 and dip["margin_frames"] == 9
    assert row["checks"]["same_seat"]["same_seat"] is False and Path(tmp_path / "out" / row["sheet"]["file"]).is_file()


@pytest.mark.parametrize("first_word", [51, 49])
def test_dip_peak_overlapping_the_first_spoken_frame_is_refused(tmp_path: Path, two_scenes, first_word: int) -> None:
    video = write_video(tmp_path / "v.mp4", film(*two_scenes, dip=True))
    gate = judge(tmp_path, dip_config(first_word), video)
    assert gate["status"] == FAIL and gate["rows"][0]["checks"]["dip"]["margin_frames"] == first_word - 51
    assert any("overlaps the first spoken frame" in f for f in gate["failures"])


def test_the_word_timing_beats_the_config_words(tmp_path: Path, two_scenes) -> None:
    video = write_video(tmp_path / "v.mp4", film(*two_scenes, dip=True))
    timing = {"fps": FPS, "entries": [{"id": "S01_B", "start_frame": 50, "words": [{"text": "Hi", "start_s": 0.1, "start_frame": 53}]}]}
    gate = judge(tmp_path, dip_config(70), video, timing=timing)
    dip = gate["rows"][0]["checks"]["dip"]
    assert gate["status"] == PASS and dip["first_spoken_frame"] == 53 and dip["first_spoken_source"] == "word timing"
    assert dip["margin_frames"] == 2 and dip["bright_reach_last_frame"] >= 53  # speech starts while the overlay still fades: recorded


def test_dip_without_any_timing_is_uncertain_and_a_silent_line_passes(tmp_path: Path, two_scenes) -> None:
    video = write_video(tmp_path / "v.mp4", film(*two_scenes, dip=True))
    config = dip_config(None)
    assert judge(tmp_path, config, video)["status"] == PASS  # the line is declared with no words: nothing to protect
    del config["dialogue"][1]
    assert judge(tmp_path / "b", config, video)["status"] == UNCERTAIN


def test_dip_between_same_seat_shots_fails_measured_and_declared(tmp_path: Path) -> None:
    same = scene(3)
    video = write_video(tmp_path / "v.mp4", film(same, same, dip=True))
    gate = judge(tmp_path, dip_config(70), video)
    seat = gate["rows"][0]["checks"]["same_seat"]
    assert gate["status"] == FAIL and seat["same_seat"] and seat["ncc"] > 0.9 and seat["declared"] == []
    # a declaration also fails a pair that measures as a layout change, but never the other way round
    differ = write_video(tmp_path / "w.mp4", film(scene(1), scene(2), dip=True))
    declared = judge(tmp_path / "d", dip_config(70, framing="same_framing"), differ)
    assert declared["status"] == FAIL and declared["rows"][0]["checks"]["same_seat"]["declared"] == ["framing: same_framing"]
    assert judge(tmp_path / "e", dip_config(70), differ, declared=frozenset({50}))["status"] == FAIL
    assert judge(tmp_path / "f", dip_config(70, framing="new_framing"), video)["status"] == FAIL


def test_cut_and_cut_push_at_the_same_seat_pass(tmp_path: Path) -> None:
    same = scene(3)
    video = write_video(tmp_path / "v.mp4", film(same, same))
    for kind, frames in (("cut", 0), ("cut_push", 12)):
        config = make_config([transition(50, kind, frames, start=50)])
        gate = judge(tmp_path / kind, config, video)
        assert gate["status"] == PASS and gate["rows"][0]["checks"]["same_seat"]["same_seat"], gate["failures"]


def test_dissolve_blend_needs_continuity_agree_and_a_one_shot_type_may_not_ghost(tmp_path: Path, two_scenes) -> None:
    a, b = two_scenes
    frames = film(a, b)
    for k in range(12):  # a cross-dissolve over 50..61: both pictures in every frame
        frames[50 + k] = (a * (1 - (k + 1) / 13) + b * ((k + 1) / 13)).astype(np.uint8)
    video = write_video(tmp_path / "v.mp4", frames)
    refused = judge(tmp_path, make_config([transition(50, "dissolve", 12, continuity="mismatch")]), video)
    assert refused["status"] == FAIL and any("continuity" in f for f in refused["failures"])
    allowed = judge(tmp_path / "ok", make_config([transition(50, "dissolve", 12, continuity="agree")]), video)
    ghost = allowed["rows"][0]["checks"]["ghost"]
    assert allowed["status"] == PASS and ghost["shows_both_by_design"] and ghost["ghost_excess"] >= 0.15
    # the same pixels under a preset that must show ONE shot per frame are a double exposure
    one_shot = judge(tmp_path / "one", make_config([transition(50, "cut_push", 12, continuity="agree")]), video)
    assert one_shot["status"] == FAIL and any("double exposure" in f for f in one_shot["failures"])


def test_a_flash_hidden_in_a_hard_cut_fails_the_luma_step(tmp_path: Path, two_scenes) -> None:
    frames = film(*two_scenes)
    frames[50] = 255
    video = write_video(tmp_path / "v.mp4", frames)
    gate = judge(tmp_path, make_config([transition(50, "cut", 0, start=50)]), video)
    assert gate["status"] == FAIL and any("luma step" in f for f in gate["failures"])


def test_windows_outside_the_file_are_skipped_and_all_skipped_is_uncertain(tmp_path: Path, two_scenes) -> None:
    video = write_video(tmp_path / "v.mp4", film(*two_scenes))
    config = make_config([transition(50, "cut", 0, start=50), transition(500, "cut", 0, start=500)])
    gate = judge(tmp_path, config, video)
    assert gate["counts"] == {"boundaries": 2, "judged": 1, "skipped": 1, "fail": 0, "uncertain": 0}
    with pytest.raises(Exception, match="nothing could be measured"):
        judge(tmp_path / "x", config, video, origin=1000)


def test_boundaries_json_rows_resolve_through_the_preset_catalog() -> None:
    document = {"schema": "jjv/boundaries/v1", "boundaries": [
        {"frame": 1010, "from_shot": "S03_B", "to_shot": "S04_A", "class": "cut", "type": "dip_white", "frames": 9,
         "continuity": "mismatch", "motivation": "x"},
        {"frame": 1310, "from_shot": "S04_B", "to_shot": "S05_A", "class": "cut", "type": "dip_white", "continuity": "mismatch",
         "motivation": "x", "framing": "same_framing"}]}
    rows, kind, _rec = transitions_load.load_rows(document, recipe())
    legacy, approved = rows
    assert kind == "boundaries" and legacy.preset == "dip_white_legacy" and (legacy.t.start, legacy.t.end_exclusive) == (1009, 1018)
    assert transitions_run._peak_frames(legacy) == [1013] and transitions_run._peak_frames(approved) == [1311]
    assert approved.t.layout_change is False and approved.framing == "same_framing"
    for bad in ({"schema": "jjv/boundaries/v1", "boundaries": [{"from_shot": "a", "to_shot": "b"}]}, {"x": 1}, []):
        with pytest.raises(Exception):
            transitions_load.load_rows(bad, recipe())


def test_the_verb_is_registered_on_the_qa_parser() -> None:
    parser = argparse.ArgumentParser()
    qa_cli.register_cli(parser.add_subparsers(dest="stage"))
    args = parser.parse_args(["qa", "transitions", "--episode", "E", "--video", "v.mp4", "--boundaries", "b.json", "--timing", "t.json",
                              "--out", "o"])
    assert (args.stage, args.verb, args.boundaries, args.timing, args.out) == ("qa", "transitions", "b.json", "t.json", "o")
    with pytest.raises(SystemExit):
        parser.parse_args(["qa", "transitions", "--video", "v.mp4"])


# ---- pinned ep04 negative controls (bundled, hash-checked) -----------------------------------------------------------
@pytest.mark.parametrize("first,boundary", [(1290, "T1310"), (995, "T1010")])
def test_v012_same_seat_white_flash_windows_fail(tmp_path: Path, first: int, boundary: str) -> None:
    gate = judge(tmp_path, ep_config("012"), review_clip("012", tmp_path, first, 60), origin=first)
    row = next(r for r in gate["rows"] if r["status"] != "SKIPPED")
    assert gate["status"] == FAIL and row["id"] == boundary and row["type"] == "dip_white"
    seat = row["checks"]["same_seat"]
    assert seat["status"] == FAIL and seat["ncc"] >= 0.35 and "same seat" in row["reasons"][0]
    assert row["checks"]["dip"]["status"] == PASS  # the peak itself clears the speech: it is the SEAT that is wrong


def test_v005_dissolve_double_exposure_fails_with_the_measured_ghost(tmp_path: Path) -> None:
    gate = judge(tmp_path, ep_config("005"), review_clip("005", tmp_path, 1295, 40), origin=1295)
    row = next(r for r in gate["rows"] if r["status"] != "SKIPPED")
    assert gate["status"] == FAIL and row["id"] == "T1310" and row["type"] == "dissolve"
    assert row["checks"]["ghost"]["ghost_excess"] >= 0.15 and any("double exposure" in r for r in row["reasons"])
    assert Path(tmp_path / "out" / row["sheet"]["file"]).is_file()


@needs_ep
def test_cli_writes_a_stamped_receipt_and_exits_1_on_a_negative_control(tmp_path: Path, capsys) -> None:
    episode = EP.parent / "engine" / "episode.json"
    video = review_clip("012", tmp_path, 995, 60)
    from test_qa_review_support import review_config_path
    code = transitions_cli.main(["--episode", str(episode), "--video", str(video), "--boundaries", str(review_config_path("012")),
                                 "--frame-origin", "995", "--out", str(tmp_path / "cli"), "--json"])
    printed = json.loads(capsys.readouterr().out)
    written = json.loads((tmp_path / "cli" / "transitions-receipt.json").read_text(encoding="utf-8"))
    assert code == 1 and printed == written and printed["verdict"] == FAIL and printed["recipe"]["sha256"] == RECIPE_SHA
    assert printed["schema"] == "jjv/qa-transitions-receipt/v1" and "engine_tree_sha256" in printed
    assert printed["video"]["sha256"] and printed["boundaries"]["kind"] == "review-config"


# ---- retained shipped export (positive control) ----------------------------------------------------------------------
@needs_ep
def test_shipped_v015_clip_around_the_dip_passes_with_measured_numbers(tmp_path: Path) -> None:
    from test_qa_review_support import ep_video, cut_clip
    clip = cut_clip(ep_video("015"), tmp_path / "v015.mp4", 1590, 60)
    config = json.loads((EP / "review-hd-v015" / "config" / "review-config-v015.json").read_text(encoding="utf-8"))
    timing = json.loads((EP / "word-timing-v004" / "WORD-TIMING-v004.json").read_text(encoding="utf-8"))
    gate = judge(tmp_path, config, clip, timing=timing, origin=1590)
    row = next(r for r in gate["rows"] if r["status"] != "SKIPPED")
    assert gate["status"] == PASS, gate["failures"]
    assert row["id"] == "T1610" and row["checks"]["dip"]["margin_frames"] == 1643 - 1611
    assert row["checks"]["same_seat"]["ncc"] < 0.35 and row["checks"]["ghost"]["ghost_excess"] < 0.09


# ---- T-E34-f: no silent PASS when the evidence is incomplete -----------------------------------------------------------
def _row(config: dict):
    rows, _kind, rec = transitions_load.load_rows(config, recipe())
    return rows[0], rec


def _got(frames: "np.ndarray", drop: tuple[int, ...] = ()) -> dict:
    return {f: frames[f] for f in range(len(frames)) if f not in drop}


def test_long_window_double_exposure_is_judged_not_subsampled(tmp_path: Path, two_scenes) -> None:
    a, b = two_scenes
    frames = film(a, b, boundary=30, total=120)
    for k in range(60):  # 30..89: 60 frames > the old 48-frame cap: a double exposure all the way
        frames[30 + k] = (a * (1 - (k + 1) / 61) + b * ((k + 1) / 61)).astype(np.uint8)
    video = write_video(tmp_path / "v.mp4", frames)
    gate = judge(tmp_path, make_config([transition(30, "cut_push", 60, continuity="agree")]), video)
    ghost = gate["rows"][0]["checks"]["ghost"]
    assert gate["status"] == FAIL and ghost["ghost_excess"] >= 0.15 and any("double exposure" in f for f in gate["failures"])


def test_incomplete_window_records_an_uncertain_ghost_check_with_the_missing_frames(tmp_path: Path, two_scenes) -> None:
    frames = film(*two_scenes)
    row, rec = _row(make_config([transition(50, "cut_push", 12, start=50)]))
    result = transitions_run.judge_row(row, _got(frames, drop=(55,)), (W, H), rec, {}, frozenset(), tmp_path, FFMPEG)
    ghost = result["checks"]["ghost"]
    assert ghost["status"] == UNCERTAIN and ghost["missing_frames"] == [55] and "missing" in ghost["reasons"][0]
    assert result["status"] == UNCERTAIN


def test_luma_step_is_never_taken_across_a_gap(tmp_path: Path) -> None:
    a = scene(1)
    b = np.clip(a.astype(int) + 70, 0, 255).astype(np.uint8)
    frames = np.stack([a if f < 55 else b for f in range(100)])  # the whole jump sits on the frame that is dropped
    row, rec = _row(make_config([transition(50, "cut_push", 12, start=50)]))
    result = transitions_run.judge_row(row, _got(frames, drop=(55,)), (W, H), rec, {}, frozenset(), tmp_path, FFMPEG)
    step = result["checks"]["luma_step"]
    assert step["status"] == UNCERTAIN and step["gaps"] == [[54, 56]]  # the jump is not measured, so it is not judged
    assert step["max_step"] < 30.0 and result["status"] == UNCERTAIN


def test_dip_with_no_readable_window_and_no_schedule_is_uncertain(tmp_path: Path, two_scenes) -> None:
    frames = film(*two_scenes)
    row, rec = _row(make_config([transition(50, "flash", 8, start=48, continuity="mismatch")]))
    assert transitions_run._peak_frames(row) == []
    got = _got(frames, drop=tuple(range(48, 56)))
    result = transitions_run.judge_row(row, got, (W, H), rec, {"S01_B": {"frame": 70, "word": "Hi", "source": "x"}}, frozenset(),
                                       tmp_path, FFMPEG)
    dip = result["checks"]["dip"]
    assert dip["status"] == UNCERTAIN and dip["peak_frame_checked"] is None and "no window frame" in dip["reasons"][0]


def test_dip_starting_at_frame_zero_does_not_crash_and_is_uncertain(tmp_path: Path, two_scenes) -> None:
    video = write_video(tmp_path / "v.mp4", film(*two_scenes, dip=True, boundary=3))
    gate = judge(tmp_path, make_config([transition(3, "dip_white", 8, start=0, continuity="mismatch")]), video)
    row = gate["rows"][0]
    assert gate["status"] == UNCERTAIN and row["status"] == UNCERTAIN and "frame 0" in row["reasons"][0]


# 0.31 = the shipped, user-approved T390 whip: the band starts above it (root, recipes/qa/transitions-gates-v001.json)
@pytest.mark.parametrize("ncc_value,verdict", [(0.36, FAIL), (0.338, UNCERTAIN), (0.32, UNCERTAIN), (0.31, PASS)])
def test_same_seat_grey_band_is_uncertain_between_the_two_recipe_thresholds(tmp_path: Path, two_scenes, monkeypatch, ncc_value, verdict) -> None:
    monkeypatch.setattr(transitions_run, "ncc", lambda a, b: ncc_value)
    video = write_video(tmp_path / "v.mp4", film(*two_scenes, dip=True))
    gate = judge(tmp_path, dip_config(70), video)
    seat = gate["rows"][0]["checks"]["same_seat"]
    assert seat["status"] == verdict and gate["status"] == verdict and seat["ncc_grey_min"] == 0.32 and seat["ncc_limit"] == 0.35
    assert "near same-seat" in " ".join(seat["reasons"]) or verdict != UNCERTAIN


def test_a_cut_in_the_grey_band_still_passes(tmp_path: Path, two_scenes, monkeypatch) -> None:
    monkeypatch.setattr(transitions_run, "ncc", lambda a, b: 0.338)
    video = write_video(tmp_path / "v.mp4", film(*two_scenes))
    assert judge(tmp_path, make_config([transition(50, "cut", 0, start=50)]), video)["status"] == PASS


def test_first_spoken_frame_matches_the_word_start_s_not_the_first_word() -> None:
    words = [{"text": "late", "start_s": 2.0}, {"text": "early", "start_s": 1.0}]
    assert transitions_load._first_of(words, 100, 25.0) == (125, "early")
