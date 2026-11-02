"""CR-QUEUEOWN: the ``.owner`` sidecar and machine aliases may not forge episode ownership of a domain-less queue."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.core.io import sha256_file
from engine.core.errors import Refused
from engine.images import codex_queue
from images_fixtures import LIVE, World


def make_run(tmp: Path, ctx, *, run_json: bool = True, runs: str = "pool.runs", source: Path | None = None,
             episode_ref: str | None = None) -> tuple[Path, Path]:
    """A library run dir with a queue copy + sidecar; returns (queue copy, source queue under episode staging)."""
    src = source or (ctx.root / "staging" / "image-batches" / "queue-r005.json")
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("[]", encoding="utf-8")
    batches = tmp / runs / "20261031" / "batches"
    batches.mkdir(parents=True)
    copy = batches / "queue-r005.json"
    copy.write_bytes(src.read_bytes())
    codex_queue.write_owner_sidecar(ctx, src, copy)  # returns False for a foreign source (test forges the note)
    if run_json:
        (batches.parent / "run.json").write_text(json.dumps({
            "context": {"episode": episode_ref or str(ctx.episode_file)},
            "queues": [{"source": src.as_posix(), "copy": copy.as_posix(), "sha256": sha256_file(copy)}]}), encoding="utf-8")
    return copy, src


def refuse(ctx, queue: Path) -> None:
    codex_queue._refuse_domain({"queue_file": str(queue), "prompt_id": "P"}, True, ctx)


def test_genuine_run_sidecar_is_accepted(tmp_path):
    ctx = World(tmp_path / "w", domain=LIVE).ctx()
    copy, _ = make_run(tmp_path, ctx)
    refuse(ctx, copy)


def test_forged_sidecar_next_to_a_queue_outside_any_run_is_refused(tmp_path):
    ctx = World(tmp_path / "w", domain=LIVE).ctx()
    copy, src = make_run(tmp_path, ctx)
    evil = tmp_path / "elsewhere" / "queue-r005.json"
    evil.parent.mkdir()
    evil.write_bytes(copy.read_bytes())
    Path(str(evil) + ".owner").write_text(Path(str(copy) + ".owner").read_text("utf-8"), encoding="utf-8")
    with pytest.raises(Refused, match="no domain ownership"):
        refuse(ctx, evil)


def test_sidecar_without_the_runs_own_run_json_is_refused(tmp_path):
    ctx = World(tmp_path / "w", domain=LIVE).ctx()
    copy, _ = make_run(tmp_path, ctx, run_json=False)
    with pytest.raises(Refused, match="no domain ownership"):
        refuse(ctx, copy)


def test_sidecar_whose_source_is_outside_episode_staging_is_refused(tmp_path):
    ctx = World(tmp_path / "w", domain=LIVE).ctx()
    other = tmp_path / "w2" / "ep" / "staging" / "queue-r005.json"
    copy, _ = make_run(tmp_path, ctx, source=other)  # write_owner_sidecar refuses, so forge the note by hand
    note = {"episode_id": ctx.episode_id, "domain": ctx.domain_id, "queue_sha256": sha256_file(copy), "source": other.as_posix()}
    Path(str(copy) + ".owner").write_text(json.dumps(note), encoding="utf-8")
    (copy.parent.parent / "run.json").write_text(json.dumps({
        "context": {"episode": str(ctx.episode_file)},
        "queues": [{"source": other.as_posix(), "copy": copy.as_posix(), "sha256": sha256_file(copy)}]}), encoding="utf-8")
    with pytest.raises(Refused, match="no domain ownership"):
        refuse(ctx, copy)


def test_run_json_of_another_episode_is_refused(tmp_path):
    ctx = World(tmp_path / "w", domain=LIVE).ctx()
    other = World(tmp_path / "other", domain=LIVE).ctx()
    copy, _ = make_run(tmp_path, ctx, episode_ref=str(other.episode_file))
    with pytest.raises(Refused, match="no domain ownership"):
        refuse(ctx, copy)


@pytest.mark.parametrize("alias", [".", "production-local", "production-local/engine/staging", "production-local/Story"])
def test_over_broad_alias_is_ignored(tmp_path, monkeypatch, alias):
    repo = tmp_path / "repo"
    ctx = World(repo / "production-local" / "Story" / "mine", domain=LIVE).ctx()
    (repo / "production-local" / "engine" / "staging").mkdir(parents=True)
    other = World(repo / "production-local" / "Story" / "theirs", domain=LIVE)  # another episode under the alias
    monkeypatch.setattr(codex_queue, "REPO_ROOT", repo)
    ctx.machine.setdefault("images", {})["legacy_queue_roots"] = {ctx.episode_id: [alias]}
    queue = other.root / "staging" / "queue-r005.json"
    queue.parent.mkdir(parents=True)
    queue.write_text("[]", encoding="utf-8")
    assert not codex_queue.legacy_queue_owned(ctx, queue)


def test_sidecar_whose_source_no_longer_exists_is_refused(tmp_path):
    ctx = World(tmp_path / "w", domain=LIVE).ctx()
    copy, src = make_run(tmp_path, ctx)
    src.unlink()  # forged run.json + .owner naming a source that is not there
    with pytest.raises(Refused, match="no domain ownership"):
        refuse(ctx, copy)


def test_sidecar_whose_source_has_different_content_is_refused(tmp_path):
    ctx = World(tmp_path / "w", domain=LIVE).ctx()
    copy, src = make_run(tmp_path, ctx)
    src.write_text('[{"forged": true}]', encoding="utf-8")  # copy is no longer byte-identical to its source
    with pytest.raises(Refused, match="no domain ownership"):
        refuse(ctx, copy)
