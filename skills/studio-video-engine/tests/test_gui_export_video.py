"""Video adapter exercises the existing H3/anchor/listen approval readers.

Reuses the engine's PackWorld, whose fake ComfyUI directory and approval files
are all inside pytest's temporary directory. No H3 or pack gate is mocked.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROPOSED = Path(__file__).resolve().parents[1]
_REPO = next(parent for parent in _PROPOSED.parents if (parent / ".agents/skills/studio-video-engine").is_dir())
_SKILL = _REPO / ".agents/skills/studio-video-engine"
for _path in (_SKILL, _SKILL / "tests", _SKILL / "tests/h3", _SKILL / "tests/video"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import engine  # noqa: E402

if str(_PROPOSED / "engine") not in engine.__path__:
    engine.__path__.insert(0, str(_PROPOSED / "engine"))

from engine.core.errors import Refused  # noqa: E402
from engine.core.io import canonical_json, canonical_sha256, read_json, sha256_file  # noqa: E402
from engine.gui_export.video import load_video  # noqa: E402
from engine.h3 import prepare as h3_prepare  # noqa: E402
from test_h3_pack_bind import PackWorld, SHOT  # noqa: E402


@pytest.fixture
def prepared(tmp_path):
    world = PackWorld(tmp_path)
    world.stage()
    world.build()
    h3_prepare.prepare(world.ctx(), world.tmp / "built-inputs.json", world.out)
    return world


def _receipt(world):
    return world.out / SHOT / "preparation.json"


def _replace_receipt(world, change):
    body = read_json(_receipt(world))
    change(body)
    _receipt(world).write_text(json.dumps(body), encoding="utf-8")


def _change_graph(world, change):
    path = world.out / SHOT / "graph.api.json"
    graph = read_json(path)
    change(graph)
    path.write_bytes(canonical_json(graph, mode="ascii"))
    digest = canonical_sha256(graph, mode="ascii")
    _replace_receipt(world, lambda receipt: receipt.update(graph_sha256=digest, api={"path": path.name, "sha256": digest}))


def test_video_adapter_reads_real_preparation_and_all_approved_bindings(prepared):
    world = prepared
    result = load_video(world.ctx(), world.out, SHOT, "preview")
    assert result["shot"] == SHOT and result["tier"] == "preview"
    assert result["source_graph_sha256"] == sha256_file(Path(result["graph_path"]))
    assert {item["role"] for item in result["bindings"]} == {"anchor", "wav", "face", "body", "wardrobe"}
    assert len(result["bindings"]) == 6
    assert all(Path(row["path"]).is_file() and sha256_file(Path(row["path"])) == row["sha256"]
               for row in result["receipts"].values())
    assert (world.world.comfy_root / "input").is_dir()
    assert not (world.world.comfy_root / "user").exists()  # adapter itself never publishes workflows


def test_video_adapter_refuses_revoked_real_voice_approval(prepared):
    prepared.revoke_approval()
    with pytest.raises(Refused, match="E_LISTEN_APPROVAL"):
        load_video(prepared.ctx(), prepared.out, SHOT)


def test_video_adapter_refuses_revoked_real_anchor_approval(prepared):
    pack = read_json(prepared.pack_path)
    Path(pack["face_refs"][0]["approval_record"]).unlink()
    with pytest.raises(Refused, match="ANCHOR_NOT_APPROVED|ANCHOR_APPROVAL_SHA_MISMATCH"):
        load_video(prepared.ctx(), prepared.out, SHOT)


def test_video_adapter_refuses_pilot_substitute_without_mocks(tmp_path):
    world = PackWorld(tmp_path, storyboard=False)
    world.stage()
    world.build(allow_pending_storyboard=True)
    h3_prepare.prepare(world.ctx(), world.tmp / "built-inputs.json", world.out)
    with pytest.raises(Refused, match="STORYBOARD_PENDING"):
        load_video(world.ctx(), world.out, SHOT)


@pytest.mark.parametrize("tier", ["fullhd", "2k", "unknown"])
def test_video_adapter_refuses_non_native_tiers(prepared, tier):
    with pytest.raises(Refused, match="GUI_TIER_REFUSED"):
        load_video(prepared.ctx(), prepared.out, SHOT, tier)


@pytest.mark.parametrize("field,value", [("shot", "OTHER"), ("status", "UNAPPROVED"),
                                        ("domain", "foreign_domain")])
def test_video_adapter_refuses_preparation_identity_drift(prepared, field, value):
    _replace_receipt(prepared, lambda receipt: receipt.update({field: value}))
    with pytest.raises(Refused, match="GUI_PREPARATION|another episode/domain"):
        load_video(prepared.ctx(), prepared.out, SHOT)


def test_video_adapter_refuses_prepared_graph_loader_receipt_disagreement(prepared):
    # Rehashing the graph receipt must not authorize a different media input.
    _change_graph(prepared, lambda graph: graph["7"]["inputs"].update(audio="another-unapproved.wav"))
    with pytest.raises(Refused, match="GUI_MEDIA_BINDING"):
        load_video(prepared.ctx(), prepared.out, SHOT)


def test_video_adapter_refuses_incomplete_pack_ref_binding(prepared):
    _replace_receipt(prepared, lambda receipt: receipt["refs"].pop())
    with pytest.raises(Refused, match="ANCHOR_PACK_REF_MISMATCH"):
        load_video(prepared.ctx(), prepared.out, SHOT)


def test_video_adapter_refuses_unbound_extra_loader(prepared):
    _change_graph(prepared, lambda graph: graph.update({"99": {"class_type": "LoadImage", "inputs": {"image": "unapproved.png"}}}))
    with pytest.raises(Refused, match="GUI_MEDIA_BINDING"):
        load_video(prepared.ctx(), prepared.out, SHOT)
