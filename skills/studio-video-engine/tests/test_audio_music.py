"""Music: loop-extend, guarded execution against a fake ComfyUI (never re-POST), finalize (T-E43)."""

from __future__ import annotations

import numpy as np
import pytest
from audio_fixtures import RATE, Rig, audio_world, recipe_of, song_wav
from fake_comfy import FakeComfy

from engine.audio import dsp, jobs, loopext, music
from engine.comfy.dispatch import INTENT_FILE
from engine.core.errors import Failed, Refused, Uncertain
from engine.core.io import read_json, write_json_once
from engine.seedvr2.seam_media import find_ffmpeg
from engine.voice.wavio import read_wav

TIMELINE = {"fps": 30, "total_frames": 2400, "duration_s": 80.0, "sample_rate": RATE, "total_samples": 2400 * 1600,
            "source": "test"}
BRIEF = {"bpm": 96, "key": "G major", "instruments": "soft felt piano"}


def synthetic_song(seconds: float, bpm: float = 96.0) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    bar = 4 * 60.0 / bpm
    env = (0.15 + 0.25 * np.sin(np.pi * (t % bar) / bar) ** 2) * np.clip((seconds - t) / 2.0, 0.0, 1.0)
    return np.repeat((env * np.sin(2 * np.pi * 262.0 * t))[:, None], 2, axis=1).astype(np.float32)


def test_loop_extend_keeps_the_natural_ending_and_reaches_the_target() -> None:
    song = synthetic_song(40.0)
    bed, meta = loopext.extend(song, 96.0, 83.0, RATE, crossfade_s=0.25)
    assert meta["loop"] and bed.shape[0] / RATE >= 83.0 and meta["envelope_match_score"] > 0.9
    assert [j["kind"] for j in meta["joins"]][-1] == "tail [a,end)"
    assert np.array_equal(bed[-1000:], song[-1000:])  # the song's own ending is the bed's ending
    loop_point = meta["loop_point_s"]
    assert 20.0 <= loop_point < 40.0 and (meta["ref_start_s"] == 5.0)  # intro_bars 2 at 96 BPM = 5 s


def test_a_long_enough_song_is_not_looped_and_a_too_short_one_is_refused() -> None:
    song = synthetic_song(40.0)
    bed, meta = loopext.extend(song, 96.0, 30.0, RATE)
    assert not meta["loop"] and bed.shape[0] == song.shape[0]
    with pytest.raises(Refused, match="shorter than intro"):
        loopext.extend(synthetic_song(6.0), 96.0, 30.0, RATE)


def test_loop_to_length_and_the_duck_envelope_follow_the_first_episode_builder() -> None:
    source = synthetic_song(6.0)
    out = dsp.loop_to_length(source, 10 * RATE, 1.0, RATE)
    assert out.shape[0] == 10 * RATE and np.array_equal(out[:5 * RATE], source[:5 * RATE])
    windows = [{"id": "a", "start_sample": 3 * RATE, "end_sample": 4 * RATE}, {"id": "b", "start_sample": 6 * RATE, "end_sample": 7 * RATE}]
    env, rows = dsp.duck_envelope(windows, 10 * RATE, depth_db=-14.0, attack_s=0.14, release_s=0.28, rate=RATE)
    assert env.dtype == np.float32 and env[0, 0] == 1.0 and env[int(3.5 * RATE), 0] == pytest.approx(dsp.db_to_gain(-14.0))
    assert [r["id"] for r in rows] == ["a", "b"] and env[int(5 * RATE), 0] == 1.0


@pytest.fixture
def world(tmp_path):
    config, skill = audio_world(tmp_path)
    return config, skill, recipe_of(skill, "audio/music-yue2-int8-v001", "audio-music")


def planned(world, tmp_path, takes: int = 1):
    config, _, recipe = world
    out = tmp_path / "music-v001"
    plan = music.build_plan(config, recipe, "cli", out=out, timeline=TIMELINE, brief=BRIEF, brief_sources={}, evidence=None,
                            takes=takes, seed=None, write=True)
    write_json_once(out / music.PLAN_FILE, plan, mode="ascii")
    return out, plan


def test_submit_posts_once_waits_and_a_rerun_never_posts_again(world, tmp_path) -> None:
    _, skill, recipe = world
    out, plan = planned(world, tmp_path)
    with FakeComfy() as fake:
        rig = Rig(tmp_path, fake, recipe, skill)
        rig.serve(lambda prompt: song_wav(40.0))
        first = jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        assert first["completed"] == 1 and len(fake.posts_made()) == 1
        assert fake.posts[0]["prompt"]["3"]["class_type"] == "YuE2GenerateMusic"
        assert jobs.run_all(rig.context(out), plan, rig.data, rig.root)["reused"] == 1
        assert len(fake.posts_made()) == 1 and not rig.settings.lock_path.exists()
        receipt = music.finalize(out, music.load_plan(out), recipe, output_root=rig.settings.output_dir,
                                 ffmpeg=find_ffmpeg(), rate=RATE)
    take = receipt["takes"][0]
    assert take["loop_extend"]["loop"] and take["bed"]["long_enough"] and take["bed"]["duration_s"] >= 83.0
    assert receipt["stem"]["path"] == take["bed"]["path"] and receipt["stem"]["take"] == "music-c01-t01"
    assert read_wav(out / take["bed"]["path"]).frames == int(round(take["bed"]["duration_s"] * RATE))
    assert receipt["models"][0]["sha256"] == recipe.data["models"][0]["sha256"] and "yue2-cc-by-nc-4.0-creator" in receipt["licences"]
    assert "CC BY-NC" in receipt["licences"]["yue2-cc-by-nc-4.0-creator"]["name"] and receipt["prompt"]["lyrics"].startswith("[Intro]")


def test_dry_run_sends_nothing_and_a_busy_queue_or_executor_lock_refuses_before_any_post(world, tmp_path) -> None:
    _, skill, recipe = world
    out, plan = planned(world, tmp_path)
    with FakeComfy() as fake:
        rig = Rig(tmp_path, fake, recipe, skill)
        assert jobs.dry_rows(out, plan, rig.policy)[0]["state"] == "READY" and fake.requests == []
        fake.queue["queue_pending"] = [[1, "p", {}, {"client_id": "x"}, []]]
        with pytest.raises(Refused, match="queue is busy"):
            jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        fake.queue["queue_pending"] = []
        rig.settings.executor_lock_path.write_text("{}", encoding="utf-8")
        with pytest.raises(Refused, match="executor lock"):
            jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        assert fake.posts_made() == []


def test_a_model_that_differs_from_its_pin_is_refused_before_the_post(world, tmp_path) -> None:
    _, skill, recipe = world
    out, plan = planned(world, tmp_path)
    with FakeComfy() as fake:
        rig = Rig(tmp_path, fake, recipe, skill)
        model = rig.root / rig.data["models"][0]["path"]
        model.write_bytes(model.read_bytes() + b"x")
        with pytest.raises(Refused, match="bytes on disk"):
            jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        assert fake.posts_made() == []


def test_an_unknown_post_outcome_is_never_resubmitted(world, tmp_path) -> None:
    _, skill, recipe = world
    out, plan = planned(world, tmp_path)
    with FakeComfy() as fake:
        rig = Rig(tmp_path, fake, recipe, skill)
        fake.post_mode = "drop"
        with pytest.raises(Uncertain):
            jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        assert (out / "jobs" / "music-c01-t01" / INTENT_FILE).is_file() and len(fake.posts_made()) == 1
        fake.post_mode = "normal"
        with pytest.raises(Uncertain, match="never resubmitted"):  # intent without a trace in history/queue
            jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        assert len(fake.posts_made()) == 1


def test_a_changed_saved_graph_is_refused_and_a_failed_job_stays_failed(world, tmp_path) -> None:
    _, skill, recipe = world
    out, plan = planned(world, tmp_path)
    graph_file = out / plan["jobs"][0]["graph_file"]
    original = graph_file.read_bytes()
    graph_file.write_bytes(original.replace(b'"steps": 32', b'"steps": 31'))
    with FakeComfy() as fake:
        rig = Rig(tmp_path, fake, recipe, skill)
        with pytest.raises(Refused, match="no longer matches the plan"):
            jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        graph_file.write_bytes(original)
        rig.serve(lambda prompt: song_wav(5.0))
        fake.complete_status = {"status_str": "error", "completed": False}
        with pytest.raises(Failed):
            jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        with pytest.raises(Failed, match="plan a new version folder"):
            jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        assert len(fake.posts_made()) == 1


def test_takes_get_consecutive_seeds_and_the_pick_chooses_the_stem(world, tmp_path) -> None:
    _, skill, recipe = world
    out, plan = planned(world, tmp_path, takes=2)
    assert [j["seed"] for j in plan["jobs"]] == [recipe.data["seed_base"], recipe.data["seed_base"] + 1]
    with FakeComfy() as fake:
        rig = Rig(tmp_path, fake, recipe, skill)
        rig.serve(lambda prompt: song_wav(40.0))
        jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        receipt = music.finalize(out, plan, recipe, output_root=rig.settings.output_dir, ffmpeg=find_ffmpeg(), rate=RATE,
                                 pick="music-c01-t02")
    assert receipt["stem"]["take"] == "music-c01-t02" and len(receipt["takes"]) == 2
    with pytest.raises(Refused, match="not one of"):
        music.finalize(out, plan, recipe, output_root=rig.settings.output_dir, ffmpeg=find_ffmpeg(), rate=RATE, pick="music-c01-t09")
    assert read_json(out / music.FINALIZE_FILE)["stem"]["picked_by"] == "--pick"
