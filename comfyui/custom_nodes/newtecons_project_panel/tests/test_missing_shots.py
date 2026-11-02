"""Missing-video inventory and queued snapshot race checks; CPU-only."""
import json
from pathlib import Path

import pytest
from test_panel import core, project, settings


def mark(values, item, payload=b"cpu fixture video"):
    directory = values["output_dir"] / "newtecons-panel"
    directory.mkdir(exist_ok=True)
    output = directory / f"{item['shot']}.mp4"
    output.write_bytes(payload)
    marker = directory / f"{item['render_key']}.json"
    marker.write_text(json.dumps({"render_key": item["render_key"], "output": str(output),
                                  "sha256": core.sha256(output), "approved": False}), encoding="utf8")
    return output, marker


def auto_values(project):
    values = settings(project)
    values.update(run_mode=core.MODES[1], scene="ALL")
    return values


def test_missing_inventory_counts_order_and_scene_filter_without_staging(project):
    values = auto_values(project)
    report = core.missing_shots(**values)
    assert (report["missing"], report["total"], report["completed"]) == (2, 2, 0)
    assert [item["shot"] for item in report["shots"]] == ["S02_A", "S03_A"]
    assert report["shot"] == "S02_A"
    assert report["technical_render_only"] and report["approved"] is False
    assert not list(values["input_dir"].iterdir())
    assert not list(values["output_dir"].iterdir())
    values["scene"] = "S03"
    subset = core.missing_shots(**values)
    assert subset["total"] == 1 and subset["shot"] == "S03_A"


@pytest.mark.parametrize("approved", [False, True])
def test_hash_valid_render_skipped_with_or_without_approval(project, approved):
    values = auto_values(project)
    original = core.missing_shots(**values)
    for item in original["shots"]:
        _, marker = mark(values, item)
        data = json.loads(marker.read_text(encoding="utf8"))
        data["approved"] = approved
        marker.write_text(json.dumps(data), encoding="utf8")
    report = core.missing_shots(**values)
    assert (report["missing"], report["completed"], report["total"]) == (0, 2, 2)
    assert report["pending"] is False and report["shot"] is None
    assert core.prepare(**values) is None


@pytest.mark.parametrize("damage", ["corrupt", "deleted", "bad_json", "key_mismatch", "outside"])
def test_stale_or_forged_receipt_never_skips(project, damage):
    values = auto_values(project)
    first = core.missing_shots(**values)["shots"][0]
    output, marker = mark(values, first)
    if damage == "corrupt":
        output.write_bytes(b"changed")
    elif damage == "deleted":
        output.unlink()
    elif damage == "bad_json":
        marker.write_text("{", encoding="utf8")
    else:
        data = json.loads(marker.read_text(encoding="utf8"))
        if damage == "key_mismatch":
            data["render_key"] = "0" * 64
        else:
            external = Path(values["script_path"])
            data.update(output=str(external), sha256=core.sha256(external))
        marker.write_text(json.dumps(data), encoding="utf8")
    report = core.missing_shots(**values)
    assert report["shot"] == first["shot"] and report["missing"] == 2


def test_snapshot_binds_selected_shot_even_if_an_earlier_shot_is_missing(project):
    values = auto_values(project)
    second = core.missing_shots(**values)["shots"][1]
    result = core.prepare(**values, auto_shot=second["shot"], auto_render_key=second["render_key"])
    assert result["shot"] == "S03_A" and result["render_key"] == second["render_key"]


def test_snapshot_refuses_changed_script_before_staging(project):
    values = auto_values(project)
    selected = core.missing_shots(**values)["shots"][0]
    Path(values["script_path"]).write_text("changed after submit", encoding="utf8")
    with pytest.raises(ValueError, match="snapshot inputs changed"):
        core.prepare(**values, auto_shot=selected["shot"], auto_render_key=selected["render_key"])
    assert not list(values["input_dir"].iterdir())


def test_snapshot_completed_while_queued_fails_before_gpu(project):
    values = auto_values(project)
    selected = core.missing_shots(**values)["shots"][0]
    mark(values, selected)
    with pytest.raises(ValueError, match="AUTO_ALREADY_RENDERED"):
        core.prepare(**values, auto_shot=selected["shot"], auto_render_key=selected["render_key"])


def test_snapshot_fields_do_not_change_graph_context_key():
    graph = {"1": {"class_type": "NewteconsProjectPanel", "inputs": {"min_duration": 4}}}
    bound = json.loads(json.dumps(graph))
    bound["1"]["inputs"].update(auto_shot="S03_A", auto_render_key="a" * 64)
    assert core.context_hash(bound) == core.context_hash(graph)


@pytest.mark.parametrize("shot,key", [("S02_A", ""), ("", "a" * 64), ("../x", "a" * 64), ("S02_A", "bad")])
def test_partial_or_unsafe_binding_refused(project, shot, key):
    with pytest.raises(ValueError, match="snapshot"):
        core.prepare(**auto_values(project), auto_shot=shot, auto_render_key=key)
