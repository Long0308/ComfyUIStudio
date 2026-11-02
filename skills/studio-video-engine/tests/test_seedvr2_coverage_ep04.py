"""ep04 (read-only): the coverage negative control, segment parity against the v004 segments, a real tails plan.

Everything real is read-only; outputs go to tmp_path.  Skipped when the episode files or ffmpeg are absent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from engine.config import loader
from engine.core.errors import Refused, exit_code_for
from engine.media.probe import probe_video
from engine.seedvr2 import coverage, segment_cut, segments, tails
from engine.seedvr2.plan import build_plan

EP = loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom"
V008 = EP / "editorial/review-hd-v008/config/review-config-v008.json"
V015 = EP / "editorial/review-hd-v015/config/review-config-v015.json"
TAIL_MAP = EP / "technical/seedvr2-tails-v001/MASTER-TAIL-MAP.json"
V004 = EP / "technical/seedvr2-production-v004"
needs_ep04 = pytest.mark.skipif(not (V008.is_file() and TAIL_MAP.is_file() and V004.is_dir()),
                                reason="ep04 production files are not present")
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def config():
    return loader.resolve_episode("04-milk-and-mom")


@needs_ep04
def test_negative_control_v008_plan_without_tails_is_refused_naming_the_three_tail_ranges(config) -> None:
    reads, _ = coverage.load_reads(V008)
    with pytest.raises(Refused) as caught:
        build_plan(config, repo_root=loader.REPO_ROOT, reads=reads)
    assert exit_code_for(caught.value) == 1
    missing = [(m["shot"], m["start_frame"], m["end_frame_exclusive"]) for m in caught.value.evidence["missing"]]
    assert missing == [("S03_B", 100, 103), ("S04_B", 128, 131), ("S05_B", 92, 95)]
    text = str(caught.value)
    assert "S03_B f100..f102" in text and "S04_B f128..f130" in text and "S05_B f92..f94" in text


@needs_ep04
def test_v008_plan_with_the_assembled_v001_tails_is_accepted(config) -> None:
    reads, _ = coverage.load_reads(V008)
    extra = coverage.load_tail_map(TAIL_MAP)
    plan = build_plan(config, repo_root=loader.REPO_ROOT, reads=reads, extra_scope=extra).plan
    assert plan["coverage"]["ok"] and plan["coverage"]["scope"]["S05_B"] == [[0, 102]]


@needs_ep04
def test_dropping_one_tail_chunk_names_only_that_shot(config) -> None:
    reads, _ = coverage.load_reads(V008)
    extra = [r for r in coverage.load_tail_map(TAIL_MAP) if r[0] != "S04_B"]
    with pytest.raises(Refused) as caught:
        build_plan(config, repo_root=loader.REPO_ROOT, reads=reads, extra_scope=extra)
    assert [m["shot"] for m in caught.value.evidence["missing"]] == ["S04_B"]


@needs_ep04
@pytest.mark.skipif(not V015.is_file(), reason="v015 review config missing")
def test_v015_needs_one_tail_frame_and_the_v001_tails_cover_it(config) -> None:
    reads, _ = coverage.load_reads(V015)
    with pytest.raises(Refused, match=r"S05_B f92\.\.f92"):
        build_plan(config, repo_root=loader.REPO_ROOT, reads=reads)
    assert build_plan(config, repo_root=loader.REPO_ROOT, reads=reads,
                      extra_scope=coverage.load_tail_map(TAIL_MAP)).plan["coverage"]["ok"]


@needs_ep04
@needs_ffmpeg
def test_segments_parity_with_v004_frame_md5_on_representative_chunks(config, tmp_path: Path) -> None:
    """Multi-chunk shot (first/middle/last), a short last shot, and a two-chunk shot: the cut of the engine equals
    the frozen v004 segment decode frame for frame, and the frame ranges are identical."""
    out = tmp_path / "segs"
    only = "S01_A:0,S01_A:1,S01_A:7,S03_B,S06_B3"
    summary = segments.run_segments(config, repo_root=loader.REPO_ROOT, out_root=out, only=only)
    assert summary["cut"] == summary["chunks"] >= 12
    frozen_plan = json.loads((V004 / "PRODUCTION-PLAN.json").read_text("utf-8"))
    frozen = {(s["shot_id"], c["chunk_name"]): c for s in frozen_plan["shots"] for c in s["chunks"]}
    for row in summary["segments"]:
        old = frozen[(row["shot_id"], row["chunk"])]
        assert (row["source_start_frame"], row["source_end_frame_exclusive"]) == (
            old["segment_start_frame"], old["segment_end_frame_exclusive"])
        mine, theirs = out / row["segment_path"], V004 / row["segment_path"]
        assert probe_video(mine, count_packets=True).frames == old["segment_frames"]
        assert segment_cut.framemd5(mine) == segment_cut.framemd5(theirs), row["segment_path"]


@needs_ep04
@needs_ffmpeg
def test_real_tails_plan_for_v008_reproduces_the_hand_cut_v001_frames(config, tmp_path: Path) -> None:
    reads, _ = coverage.load_reads(V008)  # its clip paths name the retired D: root; the engine reads them where they live now
    out = tmp_path / "tails"
    summary = tails.plan_tails(config, repo_root=loader.REPO_ROOT, reads=reads, out=out)
    assert summary["status"] == "PLANNED_NOT_RENDERED" and summary["totals"]["total_chunks"] == 3
    plan = json.loads((out / tails.TAILS_PLAN_FILE).read_text())
    ranges = {s["shot_id"]: (s["source_range"]["start_frame"], s["source_range"]["end_frame_exclusive"])
              for s in plan["shots"]}
    assert ranges == {"S03_B": (96, 103), "S04_B": (124, 131), "S05_B": (88, 95)}
    v001 = EP / "technical/seedvr2-tails-v001/episode/clips"
    for shot, clip, first in (("S03_B", "S03_B-tail-n096-n106.mp4", 96), ("S04_B", "S04_B-tail-n124-n134.mp4", 124),
                              ("S05_B", "S05_B-tail-n089-n101.mp4", 89)):
        mine = segment_cut.framemd5(out / shot / "chunks/chunk-0000/source-segment.mp4")
        old = segment_cut.framemd5(v001 / clip)
        start = ranges[shot][0]
        overlap = mine[max(0, first - start):]
        assert overlap == old[max(0, start - first):][:len(overlap)] and len(overlap) >= 6, shot


@needs_ep04
@needs_ffmpeg
def test_the_existing_execute_dry_run_accepts_the_real_tails_plan(config, tmp_path: Path) -> None:
    reads, _ = coverage.load_reads(V008)  # its clip paths name the retired D: root; the engine reads them where they live now
    out = tmp_path / "tails"
    tails.plan_tails(config, repo_root=loader.REPO_ROOT, reads=reads, out=out)
    done = subprocess.run([sys.executable, "-I", str(loader.SKILL_ROOT / "bin" / "jjv.py"), "seedvr2", "execute",
                           "--episode", "04-milk-and-mom", "--plan", str(out / tails.TAILS_PLAN_FILE)],
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads(done.stdout)
    assert report["dry_run"] and report["planned_chunks"] == 3 and "POST skipped (dry-run)" in done.stderr
