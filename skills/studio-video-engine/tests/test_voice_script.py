"""voice from the locked script: plan --script, per-line metadata, voice-bindings.json, and a fake end-to-end run.

Chain under test: script (EN text + VI subtitle + frames) -> plan -> synth (fake VoiceStudio) -> approve -> finalize
-> voice-bindings.json, then read back by the REAL readers of the next stages (timing parse_lines, qa
resolve_bindings, audio load_placed / load_extra / load_brand_voice).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest
from config_fixtures import make_world
from fake_voicestudio import FakeVoiceStudio
from test_voice_finalize import FFMPEG, make
from test_voice_plan import cast_doc

from engine.audio import windows
from engine.config import loader
from engine.config.loader import resolve_episode
from engine.core.errors import Refused
from engine.core.io import read_json, sha256_file
from engine.qa.bindings import resolve_bindings
from engine.timing.dialogue import parse_lines, parse_vocabulary
from engine.voice import finalize, receipts, synth
from engine.voice.client import VoiceStudioClient
from engine.voice.plan import build_plan
from engine.voice.recipe import voice_settings
from engine.voice.script_ingest import dialogue_from_script

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "bin"))
import jjv  # noqa: E402

IDLE = {"queue_running": [], "queue_pending": []}
TIMELINE = {"sample_rate": 48_000, "fps": 30}
EXTRAS = [{"kind": "end_line", "id": "host", "speaker": "host", "text_tts": "See you again!", "target_duration_s": 1.8,
           "subtitle": {"vi": "Hẹn gặp lại nhé!"}, "start_frame": 600},
          {"kind": "brand_voice", "id": "channel", "speaker": "host", "text_tts": "Jennie Joy Kids", "target_duration_s": 1.5}]


def script_doc(status: str = "LOCKED_BY_USER", **extra: object) -> dict:
    doc = {"film_id": "ignored", "status": status, "fps": 30, "language": {"spoken": "en", "subtitle": "vi"},
           "shots": [
               {"id": "S01_A", "speaker": "host", "speech_text": "Look at the  moon!", "duration_s": 4.5,
                "dialogue_vi": "Nhìn mặt trăng!", "start_frame": 90, "duration_frames": 135,
                "target_keywords": ["moon"], "voice": {"emotion": "warm"}},
               {"id": "S01_B", "speaker": "kid", "speech_text": "It is round.", "duration_s": 3.0,
                "dialogue_vi": "Nó tròn.", "start_frame": 225, "duration_frames": 90},
               {"id": "S01_C", "speaker": "pet", "speech_text": "", "duration_s": 2.0}],
           "vocabulary_cards": [{"term": "Moon", "icon": "moon", "proposed_outro_duration_s": 0.9, "vi": "Mặt trăng",
                                 "start_frame": 400}],
           "voice_extras": EXTRAS}
    doc.update(extra)
    return doc


@pytest.fixture
def world_config(tmp_path: Path, monkeypatch):
    world = make_world(tmp_path)
    monkeypatch.setattr(loader, "DEFAULT_MACHINE_PATH", world.machine_path)
    config = resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    return world, config


def write(tmp_path: Path, name: str, value: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_script_becomes_one_job_per_spoken_line_with_metadata(world_config, tmp_path) -> None:
    world, config = world_config
    eid = config.episode["episode_id"]
    document = dialogue_from_script(script_doc(), episode_id=eid, vocabulary_speaker="kid")
    assert [r["shot"] for r in document["dialogue"]] == ["S01_A", "S01_B"]  # the silent shot has no job
    assert document["status"] == "LOCKED" and document["fps"] == 30 and document["language"] == "en"
    assert dialogue_from_script(script_doc("PENDING_PARENT_REVIEW"), episode_id=eid, vocabulary_speaker="kid")["status"] == "DRAFT"
    settings = voice_settings(config, skill_root=world.skill_root)
    plan = build_plan(config, settings, cast_path=write(tmp_path, "cast.json", cast_doc(eid)), out=tmp_path / "o",
                      derived={"document": document, "source": {"kind": "script", "path": "s.json", "sha256": "0" * 64}})
    ids = [j["request_id"] for j in plan["jobs"]]
    assert ids == ["dialogue:S01_A", "dialogue:S01_B", "vocabulary:Moon", "end_line:host", "brand_voice:channel"]
    first = plan["jobs"][0]
    assert first["text_tts"] == "Look at the moon!" and first["profile_id"] == "aaaa1111"
    assert first["meta"]["subtitle"] == {"vi": "Nhìn mặt trăng!"} and first["meta"]["emotion"] == "warm"
    assert first["meta"]["start_frame"] == 90 and first["meta"]["target_keywords"] == ["moon"]
    assert "emotion" not in first["request"] and plan["fps"] == 30
    assert plan["inputs"]["dialogue"]["derived_from"]["kind"] == "script"
    assert plan["jobs"][2]["profile_id"] == "bbbb2222" and plan["jobs"][3]["meta"]["subtitle"]["vi"].startswith("Hẹn")
    assert "meta" not in plan["jobs"][4]  # no metadata on the brand line: no meta key


def test_script_refusals(world_config, tmp_path) -> None:
    world, config = world_config
    eid = config.episode["episode_id"]
    with pytest.raises(Refused, match="no speaker"):
        dialogue_from_script(script_doc(shots=[{"id": "S01_A", "speech_text": "Hi", "duration_s": 1}]), episode_id=eid)
    with pytest.raises(Refused, match="has no speaker.*--vocabulary-speaker"):
        dialogue_from_script(script_doc(), episode_id=eid)
    shots = script_doc()["shots"]
    with pytest.raises(Refused, match="duplicate spoken shot ids"):
        dialogue_from_script(script_doc(shots=[shots[0], shots[0]]), episode_id=eid, vocabulary_speaker="kid")
    settings = voice_settings(config, skill_root=world.skill_root)
    cast = write(tmp_path, "cast.json", cast_doc(eid))
    wrong = dialogue_from_script(script_doc(language={"spoken": "vi"}), episode_id=eid, vocabulary_speaker="kid")
    with pytest.raises(Refused, match="E_LANGUAGE"):
        build_plan(config, settings, cast_path=cast, out=None, derived={"document": wrong, "source": {}})


def test_effect_preset_tag_needs_the_recipe_to_allow_it(world_config, tmp_path) -> None:
    world, config = world_config
    eid = config.episode["episode_id"]
    doc = dialogue_from_script(script_doc(), episode_id=eid, vocabulary_speaker="kid")
    doc["dialogue"][0]["effect_preset"] = "cosy"
    cast = write(tmp_path, "cast.json", cast_doc(eid))
    settings = voice_settings(config, skill_root=world.skill_root)
    with pytest.raises(Refused, match="E_EFFECT_PRESET"):
        build_plan(config, settings, cast_path=cast, out=None, derived={"document": doc, "source": {}})
    data = dict(settings.recipe.data, allowed_effect_presets=["cosy"])
    allowed = dataclasses.replace(settings, recipe=dataclasses.replace(settings.recipe, data=data))
    plan = build_plan(config, allowed, cast_path=cast, out=None, derived={"document": doc, "source": {}})
    assert plan["jobs"][0]["request"]["effect_preset"] == "cosy" and plan["jobs"][1]["request"]["effect_preset"] == "broadcast"


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not available")
def test_fake_episode_end_to_end_from_script_to_readable_bindings(world_config, tmp_path, capsys) -> None:
    world, config = world_config
    eid = config.episode["episode_id"]
    script = write(tmp_path, "script.json", script_doc())
    cast = write(tmp_path, "cast.json", cast_doc(eid))
    out = tmp_path / "voice-v001"
    ep = ["--episode", str(world.episode_file), "--out", str(out)]
    assert jjv.main(["voice", "plan", *ep, "--script", str(script), "--cast", str(cast), "--vocabulary-speaker", "kid"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["job_count"] == 5
    plan = receipts.load_plan(out)
    with FakeVoiceStudio() as fake:
        settings = voice_settings(config, voicestudio_url=fake.url, skill_root=world.skill_root)
        settings = dataclasses.replace(settings, gpu_lock_path=tmp_path / "gpu.lock", comfy_url="http://unused",
                                       lock_timeout_seconds=0.2, http_timeout_seconds=5.0)
        context = synth.SynthContext(settings=settings, out=out, plan=plan, queue_reader=lambda: IDLE,
                                     voice=VoiceStudioClient(fake.url, timeout_seconds=5.0, read_timeout_seconds=5.0),
                                     episode_root=Path(config.episode_root))
        result = synth.run_synth(context)
        assert result["completed"] == 5 and fake.posts_made() == 5
        assert [p["text"] for p in fake.posts][0] == "Look at the moon!" and fake.posts[4]["text"] == "Jennie Joy Kids"
    assert jjv.main(["voice", "finalize", *ep, "--category", "all"]) == 1  # not listened to yet: refused
    assert "E_LISTEN_APPROVAL" in json.loads(capsys.readouterr().out)["error"]
    for job in plan["jobs"]:
        assert jjv.main(["voice", "approve", *ep, "--job", job["request_id"], "--by", "Ken", "--note", "clear"]) == 0
    capsys.readouterr()
    assert jjv.main(["voice", "finalize", *ep, "--category", "all"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["bindings"].endswith("voice-bindings.json")
    assert printed["mix_handoff"]["classes"] == {"brand_voice": 1, "dialogue": 2, "end_line": 1, "vocabulary": 1}
    bindings = read_json(out / receipts.BINDINGS_FILE)
    assert bindings["schema"] == "jjv/voice-bindings/v1" and bindings["fps"] == 30
    assert bindings["finalize_sha256"] == sha256_file(out / receipts.FINALIZE_FILE)
    assert bindings["timeline_bound"] is True and bindings["pending_start_frames"] == []
    row = bindings["dialogue"][0]
    assert row["id"] == "S01_A" and row["start_frame"] == 90 and row["end_frame_exclusive"] == 225
    assert row["speech_text"] == "Look at the moon!" and row["dialogue_vi"] == "Nhìn mặt trăng!"
    assert row["audio"]["sha256"] == read_json(out / receipts.FINALIZE_FILE)["entries"][0]["receipt_wav"]["sha256"]
    # --- the real readers of the next stages ---
    root = Path(config.episode_root)
    lines = parse_lines(bindings)
    assert [(ln["id"], ln["start_frame"], ln["end_frame_exclusive"]) for ln in lines] == [("S01_A", 90, 225), ("S01_B", 225, 315)]
    assert lines[0]["target_keywords"] == ["moon"] and lines[0]["audio"]["sha256"] == row["audio"]["sha256"]
    assert parse_vocabulary(bindings["vocabulary"])[0]["term"] == "Moon"
    rows, source = resolve_bindings(bindings)
    assert source == "wav_bindings" and [b.name for b in rows] == ["dlg S01_A", "dlg S01_B", "voc Moon"]
    placed = windows.load_placed(bindings, root, TIMELINE, (out,))
    assert [(w.name, w.bus) for w in placed] == [("dlg S01_A", "dialogue"), ("dlg S01_B", "dialogue"), ("voc Moon", "vocabulary")]
    end = bindings["extras"][0]
    assert end["class"] == "end_line" and end["start_frame"] == 600
    extra = windows.load_extra(end["usage"]["extra_wav_args"][0], root, TIMELINE, (out,))
    assert extra.bus == "end_line" and extra.start_frame == 600 and extra.sha256 == end["audio"]["sha256"]
    brand = bindings["extras"][1]
    args = brand["usage"]["args"]
    assert args[0] == "--brand-voice" and brand["usage"]["via"] == "--brand-voice"
    voice = windows.load_brand_voice(args[1] if Path(args[1]).is_absolute() else root / args[1], args[3], TIMELINE, 0.15, 10 ** 7)
    assert voice.sha256 == brand["audio"]["sha256"]
    assert sha256_file(out / receipts.BINDINGS_FILE) and jjv.main(["voice", "finalize", *ep, "--category", "all"]) == 0  # idempotent


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not available")
def test_without_script_frames_the_bindings_keep_null_placeholders_that_readers_refuse(tmp_path) -> None:
    context = make(tmp_path, approved=True)  # dialogue file without frames
    finalize.run_finalize(context)
    bindings = read_json(context.out / receipts.BINDINGS_FILE)
    assert bindings["timeline_bound"] is False and len(bindings["pending_start_frames"]) == 3
    assert all(b["start_frame"] is None for b in bindings["wav_bindings"])
    with pytest.raises(Refused, match="integer"):
        parse_lines(bindings)
    with pytest.raises(Refused, match="integer"):
        resolve_bindings(bindings)
    split = next(e for e in read_json(context.out / receipts.FINALIZE_FILE)["entries"] if e["split"])
    assert split["split"]["full"]["samples"] == 72_000 and split["split"]["proof"]["ok"]
    kid = next(r for r in bindings["dialogue"] if r["id"] == "S01_B")
    assert kid["audio"]["sha256"] == split["split"]["full"]["sha256"]  # a split line binds as ONE full WAV
    assert [s["name"] for s in split["mix"]["h3_segments"]] == ["dlg S01_B:seg1", "dlg S01_B:seg2"]
