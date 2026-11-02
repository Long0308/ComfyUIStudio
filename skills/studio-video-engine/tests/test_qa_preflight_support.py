"""Shared helpers of the ``qa preflight`` tests (no tests here): a small synthetic review config whose pieces are real clips."""

from __future__ import annotations

import copy
from pathlib import Path

from test_qa_review_support import FFMPEG, FPS, H, W, np, recipe, scene, sha_of, write_png_rgb, write_video  # noqa: F401
from engine.qa import preflight_recipe
from engine.qa.preflight_segments import pieces
from engine.qa.review_model import build_model

PRE, PRE_SHA = preflight_recipe.load_recipe()


def pre() -> dict:
    return copy.deepcopy(PRE)


def clip(tmp_path: Path, name: str, seed: int, frames: int = 30) -> Path:
    return write_video(tmp_path / f"{name}.mp4", np.stack([scene(seed)] * frames))


def piece(source: str, path: Path, start: int, frames: int = 30) -> dict:
    return {"source_id": source, "path": str(path), "delivery_frames": frames, "native_frames": frames,
            "relative_start_frame": start}


def config(tmp_path: Path, *, seed_a: int, seed_b: int, kind: str = "dip", frames: int = 8, extra: dict | None = None,
          **row) -> dict:
    """Two 30-frame picture shots A -> B with one transition at f30 (window f26-f34 for a dip)."""
    a, b = clip(tmp_path, "a", seed_a), clip(tmp_path, "b", seed_b)
    transition = {"id": "T30", "boundary": 30, "from": "S01_A", "to": "S01_B", "type": kind, "frames": frames,
                  "start": 26, "end_exclusive": 34, **row}
    config = {"fps": FPS, "width": W, "height": H, "main_frames": 60, "end_hold_frames": 0, "total_frames": 60,
              "motion": {"transitions": [transition]}, "outro_cards": [],
              "dialogue": [{"id": "S01_A", "start_frame": 0, "end_frame_exclusive": 30, "words": [],
                            "segments": [piece("S01_A", a, 0)]},
                           {"id": "S01_B", "start_frame": 30, "end_frame_exclusive": 60, "words": [],
                            "segments": [piece("S01_B", b, 0)]}]}
    config.update(extra or {})
    return config


def transitions_run(cfg: dict, tmp_path: Path, **kw) -> dict:
    from engine.qa import preflight_transitions
    rec = recipe()
    return preflight_transitions.run(cfg, build_model(cfg, rec), rec, pre(), pieces(cfg, tmp_path), FFMPEG, **kw)
