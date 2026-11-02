"""Cheap framing measurement on the SOURCE clips: one frame decoded from each side of a boundary.

The number is the Q3 one (``engine.qa.gates.q3_flash``): normalised correlation of 4x4 block means of a gray
frame area-scaled to the recipe's analysis size, here between the LAST editorial frame of the outgoing clip and
the FIRST frame of the incoming clip.  CPU only (ffmpeg + numpy); nothing is rendered or written.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..config.loader import SKILL_ROOT
from ..core.errors import Refused, Uncertain
from ..core.io import read_json
from ..media.probe import probe_video
from ..qa.gates.q3_flash import _small, ncc as ncc_of
from ..qa.review_media import numpy_module
from ..qa.scope import require_scoped
from ..seedvr2.seam_media import ffmpeg_flags

QA_RECIPE = SKILL_ROOT / "recipes" / "qa" / "review-gates-v001.json"


def q3_numbers() -> dict[str, Any]:
    """``same_framing_ncc_min`` and the analysis size, straight from the QA recipe (never re-typed here)."""
    q3 = read_json(QA_RECIPE)["q3_flash"]
    return {"same_framing_ncc_min": q3["same_framing_ncc_min"],
            "analysis": [q3["analysis_width"], q3["analysis_height"]]}


def find_ffmpeg(explicit: str | None = None) -> str:
    found = explicit or shutil.which("ffmpeg")
    if not found:
        raise Uncertain("ffmpeg not found on PATH (pass --ffmpeg)")
    return str(found)


def probe_frames(clip: Path) -> int:
    """Native frame count of a clip (packet count; no decoding)."""
    info = probe_video(clip, count_packets=True)
    if info.frames is None:
        raise Refused(f"cannot count frames of {clip}")
    return info.frames


def gray_frame(clip: Path, index: int, ffmpeg: str, width: int, height: int) -> Any | None:
    """Frame ``index`` as an 8-bit gray ``(height, width)`` array, or None when the clip does not hold it."""
    np = numpy_module()
    command = [ffmpeg, "-v", "error", "-i", str(clip), "-an", "-vf",
               f"select=eq(n\\,{index}),scale={width}:{height}:flags=area,format=gray",
               "-fps_mode", "passthrough", "-frames:v", "1", "-f", "rawvideo", "-"]
    try:
        result = subprocess.run(command, capture_output=True, creationflags=ffmpeg_flags(), check=False)
    except OSError as error:
        raise Uncertain(f"cannot run ffmpeg: {error}") from error
    if result.returncode != 0:
        raise Uncertain(f"cannot decode {clip.name}: {result.stderr.decode(errors='replace')[:200]}")
    if len(result.stdout) != width * height:
        return None
    return np.frombuffer(result.stdout, np.uint8).reshape(height, width)


def measure_pair(root: Path, outgoing: dict, incoming: dict, ffmpeg: str, analysis: list[int],
                 allow: tuple = ()) -> dict:
    """``{ncc, mae, from, to}`` for two shots.json shot rows; ``ncc`` is None (with ``why``) when a frame is missing."""
    np = numpy_module()
    width, height = analysis
    a_clip = require_scoped(root / outgoing["clip"]["path"], root, allow, "clip")
    b_clip = require_scoped(root / incoming["clip"]["path"], root, allow, "clip")
    a_index = outgoing["clip"]["frames"] - 1
    out = {"ncc": None, "mae": None, "why": None,
           "from": {"shot": outgoing["shot"], "clip": outgoing["clip"]["path"], "frame_index": a_index},
           "to": {"shot": incoming["shot"], "clip": incoming["clip"]["path"], "frame_index": 0}}
    if not a_clip.is_file() or not b_clip.is_file():
        out["why"] = f"clip not found: {(a_clip if not a_clip.is_file() else b_clip).name}"
        return out
    first, second = gray_frame(a_clip, a_index, ffmpeg, width, height), gray_frame(b_clip, 0, ffmpeg, width, height)
    if first is None or second is None:
        out["why"] = f"frame not in file ({outgoing['shot'] if first is None else incoming['shot']})"
        return out
    out["ncc"] = round(ncc_of(_small(first), _small(second)), 3)
    out["mae"] = round(float(np.abs(first.astype(np.float64) - second).mean()), 1)
    return out
