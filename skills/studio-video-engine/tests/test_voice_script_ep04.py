"""The first episode through the script-driven voice stage (read-only on production-local, adopt mode).

Pins: the locked script gives the SAME 24 request_sha256 as the hand-made dialogue file; the 25th job is the end line
("See you again, baby!", sha 2cae6756...); after adopt -> approve -> finalize the voice-bindings.json carries the
subtitle id -> receipt WAV rows that equal the first episode's review config: the 6 Alice lines, the 12 vocabulary
cards and the S06_B full WAV are sha-equal; the 6 Mother lines carry the pinned engine shas (onset rule, documented
in SKILL-SECTION-voice.md).  The end line needs the optional ``quiet_burst_db`` onset rule to reproduce the hand trim.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from ep04_voice_fixture import EPISODE_ROOT, EPISODE_SLUG, SCRIPT, SPLIT_S06B, available, derive_documents
from test_voice_parity_ep04 import MOTHER_ENGINE_SHA
from test_voice_support import approve_all

from engine.config.loader import resolve_episode
from engine.core.errors import Refused
from engine.core.io import read_json, sha256_file
from engine.seedvr2.seam_media import find_ffmpeg
from engine.voice import approval, finalize, receipts, reconcile, synth
from engine.voice.plan import build_plan
from engine.voice.recipe import voice_settings
from engine.voice.script_ingest import dialogue_from_script

try:
    FFMPEG: str | None = find_ffmpeg(None)
except Refused:
    FFMPEG = None
REVIEW = EPISODE_ROOT / "editorial" / "review-hd-v015" / "config" / "review-config-v015.json"
END_LINE = EPISODE_ROOT / "audio" / "end-line-v001"
pytestmark = pytest.mark.skipif(not available() or FFMPEG is None or not REVIEW.is_file() or not END_LINE.is_dir(),
                                reason="first-episode sources or ffmpeg not available")
END_REQUEST_SHA = "2cae6756177867a5fa3a8b7481a7ce59fbdf0e2a896e0ce70d75be2f5f7ad1df"
END_LEGACY_SHA = "d250672daa49e7d70eb589311ef46e1c100fca17c35d603a5d04bd3baa01b5d7"
END_EXTRA = {"kind": "end_line", "id": "mother", "speaker": "mother", "text_tts": "See you again, baby!",
             "target_duration_s": 1.8}


def _script() -> dict:
    script = json.loads(SCRIPT.read_text(encoding="utf-8-sig"))
    for shot in script["shots"]:
        if shot["id"] == "S06_B":
            shot["voice_split"] = SPLIT_S06B  # the split plan is data on the shot (the script has none yet)
    return script


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    tmp = tmp_path_factory.mktemp("ep04-script-voice")
    docs = derive_documents()
    config = resolve_episode(EPISODE_SLUG)
    settings = voice_settings(config)
    document = dialogue_from_script(_script(), episode_id=config.episode["episode_id"], vocabulary_speaker="alice",
                                    extras=[END_EXTRA])
    cast = tmp / "cast.json"
    cast.write_text(json.dumps(docs["cast"]), encoding="utf-8")
    out = tmp / "voice-script"
    plan = build_plan(config, settings, cast_path=cast, out=out,
                      derived={"document": document, "source": {"kind": "script", "path": str(SCRIPT), "sha256": sha256_file(SCRIPT)}})
    out.mkdir()
    (out / receipts.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
    context = synth.SynthContext(settings=settings, out=out, plan=plan, voice=None, queue_reader=lambda: None,
                                 episode_root=Path(config.episode_root))
    end_take = {"request_id": "end_line:mother", "audio_id": "ef974ceb",
                "path": str(END_LINE / "native" / "end_line-mother-ef974ceb-native.wav")}
    assert reconcile.adopt_takes(context, [*docs["takes"], end_take])["adopted"] == 25
    approve_all(out, plan, Path(config.episode_root))
    receipt = finalize.run_finalize(finalize.FinalizeContext(settings=settings, config=config, out=out, plan=plan,
                                                             ffmpeg=FFMPEG, category="all"))
    return {"docs": docs, "plan": plan, "out": out, "settings": settings, "config": config, "context": context,
            "receipt": receipt, "review": json.loads(REVIEW.read_text(encoding="utf-8-sig"))}


def test_script_gives_the_same_24_jobs_plus_the_end_line(run: dict) -> None:
    got = {j["request_id"]: j["request_sha256"] for j in run["plan"]["jobs"]}
    assert got.pop("end_line:mother") == END_REQUEST_SHA
    assert got == run["docs"]["expected_request_sha"] and len(got) == 24
    assert run["plan"]["jobs"][0]["meta"]["subtitle"]["vi"].startswith("Alice ơi")


def test_bindings_equal_the_first_episode_receipt_wavs(run: dict) -> None:
    bindings = read_json(run["out"] / receipts.BINDINGS_FILE)
    legacy = {r["id"]: r for r in run["review"]["dialogue"]}
    assert [r["id"] for r in bindings["dialogue"]] == list(legacy)
    for row in bindings["dialogue"]:
        old = legacy[row["id"]]
        assert row["speech_text"] == old["speech_text"] and row["dialogue_vi"] == old["dialogue_vi"]
        assert row["speaker"] == old["speaker"]
        if row["speaker"] == "alice":
            assert row["audio"]["sha256"] == old["audio"]["sha256"], row["id"]  # incl. the S06_B full 12.5 s WAV
        else:
            assert row["audio"]["sha256"] == MOTHER_ENGINE_SHA[row["id"]], row["id"]
    scripted = {s["id"]: s["start_frame"] for s in _script()["shots"]}
    assert {r["id"]: r["start_frame"] for r in bindings["dialogue"]} == scripted  # frames come from the script


def test_vocabulary_cards_and_the_late_lines_bind_for_the_mix(run: dict) -> None:
    bindings = read_json(run["out"] / receipts.BINDINGS_FILE)
    cards = {c["term"]: c for c in run["review"]["outro_cards"]}
    assert [c["term"] for c in bindings["outro_cards"]] == list(cards) and len(cards) == 12
    for card in bindings["outro_cards"]:
        assert card["audio"]["sha256"] == cards[card["term"]]["audio"]["sha256"], card["term"]
        assert card["start_frame"] is None  # the script gives seconds, not frames: a placeholder, never invented
    assert bindings["timeline_bound"] is False and len(bindings["pending_start_frames"]) == 12
    assert [b["name"] for b in bindings["wav_bindings"]][:2] == ["dlg S01_A", "dlg S01_B"]
    assert [b["name"] for b in bindings["wav_bindings"]][12] == "voc Creamy"
    end = bindings["extras"][0]
    assert end["id"] == "mother" and end["class"] == "end_line" and end["speech_text"] == "See you again, baby!"
    assert run["receipt"]["mix_handoff"]["classes"] == {"dialogue": 12, "end_line": 1, "vocabulary": 12}


def test_end_line_reproduces_the_hand_trim_only_with_the_quiet_burst_rule(run: dict, tmp_path: Path) -> None:
    job = next(j for j in run["plan"]["jobs"] if j["request_id"] == "end_line:mother")
    native = END_LINE / "native" / "end_line-mother-ef974ceb-native.wav"
    legacy = read_json(END_LINE / "TRIM-RECEIPT.json")
    assert sha256_file(native) == legacy["native"]["sha256"]
    shas = {}
    for label, quiet in (("default", None), ("quiet", 15.0)):
        out = tmp_path / label
        out.mkdir()
        plan = dict(run["plan"], jobs=[job])
        (out / receipts.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
        recipe_data = json.loads(json.dumps(run["settings"].recipe.data))
        if quiet is not None:
            recipe_data["trim"]["onset"]["quiet_burst_db"] = quiet
        settings = dataclasses.replace(run["settings"], recipe=dataclasses.replace(run["settings"].recipe, data=recipe_data))
        context = synth.SynthContext(settings=settings, out=out, plan=plan, voice=None, queue_reader=lambda: None,
                                     episode_root=Path(run["config"].episode_root))
        reconcile.adopt_takes(context, [{"request_id": job["request_id"], "path": str(native), "audio_id": "ef974ceb"}])
        approval.approve(out, job, by="Ken", note="test", sha256=None, episode_root=context.episode_root)
        entry = finalize.run_finalize(finalize.FinalizeContext(settings=settings, config=run["config"], out=out, plan=plan,
                                                               ffmpeg=FFMPEG, category="end_line"))["entries"][0]
        shas[label] = entry
        assert entry["class"] == "end_line" and entry["mix"]["usage"]["via"] == "--extra-wav"
    assert shas["default"]["receipt_wav"]["sha256"] != END_LEGACY_SHA  # the 0.11 s breath latches the onset (documented)
    assert shas["default"]["trim"]["onset"]["skipped_bursts"] == []
    assert shas["quiet"]["receipt_wav"]["sha256"] == END_LEGACY_SHA  # == end-line-mother-trim-v001-48k.wav
    assert shas["quiet"]["trim"]["onset"]["skipped_bursts"][0]["reason"] == "quiet_vs_loudest_run"
    assert shas["quiet"]["receipt_wav"]["samples"] == 77_760
