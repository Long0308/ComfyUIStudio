"""``jjv audio mix --remux``: mux(picture, final mix) with the video stream COPIED, and prove it.

The proof is the video PACKET stream: ``ffmpeg -map 0:v:0 -c copy -f framemd5`` lists one md5 per packet
with its timestamps; the payload column and the timing columns of the picture and of the muxed film must be
identical, otherwise the output is deleted and the mux is ``Refused`` (nothing was re-encoded, or it fails
here).  Only the audio track changes; a picture that already carries audio loses it (pictures are silent).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Callable

from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _run(command: list[str], runner: Runner, what: str) -> "subprocess.CompletedProcess[str]":
    try:
        done = runner(command, capture_output=True, text=True, timeout=1800, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"cannot run {what}: {error}") from error
    if done.returncode != 0:
        raise Uncertain(f"{what} failed ({done.returncode}): {done.stderr.strip()[-400:]}")
    return done


def video_packets(ffmpeg: str, video: Path, runner: Runner = subprocess.run) -> dict:
    """Payload and timing hashes of the first video stream's packets, without decoding."""
    done = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(video), "-map", "0:v:0",
                 "-c", "copy", "-f", "framemd5", "-"], runner, "ffmpeg framemd5")
    payload, timing, count = hashlib.sha256(), hashlib.sha256(), 0
    for line in done.stdout.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = [f.strip() for f in line.split(",")]
        if len(fields) < 6:
            raise Uncertain(f"unexpected framemd5 line: {line!r}")
        payload.update(fields[-1].encode("ascii"))
        timing.update(",".join(fields[:-1]).encode("ascii"))
        count += 1
    if count == 0:
        raise Refused(f"{video}: no video packets")
    return {"packets": count, "payload_sha256": payload.hexdigest(), "timing_sha256": timing.hexdigest()}


def probe_streams(ffprobe: str, path: Path, runner: Runner = subprocess.run) -> dict:
    done = _run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], runner, "ffprobe")
    try:
        return json.loads(done.stdout)
    except ValueError as error:
        raise Uncertain(f"ffprobe returned non-JSON for {path}") from error


def _duration(probe: dict, kind: str) -> float | None:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == kind and stream.get("duration") not in (None, "N/A"):
            return float(stream["duration"])
    return None


def mux(ffmpeg: str, ffprobe: str, picture: Path, mix_wav: Path, out: Path, remux_cfg: dict, fps: int,
        runner: Runner = subprocess.run) -> dict:
    """Write ``out`` (write-once) = picture video stream copy + the mix as the only audio; verify; return the record."""
    picture, out = Path(picture), Path(out)
    if out.exists():
        raise Refused(f"refusing to overwrite {out}")
    before = video_packets(ffmpeg, picture, runner)
    pic_probe = probe_streams(ffprobe, picture, runner)
    video_s, audio_s = _duration(pic_probe, "video"), read_duration(mix_wav)
    if video_s is not None and audio_s - video_s > 1.0 / fps:
        raise Refused(f"the mix is {audio_s:.3f} s but the picture {video_s:.3f} s: the audio would outrun the picture")
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(f".{out.stem}.{uuid.uuid4().hex}.tmp{out.suffix}")
    try:
        _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-i", str(picture), "-i", str(mix_wav),
              "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", remux_cfg["audio_codec"],
              "-b:a", remux_cfg["audio_bitrate"], "-movflags", "+faststart", str(temporary)], runner, "ffmpeg mux")
        after = video_packets(ffmpeg, temporary, runner)
        if after != before:
            raise Refused(f"the video packet stream changed by the mux ({before} -> {after}); output removed")
        out_probe = probe_streams(ffprobe, temporary, runner)
        kinds = [s.get("codec_type") for s in out_probe.get("streams", [])]
        if kinds.count("video") != 1 or kinds.count("audio") != 1:
            raise Refused(f"the muxed film must hold exactly one video and one audio stream, found {kinds}")
        try:
            os.link(temporary, out)
        except FileExistsError as error:
            raise Refused(f"refusing to overwrite {out}") from error
    finally:
        temporary.unlink(missing_ok=True)
    video = next(s for s in out_probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in out_probe["streams"] if s["codec_type"] == "audio")
    return {"picture": {"path": picture.name, "sha256": sha256_file(picture), "video_packets": before,
                        "duration_s": video_s},
            "output": {"path": out.name, "sha256": sha256_file(out), "video_packets": after,
                       "video_codec": video.get("codec_name"), "audio_codec": audio.get("codec_name"),
                       "audio_duration_s": _duration(out_probe, "audio"), "video_duration_s": _duration(out_probe, "video")},
            "video_untouched": True}


def read_duration(wav: Path) -> float:
    from ..voice.wavio import read_wav
    return read_wav(wav).duration_s
