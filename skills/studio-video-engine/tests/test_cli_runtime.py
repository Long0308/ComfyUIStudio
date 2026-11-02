"""M4: the CLI verbs (`seedvr2 execute`, `comfy submit|wait|reconcile`), the domain rule, a real
ffmpeg trim on a tiny clip, and source hygiene."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from config_fixtures import make_live_action_world
from engine import cli_runtime
from engine.config import loader
from engine.core.io import sha256_file
from engine.media.probe import probe_video
from engine.seedvr2.media_ops import Geometry, core_trim_filter, trim_core
from exec_fixtures import SHOT, FakeDocker, fake_probe, make_rig
from fake_comfy import FakeComfy

SKILL = loader.SKILL_ROOT


def jjv():
    spec = importlib.util.spec_from_file_location("jjv_cli_m4", SKILL / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


@pytest.fixture()
def wired(fake, tmp_path, monkeypatch):
    """The rig's config behind the CLI, with fake media tools (no real ffprobe/ffmpeg/docker)."""
    rig = make_rig(tmp_path, fake)
    monkeypatch.setattr(cli_runtime, "resolve_episode", lambda ref: rig.config)
    real = cli_runtime.Executor
    monkeypatch.setattr(cli_runtime, "Executor", lambda **kw: real(
        **kw, probe=fake_probe, runner=rig.ffmpeg, emit=lambda message: None, container_probe=FakeDocker()))
    return rig


def run_cli(capsys, *argv: str) -> tuple[int, dict]:
    code = jjv().main(list(argv))
    return code, json.loads(capsys.readouterr().out)


# ---- domain rule -------------------------------------------------------------------------
@pytest.mark.parametrize("extra", [[], ["--execute"]])
def test_a_domain_without_a_qualified_recipe_refuses_execution_exit_one(tmp_path, capsys, extra) -> None:
    world = make_live_action_world(tmp_path)
    code, out = run_cli(capsys, "seedvr2", "execute", "--episode", str(world.episode_file),
                        "--plan", str(tmp_path / "no-plan.json"), *extra)
    assert code == 1 and out["ok"] is False and "no qualified seedvr2 recipe" in out["error"]


def test_the_cartoon_recipe_is_not_borrowed_by_a_plan_for_another_domain(fake, tmp_path) -> None:
    from engine.core.errors import Refused
    rig = make_rig(tmp_path, fake)
    plan = json.loads(rig.plan.path.read_text())
    plan["domain"] = "newtecons_live_action"
    rig.plan.path.write_text(json.dumps(plan))
    with pytest.raises(Refused, match="domain"):
        rig.reload_plan()


# ---- seedvr2 execute ---------------------------------------------------------------------
def test_cli_dry_run_prints_post_skipped_and_touches_nothing(wired, fake, tmp_path, capsys) -> None:
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    code, out = run_cli(capsys, "seedvr2", "execute", "--episode", "ignored", "--plan", str(wired.plan.path),
                        "--max-chunks", "2")
    assert code == 0 and out["dry_run"] is True and out["message"] == "POST skipped (dry-run)"
    assert out["planned_chunks"] == 2 and fake.requests == []
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


def test_cli_execute_runs_resumes_and_reports_one_json_summary(wired, fake, capsys) -> None:
    args = ("seedvr2", "execute", "--episode", "ignored", "--plan", str(wired.plan.path), "--execute",
            "--no-telemetry", "--only", f"{SHOT}:0,{SHOT}:1")
    code, out = run_cli(capsys, *args)
    assert code == 0 and out["ok"] and [c["chunk"] for c in out["completed"]] == ["chunk-0000", "chunk-0001"]
    code, out = run_cli(capsys, *args)  # no --resume: existing state refuses, nothing is sent
    assert code == 2 and out["stopped"]["stage"] == "existing_state" and len(fake.posts_made()) == 2
    code, out = run_cli(capsys, *args, "--resume")
    assert code == 0 and len(fake.posts_made()) == 2


def test_cli_execute_exit_code_is_two_when_the_post_outcome_is_unknown(wired, fake, capsys) -> None:
    fake.post_mode = "drop"
    code, out = run_cli(capsys, "seedvr2", "execute", "--episode", "ignored", "--plan", str(wired.plan.path),
                        "--execute", "--no-telemetry", "--max-chunks", "1")
    assert code == 2 and out["stopped"]["stage"] == "post_outcome_unknown" and len(fake.posts_made()) == 1


def test_cli_execute_refuses_a_plan_outside_the_episode_tree(wired, fake, tmp_path, capsys) -> None:
    outside = tmp_path / "scratch" / "plan"
    shutil.copytree(wired.plan.root, outside)
    code, out = run_cli(capsys, "seedvr2", "execute", "--episode", "ignored",
                        "--plan", str(outside / wired.plan.path.name), "--execute", "--no-telemetry")
    assert code == 1 and "escaped" in out["error"] and fake.requests == []
    code, _ = run_cli(capsys, "seedvr2", "execute", "--episode", "ignored",
                      "--plan", str(outside / wired.plan.path.name), "--max-chunks", "1")
    assert code == 0, "a dry run may read a scratch plan anywhere"


def test_cli_execute_requires_a_gpu_lock_path(wired, fake, capsys, monkeypatch) -> None:
    import dataclasses
    broken = dataclasses.replace(wired.config, machine={**wired.config.machine, "gpu_lock_path": " "})
    monkeypatch.setattr(cli_runtime, "resolve_episode", lambda ref: broken)
    code, out = run_cli(capsys, "seedvr2", "execute", "--episode", "ignored", "--plan", str(wired.plan.path),
                        "--execute", "--no-telemetry")
    assert code == 1 and "gpu_lock_path" in out["error"] and fake.requests == []


# ---- comfy verbs -------------------------------------------------------------------------
def test_cli_comfy_submit_wait_reconcile(wired, fake, tmp_path, capsys) -> None:
    graph = tmp_path / "g.json"
    graph.write_text(json.dumps({"1": {"class_type": "LocalNode", "inputs": {}}}))
    rc = tmp_path / "rc"
    fake.on_post = None  # this graph has no node 15 to render
    code, out = run_cli(capsys, "comfy", "submit", "--episode", "x", "--graph", str(graph),
                        "--receipt-dir", str(rc), "--expect-sha", sha256_file(graph))
    assert code == 0 and out["prompt_id"] == "pid-0001" and len(fake.posts_made()) == 1
    code, out = run_cli(capsys, "comfy", "wait", "--episode", "x", "--receipt-dir", str(rc), "--timeout", "2")
    assert code == 0 and out["status"] == "COMPLETED"
    code, out = run_cli(capsys, "comfy", "reconcile", "--episode", "x", "--receipt-dir", str(rc))
    assert code == 0 and out["status"] == "matched" and len(fake.posts_made()) == 1
    code, out = run_cli(capsys, "comfy", "submit", "--episode", "x", "--graph", str(graph),
                        "--receipt-dir", str(rc))
    assert code == 1 and "receipt dir was used" in out["error"] and len(fake.posts_made()) == 1


def test_cli_comfy_submit_refuses_claudenode_with_exit_one(wired, fake, tmp_path, capsys) -> None:
    graph = tmp_path / "g.json"
    graph.write_text(json.dumps({"1": {"class_type": "ClaudeNode", "inputs": {}}}))
    code, out = run_cli(capsys, "comfy", "submit", "--episode", "x", "--graph", str(graph),
                        "--receipt-dir", str(tmp_path / "rc"))
    assert code == 1 and out["ok"] is False and fake.posts_made() == [] and fake.requests == []


def test_cli_comfy_reconcile_with_no_trace_is_exit_two(wired, fake, tmp_path, capsys) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "dispatch-intent.json").write_text(json.dumps({"client_id": "jjv-x", "graph_sha256": "a" * 64}))
    code, out = run_cli(capsys, "comfy", "reconcile", "--episode", "x", "--receipt-dir", str(rc))
    assert code == 2 and out["ok"] is False and out["status"] == "none"


# ---- real ffmpeg on a tiny clip: trim [offset, offset+core) and crop, never resize -------
@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg absent")
def test_real_core_trim_selects_the_right_frames_and_crops_without_resizing(tmp_path) -> None:
    raw = tmp_path / "raw.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=24:duration=1.0",
                    "-frames:v", "21", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "0", str(raw)],
                   check=True)
    geometry = Geometry(fps=__import__("fractions").Fraction(24), fps_text="24/1", processing_width=64,
                        processing_height=48, final_width=32, final_height=48, crop_left=4, crop_top=0,
                        padding_alignment=4, core_encoding="libx264-crf0-yuv420p")
    core = trim_core(raw, tmp_path / "core" / "c.mp4", offset=4, frames=13, geometry=geometry)
    info = probe_video(core, count_packets=True)
    assert (info.frames, info.width, info.height) == (13, 32, 48)

    def md5s(path: Path, vf: str) -> list[str]:
        out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", vf, "-f", "framemd5", "-"],
                             capture_output=True, text=True, check=True).stdout
        return [line.split(",")[-1].strip() for line in out.splitlines() if not line.startswith("#")]

    expected = md5s(raw, "select='between(n\\,4\\,16)',crop=32:48:4:0")  # independent of trim=
    assert md5s(core, "null") == expected and len(expected) == 13
    with pytest.raises(Exception, match="overwrite"):
        trim_core(raw, tmp_path / "core" / "c.mp4", offset=4, frames=13, geometry=geometry)
    assert core_trim_filter(4, 13, geometry) == (
        "trim=start_frame=4:end_frame=17,setpts=PTS-STARTPTS,crop=32:48:4:0")


# ---- hygiene -----------------------------------------------------------------------------
def test_every_engine_file_stays_under_400_lines() -> None:
    for source in (SKILL / "engine").rglob("*.py"):
        assert len(source.read_text("utf-8").splitlines()) < 400, source


def test_every_test_file_stays_under_400_lines() -> None:
    for source in (SKILL / "tests").glob("*.py"):
        assert len(source.read_text("utf-8").splitlines()) < 400, source


_TECHNICAL_FOLDER = re.compile(r"\btechnical\b")


def names_the_technical_folder(text: str) -> bool:
    """Chữ ``technical`` đứng riêng hoặc làm một đoạn đường dẫn (thư mục `technical/` của episode cũ) là vi phạm;
    nhãn ``technical-...`` và định danh như ``blocked_technical`` (``_`` là ký tự từ, không có ranh giới) thì không —
    tên cổng đó do spec video §4 đặt, không phải đường dẫn máy."""
    return _TECHNICAL_FOLDER.search(text.replace("technical-", "")) is not None


def test_engine_source_hardcodes_no_comfy_port_or_machine_path() -> None:
    for source in (SKILL / "engine").rglob("*.py"):
        text = source.read_text("utf-8")
        assert "8188" not in text and "D:\\" not in text and not names_the_technical_folder(text), source


@pytest.mark.parametrize("snippet,flagged", [
    ('Path("technical") / ".comfyui.lock"', True),
    ("x/04-milk-and-mom/technical/.lock", True),
    ("a\\technical\\b", True),
    ("technical", True),
    ("GATE_TECH = 'blocked_technical'", False),
    ("technical-stop", False),
    ("nontechnical", False),
])
def test_technical_folder_scan_flags_paths_not_the_gate_name(snippet: str, flagged: bool) -> None:
    """Bộ quét phải còn đỏ được trên đường dẫn thật và xanh trên tên cổng của spec."""
    assert names_the_technical_folder(snippet) is flagged
