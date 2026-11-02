"""IMGRT-FIX regressions: CPU-only queue isolation, confirmation and canvas checks."""
import json
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.images import codex, codex_queue, local, prompt_route
from images_fixtures import World
from test_images_prompt_route import NEWT, CARTOON, make, item_of, confirm


def queue_batch(folder, *, domain=None, file_domain=None, name="queue-test.json"):
    folder.mkdir(parents=True, exist_ok=True)
    batch = folder / "batch.json"
    batch.write_text(json.dumps([{"prompt_id": "P1", "prompt_text": "frame 3:4", "ref_images": []}]), "utf-8")
    rows = [{"prompt_id": "P1", "dispatch_allowed": True, "domain": domain}]
    value = {"domain": file_domain, "rows": rows} if file_domain else rows
    (folder / name).write_text(json.dumps(value), "utf-8")
    return batch


def gate(ctx, batch, provider):
    if provider == "comfy":
        item, _ = prompt_route.comfy_item(ctx, batch, batch.parent / "out")
        local.queue_gate(ctx, item, False)
    else:
        # Valid provenance reaches the account check; no runner or remote calls.
        try:
            codex.submit_library_batch(ctx, batch.parent / "out", batch, [], codex_cmd=["unused"],
                                       state_path=batch.parent / "state.json")
        except Refused as error:
            if "no codex accounts" not in str(error):
                raise


@pytest.mark.parametrize("provider", ["codex", "comfy"])
@pytest.mark.parametrize("domain", [None, CARTOON])
def test_gap1_unowned_or_wrong_domain_refused(tmp_path, provider, domain):
    ctx = World(tmp_path / "world", domain=NEWT).ctx()
    batch = queue_batch(tmp_path / "unowned", domain=domain)
    with pytest.raises(Refused, match="domain"):
        gate(ctx, batch, provider)


@pytest.mark.parametrize("provider", ["codex", "comfy"])
def test_gap1_queue_document_can_declare_domain(tmp_path, provider):
    ctx = World(tmp_path / "world", domain=NEWT).ctx()
    gate(ctx, queue_batch(tmp_path / "declared", file_domain=NEWT), provider)


@pytest.mark.parametrize("provider", ["codex", "comfy"])
@pytest.mark.parametrize("owned", [True, False])
def test_gap1_legacy_r005_requires_own_staging(tmp_path, provider, owned):
    ctx = World(tmp_path / "world", domain=NEWT).ctx()
    root = ctx.root if owned else tmp_path / "other_episode"
    batch = queue_batch(root / "staging" / "library", name="queue-r005f.json")
    if owned:
        gate(ctx, batch, provider)
    else:
        with pytest.raises(Refused, match="domain"):
            gate(ctx, batch, provider)


def test_gap2_new_rows_are_marked(tmp_path):
    _, _, made = make(tmp_path)
    assert json.loads(Path(made["queue"]).read_text("utf-8"))[0]["source"] == "prompt_route"


@pytest.mark.parametrize("provider", ["codex", "comfy"])
def test_gap2_manual_dispatch_toggle_needs_confirmation(tmp_path, provider):
    ctx, _, made = make(tmp_path)
    path = Path(made["queue"])
    rows = json.loads(path.read_text("utf-8"))
    rows[0]["dispatch_allowed"] = True
    path.write_text(json.dumps(rows), "utf-8")
    with pytest.raises(Refused, match="confirmation"):
        gate(ctx, Path(made["batch"]), provider)


@pytest.mark.parametrize("field", ["prompt_sha256", "prompt_id", "queue", "schema"])
def test_gap2_receipt_must_match(tmp_path, field):
    ctx, _, made = make(tmp_path)
    record = Path(confirm(made)["confirmation"])
    value = json.loads(record.read_text("utf-8"))
    value[field] = "tampered"
    record.write_text(json.dumps(value), "utf-8")
    with pytest.raises(Refused, match="confirmation"):
        codex_queue._refuse_blocked(item_of(ctx, made), True)


@pytest.mark.parametrize("kind", ["SHOT", "ASSET", "SET", "FIX"])
def test_gap3_no_lock_is_explicit(tmp_path, kind):
    _, _, made = make(tmp_path, kind=kind)
    row = json.loads(Path(made["queue"]).read_text("utf-8"))[0]
    assert row["canvas_check"] == f"no canvas lock for kind {kind}"


@pytest.mark.parametrize("kind", ["SHOT", "ASSET", "SET", "FIX"])
def test_gap3_recipe_lock_is_checked(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(prompt_route.library_plan, "library_canvas", lambda: {kind: "16:9"})
    with pytest.raises(Refused, match="16:9"):
        make(tmp_path, kind=kind)


@pytest.mark.parametrize("same_episode", [True, False])
def test_gap1_known_legacy_external_staging_is_episode_bound(tmp_path, monkeypatch, same_episode):
    from dataclasses import replace
    ctx = World(tmp_path / "world", domain=NEWT).ctx()
    episode_id = "Newtecons-TienDo-KichTinh-30s"
    root = tmp_path / "production-local" / "JennieJoyKids-Story" / episode_id
    if not same_episode:
        root = root.with_name("another-episode")
    ctx = replace(ctx, root=root, episode={**ctx.episode, "episode_id": episode_id if same_episode else "another-episode"})
    monkeypatch.setattr(codex_queue, "REPO_ROOT", tmp_path)
    ctx.machine.setdefault("images", {})["legacy_queue_roots"] = {
        episode_id: ["production-local/engine/staging/newtecons-30s"]}
    batch = queue_batch(tmp_path / "production-local" / "engine" / "staging" / "newtecons-30s" / "image-batches-r005f",
                        name="queue-r005f.json")
    if same_episode:
        gate(ctx, batch, "codex")
    else:
        with pytest.raises(Refused, match="domain"):
            gate(ctx, batch, "codex")


def test_document_queue_duplicate_prompt_is_refused(tmp_path):
    ctx = World(tmp_path / "world", domain=NEWT).ctx()
    batch = queue_batch(tmp_path / "prompts", file_domain=NEWT)
    with pytest.raises(Refused, match="already has a row"):
        prompt_route.prompt_new(ctx, batch.parent, text="frame 3:4", prompt_id="P1", kind="FACE", aspect=None,
                                refs=[], route=None, rev=None, batch_id=None)


@pytest.mark.parametrize("provider", ["codex", "comfy"])
def test_valid_confirmation_passes_both_routes(tmp_path, provider):
    ctx, _, made = make(tmp_path)
    confirm(made)
    gate(ctx, Path(made["batch"]), provider)


def test_domain_document_cannot_contradict_row(tmp_path):
    ctx = World(tmp_path / "world", domain=NEWT).ctx()
    batch = queue_batch(tmp_path / "conflict", domain=NEWT, file_domain=CARTOON)
    with pytest.raises(Refused, match="domain"):
        gate(ctx, batch, "codex")


def test_unknown_queue_under_own_staging_still_refused(tmp_path):
    ctx = World(tmp_path / "world", domain=NEWT).ctx()
    batch = queue_batch(ctx.root / "staging" / "library")
    with pytest.raises(Refused, match="domain"):
        gate(ctx, batch, "codex")


def test_cartoon_untagged_queue_still_passes(tmp_path):
    ctx = World(tmp_path / "world", domain=CARTOON).ctx()
    gate(ctx, queue_batch(tmp_path / "legacy-cartoon"), "codex")


def test_cartoon_free_form_dispatch_behavior_is_unchanged(tmp_path):
    ctx, _, made = make(tmp_path, domain=CARTOON)
    queue = Path(made["queue"])
    rows = json.loads(queue.read_text("utf-8"))
    rows[0]["dispatch_allowed"] = True
    queue.write_text(json.dumps(rows), "utf-8")
    gate(ctx, Path(made["batch"]), "codex")


def test_confirmation_checked_again_at_dispatch(tmp_path):
    ctx, _, made = make(tmp_path)
    record = Path(confirm(made)["confirmation"])
    item = item_of(ctx, made)
    record.write_text("{}", "utf-8")
    with pytest.raises(Refused, match="confirmation"):
        local.queue_gate(ctx, item, False)


# ---- WINFLASH: tiến trình con không bật cửa sổ console đen ----------------------------------------------
def test_winflash_children_get_create_no_window(tmp_path, monkeypatch):
    import subprocess
    import sys
    from engine.core.winflags import no_window
    from engine.images import codex_run, library_run
    seen = []

    class FakePopen:
        pid = 1

        def __init__(self, *a, **kw):
            seen.append(kw.get("creationflags"))

    monkeypatch.setattr(library_run.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(library_run, "write_launch_record", lambda *a, **k: None)
    library_run.spawn_lane(tmp_path / "plan.json", tmp_path, "acct1", detach=False)
    monkeypatch.setattr(codex_run.subprocess, "run", lambda *a, **kw: seen.append(kw.get("creationflags")))
    codex_run.default_runner(["x"], input_text="", env={}, cwd=str(tmp_path), timeout=1)
    if sys.platform == "win32":
        assert no_window() == subprocess.CREATE_NO_WINDOW
        assert all(flags & subprocess.CREATE_NO_WINDOW for flags in seen) and len(seen) == 2
    else:
        assert seen == [0, 0] and no_window() == 0
