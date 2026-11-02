"""Q5 pacing + frames + loudness.

* Config arithmetic (no video needed): the logo is still for >= ``logo_still_min_frames``, every vocabulary card
  lasts >= ``card_min_frames``, dialogue windows tile with no gap or overlap, cards are contiguous, the end plate
  starts where the last card ends, ``main + end card == total`` and the total equals the contract.
* File (ffprobe, no decoding): frame count, fps, size and an audio stream whose length matches the picture.
* Measured logo still: the longest run of consecutive frames inside the declared still window whose
  4x4 block-mean luma step is <= ``still_diff_max`` must also reach ``logo_still_min_frames`` (a declared hold the
  picture does not honour fails).
* Loudness: ``q5_loudness``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...media.probe import VideoInfo
from ..review_media import numpy_module
from ..review_model import Model, contract_frames, logo_still_frames
from . import FAIL, PASS, UNCERTAIN, roll_up
from .q3_flash import _small


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def _tiling(model: Model) -> list[dict]:
    out, rows = [], [d for d in model.dialogue if isinstance(d.get("start_frame"), int)]
    for a, b in zip(rows, rows[1:]):
        gap = b["start_frame"] - a["end_frame_exclusive"]
        if gap:
            out.append(_check("dialogue_tiling", False, f"{a['id']} ends f{a['end_frame_exclusive']} but "
                                                         f"{b['id']} starts f{b['start_frame']} ({gap:+d} f)"))
    cards = model.cards
    for a, b in zip(cards, cards[1:]):
        gap = b["start_frame"] - (a["start_frame"] + a["duration_frames"])
        if gap:
            out.append(_check("card_tiling", False, f"card {a['term']!r} ends f{a['start_frame'] + a['duration_frames']} "
                                                     f"but {b['term']!r} starts f{b['start_frame']} ({gap:+d} f)"))
    return out or [_check("tiling", True, f"{len(rows)} dialogue windows and {len(cards)} cards are contiguous")]


def pacing(config: dict, model: Model, recipe: dict, expect_frames: int | None) -> tuple[list[dict], int | None]:
    """Config arithmetic.  Returns (checks, contract total)."""
    p = recipe["q5_pacing"]
    checks: list[dict] = []
    still, window, source = logo_still_frames(model)
    if still is None:
        checks.append({**_check("logo_still", False, "the config states no logo still length"), "uncertain": True})
    else:
        checks.append(_check("logo_still", still >= p["logo_still_min_frames"],
                             f"{still} f ({source}), minimum {p['logo_still_min_frames']}"))
    short = [f"{c.get('term')}: {c.get('duration_frames')} f" for c in model.cards
             if not isinstance(c.get("duration_frames"), int) or c["duration_frames"] < p["card_min_frames"]]
    checks.append(_check("card_length", not short and bool(model.cards),
                         f"{len(model.cards)} cards, minimum {p['card_min_frames']} f" + (f"; too short: {short}" if short else "")))
    checks += _tiling(model)
    total, where = contract_frames(config, model)
    plate = (model.ending.get("end_plate") or {}).get("start")
    if model.cards and isinstance(plate, int):
        last = model.cards[-1]
        end = last["start_frame"] + last["duration_frames"]
        checks.append(_check("plate_after_cards", plate == end, f"end plate starts f{plate}, last card ends f{end}"))
    if model.main_frames is not None and total is not None:
        checks.append(_check("main_plus_end_card", model.main_frames + model.end_frames == total,
                             f"{model.main_frames} + {model.end_frames} vs total {total} ({where})"))
    if expect_frames is not None:
        checks.append(_check("contract_frames", total == expect_frames, f"config total {total} vs contract {expect_frames}"))
        total = expect_frames if total is None else total
    elif total is None:
        checks.append({**_check("contract_frames", False, "no total frame count in the config"), "uncertain": True})
    return checks, total


def file_checks(info: VideoInfo, durations: dict, model: Model, total: int | None, has_mix: bool, tol_s: float) -> list[dict]:
    checks = []
    if total is not None:
        ok = info.frames == total
        checks.append({**_check("frame_count", ok, f"file has {info.frames} f, contract {total}"),
                       "uncertain": info.frames is None})
    fps_ok = abs(float(info.fps) - model.fps) < 1e-3
    checks.append(_check("fps", fps_ok, f"file {float(info.fps):.3f}, config {model.fps}"))
    if model.width and model.height:
        checks.append(_check("size", (info.width, info.height) == (model.width, model.height),
                             f"file {info.width}x{info.height}, config {model.width}x{model.height}"))
    if not has_mix:
        audio, video = durations["audio_s"], durations["video_s"]
        ok = durations["has_audio"] and audio is not None and video is not None and abs(audio - video) <= tol_s
        checks.append(_check("audio_stream", bool(ok), f"audio {audio} s vs picture {video} s (tolerance {tol_s})"))
    return checks


def measure_still(gray: Any, origin: int, window: tuple[int, int] | None, p: dict) -> dict | None:
    """Longest run of frames inside ``window`` whose block-mean luma step to the previous frame is small."""
    np = numpy_module()
    if window is None:
        return None
    first, last = window[0] - origin, window[1] - origin
    if first < 1 or last >= gray.shape[0]:
        return None
    steps = [float(np.abs(_small(gray[i]) - _small(gray[i - 1])).mean()) for i in range(first, last + 1)]
    best = run = 0
    for s in steps:
        run = run + 1 if s <= p["still_diff_max"] else 0
        best = max(best, run)
    return {"window": list(window), "longest_still_run": best, "max_step": round(max(steps), 2)}


def run(config: dict, model: Model, recipe: dict, video: Path | None, info: VideoInfo | None, durations: dict | None,
        gray: Any, origin: int, expect_frames: int | None, has_mix: bool) -> dict:
    p = recipe["q5_pacing"]
    checks, total = pacing(config, model, recipe, expect_frames)
    still = None
    if gray is not None:
        _, window, _ = logo_still_frames(model)
        still = measure_still(gray, origin, window, p)
        if still is not None:
            ok = still["longest_still_run"] >= p["logo_still_min_frames"]
            checks.append(_check("logo_still_measured", ok, f"longest still run {still['longest_still_run']} f in "
                                                            f"f{still['window'][0]}-f{still['window'][1]}"))
    if info is not None and durations is not None and origin == 0:
        checks += file_checks(info, durations, model, total, has_mix, p["ffprobe_duration_tolerance_s"])
    failed = [c for c in checks if not c["ok"] and not c.get("uncertain")]
    unsure = [c for c in checks if not c["ok"] and c.get("uncertain")]
    status = roll_up([FAIL] * bool(failed) + [UNCERTAIN] * bool(unsure) + [PASS])
    return {"status": status, "checks": checks, "contract_frames": total, "still": still,
            "failures": [f"{c['name']}: {c['detail']}" for c in failed + unsure]}

