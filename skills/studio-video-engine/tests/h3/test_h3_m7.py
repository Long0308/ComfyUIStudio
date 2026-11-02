"""M7: jjv h3 prepare / submit / adopt / accept against a FAKE ComfyUI (no GPU, nothing but 127.0.0.1)."""

from __future__ import annotations

import json
import shutil

import pytest
from fake_comfy import FakeComfy
from h3_fixtures import SHOT, FakeProbe, H3World, fake_with_video, ok_ps, run_h3, sha_bytes, sha_file
from test_h3_inputs_m8b import library_stub  # noqa: F401  (library_stub: fixture)

from engine.comfy.client import ComfyClient
from engine.core.errors import Refused, Uncertain
from engine.h3 import accept, adopt, submit


pytestmark = pytest.mark.usefixtures("library_stub")

@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def go(world: H3World, fake: FakeComfy, **kw):
    return submit.submit(world.ctx(), world.out, None, world.settings(), ComfyClient(fake.url, timeout_seconds=5),
                         probe=FakeProbe(), ps=ok_ps, wait_timeout=5, **kw)


# ---- prepare -----------------------------------------------------------------------------------------
def test_prepare_is_deterministic_and_binds_hashed_media(tmp_path) -> None:
    world = H3World(tmp_path)
    first = world.prepare()
    second = world.prepare(out=tmp_path / "again")
    assert first["shots"][0]["graph_sha256"] == second["shots"][0]["graph_sha256"]
    assert first["shots"][0]["preparation_sha256"] == second["shots"][0]["preparation_sha256"]
    assert world.prepare()["shots"][0]["graph_sha256"] == first["shots"][0]["graph_sha256"]  # idempotent re-run
    graph = json.loads((world.out / SHOT / "graph.api.json").read_text("utf-8"))
    assert graph["30"]["inputs"]["image"] == f"h3-{sha_file(world.anchor)}.png"
    assert graph["7"]["inputs"]["audio"] == f"h3-{sha_file(world.wav)}.wav"
    assert graph["19"]["inputs"]["value"] == "Alice speaks to <Audio 1>"
    assert graph["63"]["inputs"]["filename_prefix"].startswith(f"h3/t-ep/{SHOT}/")
    receipt = json.loads((world.out / SHOT / "preparation.json").read_text("utf-8"))
    assert receipt["status"] == "PREPARED_NOT_SUBMITTED" and receipt["wav"]["sha256"] == sha_file(world.wav)
    assert not any((world.world.comfy_root / "input").iterdir())  # prepare stages nothing


def test_prepare_changes_sha_when_an_input_changes(tmp_path) -> None:
    world = H3World(tmp_path)
    base = world.prepare()["shots"][0]["graph_sha256"]
    world.write_manifest([world.row(mouth={"19.value": "other words", "6.length": 141, "11.noise_seed": 1})])
    assert world.prepare(out=tmp_path / "o2")["shots"][0]["graph_sha256"] != base


@pytest.mark.parametrize("which", ["native_wav", "trimmed_wav"])
def test_wrong_wav_sha_is_refused(tmp_path, which) -> None:
    world = H3World(tmp_path)
    wrong = getattr(world, which)
    row = world.row()
    row["wav"] = {"path": wrong.relative_to(world.root).as_posix(), "sha256": sha_file(wrong),
                  "ports": [["7", "audio"]]}
    world.write_manifest([row])
    with pytest.raises(Refused, match="WAV differs"):
        world.prepare()
    assert not world.out.exists()


def test_unknown_or_unapproved_wav_is_refused(tmp_path) -> None:
    world = H3World(tmp_path)
    stranger = world._file("assets/stranger.wav", b"RIFF-not-in-finalize")
    row = world.row()
    row["wav"] = {"path": "assets/stranger.wav", "sha256": sha_file(stranger), "ports": [["7", "audio"]]}
    world.write_manifest([row])
    with pytest.raises(Refused, match="E_LISTEN_APPROVAL"):
        world.prepare()
    world.write_manifest()
    world.revoke_approval()
    with pytest.raises(Refused, match="E_LISTEN_APPROVAL"):
        world.prepare()


def test_missing_anchor_hash_drift_and_domain_are_refused(tmp_path, monkeypatch) -> None:
    world = H3World(tmp_path)
    row = world.row()
    row["anchor"]["path"] = "assets/missing.png"
    world.write_manifest([row])
    with pytest.raises(Refused, match="anchor is missing"):
        world.prepare()
    row = world.row()
    row["anchor"]["sha256"] = "0" * 64
    world.write_manifest([row])
    with pytest.raises(Refused, match="hash mismatch"):
        world.prepare()
    # newtecons_live_action is qualified now (receipt 30cd429b..., installed 2026-11-01). The refusal check runs against
    # the pre-qualification H3 routes: a temp copy with no qualification_required entry for the live domain.
    from engine.h3 import prepare

    unqualified = tmp_path / "routes-unqualified.json"
    unqualified.write_text(json.dumps({"allowed_domains": ["jenniejoy_cartoon_3d"], "qualification_required": {},
                                       "legacy_voice_episodes": []}), encoding="utf-8")
    monkeypatch.setattr(prepare, "ROUTES", unqualified)
    live = H3World(tmp_path / "live", domain="newtecons_live_action")
    with pytest.raises(Refused, match="not qualified"):
        live.prepare()


def test_wav_must_equal_the_prior_preparation_receipt(tmp_path) -> None:
    world = H3World(tmp_path)
    world.prepare()
    moved = world.root / "assets" / "prior-preparation.json"
    shutil.copy(world.out / SHOT / "preparation.json", moved)
    row = world.row(preparation_receipt={"path": "assets/prior-preparation.json", "sha256": sha_file(moved)})
    world.write_manifest([row])
    assert world.prepare(out=tmp_path / "ok")["shots"]  # same WAV as the receipt: fine
    data = json.loads(moved.read_text("utf-8"))
    data["wav"]["sha256"] = sha_file(world.native_wav)
    moved.write_text(json.dumps(data), encoding="utf-8")
    row = world.row(preparation_receipt={"path": "assets/prior-preparation.json", "sha256": sha_file(moved)})
    world.write_manifest([row])
    with pytest.raises(Refused, match="preparation.json -> wav.sha256"):
        world.prepare(out=tmp_path / "bad")


def test_duplicate_port_and_unsafe_ids_are_refused(tmp_path) -> None:
    world = H3World(tmp_path)
    row = world.row()
    row["faces"][0]["ports"] = [["31", "image"], ["31", "image"]]
    world.write_manifest([row])
    with pytest.raises(Refused, match="duplicate media port"):
        world.prepare()
    world.write_manifest([world.row(shot="../evil")])
    with pytest.raises(Refused, match="unsafe H3 identifier"):
        world.prepare()


def test_legacy_voice_needs_an_explicit_flag_and_a_receipt(tmp_path) -> None:
    world = H3World(tmp_path)
    world.write_manifest(voice_dir=None)
    with pytest.raises(Refused, match="voice_dir"):
        world.prepare()
    world.write_manifest(voice_dir=None, legacy_voice=True)
    with pytest.raises(Refused, match="preparation_receipt"):
        world.prepare()


def _routes(tmp_path, monkeypatch, episodes):
    from engine.h3 import prepare

    path = tmp_path / "routes.json"
    path.write_text(json.dumps({"allowed_domains": ["jenniejoy_cartoon_3d"], "legacy_voice_episodes": episodes}),
                    encoding="utf-8")
    monkeypatch.setattr(prepare, "ROUTES", path)


def _legacy_world(tmp_path, prior_body: dict | None = None, *, receipt_wav=None):
    """legacy_voice manifest whose prior receipt is a copy of a real H3 preparation (or the given body)."""
    world = H3World(tmp_path)
    world.prepare()
    prior = world.root / "assets" / "prior-preparation.json"
    if prior_body is None:
        shutil.copy(world.out / SHOT / "preparation.json", prior)
    else:
        prior.write_text(json.dumps(prior_body), encoding="utf-8")
    row = world.row(preparation_receipt={"path": "assets/prior-preparation.json", "sha256": sha_file(prior)})
    world.write_manifest([row], voice_dir=None, legacy_voice=True)
    return world


def test_legacy_voice_is_refused_for_an_episode_not_listed_in_data(tmp_path, monkeypatch) -> None:
    world = _legacy_world(tmp_path)  # t-ep is not in routes-v001.json -> legacy_voice_episodes
    with pytest.raises(Refused, match="legacy_voice_episodes"):
        world.prepare(out=tmp_path / "legacy")
    assert not (tmp_path / "legacy").exists()
    _routes(tmp_path, monkeypatch, ["04-milk-and-mom"])  # still not t-ep
    with pytest.raises(Refused, match="legacy_voice_episodes"):
        world.prepare(out=tmp_path / "legacy")


def test_legacy_voice_needs_a_real_preparation_receipt(tmp_path, monkeypatch) -> None:
    _routes(tmp_path, monkeypatch, ["t-ep"])
    wav = sha_bytes(b"RIFF-receipt-wav")
    world = _legacy_world(tmp_path, {"wav": {"sha256": wav}})  # any JSON with a matching wav sha
    with pytest.raises(Refused, match="not an H3 preparation receipt"):
        world.prepare(out=tmp_path / "legacy")
    foreign = _legacy_world(tmp_path / "f", {"schema": "jjv/h3-preparation/v1", "episode_id": "other-ep",
                                             "shot": SHOT, "status": "PREPARED_NOT_SUBMITTED",
                                             "graph_sha256": "a" * 64, "wav": {"sha256": wav}})
    with pytest.raises(Refused, match="not an H3 preparation receipt"):
        foreign.prepare(out=tmp_path / "legacy2")


def test_legacy_voice_passes_for_a_listed_episode_with_a_real_receipt(tmp_path, monkeypatch) -> None:
    _routes(tmp_path, monkeypatch, ["t-ep"])
    world = _legacy_world(tmp_path)  # new-schema receipt
    first = world.prepare(out=tmp_path / "a")["shots"][0]
    receipt = json.loads((tmp_path / "a" / SHOT / "preparation.json").read_text("utf-8"))
    assert receipt["voice_approval"]["mode"] == "legacy-preparation-receipt"
    assert receipt["voice_approval"]["receipt_sha256"] == receipt["prior_preparation"]["sha256"]
    old = {"entry_type": "motivated_cut_new_angle", "film_id": "t-ep", "shot_id": SHOT,
           "status": "PREPARED_NOT_SUBMITTED", "api": {"sha256": "b" * 64}, "wav": {"sha256": sha_bytes(b"RIFF-receipt-wav")}}
    shape = _legacy_world(tmp_path / "old", old)  # the pre-engine ep04 receipt shape
    assert shape.prepare(out=tmp_path / "b")["shots"][0]["graph_sha256"] == first["graph_sha256"]


# ---- submit ------------------------------------------------------------------------------------------
def test_submit_without_approve_gpu_posts_nothing_and_exits_nonzero(tmp_path, fake) -> None:
    world = H3World(tmp_path, comfy_url=fake.url)
    world.prepare()
    with pytest.raises(Refused, match="--approve-gpu"):
        go(world, fake, approve_gpu=False)
    code, body = run_h3(["submit", "--episode", str(world.root), "--out", str(world.out),
                         "--machine", str(world.world.machine_path)])
    assert code == 1 and body["ok"] is False and "--approve-gpu" in body["error"]
    assert fake.posts == [] and fake.posts_made() == []
    assert not (world.out / SHOT / "comfy").exists()
    assert not any((world.world.comfy_root / "input").iterdir())


def test_submit_posts_once_and_a_duplicate_does_not_post_again(tmp_path, fake) -> None:
    world = H3World(tmp_path, comfy_url=fake.url)
    fake_with_video(world, fake)
    world.prepare()
    first = go(world, fake, approve_gpu=True)
    assert len(fake.posts) == 1 and first["submitted"][0]["status"] == "COMPLETED"
    graph = json.loads((world.out / SHOT / "graph.api.json").read_text("utf-8"))
    assert fake.posts[0]["prompt"] == graph
    staged = sorted(p.name for p in (world.world.comfy_root / "input").iterdir())
    assert f"h3-{sha_file(world.anchor)}.png" in staged and f"h3-{sha_file(world.wav)}.wav" in staged
    again = go(world, fake, approve_gpu=True)
    assert len(fake.posts) == 1  # POSTed once
    assert again["submitted"] == [] and again["already_submitted"][0]["status"] == "ALREADY_SUBMITTED"
    intent = json.loads((world.out / SHOT / "comfy" / "dispatch-intent.json").read_text("utf-8"))
    assert intent["container_instance"]["started_at_text"] == "2026-10-28T00:00:00Z"


def test_submit_refuses_busy_queue_unready_container_and_changed_input(tmp_path, fake) -> None:
    world = H3World(tmp_path, comfy_url=fake.url)
    world.prepare()
    fake.queue["queue_pending"] = [[1, "x", {}, {"client_id": "c"}, []]]
    with pytest.raises(Refused, match="not ready"):
        go(world, fake, approve_gpu=True)
    fake.queue["queue_pending"] = []
    with pytest.raises(Refused, match="not ready"):
        submit.submit(world.ctx(), world.out, None, world.settings(), ComfyClient(fake.url, timeout_seconds=5),
                      approve_gpu=True, probe=FakeProbe(), ps=lambda n: f"{n}|exited|Exited (1)\n")
    world.anchor.write_bytes(b"tampered")
    with pytest.raises(Refused, match="hash mismatch"):
        go(world, fake, approve_gpu=True)
    assert fake.posts == []


def test_unknown_outcome_without_receipt_is_uncertain_and_never_resubmitted(tmp_path, fake) -> None:
    world = H3World(tmp_path, comfy_url=fake.url)
    world.prepare()
    fake.post_mode = "drop"
    with pytest.raises(Uncertain):
        go(world, fake, approve_gpu=True)
    fake.post_mode = "normal"
    posts = len(fake.posts)
    with pytest.raises(Uncertain, match="reconcile"):
        go(world, fake, approve_gpu=True)
    assert len(fake.posts) == posts


# ---- adopt + accept ----------------------------------------------------------------------------------
def adopted(tmp_path, fake):
    world = H3World(tmp_path, comfy_url=fake.url)
    fake_with_video(world, fake)
    world.prepare()
    go(world, fake, approve_gpu=True)
    result = adopt.adopt(world.ctx(), world.out, None, world.settings(), ComfyClient(fake.url, timeout_seconds=5))
    return world, result


def test_adopt_writes_receipts_and_a_gui_workflow_with_the_result_pinned(tmp_path, fake) -> None:
    world, result = adopted(tmp_path, fake)
    row = result["adopted"][0]
    folder = world.out / SHOT
    body = json.loads((folder / "adopt.json").read_text("utf-8"))
    roles = {o["role"]: o for o in body["outputs"]}
    assert set(roles) == {"editorial", "native"} and body["review_status"] == "pending"
    for item in body["outputs"]:
        assert sha_file(item["path"]) == item["sha256"] and "results" in item["path"]
    review = json.loads((folder / "graph.review.gui.json").read_text("utf-8"))
    pin = next(n for n in review["nodes"] if n["type"] == "LoadVideo")
    assert pin["widgets_values"][0] == body["pinned_input"]
    staged = world.world.comfy_root / "input" / body["pinned_input"]
    assert staged.is_file() and sha_file(staged) == roles["editorial"]["sha256"]
    manifest_path = world.root / "workflows" / "WORKFLOW-MANIFEST.json"
    entry = json.loads(manifest_path.read_text("utf-8"))["entries"][0]
    assert entry["result_sha256"] == roles["editorial"]["sha256"]
    assert entry["result_pins"][0]["node_type"] == "LoadVideo"
    assert (world.root / entry["path"]).is_file() and row["workflow"].endswith(".workflow.json")
    assert (folder / "graph.gui.json").is_file() or body["editable_gui_error"]  # editable GUI: best effort, recorded
    again = adopt.adopt(world.ctx(), world.out, None, world.settings(), ComfyClient(fake.url, timeout_seconds=5))
    assert again["adopted"][0]["reused"] is True
    assert len(json.loads(manifest_path.read_text("utf-8"))["entries"]) == 1


def test_adopt_refuses_an_unsubmitted_shot_and_a_foreign_graph(tmp_path, fake) -> None:
    world = H3World(tmp_path, comfy_url=fake.url)
    world.prepare()
    with pytest.raises(Refused, match="submit"):
        adopt.adopt(world.ctx(), world.out, None, world.settings(), None)
    job = world.out / SHOT / "comfy"
    job.mkdir()
    (job / "job.json").write_text(json.dumps({"status": "COMPLETED", "graph_sha256": "f" * 64, "prompt_id": "p",
                                              "client_id": "c", "outputs": []}), encoding="utf-8")
    with pytest.raises(Refused, match="not adoptable"):
        adopt.adopt(world.ctx(), world.out, None, world.settings(), None)


def test_acceptance_gate_rejected_takes_never_reach_the_edit(tmp_path, fake) -> None:
    world, _ = adopted(tmp_path, fake)
    out, ctx = world.out, world.ctx()
    assert accept.status(out, ctx=ctx)[0]["review"] == "pending" and accept.accepted_takes(out, ctx=ctx) == []
    sha = accept.status(out, ctx=ctx)[0]["sha256"]
    with pytest.raises(Refused, match="not the adopted"):
        accept.decide(out, SHOT, "pick", by="Kim", reason="ok", sha256="a" * 64, ctx=ctx)
    with pytest.raises(Refused, match="E_APPROVAL_BY"):
        accept.decide(out, SHOT, "pick", by="claude", reason="looks fine", ctx=ctx)
    with pytest.raises(Refused, match="reason"):
        accept.decide(out, SHOT, "pick", by="Kim", reason=" ", ctx=ctx)
    with pytest.raises(Refused, match="never reach the edit"):
        accept.require_accepted(out, SHOT, sha, ctx=ctx)
    accept.decide(out, SHOT, "reject", by="Kim", reason="lips drift at 3s", ctx=ctx)
    assert accept.status(out, ctx=ctx)[0]["review"] == "rejected" and accept.accepted_takes(out, ctx=ctx) == []
    with pytest.raises(Refused, match="rejected"):
        accept.decide(out, SHOT, "pick", by="Kim", reason="changed my mind", ctx=ctx)
    with pytest.raises(Refused, match="never reach the edit"):
        accept.require_accepted(out, SHOT, sha, ctx=ctx)
    assert len(list((out / SHOT / "acceptance").glob("*.json"))) == 1  # the refused pick wrote nothing


def test_acceptance_pick_is_listed_and_cli_round_trip(tmp_path, fake) -> None:
    world, _ = adopted(tmp_path, fake)
    ctx = world.ctx()
    base = ["--episode", str(world.root), "--out", str(world.out), "--machine", str(world.world.machine_path)]
    code, body = run_h3(["accept", *base, "--shot", SHOT, "--pick", "--by", "Kim", "--reason", "lips and identity ok"])
    assert code == 0 and body["decision"] == "pick"
    code, body = run_h3(["accept", *base, "--list"])
    assert code == 0 and body["shots"][0]["review"] == "picked" and body["accepted"][0]["shot"] == SHOT
    accept.require_accepted(world.out, SHOT, body["accepted"][0]["sha256"], ctx=ctx)
    code, body = run_h3(["accept", *base, "--shot", SHOT, "--pick"])
    assert code == 1  # missing --by/--reason
    for path in (world.out / SHOT / "results").rglob("*.mp4"):
        path.write_bytes(b"changed after the pick")
    assert accept.accepted_takes(world.out, ctx=ctx) == []  # a take that no longer matches its receipt is not accepted


def _second_folder(world, name: str):
    """A new --out folder that holds the SAME adopted take but no acceptance history (re-prepare / copy)."""
    other = world.tmp / name
    shutil.copytree(world.out / SHOT, other / SHOT, ignore=shutil.ignore_patterns("acceptance"))
    return other


def test_rejection_is_episode_wide_not_scoped_to_the_out_folder(tmp_path, fake) -> None:
    world, _ = adopted(tmp_path, fake)
    ctx = world.ctx()
    sha = accept.status(world.out, ctx=ctx)[0]["sha256"]
    accept.decide(world.out, SHOT, "reject", by="Kim", reason="lips drift at 3s", ctx=ctx)
    other = _second_folder(world, "h3out2")
    assert accept.status(other, ctx=ctx)[0]["review"] == "rejected"
    with pytest.raises(Refused, match="rejected"):
        accept.decide(other, SHOT, "pick", by="Kim", reason="fresh folder", ctx=ctx)
    assert not (other / SHOT / "acceptance").exists()  # the refused pick wrote nothing
    folder_reject = next((world.out / SHOT / "acceptance").glob("*-reject.json"))  # a forged pick in the folder
    forged = json.loads(folder_reject.read_text("utf-8"))
    forged["decision"] = "pick"
    (other / SHOT / "acceptance").mkdir()
    (other / SHOT / "acceptance" / "001-pick.json").write_text(json.dumps(forged), encoding="utf-8")
    assert accept.accepted_takes(other, ctx=ctx) == []
    with pytest.raises(Refused, match="never reach the edit"):
        accept.require_accepted(other, SHOT, sha, ctx=ctx)


def test_episode_ledger_is_tamper_evident_and_lives_outside_out(tmp_path, fake) -> None:
    world, _ = adopted(tmp_path, fake)
    ctx = world.ctx()
    accept.decide(world.out, SHOT, "reject", by="Kim", reason="lips drift at 3s", ctx=ctx)
    ledger = accept.ledger_path(ctx)
    assert ledger.is_file() and world.out not in ledger.parents and ctx.root in ledger.parents
    lines = ledger.read_text("utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["decision"] == "reject"
    ledger.write_text(lines[0].replace("reject", "pick") + "\n", encoding="utf-8")  # rewrite history
    with pytest.raises(Refused, match="ledger"):
        accept.status(world.out, ctx=ctx)


def test_prepare_refuses_a_missing_anchor_pack_when_no_legacy_approval_is_recorded(tmp_path) -> None:
    world = H3World(tmp_path, legacy_cast=False)  # neither an anchor pack nor a legacy_cast_faces approval record
    with pytest.raises(Refused, match="ANCHOR_PACK_MISSING: S02_A: no anchor pack and no explicit legacy_cast_faces approval"):
        world.prepare()
