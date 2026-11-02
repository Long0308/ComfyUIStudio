"""``jjv qa review``: the automatic gates Q2-Q5 that run before any person sees a review cut.

Q1 (word-sync onset) belongs to the timing stage and is not run here.  CPU only (ffmpeg + numpy), no network.
The video is decoded ONCE as small gray frames (shared by Q3, Q4, Q5); full-resolution frames are pulled only
for the contact sheets and the icon tiles.

Verdict / exit code: any gate FAIL -> ``FAIL`` (exit 1); else any UNCERTAIN -> ``UNCERTAIN`` (exit 2); else
``PASS`` (exit 0).  A gate that cannot read its inputs is UNCERTAIN, never a silent pass.  The report carries no
timestamp; ``timing_s`` is wall-clock seconds per stage.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file
from . import review_media as media
from .preflight import apply_floors
from .gates import FAIL, PASS, UNCERTAIN, q1b_caption, q2_icons, q3_flash, q4_ghost, q5_loudness, q5_pacing, roll_up
from .review_model import build_model
from .review_recipe import effective_recipe

REPORT_SCHEMA = "jjv/qa-review-report/v1"
ALL_GATES = ("Q1B", "Q2", "Q3", "Q4", "Q5")
EXIT = {PASS: 0, FAIL: 1, UNCERTAIN: 2}


def _guard(name: str, call) -> dict:
    """An unreadable input inside one gate makes THAT gate UNCERTAIN; the other gates still run."""
    try:
        return call()
    except Uncertain as error:
        return {"gate": name, "status": UNCERTAIN, "failures": [f"unreadable input: {error}"]}


def _q5(config: dict, model: Any, recipe: dict, ctx: dict) -> dict:
    gray, info, source = ctx["gray"], ctx["info"], ctx["audio_source"]
    pace = q5_pacing.run(config, model, recipe, ctx["video"], info, ctx["durations"], gray, ctx["origin"],
                         ctx["expect_frames"], ctx["has_mix"])
    loud = _guard("Q5", lambda: q5_loudness.run(model, recipe, source, ctx["ffmpeg"], pace["contract_frames"],
                                                ctx["audio_origin_s"]))
    return {"gate": "Q5", "status": roll_up([pace["status"], loud["status"]]), "pacing": pace, "loudness": loud,
            "failures": pace["failures"] + loud.get("failures", [])}


def bind_contract(recipe: dict, overrides: dict, *, limits: dict | None, episode_total: int | None,
                  explicit: int | None, declared: int | None) -> int | None:
    """Bind Q5 to the per-episode DELIVERY CONTRACT (M9a): the domain floors raise the recipe floors (in place) and the
    contract total is the expected length.  A length stated by the caller or the config that disagrees is Refused."""
    apply_floors(recipe, limits, overrides)
    for label, value in (("--expect-frames", explicit), ("config qa.review.expect_total_frames", declared)):
        if value is not None and episode_total is not None and value != episode_total:
            raise Refused(f"{label} {value} disagrees with the episode contract total {episode_total} f")
    stated = explicit if explicit is not None else declared
    return stated if stated is not None else episode_total


def run_review(*, config: dict, video: Path, ffmpeg: str, recipe: dict, recipe_sha256: str, config_sha256: str,
               root: Path, mix: Path | None = None, events: dict | None = None, gates: tuple[str, ...] = ALL_GATES,
               sheets_dir: Path | None = None, origin: int = 0, audio_origin_s: float = 0.0,
               expect_frames: int | None = None, layout_non_change: frozenset[int] = frozenset(),
               limits: dict | None = None, episode_total: int | None = None) -> dict:
    """Run the selected gates on one review export and return the report (see module doc)."""
    unknown = sorted(set(gates) - set(ALL_GATES))
    if unknown:
        raise Refused(f"unknown gate(s) {unknown}; choose from {list(ALL_GATES)}")
    for path, label in ((video, "video"), (mix, "mix wav")):
        if path is not None and not Path(path).is_file():
            raise Uncertain(f"{label} not found: {path}")
    started, timing = time.perf_counter(), {}
    recipe, overrides = effective_recipe(recipe, config)
    block = ((config.get("qa") or {}).get("review")) or {}
    expect = bind_contract(recipe, overrides, limits=limits, episode_total=episode_total, explicit=expect_frames,
                           declared=block.get("expect_total_frames"))
    declared = layout_non_change | frozenset(block.get("layout_change_boundaries") or [])
    model = build_model(config, recipe, events)
    ffprobe = media.find_ffprobe(ffmpeg)
    info = media.probe(video, ffprobe)
    native = (info.width, info.height)
    mark = time.perf_counter()
    q3p = recipe["q3_flash"]
    gray = None
    if {"Q3", "Q4", "Q5"} & set(gates):  # Q2 reads only a few full frames
        gray = media.decode_gray(video, ffmpeg, q3p["analysis_width"], q3p["analysis_height"])
    timing["decode"] = round(time.perf_counter() - mark, 2)
    results: dict[str, dict] = {}
    out_dir = Path(sheets_dir) if sheets_dir else Path(tempfile.mkdtemp(prefix="jjv-qa-review-sheets-"))
    ctx = {"gray": gray, "info": info, "video": video, "ffmpeg": ffmpeg, "origin": origin, "expect_frames": expect,
           "has_mix": mix is not None, "audio_source": mix or video, "audio_origin_s": audio_origin_s,
           "durations": media.probe_durations(video, ffprobe)}
    steps = {"Q1B": lambda: q1b_caption.run_q1b(config, video, ffmpeg=ffmpeg, origin=origin),
             "Q2": lambda: q2_icons.run(model, recipe, video, ffmpeg, root, native, origin),
             "Q3": lambda: q3_flash.run(model, gray, recipe, origin, declared),
             "Q4": lambda: q4_ghost.run(model, gray, video, ffmpeg, recipe, out_dir, native, origin),
             "Q5": lambda: _q5(config, model, recipe, ctx)}
    for name in ALL_GATES:
        if name in gates:
            mark = time.perf_counter()
            results[name] = _guard(name, steps[name])
            timing[name] = round(time.perf_counter() - mark, 2)
    timing["total"] = round(time.perf_counter() - started, 2)
    verdict = roll_up(r["status"] for r in results.values())
    return {"schema": REPORT_SCHEMA, "verdict": verdict, "ok": verdict == PASS, "exit_code": EXIT[verdict],
            "gates": results, "config_sha256": config_sha256,
            "contract": {"episode_total_frames": episode_total, "expected_frames": expect},
            "recipe": {"id": recipe["id"], "sha256": recipe_sha256, "overrides": overrides},
            "video": {"name": Path(video).name, "sha256": sha256_file(video), "frames": info.frames,
                      "fps": float(info.fps), "width": info.width, "height": info.height, "origin_frame": origin},
            "mix": {"name": Path(mix).name, "sha256": sha256_file(mix)} if mix else None,
            "sheets_dir": str(out_dir) if "Q4" in gates else None, "timing_s": timing,
            "caveats": ["Q1 (word-sync onset) is not part of this command",
                        "a green mechanical gate is necessary, not sufficient: look at the Q4 contact sheets"]}
