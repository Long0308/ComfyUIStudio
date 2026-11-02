"""Tails end to end on a fake ComfyUI: plan -> existing execute -> check -> assemble -> map -> coverage closes.

No GPU, no real ComfyUI, no network: the fake server restores a chunk by renaming its frame ids.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.config import loader
from engine.core.errors import Failed, Refused, exit_code_for
from engine.core.io import sha256_file
from engine.seedvr2 import coverage, tails, tails_assemble
from engine.seedvr2.execplan import load_exec_plan, select_tasks
from engine.seedvr2.plan import build_plan
from fake_comfy import FakeComfy
from test_seedvr2_segments_support import (executor, fake_probe, install_render, make_settings, make_world,
                                           read_ids, write_media)


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


class Rig:
    def __init__(self, tmp_path: Path, fake: FakeComfy) -> None:
        self.world = make_world(tmp_path, comfy_url=fake.url)
        self.fake = fake
        self.out = self.world.root / "tails-run"
        tails.plan_tails(self.world.config, repo_root=loader.REPO_ROOT, reads=self.world.reads, out=self.out,
                         probe=fake_probe, runner=self.world.runner)
        self.plan = load_exec_plan(self.out / tails.TAILS_PLAN_FILE, self.world.config, self.world.recipe)
        self.settings = make_settings(self.world, fake.url)
        install_render(self.world, fake, self.plan.geometry)

    def run(self) -> dict:
        return executor(self.world, self.plan, self.settings).run(select_tasks(self.plan.tasks))

    def check(self) -> dict:
        return tails_assemble.check_tails_run(self.plan, probe=fake_probe, runner=self.world.runner)

    def assemble(self, name: str = "masters") -> dict:
        return tails_assemble.assemble_tail_masters(self.plan, self.world.tmp / name, probe=fake_probe,
                                                    runner=self.world.runner)


@pytest.fixture()
def rig(tmp_path: Path, fake: FakeComfy) -> Rig:
    return Rig(tmp_path, fake)


@pytest.fixture()
def done(rig: Rig) -> Rig:
    result = rig.run()
    assert result["exit_code"] == 0 and result["stopped"] is None
    return rig


def test_execute_runs_the_tails_plan_through_the_existing_path(done: Rig) -> None:
    assert len(done.fake.posts_made()) == 1
    graph = done.fake.posts[0]["prompt"]
    assert graph["15"]["inputs"]["filename_prefix"].endswith("/tails/S01_A/chunk-0000")
    shot = json.loads((done.plan.root / "runs/S01_A/shot.json").read_text())
    assert shot["frame_count"] == 7 and shot["status"] == "COMPLETED"
    assert read_ids(Path(shot["path"]))[0].startswith("raw[") and len(read_ids(Path(shot["path"]))) == 7


def test_check_is_green_after_a_real_run(done: Rig) -> None:
    report = done.check()
    assert report["all_pass"], json.dumps(report, indent=1)
    names = list(report["shots"][0]["checks"])
    assert any("core == crop(trim(raw))" in n for n in names) and any("shot concat frames" in n for n in names)
    assert (done.plan.root / "runs" / tails_assemble.REPORT_FILE).is_file()


def test_assemble_cuts_the_tail_frames_and_writes_the_map(done: Rig) -> None:
    summary = done.assemble()
    (entry,) = summary["tails"]
    clip = done.world.tmp / "masters" / entry["clip"]
    core_ids = read_ids(Path(entry["source_core"]))
    assert read_ids(clip) == core_ids[4:7], "context frames 0..3 are dropped; the 3 tail frames are kept"
    assert entry["native_first"] == 40 and entry["frames"] == 3 and entry["clip_sha256"] == sha256_file(clip)
    assert entry["transition"] == "T40" and entry["start_from_frame_30fps"] == 0
    # (50 + k) * 24 / 30 = 40, 40.8, 41.6  ->  floor 40,40,41  ceil 40,41,42  (relative to native 40)
    assert entry["clip_frame_for_output_k"] == {"floor": [0, 0, 1], "ceil": [0, 1, 2]}
    document = json.loads((done.world.tmp / "masters" / "MASTER-TAIL-MAP.json").read_text())
    assert document["schema"] == "jjv/master-tail-map/v1" and document["plan_sha256"] == done.plan.sha256
    assert entry["clip"].startswith("master-tails/S01_A-tail-3840x2160-n040-n042")


def test_the_map_closes_the_coverage_the_plan_gate_refuses_without_it(done: Rig) -> None:
    world, config = done.world, done.world.config
    with pytest.raises(Refused, match=r"S01_A f40\.\.f42") as caught:
        build_plan(config, repo_root=loader.REPO_ROOT, reads=world.reads, probe=fake_probe)
    assert exit_code_for(caught.value) == 1
    posts_before = len(done.fake.posts_made())
    summary = done.assemble()
    extra = coverage.load_tail_map(Path(summary["map_path"]))
    assert extra == [("S01_A", 40, 43)]
    ok = build_plan(config, repo_root=loader.REPO_ROOT, reads=world.reads, extra_scope=extra, probe=fake_probe)
    assert ok.plan["coverage"]["ok"]
    assert len(done.fake.posts_made()) == posts_before, "planning never POSTs"
    assert tails.build_tails_plan(config, repo_root=loader.REPO_ROOT, reads=world.reads, extra_scope=extra,
                                  probe=fake_probe) is None, "nothing left to restore"


def test_dropping_the_tail_chunk_is_refused_with_exit_1_and_no_post(rig: Rig) -> None:
    """Audit acceptance: the plan with the tail dropped is refused before anything is sent."""
    with pytest.raises(Refused) as caught:
        build_plan(rig.world.config, repo_root=loader.REPO_ROOT, reads=rig.world.reads, extra_scope=[],
                   probe=fake_probe)
    assert exit_code_for(caught.value) == 1 and rig.fake.posts_made() == []
    assert caught.value.evidence["missing"][0]["shot"] == "S01_A"


# ---- the checks can fail (negative controls) --------------------------------------------------------
def chunk_job(rig: Rig) -> tuple[Path, dict]:
    path = rig.plan.root / "runs/S01_A/chunk-0000/job.json"
    return path, json.loads(path.read_text())


def test_check_fails_when_the_core_file_changed_and_assemble_refuses(done: Rig) -> None:
    _, job = chunk_job(done)
    write_media(Path(job["core_path"]), ["evil"] * 7, 3840, 2160)
    report = done.check()
    assert not report["all_pass"]
    failed = [n for n, c in report["shots"][0]["checks"].items() if not c["pass"]]
    assert any("receipts re-verify" in n for n in failed)
    with pytest.raises(Refused, match="not green"):
        done.assemble()
    assert not (done.world.tmp / "masters").exists()


def test_check_catches_a_core_that_is_not_the_raw_even_when_the_receipt_was_rewritten(done: Rig) -> None:
    """A consistent forgery (new core + its sha in job.json and provenance) passes the hash proof and must
    still fail the framemd5 proof 'core == crop(trim(raw))'."""
    path, job = chunk_job(done)
    core = Path(job["core_path"])
    write_media(core, [f"forged:{i}" for i in range(7)], 3840, 2160)
    digest = sha256_file(core)
    job["core_sha256"] = digest
    job["core_provenance"]["core_sha256"] = digest
    path.write_text(json.dumps(job))
    report = done.check()
    checks = report["shots"][0]["checks"]
    assert checks["chunk-0000 receipts re-verify (hashes, provenance, probes)"]["pass"]
    assert not checks["chunk-0000 core == crop(trim(raw)) (framemd5)"]["pass"]
    assert not report["all_pass"]


def test_check_fails_without_the_shot_receipt_or_before_the_run(done: Rig, rig: Rig) -> None:
    (done.plan.root / "runs/S01_A/shot.json").unlink()
    assert not done.check()["all_pass"]


def test_check_on_a_plan_nobody_ran_is_red(rig: Rig) -> None:
    report = rig.check()
    assert not report["all_pass"]
    assert any("job.json present" in n for n in report["shots"][0]["checks"])


def test_assemble_is_write_once_and_md5_verified(done: Rig) -> None:
    done.assemble()
    with pytest.raises(Refused, match="overwrite"):
        done.assemble()  # the clip exists: never replaced
    done.world.runner.corrupt = lambda path, ids: ["bad:" + i for i in ids]
    with pytest.raises(Failed, match="frames differ from the finalized core"):
        done.assemble("masters2")
    assert not list((done.world.tmp / "masters2").rglob("*.mp4")) and not (done.world.tmp / "masters2" / "MASTER-TAIL-MAP.json").exists()


def test_a_mapping_that_leaves_the_clip_is_refused() -> None:
    from fractions import Fraction
    transition = {"id": "T9", "delivery_start_frame": 50, "output_frames": 12, "delivery_fps": 30}
    with pytest.raises(Refused, match="leaves its tail clip"):
        tails_assemble._output_mapping(transition, 40, 3, Fraction(24))
    assert tails_assemble._output_mapping({**transition, "delivery_fps": None}, 40, 3, Fraction(24)) is None


def test_tails_check_refuses_a_normal_plan(tmp_path: Path, fake: FakeComfy) -> None:
    from engine.seedvr2.plan import write_plan
    from engine.seedvr2.segments import run_segments
    world = make_world(tmp_path, comfy_url=fake.url)
    out = world.root / "main"
    run_segments(world.config, repo_root=loader.REPO_ROOT, out_root=out, probe=fake_probe, runner=world.runner)
    write_plan(out, build_plan(world.config, repo_root=loader.REPO_ROOT, segments_root=out, probe=fake_probe))
    plan = load_exec_plan(out / "seedvr2-plan-v2.json", world.config, world.recipe)
    with pytest.raises(Refused, match="not a tails plan"):
        tails_assemble.check_tails_run(plan, probe=fake_probe, runner=world.runner)


def test_a_plan_without_reads_has_no_coverage_or_kind_key(tmp_path: Path) -> None:
    """The existing 134-chunk parity tests prove the plan is unchanged; this pins the two new keys as opt-in."""
    world = make_world(tmp_path)
    plan = build_plan(world.config, repo_root=loader.REPO_ROOT, probe=fake_probe).plan
    assert "coverage" not in plan and "kind" not in plan
