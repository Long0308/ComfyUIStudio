"""ffmpeg process I/O for seam blending (CPU only, no GPU, no network).

numpy and OpenCV are optional, lazily imported dependencies: a missing module is an ``Uncertain``
(exit 2) with an explicit message.  Nothing here knows a film, episode or machine path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

from ..core.errors import Refused, Uncertain

Emitter = Any


def find_ffmpeg(explicit: str | None = None) -> str:
    """An explicit path, ``$FFMPEG`` or PATH; no machine-specific default lives in the engine."""
    for candidate in (explicit, os.environ.get("FFMPEG"), shutil.which("ffmpeg")):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise Refused("ffmpeg not found (pass --ffmpeg or set FFMPEG)")


def ffmpeg_flags() -> int:
    """Windows BELOW_NORMAL_PRIORITY_CLASS for child processes; 0 elsewhere."""
    return 0x4000 if os.name == "nt" else 0


def _run(cmd: list[str]) -> "subprocess.CompletedProcess[bytes]":
    try:
        return subprocess.run(cmd, capture_output=True, creationflags=ffmpeg_flags())
    except OSError as error:
        raise Uncertain(f"cannot run {cmd[0]}: {error}") from error


def ffmpeg_version(ffmpeg: str) -> str:
    try:
        out = _run([ffmpeg, "-version"]).stdout.decode(errors="replace")
        return out.splitlines()[0] if out else "unknown"
    except Uncertain:
        return "unknown"


def require_numpy():
    try:
        import numpy  # noqa: PLC0415 - optional dependency, imported on demand
    except ImportError as error:
        raise Uncertain("seam blending needs numpy (pip install numpy); --dry-run does not") from error
    return numpy


def require_cv2():
    try:
        import cv2  # noqa: PLC0415 - optional dependency, imported on demand
    except ImportError as error:
        raise Uncertain("hf8 needs OpenCV (pip install opencv-python-headless); lin8/core do not") from error
    return cv2


def dependency_versions() -> dict:
    versions: dict[str, str | None] = {"numpy": None, "opencv": None}
    try:
        import numpy  # noqa: PLC0415
        versions["numpy"] = numpy.__version__
    except ImportError:
        pass
    try:
        import cv2  # noqa: PLC0415
        versions["opencv"] = cv2.__version__
    except ImportError:
        pass
    return versions


def planes_from_bytes(data: bytes, width: int, height: int):
    """yuv420p bytes -> (Y, U, V) arrays shaped (n, h, w)."""
    np = require_numpy()
    frame_size = width * height * 3 // 2
    count = len(data) // frame_size
    if count == 0 or len(data) != count * frame_size:
        raise Uncertain(f"decoded {len(data)} bytes is not a whole number of {width}x{height} "
                        "yuv420p frames")
    flat = np.frombuffer(data, np.uint8).reshape(count, frame_size)
    y_plane = flat[:, :width * height].reshape(count, height, width)
    u_plane = flat[:, width * height:width * height * 5 // 4].reshape(count, height // 2, width // 2)
    v_plane = flat[:, width * height * 5 // 4:].reshape(count, height // 2, width // 2)
    return y_plane, u_plane, v_plane


def decode_planes(ffmpeg: str, path: Path, vf: str | None, width: int, height: int,
                  threads: int = 4):
    """Decode one video to yuv420p planes (whole file in memory; used per chunk only)."""
    cmd = [ffmpeg, "-hide_banner", "-v", "error", "-threads", str(threads), "-i", str(path)]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-pix_fmt", "yuv420p", "-f", "rawvideo", "-"]
    result = _run(cmd)
    if result.returncode != 0:
        raise Uncertain(f"ffmpeg failed decoding {path.name}: "
                        f"{result.stderr.decode(errors='replace').strip()[-300:]}")
    return planes_from_bytes(result.stdout, width, height)


def iter_gray(ffmpeg: str, path: Path, vf: str | None, width: int, height: int,
              threads: int = 4) -> Iterator[Any]:
    """Stream gray frames (no full-shot buffer) for the motion metric."""
    np = require_numpy()
    cmd = [ffmpeg, "-hide_banner", "-v", "error", "-threads", str(threads), "-i", str(path)]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-pix_fmt", "gray", "-f", "rawvideo", "-"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=ffmpeg_flags())
    size = width * height
    try:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(size)
            if not chunk:
                break
            if len(chunk) != size:
                raise Uncertain(f"truncated gray frame from {path.name}: "
                                f"{len(chunk)} of {size} bytes")
            yield np.frombuffer(chunk, np.uint8).reshape(height, width)
        stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
        code = process.wait()
        if code != 0:
            raise Uncertain(f"ffmpeg failed decoding {path.name}: {stderr.strip()[-300:]}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


class Encoder:
    """Stream yuv420p frames into a lossless H.264 mp4 (same settings as the verified v001)."""

    def __init__(self, ffmpeg: str, path: Path, width: int, height: int, fps: str,
                 threads: int = 4) -> None:
        self.frames = 0
        # Colour tags go on the rawvideo INPUT and match the SeedVR2 cores (bt709 / sRGB transfer).
        # Given only as output options, ffmpeg 9 converts the pixels instead of tagging them
        # (error-db ffmpeg-output-colour-tags-convert-pixels).
        cmd = [ffmpeg, "-hide_banner", "-v", "error", "-y", "-threads", str(threads),
               "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{width}x{height}", "-r", str(fps),
               "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709",
               "-color_trc", "iec61966-2-1",
               "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "0",
               "-pix_fmt", "yuv420p", "-f", "mp4", str(path)]
        try:
            self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                            creationflags=ffmpeg_flags())
        except OSError as error:
            raise Uncertain(f"cannot start ffmpeg encoder: {error}") from error

    def write(self, planes) -> None:
        np = require_numpy()
        assert self.process.stdin is not None
        for plane in planes:
            self.process.stdin.write(np.ascontiguousarray(plane).tobytes())
        self.frames += 1

    def close(self) -> None:
        assert self.process.stdin is not None and self.process.stderr is not None
        self.process.stdin.close()
        stderr = self.process.stderr.read().decode(errors="replace")
        code = self.process.wait()
        if code != 0:
            raise Uncertain(f"ffmpeg encoder exited {code}: {stderr.strip()[-300:]}")

    def abort(self) -> None:
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except OSError:
            pass
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()


def emit_default(message: str) -> None:
    print(message, file=sys.stderr)
