"""CLI of ``jjv audio``: every verb parses and dry-runs without GPU or ComfyUI; module size and neutrality (T-E43)."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest
from audio_fixtures import audio_world, hand_built_review, write_tone

from engine.config import loader

SKILL_ROOT = loader.SKILL_ROOT
AUDIO = SKILL_ROOT / "engine" / "audio"


def jjv():
    spec = importlib.util.spec_from_file_location("jjv_audio_cli", SKILL_ROOT / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def episode(tmp_path):
    config, _ = audio_world(tmp_path)
    root = Path(config.episode_root)
    review = root / "review-config.json"
    review.write_text(json.dumps(hand_built_review(root)), encoding="utf-8")
    pack = root / "pack.json"
    pack.write_text(json.dumps({"shots": [{"shot_id": "S01_A", "visual_description": "Mother rotates it a quarter-turn. No pouring."},
                                          {"shot_id": "S01_B", "visual_description": "Alice sets three wooden tokens beside the milk farm cow."}]}), "utf-8")
    music = root / "music.wav"
    write_tone(music, 6.0, 0.3, 180.0)
    return str(root / "engine" / "episode.json"), review, pack, music, tmp_path


def run(capsys, *argv: str) -> tuple[int, dict]:
    code = jjv().main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_music_plan_dry_run_derives_the_brief_from_the_script_and_writes_nothing(episode, capsys) -> None:
    episode_file, review, pack, _, tmp = episode
    code, out = run(capsys, "audio", "music", "plan", "--episode", episode_file, "--out", str(tmp / "m"), "--review-config", str(review),
                    "--shot-pack", str(pack), "--dry-run")
    plan = out["plan"]
    assert code == 0 and not (tmp / "m").exists() and plan["brief_sources"]["bpm"] == "derived from the script"
    assert plan["brief"]["instruments"].startswith("ukulele") and "major" in plan["brief"]["key"]  # farm/cow keywords: pastoral
    assert plan["bed_target_s"] == 23.0 and plan["timeline"]["source"] == "review-config"
    assert plan["prompt"]["style"].endswith(f"{plan['brief']['bpm']:g} BPM, {plan['brief']['key']}, {plan['brief']['instruments']}")


def test_music_plan_flags_override_the_derived_brief_and_write_once(episode, capsys) -> None:
    episode_file, review, pack, _, tmp = episode
    args = ["audio", "music", "plan", "--episode", episode_file, "--out", str(tmp / "m"), "--review-config", str(review),
            "--bpm", "104", "--key", "D major", "--instruments", "ukulele only", "--takes", "2", "--seed", "7"]
    code, out = run(capsys, *args)
    assert code == 0 and out["brief"] == {"bpm": 104.0, "key": "D major", "instruments": "ukulele only"} and out["jobs"] == 2
    assert out["brief_sources"]["bpm"] == "cli"
    plan = json.loads((tmp / "m" / "music-plan.json").read_text("utf-8"))
    assert [j["seed"] for j in plan["jobs"]] == [7, 8] and (tmp / "m" / "workflows" / "music-c01-t02.api.json").is_file()
    code, again = run(capsys, *args)  # identical re-plan is idempotent
    assert code == 0 and again["plan_sha256"] == out["plan_sha256"]
    code, refused = run(capsys, *args[:-1], "9")  # another seed over the same folder is refused
    assert code == 1 and "refusing to overwrite" in refused["error"]


def test_sfx_cues_dry_run_and_submit_dry_run_send_nothing(episode, capsys) -> None:
    episode_file, review, pack, _, tmp = episode
    base = ["--episode", episode_file, "--out", str(tmp / "s")]
    code, out = run(capsys, "audio", "sfx", "cues", *base, "--review-config", str(review), "--shot-pack", str(pack), "--dry-run")
    classes = {p["class"] for p in out["plan"]["placements"]}
    assert code == 0 and {"bottle_rotate", "wood_token_set", "sparkle", "card_sparkle", "whoosh", "logo_chime"} <= classes
    assert "pour" not in classes and not (tmp / "s").exists()
    code, out = run(capsys, "audio", "sfx", "cues", *base, "--review-config", str(review), "--shot-pack", str(pack))
    assert code == 1 and "OFF by default" in out["error"] and not (tmp / "s").exists()   # SFX are opt-in per episode
    code, out = run(capsys, "audio", "sfx", "cues", *base, "--review-config", str(review), "--shot-pack", str(pack), "--with-sfx")
    assert code == 0 and out["clips"] == len(json.loads((tmp / "s" / "sfx-plan.json").read_text("utf-8"))["jobs"])
    code, out = run(capsys, "audio", "sfx", "submit", *base)
    assert code == 0 and out["dry_run"] and {r["state"] for r in out["jobs"]} == {"READY"}
    code, out = run(capsys, "audio", "sfx", "submit", *base, "--execute")
    assert code == 1 and "OFF by default" in out["error"]
    code, out = run(capsys, "audio", "sfx", "submit", *base, "--execute", "--dry-run", "--with-sfx")
    assert code == 1 and "exclude each other" in out["error"]


def test_music_submit_dry_run_and_finalize_dry_run(episode, capsys) -> None:
    episode_file, review, _, _, tmp = episode
    base = ["--episode", episode_file, "--out", str(tmp / "m")]
    run(capsys, "audio", "music", "plan", *base, "--review-config", str(review))
    code, out = run(capsys, "audio", "music", "submit", *base)
    assert code == 0 and out["dry_run"] and out["jobs"][0]["state"] == "READY"
    code, out = run(capsys, "audio", "music", "finalize", *base, "--dry-run")
    assert code == 0 and out["states"] == [{"job_id": "music-c01-t01", "state": "READY"}]
    code, out = run(capsys, "audio", "music", "finalize", *base)
    assert code == 2 and "no job.json yet" in out["error"]  # nothing generated yet: exit 2, never a traceback


def test_mix_dry_run_and_the_missing_input_refusals(episode, capsys) -> None:
    episode_file, review, _, music, tmp = episode
    base = ["audio", "mix", "--episode", episode_file, "--out", str(tmp / "x"), "--review-config", str(review)]
    code, out = run(capsys, *base, "--music-wav", str(music), "--dry-run")
    assert code == 0 and out["recipe"]["profile"] == "cinema" and out["timeline"]["total_frames"] == 600
    code, out = run(capsys, *base, "--dry-run")
    assert code == 1 and "exactly one of --music-receipt and --music-wav" in out["error"]
    code, out = run(capsys, *base, "--music-wav", str(music), "--remux", "p.mp4")
    assert code == 1 and "--remux needs --remux-out" in out["error"]


def test_audio_modules_stay_small_neutral_and_never_post_by_hand() -> None:
    sources = sorted(AUDIO.glob("*.py"))
    assert len(sources) >= 15
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 400, source
        for token in ("jenniejoy", "newtecons", "04-milk-and-mom", "ep04", "milk"):
            assert token not in text.lower(), (source, token)
        tree = ast.parse(text)
        for node in ast.walk(tree):  # the only HTTP the audio package makes is GET /object_info and the engine.comfy dispatch
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "post":
                raise AssertionError(f"{source.name} calls .post() itself; POSTs go through engine.comfy.dispatch")
    assert not any("requests" in s.read_text("utf-8") or "urllib" in s.read_text("utf-8") for s in sources)
