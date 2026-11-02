"""Tiny ffprobe wrapper: frame count, dimensions, fps of the first video stream."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable

from ..core.errors import Uncertain

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class VideoInfo:
    frames: int | None
    width: int
    height: int
    fps: Fraction


def _fraction(text: object) -> Fraction | None:
    try:
        value = Fraction(str(text))
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def _whole(text: object) -> int | None:
    try:
        number = int(str(text))
    except ValueError:
        return None
    return number if number >= 0 else None


def parse_probe(payload: dict, label: str = "video") -> VideoInfo:
    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        raise Uncertain(f"{label}: ffprobe reported no video stream")
    stream = streams[0]
    width, height = _whole(stream.get("width")), _whole(stream.get("height"))
    if not width or not height:
        raise Uncertain(f"{label}: ffprobe reported no usable dimensions")
    fps = _fraction(stream.get("avg_frame_rate")) or _fraction(
        stream.get("r_frame_rate")
    )
    if fps is None:
        raise Uncertain(f"{label}: ffprobe reported no usable frame rate")
    frames = _whole(stream.get("nb_frames"))
    if frames is None:
        frames = _whole(stream.get("nb_read_packets"))
    return VideoInfo(frames=frames, width=width, height=height, fps=fps)


def probe_video(
    path: Path,
    *,
    ffprobe: str = "ffprobe",
    count_packets: bool = False,
    runner: Runner = subprocess.run,
) -> VideoInfo:
    """Probe without decoding.  ``count_packets`` reads packet headers (no
    decode) to fill ``frames`` when the container has no ``nb_frames``."""
    command = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,nb_read_packets",
        "-of", "json",
    ]
    if count_packets:
        command.insert(1, "-count_packets")
    command.append(str(path))
    try:
        result = runner(command, capture_output=True, text=True, check=False)
    except OSError as error:
        raise Uncertain(f"cannot run ffprobe for {path}: {error}") from error
    if result.returncode != 0:
        raise Uncertain(f"ffprobe failed for {path}: {result.stderr.strip()[:300]}")
    try:
        payload = json.loads(result.stdout)
    except ValueError as error:
        raise Uncertain(f"ffprobe output is not JSON for {path}") from error
    return parse_probe(payload, str(path))
