"""H3 live-action qualification and output routing; all evidence here is synthetic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_comfy import FakeComfy
from h3_fixtures import EP, SHOT, FakeProbe, H3World, ok_ps, sha_file
from test_h3_inputs_m8b import library_stub  # noqa: F401  (library_stub: fixture)

from engine.comfy.client import ComfyClient
from engine.core.errors import Refused
from engine.h3 import prepare, qualification, submit


LIVE = "newtecons_live_action"
RECEIPT = "evidence/h3-live-action-pilot.json"


pytestmark = pytest.mark.usefixtures("library_stub")


@pytest.fixture(autouse=True)
def _synthetic_faces_are_not_identity_evidence(monkeypatch):
    """These tests cover qualification/output routing with synthetic face.png files; the identity allow-list
    (engine.policy.identity_guard, covered in tests/policy) is switched off here, not weakened globally."""
    from engine.policy import identity_guard
    monkeypatch.setattr(identity_guard, "block", lambda domain: None)

@pytest.fixture
def live_route(tmp_path, monkeypatch):
    world = H3World(tmp_path / "world", domain=LIVE)
    graph = json.loads(world.template.read_text(encoding="utf-8"))
    for node in ("18", "63"):
        graph[node]["inputs"]["filename_prefix"] = "NEWTECONS/H3/Shot"
    world.template.write_text(json.dumps(graph), encoding="utf-8")
    world.write_manifest()

    repo = tmp_path / "repo"
    receipt = repo / RECEIPT
    receipt.parent.mkdir(parents=True)
    routes_file = tmp_path / "routes.json"
    routes = {
        "allowed_domains": ["jenniejoy_cartoon_3d"],
        "legacy_voice_episodes": [],
        "qualification_required": {
            LIVE: {"receipt": {"path": RECEIPT, "sha256": None}, "output_prefix_root": "NEWTECONS"}
        },
    }

    def write_routes():
        routes_file.write_text(json.dumps(routes), encoding="utf-8")

    def write_receipt(body):
        receipt.write_text(json.dumps(body), encoding="utf-8")
        routes["qualification_required"][LIVE]["receipt"]["sha256"] = sha_file(receipt)
        write_routes()

    body = {
        "schema": "jjv/h3-qualification/v1",
        "stage": "h3",
        "domain": LIVE,
        "status": "PASS",
        "pilot": {
            "executor": "comfyui-local",
            "user_authorized": True,
            "prompt_id": "synthetic-prompt",
            "graph_sha256": "a" * 64,
            "template_sha256": sha_file(world.template),
            "allowed_override_ports": ["19.value", "6.length", "11.noise_seed"],
        },
    }
    write_routes()
    monkeypatch.setattr(prepare, "ROUTES", routes_file)
    monkeypatch.setattr(prepare, "REPO_ROOT", repo, raising=False)
    return world, receipt, routes, body, write_routes, write_receipt


def test_live_default_route_names_missing_qualification_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, "REPO_ROOT", tmp_path / "empty-repo")
    world = H3World(tmp_path, domain=LIVE)
    with pytest.raises(Refused, match=r"not qualified.*qualification.*h3.*\.json"):
        world.prepare()
    assert not world.out.exists()


def test_live_missing_receipt_names_the_configured_path(live_route):
    world, receipt, _, _, _, _ = live_route
    with pytest.raises(Refused, match="h3-live-action-pilot.json"):
        world.prepare()
    assert not world.out.exists()


def test_legacy_allow_list_cannot_bypass_a_required_receipt(live_route):
    world, _, routes, _, write_routes, _ = live_route
    routes["allowed_domains"].append(LIVE)
    write_routes()
    with pytest.raises(Refused, match="h3-live-action-pilot.json"):
        world.prepare()


def test_live_missing_pin_and_hash_drift_are_refused(live_route):
    world, receipt, routes, body, write_routes, write_receipt = live_route
    write_receipt(body)
    routes["qualification_required"][LIVE]["receipt"]["sha256"] = None
    write_routes()
    with pytest.raises(Refused, match=r"qualification.*sha256"):
        world.prepare()
    routes["qualification_required"][LIVE]["receipt"]["sha256"] = "0" * 64
    write_routes()
    with pytest.raises(Refused, match=r"qualification.*hash mismatch"):
        world.prepare()
    assert not world.out.exists()


@pytest.mark.parametrize("change", [
    {"schema": "jjv/h3-preparation/v1"},
    {"stage": "seedvr2"},
    {"domain": "jenniejoy_cartoon_3d"},
    {"status": "FAIL"},
    {"pilot": {"executor": "comfyui-local", "user_authorized": False, "prompt_id": "synthetic-prompt",
               "graph_sha256": "a" * 64, "template_sha256": "b" * 64}},
    {"pilot": {"executor": "partner-cloud", "user_authorized": True, "prompt_id": "synthetic-prompt",
               "graph_sha256": "a" * 64, "template_sha256": "b" * 64}},
    {"pilot": {"executor": "comfyui-local", "user_authorized": True, "prompt_id": "",
               "graph_sha256": "a" * 64, "template_sha256": "b" * 64}},
    {"pilot": {"executor": "comfyui-local", "user_authorized": True, "prompt_id": "synthetic-prompt",
               "graph_sha256": "bad", "template_sha256": "b" * 64}},
])
def test_live_invalid_receipt_is_refused(live_route, change):
    world, _, _, body, _, write_receipt = live_route
    write_receipt({**body, **change})
    with pytest.raises(Refused, match="qualification"):
        world.prepare()
    assert not world.out.exists()


def test_live_template_must_match_the_pilot(live_route):
    world, _, _, body, _, write_receipt = live_route
    body["pilot"]["template_sha256"] = "b" * 64
    write_receipt(body)
    with pytest.raises(Refused, match=r"qualification.*template"):
        world.prepare()


def test_live_only_changes_ports_qualified_by_the_pilot(live_route):
    world, _, _, body, _, write_receipt = live_route
    write_receipt(body)
    row = world.row()
    row["mouth"]["17.fps"] = 120
    world.write_manifest([row])
    with pytest.raises(Refused, match=r"qualification.*17\.fps"):
        world.prepare()
    assert not world.out.exists()


@pytest.mark.parametrize("asset", ["anchor", "wav", "face"])
def test_live_media_ports_cannot_modify_other_graph_inputs(live_route, asset):
    world, _, _, body, _, write_receipt = live_route
    write_receipt(body)
    row = world.row()
    item = row["faces"][0] if asset == "face" else row[asset]
    item["ports"].append(["17", "fps"])
    world.write_manifest([row])
    with pytest.raises(Refused, match=r"qualification.*media port"):
        world.prepare()
    assert not world.out.exists()


def test_live_output_port_cannot_modify_a_prompt(live_route):
    world, _, _, body, _, write_receipt = live_route
    write_receipt(body)
    row = world.row()
    row["mouth"]["19.value"] = "NEWTECONS/H3/prompt"
    row["output_ports"].append(["19", "value"])
    world.write_manifest([row])
    with pytest.raises(Refused, match=r"qualification.*output port"):
        world.prepare()
    assert not world.out.exists()


def test_live_mouth_cannot_replace_a_template_output_prefix(live_route):
    world, _, _, body, _, write_receipt = live_route
    body["pilot"]["allowed_override_ports"].append("18.filename_prefix")
    write_receipt(body)
    row = world.row()
    row["mouth"]["18.filename_prefix"] = "NEWTECONS/H3/Redirected"
    world.write_manifest([row])
    with pytest.raises(Refused, match=r"qualification.*output port"):
        world.prepare()
    assert not world.out.exists()


def test_live_qualified_prepare_preserves_each_template_prefix(live_route):
    world, receipt, _, body, _, write_receipt = live_route
    write_receipt(body)
    world.prepare()
    graph = json.loads((world.out / SHOT / "graph.api.json").read_text(encoding="utf-8"))
    prepared = json.loads((world.out / SHOT / "preparation.json").read_text(encoding="utf-8"))
    for index, node in enumerate(("18", "63")):
        prefix = graph[node]["inputs"]["filename_prefix"]
        assert prefix.startswith(f"NEWTECONS/H3/Shot/{EP}/{SHOT}/")
        assert prefix.endswith(f"/{index}")
    assert prepared["qualification"]["sha256"] == sha_file(receipt)
    assert Path(prepared["qualification"]["path"]) == receipt
    assert prepare.load_prepared(world.ctx(), world.out)


def test_live_preserves_distinct_prefixes_per_output(live_route):
    world, _, _, body, _, write_receipt = live_route
    graph = json.loads(world.template.read_text(encoding="utf-8"))
    graph["63"]["inputs"]["filename_prefix"] = "NEWTECONS/H3/Review"
    world.template.write_text(json.dumps(graph), encoding="utf-8")
    world.write_manifest()
    body["pilot"]["template_sha256"] = sha_file(world.template)
    write_receipt(body)
    world.prepare()
    graph = json.loads((world.out / SHOT / "graph.api.json").read_text(encoding="utf-8"))
    assert graph["18"]["inputs"]["filename_prefix"].startswith("NEWTECONS/H3/Shot/")
    assert graph["63"]["inputs"]["filename_prefix"].startswith("NEWTECONS/H3/Review/")


@pytest.mark.parametrize("prefix", ["h3/foreign", "NEWTECONS/../foreign", "/NEWTECONS/H3", "NEWTECONS\\H3"])
def test_live_refuses_unsafe_or_foreign_output_prefix(live_route, prefix):
    world, _, _, body, _, write_receipt = live_route
    graph = json.loads(world.template.read_text(encoding="utf-8"))
    graph["18"]["inputs"]["filename_prefix"] = prefix
    world.template.write_text(json.dumps(graph), encoding="utf-8")
    world.write_manifest()
    body["pilot"]["template_sha256"] = sha_file(world.template)
    write_receipt(body)
    with pytest.raises(Refused, match=r"output prefix"):
        world.prepare()
    assert not world.out.exists()


def test_live_rechecks_qualification_before_submit(live_route):
    world, _, _, body, _, write_receipt = live_route
    write_receipt(body)
    world.prepare()
    body["pilot"]["prompt_id"] = "other-pilot"
    write_receipt(body)  # A valid but different qualification cannot authorize an old preparation.
    with FakeComfy() as fake:
        client = ComfyClient(fake.url, timeout_seconds=5)
        with pytest.raises(Refused, match=r"qualification.*changed"):
            submit.submit(world.ctx(), world.out, None, world.settings(), client,
                          approve_gpu=True, probe=FakeProbe(), ps=ok_ps, wait_timeout=5)
        assert fake.posts == []


def test_live_cannot_drop_qualification_from_an_existing_preparation(live_route):
    world, _, routes, body, write_routes, write_receipt = live_route
    write_receipt(body)
    world.prepare()
    routes["qualification_required"].pop(LIVE)
    routes["allowed_domains"].append(LIVE)
    write_routes()
    with pytest.raises(Refused, match=r"qualification.*changed"):
        prepare.load_prepared(world.ctx(), world.out)


def test_live_malformed_receipt_is_refused(live_route):
    world, receipt, routes, _, write_routes, _ = live_route
    receipt.write_text("{bad json", encoding="utf-8")
    routes["qualification_required"][LIVE]["receipt"]["sha256"] = sha_file(receipt)
    write_routes()
    with pytest.raises(Refused, match=r"qualification.*invalid"):
        world.prepare()


def test_live_receipt_must_be_parsed_from_the_bytes_that_were_hashed(live_route, monkeypatch):
    world, receipt, _, body, _, write_receipt = live_route
    write_receipt({**body, "status": "FAIL"})
    original = qualification.read_json

    def racy_read(path):
        if Path(path) != receipt:
            return original(path)
        pinned_bytes = receipt.read_bytes()
        receipt.write_text(json.dumps(body), encoding="utf-8")
        try:
            return original(path)
        finally:
            receipt.write_bytes(pinned_bytes)

    monkeypatch.setattr(qualification, "read_json", racy_read)
    with pytest.raises(Refused, match=r"qualification.*invalid"):
        world.prepare()


def test_live_rechecks_the_qualified_template(live_route):
    world, _, _, body, _, write_receipt = live_route
    write_receipt(body)
    world.prepare()
    world.template.write_text("{}", encoding="utf-8")
    with pytest.raises(Refused, match=r"qualified H3 template.*hash mismatch"):
        prepare.load_prepared(world.ctx(), world.out)
