"""``jjv plan explain`` units: slicing helpers, node keys, the cost table, and the input loader's refusals."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.plan.costs import load_costs
from engine.plan.load import load_inputs
from engine.plan.model import diff_parts, flatten, node_key, strip, why_text

import test_plan_support as S

COSTS = S.PLAN_DIR / "costs-v001.json"


# ---- model ------------------------------------------------------------------------------------------------------------
def test_strip_drops_sha_bound_paths_and_named_keys_without_mutating_the_input() -> None:
    """A file key beside its sha is dropped (the sha is the identity); one WITHOUT a sha is kept as written (N41c: an
    unidentified file reference is never silently ignored); a sibling that is not a 64-hex sha does not count."""
    sha = S.sha("c")
    doc = {"path": "a", "icon_path": "b", "keep": {"path": "c", "sha256": sha, "method": "m"},
           "bogus": {"path": "d", "sha256": "x"}, "list": [{"audio": 1, "n": 2}]}
    before = copy.deepcopy(doc)
    assert strip(doc, frozenset({"method", "audio"})) == {"path": "a", "icon_path": "b", "keep": {"sha256": sha},
                                                          "bogus": {"path": "d", "sha256": "x"}, "list": [{"n": 2}]}
    assert doc == before


def test_flatten_and_diff_name_the_exact_leaf() -> None:
    old = {"shot:S1": {"words": [{"startF": 10}, {"startF": 20}]}, "gone": 1, "same": [1, 2]}
    new = {"shot:S1": {"words": [{"startF": 10}, {"startF": 23}]}, "added": 2, "same": [1, 2]}
    assert flatten(old["shot:S1"], "shot:S1") == {"shot:S1.words[0].startF": 10, "shot:S1.words[1].startF": 20}
    paths = [c.path for c in diff_parts(old, new)]
    assert paths == ["+added", "-gone", "shot:S1.words[1].startF"]
    assert why_text(diff_parts(old, new), limit=1)[-1] == "(+2 more leaves)"


def test_node_key_moves_with_a_part_a_pin_and_the_kind_only() -> None:
    k = node_key("composite.segment", {"a": 1}, {"p": "1"})
    assert k == node_key("composite.segment", {"a": 1}, {"p": "1"})
    assert len({k, node_key("composite.segment", {"a": 2}, {"p": "1"}), node_key("composite.segment", {"a": 1}, {"p": "2"}),
                node_key("mux", {"a": 1}, {"p": "1"})}) == 4


# ---- cost table -------------------------------------------------------------------------------------------------------
def test_shipped_cost_table_tags_every_number_and_never_invents_one() -> None:
    costs = load_costs(COSTS)
    assert costs.version == "v001" and len(costs.sha256) == 64
    for name, entry in costs.entries.items():
        assert entry["basis"] in ("measured", "derived", "unmeasured") and entry["source"], name
        assert (entry["seconds_per_unit"] is None) == (entry["basis"] == "unmeasured"), name
    # the audit numbers the planner prices from (ENGINE-AUDIT-2026-10-27 s3)
    assert costs.entries["composite.master.shot_frame"]["seconds_per_unit"] == 0.305
    assert costs.entries["composite.master.vector_frame"]["seconds_per_unit"] == 0.083
    assert costs.entries["film.downscale.2k"]["seconds_per_unit"] == 54.28
    assert costs.entries["mux.review"]["seconds_per_unit"] == pytest.approx(2.01 + 0.88)
    assert costs.entries["upscale.chunks.native_frame"]["seconds_per_unit"] == 9.1
    assert costs.entries["audio.mix"]["basis"] == "unmeasured"      # "jjv audio mix itself chua do"


def test_price_combines_bases_and_one_unmeasured_entry_makes_it_unmeasured() -> None:
    costs = load_costs(COSTS)
    est = costs.price([("composite.master.shot_frame", 100), ("mux.review", 1)])
    assert est.seconds == pytest.approx(30.5 + 2.89) and est.basis == "measured"
    assert costs.price([("composite.review.frame", 100)]).basis == "derived"
    unknown = costs.price([("composite.review.frame", 100), ("audio.mix", 1)])
    assert unknown.seconds is None and unknown.basis == "unmeasured"
    assert costs.price([("motion.h3.native_frame", None)]).seconds is None
    with pytest.raises(Refused, match="no entry"):
        costs.price([("nonsense", 1)])


@pytest.mark.parametrize("edit, message", [
    (lambda d: d.update(schema="x"), "schema"),
    (lambda d: d["entries"]["qa.av"].update(seconds_per_unit=3.0), "unmeasured"),
    (lambda d: d["entries"]["mux.review"].update(source=""), "source"),
    (lambda d: d["entries"]["mux.review"].update(basis="guess"), "basis"),
])
def test_a_cost_table_that_breaks_its_own_rules_is_refused(tmp_path: Path, edit, message: str) -> None:
    doc = json.loads(COSTS.read_text("utf-8"))
    edit(doc)
    path = tmp_path / "costs.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(Refused, match=message):
        load_costs(path)


# ---- loader -----------------------------------------------------------------------------------------------------------
PINS = ["compositor_sha256", "remotion_version", "chromium_gl"]


def test_loader_refuses_a_missing_directory_two_configs_and_a_wrong_descriptor_schema(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="not a directory"):
        load_inputs(tmp_path / "nope", pin_keys=PINS)
    d = S.write_version(tmp_path, "two", S.base_config())
    (d / "config" / "review-config-y.json").write_text("{}", encoding="utf-8")
    with pytest.raises(Refused, match="name the config"):
        load_inputs(d, pin_keys=PINS)
    bad = S.write_version(tmp_path, "bad", S.base_config())
    (bad / "plan-inputs.json").write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    with pytest.raises(Refused, match="schema must be"):
        load_inputs(bad, pin_keys=PINS)
    with pytest.raises(Refused, match="no review config"):
        load_inputs(tmp_path, pin_keys=PINS)


def test_loader_refuses_a_receipt_whose_mix_plan_sha_lies_and_warns_when_the_plan_is_gone(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(S.mix_plan()), encoding="utf-8")
    d = S.write_version(tmp_path, "r", S.base_config())
    receipt = {"separate_deliverables": {"mix_wav": {"plan": str(plan), "plan_sha256": "0" * 64, "sha256": S.sha("w")}}}
    (d / "RECEIPT.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(Refused, match="differs from the"):
        load_inputs(d, pin_keys=PINS)
    receipt["separate_deliverables"]["mix_wav"]["plan_sha256"] = sha256_file(plan)
    (d / "RECEIPT.json").write_text(json.dumps(receipt), encoding="utf-8")
    ok = load_inputs(d, pin_keys=PINS)
    assert ok.mix_plan["bed"]["label"] == "bed-A" and ok.mix_wav_sha256 == S.sha("mix-bed-A")   # the plan's own mix sha first
    plan.unlink()
    gone = load_inputs(d, pin_keys=PINS)
    assert gone.mix_plan is None and any("not on disk" in w for w in gone.warnings)
    assert gone.mix_wav_sha256 == S.sha("w")                          # then the receipt's


def test_loader_reads_pins_from_the_render_record_and_never_pins_the_render_script(tmp_path: Path) -> None:
    d = S.write_version(tmp_path, "p", S.base_config(), record=S.record("c9"))
    inputs = load_inputs(d, pin_keys=PINS)
    assert inputs.pins == {"compositor_sha256": S.sha("c9"), "remotion_version": "4.0.536", "chromium_gl": "swiftshader"}
