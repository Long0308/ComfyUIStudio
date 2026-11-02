"""Frame-exact cut of a source sub-range (port of the v004 helper ``split_segment``) and framemd5 helpers.

The encode is the one every v004 segment used: ``trim=start_frame:end_frame,setpts=PTS-STARTPTS``,
passthrough timestamps, no audio, ``libx264 -preset medium -crf 0 -pix_fmt yuv420p +faststart``
(lossless, so the decoded frames equal the source frames).  A cut is written to a temp file, probed
for the exact frame count / size / fps, then hard-linked in place: it never overwrites.
"""

from __future__ import annotations

import os
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Callable

from ..core.errors import Failed, Refused
from ..media.probe import probe_video
from .media_ops import Probe, Runner, default_runner, run_command, verify_video

SEGMENT_ENCODE = ["-c:v", "libx264", "-preset", "medium", "-crf", "0", "-pix_fmt", "yuv420p",
                  "-movflags", "+faststart"]
SEGMENT_ENCODE_NAME = "libx264-preset-medium-crf0-yuv420p-faststart"


def trim_filter(start: int, end_exclusive: int) -> str:
    if start < 0 or end_exclusive <= start:
        raise Refused(f"invalid frame range [{start}, {end_exclusive})")
    return f"trim=start_frame={start}:end_frame={end_exclusive},setpts=PTS-STARTPTS"


def cut_command(source: Path, destination: Path, start: int, end_exclusive: int, *, ffmpeg: str = "ffmpeg",
                threads: int | None = None) -> list[str]:
    """The ffmpeg command of one cut (argument order identical to the v004 helper)."""
    return [ffmpeg, "-v", "error", *(["-threads", str(threads)] if threads else []), "-i", str(source),
            "-map", "0:v:0", "-vf", trim_filter(start, end_exclusive), "-fps_mode", "passthrough", "-an",
            *SEGMENT_ENCODE, str(destination)]


def cut_segment(source: Path, destination: Path, *, start: int, end_exclusive: int, fps: Fraction, width: int,
                height: int, runner: Runner = default_runner, probe: Probe = probe_video, ffmpeg: str = "ffmpeg",
                threads: int | None = None, check: Callable[[Path], None] | None = None) -> Path:
    """Cut source frames ``[start, end_exclusive)`` into ``destination`` (never overwritten).

    ``check`` runs on the finished temp file before it is linked in place: a raise leaves no segment."""
    destination = Path(destination)
    if destination.exists():
        raise Refused(f"refusing to overwrite segment: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.tmp{destination.suffix}")
    verify = dict(frames=end_exclusive - start, width=width, height=height, fps=fps, probe=probe, error=Failed)
    try:
        run_command(runner, cut_command(source, temporary, start, end_exclusive, ffmpeg=ffmpeg, threads=threads),
                    f"segment cut of {Path(source).name} [{start},{end_exclusive})")
        verify_video(temporary, **verify)
        if check is not None:
            check(temporary)
        try:
            os.link(temporary, destination)
        except FileExistsError as error:
            raise Refused(f"refusing to overwrite concurrent segment: {destination}") from error
        verify_video(destination, **verify)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def framemd5(path: Path, *, vf: str | None = None, runner: Runner = default_runner,
             ffmpeg: str = "ffmpeg") -> list[str]:
    """Per-frame md5 of the decoded video stream (optionally through the filter ``vf``)."""
    command = [ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v:0", *(["-vf", vf] if vf else []),
               "-fps_mode", "passthrough", "-f", "framemd5", "-"]
    try:
        result = runner(command)
    except OSError as error:
        raise Failed(f"framemd5: cannot run {ffmpeg}: {error}") from error
    if result.returncode != 0:
        raise Failed(f"framemd5 of {Path(path).name} failed (exit {result.returncode}): "
                     f"{(result.stderr or '').strip()[-300:]}")
    return [line.split(",")[-1].strip() for line in result.stdout.splitlines() if line and not line.startswith("#")]


def slice_md5(source: Path, start: int, end_exclusive: int, *, runner: Runner = default_runner,
              ffmpeg: str = "ffmpeg") -> list[str]:
    """Frame md5 of ``source[start:end)`` exactly as the segment encoder sees it (``format=yuv420p``)."""
    return framemd5(source, vf=f"{trim_filter(start, end_exclusive)},format=yuv420p", runner=runner, ffmpeg=ffmpeg)
