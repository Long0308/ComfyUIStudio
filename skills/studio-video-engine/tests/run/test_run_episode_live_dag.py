"""B01: the run recipe is chosen from the episode's domain (data), and a live-action episode gets its own DAG.

No verb really runs: every step goes through the recording FakeRunner.  Domain names appear in recipes and tests
(data), never in engine source.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

import pytest
from run_fixtures import CARTOON, LIVE, FakeRunner, make_run_world, run_cli, write

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.run import dag as dag_mod
from engine.run import gates
from engine.run.context import load_run_context
from test_run_dag_live_fix import trust  # noqa: F401  (fixture: signer trust root for the proof sidecars)

@functools.lru_cache(maxsize=1)
def _live_dag():
    return dag_mod.load_dag(domain_id=LIVE)


class _LazyDag:
    """Resolved on first use, not at import: collection no longer reads recipes/run/ (shared, may be mid-edit)."""

    def __getattr__(self, name):
        return getattr(_live_dag(), name)


LIVE_DAG = _LazyDag()
# the audit order (AUDIT-AUTO-NEWTECONS-v001): each id must appear, in this order
CHAIN = ["config", "ingest", "storyboard", "library", "layout-plan", "layout-author", "layout-check", "layout-render",
         "still-route-check", "still-assets", "still-set-control", "still-lock", "still-nine", "still-fix", "still-review",
         "images-native", "voice", "video-plan", "h3-qualification", "h3-inputs",
         "video-render", "upscale-1080p", "publish-shots", "timing", "music", "editorial", "mix", "edit", "qa", "review", "master", "deliver",
         "brand", "publish"]


def stage(receipt: dict, stage_id: str) -> dict:
    return next(s for s in receipt["stages"] if s["id"] == stage_id)


def declare(world, **files: str) -> None:
    doc = json.loads(world.episode_file.read_text("utf-8"))
    doc["files"].update(files)
    write(world.episode_file, doc)


# ---- selection by domain (data) ---------------------------------------------------------------------------
def test_recipe_is_selected_by_the_episodes_domain() -> None:
    assert LIVE_DAG.domains == (LIVE,)
    assert dag_mod.load_dag(domain_id=CARTOON).path.name == "episode-dag-v001.json"
    assert dag_mod.load_dag().path.name == "episode-dag-v001.json"            # default unchanged
    assert LIVE_DAG.path != dag_mod.load_dag(domain_id=CARTOON).path


def test_a_domain_with_no_recipe_is_refused_naming_it() -> None:
    with pytest.raises(Refused, match="cross-domain") as err:
        dag_mod.load_dag(domain_id="no_such_domain")
    assert "no_such_domain" in str(err.value)


def test_two_recipes_for_one_domain_are_refused(tmp_path: Path, monkeypatch) -> None:
    raw = json.loads(LIVE_DAG.path.read_text("utf-8"))
    write(tmp_path / "a.json", raw)
    write(tmp_path / "b.json", {**raw, "id": "run/other"})
    monkeypatch.setattr(dag_mod, "RECIPE_DIR", tmp_path)
    with pytest.raises(Refused, match="more than one"):
        dag_mod.load_dag(domain_id=LIVE)


def test_engine_run_source_names_no_domain() -> None:
    for file in (SKILL_ROOT / "engine" / "run").glob("*.py"):
        assert not re.search(r"newtecons|jenniejoy|live_action|cartoon", file.read_text("utf-8"), re.I), file.name


# ---- the recipe itself ------------------------------------------------------------------------------------
def test_live_chain_is_the_audit_order() -> None:
    ids = list(LIVE_DAG.ids)
    assert ids == CHAIN


def test_every_gpu_verb_and_human_gate_is_an_explicit_stop() -> None:
    gpu = {tuple(step.argv[:2]) for s in LIVE_DAG.stages for step in s.steps if step.gpu}
    assert {("voice", "synth"), ("images", "submit"), ("video", "run")} <= gpu
    # h3 prepare/submit/adopt run INSIDE `video run` (per-shot scheduler): no second GPU path in the recipe
    assert not any(step.argv[:2] in (("h3", "submit"), ("h3", "prepare")) for s in LIVE_DAG.stages for step in s.steps)
    for sid in ("h3-qualification", "upscale-1080p"):
        row = LIVE_DAG.stage(sid)
        assert row.human == "receipt-gate" and not row.steps
    assert "needs-gpu-pilot-approval" in LIVE_DAG.stage("upscale-1080p").human_gates["receipt-gate"]["label"]
    assert LIVE_DAG.stage("review").human == "user-review"
    assert any(step.human == "publish-approval" for step in LIVE_DAG.stage("publish").steps)


def test_live_recipe_is_not_the_cartoon_recipe_for_upscale_or_2k() -> None:
    verbs = {tuple(step.argv[:2]) for s in LIVE_DAG.stages for step in s.steps}
    assert ("seedvr2", "execute") not in verbs and ("deliver", "film-2k") not in verbs


# ---- gate kind ---------------------------------------------------------------------------------------------
def test_receipt_gate_passes_only_when_a_matching_file_exists(tmp_path: Path) -> None:
    world = make_run_world(tmp_path, domain=LIVE)
    ctx = load_run_context(str(world.episode_file), runs_root=world.runs_root, stages_root=world.stages_root)
    spec = {"receipt-gate": {"file": str(tmp_path / "q" / "*.json"), "label": "needs-x", "next": "do the pilot"}}
    state = gates.check(ctx, "s", spec, "receipt-gate")
    assert not state.ok and "needs-x" in state.detail and state.next_step == "do the pilot"
    write(tmp_path / "q" / "r.json", {"ok": True})
    assert gates.check(ctx, "s", spec, "receipt-gate").ok


# ---- jjv run episode --dry-run on a live-action episode -----------------------------------------------------
def test_live_dry_run_stops_at_the_first_unmet_gate_and_names_it(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    # Qualification receipts live outside the fixture; simulate both being absent.
    ctx = load_run_context(str(world.episode_file), runs_root=world.runs_root, stages_root=world.stages_root)
    qualification_paths = {
        gates.spec_of(LIVE_DAG.stage(sid).human_gates, "receipt-gate", ctx, sid)["file"]
        for sid in ("h3-qualification", "upscale-1080p")
    }
    expand = gates.expand
    monkeypatch.setattr(gates, "expand", lambda pattern: [] if pattern in qualification_paths else expand(pattern))
    fake = FakeRunner()
    code, plan = run_cli(capsys, monkeypatch, fake, world.base_argv(dry_run=True))
    assert code == 0 and plan["dry_run"] and fake.calls == [] and plan["domain"] == LIVE
    assert plan["dag"]["id"] == LIVE_DAG.id and [s["id"] for s in plan["stages"]] == CHAIN
    first = plan["first_stop"]
    assert first["stage"] == "library" and first["kind"] == "human-gate"
    assert "library_dir" in first["reason"]                                  # names what is missing
    for sid, label in (("h3-qualification", "h3"), ("upscale-1080p", "needs-gpu-pilot-approval")):
        stop = stage(plan, sid)["would_stop"]
        assert stop["kind"] == "human-gate" and label in stop["reason"]


def test_live_dry_run_moves_on_to_the_layout_author_stop_once_the_library_gate_holds(tmp_path, capsys, monkeypatch, trust) -> None:
    from test_run_dag_live_fix import build_library, make_ctx
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    build_library(world, make_ctx(world), sidecar=True)     # full coverage + cast + signed sidecar proofs (trust root by fixture)
    code, plan = run_cli(capsys, monkeypatch, FakeRunner(), world.base_argv(dry_run=True))
    assert code == 0 and stage(plan, "library")["human"]["ok"] is True
    assert plan["first_stop"]["stage"] == "layout-author" and plan["first_stop"]["kind"] == "human-gate"
    for sid, kind in (("layout-render", "gpu-approval"), ("still-nine", "gpu-approval"), ("still-set-control", "human-gate")):
        assert stage(plan, sid)["would_stop"]["kind"] == kind, sid


def test_live_video_run_is_a_gpu_stop_without_approval_and_is_never_run(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path, domain=LIVE, episode_id="live-fixture")
    fake = FakeRunner()
    code, plan = run_cli(capsys, monkeypatch, fake, world.base_argv(dry_run=True))
    row = stage(plan, "video-render")
    assert [s["id"] for s in row["steps"]] == ["run"] and row["steps"][0]["gpu"] is True
    assert fake.touched_gpu() == [] and not any(c[:2] == ("video", "run") for c in fake.calls)


def test_cartoon_still_gets_its_own_recipe(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    code, plan = run_cli(capsys, monkeypatch, FakeRunner(), world.base_argv(dry_run=True))
    assert code == 0 and plan["dag"]["id"] == "run/episode-dag-v001"
