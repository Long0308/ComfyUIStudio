"""Shared fixtures of the ``jjv plan explain`` tests: a small synthetic review config + helpers (no tests here).

The synthetic film (510 f @ 30): intro, 3 shots (S01_A, S01_B, S02_A), a bloom / a whip / an iris boundary, two vocab
cards, an end plate and a 30 f end hold.  Every sha is a made-up 64-hex string: the planner never opens a media file.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from engine.plan.api import plan_explain

PLAN_DIR = Path(__file__).resolve().parents[1] / "recipes" / "plan"
EP04_EDITORIAL = (Path(__file__).resolve().parents[4] / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom" /
                  "editorial")


def sha(tag: str) -> str:
    import hashlib
    return hashlib.sha256(tag.encode()).hexdigest()


def _words(shot: str, start: int) -> list[dict]:
    return [{"w": f"{shot}-w{i}", "startF": start + 10 + 30 * i, "endF": start + 25 + 30 * i, "keyword": i == 1,
             "method": "whisper", "icon": None, "anchor": False} for i in range(3)]


def _shot(shot: str, start: int, end: int) -> dict:
    return {"id": shot, "speaker": "mother", "start_frame": start, "duration_frames": end - start,
            "end_frame_exclusive": end, "speech_text": f"text {shot}", "target_keywords": ["a"],
            "segments": [{"source_id": shot, "path": f"C:/x/{shot}.mp4", "sha256": sha(f"clip-{shot}"),
                          "native_frames": 72, "delivery_frames": end - start}],
            "audio": {"path": f"C:/x/{shot}.wav", "sha256": sha(f"wav-{shot}"), "offset_frames": 0,
                      "duration_seconds": 4.0},
            "words": _words(shot, start)}


def _rec(rid: str, kind: str, boundary: int, frm: str, to: str, start: int, end: int) -> dict:
    return {"id": rid, "boundary": boundary, "from": frm, "to": to, "type": kind, "start": start,
            "end_exclusive": end, "motivation": f"prose {rid}"}


def base_config() -> dict:
    return {
        "schema": "synthetic/review-config", "episode_id": "synthetic", "fps": 30, "width": 1920, "height": 1080,
        "label": "REVIEW", "main_frames": 480, "end_hold_frames": 30, "total_frames": 480,
        "opening": {"path": "C:/x/open.png", "sha256": sha("opening")}, "logo": {"path": "C:/x/logo.png", "sha256": sha("logo")},
        "dialogue": [_shot("S01_A", 30, 150), _shot("S01_B", 150, 270), _shot("S02_A", 270, 390)],
        "outro_cards": [{"term": "Alpha", "start_frame": 410, "duration_frames": 20,
                         "icon": {"path": "C:/x/a.png", "sha256": sha("icon-alpha")},
                         "audio": {"path": "C:/x/a.wav", "sha256": sha("card-alpha")}},
                        {"term": "Beta", "start_frame": 430, "duration_frames": 20,
                         "icon": {"path": "C:/x/b.png", "sha256": sha("icon-beta")},
                         "audio": {"path": "C:/x/b.wav", "sha256": sha("card-beta")}}],
        "mix": {"music": {"path": "C:/x/music.wav", "sha256": sha("music-A"), "gain": 1.0, "status": "CANDIDATE"},
                "ambience_foley": {"path": "C:/x/amb.wav", "sha256": sha("ambience"), "gain": 1.0},
                "outro": {"mix_parameters": {"duck_db": -7.0, "dialogue_gain_db": -1.5}, "sections_LUFS": {"a": -17.0}},
                "mix_wav": {"path": "C:/x/mix.wav", "sha256": sha("mix-wav-A")}},
        "end_line": {"text": "bye", "start_frame": 470, "duration_frames": 20,
                     "audio": {"path": "C:/x/bye.wav", "sha256": sha("end-line")}},
        "word_timing": {"path": "C:/x/wt.json", "sha256": sha("word-timing-1"), "schema": "wt/v1", "words": 9},
        "motion": {
            "transitions": [_rec("T30", "bloom", 30, "INTRO", "S01_A", 28, 34),
                            _rec("T150", "none", 150, "S01_A", "S01_B", 150, 150),
                            _rec("T270", "whip", 270, "S01_B", "S02_A", 266, 274),
                            _rec("T390", "iris", 390, "S02_A", "LOGO", 380, 420),
                            _rec("T450", "plate-in", 450, "CARD", "PLATE", 450, 480)],
            "icons": [{"id": "IC01", "shot": "S01_B", "word": "w1", "icon": "a.png", "icon_path": "C:/x/a.png",
                       "icon_sha256": sha("icon-a"), "word_start_frame": 190, "frame": 190, "total_frames": 32}],
            "ending": {"logo_disc": {"in": 400}, "end_plate": {"start": 450, "text_en": "See you", "text_vi": "Hen"},
                       "audio_tail": "music tail", "end_logo": {"frames": 30}}},
    }


def mix_plan(bed: str = "bed-A", duck: float = -7.0) -> dict:
    return {"schema": "synthetic/mix-plan", "task": "T", "parameters": {"duck_db": duck, "dialogue_gain_db": -1.5},
            "bed": {"path": "C:/x/bed.wav", "sha256": sha(bed), "label": bed},
            "sections": {"whole": {"integrated_LUFS": -17.0}}, "mix_peak_dBFS": -2.0,
            "mix": {"path": "C:/x/mix.wav", "sha256": sha("mix-" + bed)}}


def write_version(root: Path, name: str, config: dict, *, plan: dict | None = None,
                  descriptor: dict | None = None, record: dict | None = None) -> Path:
    """Write one version directory (config + optional mix plan / render record / descriptor); return it."""
    d = root / name
    (d / "config").mkdir(parents=True, exist_ok=True)
    (d / "config" / "review-config-x.json").write_text(json.dumps(config), encoding="utf-8")
    if plan is not None:
        (d / "mix-plan-x.json").write_text(json.dumps(plan), encoding="utf-8")
    if record is not None:
        (d / "render-record-picture-x.json").write_text(json.dumps(record), encoding="utf-8")
    if descriptor is not None:
        (d / "plan-inputs.json").write_text(json.dumps({"schema": "jjv/plan-inputs/v1", **descriptor}), encoding="utf-8")
    return d


def record(compositor: str = "comp-1", remotion: str = "4.0.536") -> dict:
    return {"compositor": {"sha256": sha(compositor)}, "remotion_version": remotion, "chromium_gl": "swiftshader",
            "render_script": {"sha256": sha("script-" + compositor)}}


def mutate(config: dict, fn) -> dict:
    """A deep copy of ``config`` edited by ``fn(copy)`` (the original is never touched)."""
    out = copy.deepcopy(config)
    fn(out)
    return out


def shot_of(config: dict, shot: str) -> dict:
    return next(d for d in config["dialogue"] if d["id"] == shot)


def run(old: Path, new: Path, **kwargs) -> dict:
    return plan_explain(old, new, **kwargs)


def rows(doc: dict, *, kind: str | None = None, status: str | None = None) -> dict:
    """``node -> row`` filtered by kind / status."""
    return {r["node"]: r for r in doc["rows"] if (kind is None or r["kind"] == kind) and (status is None or r["status"] == status)}
