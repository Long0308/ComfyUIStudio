"""Parity of the voice stage with the first episode's hand-made batch (read-only on production-local).

Pins: 24 request_sha256; the 6 Alice receipt WAVs + the 3 S06_B segments byte-equal to
dialogue-trim-v002; the 6 Mother cuts equal the legacy shas with the burst filter off
(min_run_s = 0) and equal the recorded engine shas with the default onset rule, so any change
to ``choose_onset`` or the trim arithmetic turns this red.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from ep04_voice_fixture import EPISODE_SLUG, TRIM_V002, available, derive_documents

from engine.config.loader import resolve_episode
from engine.seedvr2.seam_media import find_ffmpeg
from engine.core.errors import Refused
from engine.voice import finalize, receipts, reconcile, synth
from engine.voice.plan import build_plan
from engine.voice.recipe import voice_settings
from engine.voice.trim import TrimParams, trim_bounds, trim_pcm
from engine.voice.wavio import read_wav, wav_bytes
from test_voice_support import approve_all

try:
    FFMPEG: str | None = find_ffmpeg(None)
except Refused:
    FFMPEG = None
pytestmark = pytest.mark.skipif(not available() or FFMPEG is None,
                                reason="first-episode voice sources or ffmpeg not available")

ALICE = ("S01_B", "S02_B", "S03_B", "S04_B", "S05_B", "S06_B")
MOTHER_ENGINE_SHA = {  # default onset rule (recorded 2026-10-27, ffmpeg 9.0 gyan build)
    "S01_A": "a000850b8ec489770b3d750314b887413f3ea96dccfe9f2b40c1277405bd364a",
    "S02_A": "44095e8dc561ec05a6ad680dea254acf55429b4c4018530c9723787fffc3e016",
    "S03_A": "6552b4f8c48236b6c87628b9dddeb458af47109ffd06ae90e9c91941a54eff56",
    "S04_A": "491026ab279aa62cb8bab182abc2409d6b6e707e06d9e4fdaf02a3ee064d6148",
    "S05_A": "2a190a5f9ea46ada6462d90ddd2b69288ca0e282f98ed5ed306f63809576bad1",
    "S06_A": "b55a4bd4d0ea35b97272689710cd04e7b9b729b152e809a5d123756a7324a643",
}


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """plan -> adopt (24 natives, hashed in place) -> finalize dialogue, once per module."""
    tmp = tmp_path_factory.mktemp("ep04-voice")
    docs = derive_documents()
    d, c = tmp / "dialogue.json", tmp / "cast.json"
    d.write_text(json.dumps(docs["dialogue"]), encoding="utf-8")
    c.write_text(json.dumps(docs["cast"]), encoding="utf-8")
    config = resolve_episode(EPISODE_SLUG)
    settings = voice_settings(config)
    out = tmp / "voice-parity"
    plan = build_plan(config, settings, dialogue_path=d, cast_path=c, out=out)
    out.mkdir()
    (out / receipts.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
    context = synth.SynthContext(settings=settings, out=out, plan=plan, voice=None, queue_reader=lambda: None,
                                 episode_root=Path(config.episode_root))
    assert reconcile.adopt_takes(context, docs["takes"])["adopted"] == 24
    approve_all(out, plan, Path(config.episode_root))  # test-only: the domain requires a listen approval record per take
    receipt = finalize.run_finalize(finalize.FinalizeContext(settings=settings, config=config, out=out, plan=plan,
                                                             ffmpeg=FFMPEG, category="dialogue"))
    return {"docs": docs, "plan": plan, "receipt": receipt, "out": out, "settings": settings}


def test_24_request_sha256_equal_the_historical_manifest(run: dict) -> None:
    got = {job["request_id"]: job["request_sha256"] for job in run["plan"]["jobs"]}
    assert got == run["docs"]["expected_request_sha"] and len(got) == 24


def test_alice_receipt_wavs_are_byte_equal_to_trim_v002(run: dict) -> None:
    entries = {e["shot"]: e for e in run["receipt"]["entries"]}
    for shot in ALICE:
        assert entries[shot]["receipt_wav"]["sha256"] == run["docs"]["trim_v002"][shot]["sha256"], shot
        assert entries[shot]["trim"]["onset"]["differs_from_naive"] is False, shot


def test_s06b_split_segments_are_byte_equal_with_the_concatenation_proof(run: dict) -> None:
    split = {e["shot"]: e for e in run["receipt"]["entries"]}["S06_B"]["split"]
    assert split["proof"]["ok"] and split["proof"]["concatenated_samples"] == 600_000
    assert [s["samples"] for s in split["segments"]] == [240_000, 280_000, 80_000]
    for segment in split["segments"]:
        reference = TRIM_V002 / f"dialogue-S06_B-{segment['label']}-v003-48k.wav"
        assert segment["sha256"] == hashlib.sha256(reference.read_bytes()).hexdigest(), segment["label"]
    assert split["segments"][2]["speech_conditioning"] is False and split["segments"][2]["padded_samples"] == 78_720


def test_mother_cuts_differ_only_by_the_onset_rule(run: dict) -> None:
    entries = {e["shot"]: e for e in run["receipt"]["entries"]}
    params = TrimParams.from_recipe(run["settings"].recipe.data)
    naive = dataclasses.replace(params, min_run_s=0.0)  # every run is speech == the legacy first-window rule
    for shot, engine_sha in MOTHER_ENGINE_SHA.items():
        entry = entries[shot]
        assert entry["receipt_wav"]["sha256"] == engine_sha, shot  # default onset rule, pinned
        assert entry["trim"]["onset"]["differs_from_naive"] is True and len(entry["trim"]["onset"]["skipped_bursts"]) == 1
        wav = read_wav(run["out"] / entry["editorial"]["path"])
        legacy = hashlib.sha256(wav_bytes(wav.rate, wav.channels, 2, trim_pcm(wav, trim_bounds(wav, naive)))).hexdigest()
        assert legacy == run["docs"]["trim_v002"][shot]["sha256"], shot
        assert entry["trim"]["onset"]["naive_first_speech_sample"] == round(run["docs"]["trim_v002"][shot]["voiced_start_s"] * 48_000)
