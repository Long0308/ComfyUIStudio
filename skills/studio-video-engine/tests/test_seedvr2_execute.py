"""M4: SeedVR2 executor against a fake ComfyUI.  Ports the 16 v004 executor tests and adds the
helper-derived guarantees (dry run never POSTs; hash mismatch / busy queue / held lock refuse;
intent before POST; failure stops the run; resume skips and reconciles; short segments)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.core.io import canonical_sha256
from engine.comfy.settings import ComfySettings
from engine.seedvr2.execplan import select_tasks
from exec_fixtures import SHOT, make_rig, media_bytes
from fake_comfy import FakeComfy


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


# ---- dry run ---------------------------------------------------------------------------
def test_dry_run_never_posts_touches_no_network_and_writes_nothing(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    lines: list[str] = []
    before = tree(tmp_path)
    rows = rig.executor(emit=lines.append).dry_run(rig.tasks())
    assert fake.requests == [], "a dry run makes no HTTP request at all (queue/history/object_info)"
    assert tree(tmp_path) == before and not (tmp_path / "gpu.lock").exists()
    assert not (tmp_path / "comfy").exists(), "ComfyUI folders are not even created or inspected"
    text = "\n".join(lines)
    assert text.count("POST skipped (dry-run)") == len(rows) == 4
    for task in rig.plan.tasks:
        assert task.chunk["segment_sha256"] in text and task.chunk["api_graph_canonical_sha256"] in text


def test_dry_run_with_a_tampered_segment_refuses(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    (rig.plan.segments_root / SHOT / "chunks" / "chunk-0001" / "source-segment.mp4").write_bytes(b"tampered")
    with pytest.raises(Refused, match="hash mismatch"):
        rig.executor().dry_run(rig.tasks())
    assert fake.requests == []


def test_dry_run_applies_the_static_class_policy(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    graph_path = next((rig.plan.root / "workflows").rglob("chunk-0000-*.api.json"))
    graph = json.loads(graph_path.read_text())
    graph["99"] = {"class_type": "ClaudeNode", "inputs": {}}
    graph_path.write_text(json.dumps(graph))  # canonical sha no longer matches the plan: refused first
    with pytest.raises(Refused):
        rig.executor().dry_run(rig.tasks(only=f"{SHOT}:0"))


# ---- refusals before any POST ------------------------------------------------------------
def test_hash_mismatch_refuses_before_post_exit_one(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    (rig.plan.segments_root / SHOT / "chunks" / "chunk-0000" / "source-segment.mp4").write_bytes(b"tampered")
    result = rig.executor().run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 1 and fake.posts_made() == []
    job = rig.job(0)
    assert job["status"] == "FAILED" and "hash" in job["failure"]["message"].lower()
    assert not (rig.chunk_dir(0) / "dispatch-intent.json").exists()


def test_busy_queue_refuses_before_intent_or_post(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    fake.queue["queue_pending"] = [[1, "foreign", {}, {}, []]]
    result = rig.executor().run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 1 and fake.posts_made() == []
    assert "busy" in rig.job(0)["failure"]["message"]
    assert not (rig.chunk_dir(0) / "dispatch-intent.json").exists() and not (tmp_path / "gpu.lock").exists()


def test_held_lock_refuses_and_preserves_the_foreign_lock(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    (tmp_path / "gpu.lock").write_text("foreign-owner\n")
    result = rig.executor().run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 1 and fake.posts_made() == []
    assert (tmp_path / "gpu.lock").read_text() == "foreign-owner\n"
    assert "lock" in rig.job(0)["failure"]["message"].lower()


def test_staging_collision_refuses_and_leaves_the_foreign_input_untouched(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    task = rig.tasks()[0]
    foreign = rig.settings.input_dir / task.chunk["comfy_input_name"]
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"different-existing-file")
    result = rig.executor().run([task])
    assert result["exit_code"] == 1 and fake.posts_made() == []
    assert foreign.read_bytes() == b"different-existing-file"
    assert result["stopped"]["stage"] == "refused"


def test_partner_node_in_the_graph_refuses_before_staging(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    fake.object_info["SaveVideo"] = {"python_module": "comfy_api_nodes.x", "category": "api node"}
    result = rig.executor().run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 1 and "partner" in result["stopped"]["message"]
    assert fake.posts_made() == [] and not rig.settings.input_dir.exists()


# ---- successful run, receipts, trim math -------------------------------------------------
def test_full_run_completes_every_chunk_finalizes_the_shot_and_trims_from_the_recipe(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)  # 40 frames -> segment frames 17, 21, 18, 5
    seen: dict = {}

    def at_post(payload, prompt_id, _render=fake.on_post):
        if prompt_id == "pid-0001":
            intent = json.loads((rig.chunk_dir(0) / "dispatch-intent.json").read_text())
            seen.update(intent=intent, lock=(tmp_path / "gpu.lock").exists(),
                        job=rig.job(0)["status"], input_staged=any(rig.settings.input_dir.iterdir()))
        return _render(payload, prompt_id)

    fake.on_post = at_post
    result = rig.executor().run(rig.tasks())
    assert result["exit_code"] == 0 and result["stopped"] is None and len(fake.posts_made()) == 4
    assert seen["intent"]["client_id"] == fake.posts[0]["client_id"] and seen["lock"]
    assert seen["job"] == "PREPARED" and seen["input_staged"], "intent, lock and staged input precede the POST"
    assert [j["status"] for j in map(rig.job, range(4))] == ["COMPLETED"] * 4
    g = rig.plan.geometry
    assert rig.ffmpeg.trims()[:2] == [
        f"trim=start_frame=0:end_frame=13,setpts=PTS-STARTPTS,crop={g.final_width}:{g.final_height}:24:0",
        f"trim=start_frame=4:end_frame=17,setpts=PTS-STARTPTS,crop={g.final_width}:{g.final_height}:24:0"]
    job = rig.job(3)
    assert job["raw_output_frames_expected"] == job["output_frame_count"] == 5 and job["core_frame_count"] == 1
    assert job["core_provenance"]["trim_offset"] == 4 and job["core_provenance"]["crop"] == g.crop_filter
    assert job["core_provenance"]["encoding"] == "libx264-crf0-yuv420p"
    shot = json.loads((rig.plan.root / "runs" / SHOT / "shot.json").read_text())
    assert result["shots"][0]["frame_count"] == shot["frame_count"] == 40 and shot["status"] == "COMPLETED"
    assert json.loads((rig.plan.root / "runs" / "run-state.json").read_text())["status"] == "COMPLETED_SELECTION"
    assert not (tmp_path / "gpu.lock").exists()


@pytest.mark.parametrize("frames,last_segment,padded", [(40, 5, 5), (42, 7, 9), (50, 15, 17)])
def test_short_segments_accept_raw_equal_to_segment_frames(fake, tmp_path, frames, last_segment, padded) -> None:
    rig = make_rig(tmp_path, fake, frames=frames)
    task = rig.tasks(only=f"{SHOT}:3")[0]
    assert task.chunk["segment_frames"] == last_segment and task.chunk["seedvr2_padded_frames"] == padded
    result = rig.executor().run([task])
    assert result["exit_code"] == 0
    job = rig.job(3)
    assert job["status"] == "COMPLETED" and job["output_frame_count"] == last_segment
    assert job["plan_padded_frames"] == padded


@pytest.mark.parametrize("frames,wrong", [(42, 9), (50, 17), (40, 5 + 1)])
def test_raw_frame_mismatch_fails_before_core_exit_four(fake, tmp_path, frames, wrong) -> None:
    rig = make_rig(tmp_path, fake, frames=frames)
    rig.raw_frames["chunk-0003"] = wrong  # Comfy returned the PADDED (or any other) count
    result = rig.executor().run(rig.tasks(only=f"{SHOT}:3"))
    assert result["exit_code"] == 4
    job = rig.job(3)
    assert job["status"] == "FAILED" and job["failure"]["stage"] == "output_validation"
    assert "frame count mismatch" in job["failure"]["message"]
    assert not (rig.chunk_dir(3) / "core").exists() and rig.ffmpeg.commands == []


def test_a_full_21_frame_segment_is_unchanged(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    assert rig.executor().run(rig.tasks(only=f"{SHOT}:1"))["exit_code"] == 0
    job = rig.job(1)
    assert job["raw_output_frames_expected"] == job["plan_padded_frames"] == job["output_frame_count"] == 21


def test_raw_output_of_the_wrong_size_fails(fake, tmp_path, monkeypatch) -> None:
    rig = make_rig(tmp_path, fake)
    real_render = fake.on_post

    def small(payload, prompt_id):
        outputs = real_render(payload, prompt_id)
        entry = outputs["15"]["images"][0]
        (rig.root / "comfy" / "output" / entry["subfolder"] / entry["filename"]).write_bytes(
            media_bytes(17, 864, 480, "not-upscaled"))
        return outputs

    fake.on_post = small
    result = rig.executor().run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 4 and "size mismatch" in rig.job(0)["failure"]["message"]


def test_history_for_a_different_graph_is_never_accepted(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake, auto_complete=False)
    real_render = fake.on_post

    def foreign_history(payload, prompt_id):
        graph = json.loads(json.dumps(payload["prompt"]))
        graph["10"]["inputs"]["denoise"] = 0.5
        fake.add_history(prompt_id, graph, payload["client_id"], real_render(payload, prompt_id))
        return None

    fake.on_post = foreign_history
    result = rig.executor().run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 2 and "different graph" in rig.job(0)["failure"]["message"]


def test_a_wait_timeout_is_exit_three_and_keeps_the_intent(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake, auto_complete=False, history_timeout=0.2)
    result = rig.executor().run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 3 and len(fake.posts_made()) == 1
    assert (rig.chunk_dir(0) / "dispatch-intent.json").exists()
    assert rig.job(0)["failure"]["automatic_resubmit"] is False


# ---- failure stops the run; post problems are exit 2 -------------------------------------
@pytest.mark.parametrize("mode", ["drop", "status:400"])
def test_post_failure_stops_the_whole_run_with_exit_two_never_one(fake, tmp_path, mode) -> None:
    rig = make_rig(tmp_path, fake)
    fake.post_mode = mode
    result = rig.executor().run(rig.tasks(max_chunks=2))
    assert result["exit_code"] == 2 and len(fake.posts_made()) == 1
    assert not (rig.chunk_dir(1) / "job.json").exists()
    first = rig.job(0)
    assert first["status"] == "FAILED" and first["failure"]["stage"] == "post_outcome_unknown"
    assert first["failure"]["uncertain"] is True and first["failure"]["intent_exists"] is True
    assert json.loads((rig.plan.root / "runs" / "run-state.json").read_text())["status"] == "STOPPED"


def test_a_refusal_after_the_post_is_reported_as_two_never_one(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    executor = rig.executor()

    def late_guard(*args, **kwargs):
        raise Refused("late guard after the POST")

    executor.materialize = late_guard  # type: ignore[method-assign]
    result = executor.run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 2 and len(fake.posts_made()) == 1
    assert rig.job(0)["failure"]["posted"] is True
