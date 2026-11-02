"""SFX opt-in, the dialogue bus trim in a real mix run, and the vocal-free gate of a music bed (T-E43)."""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from audio_fixtures import RATE, Rig, audio_world, hand_built_review, recipe_of, song_wav, tone, wav_bytes, write_tone
from fake_comfy import FakeComfy
from test_audio_mix_run import episode, make_args, run  # noqa: F401  (episode is a fixture)
from test_audio_music import planned

from engine.audio import jobs, mix, mixcli, music, vocalgate
from engine.core.errors import Refused
from engine.seedvr2.seam_media import find_ffmpeg
from engine.voice.wavio import read_wav

GATE = {"limit_db": -35.0, "vocals_file": "vocals.wav", "timeout_s": 5.0}


def fake_separator(vocal_amplitude: float, *, code: int = 0, files: int = 1, rate: int = RATE):
    """A runner standing in for the external separator: writes ``vocals.wav`` (a tone) into {out_dir}."""
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        out_dir = Path(argv[argv.index("--out") + 1])
        for index in range(files if code == 0 else 0):
            target = out_dir / (f"sub{index}" if files > 1 else ".") / "vocals.wav"
            target.parent.mkdir(parents=True, exist_ok=True)
            data = wav_bytes(tone(2.0, vocal_amplitude, 440.0, rate), rate) if vocal_amplitude else wav_bytes(np.zeros((rate, 2)), rate)
            target.write_bytes(data)
        return subprocess.CompletedProcess(argv, code, "", "boom" if code else "")
    runner.calls = calls
    return runner


def gate() -> vocalgate.VocalGate:
    return vocalgate.VocalGate(("separate", "--in", "{input}", "--out", "{out_dir}"), "vocals.wav", -35.0, 5.0, "test")


# ---- SFX are opt-in ------------------------------------------------------------------------------------
def test_sfx_inputs_without_the_opt_in_are_refused_and_the_default_mix_has_a_silent_sfx_stem(episode, tmp_path) -> None:  # noqa: F811
    config, root, review, music_wav, _ = episode
    stem = root / "ambience.wav"
    write_tone(stem, 20.0, 0.2, 120.0)
    with pytest.raises(Refused, match="OFF by default"):
        run(config, make_args(tmp_path, review, music_wav, sfx_stem=str(stem), dry_run=True))
    summary, code = run(config, make_args(tmp_path, review, music_wav))
    receipt = json.loads((tmp_path / "mix" / mix.RECEIPT_FILE).read_text("utf-8"))
    assert receipt["sfx_enabled"] is False and receipt["sfx"]["enabled"] is False
    assert not np.any(np.frombuffer(read_wav(tmp_path / "mix" / mix.STEMS["sfx"]).pcm, dtype="<i2"))


def test_the_opt_in_flag_lets_an_sfx_stem_in(episode, tmp_path) -> None:  # noqa: F811
    config, root, review, music_wav, _ = episode
    stem = root / "ambience.wav"
    write_tone(stem, 20.0, 0.05, 120.0)
    summary, _ = run(config, make_args(tmp_path, review, music_wav, sfx_stem=str(stem), with_sfx=True))
    receipt = json.loads((tmp_path / "mix" / mix.RECEIPT_FILE).read_text("utf-8"))
    assert receipt["sfx_enabled"] is True and np.any(np.frombuffer(read_wav(tmp_path / "mix" / mix.STEMS["sfx"]).pcm, dtype="<i2"))


def test_an_episode_can_opt_in_through_its_audio_block(episode) -> None:  # noqa: F811
    config, *_ = episode
    recipe = {"sfx": {"default_enabled": False}}
    assert mixcli.sfx_enabled(config, recipe, False) is False and mixcli.sfx_enabled(config, recipe, True) is True
    opted = dataclasses.replace(config, episode={**config.episode, "audio": {"sfx": {"enabled": True}}})
    assert mixcli.sfx_enabled(opted, recipe, False) is True


# ---- dialogue bus trim in a real run -------------------------------------------------------------------
def test_loud_speech_is_trimmed_on_the_bus_only_and_the_dialogue_stem_stays_exact(tmp_path) -> None:
    config, _ = audio_world(tmp_path)
    root = Path(config.episode_root)
    doc = hand_built_review(root, total_frames=480, lines=(("S01_A", 30, 2.0, 0.22), ("S01_B", 150, 2.0, 0.22)),
                            cards=(("Alpha", 300, 3.0, 0.22), ("Beta", 390, 3.0, 0.22)))
    review = root / "review-config.json"
    review.write_text(json.dumps(doc), encoding="utf-8")
    music_wav = root / "music.wav"
    write_tone(music_wav, 6.0, 0.4, 180.0)
    summary, code = run(config, make_args(tmp_path, review, music_wav))
    receipt = json.loads((tmp_path / "mix" / mix.RECEIPT_FILE).read_text("utf-8"))
    buses = receipt["speech_buses"]
    assert set(buses) == {"dialogue", "vocabulary"} and all(b["mode"] == "solve" and -3.0 <= b["gain_db"] <= 3.0 for b in buses.values())
    trim = buses["dialogue"]["gain_db"]
    assert trim < 0.0 and buses["dialogue"]["min_db"] == -3.0, buses
    assert receipt["dialogue_exact"] and max(receipt["bed_steps_db"]) <= receipt["bed_step_limit_db"] + 1e-6
    stem = np.frombuffer(read_wav(tmp_path / "mix" / mix.STEMS["dialogue"]).pcm, dtype="<i2").reshape(-1, 2)
    bound = read_wav(root / "audio" / "S01_A.wav")
    assert np.array_equal(stem[30 * 1600:30 * 1600 + bound.frames], np.frombuffer(bound.pcm, dtype="<i2").reshape(-1, 2))
    final = np.frombuffer(read_wav(tmp_path / "mix" / mix.STEMS["final"]).pcm, dtype="<i2").reshape(-1, 2).astype(np.float64)
    beds = (np.frombuffer(read_wav(tmp_path / "mix" / mix.STEMS["music"]).pcm, dtype="<i2").reshape(-1, 2)
            + np.frombuffer(read_wav(tmp_path / "mix" / mix.STEMS["sfx"]).pcm, dtype="<i2").reshape(-1, 2)).astype(np.float64)
    speech = slice(30 * 1600, 30 * 1600 + bound.frames)
    loud = np.abs(stem[speech]) > 4000
    ratio = ((final - beds)[speech][loud] / stem[speech][loud])  # S01_A is a dialogue WAV: its class bus gain
    assert ratio.min() == pytest.approx(10 ** (trim / 20), abs=3e-3) and ratio.max() == pytest.approx(10 ** (trim / 20), abs=3e-3)
    assert code == (0 if summary["verdict"] == "PASS" else 1)


# ---- vocal-free gate -----------------------------------------------------------------------------------
def test_the_separator_command_comes_from_the_cli_or_the_machine_config_and_needs_the_input_placeholder() -> None:
    machine = {"audio": {"vocal_gate": {"command": ["demucs", "{input}", "-o", "{out_dir}"]}}}
    assert vocalgate.resolve(machine, GATE, None).command[0] == "demucs" and vocalgate.resolve(machine, GATE, None).source.startswith("machine")
    from_cli = vocalgate.resolve({}, GATE, json.dumps(["sep", "{input}", "{out_dir}"]))
    assert from_cli.source == "cli" and from_cli.limit_db == -35.0 and from_cli.vocals_file == "vocals.wav"
    assert vocalgate.resolve({}, GATE, None) is None
    with pytest.raises(Refused, match="placeholder"):
        vocalgate.resolve({}, GATE, '["sep", "x"]')
    with pytest.raises(Refused, match="JSON list"):
        vocalgate.resolve({}, GATE, "not json")


def test_a_quiet_vocal_stem_passes_a_loud_one_fails_and_the_numbers_are_recorded(tmp_path) -> None:
    bed = tmp_path / "bed.wav"
    write_tone(bed, 2.0, 0.3, 262.0)
    ok = vocalgate.run(gate(), bed, tmp_path / "o1", fake_separator(0.002))
    assert ok["status"] == "PASS" and ok["vocals_relative_db"] == pytest.approx(-43.5, abs=0.3) and ok["limit_db"] == -35.0
    assert ok["vocals"]["sha256"] and ok["command"][2].endswith("bed.wav") and ok["bed_rms_dbfs"] > ok["vocals_rms_dbfs"]
    bad = vocalgate.run(gate(), bed, tmp_path / "o2", fake_separator(0.1))
    assert bad["status"] == "FAIL" and bad["vocals_relative_db"] == pytest.approx(-9.5, abs=0.3)
    silent = vocalgate.run(gate(), bed, tmp_path / "o3", fake_separator(0.0))
    assert silent["status"] == "PASS" and silent["vocals_relative_db"] <= -90


@pytest.mark.parametrize("runner,why", [(fake_separator(0.01, code=3), "exited 3"), (fake_separator(0.01, files=2), "found 2"),
                                        (fake_separator(0.01, rate=44100), "differs from the bed")])
def test_a_separator_that_fails_or_leaves_nothing_usable_is_an_error_never_a_pass(tmp_path, runner, why) -> None:
    bed = tmp_path / "bed.wav"
    write_tone(bed, 2.0, 0.3, 262.0)
    result = vocalgate.run(gate(), bed, tmp_path / "o", runner)
    assert result["status"] == "ERROR" and why in result["reason"]


def test_finalize_runs_the_gate_per_bed_and_the_stem_is_the_first_take_that_passes(tmp_path) -> None:
    config, skill = audio_world(tmp_path)
    recipe = recipe_of(skill, "audio/music-yue2-int8-v001", "audio-music")
    out, plan = planned((config, skill, recipe), tmp_path, takes=2)
    with FakeComfy() as fake:
        rig = Rig(tmp_path, fake, recipe, skill)
        rig.serve(lambda prompt: song_wav(40.0))
        jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        quiet, loud = fake_separator(0.001), fake_separator(0.2)

        def by_take(argv, **kwargs):
            return (quiet if "t02" in argv[argv.index("--out") + 1] else loud)(argv, **kwargs)
        receipt = music.finalize(out, plan, recipe, output_root=rig.settings.output_dir, ffmpeg=find_ffmpeg(), rate=RATE,
                                 vocal_gate=gate(), vocal_runner=by_take)
    assert [t["vocal_gate"]["status"] for t in receipt["takes"]] == ["FAIL", "PASS"]
    assert receipt["stem"]["take"] == "music-c01-t02" and receipt["stem"]["picked_by"] == "first take that passed the vocal gate"
    assert receipt["stem"]["vocal_gate"]["status"] == "PASS" and receipt["status"] == "CANDIDATE_PENDING_LISTENING"
    assert (out / "vocal-gate" / "music-c01-t02" / "vocals.wav").is_file()


def test_no_separator_means_not_run_and_all_failing_takes_mean_a_failed_status(tmp_path) -> None:
    config, skill = audio_world(tmp_path)
    recipe = recipe_of(skill, "audio/music-yue2-int8-v001", "audio-music")
    out, plan = planned((config, skill, recipe), tmp_path)
    with FakeComfy() as fake:
        rig = Rig(tmp_path, fake, recipe, skill)
        rig.serve(lambda prompt: song_wav(40.0))
        jobs.run_all(rig.context(out), plan, rig.data, rig.root)
        none = music.finalize(out, plan, recipe, output_root=rig.settings.output_dir, ffmpeg=find_ffmpeg(), rate=RATE)
        assert none["stem"]["vocal_gate"]["status"] == "NOT_RUN" and none["status"] == "VOCAL_GATE_NOT_RUN"
        assert "no separator command" in none["stem"]["vocal_gate"]["reason"]
    (out / music.FINALIZE_FILE).unlink()
    receipt = music.finalize(out, plan, recipe, output_root=rig.settings.output_dir, ffmpeg=find_ffmpeg(), rate=RATE,
                             vocal_gate=gate(), vocal_runner=fake_separator(0.2))
    assert receipt["status"] == "VOCAL_GATE_FAIL" and receipt["stem"]["picked_by"] == "first take"


def music_receipt(tmp_path: Path, status: str) -> Path:
    stem = tmp_path / "bed.wav"
    sha = write_tone(stem, 6.0, 0.4, 180.0)
    path = tmp_path / "music-finalize.json"
    path.write_text(json.dumps({"stem": {"path": "bed.wav", "sha256": sha, "vocal_gate": {"status": status}}}), encoding="utf-8")
    return path


@pytest.mark.parametrize("status", ["NOT_RUN", "FAIL", "ERROR"])
def test_the_mix_refuses_a_music_receipt_whose_vocal_gate_is_not_pass_unless_overridden(episode, tmp_path, status) -> None:  # noqa: F811
    config, root, review, music_wav, _ = episode
    receipt = music_receipt(tmp_path, status)
    with pytest.raises(Refused, match="vocal-free gate"):
        run(config, make_args(tmp_path, review, None, music_wav=None, music_receipt=str(receipt), dry_run=True))
    summary, code = run(config, make_args(tmp_path, review, None, music_wav=None, music_receipt=str(receipt), dry_run=True,
                                          allow_ungated_music=True))
    assert code == 0 and summary["music"]["vocal_gate"] == status


def test_the_mix_takes_a_passing_music_receipt(episode, tmp_path) -> None:  # noqa: F811
    config, root, review, music_wav, _ = episode
    summary, code = run(config, make_args(tmp_path, review, None, music_wav=None, music_receipt=str(music_receipt(tmp_path, "PASS")),
                                          dry_run=True))
    assert code == 0 and summary["music"]["vocal_gate"] == "PASS" and summary["music"]["source"] == "receipt"


def test_the_gate_uses_lufs_when_ffmpeg_is_given_and_a_loud_one_second_window_fails_it(tmp_path) -> None:
    bed = tmp_path / "bed.wav"
    write_tone(bed, 6.0, 0.3, 262.0)
    ok = vocalgate.run(gate(), bed, tmp_path / "o1", fake_separator(0.002), find_ffmpeg())
    assert ok["status"] == "PASS" and ok["metric"] == "lufs" and ok["vocals_relative_db"] <= -35.0 and ok["bed_lufs"] > ok["vocals_lufs"]
    assert ok["vocals_worst_1s_window_dbfs"] < -40.0 and ok["window_limit_dbfs"] == -40.0

    def burst(argv, **kwargs):  # a vocal stem that is silent except for one loud second
        out_dir = Path(argv[argv.index("--out") + 1])
        audio = np.zeros((6 * RATE, 2))
        audio[2 * RATE:3 * RATE] = tone(1.0, 0.02, 440.0)
        (out_dir / "vocals.wav").write_bytes(wav_bytes(audio))
        return subprocess.CompletedProcess(argv, 0, "", "")

    loose = vocalgate.VocalGate(gate().command, "vocals.wav", 0.0, 5.0, "test", -40.0)    # relative limit out of the way
    result = vocalgate.run(loose, bed, tmp_path / "o2", burst, find_ffmpeg())
    assert result["status"] == "FAIL" and result["vocals_worst_1s_window_dbfs"] > -40.0 and result["vocals_relative_db"] <= 0.0
