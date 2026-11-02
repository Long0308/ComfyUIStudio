"""SPEC-DAG-FIX (live DAG): layout/still stages, full library coverage, signed human proof, scoped GPU proof.

Four RED tests drafted by Terra (dag-live-red-tests-v001.md) adapted to this suite's fixtures, plus positive controls
and the refusals of the new validators.  Every verb goes through the recording FakeRunner: no GPU, no network.
The proofs are the engine's FILE-TOKEN speed bump (engine/run/proof.py), not an unforgeable signature.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from pathlib import Path

import pytest
from run_fixtures import LIVE, FakeRunner, jjv_module, make_run_world, run_cli, write

from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.images import library as images_library
from engine.run import dag as dag_mod
from engine.run import gates, library_gate, proof
from engine.run import orchestrator
from engine.run.context import load_run_context

KEY = "ab" * 32
ISSUER = "user-1"
PRINCIPAL = "Nguyen Van A"
REQUIRED_STAGES = ("layout-plan", "layout-author", "layout-check", "layout-render", "still-route-check", "still-assets",
                   "still-set-control", "still-lock", "still-nine", "still-fix", "still-review", "images-native")


@pytest.fixture(autouse=True)
def trust(tmp_path, monkeypatch):
    folder = tmp_path / "trust"
    write(folder / "issuers.json", {"issuers": {ISSUER: {"principal": PRINCIPAL, "key_hex": KEY}}, "revoked": []})
    monkeypatch.setenv(proof.TRUST_ENV, str(folder))
    return folder


def live_dag() -> dag_mod.Dag:
    return dag_mod.load_dag(domain_id=LIVE)


def make_ctx(world, **kw):
    ctx = load_run_context(str(world.episode_file), runs_root=world.runs_root, stages_root=world.stages_root)
    return dataclasses.replace(ctx, **kw)


def signed(ctx, gate, verdict="accept", subjects=(), scope=None, expires=3600, issuer=ISSUER, key=KEY, **over):
    body = {"proof_id": f"p-{gate}-{len(subjects)}-{verdict}", "issuer": issuer, "gate": gate, "verdict": verdict,
            "episode_id": ctx.episode_id, "domain": ctx.domain_id, "subjects": list(subjects), "scope": scope or {},
            "nonce": "n1", "issued_at": time.time(), "expires_at": time.time() + expires, **over}
    return proof.sign(body, key)


# ---- D01: layout + still stages are in the live DAG, in order ------------------------------------------------------
def test_live_requires_layout_before_stills() -> None:
    dag = live_dag()
    missing = set(REQUIRED_STAGES) - set(dag.ids)
    assert not missing, f"D01: live DAG is missing required layout/still stages: {sorted(missing)}"
    ids = list(dag.ids)
    assert [ids.index(s) for s in REQUIRED_STAGES] == sorted(ids.index(s) for s in REQUIRED_STAGES)
    assert ids.index("library") < ids.index("layout-plan") < ids.index("still-nine") < ids.index("images-native") \
        < ids.index("video-plan")
    plan = next(s for s in dag.stage("still-nine").steps if s.id == "plan")
    assert "--layout" in plan.argv and "{stage:layout-plan}" in plan.argv, "D01: images plan lacks --layout"
    assert "--allow-draft" not in {a for s in dag.stages for st in s.steps for a in st.argv}
    for first, then in (("library", "layout-plan"), ("layout-plan", "layout-author"), ("layout-author", "layout-check"),
                        ("layout-check", "layout-render"), ("layout-render", "still-route-check"),
                        ("still-lock", "still-nine"), ("still-nine", "still-fix"), ("still-fix", "still-review"),
                        ("still-review", "images-native")):
        assert first in dag.stage(then).needs, f"D01: {then} does not need {first}"
    assert "video-plan" in {s.id for s in dag.stages} and "images-native" in dag.stage("video-plan").needs
    assert "images" not in dag.ids   # one parent stage can no longer hide eight checkpoints


def test_disabled_checkpoints_are_visible_blockers(tmp_path, capsys, monkeypatch) -> None:
    label = live_dag().stage("still-set-control").human_gates["receipt-gate"]["label"]
    assert "03" in label and "05" in label and "04" in label and "weights" in label
    assert live_dag().stage("still-set-control").human == "receipt-gate"      # never completes without a receipt


def test_live_recipe_requires_proofs() -> None:
    dag = live_dag()
    assert dag.human_proof == "required" and dag.gpu_authorization == "proof"
    assert dag.stage("library").human == "library-coverage"


# ---- library fixture: real library approvals the gate re-verifies --------------------------------------------------
def build_library(world, ctx, chars=("CHAR_01", "CHAR_02"), kinds=(("FACE", 2), ("ACTION", 2)), sidecar=False):
    lib = world.root / "library"
    slots, shas = [], {}
    items = images_library.checklist_items()
    for ch in chars:
        for kind, count in kinds:
            for n in range(1, count + 1):
                pid = f"{ch}_{kind}_{n}_r001"
                png = lib / ch / pid / f"{pid}.png"
                png.parent.mkdir(parents=True, exist_ok=True)
                png.write_bytes(f"png-{pid}".encode())
                sha = sha256_file(png)
                receipt = write(lib / ch / pid / f"{pid}.receipt.json",
                                {"prompt_id": pid, "output": {"path": png.as_posix(), "sha256": sha}, "ref_hashes": []})
                sheet = write(lib / "_review" / pid / "checklist.json",
                              {"items": [], "candidates": {sha: {i: {"status": "pass"} for i in items}}})
                appr = write(lib / "_review" / pid / "approvals" / "approval-v001.json", {
                    "schema": images_library.APPROVAL_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
                    "prompt_id": pid, "character": ch, "candidate_sha256": sha, "status": "accepted_library_image",
                    "scope": "character-library", "receipt": {"path": receipt.as_posix(), "sha256": sha256_file(receipt)},
                    "checklist_path": sheet.as_posix(), "checklist_sha256": sha256_file(sheet)})
                if sidecar:
                    write(appr.with_name("approval-v001.proof.json"),
                          signed(ctx, "library-approval", subjects=[sha], proof_id=f"lib-{pid}"))
                slots.append({"character": ch, "kind": kind, "slot": str(n), "prompt_id": pid})
                shas.setdefault(ch, []).append(sha)
                if n == 1 and kind == "FACE":
                    canonical = png
    cast = [{"character_id": ch, "canonical_png": (lib / ch / f"{ch}_FACE_1_r001" / f"{ch}_FACE_1_r001.png").as_posix(),
             "canonical_sha256": shas[ch][0]} for ch in chars]
    write(world.root / "characters" / "cast.json", {"schema": "jjv/cast/v1", "characters": cast})
    write(lib / "requirements.json", {"schema": library_gate.REQ_SCHEMA, "characters": list(chars),
                                      "kinds": dict(kinds), "slots": slots})
    doc = json.loads(world.episode_file.read_text("utf-8"))
    doc["files"].update(library_dir="../library", library_requirements="../library/requirements.json")
    write(world.episode_file, doc)
    return lib, slots


def library_state(world, **ctx_kw):
    ctx = make_ctx(world, **ctx_kw)
    return gates.check(ctx, "library", live_dag().stage("library").human_gates, "library-coverage")


def test_one_approval_cannot_unlock_library(tmp_path) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    doc = json.loads(world.episode_file.read_text("utf-8"))
    doc["files"].update(library_dir="../library", library_requirements="../library/requirements.json")
    write(world.episode_file, doc)
    write(world.root / "library" / "_review" / "p1" / "approvals" / "approval-v001.json", {"ok": True})
    state = library_state(world)
    assert not state.ok, "L01: one arbitrary approval unlocked library"
    assert "requirement manifest" in state.detail


def test_full_coverage_cast_bound_positive_control(tmp_path) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    build_library(world, make_ctx(world))
    state = library_state(world)
    assert state.ok, state.detail
    assert "8/8" in state.detail


def test_missing_slot_and_policy_shortfall_stop_naming_the_slot(tmp_path) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    lib, slots = build_library(world, make_ctx(world))
    (lib / "_review" / "CHAR_02_ACTION_2_r001" / "approvals" / "approval-v001.json").unlink()
    state = library_state(world)
    assert not state.ok and "CHAR_02/ACTION/2" in state.detail and "7/8" in state.detail
    req = json.loads((lib / "requirements.json").read_text("utf-8"))      # manifest shrunk below policy: refused
    req["slots"] = [s for s in req["slots"] if s["character"] != "CHAR_02" or s["kind"] != "ACTION"]
    write(lib / "requirements.json", req)
    shrunk = library_state(world)
    assert not shrunk.ok and "CHAR_02/ACTION: manifest lists 0 slots, policy needs 2" in shrunk.detail


def test_duplicates_do_not_inflate_coverage(tmp_path) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    lib, slots = build_library(world, make_ctx(world))
    req = json.loads((lib / "requirements.json").read_text("utf-8"))
    req["slots"][1] = {**req["slots"][0], "slot": "9"}                      # same prompt_id listed twice
    write(lib / "requirements.json", req)
    assert "duplicate slot" in library_state(world).detail


def test_library_provenance_is_revalidated(tmp_path) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    lib, _ = build_library(world, make_ctx(world))
    (lib / "CHAR_01" / "CHAR_01_FACE_1_r001" / "CHAR_01_FACE_1_r001.png").write_bytes(b"tampered")
    state = library_state(world)
    assert not state.ok and "CHAR_01/FACE/1" in state.detail
    other = make_run_world(tmp_path / "x", domain=LIVE, episode_id="live-fixture")
    build_library(other, make_ctx(other))
    path = other.root / "library" / "_review" / "CHAR_01_FACE_2_r001" / "approvals" / "approval-v001.json"
    row = json.loads(path.read_text("utf-8"))
    write(path, {**row, "scope": "shot"})                                    # wrong scope
    assert "wrong scope" in library_state(other).detail


def test_cast_must_bind_an_approved_pick(tmp_path) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    build_library(world, make_ctx(world))
    stranger = write(world.root / "characters" / "other.png", "not a library pick")
    cast = json.loads((world.root / "characters" / "cast.json").read_text("utf-8"))
    cast["characters"][0].update(canonical_png=stranger.as_posix(), canonical_sha256=sha256_file(stranger))
    write(world.root / "characters" / "cast.json", cast)
    state = library_state(world)
    assert not state.ok and "canonical image of CHAR_01 is not one of its approved library picks" in state.detail
    cast["characters"].pop(0)                                                # unbound role: character missing from cast
    write(world.root / "characters" / "cast.json", cast)
    assert "CHAR_01 is not bound" in library_state(world).detail


def test_library_needs_signed_sidecar_when_proof_required(tmp_path) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    build_library(world, make_ctx(world))
    state = library_state(world, proof_required=True)
    assert not state.ok and "needs human proof" in state.detail
    proved = make_run_world(tmp_path / "y", domain=LIVE, episode_id="live-fixture")
    build_library(proved, make_ctx(proved), sidecar=True)
    assert library_state(proved, proof_required=True).ok


# ---- A01: a typed name is not authentication ----------------------------------------------------------------------
def test_named_human_is_not_authentication(tmp_path) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    ctx = make_ctx(world, proof_required=True)
    subject = write(tmp_path / "review.bin", "review bytes")
    sha = sha256_file(subject)
    with pytest.raises(Refused, match="signed human proof"):
        gates.record_approval(ctx, "music-approval", by=PRINCIPAL, note="reviewed", verdict="accept", sha256=sha)
    spec = {"music-approval": {"subject": str(subject)}}
    assert not gates.check(ctx, "music", spec, "music-approval").ok, "A01: unsigned human name opened approval gate"
    # a LEGACY record already on disk (no proof) is kept but does not open the gate (needs-human-proof)
    legacy = make_ctx(world)
    gates.record_approval(legacy, "music-approval", by=PRINCIPAL, note="old", verdict="accept", sha256=sha)
    assert not gates.check(ctx, "music", spec, "music-approval").ok
    assert gates.check(legacy, "music", spec, "music-approval").ok     # the non-proof (cartoon) mode is unchanged


def test_signed_proof_opens_the_gate_and_is_bound(tmp_path) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    ctx = make_ctx(world, proof_required=True)
    subject = write(tmp_path / "review.bin", "review bytes")
    sha = sha256_file(subject)
    spec = {"music-approval": {"subject": str(subject)}}
    good = signed(ctx, "music-approval", subjects=[sha])
    gates.record_approval(ctx, "music-approval", by=None, note="bed ok", verdict="accept", sha256=sha, proof=good)
    state = gates.check(ctx, "music", spec, "music-approval")
    assert state.ok and PRINCIPAL in state.detail
    with pytest.raises(Refused, match="not the principal"):
        gates.record_approval(ctx, "music-approval", by="Someone Else", note="x", verdict="accept", sha256=sha, proof=good)
    subject.write_text("changed bytes", encoding="utf-8")                  # the subject moved: the old proof no longer counts
    assert not gates.check(ctx, "music", spec, "music-approval").ok


@pytest.mark.parametrize("mutate,message", [
    (lambda p: {**p, "subjects": ["0" * 64]}, "does not cover subject|signature"),
    (lambda p: {**p, "episode_id": "other-episode"}, "signature"),
    (lambda p: {**p, "issuer": "agent-made"}, "not in the trust root"),
    (lambda p: proof.sign({k: v for k, v in p.items() if k != "mac"}, "cd" * 32), "signature"),     # key the agent made up
    (lambda p: {**p, "expires_at": 1.0}, "signature"),
])
def test_forged_or_altered_proof_is_refused(tmp_path, mutate, message) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    ctx = make_ctx(world, proof_required=True)
    sha = "1" * 64
    forged = mutate(signed(ctx, "music-approval", subjects=[sha]))
    with pytest.raises(Refused, match=message):
        gates.record_approval(ctx, "music-approval", by=None, note="x", verdict="accept", sha256=sha, proof=forged)


def test_expired_wrong_gate_wrong_verdict_and_revoked_proofs_are_refused(tmp_path, trust) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    ctx = make_ctx(world, proof_required=True)
    sha = "2" * 64

    def attempt(p, gate="music-approval", verdict="accept"):
        gates.record_approval(ctx, gate, by=None, note="x", verdict=verdict, sha256=sha, proof=p)

    with pytest.raises(Refused, match="expired"):
        attempt(signed(ctx, "music-approval", subjects=[sha], expires=-10))
    with pytest.raises(Refused, match="another gate"):
        attempt(signed(ctx, "publish-approval", subjects=[sha]))
    with pytest.raises(Refused, match="verdict"):
        attempt(signed(ctx, "music-approval", verdict="change", subjects=[sha]))
    revoked = signed(ctx, "music-approval", subjects=[sha], proof_id="gone")
    write(trust / "issuers.json", {"issuers": {ISSUER: {"principal": PRINCIPAL, "key_hex": KEY}}, "revoked": ["gone"]})
    with pytest.raises(Refused, match="revoked"):
        attempt(revoked)


def test_no_trust_root_means_no_authority(tmp_path, monkeypatch) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    ctx = make_ctx(world, proof_required=True)
    p = signed(ctx, "music-approval", subjects=["3" * 64])
    monkeypatch.delenv(proof.TRUST_ENV)
    with pytest.raises(Refused, match="no trust root"):
        gates.record_approval(ctx, "music-approval", by=None, note="x", verdict="accept", sha256="3" * 64, proof=p)


def test_run_approve_cli_by_name_creates_no_record_on_a_live_episode(tmp_path, capsys) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    ctx = make_ctx(world)
    argv = ["run", "approve", "--episode", str(world.episode_file), "--runs-root", str(world.runs_root), "--gate",
            "music-approval", "--verdict", "accept", "--by", PRINCIPAL, "--note", "ok", "--sha256", "4" * 64]
    code = jjv_module().main(argv)
    capsys.readouterr()
    assert code != 0 and not list(ctx.approvals_dir.glob("music-approval-*.json"))
    pfile = write(tmp_path / "proof.json", signed(ctx, "music-approval", subjects=["4" * 64]))
    code = jjv_module().main(argv + ["--approval-file", str(pfile)])
    assert code == 0 and len(list(ctx.approvals_dir.glob("music-approval-*.json"))) == 1


# ---- G01: a bare GPU flag is a request, not an authorization -------------------------------------------------------
def _gpu_run(world, monkeypatch, capsys, fake, *more, proof_file=None):
    monkeypatch.setattr(orchestrator, "health_gate_status", lambda dag: "available")
    argv = world.base_argv("--from", "still-nine", "--to", "still-nine", approve_gpu=True)
    if proof_file:
        argv += ["--gpu-proof", str(proof_file)]
    return run_cli(capsys, monkeypatch, fake, argv + list(more))


def _gpu_proof(world, tmp_path, stages=("still-nine",), mode="batch", dag_sha=None, **kw):
    ctx = make_ctx(world)
    scope = {"stages": list(stages), "mode": mode, "dag_sha256": dag_sha or live_dag().sha256}
    return write(tmp_path / f"gpu-{mode}.json", signed(ctx, "gpu-dispatch", scope=scope, proof_id=f"gpu-{mode}", **kw))


def test_bare_gpu_flag_does_not_authorize_dispatch(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    fake = FakeRunner()
    code, receipt = _gpu_run(world, monkeypatch, capsys, fake)
    assert fake.touched_gpu() == [], "G01: bare --approve-gpu dispatched a fake GPU verb"
    assert code != 0 and receipt["first_stop"]["kind"] == "gpu-approval"
    assert "bare --approve-gpu" in receipt["first_stop"]["reason"]


def test_a_gpu_file_by_existence_is_not_authority(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    write(world.runs_root / "approvals" / "gpu-pilot-approved.json", {"ok": True})
    write(world.runs_root / "approvals" / "gpu-approved.json", {"ok": True})
    fake = FakeRunner()
    _gpu_run(world, monkeypatch, capsys, fake)
    assert fake.touched_gpu() == [] and not any("--pilot" in c for c in fake.calls)


@pytest.mark.parametrize("kw", [
    {"stages": ("voice",)}, {"dag_sha": "f" * 64}, {"expires": -5}, {"key": "cd" * 32}, {"gate": "music-approval"},
])
def test_gpu_proof_outside_its_scope_is_refused(tmp_path, capsys, monkeypatch, kw) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    gate = kw.pop("gate", "gpu-dispatch")
    ctx = make_ctx(world)
    if gate != "gpu-dispatch":
        pfile = write(tmp_path / "g.json", signed(ctx, gate, scope={"stages": ["still-nine"], "dag_sha256": live_dag().sha256}))
    else:
        pfile = _gpu_proof(world, tmp_path, **kw)
    fake = FakeRunner()
    code, receipt = _gpu_run(world, monkeypatch, capsys, fake, proof_file=pfile)
    assert fake.touched_gpu() == [] and receipt["first_stop"]["kind"] == "gpu-approval"


def test_scoped_gpu_proof_reaches_the_fake_dispatch_and_pilot_mode_adds_pilot(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    pfile = _gpu_proof(world, tmp_path, mode="pilot")
    fake = FakeRunner(receipts={("images", "plan"): "images-plan.json"})
    code, receipt = _gpu_run(world, monkeypatch, capsys, fake, proof_file=pfile)
    submits = [c for c in fake.calls if c[:2] == ("images", "submit")]
    assert submits and all("--pilot" in c for c in submits), receipt["first_stop"]
    batch = make_run_world(tmp_path / "b", domain=LIVE, episode_id="live-fixture")
    fake2 = FakeRunner(receipts={("images", "plan"): "images-plan.json"})
    _gpu_run(batch, monkeypatch, capsys, fake2, proof_file=_gpu_proof(batch, tmp_path / "b", mode="batch"))
    assert [c for c in fake2.calls if c[:2] == ("images", "submit")]
    assert not any("--pilot" in c for c in fake2.calls)
