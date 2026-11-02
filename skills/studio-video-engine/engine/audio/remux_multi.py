"""Multitrack mux: picture video COPY + N audio streams in the order the recipe declares (``remux.tracks``).

Each track names a stem (``final``/``dialogue``/``music``/``sfx``/``brand_voice``), a ``title`` (stream tag), a codec and
optionally ``default`` (disposition) and ``verify_exact``.  Proof after the mux: the video packet stream is unchanged, the
audio stream count equals the declared count, every stream is within one frame of the picture, and a lossless track decodes
to the same PCM as its input stem (sample-exact); a lossy track records the measured result instead (never claimed exact).
A recipe without ``remux.tracks`` never reaches this module (``remux.mux`` keeps the single-stream path).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
from pathlib import Path

from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file
from ..voice.wavio import read_wav
from .remux import Runner, _duration, _run, probe_streams, video_packets

LOSSLESS = ("flac", "alac") + tuple(f"pcm_{k}" for k in ("s16le", "s24le", "s32le", "f32le"))


def _decode_pcm(ffmpeg: str, path: Path, index: int, rate: int, runner: Runner) -> bytes:
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path), "-map", f"0:a:{index}",
               "-f", "s16le", "-acodec", "pcm_s16le", "-ar", str(rate), "-ac", "2", "-"]
    try:
        done = runner(command, capture_output=True, timeout=1800, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"cannot decode audio stream {index}: {error}") from error
    if done.returncode != 0:
        raise Uncertain(f"decoding audio stream {index} failed ({done.returncode})")
    return done.stdout


def _packet_times(ffmpeg: str, video: Path, runner: Runner) -> list[float]:
    """Packet pts (seconds) of the first video stream, from framemd5 with its ``#tb`` header."""
    done = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(video), "-map", "0:v:0",
                 "-c", "copy", "-f", "framemd5", "-"], runner, "ffmpeg framemd5")
    num, den, times = 1, 1, []
    for line in done.stdout.splitlines():
        if line.startswith("#tb"):
            num, den = (int(x) for x in line.split(":", 1)[1].strip().split("/"))
        elif line.strip() and not line.startswith("#"):
            times.append(int(line.split(",")[2]) * num / den)
    return times


def _same_video(ffmpeg: str, picture: Path, temporary: Path, before: dict, after: dict, runner: Runner) -> bool:
    """Payload and packet count must be identical; timing is identical, or (matroska keeps 1 ms ticks) within 1 ms."""
    if after == before:
        return True
    if (after["packets"], after["payload_sha256"]) != (before["packets"], before["payload_sha256"]):
        return False
    a, b = _packet_times(ffmpeg, picture, runner), _packet_times(ffmpeg, temporary, runner)
    offset = (b[0] - a[0]) if a and b else 0.0
    return len(a) == len(b) and all(abs((y - offset) - x) <= 0.001 for x, y in zip(a, b))


def _check_tracks(tracks: list[dict], stems: dict[str, Path]) -> None:
    if not tracks:
        raise Refused("remux.tracks is empty")
    for track in tracks:
        path = stems.get(track["stem"])
        if path is None or not Path(path).is_file():
            raise Refused(f"track {track.get('title')!r}: stem {track['stem']!r} is missing ({path})")
    if sum(1 for t in tracks if t.get("default")) != 1:
        raise Refused("exactly one remux track must be marked default")


def _build_command(ffmpeg: str, picture: Path, stems: dict[str, Path], tracks: list[dict], temporary: Path) -> list[str]:
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-i", str(picture)]
    for track in tracks:
        command += ["-i", str(stems[track["stem"]])]
    command += ["-map", "0:v:0", "-c:v", "copy"]
    for i, track in enumerate(tracks):
        command += ["-map", f"{i + 1}:a:0", f"-c:a:{i}", track["codec"]]
        if track.get("bitrate"):
            command += [f"-b:a:{i}", track["bitrate"]]
        command += [f"-metadata:s:a:{i}", f"title={track['title']}",
                    f"-metadata:s:a:{i}", f"language={track.get('language', 'und')}",
                    f"-disposition:a:{i}", "default" if track.get("default") else "0"]
    return command + ["-movflags", "+faststart", str(temporary)]


def _verify_track(ffmpeg: str, temporary: Path, i: int, track: dict, stream: dict, ref: Path, video_s: float | None,
                  fps: int, runner: Runner) -> dict:
    source = read_wav(ref)
    decoded = _decode_pcm(ffmpeg, temporary, i, source.rate, runner)
    seconds = len(decoded) / 4 / source.rate
    if video_s is not None and abs(seconds - video_s) > 1.0 / fps and seconds > video_s:
        raise Refused(f"audio stream {i} ({track['title']}) is {seconds:.3f} s, picture {video_s:.3f} s; output removed")
    lossless = track["codec"] in LOSSLESS
    digest = hashlib.sha256(decoded).hexdigest()
    exact = digest == hashlib.sha256(source.pcm).hexdigest()
    if track.get("verify_exact") and not exact:
        raise Refused(f"track {track['title']!r} ({track['codec']}) is not sample-exact to stem {track['stem']!r}; output removed"
                      + ("" if lossless else " (a lossy codec cannot be exact: use flac or pcm)"))
    return {"index": i, "stem": track["stem"], "title": stream.get("tags", {}).get("title"),
            "default": bool(stream.get("disposition", {}).get("default")), "codec": stream.get("codec_name"),
            "duration_s": round(seconds, 6), "stem_sha256": sha256_file(ref), "decoded_pcm_sha256": digest,
            "sample_exact": exact, "lossless_codec": lossless}


def mux_multitrack(ffmpeg: str, ffprobe: str, picture: Path, stems: dict[str, Path], out: Path, remux_cfg: dict, fps: int,
                   runner: Runner = subprocess.run) -> dict:
    """Write ``out`` (write-once) = picture video copy + one audio stream per ``remux_cfg['tracks']``; verify; return the record."""
    tracks = remux_cfg["tracks"]
    picture, out = Path(picture), Path(out)
    if out.exists():
        raise Refused(f"refusing to overwrite {out}")
    _check_tracks(tracks, stems)
    before = video_packets(ffmpeg, picture, runner)
    video_s = _duration(probe_streams(ffprobe, picture, runner), "video")
    for track in tracks:
        seconds = read_wav(Path(stems[track["stem"]])).duration_s
        if video_s is not None and seconds - video_s > 1.0 / fps:
            raise Refused(f"stem {track['stem']!r} is {seconds:.3f} s but the picture {video_s:.3f} s: "
                          "the audio would outrun the picture")
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(f".{out.stem}.{uuid.uuid4().hex}.tmp{out.suffix}")
    try:
        _run(_build_command(ffmpeg, picture, stems, tracks, temporary), runner, "ffmpeg multitrack mux")
        after = video_packets(ffmpeg, temporary, runner)
        if not _same_video(ffmpeg, picture, temporary, before, after, runner):
            raise Refused(f"the video packet stream changed by the mux ({before} -> {after}); output removed")
        probe = probe_streams(ffprobe, temporary, runner)
        audio = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
        if len(audio) != len(tracks):
            raise Refused(f"declared {len(tracks)} audio streams but the film holds {len(audio)}; output removed")
        rows = [_verify_track(ffmpeg, temporary, i, t, s, Path(stems[t["stem"]]), video_s, fps, runner)
                for i, (t, s) in enumerate(zip(tracks, audio))]
        try:
            os.link(temporary, out)
        except FileExistsError as error:
            raise Refused(f"refusing to overwrite {out}") from error
    finally:
        temporary.unlink(missing_ok=True)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    return {"picture": {"path": picture.name, "sha256": sha256_file(picture), "video_packets": before, "duration_s": video_s},
            "output": {"path": out.name, "sha256": sha256_file(out), "video_packets": after,
                       "video_codec": video.get("codec_name"), "audio_streams": rows,
                       "video_duration_s": _duration(probe, "video")},
            "video_untouched": True}
