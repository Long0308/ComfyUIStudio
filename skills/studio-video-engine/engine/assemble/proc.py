"""Process helpers shared by the assemble modules (ffmpeg/ffprobe runner, media probe, mean volume)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence

from ..core.errors import Failed
from .edl import refuse

Runner = Callable[..., subprocess.CompletedProcess]


def run_cmd(command: Sequence[Any], runner: Runner = subprocess.run, cwd: Path | None = None,
            check: bool = True) -> subprocess.CompletedProcess:
    done = runner([str(part) for part in command], cwd=cwd, capture_output=True, text=True,
                  encoding="utf-8", errors="replace")
    if check and done.returncode != 0:
        raise Failed(f"command failed ({done.returncode}): {' '.join(str(c) for c in command)[:300]}\n"
                     f"{(done.stderr or '')[-1500:]}")
    return done


def probe_media(path: Path, ffprobe: str = "ffprobe", runner: Runner = subprocess.run) -> dict:
    """Packet count / fps / size / audio presence (no decoding)."""
    done = run_cmd([ffprobe, "-v", "error", "-count_packets", "-show_entries",
                    "stream=codec_type,width,height,r_frame_rate,nb_read_packets,duration", "-of", "json", path], runner)
    streams = json.loads(done.stdout).get("streams", [])
    video = next((stream for stream in streams if stream["codec_type"] == "video"), None)
    audio = next((stream for stream in streams if stream["codec_type"] == "audio"), None)
    if video is None and audio is None:
        refuse("EDL_SOURCE_UNREADABLE", f"{path} has no audio/video stream")
    info: dict[str, Any] = {"has_audio": audio is not None}
    if video is not None:
        num, den = (int(part) for part in video["r_frame_rate"].split("/"))
        info.update(frames=int(video["nb_read_packets"]), fps=num / den,
                    width=int(video["width"]), height=int(video["height"]))
    return info


def volume_mean_db(path: Path, ffmpeg: str, runner: Runner, seconds: float | None = None) -> float:
    command = [ffmpeg, "-hide_banner", "-nostdin"]
    command += ["-t", f"{seconds}"] if seconds else []
    stderr = run_cmd(command + ["-i", path, "-af", "volumedetect", "-f", "null", "-"], runner).stderr
    match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", stderr)
    return float(match.group(1)) if match else -60.0
