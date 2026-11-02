"""voice synth / reconcile / adopt against the fake VoiceStudio (ports of the first batch tool's tests)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from config_fixtures import make_world
from fake_voicestudio import FakeVoiceStudio
from wav_fixtures import tone_wav_bytes

from engine.config.loader import resolve_episode
from engine.core.errors import Failed, Refused, Uncertain, exit_code_for
from engine.core.io import read_json
from engine.voice import receipts, reconcile, synth
from engine.voice.client import VoiceStudioClient
from engine.voice.plan import build_plan
from engine.voice.recipe import voice_settings
from test_voice_plan import cast_doc, dialogue_doc

IDLE = {"queue_running": [], "queue_pending": []}
BUSY = {"queue_running": [], "queue_pending": [[1, "p", {}, {}, []]]}


@pytest.fixture
def fake():
    with FakeVoiceStudio() as server:
        yield server


@pytest.fixture
def context(tmp_path: Path, fake: FakeVoiceStudio) -> synth.SynthContext:
    world = make_world(tmp_path)
    config = resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    eid = config.episode["episode_id"]
    d, c = tmp_path / "dialogue.json", tmp_path / "cast.json"
    d.write_text(json.dumps(dialogue_doc(eid)), encoding="utf-8")
    c.write_text(json.dumps(cast_doc(eid)), encoding="utf-8")
    settings = voice_settings(config, voicestudio_url=fake.url, skill_root=world.skill_root)
    settings = dataclasses.replace(settings, gpu_lock_path=tmp_path / "gpu.lock", comfy_url="http://unused",
                                   lock_timeout_seconds=0.2, http_timeout_seconds=5.0)
    out = tmp_path / "voice-v001"
    plan = build_plan(config, settings, dialogue_path=d, cast_path=c, out=out)
    out.mkdir()
    (out / receipts.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
    return synth.SynthContext(settings=settings, out=out, plan=plan,
                              voice=VoiceStudioClient(fake.url, timeout_seconds=5.0, read_timeout_seconds=5.0),
                              queue_reader=lambda: IDLE, episode_root=Path(config.episode_root))


def job(context: synth.SynthContext, index: int = 0) -> dict:
    return context.plan["jobs"][index]


def test_dry_run_sends_nothing(context, fake) -> None:
    rows = synth.dry_run_rows(context.out, context.plan)
    assert [r["state"] for r in rows] == ["READY"] * 3 and fake.requests == []


def test_execute_binds_a_take_and_releases_the_lock(context, fake) -> None:
    result = synth.synth_job(context, job(context))
    assert result["status"] == "COMPLETED" and fake.posts_made() == 1
    folder = receipts.job_dir(context.out, "dialogue:S01_A")
    take = read_json(folder / receipts.TAKE)
    assert (folder / receipts.INTENT).is_file() and take["provenance"] == "generate"
    native = context.out / take["native"]["path"]
    assert native.is_file() and take["native"]["metrics"]["sample_rate"] == 24_000
    assert not context.settings.gpu_lock_path.exists()
    assert fake.posts[0]["text"] == "Look at the moon!" and fake.posts[0]["profile_id"] == "aaaa1111"
    assert synth.synth_job(context, job(context))["status"] == "REUSED" and fake.posts_made() == 1


def test_wav_body_answer_needs_no_download(context, fake) -> None:
    fake.post_mode = "wav"
    assert synth.synth_job(context, job(context))["status"] == "COMPLETED"
    assert not any(path.startswith("/audio/") for _, path in fake.requests)


def test_lost_answer_is_uncertain_and_never_reposted_then_reconciled(context, fake) -> None:
    fake.post_mode = "drop"
    with pytest.raises(Uncertain, match="never auto-resubmitted"):
        synth.synth_job(context, job(context))
    folder = receipts.job_dir(context.out, "dialogue:S01_A")
    assert (folder / receipts.UNKNOWN).is_file() and not (folder / receipts.TAKE).is_file()
    assert receipts.job_state(context.out, "dialogue:S01_A") == "UNCERTAIN"
    with pytest.raises(Uncertain, match="reconcile"):
        synth.synth_job(context, job(context))
    assert fake.posts_made() == 1
    fake.post_mode = "normal"
    result = reconcile.reconcile_job(context, job(context))
    assert result["status"] == "RECONCILED" and fake.posts_made() == 1
    assert read_json(folder / receipts.TAKE)["provenance"] == "reconciled"
    assert synth.synth_job(context, job(context))["status"] == "REUSED"


def test_reconcile_with_no_match_or_several_matches_is_uncertain(context, fake) -> None:
    fake.post_mode = "drop"
    with pytest.raises(Uncertain):
        synth.synth_job(context, job(context))
    saved = list(fake.history)
    fake.history.clear()
    with pytest.raises(Uncertain, match="no new history entry"):
        reconcile.reconcile_job(context, job(context))
    fake.history.extend(saved)
    fake.add_take(fake.posts[0])  # a second identical take appeared server-side
    with pytest.raises(Uncertain, match="ambiguous"):
        reconcile.reconcile_job(context, job(context))
    assert fake.posts_made() == 1


def test_reconcile_rejects_entries_older_than_the_intent_or_with_another_engine(context, fake) -> None:
    fake.post_mode = "drop"
    with pytest.raises(Uncertain):
        synth.synth_job(context, job(context))
    entry = fake.history[-1]
    entry["created_unix"] = 1.0  # same text/profile/language, but created long before this intent
    with pytest.raises(Uncertain, match="no new history entry"):
        reconcile.reconcile_job(context, job(context))
    del entry["created_unix"]
    entry["engine"] = "other-engine"  # an echoed request field that disagrees
    with pytest.raises(Uncertain, match="no new history entry"):
        reconcile.reconcile_job(context, job(context))
    entry["engine"] = job(context)["request"]["engine"]
    assert reconcile.reconcile_job(context, job(context))["status"] == "RECONCILED" and fake.posts_made() == 1


def test_run_synth_carries_partial_results_on_the_error(context, fake) -> None:
    synth.synth_job(context, job(context, 0))
    fake.post_mode = "drop"
    with pytest.raises(Uncertain) as caught:
        synth.run_synth(context)
    assert [r["status"] for r in caught.value.evidence["results"]] == ["REUSED"]
    assert caught.value.evidence["stopped_at"] == "dialogue:S01_B"


def test_duplicate_mode_is_ambiguous_on_reconcile(context, fake) -> None:
    fake.post_mode = "duplicate"
    with pytest.raises(Uncertain):
        synth.synth_job(context, job(context))
    with pytest.raises(Uncertain, match="ambiguous"):
        reconcile.reconcile_job(context, job(context))


@pytest.mark.parametrize("mode", ["status:500", "truncated", "no_id"])
def test_unknown_outcomes_after_the_post_are_exit_2(context, fake, mode) -> None:
    fake.post_mode = mode
    with pytest.raises(Uncertain) as caught:
        synth.synth_job(context, job(context))
    assert exit_code_for(caught.value, posted=True) == 2
    assert (receipts.job_dir(context.out, "dialogue:S01_A") / receipts.UNKNOWN).is_file()


def test_client_error_is_failed_exit_4_not_1(context, fake) -> None:
    fake.post_mode = "status:400"
    with pytest.raises(Failed) as caught:
        synth.synth_job(context, job(context))
    assert exit_code_for(caught.value, posted=True) == 4
    assert (receipts.job_dir(context.out, "dialogue:S01_A") / receipts.REJECTED).is_file()
    with pytest.raises(Failed, match="rejected this request earlier"):
        synth.synth_job(context, job(context))
    assert fake.posts_made() == 1


def test_busy_queue_blocks_before_any_intent(context, fake) -> None:
    busy = dataclasses.replace(context, queue_reader=lambda: BUSY)
    with pytest.raises(Refused, match="E_QUEUE_BUSY"):
        synth.synth_job(busy, job(context))
    assert not receipts.job_dir(context.out, "dialogue:S01_A").exists() and fake.requests == []
    assert not context.settings.gpu_lock_path.exists()


def test_held_gpu_lock_refuses_and_is_preserved(context, fake) -> None:
    lock = context.settings.gpu_lock_path
    lock.write_text("pid=1 acquired_unix=0 token=deadbeef\n")
    with pytest.raises(Refused, match="E_GPU_LOCK"):
        synth.synth_job(context, job(context))
    assert lock.read_text() == "pid=1 acquired_unix=0 token=deadbeef\n" and fake.requests == []


def test_unhealthy_voicestudio_refuses_before_the_intent(context, fake) -> None:
    fake.history_mode = "status:500"
    with pytest.raises(Refused, match="E_VOICESTUDIO_UNHEALTHY"):
        synth.synth_job(context, job(context))
    assert not (receipts.job_dir(context.out, "dialogue:S01_A") / receipts.INTENT).exists()
    assert fake.posts_made() == 0


def test_execute_preconditions(context) -> None:
    draft = dict(context.plan, script_status="DRAFT")
    with pytest.raises(Refused, match="LOCKED"):
        synth.require_execute_preconditions(context.settings, draft)
    with pytest.raises(Refused, match="E_GPU_LOCK"):
        synth.require_execute_preconditions(dataclasses.replace(context.settings, gpu_lock_path=None), context.plan)
    with pytest.raises(Refused, match="VoiceStudio URL"):
        synth.require_execute_preconditions(dataclasses.replace(context.settings, voicestudio_url=None), context.plan)


def test_run_synth_is_serial_and_stops_at_the_first_unknown(context, fake) -> None:
    fake.post_mode = "drop"
    with pytest.raises(Uncertain):
        synth.run_synth(context)
    assert fake.posts_made() == 1
    assert receipts.job_state(context.out, "dialogue:S01_B") == "READY"


def test_tampered_native_wav_blocks_reuse_and_finalize(context, fake) -> None:
    synth.synth_job(context, job(context))
    take = read_json(receipts.job_dir(context.out, "dialogue:S01_A") / receipts.TAKE)
    (context.out / take["native"]["path"]).write_bytes(tone_wav_bytes(seconds=0.1))
    with pytest.raises(Refused, match="hash differs"):
        synth.synth_job(context, job(context))
    assert fake.posts_made() == 1


def test_adopt_binds_existing_wavs_without_http(context, fake, tmp_path) -> None:
    source = tmp_path / "old-native.wav"
    source.write_bytes(tone_wav_bytes(seconds=0.4, rate=24_000, channels=1))
    rows = [{"request_id": "dialogue:S01_A", "path": str(source), "audio_id": "c0ffee01"}]
    result = reconcile.adopt_takes(context, rows)
    assert result["adopted"] == 1 and fake.requests == []
    take = read_json(receipts.job_dir(context.out, "dialogue:S01_A") / receipts.TAKE)
    assert take["provenance"] == "adopted" and take["audio_id"] == "c0ffee01"
    assert reconcile.adopt_takes(context, rows)["results"][0]["status"] == "ALREADY_BOUND"
    with pytest.raises(Uncertain, match="not a planned request id"):
        reconcile.adopt_takes(context, [{"request_id": "dialogue:S99_Z", "path": str(source)}])
    assert synth.synth_job(context, job(context))["status"] == "REUSED" and fake.posts_made() == 0
