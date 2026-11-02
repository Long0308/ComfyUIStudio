"""Ported seam-blend geometry/verification tests (the 10 synthetic v001 tests)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.seedvr2 import seam_blend as sb
from seam_fixtures import SHOT, TH, TW, build_tree, make_chunks

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:  # numpy is an optional engine dependency: skip, never fail
    np = None
    HAS_NUMPY = False

requires_numpy = pytest.mark.skipif(not HAS_NUMPY, reason="numpy is not installed")


@requires_numpy
def synth_raw(chunks: list[dict], seed: int = 0) -> list[tuple]:
    rng = np.random.default_rng(seed)
    raws = []
    for chunk in chunks:
        frames = chunk["segment_frames"]
        raws.append((rng.integers(0, 256, (frames, TH, TW), dtype=np.uint8),
                     rng.integers(0, 256, (frames, TH // 2, TW // 2), dtype=np.uint8),
                     rng.integers(0, 256, (frames, TH // 2, TW // 2), dtype=np.uint8)))
    return raws


def loader(chunks: list[dict], raws: list[tuple]):
    def load(index: int) -> dict:
        chunk = chunks[index]
        offset, frames = chunk["core_offset_in_segment"], chunk["core_frames"]
        core = tuple(plane[offset:offset + frames].copy() for plane in raws[index])
        return {"raw": raws[index], "core": core}
    return load


@pytest.fixture
def shot():
    chunks, frames = make_chunks([13, 13, 13, 13, 11])
    return chunks, frames, synth_raw(chunks)


def windows_of(chunks: list[dict], frames: int, *, allow_clipped: bool = True) -> list[dict]:
    return sb.plan_windows(chunks, frames, half=4, blend_frames=8,
                           allow_clipped_tail=allow_clipped)


def test_weights_sum_and_values() -> None:
    weights = sb.seam_weights(8)
    assert len(weights) == 8
    assert weights[0] == pytest.approx(1 / 16) and weights[-1] == pytest.approx(15 / 16)
    for index in range(8):
        assert weights[index] + (1 - weights[index]) == pytest.approx(1.0)
        assert weights[index] + weights[7 - index] == pytest.approx(1.0)
    assert all(left < right for left, right in zip(weights, weights[1:]))


def test_window_indices(shot) -> None:
    chunks, frames, _ = shot
    windows = windows_of(chunks, frames)
    assert [window["S"] for window in windows] == [13, 26, 39, 52]
    for window in windows:
        assert (window["lo"], window["hi"]) == (window["S"] - 4, window["S"] + 4)
        assert not window["clipped"]
        for index in (window["k"], window["k"] + 1):
            chunk = chunks[index]
            assert chunk["segment_start_frame"] <= window["lo"]
            assert chunk["segment_end_frame_exclusive"] >= window["hi"]
    assert all(left["hi"] <= right["lo"] for left, right in zip(windows, windows[1:]))


@requires_numpy
def test_blend_frame_selection_and_weights(shot) -> None:
    chunks, frames, raws = shot
    windows = windows_of(chunks, frames)
    gains: list[dict] = []
    output = {frame: (planes, kind) for frame, planes, kind in sb.assemble_frames(
        chunks, frames, windows, loader(chunks, raws), "lin8", blend_frames=8,
        gains_out=gains)}
    first = windows[0]
    for offset, frame in enumerate(range(first["lo"], first["hi"])):
        left = raws[0][0][frame - chunks[0]["segment_start_frame"]]
        right = raws[1][0][frame - chunks[1]["segment_start_frame"]]
        weight = (offset + 0.5) / 8
        expected = np.clip(np.rint((1 - weight) * left.astype(np.float32)
                                   + weight * right.astype(np.float32)), 0, 255).astype(np.uint8)
        assert output[frame][1] == "blend"
        assert np.array_equal(output[frame][0][0], expected)
    assert [gain["frame"] for gain in gains] == [frame for window in windows
                                                 for frame in range(window["lo"], window["hi"])]


@requires_numpy
@pytest.mark.parametrize("mode", ["lin8", "hf8"])
def test_frames_outside_windows_bit_identical_to_cores(shot, mode: str) -> None:
    if mode == "hf8":
        pytest.importorskip("cv2")
    chunks, frames, raws = shot
    windows = windows_of(chunks, frames)
    inside = {frame for window in windows for frame in range(window["lo"], window["hi"])}
    load = loader(chunks, raws)
    blended = {frame: planes for frame, planes, _ in
               sb.assemble_frames(chunks, frames, windows, load, mode, blend_frames=8)}
    baseline = {frame: planes for frame, planes, _ in
                sb.assemble_frames(chunks, frames, windows, load, "core", blend_frames=8)}
    assert len(blended) == len(baseline) == frames
    changed = 0
    for frame in range(frames):
        same = all(np.array_equal(left, right) for left, right in zip(blended[frame],
                                                                      baseline[frame]))
        if frame in inside:
            changed += 0 if same else 1
        else:
            assert same, f"frame {frame} outside windows differs from core"
    assert changed > 0
    for index, chunk in enumerate(chunks):
        core = load(index)["core"]
        for offset in range(chunk["core_frames"]):
            frame = chunk["core_start_frame"] + offset
            assert all(np.array_equal(baseline[frame][plane], core[plane][offset])
                       for plane in range(3))


@requires_numpy
def test_hf_gain_at_least_one_and_recorded(shot) -> None:
    pytest.importorskip("cv2")
    chunks, frames, raws = shot
    windows = windows_of(chunks, frames)
    gains: list[dict] = []
    list(sb.assemble_frames(chunks, frames, windows, loader(chunks, raws), "hf8",
                            blend_frames=8, gains_out=gains))
    assert len(gains) == 8 * len(windows)
    assert all(gain["gain"] >= 1.0 for gain in gains)


def test_refuses_frame_count_mismatch(shot) -> None:
    chunks, _, _ = shot
    chunk = chunks[1]
    sb.check_frame_counts(chunk, chunk["segment_frames"], chunk["segment_frames"],
                          chunk["core_frames"])
    with pytest.raises(Refused, match="raw frames"):
        sb.check_frame_counts(chunk, chunk["segment_frames"], chunk["segment_frames"] - 1,
                              chunk["core_frames"])
    with pytest.raises(Refused, match="raw frames"):
        sb.check_frame_counts(chunk, chunk["segment_frames"] + 1, chunk["segment_frames"],
                              chunk["core_frames"])
    with pytest.raises(Refused, match="core frames"):
        sb.check_frame_counts(chunk, chunk["segment_frames"], chunk["segment_frames"],
                              chunk["core_frames"] - 1)


@requires_numpy
def test_refuses_core_not_equal_raw_trim(shot) -> None:
    chunks, _, raws = shot
    chunk, raw = chunks[2], raws[2]
    core = loader(chunks, raws)(2)["core"]
    assert sb.check_core_equals_raw(chunk, raw, core) == [0, 0, 0]
    bad = (core[0].copy(),) + core[1:]
    bad[0][3, 5, 5] ^= 1
    with pytest.raises(Refused, match="core != raw"):
        sb.check_core_equals_raw(chunk, raw, bad)


def test_refuses_small_core_clipped_tail_gap_and_uncovered_context() -> None:
    chunks, frames = make_chunks([13, 5, 13, 13])
    with pytest.raises(Refused, match="core_frames=5"):
        windows_of(chunks, frames)
    chunks, frames = make_chunks([13, 13, 13, 3])
    with pytest.raises(Refused, match="past the shot end"):
        windows_of(chunks, frames, allow_clipped=False)
    windows = windows_of(chunks, frames, allow_clipped=True)
    assert windows[-1]["clipped"] and windows[-1]["hi"] == frames
    assert windows[-1]["lo"] == frames - 3 - 4
    chunks, frames = make_chunks([13, 13, 13])
    chunks[1]["core_start_frame"] += 1
    with pytest.raises(Refused, match="core_start"):
        windows_of(chunks, frames)
    chunks, frames = make_chunks([13, 13, 13])
    chunks[0]["segment_end_frame_exclusive"] -= 1
    with pytest.raises(Refused, match="does not cover"):
        windows_of(chunks, frames)


def test_check_job_refuses_incomplete(tmp_path: Path) -> None:
    tree = build_tree(tmp_path / "case", complete=False)
    geometry = sb.geometry_from_plan(tree.plan)
    chunk = tree.chunks[0]
    job = json.loads(tree.job_path(0).read_text("utf-8"))
    job["_path"] = str(tree.job_path(0))
    with pytest.raises(Refused, match="WAITING"):
        sb.check_job(SHOT, chunk, job, tree.plan_sha, tree.plan_path.parent, geometry)
    job["status"] = "COMPLETED"
    sb.check_job(SHOT, chunk, job, tree.plan_sha, tree.plan_path.parent, geometry)
    job["output_frame_count"] += 1
    with pytest.raises(Refused, match="output_frame_count"):
        sb.check_job(SHOT, chunk, job, tree.plan_sha, tree.plan_path.parent, geometry)


def test_encoder_colour_tags_are_input_options() -> None:
    """ffmpeg 9 converts pixels when colour tags are output-only (error-db ffmpeg-output-colour-tags-convert-pixels)."""
    import inspect
    from engine.seedvr2 import seam_media
    src = inspect.getsource(seam_media.Encoder.__init__)
    assert src.index('"-color_trc"') < src.index('"-i", "-"'), "colour tags must precede -i"
    assert '"iec61966-2-1"' in src, "transfer tag must match the SeedVR2 cores"
