"""voice recipe mode ``passthrough`` (NEWTECONS adopt of listen-approved WAVs): the receipt WAV keeps the approved sha256."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from config_fixtures import make_live_action_world
from wav_fixtures import tone_wav_bytes

from engine.config.loader import resolve_episode
from engine.core.errors import Refused
from engine.core.io import read_json, sha256_file
from engine.seedvr2.seam_media import find_ffmpeg
from engine.voice import finalize, receipts, reconcile, synth, voice_bindings
from engine.voice.plan import build_plan
from engine.voice.recipe import load_voice_recipe, voice_settings
from test_voice_support import approve_all

RECIPE = "voice/ntc-vi-adopt-passthrough-v001"
try:
    FFMPEG: str | None = find_ffmpeg(None)
except Refused:
    FFMPEG = None
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not available")


def build(tmp_path: Path, *, rate: int = 48_000, channels: int = 2, semitones: float = 0, split: dict | None = None,
          approve: bool = True):
    world = make_live_action_world(tmp_path)
    config = resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    eid = config.episode["episode_id"]
    line = {"shot": "S01_A", "speaker": "host", "text_tts": "Xin chao cac ban.", "target_duration_s": 2.0}
    if split:
        line["split"] = split
    dialogue = {"schema": "jjv/dialogue/v1", "episode_id": eid, "status": "LOCKED", "dialogue": [line]}
    cast = {"schema": "jjv/cast/v1", "episode_id": eid, "speakers": {
        "host": {"speech_allowed": True, "voice": {"profile_id": "d9d994a3", "transform": {"pitch_semitones": semitones}}}}}
    d, c = tmp_path / "dialogue.json", tmp_path / "cast.json"
    d.write_text(json.dumps(dialogue), encoding="utf-8")
    c.write_text(json.dumps(cast), encoding="utf-8")
    settings = voice_settings(config, recipe_id=RECIPE, skill_root=world.skill_root)
    out = tmp_path / "voice"
    plan = build_plan(config, settings, dialogue_path=d, cast_path=c, out=out)
    out.mkdir()
    (out / receipts.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
    context = synth.SynthContext(settings=settings, out=out, plan=plan, voice=None, queue_reader=lambda: None,
                                 episode_root=Path(config.episode_root))
    native = tmp_path / "approved.wav"
    native.write_bytes(tone_wav_bytes(seconds=0.5, rate=rate, channels=channels, lead_silence=0.2, tail_silence=0.3))
    reconcile.adopt_takes(context, [{"request_id": plan["jobs"][0]["request_id"], "path": str(native), "audio_id": "pick1"}])
    if approve:
        approve_all(out, plan, Path(config.episode_root))
    ctx = finalize.FinalizeContext(settings=settings, config=config, out=out, plan=plan,
                                   ffmpeg=FFMPEG or "ffmpeg", category="all")
    return ctx, native


def test_recipe_modes_are_checked(tmp_path: Path) -> None:
    recipe = load_voice_recipe(RECIPE)
    assert recipe.passthrough and "trim" not in recipe.data and "transform" not in recipe.data
    synth_recipe = load_voice_recipe("voice/omnivoice-en-broadcast-v001")
    assert not synth_recipe.passthrough


def test_passthrough_recipe_that_names_a_trim_is_refused(tmp_path: Path) -> None:
    world = make_live_action_world(tmp_path)
    path = world.skill_root / "recipes" / "voice" / "ntc-vi-adopt-passthrough-v001.json"
    data = read_json(path)
    data["trim"] = read_json(world.skill_root / "recipes/voice/omnivoice-en-broadcast-v001.json")["trim"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Refused, match="passthrough must not declare"):
        load_voice_recipe(RECIPE, skill_root=world.skill_root)


def test_synth_recipe_without_trim_is_refused(tmp_path: Path) -> None:
    world = make_live_action_world(tmp_path)
    path = world.skill_root / "recipes" / "voice" / "omnivoice-en-broadcast-v001.json"
    data = read_json(path)
    del data["trim"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Refused, match="synth requires"):
        load_voice_recipe("voice/omnivoice-en-broadcast-v001", skill_root=world.skill_root)


@needs_ffmpeg
def test_passthrough_keeps_the_approved_sha_and_binds_it(tmp_path: Path) -> None:
    ctx, native = build(tmp_path)
    approved_sha = sha256_file(native)
    receipt = finalize.run_finalize(ctx)
    entry = receipt["entries"][0]
    assert receipt["mode"] == "passthrough" and receipt["trim"] is None
    for key in ("native", "base", "editorial", "receipt_wav"):
        assert entry[key]["sha256"] == approved_sha, key
    assert entry["trim"] is None and entry["transform"]["mode"] == "passthrough"
    assert not (ctx.out / "finalize").exists()  # nothing was converted, trimmed or written
    bindings = read_json(ctx.out / receipts.BINDINGS_FILE)
    assert bindings["dialogue"][0]["audio"]["sha256"] == approved_sha
    path = receipts.resolve_described(bindings["dialogue"][0]["audio"]["path"], episode_root=ctx.episode_root, out=ctx.out)
    assert sha256_file(path) == approved_sha and voice_bindings.BINDINGS_SCHEMA == bindings["schema"]


@needs_ffmpeg
def test_passthrough_still_needs_a_listen_approval(tmp_path: Path) -> None:
    ctx, _ = build(tmp_path, approve=False)
    with pytest.raises(Refused, match="E_LISTEN_APPROVAL"):
        finalize.run_finalize(ctx)


@needs_ffmpeg
def test_passthrough_refuses_a_take_in_another_format(tmp_path: Path) -> None:
    ctx, _ = build(tmp_path, rate=24_000, channels=1)
    with pytest.raises(Refused, match="E_PASSTHROUGH_FORMAT"):
        finalize.run_finalize(ctx)


@needs_ffmpeg
def test_passthrough_refuses_a_pitch_transform(tmp_path: Path) -> None:
    ctx, _ = build(tmp_path, semitones=1.0)
    with pytest.raises(Refused, match="E_PASSTHROUGH_EDIT"):
        finalize.run_finalize(ctx)


@needs_ffmpeg
def test_passthrough_dry_run_reports_no_trim(tmp_path: Path) -> None:
    ctx, _ = build(tmp_path)
    report = finalize.dry_run(ctx)
    assert report["trim"] is None and report["jobs"][0]["approved"] is True
