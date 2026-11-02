"""Extra line kinds (end line, brand voice) as first-class jobs, and the optional quiet-burst onset rule."""

from __future__ import annotations

import dataclasses
import io
import json
import wave
from pathlib import Path

import pytest
from config_fixtures import make_world
from test_voice_plan import cast_doc, dialogue_doc
from test_voice_trim import params, wav_data
from wav_fixtures import silence, tone

from engine.config.loader import resolve_episode
from engine.core.errors import Refused
from engine.voice import handoff
from engine.voice.plan import build_jobs, build_plan
from engine.voice.recipe import load_voice_recipe, voice_settings
from engine.voice.trim import trim_bounds

END = {"kind": "end_line", "id": "host", "speaker": "host", "text_tts": "See you again!", "target_duration_s": 1.8}
BRAND = {"kind": "brand_voice", "id": "channel", "speaker": "kid", "text_tts": "Jennie Joy Kids", "target_duration_s": 1.5}


def test_extras_are_jobs_with_their_own_request_ids_and_classes(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    config = resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    eid = config.episode["episode_id"]
    recipe = load_voice_recipe("voice/omnivoice-en-broadcast-v001", skill_root=world.skill_root)
    jobs = build_jobs(dialogue_doc(eid, extras=[END, BRAND]), cast_doc(eid), recipe.data)
    assert [j["request_id"] for j in jobs[-2:]] == ["end_line:host", "brand_voice:channel"]
    assert [j["category"] for j in jobs[-2:]] == ["end_line", "brand_voice"]
    assert jobs[-2]["request"] == {"text": "See you again!", "profile_id": "aaaa1111", "language": "English",
                                   "engine": "omnivoice", "duration": "1.8", "effect_preset": "broadcast", "wav_bits": "16"}
    assert jobs[-1]["profile_id"] == "bbbb2222" and jobs[-1]["transform"] == {"pitch_semitones": -1.0}
    assert handoff.binding_name(jobs[-2]) == "host" and handoff.binding_name(jobs[0]) == "dlg S01_A"
    assert handoff.binding_name(jobs[2]) == "voc Moon"


@pytest.mark.parametrize("change, code", [
    ({"text_tts": "Host: See you again!"}, "E_SPEAKER_PREFIX"),
    ({"speaker": "pet"}, "E_APPROVED_CAST.*silent"),
    ({"speaker": "ghost"}, "E_APPROVED_CAST.*not in the cast"),
])
def test_extras_obey_the_same_gates_as_dialogue(tmp_path: Path, change: dict, code: str) -> None:
    world = make_world(tmp_path)
    config = resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    eid = config.episode["episode_id"]
    recipe = load_voice_recipe("voice/omnivoice-en-broadcast-v001", skill_root=world.skill_root)
    with pytest.raises(Refused, match=code):
        build_jobs(dialogue_doc(eid, extras=[{**END, **change}]), cast_doc(eid), recipe.data)


def test_bad_kind_duplicate_id_and_bad_id_are_refused(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    config = resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    eid = config.episode["episode_id"]
    settings = voice_settings(config, skill_root=world.skill_root)
    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps(cast_doc(eid)), encoding="utf-8")

    def plan(extras: list[dict]) -> dict:
        d = tmp_path / "d.json"
        d.write_text(json.dumps(dialogue_doc(eid, extras=extras)), encoding="utf-8")
        return build_plan(config, settings, dialogue_path=d, cast_path=cast, out=None)

    assert plan([END, BRAND])["job_count"] == 5
    with pytest.raises(Refused, match="kind"):
        plan([{**END, "kind": "jingle"}])
    with pytest.raises(Refused, match="duplicate voice request ids"):
        plan([END, END])
    with pytest.raises(Refused, match="id"):
        plan([{**END, "id": "Host Line"}])


def burst_then_speech(burst_amplitude: float, gap: float) -> list[list[int]]:
    return [silence(0.1, 48_000), tone(0.06, 48_000, amplitude=burst_amplitude), silence(gap, 48_000),
            tone(1.0, 48_000, amplitude=0.25), silence(0.3, 48_000)]


def test_quiet_burst_rule_is_off_by_default_and_changes_nothing_for_existing_recipes() -> None:
    p = params()
    assert p.quiet_burst_db is None and "quiet_burst_db" not in p.as_dict()  # existing receipts stay comparable
    data = wav_data(burst_then_speech(0.02, 0.12), channels=2)
    assert trim_bounds(data, p).voiced_start_sample == round(0.1 * 48_000)  # the cluster-burst latches (the bug)


def test_quiet_burst_inside_a_cluster_is_skipped_only_when_far_below_the_loudest_run() -> None:
    on = dataclasses.replace(params(), quiet_burst_db=15.0)
    assert on.as_dict()["quiet_burst_db"] == 15.0
    quiet = trim_bounds(wav_data(burst_then_speech(0.02, 0.12)), on)
    assert quiet.voiced_start_sample == round(0.28 * 48_000)
    assert quiet.onset["skipped_bursts"][0]["reason"] == "quiet_vs_loudest_run" and quiet.onset["differs_from_naive"]
    loud = trim_bounds(wav_data(burst_then_speech(0.2, 0.12)), on)  # only ~2 dB under the speech: real onset, kept
    assert loud.voiced_start_sample == round(0.1 * 48_000) and loud.onset["skipped_bursts"] == []
    plain = trim_bounds(wav_data([silence(0.1, 48_000), tone(1.0, 48_000, amplitude=0.25), silence(0.3, 48_000)]), on)
    assert plain.voiced_start_sample == round(0.1 * 48_000)  # a single run is never skipped


def test_recipe_schema_accepts_the_optional_key_and_bounds_it(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    path = world.skill_root / "recipes" / "voice" / "omnivoice-en-broadcast-v001.json"
    base = json.loads(path.read_text(encoding="utf-8"))
    base["trim"]["onset"]["quiet_burst_db"] = 15.0
    base["allowed_effect_presets"] = ["cosy"]
    path.write_text(json.dumps(base), encoding="utf-8")
    assert load_voice_recipe("voice/omnivoice-en-broadcast-v001", skill_root=world.skill_root).data["allowed_effect_presets"] == ["cosy"]
    base["trim"]["onset"]["quiet_burst_db"] = 1.0
    path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(Refused, match="quiet_burst_db"):
        load_voice_recipe("voice/omnivoice-en-broadcast-v001", skill_root=world.skill_root)
