"""``jjv qa av``: whole runs with a fake decoder, real mp4 + CLI exit codes, scope and receipts."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from av_fixtures import (FPS, HAS_FFMPEG, SR, FakeFfmpeg, P, _jjv, _make_export, _mix_with, _noise,
                         _run, _world, _write_wav, np)
from engine.core.errors import Refused, Uncertain  # noqa: E402
from engine.qa import av  # noqa: E402


# ---- whole run with a fake decoder ----------------------------------------------------------


def test_run_av_passes_and_the_receipt_has_no_timestamp(tmp_path: Path) -> None:
    video, config, runner = _world(tmp_path)
    receipt = _run(tmp_path, config, video, runner)
    assert receipt["verdict"] == "PASS" and receipt["ok"] and receipt["wav_starts"][0]["lag_ms"] == 0.0
    assert _run(tmp_path, config, video, runner) == receipt  # deterministic: write_once stays idempotent
    assert not any("time" in key or "date" in key for key in receipt)


def test_run_av_fails_when_the_wav_is_too_late(tmp_path: Path) -> None:
    video, config, runner = _world(tmp_path, lag_samples=int(0.1 * SR))
    receipt = _run(tmp_path, config, video, runner)
    assert receipt["verdict"] == "FAIL" and receipt["wav_starts"][0]["lag_ms"] == pytest.approx(100.0, abs=0.1)


def test_run_av_fails_when_the_bound_hash_is_not_the_wav_on_disk(tmp_path: Path) -> None:
    video, config, runner = _world(tmp_path, bound_sha="0" * 64)
    assert _run(tmp_path, config, video, runner)["verdict"] == "FAIL"


def test_run_av_a_reference_without_a_window_compares_the_whole_overlap(tmp_path: Path) -> None:
    video, config, runner = _world(tmp_path)
    receipt = _run(tmp_path, config, video, runner, reference=video)
    pcm = receipt["pcm_identity"]
    assert pcm["ok"] and pcm["window_source"] == "full overlap" and pcm["seconds"] == 6.0


def test_run_av_reference_window_can_come_from_the_config_when_it_covers_the_overlap(tmp_path: Path) -> None:
    video, config, runner = _world(tmp_path)
    config["qa"] = {"av": {"reference_seconds": 6}}
    receipt = _run(tmp_path, config, video, runner, reference=video)
    assert receipt["pcm_identity"]["ok"] and receipt["pcm_identity"]["seconds"] == 6
    config["qa"] = {"av": {"reference_seconds": 3}}
    with pytest.raises(Refused, match="reference_seconds"):  # a shorter window could hide a later divergence
        _run(tmp_path, config, video, runner, reference=video)


def test_run_av_a_failing_pcm_identity_fails_the_verdict(tmp_path: Path) -> None:
    video, config, runner = _world(tmp_path)
    other = tmp_path / "ref.mp4"
    other.write_bytes(b"ref")
    runner.table[str(other.resolve())] = _noise(6.0, 123)
    receipt = _run(tmp_path, config, video, runner, reference=other, reference_seconds=3)
    assert receipt["verdict"] == "FAIL" and not receipt["pcm_identity"]["ok"]


def test_run_av_refuses_a_config_whose_fps_is_not_the_domain_fps(tmp_path: Path) -> None:
    video, config, runner = _world(tmp_path)
    config["fps"] = 24
    with pytest.raises(Refused):
        _run(tmp_path, config, video, runner)


def test_run_av_unreadable_inputs_are_uncertain_not_a_pass(tmp_path: Path) -> None:
    video, config, runner = _world(tmp_path)
    with pytest.raises(Uncertain):
        _run(tmp_path, config, tmp_path / "missing.mp4", runner)
    (tmp_path / "audio" / "a.wav").unlink()
    with pytest.raises(Uncertain):
        _run(tmp_path, config, video, runner)


def test_decode_failure_is_uncertain() -> None:
    with pytest.raises(Uncertain):
        av.decode_mono(Path("x.mp4"), runner=FakeFfmpeg({}))


# ---- real ffmpeg + CLI -------------------------------------------------------------------------
@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg absent")
@pytest.mark.parametrize("start_s, code", [(2.0, 0), (2.1, 1)])
def test_cli_qa_av_exit_codes_with_a_real_mp4(tmp_path: Path, capsys, start_s: float, code: int) -> None:
    wav = _noise(1.0, 21)
    wav_path = tmp_path / "w.wav"
    sha = _write_wav(wav_path, wav)
    export = _make_export(tmp_path, "export", wav, start_s)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"fps": 30, "wav_bindings": [
        {"name": "dlg A", "path": str(wav_path), "sha256": sha, "start_frame": 60}]}), encoding="utf-8")
    out = tmp_path / "receipt.json"
    status = _jjv().main(["qa", "av", "--episode", "04-milk-and-mom", "--video", str(export),
                          "--config", str(config), "--out", str(out), "--json",
                          "--allow-outside", str(tmp_path)])
    receipt = json.loads(capsys.readouterr().out)
    assert status == code and receipt["verdict"] == ("PASS" if code == 0 else "FAIL")
    assert json.loads(out.read_text("utf-8")) == receipt
    assert abs(receipt["wav_starts"][0]["lag_ms"] - (start_s - 2.0) * 1000) < 40


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg absent")
def test_cli_qa_av_pcm_identity_against_a_reference(tmp_path: Path, capsys) -> None:
    wav = _noise(1.0, 22)
    wav_path = tmp_path / "w.wav"
    sha = _write_wav(wav_path, wav)
    export = _make_export(tmp_path, "export", wav, 2.0)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"fps": 30, "wav_bindings": [
        {"name": "dlg A", "path": str(wav_path), "sha256": sha, "start_frame": 60}]}), encoding="utf-8")
    args = ["qa", "av", "--episode", "04-milk-and-mom", "--video", str(export), "--config", str(config),
            "--json", "--reference-seconds", "3", "--allow-outside", str(tmp_path)]
    # the episode's main film (84 s) is far longer than this 3 s window: identical PCM is only PASS_PARTIAL (exit 1)
    assert _jjv().main(args + ["--reference", str(export)]) == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["pcm_identity"]["max_abs"] == 0.0 and receipt["verdict"] == "PASS_PARTIAL" and receipt["partial"]
    other = _make_export(tmp_path, "other", _noise(1.0, 23), 2.0)
    assert _jjv().main(args + ["--reference", str(other)]) == 1


def test_cli_qa_av_a_missing_video_exits_2_and_never_writes_a_receipt(tmp_path: Path, capsys) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"wav_bindings": [{"name": "a", "path": "a.wav", "sha256": "a" * 64,
                                                    "start_frame": 0}]}), encoding="utf-8")
    out = tmp_path / "r.json"
    status = _jjv().main(["qa", "av", "--episode", "04-milk-and-mom", "--video", str(tmp_path / "no.mp4"),
                          "--config", str(config), "--out", str(out), "--json",
                          "--allow-outside", str(tmp_path)])
    assert status == 2 and not out.exists() and json.loads(capsys.readouterr().out)["ok"] is False


def test_cli_qa_av_receipt_is_write_once(tmp_path: Path, capsys) -> None:
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg absent")
    wav = _noise(1.0, 24)
    wav_path = tmp_path / "w.wav"
    sha = _write_wav(wav_path, wav)
    export = _make_export(tmp_path, "export", wav, 2.0)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"fps": 30, "wav_bindings": [
        {"name": "dlg A", "path": str(wav_path), "sha256": sha, "start_frame": 60}]}), encoding="utf-8")
    out = tmp_path / "receipt.json"
    out.write_text("{}", encoding="utf-8")
    args = ["qa", "av", "--episode", "04-milk-and-mom", "--video", str(export), "--config", str(config),
            "--out", str(out), "--json", "--allow-outside", str(tmp_path)]
    assert _jjv().main(args) == 1  # Refused: a different file already holds that path
    assert out.read_text("utf-8") == "{}"


# ---- scope, exit classes, silent run, no absolute paths ---------------------------------------------
def test_a_wav_or_video_outside_the_episode_root_is_refused_unless_allow_listed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    video, config, runner = _world(tmp_path)
    with pytest.raises(Refused, match="outside the episode root"):
        av.run_av(video=video, config=config, config_sha256="c" * 64, episode_root=root, fps=30.0, runner=runner)
    receipt = av.run_av(video=video, config={**config, "wav_bindings": [
        {**config["wav_bindings"][0], "path": str(tmp_path / "audio" / "a.wav")}]},
        config_sha256="c" * 64, episode_root=root, fps=30.0, runner=runner, allow_outside=[tmp_path])
    assert receipt["verdict"] == "PASS"


def test_a_dot_dot_path_cannot_escape_the_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    video, config, runner = _world(tmp_path)
    config["wav_bindings"][0]["path"] = "../audio/a.wav"
    with pytest.raises(Refused, match="outside the episode root"):
        av.run_av(video=video, config=config, config_sha256="c" * 64, episode_root=root, fps=30.0,
                  runner=runner, allow_outside=[])


def test_the_receipt_echoes_no_absolute_path(tmp_path: Path) -> None:
    video, config, runner = _world(tmp_path)
    text = json.dumps(_run(tmp_path, config, video, runner))
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "/") not in text
    receipt = _run(tmp_path, config, video, runner)
    assert receipt["video"]["path"] == "v.mp4" and receipt["wav_starts"][0]["wav"] == "audio/a.wav"


def test_run_av_a_declared_silent_wav_is_reported_with_a_caveat_and_never_as_located(tmp_path: Path) -> None:
    video, config, runner = _world(tmp_path)
    quiet = tmp_path / "audio" / "quiet.wav"
    sha = _write_wav(quiet, np.full(SR, 1e-5, dtype=np.float32))
    runner.table[str(quiet.resolve())] = np.full(SR, 1e-5, dtype=np.float32)
    config["wav_bindings"].append({"name": "dlg Q", "path": "audio/quiet.wav", "sha256": sha, "start_frame": 150,
                                   "expect_silent": {"start_frame": 150, "end_frame_exclusive": 180, "max_rms": 0.05}})
    receipt = _run(tmp_path, config, video, runner)
    row = receipt["wav_starts"][1]
    assert receipt["verdict"] == "PASS" and row["status"] == "silent-declared" and row["lag_ms"] is None
    assert receipt["unverifiable_silent_wavs"] == ["dlg Q"] and "unprovable by correlation" in receipt["caveats"][0]
    measured = row["expect_silent"]["export_rms"]
    assert measured > 0.005  # the export bed is really measured (noise RMS ~0.01), not an empty window
    config["wav_bindings"][1]["expect_silent"]["max_rms"] = measured / 2
    assert _run(tmp_path, config, video, runner)["verdict"] == "FAIL"  # the verdict depends on the bound
    config["wav_bindings"][1]["expect_silent"]["max_rms"] = 0.05
    del config["wav_bindings"][1]["expect_silent"]
    assert _run(tmp_path, config, video, runner)["verdict"] == "FAIL"  # undeclared silence fails


def test_run_av_a_binding_without_sha_is_refused_not_a_pass(tmp_path: Path) -> None:
    video, config, runner = _world(tmp_path)
    del config["wav_bindings"][0]["sha256"]
    with pytest.raises(Refused, match="no sha256"):
        _run(tmp_path, config, video, runner)


def test_cli_missing_episode_and_missing_ffmpeg_are_unreadable_inputs_exit_2(tmp_path: Path, capsys,
                                                                             monkeypatch) -> None:
    from engine.qa import cli as qa_cli
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"wav_bindings": [{"name": "a", "path": "a.wav", "sha256": "a" * 64,
                                                    "start_frame": 0}]}), encoding="utf-8")
    base = ["qa", "av", "--video", str(tmp_path / "v.mp4"), "--config", str(config), "--json",
            "--allow-outside", str(tmp_path)]
    assert _jjv().main(base + ["--episode", "no-such-episode"]) == 2
    capsys.readouterr()

    def no_ffmpeg(_explicit):
        raise Refused("ffmpeg not found (pass --ffmpeg or set FFMPEG)")

    monkeypatch.setattr(qa_cli, "find_ffmpeg", no_ffmpeg)
    assert _jjv().main(base + ["--episode", "04-milk-and-mom"]) == 2


def test_cli_a_config_that_is_not_valid_json_exits_2(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "c.json"
    bad.write_text("{not json", encoding="utf-8")
    assert _jjv().main(["qa", "av", "--episode", "04-milk-and-mom", "--video", str(tmp_path / "v.mp4"),
                        "--config", str(bad), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
