"""jjv seam-blend CLI contract: config-driven policy, dry-run, receipts, refusals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.seedvr2 import seam_blend as sb
from engine.seedvr2 import seam_blend_policy as sp
from engine.seedvr2 import seam_blend_run as sbr
from seam_fixtures import (SHOT, FakeEncoder, build_tree, fake_deps, make_chunks, measurement,
                           policy_document, seam_policy_block)

try:
    import numpy  # noqa: F401
    HAS_NUMPY = True
except ImportError:  # optional engine dependency: skip, never fail
    HAS_NUMPY = False

requires_numpy = pytest.mark.skipif(not HAS_NUMPY, reason="numpy is not installed")


def windows_of(chunks: list[dict], frames: int) -> list[dict]:
    return sb.plan_windows(chunks, frames, half=4, blend_frames=8, allow_clipped_tail=True)


def test_auto_policy_thresholds_come_from_config(tmp_path: Path) -> None:
    policy = sp.SeamPolicy.from_config(build_tree(tmp_path / "cfg").config)
    assert policy.low_motion_max == 5.0 and policy.excess_trigger == 1.0
    assert sp.decide_policy("auto", policy, measurement(1.0, 2.2))["mode"] == "hf8"
    assert sp.decide_policy("auto", policy, measurement(15.3, -0.3))["mode"] == "core"
    assert sp.decide_policy("auto", policy, measurement(2.35, 0.93))["mode"] == "core"
    strict = sp.SeamPolicy.from_config(
        build_tree(tmp_path / "strict", policy=seam_policy_block(excess_trigger=3.0)).config)
    assert sp.decide_policy("auto", strict, measurement(1.0, 2.2))["mode"] == "core"
    assert sp.decide_policy("core", policy, None)["mode"] == "core"


def test_missing_seam_blend_block_is_refused(tmp_path: Path) -> None:
    tree = build_tree(tmp_path / "no-policy")
    tree.config.domain.pop("seam_blend")
    with pytest.raises(Refused, match="no seam_blend block"):
        sp.SeamPolicy.from_config(tree.config)


def test_measurement_summary_marks_seam_excess() -> None:
    chunks, frames = make_chunks([13, 13, 13])
    windows = windows_of(chunks, frames)
    native = [1.0] * (frames - 1)
    reference = [1.0] * (frames - 1)
    core = [1.0] * (frames - 1)
    core[13] = 4.0
    summary = sp.summarize_measurement(native, core, reference, windows)
    assert summary["native_mean_absdY"] == 1.0
    assert summary["n_seams"] == 2
    assert summary["max_excess_peak"] == 3.0
    assert summary["mean_excess_peak"] == 1.5


def test_cli_parser_registers_seam_blend() -> None:
    parser = argparse.ArgumentParser()
    seedvr2 = parser.add_subparsers(dest="stage", required=True)
    verbs = seedvr2.add_parser("seedvr2").add_subparsers(dest="verb", required=True)
    sbr.register_cli(verbs)
    args = parser.parse_args(["seedvr2", "seam-blend", "--episode", "e", "--shot", "S02_A",
                              "--out", "o.mp4"])
    assert args.mode == "auto" and args.dry_run is False and args.policy is None
    assert args.threads == 4


def test_cli_dry_run_prints_plan_without_decode(tmp_path: Path) -> None:
    tree = build_tree(tmp_path / "dry")

    def no_decode(*_args, **_kwargs):
        raise AssertionError("dry-run must not decode")

    deps = sbr.Deps(decode=no_decode, encoder_factory=FakeEncoder,
                    ffmpeg_version=lambda _ffmpeg: "ffmpeg test", emit=lambda _m: None)
    summary = sbr.run_seam_blend(tree.config, shot_id=SHOT, out=str(tmp_path / "out.mp4"),
                                 dry_run=True, deps=deps)
    assert summary["ok"] and summary["dry_run"]
    assert summary["output"]["written"] is False
    assert summary["policy"]["mode"] == "auto" and summary["policy"]["decision"] == "deferred"
    assert [window["S"] for window in summary["windows"]] == [13, 26, 39]
    assert not (tmp_path / "out.mp4").exists()


def test_cli_dry_run_refuses_incomplete_shot(tmp_path: Path) -> None:
    tree = build_tree(tmp_path / "incomplete")
    tree.set_status(2, "WAITING")
    with pytest.raises(Refused, match="WAITING"):
        sbr.run_seam_blend(tree.config, shot_id=SHOT, out=str(tmp_path / "out.mp4"),
                           dry_run=True, deps=sbr.Deps(emit=lambda _m: None))
    missing = build_tree(tmp_path / "missing")
    missing.job_path(3).unlink()
    with pytest.raises(Refused, match="job.json missing"):
        sbr.run_seam_blend(missing.config, shot_id=SHOT, out=str(tmp_path / "out.mp4"),
                           dry_run=True, deps=sbr.Deps(emit=lambda _m: None))


def test_cli_dry_run_uses_recorded_policy_document(tmp_path: Path) -> None:
    tree = build_tree(tmp_path / "doc")
    path = tmp_path / "SEAM-POLICY.json"
    path.write_text(json.dumps(policy_document(tree.plan_sha, motion=1.0, excess=2.2)), "utf-8")
    summary = sbr.run_seam_blend(tree.config, shot_id=SHOT, out=str(tmp_path / "o.mp4"),
                                 dry_run=True, policy_path=str(path),
                                 deps=sbr.Deps(emit=lambda _m: None))
    assert summary["policy"]["mode"] == "hf8"
    path.write_text(json.dumps(policy_document("0" * 64)), "utf-8")
    with pytest.raises(Refused, match="re-measure"):
        sbr.run_seam_blend(tree.config, shot_id=SHOT, out=str(tmp_path / "o.mp4"),
                           dry_run=True, policy_path=str(path),
                           deps=sbr.Deps(emit=lambda _m: None))


@requires_numpy
def test_cli_auto_build_measures_then_blends(tmp_path: Path) -> None:
    tree = build_tree(tmp_path / "auto")
    out = tmp_path / "auto.mp4"
    summary = sbr.run_seam_blend(tree.config, shot_id=SHOT, out=str(out), mode="auto",
                                 ffmpeg=sys.executable,
                                 deps=fake_deps(tree, measurement=measurement(1.0, 2.2)))
    assert summary["mode"] == "hf8"
    assert out.exists() and summary["output"]["frames"] == tree.frames
    assert summary["output"]["written"] is True


@requires_numpy
def test_cli_receipt_fields(tmp_path: Path) -> None:
    tree = build_tree(tmp_path / "receipt")
    out = tmp_path / "S02_A-lin8.mp4"
    messages: list[str] = []
    decode_calls: list[str] = []
    summary = sbr.run_seam_blend(tree.config, shot_id=SHOT, out=str(out), mode="lin8",
                                 ffmpeg=sys.executable,
                                 deps=fake_deps(tree, messages, decode_called=decode_calls))
    assert decode_calls, "build must decode the verified chunks"
    receipt = json.loads(Path(summary["receipt"]["path"]).read_text("utf-8"))
    assert receipt["schema"] == sbr.RECEIPT_SCHEMA
    assert receipt["mode"] == "lin8" and receipt["mode_requested"] == "lin8"
    assert receipt["policy"]["thresholds"]["excess_trigger"] == 1.0
    assert receipt["plan"]["sha256"] == tree.plan_sha
    assert receipt["config"]["config_sha256"] == tree.config.config_sha256
    assert receipt["weights_on_next_chunk"][0] == pytest.approx(1 / 16)
    assert len(receipt["chunks"]) == len(tree.chunks)
    assert all(record["core_equals_raw_trim_crop_maxdiff_YUV"] == [0, 0, 0]
               for record in receipt["chunks"])
    assert len(receipt["seams"]) == len(tree.chunks) - 1
    assert receipt["output"]["frames"] == tree.frames
    assert receipt["output"]["sha256"] == sb.sha256_file(out)
    assert receipt["blended_frame_count"] == sum(row["hi"] - row["lo"]
                                                 for row in windows_of(tree.chunks, tree.frames))
    assert any("core==trim+crop" in message for message in messages)


@requires_numpy
def test_cli_refuses_output_inside_plan_tree(tmp_path: Path) -> None:
    tree = build_tree(tmp_path / "inside")
    inside = tree.plan_path.parent / "oops.mp4"
    with pytest.raises(Refused, match="inside the production plan tree"):
        sbr.run_seam_blend(tree.config, shot_id=SHOT, out=str(inside), mode="lin8",
                           ffmpeg=sys.executable, deps=fake_deps(tree))
    assert not inside.exists()
