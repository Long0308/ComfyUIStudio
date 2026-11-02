"""``musicpick_gen.execute`` / ``finalize_generation`` against a fake ComfyUI: one guarded POST, a re-run never re-POSTs (no GPU)."""

from __future__ import annotations

import dataclasses

from audio_fixtures import RATE, Rig, audio_world, recipe_of, song_wav
from fake_comfy import FakeComfy
from test_audio_library_support import BRIEF, gate, separator
from test_audio_music import TIMELINE

from engine.audio import jobs, music, musicpick, musicpick_gen
from engine.core.io import write_json_once
from engine.seedvr2.seam_media import find_ffmpeg


def test_execute_posts_once_through_the_guarded_path_and_finalize_gates_the_bed(tmp_path, monkeypatch) -> None:
    config, skill = audio_world(tmp_path)
    base = recipe_of(skill, "audio/music-yue2-int8-v001", "audio-music")
    pick = musicpick.load_pick_recipe(config)
    out = tmp_path / "music-ace"
    plan, recipe = musicpick_gen.build_generation_plan(config, pick, base, "acestep", out=out, timeline=TIMELINE, brief=BRIEF,
                                                       brief_sources={}, evidence=None, takes=1, seed=None, write=True)
    write_json_once(out / music.PLAN_FILE, plan, mode="ascii")
    with FakeComfy() as fake:
        rig = Rig(tmp_path, fake, recipe, skill)

        def render(payload: dict, prompt_id: str) -> dict:
            prefix = payload["prompt"]["10"]["inputs"]["filename_prefix"]
            subfolder, name = prefix.rsplit("/", 1)
            target = rig.settings.output_dir / subfolder / f"{name}_00001_.flac"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(song_wav(83.0, bpm=BRIEF["bpm"]))
            return {"10": {"audio": [{"filename": target.name, "subfolder": subfolder, "type": "output"}]}}
        fake.on_post, fake.auto_complete = render, True
        monkeypatch.setattr(musicpick_gen, "settings_from_machine", lambda machine: rig.settings)
        # the pinned multi-GB model files are replaced by tiny files with matching pins (as the other audio tests do)
        patched_recipe = dataclasses.replace(recipe, data=rig.data)
        machine = {**config.machine, "comfy": {**config.machine["comfy"], "root": str(rig.root)}}
        live = dataclasses.replace(config, machine=machine)
        first = musicpick_gen.execute(live, out, plan, patched_recipe, timeout_seconds=5.0)
        again = musicpick_gen.execute(live, out, plan, patched_recipe, timeout_seconds=5.0)
        assert first["completed"] == 1 and again["reused"] == 1 and len(fake.posts_made()) == 1
        assert jobs.job_state(out, plan["jobs"][0]) == "COMPLETED" and not rig.settings.lock_path.exists()
        receipt = musicpick_gen.finalize_generation(live, out, plan, recipe, ffmpeg=find_ffmpeg(), gate=gate(),
                                                    vocal_runner=separator(lambda source: 0.0005), with_gui=False)
    assert receipt["status"] == "CANDIDATE_PENDING_LISTENING" and receipt["stem"]["vocal_gate"]["status"] == "PASS"
    assert receipt["stem"]["vocal_gate"]["rule"] == "v2" and receipt["takes"][0]["bed"]["duration_s"] >= 83.0
    assert receipt["recipe"]["id"] == "audio/music-pick-v001#acestep" and receipt["models"][0]["licence_id"] == "ace-step-1.5-apache-2.0"
    assert RATE == 48000
