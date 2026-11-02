"""``editorial build-config``: write-once outputs, determinism, dry run, CLI, real ffprobe, parity."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

import parity_v008
from editorial_fixtures import (EPISODE, HISTORICAL_TIMING_V001, LOGO, REAL_BOUNDARIES, REAL_TIMING, Inputs,
                                fake_probe)
from engine.config import loader
from engine.core.errors import Refused
from engine.editorial import build

HAS_FFPROBE = bool(shutil.which("ffprobe"))

pytestmark = pytest.mark.usefixtures("legacy_ep04_cli")  # the live ep04 moved to its 3444 f contract


def _jjv():
    spec = importlib.util.spec_from_file_location("jjv_cli", Path(__file__).resolve().parents[1] / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cli(out: Path, *extra: str, boundaries: Path = REAL_BOUNDARIES, timing: Path = REAL_TIMING) -> list[str]:
    return ["editorial", "build-config", "--episode", EPISODE, "--boundaries", str(boundaries),
            "--word-timing", str(timing), "--out", str(out), "--allow-outside", str(LOGO), *extra]


# ---- outputs ---------------------------------------------------------------------------------------
def test_outputs_are_deterministic_and_carry_no_timestamp(tmp_path: Path) -> None:
    inputs = Inputs(tmp_path)
    first = build.write_outputs(inputs.build(), tmp_path / "a", dry_run=True)
    second = build.write_outputs(inputs.build(), tmp_path / "b", dry_run=True)
    assert {k: v["sha256"] for k, v in first.items()} == {k: v["sha256"] for k, v in second.items()}
    text = json.dumps(inputs.build().config)
    assert "generated" not in text and "timestamp" not in text


def test_dry_run_writes_nothing_and_reports_hashes(tmp_path: Path) -> None:
    out = tmp_path / "out"
    summary = build.write_outputs(Inputs(tmp_path).build(), out, dry_run=True)
    assert not out.exists() and all(len(v["sha256"]) == 64 and v["written"] is False for v in summary.values())


def test_write_is_once_idempotent_for_identical_bytes_and_refuses_a_different_file(tmp_path: Path) -> None:
    out = tmp_path / "out"
    built = Inputs(tmp_path).build()
    first = build.write_outputs(built, out, dry_run=False)
    assert build.write_outputs(built, out, dry_run=False) == first  # idempotent
    changed = Inputs(tmp_path)
    changed.row(240)["motivation"] = "a different reason"
    with pytest.raises(Refused, match="refusing to overwrite"):
        build.write_outputs(changed.build(), out, dry_run=False)
    assert json.loads((out / build.CONFIG_NAME).read_text("utf-8"))["motion"]["transitions"][1]["motivation"] != \
        "a different reason"


def test_a_conflict_on_one_file_leaves_the_other_unwritten(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / build.EVENTS_NAME).write_text("{}", encoding="utf-8")
    with pytest.raises(Refused):
        build.write_outputs(Inputs(tmp_path).build(), out, dry_run=False)
    assert not (out / build.CONFIG_NAME).exists()


def test_config_shape_binds_every_wav_and_records_input_hashes(tmp_path: Path) -> None:
    config = Inputs(tmp_path).build().config
    assert config["schema"] == build.CONFIG_SCHEMA and len(config["wav_bindings"]) == 14 + 12
    assert {b["kind"] for b in config["wav_bindings"]} == {"dialogue", "card"}
    assert all(len(v) == 64 for v in config["inputs"].values())
    assert config["qa"]["av"]["reference_seconds"] == 84.0


# ---- CLI ---------------------------------------------------------------------------------------------
def test_cli_build_config_writes_both_files_then_is_idempotent(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"
    # ffprobe is real here (3 native clips); the unit tests above use the fake probe
    if not HAS_FFPROBE:
        pytest.skip("ffprobe absent")
    assert _jjv().main(_cli(out)) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["ok"] and summary["boundaries"] == 28 and summary["icon_events"] == 19
    assert (out / "review-config.json").is_file() and (out / "events.json").is_file()
    assert _jjv().main(_cli(out)) == 0  # same bytes -> write_once idempotent


def test_cli_dry_run_writes_nothing(tmp_path: Path, capsys) -> None:
    if not HAS_FFPROBE:
        pytest.skip("ffprobe absent")
    out = tmp_path / "out"
    assert _jjv().main(_cli(out, "--dry-run")) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True and not out.exists()


def test_cli_refused_rule_exits_1_with_nothing_written(tmp_path: Path, capsys) -> None:
    bad = json.loads(REAL_BOUNDARIES.read_text("utf-8"))
    row = next(r for r in bad["boundaries"] if r["frame"] == 1010)
    row.update({"type": "dissolve", "frames": 6})  # both shots at once on a mismatch
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    out = tmp_path / "out"
    assert _jjv().main(_cli(out, boundaries=path)) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False and "both sides in one frame" in result["error"] and not out.exists()


def test_cli_missing_input_exits_2(tmp_path: Path, capsys) -> None:
    assert _jjv().main(_cli(tmp_path / "out", boundaries=tmp_path / "nope.json")) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert _jjv().main(_cli(tmp_path / "out", timing=tmp_path / "nope.json")) == 2


def test_cli_a_missing_referenced_file_exits_2_and_a_missing_episode_exits_2(tmp_path: Path, capsys) -> None:
    bad = json.loads(REAL_BOUNDARIES.read_text("utf-8"))
    bad["cards"][0]["audio"]["path"] = "audio/nope.wav"
    path = tmp_path / "b.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert _jjv().main(_cli(tmp_path / "out", "--dry-run", boundaries=path)) == 2
    capsys.readouterr()
    args = _cli(tmp_path / "out")
    args[args.index(EPISODE)] = "no-such-episode"
    assert _jjv().main(args) == 2


def test_cli_rule_violation_exits_1_even_when_the_file_exists(tmp_path: Path, capsys) -> None:
    bad = json.loads(REAL_BOUNDARIES.read_text("utf-8"))
    bad["cards"][0]["audio"]["sha256"] = "0" * 64
    path = tmp_path / "b.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert _jjv().main(_cli(tmp_path / "out", "--dry-run", boundaries=path)) == 1


# ---- real probe ----------------------------------------------------------------------------------------
@pytest.mark.skipif(not HAS_FFPROBE, reason="ffprobe absent")
def test_the_real_ffprobe_agrees_with_the_recorded_native_frame_counts(tmp_path: Path) -> None:
    built = Inputs(tmp_path).build(probe=build._probe_frames)
    tails = {t["id"]: t["outgoing_tail"] for t in built.events["transitions"] if "outgoing_tail" in t}
    assert {k: v["native_frames"] for k, v in tails.items()} == {"T1010": 107, "T1310": 141, "T1610": 107}


# ---- parity with the hand-built review cut v008 -----------------------------------------------------------
@pytest.fixture(scope="module")
def parity_pair(tmp_path_factory):
    # v008 was hand-built on word-timing v001; the canonical v003 differs only by the seven first-word
    # onsets (asserted in test_te28a_round4), so parity is checked against its own baseline.
    inputs = Inputs(tmp_path_factory.mktemp("parity"), HISTORICAL_TIMING_V001)
    built = inputs.build(probe=fake_probe)
    hand_events, hand_config = parity_v008.load_hand_built(loader.REPO_ROOT)
    return built, hand_events, hand_config


def test_parity_events_with_v008_has_no_undocumented_difference(parity_pair) -> None:
    built, hand_events, _ = parity_pair
    assert parity_v008.compare_events(built.events, hand_events) == []


def test_parity_config_with_v008_has_no_undocumented_difference(parity_pair) -> None:
    built, _, hand_config = parity_pair
    assert parity_v008.compare_config(built.config, hand_config) == []


def test_parity_covers_the_features_it_claims(parity_pair) -> None:
    built, hand_events, _ = parity_pair
    kinds = {t["type"] for t in built.events["transitions"]}
    assert {"whip", "dip_white", "iris", "bloom", "card_slide", "plate_in", "none"} <= kinds
    assert [t["boundary"] for t in built.events["transitions"] if t["type"] == "dip_white"] == [1010, 1310, 1610]
    assert all(t["continuity"] == "mismatch" for t in built.events["transitions"] if t["type"] == "dip_white")
    assert len(built.events["icon_events"]) == len(hand_events["icon_events"]) == 19
    assert built.events["ending"]["end_logo"]["frames"] == 60


def test_the_documented_differences_are_exactly_the_observed_ones(parity_pair) -> None:
    built, hand_events, hand_config = parity_pair
    observed = parity_v008.observed_intended(built.events, hand_events, built.config, hand_config)
    assert observed == set(parity_v008.INTENDED)  # no stale entry, no undocumented one


def test_a_stale_documented_difference_is_detected(parity_pair) -> None:
    built, hand_events, hand_config = parity_pair
    events = json.loads(json.dumps(built.events))
    for row, hand in zip(events["transitions"], hand_events["transitions"]):
        row["placement"] = hand["placement"]  # pretend the engine copied the placement notes
    assert "transitions[].placement" not in parity_v008.observed_intended(events, hand_events, built.config,
                                                                            hand_config)


def test_s06_b_is_part_of_the_parity(parity_pair) -> None:
    built, hand_events, hand_config = parity_pair
    row = next(d for d in built.config["dialogue"] if d["id"] == "S06_B")
    hand = next(d for d in hand_config["dialogue"] if d["id"] == "S06_B")
    assert row["timing_audio"]["sha256"] == hand["audio"]["sha256"]
    assert len(row["segments"]) == 3 and sum(s["duration_frames"] for s in row["segments"]) == hand["duration_frames"]
    assert row["words"] == hand["words"]
    config = json.loads(json.dumps(built.config))
    next(d for d in config["dialogue"] if d["id"] == "S06_B")["timing_audio"]["sha256"] = "0" * 64
    assert parity_v008.compare_config(config, hand_config)


def test_the_parity_comparison_detects_a_real_difference(parity_pair) -> None:
    built, hand_events, hand_config = parity_pair
    events = json.loads(json.dumps(built.events))
    events["transitions"][2]["frames"] += 2
    events["icon_events"][3]["frame"] += 1
    events["transitions"][6]["outgoing_tail"]["tail_frames_available"] -= 1
    diffs = parity_v008.compare_events(events, hand_events)
    assert len(diffs) >= 3
    config = json.loads(json.dumps(built.config))
    config["dialogue"][4]["words"][0]["startF"] += 1
    assert parity_v008.compare_config(config, hand_config)
