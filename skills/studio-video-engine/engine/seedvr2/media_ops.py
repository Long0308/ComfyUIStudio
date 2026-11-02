"""Media checks and the core trim for SeedVR2 chunks (invariant I6).

Every number comes from the resolved recipe geometry (:class:`Geometry`): processing size,
final crop, fps, padding alignment, core encoding.  Nothing here knows a film or a resolution.
The trim is ``trim=start_frame=offset:end_frame=offset+frames`` then a ``crop`` at the recipe
offsets: never a resize.  Cores are written to a temp file, verified, then hard-linked in place.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable

from ..core.errors import EngineError, Failed, Refused
from ..media.probe import VideoInfo, probe_video

Probe = Callable[..., VideoInfo]
Runner = Callable[[list], "subprocess.CompletedProcess[str]"]

# recipe geometry.core_encoding -> ffmpeg video-encode arguments (unknown names are refused)
CORE_ENCODINGS: dict[str, list[str]] = {
    "libx264-crf0-yuv420p": ["-c:v", "libx264", "-preset", "medium", "-crf", "0",
                             "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
}


@dataclass(frozen=True)
class Geometry:
    fps: Fraction
    fps_text: str
    processing_width: int
    processing_height: int
    final_width: int
    final_height: int
    crop_left: int
    crop_top: int
    padding_alignment: int
    core_encoding: str

    @classmethod
    def from_recipe(cls, recipe: dict) -> "Geometry":
        g = recipe["geometry"]
        if g["core_encoding"] not in CORE_ENCODINGS:
            raise Refused(f"recipe core_encoding {g['core_encoding']!r} has no ffmpeg mapping")
        return cls(fps=Fraction(g["fps"]), fps_text=g["fps"],
                   processing_width=g["processing_width"], processing_height=g["processing_height"],
                   final_width=g["final_width"], final_height=g["final_height"],
                   crop_left=g["final_crop_left"], crop_top=g["final_crop_top"],
                   padding_alignment=g["padding_alignment"], core_encoding=g["core_encoding"])

    @property
    def crop_filter(self) -> str:
        return f"crop={self.final_width}:{self.final_height}:{self.crop_left}:{self.crop_top}"


def core_trim_filter(offset: int, frames: int, geometry: Geometry) -> str:
    if offset < 0 or frames < 1:
        raise Refused("core trim offset/frames are invalid")
    return (f"trim=start_frame={offset}:end_frame={offset + frames},"
            f"setpts=PTS-STARTPTS,{geometry.crop_filter}")


def verify_video(path: Path, *, frames: int, width: int, height: int, fps: Fraction,
                 probe: Probe = probe_video, error: type[EngineError] = Refused) -> VideoInfo:
    """Exact frame count, size and fps, else ``error`` (Refused before a POST, Failed after)."""
    info = probe(path)
    if info.frames is None:
        info = probe(path, count_packets=True)
    if info.frames != frames:
        raise error(f"frame count mismatch for {path.name}: expected {frames}, found {info.frames}")
    if (info.width, info.height) != (width, height):
        raise error(f"size mismatch for {path.name}: expected {width}x{height}, "
                    f"found {info.width}x{info.height}")
    if info.fps != fps:
        raise error(f"fps mismatch for {path.name}: expected {fps}, found {info.fps}")
    return info


def default_runner(command: list) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(command, capture_output=True, text=True, check=False)


def run_command(runner: Runner, command: list, label: str) -> None:
    try:
        result = runner(command)
    except OSError as error:
        raise Failed(f"{label}: cannot run {command[0]}: {error}") from error
    if result.returncode != 0:
        raise Failed(f"{label} failed (exit {result.returncode}): {(result.stderr or '').strip()[-300:]}")


def trim_core(raw: Path, destination: Path, *, offset: int, frames: int, geometry: Geometry,
              runner: Runner = default_runner, probe: Probe = probe_video,
              ffmpeg: str = "ffmpeg") -> Path:
    """Cut core ``[offset, offset+frames)`` of ``raw``, crop (no resize), verify, link in place."""
    destination = Path(destination)
    if destination.exists():
        raise Refused(f"refusing to overwrite core output: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.tmp{destination.suffix}")
    command = [ffmpeg, "-v", "error", "-i", str(raw), "-map", "0:v:0",
               "-vf", core_trim_filter(offset, frames, geometry), "-fps_mode", "passthrough", "-an",
               *CORE_ENCODINGS[geometry.core_encoding], str(temporary)]
    check = dict(frames=frames, width=geometry.final_width, height=geometry.final_height,
                 fps=geometry.fps, probe=probe, error=Failed)
    try:
        run_command(runner, command, f"core trim of {raw.name}")
        verify_video(temporary, **check)
        try:
            os.link(temporary, destination)
        except FileExistsError as error:
            raise Refused(f"refusing to overwrite concurrent core output: {destination}") from error
        verify_video(destination, **check)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
