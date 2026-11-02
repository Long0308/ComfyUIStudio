"""ffmpeg/ffprobe I/O of ``jjv qa review`` (CPU only, no network).  numpy is imported lazily.

Frame numbers are GLOBAL film frames; ``origin`` is the global frame number of the first frame of the
file (0 for a whole film, the cut-in frame for a short clip), so a test can run the gates on a clip.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from ..core.errors import Uncertain
from ..seedvr2.seam_media import ffmpeg_flags
from ..media.probe import VideoInfo, probe_video

MAX_RANGES_PER_CALL = 400


def numpy_module():
    try:
        import numpy  # noqa: PLC0415 - optional dependency, imported on demand
    except ImportError as error:
        raise Uncertain("qa review needs numpy (pip install numpy)") from error
    return numpy


def find_ffprobe(ffmpeg: str) -> str:
    sibling = Path(ffmpeg).with_name("ffprobe.exe" if str(ffmpeg).lower().endswith(".exe") else "ffprobe")
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("ffprobe")
    if found:
        return found
    raise Uncertain("ffprobe not found next to ffmpeg or on PATH")


def _run(command: list[str]) -> "subprocess.CompletedProcess[bytes]":
    try:
        return subprocess.run(command, capture_output=True, creationflags=ffmpeg_flags(), check=False)
    except OSError as error:
        raise Uncertain(f"cannot run {command[0]}: {error}") from error


def probe(video: Path, ffprobe: str) -> VideoInfo:
    return probe_video(video, ffprobe=ffprobe, count_packets=True)


def probe_durations(video: Path, ffprobe: str) -> dict:
    """``{"has_audio": bool, "audio_s": float|None, "video_s": float|None}`` (no decoding)."""
    result = _run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(video)])
    if result.returncode != 0:
        raise Uncertain(f"ffprobe failed for {video.name}: {result.stderr.decode(errors='replace')[:200]}")
    streams = json.loads(result.stdout.decode()).get("streams", [])

    def duration(kind: str) -> float | None:
        for stream in streams:
            if stream.get("codec_type") == kind:
                try:
                    return float(stream["duration"])
                except (KeyError, ValueError):
                    return None
        return None
    return {"has_audio": any(s.get("codec_type") == "audio" for s in streams),
            "audio_s": duration("audio"), "video_s": duration("video")}


def decode_gray(video: Path, ffmpeg: str, width: int, height: int) -> "numpy.ndarray":
    """Every frame as 8-bit gray, area-scaled to ``width`` x ``height``: array ``(frames, height, width)``."""
    np = numpy_module()
    result = _run([ffmpeg, "-v", "error", "-i", str(video), "-an", "-vf",
                   f"scale={width}:{height}:flags=area,format=gray", "-f", "rawvideo", "-"])
    size = width * height
    if result.returncode != 0 or not result.stdout or len(result.stdout) % size:
        raise Uncertain(f"cannot decode {video.name}: {result.stderr.decode(errors='replace')[:200]}")
    return np.frombuffer(result.stdout, np.uint8).reshape(-1, height, width)


def _ranges(indices: Iterable[int]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for i in sorted(set(indices)):
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [(a, b) for a, b in out]


def extract_frames(video: Path, ffmpeg: str, indices: Iterable[int], width: int, height: int,
                   origin: int = 0, native: tuple[int, int] | None = None) -> dict[int, "numpy.ndarray"]:
    """``{global frame: RGB array (height, width, 3)}``; a frame the file does not hold is absent.

    ``native`` = (w, h) of the file: when it equals (width, height) no scaling is applied."""
    np = numpy_module()
    wanted = [i - origin for i in set(indices) if i - origin >= 0]
    frames: dict[int, "numpy.ndarray"] = {}
    ranges = _ranges(wanted)
    scale = "" if native == (width, height) else f",scale={width}:{height}:flags=area"
    for offset in range(0, len(ranges), MAX_RANGES_PER_CALL):
        part = ranges[offset:offset + MAX_RANGES_PER_CALL]
        select = "+".join(f"between(n,{a},{b})" for a, b in part)
        result = _run([ffmpeg, "-v", "error", "-i", str(video), "-an", "-vf", f"select='{select}'{scale}",
                       "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
        order = [n for a, b in part for n in range(a, b + 1)]
        size = width * height * 3
        count = len(result.stdout) // size
        if result.returncode != 0 or len(result.stdout) % size:
            raise Uncertain(f"cannot extract frames from {video.name}: {result.stderr.decode(errors='replace')[:200]}")
        data = np.frombuffer(result.stdout, np.uint8).reshape(-1, height, width, 3)
        for n, frame in zip(order[:count], data):  # frames past the end of the file are simply not returned
            frames[n + origin] = frame
    return frames


def write_png(path: Path, rgb: "numpy.ndarray", ffmpeg: str) -> None:
    """Encode an RGB array as PNG with ffmpeg (no PIL dependency)."""
    height, width = rgb.shape[:2]
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-i", "-",
             "-frames:v", "1", str(path)], input=rgb.tobytes(), capture_output=True, creationflags=ffmpeg_flags())
    except OSError as error:
        raise Uncertain(f"cannot run ffmpeg to write {path.name}: {error}") from error
    if result.returncode != 0:
        raise Uncertain(f"cannot write {path.name}: {result.stderr.decode(errors='replace')[:200]}")


_LUFS = re.compile(r"I:\s+(-?\d+(?:\.\d+)?|-inf)\s+LUFS")
_PEAK = re.compile(r"Peak:\s+(-?\d+(?:\.\d+)?|-inf)\s+dBFS")


def ebur128(source: Path, ffmpeg: str, start_s: float, duration_s: float) -> dict:
    """Integrated loudness (LUFS) and true peak (dBTP) of one slice of the file's first audio stream."""
    result = _run([ffmpeg, "-hide_banner", "-nostats", "-ss", f"{start_s:.6f}", "-t", f"{duration_s:.6f}",
                   "-i", str(source), "-vn", "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"])
    text = result.stderr.decode(errors="replace")
    summary = text.rsplit("Summary:", 1)[-1]
    lufs, peak = _LUFS.search(summary), _PEAK.search(summary)
    if result.returncode != 0 or not lufs or not peak:
        raise Uncertain(f"ebur128 failed for {source.name} [{start_s:.2f}s +{duration_s:.2f}s]: {text[-200:]}")
    return {"lufs": float(lufs.group(1)), "true_peak_dbtp": float(peak.group(1))}
