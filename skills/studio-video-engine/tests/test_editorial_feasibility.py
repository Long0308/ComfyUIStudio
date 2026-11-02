"""T-E42: per-boundary preset feasibility on the real ep04 tail handles, and the read-only presets CLI.
"""

from __future__ import annotations

import json

import pytest

from editorial_fixtures import Inputs, fake_probe, probe_returning
from engine.core.errors import Refused
from preset_fixtures import (PRESETS, use, record_at)

pytestmark = pytest.mark.usefixtures("legacy_ep04_cli")  # the live ep04 moved to its 3444 f contract


@pytest.fixture()
def inputs(tmp_path) -> Inputs:
    return Inputs(tmp_path)


# ---- feasibility on the real ep04 handles --------------------------------------------------------------------
def _table(inputs: Inputs, **kwargs) -> dict:
    return {row["boundary"]: row for row in inputs.table(**kwargs)["boundaries"]}


@pytest.mark.parametrize("boundary,native_tail,max_frames", [(1010, 7, 8), (1310, 13, 16), (1610, 15, 18)])
def test_feasibility_follows_the_native_tail_handle(inputs: Inputs, boundary: int, native_tail: int,
                                                    max_frames: int) -> None:
    row = _table(inputs)[boundary]
    assert row["tail_handle"]["tail_frames_available"] == native_tail
    crossfade = row["presets"]["crossfade"]
    assert crossfade["max_frames"] == max_frames and crossfade["have_native_frames"] == native_tail
    assert crossfade["frames"] == 12 and crossfade["needs_tail_frames"] == 10
    assert crossfade["available"] is (native_tail >= 10) and (crossfade["reason"] is None) is crossfade["available"]
    for name in ("wipe_linear", "cloud", "bubble", "clock_wipe", "push_slide"):
        assert row["presets"][name]["max_frames"] <= max_frames
    assert row["presets"]["wipe_linear"]["max_frames"] == max_frames


def test_feasibility_lists_every_ready_preset_and_marks_the_tail_free_ones_available(inputs: Inputs) -> None:
    row = _table(inputs)[1010]
    ready = {n for n, p in PRESETS.items() if p["status"] == "ready"}
    assert set(row["presets"]) == ready
    for name in ready:
        entry = row["presets"][name]
        assert {"available", "needs_tail_frames", "have_native_frames", "reason", "frames", "max_frames"} <= set(entry)
        if PRESETS[name]["tail_frames"] == "none":
            assert entry["needs_tail_frames"] == 0
    for name in ("cut_push", "whip", "bloom", "none"):
        assert row["presets"][name]["available"] is True and row["presets"][name]["reason"] is None


def test_feasibility_for_the_schedule_presets_uses_their_outgoing_tail_rows(inputs: Inputs) -> None:
    presets = _table(inputs)[1010]["presets"]
    assert presets["dip_white_legacy"]["needs_tail_frames"] == 3 and presets["dip_white_legacy"]["available"]
    assert presets["dip_white"]["needs_tail_frames"] == 1 and presets["dip_white"]["available"]
    assert presets["card_flip_3d"]["frames"] == 18 and presets["card_flip_3d"]["needs_tail_frames"] == 8
    assert presets["card_flip_3d"]["available"] is False and presets["card_flip_3d"]["max_frames"] == 16


def test_a_boundary_without_a_tail_clip_only_offers_the_tail_free_presets(inputs: Inputs) -> None:
    presets = _table(inputs)[390]["presets"]       # S01_B -> S02_A, no tail_clip declared
    for name, p in PRESETS.items():
        if p["status"] != "ready":
            continue
        entry = presets[name]
        if p["tail_frames"] == "none":
            assert entry["available"] is True, name
        else:
            assert entry["available"] is False and entry["have_native_frames"] is None, name
            assert "no GPU work is requested" in entry["reason"] and "no tail_clip" in entry["reason"], name


def test_the_table_can_be_narrowed_to_one_boundary(inputs: Inputs) -> None:
    by_frame = inputs.table(only="1010")["boundaries"]
    by_id = inputs.table(only="T1310")["boundaries"]
    assert [r["boundary"] for r in by_frame] == [1010] and [r["boundary"] for r in by_id] == [1310]
    with pytest.raises(Refused, match="no boundary"):
        inputs.table(only="9999")


def test_the_table_shows_eligibility_by_class_continuity_and_kind(inputs: Inputs) -> None:
    carry = _table(inputs)[240]["presets"]
    assert carry["none"]["eligible"] is True and carry["whip"]["eligible"] is False
    assert "carry" in carry["whip"]["eligible_reason"]
    mismatch = _table(inputs)[1010]["presets"]
    assert mismatch["crossfade"]["eligible"] is False
    assert "both sides in one frame" in mismatch["crossfade"]["eligible_reason"]
    assert mismatch["dip_black"]["eligible"] is True and mismatch["none"]["eligible"] is False
    graphics = _table(inputs)[2190]["presets"]
    assert graphics["card_slide"]["eligible"] is True and graphics["crossfade"]["eligible"] is False


def test_the_table_uses_the_real_probe_values_it_is_given(inputs: Inputs) -> None:
    row = _table(inputs, probe=probe_returning(140))[1010]
    assert row["tail_handle"]["tail_frames_available"] == 40
    assert row["presets"]["crossfade"]["available"] is True


def test_feasibility_matches_what_the_build_accepts(inputs: Inputs) -> None:
    """The table and the validator share one rule: max_frames builds, max_frames + 1 is refused."""
    for name in ("crossfade", "wipe_linear", "blinds", "zoom_out", "card_flip_3d"):
        top = _table(inputs)[1010]["presets"][name]["max_frames"]
        step = 2 if PRESETS[name]["frames"].get("even") else 1
        use(inputs, name, frames=top)
        inputs.build(probe=fake_probe)
        if top + step <= PRESETS[name]["frames"]["max"]:
            use(inputs, name, frames=top + step)
            with pytest.raises(Refused, match="tail handle too short"):
                inputs.build(probe=fake_probe)


# ---- frame is optional; schedules are audited; the read-only CLI -----------------------------------------------
def test_a_row_may_leave_out_its_frame_it_is_where_the_incoming_shot_starts(inputs: Inputs) -> None:
    del inputs.row(390)["frame"]
    record = record_at(inputs.build(), 390)
    assert record["boundary"] == 390 and record["id"] == "T390"


def test_every_schedule_preset_passes_the_schedule_audit() -> None:
    from engine.editorial import transitions
    transitions.audit_dip_schedule()   # one pure frame, consecutive t, shots on the right side of the boundary


def test_the_cli_without_an_episode_prints_the_catalog(capsys) -> None:
    from engine.editorial import presets_cli
    assert presets_cli.main([]) == 0
    out = json.loads(capsys.readouterr().out)
    names = [p["name"] for p in out["presets"]]
    assert names == list(PRESETS) and out["presets"][names.index("glitch")]["status"] == "planned"


@pytest.mark.skipif(not __import__("shutil").which("ffprobe"), reason="ffprobe absent")
def test_the_cli_prints_the_feasibility_table_of_one_boundary(capsys) -> None:
    from editorial_fixtures import EPISODE, LOGO, REAL_BOUNDARIES
    from engine.editorial import presets_cli
    argv = ["--episode", EPISODE, "--boundaries", str(REAL_BOUNDARIES), "--allow-outside", str(LOGO),
            "--boundary", "T1010"]
    assert presets_cli.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and [b["boundary"] for b in out["boundaries"]] == [1010]
    assert out["boundaries"][0]["presets"]["crossfade"]["max_frames"] == 8
    assert presets_cli.main(argv[:-1] + ["9999"]) == 1          # a rule failure: no such boundary
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert presets_cli.main(["--episode", "no-such-episode", "--boundaries", str(REAL_BOUNDARIES)]) == 2
