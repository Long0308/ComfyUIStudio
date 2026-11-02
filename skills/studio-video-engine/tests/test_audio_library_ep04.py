"""Read-only runs against the real first episode and the real library (skipped when they are absent).

The pick runs with ``--dry-run`` (no registry write, no receipt).  The real Demucs run is opt-in
(``JJV_REAL_DEMUCS=1``, about 35 s CPU on one 120 s bed) because it is slow; its numbers are in the builder report.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest

from engine.audio import musicpick_cli, vocalgate
from engine.config import loader
from engine.core.io import read_json, sha256_file
from engine.seedvr2.seam_media import find_ffmpeg

LIBRARY = loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "_library"
REGISTRY = LIBRARY / "music-beds" / "REGISTRY.json"
EPISODE = loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom" / "engine" / "episode.json"
pytestmark = pytest.mark.skipif(not (REGISTRY.is_file() and EPISODE.is_file()), reason="the first episode / the library are absent")


def pick_dry_run(out: Path, capsys) -> tuple[int, dict]:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="verb").add_parser("music").add_subparsers(dest="action")
    musicpick_cli.register(sub)
    args = parser.parse_args(["music", "pick", "--episode", str(EPISODE), "--out", str(out), "--dry-run"])
    code = musicpick_cli.run_music_action(args)
    return code, json.loads(capsys.readouterr().out)


def test_the_first_episode_keeps_its_bed_and_the_registry_is_not_touched(tmp_path, capsys) -> None:
    before = sha256_file(REGISTRY)
    siblings = sorted(p.name for p in REGISTRY.parent.iterdir())
    code, out = pick_dry_run(tmp_path / "never-written", capsys)
    assert code == 0 and out["dry_run"] is True and out["written"] is None
    assert out["decision"] == "library" and out["bed_id"] == "NHAC-V2-4" and out["previous_film"] is None
    assert "this episode already used it" in out["reason"] and out["bed_target_s"] == 118.0
    rows = {r["id"]: r for r in out["ranking"]}
    assert rows["NHAC-V2-4"]["fits_by_content"] is False and rows["NHAC-V2-4"]["already_used_by_this_episode"] is True
    # the brief asks for ukulele/glockenspiel/piano/hand percussion; every library bed is the guitar-marimba palette:
    # by content alone nothing fits, so a FRESH episode with this brief would generate (the table shows why)
    assert not any(r["fits_by_content"] for r in rows.values())
    assert all(r["eligible"] for r in rows.values()) and out["ranking"][0]["id"] == "NHAC-V2-4"
    assert sha256_file(REGISTRY) == before and sorted(p.name for p in REGISTRY.parent.iterdir()) == siblings
    assert not (tmp_path / "never-written").exists()


@pytest.mark.skipif(os.environ.get("JJV_REAL_DEMUCS") != "1", reason="slow: set JJV_REAL_DEMUCS=1 to run Demucs on one real bed")
def test_the_configured_wrapper_runs_real_demucs_on_one_library_bed_read_only(tmp_path) -> None:
    machine = read_json(loader.DEFAULT_MACHINE_PATH)
    recipe = read_json(loader.SKILL_ROOT / "recipes" / "audio" / "music-yue2-int8-v001.json")
    gate = vocalgate.resolve(machine, recipe["vocal_gate"], None)
    assert gate is not None, "machine.audio.vocal_gate.command is not configured"
    row = next(b for b in read_json(REGISTRY)["beds"] if b["id"] == "NHAC-V2-1")
    bed = LIBRARY / "music-beds" / row["file"]
    before = sha256_file(bed)
    result = vocalgate.run(gate, bed, tmp_path / "gate", ffmpeg=find_ffmpeg())
    assert sha256_file(bed) == before and result["status"] == "PASS" and result["rule"] == "v2"
    assert result["windows_over_limit"] == 0 and result["vocals_relative_db"] <= -35.0
    assert abs(result["vocals_relative_db"] - row["vocal_gate"]["vocal_minus_bed_rms_db"]) < 3.0  # the lane measured it on a mono mix
