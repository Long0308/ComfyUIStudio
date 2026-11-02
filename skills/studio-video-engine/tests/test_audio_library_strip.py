"""The vocal step and registration: singing bed -> gate FAIL -> no_vocals -> re-gate PASS -> library; rule v2; residue (no GPU)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from audio_fixtures import RATE, Rig, audio_world, recipe_of, song_wav, tone, wav_bytes, write_tone
from fake_comfy import FakeComfy
from test_audio_library_support import (BRIEF, SCHEMA, bed_row, demucs, gate, make_library, registry_bytes, separator,
                                        standard_rows, strip_settings)
from test_audio_music import TIMELINE

from engine.audio import jobs, library, music, musicpick, musicpick_adopt, musicpick_gen, vocalgate, vocalstrip
from engine.core.errors import Refused
from engine.core.io import read_json, write_json_once
from engine.seedvr2.seam_media import find_ffmpeg
from engine.voice.wavio import read_wav

SPEC = read_json(Path(__file__).resolve().parents[1] / "recipes" / "audio" / "music-pick-v001.json")["vocal_step"]
PREFIX = "NHAC-V3-"


def ffmpeg() -> str:
    try:
        return find_ffmpeg()
    except Exception:
        pytest.skip("ffmpeg not available")


def quiet_if_stripped(source: Path) -> float:
    return 0.0005 if "novocals" in source.name else 0.2


class World:
    """A planned + generated (fake ComfyUI) YuE2 take, finalized with a gate runner; ``adopt`` is then called by the test."""

    def __init__(self, tmp_path: Path, gate_runner, *, with_gate: bool = True, song_seconds: float = 40.0) -> None:
        self.tmp = tmp_path
        self.config, self.skill = audio_world(tmp_path)
        self.recipe = recipe_of(self.skill, "audio/music-yue2-int8-v001", "audio-music")
        self.out = tmp_path / "music-v001"
        self.plan = music.build_plan(self.config, self.recipe, "cli", out=self.out, timeline=TIMELINE, brief=BRIEF, brief_sources={},
                                     evidence=None, takes=1, seed=None, write=True)
        write_json_once(self.out / music.PLAN_FILE, self.plan, mode="ascii")
        self.lib = make_library(tmp_path, standard_rows(tmp_path / "lib"))
        with FakeComfy() as fake:
            rig = Rig(tmp_path, fake, self.recipe, self.skill)
            rig.serve(lambda prompt: song_wav(song_seconds))
            jobs.run_all(rig.context(self.out), self.plan, rig.data, rig.root)
            self.finalized = music.finalize(self.out, self.plan, self.recipe, output_root=rig.settings.output_dir,
                                            ffmpeg=find_ffmpeg(), rate=RATE, vocal_gate=gate() if with_gate else None,
                                            vocal_runner=gate_runner)
        self.gate_runner = gate_runner

    def adopt(self, *, strip_runner=None, vocal_runner=None, **over) -> dict:
        args = dict(out=self.out, plan=self.plan, recipe=self.recipe, finalized=self.finalized, lib_dir=self.lib, film="05-next",
                    domain_id="jenniejoy_cartoon_3d", spec=SPEC, gate=gate(), settings=strip_settings(find_ffmpeg()),
                    ffmpeg=find_ffmpeg(), strip_runner=strip_runner or demucs(20.0), vocal_runner=vocal_runner or self.gate_runner,
                    id_prefix=PREFIX, registry_schema=SCHEMA, energy="gentle")
        args.update(over)
        return musicpick_adopt.adopt(**args)


def test_a_singing_bed_fails_the_gate_then_no_vocals_is_looped_regated_and_registered(tmp_path) -> None:
    world = World(tmp_path, separator(quiet_if_stripped))
    assert world.finalized["stem"]["vocal_gate"]["status"] == "FAIL" and world.finalized["status"] == "VOCAL_GATE_FAIL"
    before = registry_bytes(world.lib)
    fake_demucs = demucs(20.0)
    receipt = world.adopt(strip_runner=fake_demucs)
    assert receipt["status"] == "BED_REGISTERED" and receipt["bed_id"] == "NHAC-V3-1"
    assert receipt["first_gate"]["status"] == "FAIL" and receipt["final_gate"]["status"] == "PASS"
    assert receipt["final_gate"]["rule"] == "v2" and receipt["final_gate"]["windows_over_limit"] == 0
    assert any("demucs" in call and "--two-stems" in call for call in fake_demucs.calls)
    strip = receipt["strip"]
    free, voiced = strip["residue"]["residue_vocal_free_db"], strip["residue"]["residue_voiced_db_mean"]
    assert strip["residue"]["windows_vocal_free"] >= 15 and free["max"] <= -100.0 and -30.0 < voiced < 0.0
    assert strip["loop_extend"]["loop"] and strip["bed"]["duration_s"] >= world.plan["bed_target_s"]
    # the registry: one new row with every number, the film in its used_in, a backup of the previous bytes
    document, _ = library.load_registry(world.lib, SCHEMA)
    row = next(b for b in document["beds"] if b["id"] == "NHAC-V3-1")
    assert row["generator"] == "yue2-demucs" and row["status"] == "approved_vocal_free" and row["used_in"][0]["film"] == "05-next"
    assert row["vocal_gate"]["pass"] is True and row["vocal_gate"]["rule"].startswith("v2") and row["vocal_gate"]["windows_over_-40dBFS"] == 0
    assert row["vocal_gate"]["vocal_minus_bed_rms_db"] <= -35.0 and row["strip"]["residue"]["windows_voiced"] > 0
    assert row["duration_s"] >= 83.0 and row["brief"]["bpm"] == 100 and row["loudness"]["true_peak_dbfs"] <= -0.95
    assert library.check_file(world.lib, row, rate=RATE) == [] and document["revision"] == 1
    assert Path(receipt["registry"]["backup"]).read_bytes() == before
    assert receipt["stem"]["sha256"] == row["sha256"] and receipt["stem"]["vocal_gate"]["status"] == "PASS"
    # a second adopt of the same folder is refused (write-once receipt) and writes nothing
    with pytest.raises(Refused, match="already adopted"):
        world.adopt()
    assert json.loads(registry_bytes(world.lib))["revision"] == 1
    # the new bed is now a library bed: it is picked again for the same episode (stable) and refused for the next one
    again = musicpick.pick(read_json(Path(world.skill / "recipes" / "audio" / "music-pick-v001.json")), document, lib_dir=world.lib,
                           brief=BRIEF, evidence=None, target_s=83.0, film="05-next", domain_id="jenniejoy_cartoon_3d")
    assert again["bed_id"] == "NHAC-V3-1"


def test_a_bed_that_still_sings_after_the_strip_is_not_registered(tmp_path) -> None:
    world = World(tmp_path, separator(lambda source: 0.2))
    before = registry_bytes(world.lib)
    receipt = world.adopt()
    assert receipt["status"] == "NO_VOCALS_GATE_FAIL" and receipt["registered"] is None
    assert receipt["strip"]["regate"]["status"] == "FAIL" and registry_bytes(world.lib) == before
    assert not list(library.beds_dir(world.lib).glob("*.bak-*")) and not list(library.beds_dir(world.lib).glob("NHAC-V3-*"))
    assert (world.out / musicpick_adopt.ADOPT_FILE).is_file()


def test_a_take_that_passes_the_gate_raw_is_registered_without_running_demucs(tmp_path) -> None:
    world = World(tmp_path, separator(lambda source: 0.0005))
    assert world.finalized["stem"]["vocal_gate"]["status"] == "PASS"

    def never(argv, **kwargs):
        raise AssertionError("Demucs must not run for a take that passed")
    receipt = world.adopt(strip_runner=never)
    document, _ = library.load_registry(world.lib, SCHEMA)
    row = next(b for b in document["beds"] if b["id"] == "NHAC-V3-1")
    assert receipt["strip"] is None and row["generator"] == "yue2" and row["strip"] is None
    assert receipt["stem"]["picked_by"].endswith("(raw take passed the gate)")


def test_an_unknown_vocal_state_never_enters_the_library(tmp_path) -> None:
    world = World(tmp_path, separator(lambda source: 0.0005), with_gate=False)
    assert world.finalized["stem"]["vocal_gate"]["status"] == "NOT_RUN"
    before = registry_bytes(world.lib)
    with pytest.raises(Refused, match="NOT_RUN"):
        world.adopt()
    assert registry_bytes(world.lib) == before and not (world.out / musicpick_adopt.ADOPT_FILE).exists()


def test_demucs_failures_are_refused_with_the_reason(tmp_path) -> None:
    world = World(tmp_path, separator(quiet_if_stripped))
    with pytest.raises(Refused, match="Demucs exited 3"):
        world.adopt(strip_runner=demucs(code=3))
    with pytest.raises(Refused, match="unknown take|not in the finalize receipt"):
        world.adopt(take_id="nope")


def test_demucs_44k_stems_are_resampled_to_the_bed_rate(tmp_path) -> None:
    ff = ffmpeg()
    source = tmp_path / "song.wav"
    write_tone(source, 6.0, 0.3, 262.0)
    result = vocalstrip.separate_two_stems(source, tmp_path / "stems", strip_settings(ff), demucs(2.0, rate=44100))
    assert result["rate"] == RATE and {s["demucs_rate"] for s in result["stems"].values()} == {44100}
    for name in vocalstrip.STEMS:
        wav = read_wav(tmp_path / "stems" / name)
        assert wav.rate == RATE and wav.channels == 2 and abs(wav.duration_s - 6.0) < 0.05
    with pytest.raises(Refused, match="exactly 1"):
        vocalstrip.separate_two_stems(source, tmp_path / "empty", strip_settings(ff), lambda argv, **k: __import__("subprocess").CompletedProcess(argv, 0, "", ""))


def test_the_interpreter_comes_from_the_flag_or_the_gate_command_and_never_from_nowhere() -> None:
    assert vocalstrip.settings_from(SPEC, None, ("py-venv", "wrapper.py", "{input}"), "ff").python == "py-venv"
    assert vocalstrip.settings_from(SPEC, "other-py", ("py-venv",), "ff").python == "other-py"
    with pytest.raises(Refused, match="no Demucs interpreter"):
        vocalstrip.settings_from(SPEC, None, None, "ff")


def test_residue_is_minus_120_where_the_stems_are_exact_and_reports_the_voiced_windows() -> None:
    song = tone(10.0, 0.3, 262.0, RATE).astype(np.float32)
    vocals = np.zeros_like(song)
    vocals[5 * RATE:] = tone(5.0, 0.1, 880.0, RATE)[: 5 * RATE]
    result = vocalstrip.residue(song + vocals, song, vocals, RATE, SPEC)
    assert result["windows_vocal_free"] == 5 and result["windows_voiced"] == 5
    assert result["residue_vocal_free_db"]["max"] == -120.0 or result["residue_vocal_free_db"]["max"] < -90.0
    assert -12.0 < result["residue_voiced_db_mean"] < -8.0  # 0.1 vs 0.3 sine is about -9.5 dB
    broken = vocalstrip.residue(song + vocals, song * 0.9, vocals, RATE, SPEC)  # the stem lost 10 % of the music: about -20 dB
    assert -21.0 < broken["residue_vocal_free_db"]["mean"] < -19.0


def test_the_peak_trim_only_lowers_and_records_the_gain(tmp_path) -> None:
    ff = ffmpeg()
    hot = tmp_path / "hot.wav"
    write_tone(hot, 8.0, 0.99, 262.0)
    result = musicpick_adopt.trimmed_bed(hot, tmp_path, "trim-48k.wav", ff)
    assert result["gain_applied_db"] < -0.5 and result["loudness"]["true_peak_dbfs"] <= -0.9
    assert result["before_gain"]["true_peak_dbfs"] > result["loudness"]["true_peak_dbfs"]
    quiet = tmp_path / "quiet.wav"
    sha = write_tone(quiet, 8.0, 0.1, 262.0)
    kept = musicpick_adopt.trimmed_bed(quiet, tmp_path, "kept-48k.wav", ff)
    assert kept["gain_applied_db"] == 0.0 and kept["sha256"] == sha  # untouched bytes


def test_rule_v2_passes_a_sparse_vocal_stem_that_the_lufs_rule_fails(tmp_path) -> None:
    ff = ffmpeg()
    bed = tmp_path / "bed.wav"
    write_tone(bed, 20.0, 0.3, 262.0)

    def sparse(argv, **kwargs):  # a vocal stem that is silent except for 0.5 s at -43 dBFS
        out_dir = Path(argv[argv.index("--out") + 1])
        audio = np.zeros((20 * RATE, 2))
        audio[3 * RATE:3 * RATE + RATE // 2] = tone(0.5, 0.01, 440.0)
        (out_dir / "vocals.wav").write_bytes(wav_bytes(audio))
        return __import__("subprocess").CompletedProcess(argv, 0, "", "")
    v2 = vocalgate.run(gate(), bed, tmp_path / "o2", sparse, ff)
    v1 = vocalgate.run(vocalgate.VocalGate(gate().command, "vocals.wav", -35.0, 5.0, "test", -40.0, "v1"), bed, tmp_path / "o1", sparse, ff)
    assert v2["status"] == "PASS" and v2["metric"] == "rms" and v2["vocals_relative_db"] <= -35.0
    assert v2["vocals_relative_lufs_db"] > -35.0 and v1["status"] == "FAIL" and v1["metric"] == "lufs"
    assert v2["windows_over_limit"] == 0 and vocalgate.resolve({"audio": {"vocal_gate": {"command": ["x", "{input}"]}}},
                                                                {"vocals_file": "vocals.wav", "limit_db": -35}, None).rule == "v2"
    with pytest.raises(Refused, match="rule-v2"):
        musicpick_adopt.gate_numbers(v1)
    assert musicpick_adopt.gate_numbers(v2)["pass"] is True


def test_an_acestep_plan_runs_through_the_guarded_path_and_its_clean_take_is_registered(tmp_path) -> None:
    config, skill = audio_world(tmp_path)
    base = recipe_of(skill, "audio/music-yue2-int8-v001", "audio-music")
    pick = musicpick.load_pick_recipe(config)
    brief = {"bpm": 104.0, "key": "D major", "instruments": "ukulele, glockenspiel"}
    out = tmp_path / "music-ace"
    plan, recipe = musicpick_gen.build_generation_plan(config, pick, base, "acestep", out=out, timeline=TIMELINE, brief=brief,
                                                       brief_sources={}, evidence=None, takes=1, seed=None, write=True)
    write_json_once(out / music.PLAN_FILE, plan, mode="ascii")
    graph = read_json(out / plan["jobs"][0]["graph_file"])
    inputs = graph["4"]["inputs"]
    assert recipe.recipe_id == "audio/music-pick-v001#acestep" and plan["recipe"]["sha256"] == recipe.sha256
    assert inputs["bpm"] == 104 and inputs["keyscale"] == "D major" and inputs["lyrics"] == "[Instrumental]"
    assert inputs["tags"].startswith("instrumental, no vocals,") and "ukulele, glockenspiel" in inputs["tags"]
    assert inputs["duration"] == 83.0 == graph["6"]["inputs"]["seconds"] and inputs["seed"] == graph["8"]["inputs"]["seed"] == 20261201
    assert plan["bed_target_s"] == 83.0 and musicpick_gen.rebuild(pick, base, plan).sha256 == recipe.sha256
    lib = make_library(tmp_path, standard_rows(tmp_path / "lib"))
    with FakeComfy() as fake:
        rig = Rig(tmp_path, fake, recipe, skill)

        def render(payload: dict, prompt_id: str) -> dict:
            prefix = payload["prompt"]["10"]["inputs"]["filename_prefix"]
            subfolder, name = prefix.rsplit("/", 1)
            target = rig.settings.output_dir / subfolder / f"{name}_00001_.flac"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(song_wav(83.0, bpm=104.0))
            return {"10": {"audio": [{"filename": target.name, "subfolder": subfolder, "type": "output"}]}}
        fake.on_post, fake.auto_complete = render, True
        run = jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        assert run["completed"] == 1 and fake.posts[0]["prompt"]["4"]["class_type"] == "TextEncodeAceStepAudio1.5"
        finalized = music.finalize(out, plan, recipe, output_root=rig.settings.output_dir, ffmpeg=find_ffmpeg(), rate=RATE,
                                   vocal_gate=gate(), vocal_runner=separator(lambda source: 0.0005))
    assert finalized["takes"][0]["loop_extend"]["loop"] is False and finalized["takes"][0]["bed"]["duration_s"] == 83.0
    receipt = musicpick_adopt.adopt(out=out, plan=plan, recipe=recipe, finalized=finalized, lib_dir=lib, film="05-next",
                                    domain_id="jenniejoy_cartoon_3d", spec=SPEC, gate=gate(), settings=strip_settings(),
                                    ffmpeg=find_ffmpeg(), id_prefix=PREFIX, registry_schema=SCHEMA, energy="gentle")
    document, _ = library.load_registry(lib, SCHEMA)
    row = next(b for b in document["beds"] if b["id"] == "NHAC-V3-1")
    assert row["generator"] == "acestep" and row["brief"]["key"] == "D major" and receipt["status"] == "BED_REGISTERED"
