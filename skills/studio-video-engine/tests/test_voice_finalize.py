"""voice finalize with real ffmpeg (skipped without it): editorial format, transform, one trim, split, CLI."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest
from config_fixtures import make_world
from wav_fixtures import segments_wav_bytes, silence, square_full_scale, tone, tone_wav_bytes

from engine.config import loader
from engine.config.loader import resolve_episode
from engine.core.errors import Refused
from engine.core.io import read_json, sha256_file
from engine.seedvr2.seam_media import find_ffmpeg
from engine.voice import finalize, receipts, reconcile, synth
from engine.voice.plan import build_plan
from engine.voice.recipe import VoiceRecipe, voice_settings
from engine.voice.wavio import ffmpeg_has_filter, read_wav
from test_voice_plan import cast_doc, dialogue_doc
from test_voice_support import approve_all

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "bin"))
import jjv  # noqa: E402

try:
    FFMPEG: str | None = find_ffmpeg(None)
except Refused:
    FFMPEG = None
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not available")


def make(tmp_path: Path, dialogue: dict | None = None, cast: dict | None = None, *, lead: float = 0.2,
         seconds: float = 0.5, square: bool = False, approved: bool = True) -> finalize.FinalizeContext:
    world = make_world(tmp_path)
    config = resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    eid = config.episode["episode_id"]
    d, c = tmp_path / "dialogue.json", tmp_path / "cast.json"
    d.write_text(json.dumps(dialogue or dialogue_doc(eid)), encoding="utf-8")
    c.write_text(json.dumps(cast or cast_doc(eid)), encoding="utf-8")
    settings = voice_settings(config, skill_root=world.skill_root)
    out = tmp_path / "voice-v001"
    plan = build_plan(config, settings, dialogue_path=d, cast_path=c, out=out)
    out.mkdir()
    (out / receipts.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
    context = synth.SynthContext(settings=settings, out=out, plan=plan, voice=None, queue_reader=lambda: None,
                                 episode_root=Path(config.episode_root))
    rows = []
    for index, job in enumerate(plan["jobs"]):
        native = tmp_path / f"native-{index}.wav"
        if square:
            native.write_bytes(segments_wav_bytes([silence(lead, 24_000), square_full_scale(seconds, 24_000),
                                                   silence(0.3, 24_000)], 24_000, 1))
        else:
            native.write_bytes(tone_wav_bytes(seconds=seconds, rate=24_000, channels=1, lead_silence=lead))
        rows.append({"request_id": job["request_id"], "path": str(native), "audio_id": f"id{index:06d}"})
    reconcile.adopt_takes(context, rows)
    if approved:
        approve_all(out, plan, Path(config.episode_root))
    return finalize.FinalizeContext(settings=settings, config=config, out=out, plan=plan, ffmpeg=FFMPEG, category="all")


def test_finalize_converts_transforms_trims_and_binds(tmp_path: Path) -> None:
    context = make(tmp_path)
    receipt = finalize.run_finalize(context)
    assert receipt["schema"] == "jjv/voice-finalize/v1" and len(receipt["entries"]) == 3
    host, kid = receipt["entries"][0], receipt["entries"][1]
    assert host["editorial"]["metrics"]["sample_rate"] == 48_000 and host["editorial"]["metrics"]["channels"] == 2
    assert host["base"]["path"] == host["editorial"]["path"] and host["transform"]["pitch_semitones"] == 0
    assert host["trim"]["start_sample"] == round((0.2 - 0.08) * 48_000)
    wav = read_wav(context.out / host["receipt_wav"]["path"])
    assert wav.frames == host["receipt_wav"]["samples"] and sha256_file(context.out / host["receipt_wav"]["path"]) == host["receipt_wav"]["sha256"]
    assert host["receipt_wav"]["offset_s"] == 0.0 and host["speech_conditioning"] is True
    assert kid["split"]["proof"]["ok"] and [s["label"] for s in kid["split"]["segments"]] == ["seg1", "seg2"]
    assert kid["split"]["segments"][1]["speech_conditioning"] is False and kid["split"]["segments"][1]["receipt_wav"] is False
    assert kid["split"]["segments"][1]["padded_samples"] > 0
    if ffmpeg_has_filter(FFMPEG, "rubberband"):
        assert kid["base"]["path"] != kid["editorial"]["path"] and kid["editorial"]["samples"] == kid["base"]["samples"]
        assert kid["transform"]["pitch_semitones"] == -1.0
    assert (context.out / receipts.FINALIZE_FILE).is_file()
    assert finalize.run_finalize(context) == receipt  # identical second run: idempotent write-once


@pytest.mark.skipif(FFMPEG is not None and not ffmpeg_has_filter(FFMPEG, "rubberband"), reason="no rubberband filter")
def test_pitch_transform_keeps_the_exact_sample_count(tmp_path: Path) -> None:
    context = make(tmp_path)
    receipt = finalize.run_finalize(context)
    kid = receipt["entries"][1]
    assert read_wav(context.out / kid["editorial"]["path"]).frames == read_wav(context.out / kid["base"]["path"]).frames


def test_second_finalize_with_other_trim_parameters_is_e_trim_once(tmp_path: Path) -> None:
    context = make(tmp_path)
    finalize.run_finalize(context)
    data = dict(context.settings.recipe.data)
    data["trim"] = dict(data["trim"], pre_roll_s=0.05)
    other = VoiceRecipe(recipe_id=context.settings.recipe.recipe_id, path=context.settings.recipe.path,
                        sha256="0" * 64, data=data)
    changed = dataclasses.replace(context, settings=dataclasses.replace(context.settings, recipe=other))
    with pytest.raises(Refused, match="E_TRIM_ONCE"):
        finalize.run_finalize(changed)
    with pytest.raises(Refused, match="E_TRIM_ONCE"):
        finalize.dry_run(changed)


def test_clipped_and_over_budget_and_missing_take_are_refused(tmp_path: Path) -> None:
    context = make(tmp_path / "clip", square=True)
    with pytest.raises(Refused, match="clipped samples"):
        finalize.run_finalize(context)
    context = make(tmp_path / "budget")
    doc = dialogue_doc(context.config.episode["episode_id"])
    doc["dialogue"][0]["max_duration_s"] = 0.2
    context = make(tmp_path / "budget2", dialogue=doc)
    with pytest.raises(Refused, match="over the budget"):
        finalize.run_finalize(context)
    context = make(tmp_path / "missing")
    (receipts.job_dir(context.out, "dialogue:S01_A") / receipts.TAKE).unlink()
    with pytest.raises(Refused, match="missing"):
        finalize.run_finalize(context)


def test_declared_silent_segment_with_speech_is_refused(tmp_path: Path) -> None:
    context = make(tmp_path, seconds=2.0)  # the kid line now lasts 2 s: seg2 (0.5 s, declared silent) holds speech
    with pytest.raises(Refused, match="declared silent"):
        finalize.run_finalize(context)


def test_dry_run_writes_nothing_and_category_filter(tmp_path: Path) -> None:
    context = make(tmp_path)
    rows = finalize.dry_run(context)["jobs"]
    assert [r["state"] for r in rows] == ["COMPLETED"] * 3 and not (context.out / "finalize").exists()
    only = dataclasses.replace(context, category="vocabulary")
    receipt = finalize.run_finalize(only)
    assert [e["category"] for e in receipt["entries"]] == ["vocabulary"]
    with pytest.raises(Refused, match="no planned jobs"):
        finalize.run_finalize(dataclasses.replace(context, category="dialogue", plan=dict(context.plan, jobs=[])))


def test_cli_plan_adopt_synth_dry_run_finalize(tmp_path: Path, capsys, monkeypatch) -> None:
    world = make_world(tmp_path)
    monkeypatch.setattr(loader, "DEFAULT_MACHINE_PATH", world.machine_path)  # the CLI reads the default machine file,
    # which now carries machine.voicestudio.url; this test is about a machine WITHOUT one
    config = resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    eid = config.episode["episode_id"]
    d, c = tmp_path / "dialogue.json", tmp_path / "cast.json"
    d.write_text(json.dumps(dialogue_doc(eid)), encoding="utf-8")
    c.write_text(json.dumps(cast_doc(eid)), encoding="utf-8")
    out = tmp_path / "voice-v001"
    ep = ["--episode", str(world.episode_file), "--out", str(out)]
    assert jjv.main(["voice", "plan", *ep, "--dialogue", str(d), "--cast", str(c)]) == 0
    plan = read_json(out / receipts.PLAN_FILE)
    natives = []
    for index, job in enumerate(plan["jobs"]):
        native = tmp_path / f"n{index}.wav"
        native.write_bytes(segments_wav_bytes([silence(0.2, 24_000), tone(0.4, 24_000), silence(0.2, 24_000)], 24_000, 1))
        natives.append({"request_id": job["request_id"], "path": str(native), "audio_id": f"a{index:07d}"})
    (tmp_path / "takes.json").write_text(json.dumps(natives), encoding="utf-8")
    capsys.readouterr()
    assert jjv.main(["voice", "adopt", *ep, "--takes", str(tmp_path / "takes.json")]) == 0
    assert json.loads(capsys.readouterr().out)["adopted"] == 3
    assert jjv.main(["voice", "synth", *ep]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert jjv.main(["voice", "synth", *ep, "--execute", "--dry-run"]) == 1
    capsys.readouterr()
    assert jjv.main(["voice", "synth", *ep, "--execute"]) == 1  # no VoiceStudio URL: Refused before any POST
    assert "VoiceStudio URL" in json.loads(capsys.readouterr().out)["error"]
    assert jjv.main(["voice", "finalize", *ep, "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True and not (out / "finalize").exists()
    assert jjv.main(["voice", "finalize", *ep]) == 1  # the domain requires a listen approval: refused, nothing written
    assert "E_LISTEN_APPROVAL" in json.loads(capsys.readouterr().out)["error"] and not (out / "finalize").exists()
    for job in plan["jobs"]:
        assert jjv.main(["voice", "approve", *ep, "--job", job["request_id"], "--by", "Ken", "--note", "clear"]) == 0
    capsys.readouterr()
    assert jjv.main(["voice", "finalize", *ep]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert [e["shot"] for e in summary["entries"]] == ["S01_A", "S01_B"] and summary["entries"][1]["split"] == ["seg1", "seg2"]
    assert (out / receipts.FINALIZE_FILE).is_file()
