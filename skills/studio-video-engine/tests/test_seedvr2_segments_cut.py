"""``jjv seedvr2 segments``: plan-derived cut list, frame-exact cuts, never-overwrite, md5 proof, receipts."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.config import loader
from engine.core.errors import Failed, Refused
from engine.media.probe import probe_video
from engine.seedvr2 import segment_cut, segments
from engine.seedvr2.chunking import plan_chunks
from engine.seedvr2.plan import build_plan
from test_seedvr2_segments_support import fake_probe, make_world, read_ids, write_media


@pytest.fixture()
def world(tmp_path: Path):
    return make_world(tmp_path)


def run(world, out: Path, **kw):
    kw.setdefault("probe", fake_probe)
    kw.setdefault("runner", world.runner)
    return segments.run_segments(world.config, repo_root=loader.REPO_ROOT, out_root=out, **kw)


# ---- real ffmpeg: the cut really is frame exact -------------------------------------------------
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_real_ffmpeg_cut_is_frame_exact_lossless_and_never_overwrites(tmp_path: Path) -> None:
    source = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=24", "-frames:v", "20",
                    "-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv420p", str(source)], check=True)
    from fractions import Fraction
    out = tmp_path / "cut" / "seg.mp4"
    segment_cut.cut_segment(source, out, start=5, end_exclusive=17, fps=Fraction(24), width=64, height=48)
    info = probe_video(out, count_packets=True)
    assert (info.frames, info.width, info.height, info.fps) == (12, 64, 48, Fraction(24))
    whole = segment_cut.framemd5(source)
    assert segment_cut.framemd5(out) == whole[5:17], "decoded frames of the cut are the source frames 5..16"
    assert segment_cut.slice_md5(source, 5, 17) == whole[5:17]
    assert segment_cut.framemd5(out) != whole[4:16], "an off-by-one cut would differ (the proof can fail)"
    with pytest.raises(Refused, match="overwrite"):
        segment_cut.cut_segment(source, out, start=5, end_exclusive=17, fps=Fraction(24), width=64, height=48)
    assert not list(out.parent.glob(".*tmp*")), "no temp file is left behind"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_real_ffmpeg_wrong_expected_size_fails_and_leaves_nothing(tmp_path: Path) -> None:
    source = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=24", "-frames:v", "10",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
    from fractions import Fraction
    out = tmp_path / "x.mp4"
    with pytest.raises(Failed, match="size mismatch"):
        segment_cut.cut_segment(source, out, start=0, end_exclusive=4, fps=Fraction(24), width=99, height=48)
    assert not out.exists() and not list(tmp_path.glob(".*tmp*"))


def test_cut_command_is_the_v004_encode() -> None:
    cmd = segment_cut.cut_command(Path("a.mp4"), Path("b.mp4"), 9, 30)
    assert cmd[:6] == ["ffmpeg", "-v", "error", "-i", "a.mp4", "-map"]
    assert "trim=start_frame=9:end_frame=30,setpts=PTS-STARTPTS" in cmd
    assert cmd[cmd.index("-c:v") + 1:cmd.index("-c:v") + 11] == [
        "libx264", "-preset", "medium", "-crf", "0", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "b.mp4"]
    with pytest.raises(Refused):
        segment_cut.trim_filter(5, 5)


# ---- the cut list derives from the plan --------------------------------------------------------
def test_cut_list_is_the_recipe_chunking_of_every_shot(world) -> None:
    plan = build_plan(world.config, repo_root=loader.REPO_ROOT, probe=fake_probe).plan
    jobs = segments.jobs_from_plan(plan, world.config, world.recipe)
    expected = {s: plan_chunks(n, world.recipe["geometry"]) for s, n in (("S01_A", 40), ("S02_A", 30))}
    assert [(j.shot_id, j.start, j.end) for j in jobs] == [
        (s, c["segment_start_frame"], c["segment_end_frame_exclusive"]) for s in expected for c in expected[s]]
    assert all(j.relative == f"{j.shot_id}/chunks/{j.chunk_name}/source-segment.mp4" for j in jobs)


@pytest.mark.parametrize("edit,match", [
    (lambda p: p.update(episode_id="other"), "episode_id"),
    (lambda p: p.update(config_sha256="0" * 64), "config_sha256"),
    (lambda p: p.update(recipe_canonical_sha256="0" * 64), "recipe sha256"),
    (lambda p: p.update(kind="weird"), "kind"),
    (lambda p: p["shots"][0]["chunks"][1].update(segment_end_frame_exclusive=99), "chunk window"),
    (lambda p: p["shots"][0].update(source_sha256="0" * 64), "source sha256"),
    (lambda p: p["shots"][0]["chunks"].pop(), "chunk count"),
    (lambda p: p["shots"].append(copy.deepcopy(p["shots"][0])), "duplicated"),
])
def test_a_plan_that_disagrees_with_the_config_is_refused(world, edit, match) -> None:
    plan = copy.deepcopy(build_plan(world.config, repo_root=loader.REPO_ROOT, probe=fake_probe).plan)
    edit(plan)
    with pytest.raises(Refused, match=match):
        segments.jobs_from_plan(plan, world.config, world.recipe)


def test_only_selectors(world) -> None:
    plan = build_plan(world.config, repo_root=loader.REPO_ROOT, probe=fake_probe).plan
    jobs = segments.jobs_from_plan(plan, world.config, world.recipe)
    assert [j.chunk_name for j in segments.select_jobs(jobs, "S01_A:1")] == ["chunk-0001"]
    assert {j.shot_id for j in segments.select_jobs(jobs, "S02_A")} == {"S02_A"}
    for bad in ("S09_A", "S01_A:9", "S01_A:x", ":1"):
        with pytest.raises(Refused):
            segments.select_jobs(jobs, bad)


# ---- running -----------------------------------------------------------------------------------
def test_cuts_every_chunk_with_the_v004_filter_and_writes_a_receipt(world, tmp_path: Path) -> None:
    out = tmp_path / "segs"
    summary = run(world, out)
    chunks = [c for n in (40, 30) for c in plan_chunks(n, world.recipe["geometry"])]
    assert summary["chunks"] == summary["cut"] == len(chunks)
    for row in summary["segments"]:
        shot = row["shot_id"]
        ids = read_ids(out / row["segment_path"])
        assert ids == [f"{shot}:{i}" for i in range(row["source_start_frame"], row["source_end_frame_exclusive"])]
        assert row["status"] == "cut" and row["md5_verified"] and row["frames"] == len(ids)
    filters = {c[c.index("-vf") + 1] for c in world.runner.cuts()}
    assert "trim=start_frame=0:end_frame=17,setpts=PTS-STARTPTS" in filters
    receipt = json.loads((out / "segments-receipt.json").read_text())
    assert receipt["schema"] == segments.RECEIPT_SCHEMA and receipt["md5_verified"]
    assert receipt["encode"]["args"] == segment_cut.SEGMENT_ENCODE and "timestamp" not in json.dumps(receipt)
    assert [r["sha256"] for r in receipt["segments"]] == [r["sha256"] for r in summary["segments"]]


def test_the_cut_segments_are_what_plan_binds_and_executes(world, tmp_path: Path) -> None:
    out = tmp_path / "segs"
    run(world, out)
    plan = build_plan(world.config, repo_root=loader.REPO_ROOT, segments_root=out, probe=fake_probe).plan
    assert plan["status"] == "PLANNED_NOT_RENDERED" and plan["totals"]["segments_bound"] == plan["totals"]["total_chunks"]


def test_rerun_keeps_identical_segments_and_writes_the_same_receipt(world, tmp_path: Path) -> None:
    out = tmp_path / "segs"
    first = run(world, out)
    again = run(world, out)
    assert again["cut"] == 0 and {r["status"] for r in again["segments"]} == {"existing_verified"}
    assert again["receipt_sha256"] == first["receipt_sha256"]


def test_a_rerun_that_would_change_the_receipt_never_overwrites_it(world, tmp_path: Path) -> None:
    out = tmp_path / "segs"
    run(world, out)
    with pytest.raises(Refused, match="overwrite"):
        run(world, out, verify_md5=False)  # a weaker proof must not replace the receipt of a stronger one


def test_a_tampered_existing_segment_is_refused_not_replaced(world, tmp_path: Path) -> None:
    out = tmp_path / "segs"
    run(world, out, only="S01_A:0")
    target = out / "S01_A/chunks/chunk-0000/source-segment.mp4"
    write_media(target, [f"evil:{i}" for i in range(17)], 864, 480)
    before = target.read_bytes()
    with pytest.raises(Refused, match="frame md5 differs"):
        run(world, out, only="S01_A:0")
    assert target.read_bytes() == before


def test_a_bad_cut_is_caught_by_the_md5_proof_and_leaves_no_segment(world, tmp_path: Path) -> None:
    out = tmp_path / "segs"
    world.runner.corrupt = lambda path, ids: ["bad:" + i for i in ids]
    with pytest.raises(Failed, match="frame md5 differs"):
        run(world, out)
    assert not list(out.rglob("source-segment.mp4")) and not list(out.rglob(".*tmp*"))


def test_without_the_md5_proof_a_bad_cut_goes_through(world, tmp_path: Path) -> None:
    """The proof is the only thing that catches a wrong frame: this is the control for the test above."""
    world.runner.corrupt = lambda path, ids: ["bad:" + i for i in ids]
    summary = run(world, tmp_path / "segs", verify_md5=False, only="S01_A:0")
    assert summary["segments"][0]["md5_verified"] is False


def test_source_that_changed_is_refused_before_any_cut(world, tmp_path: Path) -> None:
    write_media(world.root / "clips" / "S01_A.mp4", [f"S01_A:{i}" for i in range(40)], 864, 480, "retagged")
    with pytest.raises(Refused, match="source sha256"):
        run(world, tmp_path / "segs")
    assert not (tmp_path / "segs").exists()


def test_dry_run_lists_the_cuts_and_writes_nothing(world, tmp_path: Path) -> None:
    out = tmp_path / "segs"
    summary = run(world, out, dry_run=True)
    assert summary["dry_run"] and summary["chunks"] == len(summary["segments"]) and not out.exists()
    assert world.runner.commands == []


def test_only_writes_a_selection_receipt(world, tmp_path: Path) -> None:
    out = tmp_path / "segs"
    summary = run(world, out, only="S02_A")
    assert summary["receipt_path"].endswith(".json") and "only" in Path(summary["receipt_path"]).name
    assert {r["shot_id"] for r in summary["segments"]} == {"S02_A"}


def test_segment_paths_cannot_escape_the_out_root(world, tmp_path: Path) -> None:
    plan = copy.deepcopy(build_plan(world.config, repo_root=loader.REPO_ROOT, probe=fake_probe).plan)
    plan["shots"][0]["chunks"][0]["segment_path"] = "../evil.mp4"
    with pytest.raises(Refused, match="segment path"):
        run(world, tmp_path / "segs", plan=plan)
