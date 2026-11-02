from __future__ import annotations

import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from engine.core.errors import Uncertain
from engine.media.probe import parse_probe, probe_video


def _runner(stdout: str = "", returncode: int = 0, stderr: str = ""):
    calls: list[list[str]] = []

    def run(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _payload(**stream: object) -> str:
    base = {"width": 864, "height": 480, "avg_frame_rate": "24/1", "nb_frames": "17"}
    base.update(stream)
    return json.dumps({"streams": [base]})


def test_parse_probe_reads_frames_dims_fps() -> None:
    info = parse_probe(json.loads(_payload()))
    assert (info.frames, info.width, info.height, info.fps) == (17, 864, 480, Fraction(24))


def test_ntsc_fps_is_exact() -> None:
    info = parse_probe(json.loads(_payload(avg_frame_rate="30000/1001")))
    assert info.fps == Fraction(30000, 1001)


def test_falls_back_to_r_frame_rate_and_packet_count() -> None:
    raw = json.loads(
        _payload(avg_frame_rate="0/0", r_frame_rate="25/1", nb_frames="N/A", nb_read_packets="9")
    )
    info = parse_probe(raw)
    assert info.fps == Fraction(25) and info.frames == 9


def test_frames_unknown_is_none_not_guessed() -> None:
    assert parse_probe(json.loads(_payload(nb_frames="N/A"))).frames is None


@pytest.mark.parametrize(
    "payload",
    [{}, {"streams": []}, {"streams": [{"width": 0, "height": 5, "avg_frame_rate": "24/1"}]},
     {"streams": [{"width": 4, "height": 5}]}],
)
def test_parse_probe_rejects_unusable(payload: dict) -> None:
    with pytest.raises(Uncertain):
        parse_probe(payload)


def test_probe_video_builds_command_and_parses(tmp_path: Path) -> None:
    run = _runner(_payload())
    info = probe_video(tmp_path / "x.mp4", ffprobe="FFP", runner=run, count_packets=True)
    command = run.calls[0]
    assert command[0] == "FFP" and "-count_packets" in command
    assert command[-1] == str(tmp_path / "x.mp4") and info.frames == 17


def test_probe_video_failure_modes(tmp_path: Path) -> None:
    with pytest.raises(Uncertain):
        probe_video(tmp_path / "x.mp4", runner=_runner("", 1, "no such file"))
    with pytest.raises(Uncertain):
        probe_video(tmp_path / "x.mp4", runner=_runner("not json"))

    def missing(command, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("ffprobe")

    with pytest.raises(Uncertain):
        probe_video(tmp_path / "x.mp4", runner=missing)


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg absent")
def test_real_ffprobe_on_tiny_lavfi_clip(tmp_path: Path) -> None:
    clip = tmp_path / "tiny.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x48:r=24",
         "-frames:v", "5", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )
    info = probe_video(clip, count_packets=True)
    assert (info.frames, info.width, info.height, info.fps) == (5, 64, 48, Fraction(24))
