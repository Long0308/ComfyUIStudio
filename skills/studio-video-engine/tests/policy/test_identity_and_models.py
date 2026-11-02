"""Guards 2 and 3: identity source allow-list and model policy. CPU only."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.comfy.guards import ClassPolicy, check_graph
from engine.core.errors import Refused
from engine.policy import identity_guard, model_policy

ROOT = Path(__file__).resolve().parents[2]
GOOD, BAD = "1" * 64, "2" * 64
DOMAIN = {"identity_guard": {"enabled": True, "roles": ["face", "identity"],
                             "allowed_refs": [{"name": "anchor", "path": "x.png", "sha256": GOOD}]},
          "model_policy": {"enabled": True, "banned_models": ["flux-2-klein-4b-fp8"],
                           "roles": {"still_base": ["flux2_dev_fp8mixed"]}}}


def real(name):
    return json.loads((ROOT / "domains" / f"{name}.json").read_text("utf-8"))


def test_identity_allowed_ref_passes_and_other_roles_are_ignored():
    refs = [{"role": "face", "path": "a.png", "sha256": GOOD}, {"role": "anchor", "path": "s.png", "sha256": BAD}]
    assert identity_guard.check_refs(DOMAIN, refs, where="t") == 1


def test_generated_scene_still_as_identity_is_refused_with_clear_error():
    with pytest.raises(Refused) as caught:
        identity_guard.check_refs(DOMAIN, [{"role": "face", "path": "S05F_c02.png", "sha256": BAD}], where="export-gui S05F")
    text = str(caught.value)
    assert text.startswith("IDENTITY_SOURCE_REFUSED") and "S05F_c02.png" in text and "generated scene still" in text


def test_identity_guard_off_for_other_domains():
    assert identity_guard.check_refs({}, [{"role": "face", "path": "q", "sha256": BAD}], where="t") == 0


def test_newtecons_allow_list_seeded_from_anchor_keep_sets_and_the_42():
    guard = real("newtecons_live_action")["identity_guard"]
    names = [row["name"] for row in guard["allowed_refs"]]
    assert guard["enabled"] is True
    assert sum(n.startswith("42_anh_goc/") for n in names) == 42
    assert "CHAR_08_FACE_ANCHOR_USER_APPROVED" in names
    assert sum(n.startswith("FACESET-CODEX-CHAR_08-V001/") for n in names) == 6
    assert sum(n.startswith("FACESET-CODEX-CHAR_06-V001/") for n in names) == 7
    assert all(len(r["sha256"]) == 64 and r["path"] for r in guard["allowed_refs"])


def test_export_gui_binding_roles_are_checked(tmp_path):
    from engine.gui_export import export
    with pytest.raises(Refused) as caught:
        export.check_identity_bindings(DOMAIN, [{"role": "face", "path": "S05F_c02.png", "sha256": BAD, "ports": []}], shot="S05F")
    assert "IDENTITY_SOURCE_REFUSED" in str(caught.value)


def graph(model):
    return {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": model}},
            "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "a"}}}


def test_banned_model_in_anchor_graph_is_rejected():
    with pytest.raises(Refused) as caught:
        model_policy.check_anchor_graph(DOMAIN, graph("flux-2-klein-4b-fp8.safetensors"), where="anchor")
    assert "MODEL_POLICY_REFUSED" in str(caught.value) and "flux-2-klein-4b-fp8" in str(caught.value)
    assert model_policy.check_anchor_graph(DOMAIN, graph("flux2_dev_fp8mixed.safetensors"), where="anchor")


def test_graph_validator_wires_the_policy_but_only_when_given_the_domain():
    pol = ClassPolicy.from_domain({"forbidden_node_classes": [], "forbid_partner_nodes": True, **DOMAIN})
    with pytest.raises(Refused):
        check_graph(None, graph("flux-2-klein-4b-fp8.safetensors"), pol)
    check_graph(None, graph("flux2_dev_fp8mixed.safetensors"), pol)
    plain = ClassPolicy.from_domain({"forbidden_node_classes": [], "forbid_partner_nodes": True})
    check_graph(None, graph("flux-2-klein-4b-fp8.safetensors"), plain)  # no policy block: unchanged


def test_newtecons_model_policy_roles():
    policy = real("newtecons_live_action")["model_policy"]
    assert policy["roles"]["still_base"] == ["flux2_dev_fp8mixed", "qwen_image_2512", "qwen_image_edit_2511"]
    assert "krea2_turbo" in policy["roles"]["identity"] and "bfs_head_swap_v1.1_krea2" in policy["roles"]["identity"]
    assert "flux-2-klein-4b-fp8" in policy["banned_models"]


def test_jenniejoy_domain_has_no_new_blocks_and_its_graphs_are_unchanged():
    jj = real("jenniejoy_cartoon_3d")
    assert not {"final_gate", "identity_guard", "model_policy"} & set(jj)
    pol = ClassPolicy.from_domain(jj)
    assert pol.banned_models == frozenset()
    check_graph(None, graph("flux-2-klein-4b-fp8.safetensors"), pol)


TIERED = {"identity_guard": {"enabled": True, "roles": ["face"], "allowed_refs": [
    {"name": "canon-one", "path": "c.png", "sha256": GOOD, "tier": "canon"},
    {"name": "keep-one", "path": "k.png", "sha256": "3" * 64, "tier": "qa_keep"}]}}


def test_canon_ref_has_no_warning_and_qa_keep_ref_passes_with_a_warning_field(capsys):
    refs = [{"role": "face", "path": "c.png", "sha256": GOOD}, {"role": "face", "path": "k.png", "sha256": "3" * 64}]
    assert identity_guard.check_refs(TIERED, refs, where="h3 prepare S01") == 2
    report = {row["name"]: row for row in identity_guard.listed_report(TIERED, refs)}
    assert report["canon-one"]["identity_tier"] == "canon" and "warning" not in report["canon-one"]
    assert report["keep-one"]["identity_tier"] == "qa_keep" and report["keep-one"]["warning"] == "QA proposal, not user canon"
    lines = [x for x in capsys.readouterr().err.splitlines() if x.startswith("WARNING")]
    assert len(lines) == 1 and "keep-one" in lines[0] and "h3 prepare S01" in lines[0]


def test_unlisted_ref_is_still_refused_with_tiers():
    with pytest.raises(Refused) as caught:
        identity_guard.check_refs(TIERED, [{"role": "face", "path": "S05F_c02.png", "sha256": BAD}], where="t")
    assert "IDENTITY_SOURCE_REFUSED" in str(caught.value)


def test_missing_or_unknown_tier_fails_safe_to_qa_keep():
    odd = {"identity_guard": {"enabled": True, "roles": ["face"],
                              "allowed_refs": [{"name": "n", "path": "p", "sha256": GOOD}]}}
    assert identity_guard.listed_report(odd, [{"path": "p", "sha256": GOOD}])[0]["identity_tier"] == "qa_keep"


def test_newtecons_tiers_canon_42_plus_anchor_and_qa_keep_13():
    rows = real("newtecons_live_action")["identity_guard"]["allowed_refs"]
    canon = [r for r in rows if r["tier"] == "canon"]
    keep = [r for r in rows if r["tier"] == "qa_keep"]
    assert len(canon) == 43 and len(keep) == 13
    assert all(r["name"].startswith("42_anh_goc/") or "USER_APPROVED" in r["name"] for r in canon)
    assert all(r["name"].startswith("FACESET-CODEX-CHAR_0") for r in keep)


def test_export_gui_receipt_meta_carries_the_tier_report():
    from engine.gui_export import export
    refs = [{"role": "face", "path": "k.png", "sha256": "3" * 64, "ports": []}]
    assert export.check_identity_bindings(TIERED, refs, shot="S05F") == 1
