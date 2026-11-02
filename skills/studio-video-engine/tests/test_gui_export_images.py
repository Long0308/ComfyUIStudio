"""Image adapter uses real local.prepare and current pack/library approvals.

Only fixture *generation* is customized: PackWorld's non-image blobs become
deterministic PNGs before the fixture writes its approval records and pack.
No approval reader, graph builder or exporter gate is mocked.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
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

import pack_fixtures  # noqa: E402
from engine.core.errors import Refused  # noqa: E402
from engine.core.io import read_json, sha256_file  # noqa: E402
from engine.gui_export.images import load_images  # noqa: E402
from engine.images import imgutil, local, prompt_route, receipts  # noqa: E402
from engine.video.anchor_refs import resolve_recorded  # noqa: E402
from test_h3_pack_bind import PackWorld, SHOT  # noqa: E402


def _dump(path, body):
    Path(path).write_text(json.dumps(body), encoding="utf-8")


def _png(path, token):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    color = tuple(hashlib.sha256(str(token).encode()).digest()[:3])
    imgutil.pil().new("RGB", (96, 128), color).save(path, format="PNG")
    return path


@pytest.fixture
def images_prepared(tmp_path, monkeypatch):
    original_library = pack_fixtures.Library
    original_board = pack_fixtures.storyboard_spec

    class PngLibrary(original_library):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for kinds in self.entries.values():
                for entries in kinds.values():
                    for entry in entries:
                        path = self.dir / entry["file"]
                        _png(path, entry["prompt_id"])
                        entry["sha256"] = sha256_file(path)
                        body = read_json(Path(entry["receipt"]))
                        body["output"].update(sha256=entry["sha256"], width=96, height=128)
                        _dump(entry["receipt"], body)
            _dump(self.index, {"characters": self.entries, "revs": {"r1": "test"}})

    def png_board(world):
        result = original_board(world)
        _png(result["path"], "approved storyboard")
        body = read_json(Path(result["receipt"]))
        body["output"]["sha256"] = sha256_file(Path(result["path"]))
        _dump(result["receipt"], body)
        return result

    monkeypatch.setattr(pack_fixtures, "Library", PngLibrary)
    monkeypatch.setattr(pack_fixtures, "storyboard_spec", png_board)
    world = PackWorld(tmp_path)
    pack = read_json(world.pack_path)
    ctx = world.ctx()
    out = world.root / "gui-image-inputs"
    out.mkdir()
    placement = out / "placement.txt"
    placement.write_text("Keep the approved composition.", encoding="utf-8")
    guide = resolve_recorded(pack["storyboard_anchor"]["path"], ctx.machine)
    refs = [receipts.file_ref(resolve_recorded(row["path"], ctx.machine), role)
            for role in ("face", "body") for row in pack.get(f"{role}_refs") or []]
    _dump(out / receipts.PLAN_FILE, {"schema": receipts.PLAN_SCHEMA, "episode_id": ctx.episode_id,
                                   "domain": ctx.domain_id, "shots": [{"shot": SHOT,
                                       "guide": receipts.file_ref(guide, "guide"),
                                       "placement": receipts.file_ref(placement, "placement"), "refs": refs}]})
    prompt = out / "source-prompt.txt"
    prompt.write_text("Use the approved storyboard and exact character identities.", encoding="utf-8")
    queued = prompt_route.prompt_new(ctx, out / "prompt-route", text=prompt.read_text(encoding="utf-8"),
                                     prompt_id="GUI_IMAGE_SHOT", kind="SHOT", aspect=None, refs=[],
                                     route="comfy-krea2-edit-local-v001", rev="gui", batch_id="gui-image-batch")
    prompt_route.prompt_confirm(Path(queued["queue"]), prompt_id=queued["prompt_id"], sha256=queued["prompt_sha256"],
                                by="Kim", note="Confirmed fixture image prompt")
    prepared = local.prepare(ctx, out, SHOT, prompt, task="general", seed=42, take="t001")
    world.image_out, world.image_prepared = out, prepared["folder"]
    world.image_prompt_batch, world.image_prompt_queue = Path(queued["batch"]), Path(queued["queue"])
    return world


def _load(world, **kwargs):
    return load_images(world.ctx(), world.image_prepared, SHOT,
                       anchor_pack=world.pack_path, prompt_batch=world.image_prompt_batch, **kwargs)


def _change_plan(world, change):
    path = world.image_out / receipts.PLAN_FILE
    body = read_json(path)
    change(body)
    _dump(path, body)


def test_images_adapter_reconstructs_real_prepared_graph_and_approved_sheet(images_prepared):
    result = _load(images_prepared)
    assert result["shot"] == SHOT and result["tier"] == "preview"
    assert {row["role"] for row in result["bindings"]} == {"guide", "derived-approved-cast-sheet"}
    assert all(sha256_file(Path(row["path"])) == row["sha256"] for row in result["bindings"])
    assert result["graph"]["13"]["inputs"]["seed"] == 42
    assert "anchor_pack" in result["receipts"] and "image_plan" in result["receipts"]
    assert "prompt_confirmation" in result["receipts"] and "prompt_batch" in result["receipts"]


def test_images_adapter_refuses_missing_pack(images_prepared):
    with pytest.raises(Refused, match="ANCHOR_PACK_MISSING"):
        load_images(images_prepared.ctx(), images_prepared.image_prepared, SHOT)


def test_images_adapter_refuses_pending_pack_storyboard(images_prepared):
    world = images_prepared
    pack = read_json(world.pack_path)
    pack["storyboard_anchor"]["status"] = "pending"
    pack.update(status="pending", ready_for_graph=False)
    _dump(world.pack_path, pack)
    with pytest.raises(Refused, match="STORYBOARD_PENDING|ANCHOR_PACK_NOT_APPROVED"):
        _load(world)


def test_images_adapter_refuses_revoked_actual_library_approval(images_prepared):
    world = images_prepared
    pack = read_json(world.pack_path)
    Path(pack["face_refs"][0]["approval_record"]).unlink()
    with pytest.raises(Refused, match="ANCHOR_NOT_APPROVED|ANCHOR_APPROVAL_SHA_MISMATCH"):
        _load(world)


def test_images_adapter_refuses_graph_changes(images_prepared):
    world = images_prepared
    path = world.image_prepared / "graph.api.json"
    graph = read_json(path)
    graph["5"]["inputs"]["image"] = "another-unapproved.png"
    _dump(path, graph)
    with pytest.raises(Refused, match="GUI_IMAGE_GRAPH"):
        _load(world)


def test_images_adapter_refuses_foreign_plan(images_prepared):
    _change_plan(images_prepared, lambda plan: plan.update(domain="foreign_domain"))
    with pytest.raises(Refused, match="GUI_IMAGE_FOREIGN"):
        _load(images_prepared)


@pytest.mark.parametrize("which", ["guide", "ref"])
def test_images_adapter_refuses_unapproved_plan_media(images_prepared, which):
    world = images_prepared
    rogue = _png(world.image_out / "rogue.png", "unapproved")
    def change(plan):
        row = plan["shots"][0]
        if which == "guide":
            row["guide"] = receipts.file_ref(rogue, "guide")
        else:
            row["refs"][0] = receipts.file_ref(rogue, "face")
    _change_plan(world, change)
    with pytest.raises(Refused, match="GUI_IMAGE_UNAPPROVED"):
        _load(world)


def test_images_adapter_refuses_corrupted_sheet(images_prepared):
    world = images_prepared
    path = world.image_prepared / "cast-sheet.png"
    image = imgutil.load_rgb(path)
    image.putpixel((0, 0), (0, 0, 0))
    image.save(path, format="PNG")
    with pytest.raises(Refused, match="GUI_IMAGE_SHEET"):
        _load(world)


def test_images_adapter_refuses_apng_even_with_identical_first_frame(images_prepared):
    world = images_prepared
    path = world.image_prepared / "cast-sheet.png"
    first = imgutil.load_rgb(path)
    second = imgutil.pil().new("RGB", first.size, (255, 0, 0))
    first.save(path, format="PNG", save_all=True, append_images=[second], duration=100, loop=0)
    with pytest.raises(Refused, match="GUI_IMAGE_SHEET"):
        _load(world)


def test_images_adapter_refuses_exif_orientation_on_derived_sheet(images_prepared):
    world = images_prepared
    path = world.image_prepared / "cast-sheet.png"
    image = imgutil.load_rgb(path)
    exif = imgutil.pil().Exif()
    exif[274] = 6
    image.save(path, format="PNG", exif=exif)
    with pytest.raises(Refused, match="GUI_IMAGE_SHEET"):
        _load(world)


def test_images_adapter_refuses_higher_tier(images_prepared):
    with pytest.raises(Refused, match="GUI_TIER_REFUSED"):
        _load(images_prepared, tier="fullhd")


def _newtecons_queue_context(world):
    # Use the actual production domain recipe's provenance_required rule. The
    # queue refusal occurs BEFORE loading this fixture's cartoon anchor pack.
    domain = "newtecons_live_action"
    ctx = world.ctx()
    _change_plan(world, lambda plan: plan.update(domain=domain))
    return replace(ctx, domain_id=domain, domain=read_json(_SKILL / "domains" / f"{domain}.json"),
                   episode={**ctx.episode, "domain": domain})


def test_images_adapter_requires_batch_when_actual_domain_requires_provenance(images_prepared):
    world = images_prepared
    ctx = _newtecons_queue_context(world)
    with pytest.raises(Refused, match="provenance_required|no queue row"):
        load_images(ctx, world.image_prepared, SHOT, anchor_pack=world.pack_path)


def test_images_adapter_refuses_unconfirmed_real_prompt_queue(images_prepared):
    world = images_prepared
    ctx = _newtecons_queue_context(world)
    queued = prompt_route.prompt_new(ctx, world.image_out / "unconfirmed-prompt-route",
                                     text="Unconfirmed image prompt", prompt_id="UNCONFIRMED_IMAGE_SHOT",
                                     kind="SHOT", aspect=None, refs=[], route="comfy-krea2-edit-local-v001",
                                     rev="unconfirmed", batch_id="unconfirmed-image-batch")
    with pytest.raises(Refused, match="blocked|dispatch_allowed|confirm"):
        load_images(ctx, world.image_prepared, SHOT, anchor_pack=world.pack_path, prompt_batch=Path(queued["batch"]))


def test_images_adapter_refuses_prepared_prompt_edited_after_queue_confirmation(images_prepared):
    path = images_prepared.image_prepared / "prompt.txt"
    path.write_text("Unapproved edited prepared prompt", encoding="utf-8")
    with pytest.raises(Refused, match="GUI_IMAGE_PROMPT"):
        _load(images_prepared)
