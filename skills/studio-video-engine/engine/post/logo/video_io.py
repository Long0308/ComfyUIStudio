"""Đọc/ghi video qua pipe ffmpeg, ffprobe và sha256. CPU only; đường dẫn ffmpeg/ffprobe do caller cấp (không hardcode)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from ...core.errors import Uncertain
from ...seedvr2.seam_media import ffmpeg_flags


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps_num: int
    fps_den: int
    nb_frames: int
    codec: str
    pix_fmt: str
    audio_codec: str | None
    color_primaries: str | None
    color_trc: str | None
    color_space: str | None
    color_range: str | None
    size_bytes: int

    @property
    def fps(self) -> float:
        return self.fps_num / self.fps_den

    def as_dict(self) -> dict:
        return {
            "width": self.width, "height": self.height,
            "r_frame_rate": f"{self.fps_num}/{self.fps_den}", "nb_frames": self.nb_frames,
            "codec": self.codec, "pix_fmt": self.pix_fmt, "audio_codec": self.audio_codec,
            "color_primaries": self.color_primaries, "color_trc": self.color_trc,
            "color_space": self.color_space, "color_range": self.color_range,
            "size_bytes": self.size_bytes,
        }


def _none_if_unknown(value: object) -> str | None:
    if value in (None, "", "unknown", "unspecified"):
        return None
    return str(value)


def _run(cmd: list[str], *, timeout: int = 1800) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, creationflags=ffmpeg_flags(), timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"cannot run {cmd[0]}: {error}") from error


def probe(path: Path, ffprobe: str) -> VideoInfo:
    """Thông số luồng video/audio bằng ffprobe; nb_frames đếm thật bằng -count_frames."""
    done = _run([ffprobe, "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)])
    if done.returncode:
        raise Uncertain(f"ffprobe failed on {path}: {done.stderr.decode('utf-8', 'replace')[-400:]}")
    try:
        data = json.loads(done.stdout.decode("utf-8", "replace"))
        video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
        if video is None:
            raise Uncertain(f"no video stream: {path}")
        audio = next((s for s in data["streams"] if s.get("codec_type") == "audio"), None)
        num, den = (int(v) for v in video["r_frame_rate"].split("/"))
        counted = video.get("nb_read_frames") or video.get("nb_frames")
        return VideoInfo(
            width=int(video["width"]), height=int(video["height"]), fps_num=num, fps_den=den,
            nb_frames=int(counted), codec=str(video["codec_name"]), pix_fmt=str(video.get("pix_fmt")),
            audio_codec=str(audio["codec_name"]) if audio else None,
            color_primaries=_none_if_unknown(video.get("color_primaries")),
            color_trc=_none_if_unknown(video.get("color_transfer")),
            color_space=_none_if_unknown(video.get("color_space")),
            color_range=_none_if_unknown(video.get("color_range")),
            size_bytes=int(data["format"]["size"]),
        )
    except (KeyError, ValueError, TypeError) as error:
        raise Uncertain(f"cannot read ffprobe output for {path}: {error}") from error


def iter_frames(path: Path, info: VideoInfo, ffmpeg: str, max_frames: int | None = None) -> Iterator[np.ndarray]:
    """Từng frame BGR uint8 (H,W,3) theo thứ tự, giải mã qua ffmpeg rawvideo; ``max_frames`` cắt bằng -frames:v."""
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-i", str(path), "-map", "0:v:0"]
    if max_frames is not None:
        cmd += ["-frames:v", str(int(max_frames))]
    cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    frame_bytes = info.width * info.height * 3
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=ffmpeg_flags())
    except OSError as error:
        raise Uncertain(f"cannot run {ffmpeg}: {error}") from error
    assert proc.stdout is not None
    try:
        while True:
            buf = bytearray()
            while len(buf) < frame_bytes:
                chunk = proc.stdout.read(frame_bytes - len(buf))
                if not chunk:
                    break
                buf.extend(chunk)
            if len(buf) < frame_bytes:
                if buf:
                    raise Uncertain(f"truncated frame from ffmpeg: {len(buf)}/{frame_bytes} bytes")
                break
            yield np.frombuffer(bytes(buf), dtype=np.uint8).reshape(info.height, info.width, 3)
    finally:
        proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.read()
        proc.wait()


def color_args(info: VideoInfo) -> list[str]:
    """Gắn lại tag màu của nguồn. Đo 31/10 (ffmpeg 9): cờ -color_* không vào VUI khi vào từ rawvideo,
    nên dùng filter setparams SAU format=yuv420p (đổi RGB→YUV xong mới gắn tag, không đổi cách quy đổi)."""
    params = []
    if info.color_primaries:
        params.append(f"color_primaries={info.color_primaries}")
    if info.color_trc:
        params.append(f"color_trc={info.color_trc}")
    if info.color_space:
        params.append(f"colorspace={info.color_space}")
    if info.color_range:
        params.append(f"range={info.color_range}")
    chain = "format=yuv420p" + (",setparams=" + ":".join(params) if params else "")
    return ["-vf", chain]


class FrameWriter:
    """Ghi frame BGR vào ffmpeg (libx264) và mux audio từ nguồn bằng stream copy. ``dst`` phải là file tạm mới."""

    def __init__(self, dst: Path, src_audio: Path, info: VideoInfo, crf: int, ffmpeg: str, preset: str = "slow") -> None:
        cmd = [ffmpeg, "-y", "-v", "error", "-nostdin",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{info.width}x{info.height}",
               "-r", f"{info.fps_num}/{info.fps_den}", "-i", "pipe:0"]
        maps = ["-map", "0:v:0"]
        if info.audio_codec:
            cmd += ["-i", str(src_audio)]
            maps += ["-map", "1:a:0", "-c:a", "copy"]
        cmd += maps + color_args(info) + ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]
        cmd += ["-movflags", "+faststart", str(dst)]
        self.cmd = cmd
        self.count = 0
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=ffmpeg_flags())
        except OSError as error:
            raise Uncertain(f"cannot run {ffmpeg}: {error}") from error

    def write(self, frame: np.ndarray) -> None:
        assert self.proc.stdin is not None
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("frame must be BGR uint8")
        self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        self.count += 1

    def close(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace") if self.proc.stderr else ""
        rc = self.proc.wait()
        if rc != 0:
            raise Uncertain(f"ffmpeg encode rc={rc}: {err.strip()[:800]}")


def compare_outside_roi(src: Path, dst: Path, info: VideoInfo, rois: dict[int, tuple[int, int, int, int]],
                        ffmpeg: str) -> dict:
    """MAD nguồn vs kết quả, tách trong/ngoài ROI, tại các frame đã chọn (ngoài ROI chỉ còn nhiễu nén)."""
    report: dict[int, dict] = {}
    last = max(rois) if rois else -1
    for idx, (a, b) in enumerate(zip(iter_frames(src, info, ffmpeg, last + 1), iter_frames(dst, info, ffmpeg, last + 1))):
        if idx not in rois:
            continue
        x0, y0, x1, y1 = rois[idx]
        diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).mean(axis=2)
        mask = np.zeros(diff.shape, dtype=bool)
        mask[y0:y1, x0:x1] = True
        report[idx] = {"roi_xyxy": [x0, y0, x1, y1],
                       "mad_inside_roi": round(float(diff[mask].mean()), 3),
                       "mad_outside_roi": round(float(diff[~mask].mean()), 3),
                       "max_outside_roi": int(diff[~mask].max())}
    return report


def ffmpeg_version(ffmpeg: str) -> str:
    out = _run([ffmpeg, "-version"], timeout=60).stdout.decode("utf-8", "replace")
    return out.splitlines()[0] if out else "unknown"
