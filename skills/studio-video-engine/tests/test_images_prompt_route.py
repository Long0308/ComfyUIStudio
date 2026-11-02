"""IMGRT-1: `images route list`, `images prompt new|confirm` and the comfyui-local queue gate (G4). CPU only, no network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from engine.core.errors import Refused
from engine.images import cli, codex_queue, local, prompt_route
from images_fixtures import World

NEWT, CARTOON = "newtecons_live_action", "jenniejoy_cartoon_3d"
FACE_TEXT = "Portrait of the site engineer, 3:4 frame, plain background."


def make(tmp_path, domain=NEWT, **kw):
    world = World(tmp_path, domain=domain)
    ctx = world.ctx()
    out = tmp_path / "prompts"
    args = dict(text=FACE_TEXT, prompt_id="FREE_1", kind="FACE", aspect=None, refs=[], route=None, rev=None, batch_id=None)
    args.update(kw)
    return ctx, out, prompt_route.prompt_new(ctx, out, **args)


def item_of(ctx, made):
    from pathlib import Path
    allowed, forbidden = codex_queue.batch_roots(ctx, [])
    return codex_queue.load_batch(Path(made["batch"]), allowed=allowed, forbidden=forbidden)[0]


def confirm(made, **kw):
    from pathlib import Path
    args = dict(prompt_id=None, sha256=made["prompt_sha256"], by="long", note="ok")
    args.update(kw)
    return prompt_route.prompt_confirm(Path(made["queue"]), **args)


def test_free_form_prompt_is_refused_until_confirm(tmp_path):
    ctx, _, made = make(tmp_path)
    row = json.loads((tmp_path / "prompts" / "queue-p-FREE_1.json").read_text("utf-8"))[0]
    assert row["dispatch_allowed"] is False and row["domain"] == NEWT
    with pytest.raises(Refused, match="dispatch_allowed:false"):
        codex_queue._refuse_blocked(item_of(ctx, made), True)
    confirm(made)
    codex_queue._refuse_blocked(item_of(ctx, made), True)  # now cleared by the SAME gate


def test_confirm_is_write_once_and_sha_bound(tmp_path):
    _, out, made = make(tmp_path)
    before = (out / "queue-p-FREE_1.json").read_bytes()
    with pytest.raises(Refused, match="read the prompt again"):
        confirm(made, sha256="0" * 64)
    assert (out / "queue-p-FREE_1.json").read_bytes() == before and not (out / "confirmations").exists()
    assert confirm(made)["reused"] is False
    assert confirm(made)["reused"] is True  # same by/note: no-op
    with pytest.raises(Refused, match="write-once"):
        confirm(made, by="someone else")
    record = json.loads(next((out / "confirmations").glob("FREE_1-*.json")).read_text("utf-8"))
    assert record["by"] == "long" and record["confirmed_utc"]


def test_edited_batch_text_cannot_be_confirmed(tmp_path):
    _, out, made = make(tmp_path)
    batch = out / "FREE_1.json"
    data = json.loads(batch.read_text("utf-8"))
    data[0]["prompt_text"] = "something else 3:4"
    batch.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Refused, match="no longer matches"):
        confirm(made)


def test_face_canvas_lock_and_nothing_written_on_refusal(tmp_path):
    world = World(tmp_path, domain=NEWT)
    out = tmp_path / "p2"
    with pytest.raises(Refused, match="16:9"):
        prompt_route.prompt_new(world.ctx(), out, text="face, 16:9", prompt_id="BAD_1", kind="FACE", aspect=None,
                                refs=[], route=None, rev=None, batch_id=None)
    assert not out.exists() or list(out.iterdir()) == []
    with pytest.raises(Refused, match="locked to 3:4"):
        prompt_route.prompt_new(world.ctx(), out, text="face 3:4", prompt_id="BAD_2", kind="FACE", aspect="1:1",
                                refs=[], route=None, rev=None, batch_id=None)


def test_comfy_real_submit_needs_a_cleared_queue_row_for_newtecons(tmp_path):
    ctx, _, made = make(tmp_path)
    with pytest.raises(Refused, match="provenance_required"):
        local.queue_gate(ctx, None, dry_run=False)  # no queue row at all (e.g. --prompt-file)
    with pytest.raises(Refused, match="dispatch_allowed:false"):
        local.queue_gate(ctx, item_of(ctx, made), dry_run=False)
    # the real entry point refuses before --pilot, settings or any HTTP: client None would otherwise be a different error
    with pytest.raises(Refused, match="provenance_required"):
        local.submit(ctx, tmp_path / "o", "S01_A", tmp_path / "x.txt", None, None, pilot=True)
    local.queue_gate(ctx, None, dry_run=True)  # dry-run unchanged
    confirm(made)
    local.queue_gate(ctx, item_of(ctx, made), dry_run=False)


def test_jenniejoy_behaviour_is_unchanged(tmp_path):
    world = World(tmp_path, domain=CARTOON)
    ctx = world.ctx()
    local.queue_gate(ctx, None, dry_run=False)  # no queue needed for the cartoon domain
    args = SimpleNamespace(provider="comfyui-local", n=1, library_out=None, shot="S01_A", prompt_batch="b.json",
                           take=None, prompt_file=None)
    with pytest.raises(Refused, match="only for --provider codex-exec"):
        cli._submit(ctx, tmp_path / "o", args)


def test_row_of_another_domain_is_refused_for_comfy(tmp_path):
    _, out, made = make(tmp_path)  # a NEWTECONS row
    cartoon = World(tmp_path / "c", domain=CARTOON).ctx()
    from pathlib import Path
    with pytest.raises(Refused, match="is for domain"):
        prompt_route.comfy_item(cartoon, Path(made["batch"]), tmp_path / "o")


def test_route_list_follows_the_domain_policy(tmp_path):
    newt = prompt_route.route_list(World(tmp_path / "n", domain=NEWT).ctx())
    toon = prompt_route.route_list(World(tmp_path / "c", domain=CARTOON).ctx())
    assert "openrouter" not in newt["allowed_providers"] and newt["provenance_required"] is True
    assert [r["provider"] for r in newt["routes"]][-1] == "comfyui-local"
    assert any(r["recipe"] == "krea2-edit-local-v001" and r["gpu"] and r["installed"] == "unknown" for r in newt["routes"][1:])
    assert toon["routes"][0]["provider"] == "codex-exec" and toon["provenance_required"] is False
    assert newt["live"].startswith("not measured")
