"""CPU-only GUI export contracts, using a fake ComfyUI tree and object_info.

This file also runs directly from proposed/: untouched dependencies come from the
read-only skill; engine.gui_export comes from this staged overlay. No ComfyUI
server, Docker, HTTP POST, CUDA or production asset is used.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROPOSED = Path(__file__).resolve().parents[1]
WORKSPACE = next(p for p in PROPOSED.parents if (p / ".agents/skills/studio-video-engine").is_dir())
SKILL = WORKSPACE / ".agents/skills/studio-video-engine"
sys.path.insert(0, str(SKILL))
import engine  # noqa: E402
engine.__path__.insert(0, str(PROPOSED / "engine"))

from engine.core.errors import Refused  # noqa: E402
from engine.gui_export.export import export_gui  # noqa: E402

NTC = "newtecons_live_action"
JJ = "jenniejoy_cartoon_3d"
POLICY = {
    NTC: {"folder": "ProjectStudio5 - Film Newtecons", "image_folder": "01 Workflow Image", "video_folder": "02 Workflow Video"},
    JJ: {"folder": "JennieJoyKids", "image_folder": "01 Workflow Image", "video_folder": "02 Workflow Video"},
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
    return {"path": str(path), "sha256": _sha(path)}


def object_info(class_type):
    specs = {
        "LoadImage": {"input": {"required": {"image": [["placeholder.png"], {}]}}, "output": ["IMAGE", "MASK"], "output_name": ["IMAGE", "MASK"]},
        "LoadAudio": {"input": {"required": {"audio": [["placeholder.wav"], {}]}}, "output": ["AUDIO"], "output_name": ["AUDIO"]},
        "TestRender": {"input": {"required": {"image": ["IMAGE"], "audio": ["AUDIO"], "seed": ["INT", {"default": 1, "control_after_generate": True}], "prompt": ["STRING", {}]}}, "output": ["IMAGE"], "output_name": ["IMAGE"]},
        "SaveImage": {"input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING", {}]}}, "output": [], "output_name": []},
    }
    return copy.deepcopy(specs[class_type])


@pytest.fixture
def case(tmp_path):
    episode = tmp_path / "episode"
    episode.mkdir()
    comfy = tmp_path / "fake-comfy"
    (comfy / "input").mkdir(parents=True)
    workflows = comfy / "user/default/workflows"
    workflows.mkdir(parents=True)
    anchor = episode / "approved-anchor.png"
    anchor.write_bytes(b"synthetic anchor fixture, never a production image")
    wav = episode / "approved-dialogue.wav"
    wav.write_bytes(b"synthetic dialogue fixture, never a production wav")
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "empty.png"}},
        "2": {"class_type": "LoadAudio", "inputs": {"audio": "empty.wav"}},
        "3": {"class_type": "TestRender", "inputs": {"image": ["1", 0], "audio": ["2", 0], "seed": 42, "prompt": "real approved shot prompt"}},
        "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "approved_preview"}},
    }
    graph_ref = _json(episode / "graph.api.json", graph)
    receipt = _json(episode / "preparation.json", {"domain": NTC, "shot": "S02_A", "status": "PREPARED", "approved": True})
    prepared = {
        "graph": graph, "graph_path": graph_ref["path"], "source_graph_sha256": graph_ref["sha256"],
        "bindings": [
            {"path": str(anchor), "sha256": _sha(anchor), "ports": [("1", "image")], "role": "anchor", "input_name": "empty.png"},
            {"path": str(wav), "sha256": _sha(wav), "ports": [("2", "audio")], "role": "wav", "input_name": "empty.wav"},
        ],
        "receipts": {"preparation": receipt}, "shot": "S02_A", "tier": "preview",
    }
    ctx = SimpleNamespace(domain_id=NTC, episode_id="fixture-episode", root=episode, machine={"comfy": {"root": str(comfy)}})
    return SimpleNamespace(ctx=ctx, prepared=prepared, comfy=comfy, workflows=workflows, out=episode / "gui-export", anchor=anchor, wav=wav)


def _export(case, **kwargs):
    return export_gui(case.ctx, case.prepared, kind="video", out=case.out, object_info=object_info, policy=POLICY, **kwargs)


def _gui(result):
    return json.loads(Path(result["workflow"]).read_text(encoding="utf-8"))


def _refresh_graph(case):
    ref = _json(Path(case.prepared["graph_path"]), case.prepared["graph"])
    case.prepared["source_graph_sha256"] = ref["sha256"]


def test_filled_workflow_preserves_links_widgets_and_step_panel_metadata(case):
    result = _export(case)
    gui = _gui(result)
    assert result["status"] == "EXPORTED" and result["rendered"] is False
    expected_dir = case.workflows / POLICY[NTC]["folder"] / POLICY[NTC]["video_folder"] / "UAT"
    assert Path(result["workflow"]).parent == expected_dir
    assert result["workflow_sha256"] == _sha(result["workflow"])
    assert gui["version"] == 0.4
    nodes = {node["id"]: node for node in gui["nodes"]}
    for node_id, source, extension, key in [(1, case.anchor, ".png", "image"), (2, case.wav, ".wav", "audio")]:
        name = f"{NTC}__S02_A__{_sha(source)[:12]}__{source.name}"
        assert nodes[node_id]["widgets_values_named"][key] == name
        assert nodes[node_id]["widgets_values"][0] == name
        assert (case.comfy / "input" / name).read_bytes() == source.read_bytes()
    assert nodes[3]["widgets_values_named"]["seed"] == 42
    assert "fixed" in nodes[3]["widgets_values"]
    assert nodes[3]["widgets_values_named"]["prompt"] == "real approved shot prompt"
    assert {(row[1], row[2], row[3], row[5]) for row in gui["links"]} == {(1, 0, 3, "IMAGE"), (2, 0, 3, "AUDIO"), (3, 0, 4, "IMAGE")}
    meta = gui["extra"]["newtecons"]
    assert meta["domain"] == NTC and meta["shot"] == "S02_A"
    assert meta["receipt_shas"]["preparation"] == case.prepared["receipts"]["preparation"]["sha256"]
    assert {row["role"] for row in meta["inputs"]} == {"anchor", "wav"}
    assert all(row["type"] == "input" and row["subfolder"] == "" and len(row["sha256"]) == 64 for row in meta["inputs"])
    assert meta["outputs"] == [], "an export must not invent a rendered result"
    assert meta["output_targets"], "step panel must have output targets before a user runs the graph"
    log = [json.loads(row) for row in (case.out / "steplog.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(log) == 1 and log[0]["status"] == "COMPLETE"
    assert log[0]["inputs"] and log[0]["outputs"]


@pytest.mark.parametrize("target", ["anchor", "wav", "receipt", "graph"])
def test_hash_drift_refused_before_any_workflow_or_input_is_written(case, target):
    path = {"anchor": case.anchor, "wav": case.wav, "receipt": Path(case.prepared["receipts"]["preparation"]["path"]), "graph": Path(case.prepared["graph_path"])}[target]
    if target == "graph":
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["3"]["inputs"]["prompt"] = "tampered prompt"
        _json(path, changed)
    else:
        path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(Refused):
        _export(case)
    assert not list((case.comfy / "input").iterdir())
    assert not list(case.workflows.rglob("*.json"))


def test_unbound_loader_refused_before_copy(case):
    case.prepared["graph"]["5"] = {"class_type": "LoadImage", "inputs": {"image": "not-approved.png"}}
    _refresh_graph(case)
    with pytest.raises(Refused):
        _export(case)
    assert not list((case.comfy / "input").iterdir())


def test_binding_cannot_target_nonexistent_loader_port(case):
    case.prepared["bindings"][0]["ports"] = [("3", "prompt")]
    with pytest.raises(Refused):
        _export(case)
    assert not list((case.comfy / "input").iterdir())


def test_wrong_workflows_root_refused(case):
    other = case.workflows.parent / "foreign-project"
    with pytest.raises(Refused):
        _export(case, workflows_root=other)
    assert not other.exists()


def test_existing_hash_named_input_is_never_overwritten(case):
    target = case.comfy / "input" / f"{NTC}__S02_A__{_sha(case.wav)[:12]}__{case.wav.name}"
    target.write_bytes(b"collision or corrupted prior copy")
    with pytest.raises(Refused):
        _export(case)
    assert target.read_bytes() == b"collision or corrupted prior copy"
    assert not list(case.workflows.rglob("*.json"))


def test_repeated_export_reuses_identical_inputs_and_workflow(case):
    first = _export(case)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in (case.comfy / "input").iterdir()}
    second = _export(case)
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in (case.comfy / "input").iterdir()}
    assert first["workflow"] == second["workflow"]
    assert first["workflow_sha256"] == second["workflow_sha256"]
    assert before == after


def test_foreign_output_folder_is_normalized_or_refused(case):
    case.prepared["graph"]["4"]["inputs"]["filename_prefix"] = "JennieJoyKids/private/foreign_preview"
    _refresh_graph(case)
    try:
        result = _export(case)
    except Refused:
        assert not list(case.workflows.rglob("*.json"))
        return
    saved = next(n for n in _gui(result)["nodes"] if n["type"] == "SaveImage")
    prefix = saved["widgets_values_named"]["filename_prefix"]
    assert prefix.startswith(f"{NTC}/gui-uat/S02_A/preview/")
    assert "JennieJoyKids" not in prefix


def test_unknown_domain_refused(case):
    case.ctx.domain_id = "unknown_domain"
    with pytest.raises(Refused):
        _export(case)
    assert not list((case.comfy / "input").iterdir())


def test_domain_namespaces_share_no_input_or_workflow_paths(case):
    ntc = _export(case)
    case.ctx.domain_id = JJ
    case.out = case.ctx.root / "gui-export-jj"
    receipt_path = Path(case.prepared["receipts"]["preparation"]["path"])
    case.prepared["receipts"]["preparation"] = _json(receipt_path, {"domain": JJ, "shot": "S02_A", "status": "PREPARED", "approved": True})
    jj = _export(case)
    assert Path(jj["workflow"]).is_relative_to(case.workflows / POLICY[JJ]["folder"])
    assert Path(ntc["workflow"]).is_relative_to(case.workflows / POLICY[NTC]["folder"])
    assert jj["workflow"] != ntc["workflow"]
    names = {p.name for p in (case.comfy / "input").iterdir()}
    assert sum(name.startswith(NTC + "__") for name in names) == 2
    assert sum(name.startswith(JJ + "__") for name in names) == 2
    assert _gui(jj)["extra"]["newtecons"]["domain"] == JJ


def test_images_export_uses_separate_workflow_folder(case):
    result = export_gui(case.ctx, case.prepared, kind="image", out=case.out, object_info=object_info, policy=POLICY)
    assert Path(result["workflow"]).parent == case.workflows / POLICY[NTC]["folder"] / POLICY[NTC]["image_folder"] / "UAT"


@pytest.fixture
def prepared_video(case, monkeypatch):
    """Stub only H3's initial loader to exercise GUI's extra production gates.

    Pack domain/episode validation and pack approval checks remain real code.
    The deliberately incomplete receipt must never reach successful export.
    """
    from engine.gui_export import video

    base = case.ctx.root / "h3-prepared"
    folder = base / "S02_A"
    pack_path = case.ctx.root / "anchor-pack.json"
    pack = {"schema": "jjv/shot-anchor-pack/v1", "episode_id": case.ctx.episode_id, "domain": NTC, "shot": "S02_A", "status": "pending", "ready_for_graph": False, "storyboard_anchor": {"status": "pending"}}
    pack_ref = _json(pack_path, pack)
    receipt = {"schema": video.h3_prepare.SCHEMA, "episode_id": case.ctx.episode_id, "domain": NTC, "shot": "S02_A", "status": "PREPARED_NOT_SUBMITTED", "anchor_pack": pack_ref, "refs": [], "storyboard": {"pilot": False}}
    _json(folder / video.h3_prepare.PREPARATION_FILE, receipt)
    monkeypatch.setattr(video.h3_prepare, "load_prepared", lambda *_args, **_kw: [(folder, receipt, case.prepared["graph"])])
    return SimpleNamespace(case=case, video=video, base=base, folder=folder, receipt=receipt, pack=pack, pack_path=pack_path)


def test_video_gui_refuses_pending_storyboard_even_when_h3_pilot_would_allow_it(prepared_video):
    fixture = prepared_video
    with pytest.raises(Refused, match="STORYBOARD_PENDING"):
        fixture.video.load_video(fixture.case.ctx, fixture.base, "S02_A", "preview")
    assert not list(fixture.case.workflows.rglob("*.json"))


def test_video_gui_refuses_unapproved_body_reference(prepared_video):
    fixture = prepared_video
    fixture.pack["status"] = "approved"
    fixture.pack["ready_for_graph"] = True
    fixture.pack["storyboard_anchor"] = {"status": "approved"}
    fixture.pack["body_refs"] = [{"name": "unapproved body", "role": "body", "approval": "pending", "sha256": "a" * 64}]
    _json(fixture.pack_path, fixture.pack)
    with pytest.raises(Refused, match="ANCHOR_NOT_APPROVED"):
        fixture.video.load_video(fixture.case.ctx, fixture.base, "S02_A", "preview")


def test_video_gui_refuses_missing_listen_approval_evidence(prepared_video):
    fixture = prepared_video
    fixture.pack.update(status="approved", ready_for_graph=True, storyboard_anchor={"status": "approved"})
    _json(fixture.pack_path, fixture.pack)
    with pytest.raises(Refused, match="E_LISTEN_APPROVAL"):
        fixture.video.load_video(fixture.case.ctx, fixture.base, "S02_A", "preview")


def test_video_gui_refuses_foreign_domain_pack(prepared_video):
    fixture = prepared_video
    fixture.pack["domain"] = JJ
    _json(fixture.pack_path, fixture.pack)
    with pytest.raises(Refused, match="ANCHOR_PACK_FOREIGN"):
        fixture.video.load_video(fixture.case.ctx, fixture.base, "S02_A", "preview")


def test_video_gui_refuses_legacy_preparation_without_anchor_pack(prepared_video):
    fixture = prepared_video
    fixture.receipt.pop("anchor_pack")
    with pytest.raises(Refused, match="ANCHOR_PACK_MISSING"):
        fixture.video.load_video(fixture.case.ctx, fixture.base, "S02_A", "preview")


def test_video_gui_refuses_pilot_substitute_anchor(prepared_video):
    fixture = prepared_video
    fixture.receipt["storyboard"]["pilot"] = True
    with pytest.raises(Refused, match="STORYBOARD_PENDING"):
        fixture.video.load_video(fixture.case.ctx, fixture.base, "S02_A", "preview")


def test_video_gui_refuses_unqualified_tier(prepared_video):
    fixture = prepared_video
    with pytest.raises(Refused, match="GUI_TIER_REFUSED"):
        fixture.video.load_video(fixture.case.ctx, fixture.base, "S02_A", "4k")


def test_export_converter_roundtrip_for_interleaved_widgets_and_dynamic_links(case):
    """Widget entries before sockets must never shift serialized link indices.

    This follows the browser's socket-index lookup rather than asserting the
    converter's own intermediate numbering. Autogrow uses IMAGE metadata from
    the server template; no inference from the concrete port name is permitted.
    """
    case.prepared["graph"]["3"]["inputs"]["ref_images.ref_image_0"] = ["1", 0]
    _refresh_graph(case)

    def interleaved_info(name):
        info = object_info(name)
        if name == "TestRender":
            info["input"]["required"] = {
                "prompt": ["STRING", {}], "image": ["IMAGE"],
                "seed": ["INT", {"default": 1, "control_after_generate": True}], "audio": ["AUDIO"],
            }
            info["input"]["optional"] = {"ref_images": ["COMFY_AUTOGROW_V3", {
                "template": {"prefix": "ref_image_", "max": 4, "input": {"required": {"ref_image": ["IMAGE"]}}},
            }]}
        return info

    result = export_gui(case.ctx, case.prepared, kind="video", out=case.out, object_info=interleaved_info, policy=POLICY)
    gui = _gui(result)
    by_id = {str(node["id"]): node for node in gui["nodes"]}
    links = {row[0]: row for row in gui["links"]}
    reconstructed = {}
    for node_id, node in by_id.items():
        reconstructed[node_id] = {}
        for socket_index, socket in enumerate(node["inputs"]):
            link_id = socket.get("link")
            if link_id is None:
                continue
            link = links[link_id]
            assert link[3] == node["id"]
            assert link[4] == socket_index, f"browser would connect {socket['name']} to another socket"
            reconstructed[node_id][socket["name"]] = [str(link[1]), link[2]]
    for node_id, node in case.prepared["graph"].items():
        expected = {key: value for key, value in node["inputs"].items()
                    if isinstance(value, list) and len(value) == 2 and value[0] in case.prepared["graph"]}
        assert reconstructed[node_id] == expected
    assert [socket["name"] for socket in by_id["3"]["inputs"]] == ["image", "audio", "ref_images.ref_image_0"]
    assert by_id["3"]["widgets_values_named"]["prompt"] == "real approved shot prompt"
    assert by_id["3"]["widgets_values_named"]["seed"] == 42


@pytest.mark.parametrize("invalid_id", ["not-numeric", "0", "-4", "1.5", "01"])
def test_export_refuses_invalid_numeric_node_ids_before_writes(case, invalid_id):
    case.prepared["graph"][invalid_id] = case.prepared["graph"].pop("4")
    _refresh_graph(case)
    with pytest.raises(Refused):
        _export(case)
    assert not list((case.comfy / "input").iterdir())
    assert not list(case.workflows.rglob("*.json"))


@pytest.mark.parametrize("class_type", ["LoadVideo", "VHS_LoadVideoPath"])
def test_export_refuses_unexpected_filesystem_loader(case, class_type):
    case.prepared["graph"]["5"] = {"class_type": class_type, "inputs": {"filename": "unapproved-file.mp4"}}
    _refresh_graph(case)

    def unexpected_info(name):
        if name == class_type:
            return {"input": {"required": {"filename": ["STRING", {}]}}, "output": ["IMAGE"], "output_name": ["IMAGE"]}
        return object_info(name)

    with pytest.raises(Refused, match="GUI_MEDIA"):
        export_gui(case.ctx, case.prepared, kind="video", out=case.out, object_info=unexpected_info, policy=POLICY)
    assert not list((case.comfy / "input").iterdir())


@pytest.mark.parametrize("extra_info", [
    {"python_module": "custom_nodes.unapproved_pack.nodes"},
    {"api_node": True},
    {"python_module": "comfy_api_nodes.nodes_partner"},
    {"category": "API node/remote"},
])
def test_export_enforces_custom_pack_and_partner_node_guards(case, extra_info):
    def guarded_info(name):
        info = object_info(name)
        if name == "TestRender":
            info.update(extra_info)
        return info

    with pytest.raises(Refused, match="GUI_NODE"):
        export_gui(case.ctx, case.prepared, kind="video", out=case.out, object_info=guarded_info, policy=POLICY)
    assert not list((case.comfy / "input").iterdir())


def test_export_permits_domain_allowlisted_custom_pack(case):
    case.ctx.domain = {"allowed_custom_nodes": ["qualified_pack"], "forbidden_node_classes": []}

    def allowed_info(name):
        info = object_info(name)
        if name == "TestRender":
            info["python_module"] = "custom_nodes.qualified_pack.nodes"
        return info

    result = export_gui(case.ctx, case.prepared, kind="video", out=case.out, object_info=allowed_info, policy=POLICY)
    assert result["status"] == "EXPORTED"
