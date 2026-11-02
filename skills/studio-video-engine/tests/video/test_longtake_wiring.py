"""CPU-only route, long graph and approved legacy-anchor regression checks."""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.h3 import prepare as prepare_mod
from engine.video import longrender, routes as routes_mod, run as run_mod


def test_run_rechecks_long_route_before_render(monkeypatch) -> None:
    scheduler = object.__new__(run_mod.Scheduler)
    scheduler.ctx = type("C", (), {"domain_id": "newtecons_live_action"})()
    scheduler.route = routes_mod.load_routes()["domains"][scheduler.ctx.domain_id]
    receipt = {"shot": "LT20", "duration_s": 20, "take_mode_requested": "auto",
               "take_mode": "long", "take_route": "h3-longtake"}
    decision = scheduler._take_decision(receipt)
    assert decision["route"] == "h3-longtake"
    with pytest.raises(Refused, match="LONG_TAKE_ON_SHORT_ROUTE"):
        scheduler._take_decision(receipt, "h3-ref2va")
    receipt["take_route"] = "h3-ref2va"
    with pytest.raises(Refused, match="TAKE_PLAN_DRIFT"):
        scheduler._take_decision(receipt)


def test_unqualified_long_route_needs_token(tmp_path) -> None:
    ctx = type("C", (), {"root": tmp_path, "domain_id": "newtecons_live_action"})()
    block = {"route": "h3-longtake", "qualification": None}
    template = {"sha256": "a" * 64}
    with pytest.raises(Refused, match="LONG_TAKE_UNQUALIFIED"):
        longrender._qualification(ctx, block, {"kind": "receipt"}, template)
    assert longrender._qualification(ctx, block, {"kind": "token", "value": "approved"}, template) is None


def test_missing_anchor_pack_refuses_without_approved_legacy(tmp_path, monkeypatch) -> None:
    ctx = type("C", (), {"root": tmp_path})()
    row = {"shot": "LT20"}
    with pytest.raises(Refused, match="ANCHOR_PACK_MISSING"):
        prepare_mod.require_anchor_pack_or_approved_legacy(ctx, {}, row, [{"sha256": "a" * 64}])
    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps({"characters": [{"character_id": "CHAR01", "prompt_id": "p",
                                                  "receipt": "r", "approval_record": "a", "approval": "ok"}]}), "utf-8")
    anchor = tmp_path / "approval.json"
    anchor.write_text("{}", "utf-8")
    native = tmp_path / "native.json"
    native.write_text("{}", "utf-8")
    scene = tmp_path / "scene.png"
    scene.write_bytes(b"approved scene")
    row["anchor"] = {"path": str(scene), "sha256": sha256_file(scene)}
    evidence = {"provenance": {"legacy_cast_faces": {"enabled": True, "shots": ["LT20"]},
                               "cast": {"path": str(cast), "sha256": sha256_file(cast)},
                               "shots": {"LT20": {"image_approval": {"path": str(anchor), "sha256": sha256_file(anchor)},
                                                  "native_receipt": {"path": str(native), "sha256": sha256_file(native)}}}}}
    seen = []
    from engine.h3 import inputs as inputs_mod
    monkeypatch.setattr(inputs_mod, "approved_anchor", lambda *_a: (scene, sha256_file(scene), {}))
    monkeypatch.setattr(prepare_mod.pack_refs, "_require_ref_approval", lambda _ctx, _row, ref: seen.append(ref))
    prepare_mod.require_anchor_pack_or_approved_legacy(
        ctx, evidence, row, [{"character_id": "CHAR01", "sha256": "a" * 64}])
    assert len(seen) == 1 and seen[0]["name"] == "CHAR01"


def test_long_dispatch_calls_guarded_h3_helper_without_gpu(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "h3-r001" / "LT20"
    folder.mkdir(parents=True)
    video = tmp_path / "take.mp4"
    video.write_bytes(b"fake take")
    calls = []
    monkeypatch.setattr(longrender, "check_graph", lambda *_a, **_k: None)
    monkeypatch.setattr(longrender.ClassPolicy, "from_domain", lambda _domain: object())
    monkeypatch.setattr(longrender, "run_pid_lock", lambda *_a, **_k: nullcontext())
    monkeypatch.setattr(longrender.submit_mod, "_existing", lambda _folder: None)
    monkeypatch.setattr(longrender.submit_mod, "_submit_one", lambda *_a, **_k: calls.append("guarded") or
                        {"status": "COMPLETED", "prompt_id": "fake-prompt"})
    monkeypatch.setattr(longrender.adopt_mod, "_job", lambda *_a: {"prompt_id": "fake-prompt", "client_id": "fake"})
    monkeypatch.setattr(longrender.adopt_mod, "_copy_outputs", lambda *_a: [
        {"role": "editorial", "path": str(video), "sha256": sha256_file(video), "name": video.name}])
    monkeypatch.setattr(longrender.adopt_mod, "_gui", lambda *_a: (None, "offline"))
    monkeypatch.setattr(longrender.adopt_mod, "_review_gui", lambda *_a, **_k: {"nodes": []})
    monkeypatch.setattr(longrender.adopt_mod, "_publish", lambda *_a, **_k: {"workflow": "review.json"})
    from engine.comfy import staging
    monkeypatch.setattr(staging, "stage_input", lambda *_a: None)
    ctx = type("C", (), {"domain": {}, "episode_id": "film"})()
    comfy = type("H", (), {"settings": type("S", (), {"executor_lock_path": tmp_path / "lock",
                                                        "input_dir": tmp_path})(),
                            "client": object(), "probe": object(), "ps": object()})()
    path, result = longrender.dispatch_and_adopt(ctx, tmp_path, folder,
                                                 {"shot": "LT20", "graph_sha256": "b" * 64,
                                                  "wav": {"sha256": "c" * 64}}, {}, comfy, 1)
    assert path == folder / "adopt.json" and result["adopted"]["prompt_id"] == "fake-prompt"
    assert calls == ["guarded"]


def test_long_graph_preparation_has_six_window_prompts(tmp_path, monkeypatch) -> None:
    files = {}
    for name in ("anchor.png", "face.png", "line.wav"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        files[name] = path
    def media(name, node, key):
        path = files[name]
        return {"path": str(path), "sha256": sha256_file(path), "ports": [[node, key]]}
    anchor, face = media("anchor.png", "8", "image"), media("face.png", "5", "image")
    monkeypatch.setattr(prepare_mod, "_media", lambda *_a: (anchor, [face], [], None))
    monkeypatch.setattr(prepare_mod, "require_anchor_pack_or_approved_legacy", lambda *_a: None)
    monkeypatch.setattr(prepare_mod, "voice_proof", lambda *_a: {"approved": True})
    monkeypatch.setattr(prepare_mod, "domain_guard", lambda *_a: {"output_prefix_root": "NEWTECONS"})
    monkeypatch.setattr(longrender, "static_refusals", lambda *_a: [])
    monkeypatch.setattr(longrender.ClassPolicy, "from_domain", lambda _domain: object())
    ctx = type("C", (), {"root": tmp_path, "domain_id": "newtecons_live_action", "domain": {},
                          "episode_id": "film"})()
    route = routes_mod.load_routes()["domains"][ctx.domain_id]
    manifest = tmp_path / "h3-inputs.json"
    manifest.write_text(json.dumps({"voice_dir": "voice"}), "utf-8")
    receipt = {"shot": "LT20", "duration_s": 20, "length": {"frames": 481}, "seed": 42,
               "geometry": {"width": 864, "height": 480},
               "take_windows": [f"beat {n}" for n in range(6)]}
    state = {"shot": "LT20", "revision": 1}
    folder, prep, graph = longrender.prepare_graph(
        ctx, tmp_path / "out", state, receipt, "global wardrobe rule", route, manifest,
        {"shot": "LT20", "wav": media("line.wav", "7", "audio")},
        {"kind": "token", "value": "approved"})
    assert prep["window_count"] == 6 and len(prep["window_log"]) == 6
    assert graph["19"]["inputs"]["value"].endswith("beat 0\n")
    assert graph["45"]["inputs"]["value"].endswith("beat 5\n")
    assert (folder / "graph.api.json").is_file()
