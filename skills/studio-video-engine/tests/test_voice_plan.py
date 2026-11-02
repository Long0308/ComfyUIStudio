"""voice plan: request parity with the first batch tool, lint refusals, recipe selection, CLI."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from config_fixtures import make_world

from engine.config.loader import resolve_episode
from engine.core.errors import Refused
from engine.voice import receipts
from engine.voice.plan import build_jobs, build_plan
from engine.voice.recipe import load_voice_recipe, select_recipe_id, voice_settings

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "bin"))
import jjv  # noqa: E402

SPLIT = {"pad_tail_silence": True, "segments": [
    {"label": "seg1", "samples": 48_000, "speech_conditioning": True},
    {"label": "seg2", "samples": 24_000, "speech_conditioning": False}]}


def dialogue_doc(episode_id: str, **extra: object) -> dict:
    doc = {"schema": "jjv/dialogue/v1", "episode_id": episode_id, "status": "LOCKED",
           "dialogue": [{"shot": "S01_A", "speaker": "host", "text_tts": "Look at the moon!", "target_duration_s": 4.5},
                        {"shot": "S01_B", "speaker": "kid", "text_tts": "It is round and bright.",
                         "target_duration_s": 5.5, "split": SPLIT}],
           "vocabulary": [{"term": "Moon", "speaker": "kid", "target_duration_s": 0.9}]}
    doc.update(extra)
    return doc


def cast_doc(episode_id: str) -> dict:
    return {"schema": "jjv/cast/v1", "episode_id": episode_id, "speakers": {
        "host": {"speech_allowed": True, "voice": {"profile_id": "aaaa1111", "transform": {"pitch_semitones": 0}}},
        "kid": {"speech_allowed": True, "voice": {"profile_id": "bbbb2222", "transform": {"pitch_semitones": -1}}},
        "pet": {"speech_allowed": False}}}


@pytest.fixture
def world(tmp_path: Path):
    return make_world(tmp_path)


@pytest.fixture
def config(world):
    return resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)


def write_docs(tmp_path: Path, episode_id: str, dialogue: dict | None = None, cast: dict | None = None) -> tuple[Path, Path]:
    d, c = tmp_path / "dialogue.json", tmp_path / "cast.json"
    d.write_text(json.dumps(dialogue or dialogue_doc(episode_id)), encoding="utf-8")
    c.write_text(json.dumps(cast or cast_doc(episode_id)), encoding="utf-8")
    return d, c


def legacy_stable_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_request_shape_and_sha_match_the_first_batch_tool(config, world) -> None:
    recipe = load_voice_recipe("voice/omnivoice-en-broadcast-v001", skill_root=world.skill_root)
    jobs = build_jobs(dialogue_doc(config.episode["episode_id"]), cast_doc(config.episode["episode_id"]), recipe.data)
    assert [j["request_id"] for j in jobs] == ["dialogue:S01_A", "dialogue:S01_B", "vocabulary:Moon"]
    first = jobs[0]
    assert first["request"] == {"text": "Look at the moon!", "profile_id": "aaaa1111", "language": "English",
                                "engine": "omnivoice", "duration": "4.5", "effect_preset": "broadcast", "wav_bits": "16"}
    assert first["request_sha256"] == legacy_stable_sha256(first["request"])
    assert jobs[1]["transform"] == {"pitch_semitones": -1.0} and jobs[1]["split"] == SPLIT
    assert jobs[2]["category"] == "vocabulary" and jobs[2]["request"]["duration"] == "0.9"


def test_plan_is_deterministic_and_does_not_touch_the_config_sha(config, world, tmp_path) -> None:
    settings = voice_settings(config, skill_root=world.skill_root)
    d, c = write_docs(tmp_path, config.episode["episode_id"])
    one = build_plan(config, settings, dialogue_path=d, cast_path=c, out=tmp_path / "out")
    two = build_plan(config, settings, dialogue_path=d, cast_path=c, out=tmp_path / "out")
    assert one == two and one["config_sha256"] == config.config_sha256 and one["canonical_mode"] == "ascii"
    again = resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    assert again.config_sha256 == config.config_sha256
    assert settings.sources["recipe"] == "unique recipe for the domain"


@pytest.mark.parametrize("text, code", [
    ("Mother: Look at the moon!", "E_SPEAKER_PREFIX"),
    ("[laughs] Look at the moon!", "E_SPEAKER_PREFIX"),
    ("   ", "blank"),
])
def test_text_lint_is_red(config, world, text, code) -> None:
    recipe = load_voice_recipe("voice/omnivoice-en-broadcast-v001", skill_root=world.skill_root)
    doc = dialogue_doc(config.episode["episode_id"])
    doc["dialogue"][0]["text_tts"] = text
    with pytest.raises(Refused, match=code):
        build_jobs(doc, cast_doc(config.episode["episode_id"]), recipe.data)


@pytest.mark.parametrize("speaker, code", [("pet", "E_APPROVED_CAST.*silent"), ("ghost", "E_APPROVED_CAST.*not in the cast")])
def test_cast_gates_are_red(config, world, speaker, code) -> None:
    recipe = load_voice_recipe("voice/omnivoice-en-broadcast-v001", skill_root=world.skill_root)
    doc = dialogue_doc(config.episode["episode_id"])
    doc["dialogue"][0]["speaker"] = speaker
    with pytest.raises(Refused, match=code):
        build_jobs(doc, cast_doc(config.episode["episode_id"]), recipe.data)


def test_missing_voice_binding_duplicate_ids_and_bad_split_are_red(config, world) -> None:
    recipe = load_voice_recipe("voice/omnivoice-en-broadcast-v001", skill_root=world.skill_root)
    eid = config.episode["episode_id"]
    cast = cast_doc(eid)
    del cast["speakers"]["host"]["voice"]
    with pytest.raises(Refused, match="no voice binding"):
        build_jobs(dialogue_doc(eid), cast, recipe.data)
    doc = dialogue_doc(eid)
    doc["dialogue"].append(dict(doc["dialogue"][0]))
    with pytest.raises(Refused, match="duplicate voice request ids"):
        build_jobs(doc, cast_doc(eid), recipe.data)
    doc = dialogue_doc(eid)
    doc["dialogue"][1]["split"] = {"segments": [{"label": "a", "samples": 0, "speech_conditioning": True}]}
    with pytest.raises(Refused, match="positive integer"):
        build_jobs(doc, cast_doc(eid), recipe.data)


def test_episode_id_and_schema_mismatch_are_red(config, world, tmp_path) -> None:
    settings = voice_settings(config, skill_root=world.skill_root)
    d, c = write_docs(tmp_path, "other-episode")
    with pytest.raises(Refused, match="episode_id"):
        build_plan(config, settings, dialogue_path=d, cast_path=c, out=None)
    d, c = write_docs(tmp_path, config.episode["episode_id"], dialogue={"schema": "nope"})
    with pytest.raises(Refused, match="schema"):
        build_plan(config, settings, dialogue_path=d, cast_path=c, out=None)


def test_recipe_selection_rules(config, world) -> None:
    folder = world.skill_root / "recipes" / "voice"
    source = json.loads((folder / "omnivoice-en-broadcast-v001.json").read_text(encoding="utf-8"))
    foreign = dict(source, recipe_id="voice/foreign-v001", domain="some_other_domain")
    (folder / "foreign-v001.json").write_text(json.dumps(foreign), encoding="utf-8")
    assert select_recipe_id(config, None, skill_root=world.skill_root)[0] == "voice/omnivoice-en-broadcast-v001"
    with pytest.raises(Refused, match="belongs to domain"):
        voice_settings(config, recipe_id="voice/foreign-v001", skill_root=world.skill_root)
    with pytest.raises(Refused, match="not found"):
        voice_settings(config, recipe_id="voice/missing", skill_root=world.skill_root)
    twin = dict(source, recipe_id="voice/twin-v001")
    (folder / "twin-v001.json").write_text(json.dumps(twin), encoding="utf-8")
    with pytest.raises(Refused, match="no voice recipe selected"):
        select_recipe_id(config, None, skill_root=world.skill_root)
    bad = dict(source, wav_bits="12")
    (folder / "omnivoice-en-broadcast-v001.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(Refused, match="wav_bits"):
        load_voice_recipe("voice/omnivoice-en-broadcast-v001", skill_root=world.skill_root)


def test_cli_plan_dry_run_writes_nothing_and_plan_is_write_once(world, config, tmp_path, capsys) -> None:
    d, c = write_docs(tmp_path, config.episode["episode_id"])
    out = tmp_path / "voice-v001"
    base = ["voice", "plan", "--episode", str(world.episode_file), "--out", str(out), "--dialogue", str(d), "--cast", str(c)]
    assert jjv.main(base + ["--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["plan"]["job_count"] == 3 and not out.exists()
    assert jjv.main(base) == 0
    written = json.loads(capsys.readouterr().out)
    assert (out / receipts.PLAN_FILE).is_file() and written["job_count"] == 3
    assert jjv.main(base) == 0  # identical bytes: idempotent
    capsys.readouterr()
    (tmp_path / "dialogue.json").write_text(json.dumps(dialogue_doc(config.episode["episode_id"], status="DRAFT")))
    assert jjv.main(base) == 1  # different plan over the same file: Refused
    assert "refusing to overwrite" in json.loads(capsys.readouterr().out)["error"]


def test_cli_plan_without_documents_refuses_with_the_flag_name(world, tmp_path, capsys) -> None:
    code = jjv.main(["voice", "plan", "--episode", str(world.episode_file), "--out", str(tmp_path / "o"), "--dry-run"])
    assert code == 1 and "--dialogue" in json.loads(capsys.readouterr().out)["error"]
