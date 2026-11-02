"""T-E42: preset suitability, the legacy dip_white alias, the framing warning, planned presets and the schema.
"""

from __future__ import annotations

import json

import pytest

from editorial_fixtures import Inputs
from engine.core.errors import Refused
from preset_fixtures import (SKILL, CATALOG, PRESETS, GENEROUS, use, record_at)


@pytest.fixture()
def inputs(tmp_path) -> Inputs:
    return Inputs(tmp_path)


# ---- picture / graphic suitability ----------------------------------------------------------------------
def test_a_graphic_only_preset_is_refused_between_two_picture_shots_even_when_they_agree(inputs: Inputs) -> None:
    for name in ("card_slide", "plate_in"):
        inputs.row(390).update({"type": name, "frames": 6, "continuity": "agree", "direction": -1})
        with pytest.raises(Refused, match="graphic boundaries only"):
            inputs.build()


@pytest.mark.parametrize("name", ["push_slide", "crossfade", "zoom_out", "card_flip_3d"])
def test_a_picture_only_preset_is_refused_between_two_graphics(inputs: Inputs, name: str) -> None:
    inputs.row(2190).update({"type": name, "direction": 1, "continuity": "agree"})
    inputs.row(2190).pop("frames", None)
    with pytest.raises(Refused, match="picture shots only"):
        inputs.build(probe=GENEROUS)


def test_a_hard_cut_is_fine_between_two_graphics(inputs: Inputs) -> None:
    inputs.row(2190).update({"type": "cut", "frames": 0, "continuity": "agree"})
    assert record_at(inputs.build(), 2190)["preset"] == "cut"


def test_a_preset_for_both_kinds_works_on_a_graphic_pair(inputs: Inputs) -> None:
    inputs.row(2190).update({"type": "iris", "frames": 30, "params": {"disc_fade_frames": 4}})
    assert record_at(inputs.build(), 2190)["preset"] == "iris"


# ---- legacy alias ----------------------------------------------------------------------------------------
def test_dip_white_with_nine_frames_is_the_legacy_schedule_with_a_warning(inputs: Inputs) -> None:
    built = inputs.build()
    for boundary in (1010, 1310, 1610):
        record = record_at(built, boundary)
        assert (record["type"], record["preset"], record["renders_as"]) == (
            "dip_white", "dip_white_legacy", "dip_white")
        assert record["frames"] == 9 and len(record["schedule"]) == 9
        assert (record["start"], record["end_exclusive"]) == (boundary - 1, boundary + 8)
        assert record["outgoing_tail"]["tail_output_frames"] == 3
    legacy = [w for w in built.warnings if "legacy 9-frame dip_white" in w]
    assert len(legacy) == 3
    assert all("dip_white_legacy" in w and "approved 8-row schedule" in w for w in legacy)
    assert "boundary f1010 S03_B -> S04_A" in legacy[0]


def test_writing_dip_white_legacy_by_name_also_warns_but_keeps_its_name(inputs: Inputs) -> None:
    use(inputs, "dip_white_legacy")
    built = inputs.build(probe=GENEROUS)
    assert record_at(built)["type"] == "dip_white_legacy"
    assert any("legacy" in w and "f1010" in w for w in built.warnings)


@pytest.mark.parametrize("frames", [None, 8])
def test_dip_white_with_eight_frames_or_none_is_the_approved_schedule(inputs: Inputs, frames) -> None:
    for frame in (1010, 1310, 1610):
        row = inputs.row(frame)
        row.pop("frames")
        if frames is not None:
            row["frames"] = frames
    built = inputs.build()
    assert all(record_at(built, b)["preset"] == "dip_white" and record_at(built, b)["frames"] == 8
               for b in (1010, 1310, 1610))
    assert not any("legacy" in w for w in built.warnings)


# ---- framing warning ---------------------------------------------------------------------------------------
def test_a_visible_transition_on_same_framing_warns_but_still_builds(inputs: Inputs) -> None:
    inputs.row(390)["framing"] = "same_framing"        # a whip between S01_B and S02_A
    built = inputs.build()
    assert record_at(built, 390)["framing"] == "same_framing"
    warned = [w for w in built.warnings if "same seat/angle" in w]
    assert len(warned) == 1 and "f390" in warned[0] and "cut_push" in warned[0]


def test_the_framing_warning_covers_every_visible_preset(inputs: Inputs) -> None:
    for name in ("dip_black", "pan_motivated", "push_slide"):
        row = use(inputs, name, framing="same_framing")
        built = inputs.build(probe=GENEROUS)
        assert any("same seat/angle" in w and name in w for w in built.warnings), name
    del row["framing"]


@pytest.mark.parametrize("name", ["cut", "cut_push"])
def test_cut_and_cut_push_never_warn_on_same_framing(inputs: Inputs, name: str) -> None:
    use(inputs, name, framing="same_framing")
    assert not any("same seat/angle" in w for w in inputs.build(probe=GENEROUS).warnings)


def test_new_framing_never_warns_and_an_unknown_framing_is_a_schema_error(inputs: Inputs) -> None:
    inputs.row(390)["framing"] = "new_framing"
    assert not any("same seat/angle" in w for w in inputs.build().warnings)
    inputs.row(390)["framing"] = "sideways"
    with pytest.raises(Refused, match="boundaries.json is invalid"):
        inputs.build()


def test_the_framing_warning_is_not_raised_for_a_carry(inputs: Inputs) -> None:
    inputs.row(240)["framing"] = "same_framing"
    assert not any("same seat/angle" in w for w in inputs.build().warnings)


# ---- planned presets and the schema ------------------------------------------------------------------------
@pytest.mark.parametrize("name", [n for n, p in PRESETS.items() if p["status"] == "planned"])
def test_a_planned_preset_is_refused_with_a_clear_message(inputs: Inputs, name: str) -> None:
    inputs.row(2190).update({"type": name, "frames": 12})
    with pytest.raises(Refused, match=f"preset '{name}' is planned, not implemented"):
        inputs.build()


def test_the_schema_type_enum_equals_the_ready_presets_of_the_catalog() -> None:
    schema = json.loads((SKILL / "schemas" / "boundaries.schema.json").read_text("utf-8"))
    enum = schema["$defs"]["boundary"]["properties"]["type"]["enum"]
    assert sorted(enum) == sorted(n for n, p in PRESETS.items() if p["status"] == "ready")
    assert len(enum) == len(set(enum))


def test_the_schema_makes_frames_direction_and_frame_optional_and_knows_framing() -> None:
    schema = json.loads((SKILL / "schemas" / "boundaries.schema.json").read_text("utf-8"))
    boundary = schema["$defs"]["boundary"]
    assert not {"frames", "direction", "frame"} & set(boundary["required"])
    assert boundary["properties"]["framing"]["enum"] == ["same_framing", "new_framing"]


def test_the_type_properties_are_derived_from_the_catalog() -> None:
    from engine.editorial import transitions
    ready = {n: p for n, p in PRESETS.items() if p["status"] == "ready"}
    assert set(transitions.TYPE_PROPERTIES) == set(transitions.TYPES) == set(ready)
    assert all(transitions.TYPE_PROPERTIES[n] == {"shows_both": p["shows_both"], "tail_only": p["tail_only"]}
               for n, p in ready.items())
    assert transitions.BOTH_SHOTS_TYPES == {n for n, p in ready.items() if p["shows_both"]}
    assert transitions.TAIL_ONLY_TYPES == {n for n, p in ready.items() if p["tail_only"]}


def test_the_legacy_dip_schedule_constant_is_the_catalog_schedule() -> None:
    from engine.editorial import transitions
    assert list(transitions.DIP_WHITE_SCHEDULE) == PRESETS["dip_white_legacy"]["schedule"]


def test_every_ready_catalog_preset_has_the_fields_the_engine_reads() -> None:
    for name, p in PRESETS.items():
        assert {"status", "category", "renders_as", "shows_both", "tail_only", "tail_frames", "frames", "direction",
                "window", "params", "safe_for"} <= set(p), name
        assert p["category"] in {c["id"] for c in CATALOG["categories"]}
        assert p["tail_frames"] in ("none", "all", "half", "schedule")
        assert p["direction"] in ("none", "required", "optional")
        assert (p["tail_frames"] == "schedule") == ("schedule" in p), name


