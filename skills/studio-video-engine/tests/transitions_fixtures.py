"""Fixtures of the transition-suggestion tests: tiny synthetic episodes with REAL mp4 clips (ffmpeg lavfi).

A clip is a static pattern, so what the framing measure sees is exactly what the test declares:
``GRAD_X`` / ``GRAD_Y`` are orthogonal gradients (ncc about 0), ``GRAD_MIX`` is 0.25 GRAD_X + 0.75 GRAD_Y
(ncc to GRAD_X about 0.32: the near-same band) and ``GRAD_X`` against itself is 1.0.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

GRAD_X = "X*255/W"
GRAD_Y = "Y*255/H"
GRAD_MIX = "0.25*X*255/W+0.75*Y*255/H"
DOMAIN = {"frame_rates": {"native_fps": 24, "delivery_fps": 30, "mapping": {"num": 5, "den": 4}}}
FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not on PATH")


def make_clip(path: Path, expr: str, frames: int, size: tuple[int, int] = (864, 480)) -> None:
    """A static ``frames``-frame 24 fps clip whose luma is ``expr`` (geq syntax)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=black:s={size[0]}x{size[1]}:r=24:d={frames / 24}", "-vf",
                    f"geq=lum='{expr}':cb=128:cr=128", "-frames:v", str(frames), "-c:v", "libx264", "-qp", "0",
                    "-pix_fmt", "yuv420p", str(path)], check=True)


def shot_row(name: str, frames: int, kind: str, clip: str, from_shot: str | None = None) -> dict:
    entry = {"kind": kind, "evidence": "test"}
    if from_shot:
        entry["from_shot"] = from_shot
    return {"shot": name, "logical_shot": name[:3], "speaker": "mother", "listener": "alice", "entry": entry,
            "clip": {"path": clip, "frames": frames}}


def episode(tmp: Path, intro_s: float = 3.0) -> SimpleNamespace:
    return SimpleNamespace(episode_root=str(tmp), domain=DOMAIN,
                           episode={"episode_id": "test-episode", "timeline": {"intro_s": intro_s}})


def build(tmp: Path, specs: list[tuple], tail: dict | None = None) -> tuple[SimpleNamespace, list[dict]]:
    """``specs`` = ``(shot, editorial frames, entry kind, luma expr)`` per shot, in order.  ``tail`` maps a shot to the
    number of EXTRA native frames its ``<shot>-native.mp4`` holds beyond the editorial cut."""
    shots, previous = [], None
    for name, frames, kind, expr in specs:
        clip = f"clips/{name}-editorial.mp4"
        make_clip(tmp / clip, expr, frames)
        if tail and name in tail:
            make_clip(tmp / f"clips/{name}-native.mp4", expr, frames + tail[name])
        shots.append(shot_row(name, frames, kind, clip, previous if kind == "carry" else None))
        previous = name
    return episode(tmp), shots


def declared(rows: list[dict]) -> dict:
    """A minimal declared boundaries document: ``{from_shot, to_shot, ...}`` rows only."""
    return {"boundaries": [{"class": "cut", "continuity": "unknown", "motivation": "declared", **row} for row in rows]}
