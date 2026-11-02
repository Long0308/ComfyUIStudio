"""The pending config keys (machine / domain / episode), their schemas, and the vocal-gate wrapper."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from config_fixtures import make_world
from engine.audio import recipe as audio_recipe
from engine.audio import vocalgate
from engine.config import loader
from engine.config import rules
from engine.config.schema import validate
from engine.core.io import read_json, sha256_file

SKILL = loader.SKILL_ROOT
WRAPPER = SKILL / "tools" / "demucs_vocal_gate.py"
# M3 proposed data is copied to these production paths and sha-checked; the tests read the live files.
PROPOSED_MACHINE = loader.REPO_ROOT / "production-local" / "engine" / "machine.json"
PROPOSED_EPISODE = (
    loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom" / "engine" / "episode.json"
)


def schema(name: str) -> dict:
    return read_json(SKILL / "schemas" / f"{name}.schema.json")


# ---- schemas ---------------------------------------------------------------------------------------------
def machine_with(**extra) -> dict:
    base = read_json(loader.DEFAULT_MACHINE_PATH)
    return {**base, **extra}


def test_machine_schema_takes_the_three_stage_blocks_and_closes_them() -> None:
    ok = machine_with(voicestudio={"url": "http://127.0.0.1:8080"},
                      audio={"vocal_gate": {"command": ["py", "w.py", "{input}", "{out_dir}"]}},
                      timing={"python": "p", "model_dir": "m"})
    assert validate(ok, schema("machine"), label="machine") == []
    for bad in (machine_with(voicestudio={"url": "ftp://x"}), machine_with(voicestudio={}),
                machine_with(audio={"vocal_gate": {"command": []}}), machine_with(audio={"vocal_gate": {}}),
                machine_with(timing={"python": "p", "extra": 1}), machine_with(timing={"python": ""})):
        assert validate(bad, schema("machine"), label="machine"), bad


def test_domain_schema_blocks_and_ranges() -> None:
    domain = read_json(SKILL / "domains" / "jenniejoy_cartoon_3d.json")
    assert validate(domain, schema("domain"), label="d") == []
    for mutate in (lambda d: d["voice"].update(allowed_recipes=["audio/x"]), lambda d: d["audio"].update(extra=1),
                   lambda d: d["delivery"]["master"].update(frames=2520), lambda d: d["delivery"].pop("length"),
                   lambda d: d["delivery"]["end_card"].pop("frames_min"),
                   lambda d: d["delivery"]["sections"]["end_plate"].pop("tail_min")):
        broken = json.loads(json.dumps(domain))
        mutate(broken)
        assert validate(broken, schema("domain"), label="d"), mutate


def test_episode_schema_blocks_and_engine_relative_paths() -> None:
    episode = read_json(loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom" / "engine" / "episode.json")
    assert validate(episode, schema("episode"), label="e") == []
    for key in ("review_config", "shot_pack", "dialogue", "cast", "contract_inputs"):
        for path, fine in (("a.json", True), ("../x/y.json", True), ("/abs.json", False), ("../../up.json", False),
                           ("c:\\a.json", False), ("a/../b.json", False), ("a.txt", False)):
            doc = json.loads(json.dumps(episode))
            doc["files"][key] = path
            assert (validate(doc, schema("episode"), label="e") == []) is fine, (key, path)
    for mutate in (lambda d: d["audio"]["mix"].update(recipe="voice/x"), lambda d: d["voice"].update(recipe="audio/x"),
                   lambda d: d["timing"].update(recipe="voice/x"), lambda d: d["audio"]["music"].update(brief={"bpm": 10}),
                   lambda d: d["contract"].update(sections=[]), lambda d: d["contract"]["sections"][0].update(kind="x")):
        broken = json.loads(json.dumps(episode))
        mutate(broken)
        assert validate(broken, schema("episode"), label="e"), mutate

def test_proposed_machine_keys_are_closed_and_contain_no_secret_fields() -> None:
    machine = read_json(PROPOSED_MACHINE)
    assert validate(machine, schema("machine"), label="machine") == []
    assert machine["tools"]["blender_exe"].endswith("/Blender 5.2/blender.exe")
    assert machine["images"]["codex_bin"] is None
    assert machine["images"]["codex_state_path"].endswith("codex-pool-state.json")
    assert [row["label"] for row in machine["images"]["codex_accounts"]] == ["acct1", "acct2", "acct3", "acct4"]
    assert all(set(row) == {"label", "codex_home"} for row in machine["images"]["codex_accounts"])
    assert rules.check_machine(machine) == []

    broken = json.loads(json.dumps(machine))
    broken["images"]["codex_accounts"][0]["token"] = "must-not-be-a-machine-key"
    assert any("unexpected property 'token'" in error
               for error in validate(broken, schema("machine"), label="machine"))
    duplicate = json.loads(json.dumps(machine))
    duplicate["images"]["codex_accounts"][1]["label"] = "acct1"
    assert any("labels must be unique" in error for error in rules.check_machine(duplicate))

def test_proposed_episode_declares_script_icons_cast_roles_and_brand_voice() -> None:
    episode = read_json(PROPOSED_EPISODE)
    assert validate(episode, schema("episode"), label="episode") == []
    assert episode["files"]["script"] == "../script/script-astra-candidate-v003.json"
    assert episode["files"]["icon_registry"] == "../technical/icons-registry-v001/icons.json"
    assert episode["files"]["cast"] == "../characters/REUSE-CAST-v001.json"
    assert episode["cast_roles"] == {"mother": "mom-alice"}
    assert episode["audio"]["brand_voice"] == "intro"
    broken = json.loads(json.dumps(episode))
    broken["audio"]["brand_voice"] = "soundtrack"
    assert validate(broken, schema("episode"), label="episode")

def _materialize_proposed_episode(tmp_path: Path) -> Path:
    source = loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom"
    target = tmp_path / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom"
    engine = target / "engine"
    engine.mkdir(parents=True)
    shutil.copy2(PROPOSED_EPISODE, engine / "episode.json")
    for relative in (
        "engine/shots.json",
        "engine/mouth-boxes.json",
        "script/script-astra-candidate-v003.json",
        "script/shot-prompt-pack-v004.json",
        "characters/REUSE-CAST-v001.json",
        "technical/icons-registry-v001/icons.json",
        "editorial/review-hd-v015/config/review-config-v015.json",
        "DELIVERY-CONTRACT.json",
    ):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)
    return engine / "episode.json"

def test_proposed_ep04_resolves_with_proposed_machine(tmp_path: Path) -> None:
    episode_file = _materialize_proposed_episode(tmp_path)
    report = loader.build_config(episode_file, machine_path=PROPOSED_MACHINE, repo_root=loader.REPO_ROOT)
    assert report.ok, report.violations
    assert report.config is not None
    assert report.config.episode["files"]["script"].endswith("script-astra-candidate-v003.json")
    assert report.config.machine["images"]["codex_accounts"][0]["label"] == "acct1"

def _jjv():
    spec = importlib.util.spec_from_file_location("jjv_m3_keys", SKILL / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module

def _guide_set(layout: Path) -> None:
    from images_fixtures import make_png

    plan = read_json(layout / "layout-plan.json")
    for row in plan["shots"]:
        if not row["brief"]:
            continue
        guide = make_png(layout / "render" / row["shot"] / "r001" / f"{row['shot']}-guide.png")
        (layout / "render" / row["shot"] / "r001" / "render-receipt.json").write_text(json.dumps({
            "status": "rendered", "beauty": {"name": guide.name, "sha256": sha256_file(guide)}
        }), encoding="utf-8")
        placement = layout / "placement" / f"{row['shot']}.txt"
        placement.parent.mkdir(parents=True, exist_ok=True)
        placement.write_text(f"{row['shot']} staging placement\n", encoding="utf-8")

def test_layout_and_images_plan_read_episode_and_machine_without_manual_config_flags(
        tmp_path: Path, monkeypatch, capsys) -> None:
    episode_file = _materialize_proposed_episode(tmp_path)
    layout = tmp_path / "layout"
    assert _jjv().main(["layout", "plan", "--episode", str(episode_file), "--out", str(layout)]) == 0
    layout_out = json.loads(capsys.readouterr().out)
    assert layout_out["unbound_cast"] == []
    plan = read_json(layout / "layout-plan.json")
    assert plan["cast_file"]["path"].endswith("REUSE-CAST-v001.json")
    assert {row["role"]: row["character_id"] for row in plan["shots"][0]["cast"]} == {
        "mother": "mom-alice", "alice": "alice"
    }

    _guide_set(layout)
    images = tmp_path / "images"
    assert _jjv().main(["images", "plan", "--episode", str(episode_file), "--out", str(images),
                         "--layout", str(layout)]) == 0
    images_out = json.loads(capsys.readouterr().out)
    assert images_out["shots"]
    image_plan = read_json(images / "images-plan.json")
    codex = next(row for row in image_plan["shots"][0]["providers"] if row["provider"] == "codex-exec")
    assert codex["accounts_configured"] == 4


# ---- this machine's values are real and the stages read them with no flag ---------------------------------
def live():
    return loader.resolve_episode("04-milk-and-mom")


def test_machine_json_carries_this_machines_values() -> None:
    machine = live().machine
    assert machine["voicestudio"]["url"] == "http://127.0.0.1:8080"
    command = machine["audio"]["vocal_gate"]["command"]
    assert "{input}" in command and "{out_dir}" in command and command[1].endswith("demucs_vocal_gate.py")
    assert machine["timing"]["python"].endswith("python.exe") and "faster-whisper" in machine["timing"]["model_dir"]
    for path in (command[0], command[1], machine["timing"]["python"], machine["timing"]["model_dir"]):
        assert os.path.exists(path), path


def test_stages_resolve_their_settings_from_config_alone() -> None:
    config = live()
    gate = vocalgate.resolve(config.machine, {"vocals_file": "vocals.wav", "limit_db": -35.0}, None)
    assert gate is not None and gate.source == "machine.audio.vocal_gate"
    from engine.timing import cli as timing_cli
    from engine.timing.recipe import resolve_recipe as timing_recipe

    recipe, origin = timing_recipe(config, None)
    assert origin == "episode.timing.recipe"
    recognizer = timing_cli._recognizer(argparse.Namespace(python=None, model=None), config, recipe)
    assert recognizer is not None
    from engine.voice.recipe import voice_settings

    assert voice_settings(config, recipe_id="voice/omnivoice-en-broadcast-v001").voicestudio_url == "http://127.0.0.1:8080"
    for family, want in (("audio-music", "music-yue2-int8-v001"), ("audio-sfx", "sfx-stable-audio-3-small-v001"),
                         ("audio-mix", "mix-cinema-ep04-final-v001")):
        picked, origin = audio_recipe.select_recipe_id(config, family, None)
        assert picked == f"audio/{want}" and origin.startswith("episode.audio")
        assert picked in config.domain["audio"]["allowed_recipes"]


def test_the_legacy_parity_mix_stays_off_the_domain_list() -> None:
    assert "audio/mix-legacy-v004-parity" not in live().domain["audio"]["allowed_recipes"]
    assert live().domain["voice"]["require_listen_approval"] is True


def test_a_fresh_world_resolves_without_the_new_blocks(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    report = loader.build_config(world.episode_file, skill_root=world.skill_root, machine_path=world.machine_path)
    assert report.ok, report.violations


# ---- the Demucs wrapper (fake separator: no model, no GPU, no network) -----------------------------------
def riff(path: Path, rate: int, seconds: float = 0.5) -> None:
    data = b"\x01\x00" * round(rate * seconds)
    path.write_bytes(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(data)) + data)


def rate_of(path: Path) -> int:
    return struct.unpack("<I", path.read_bytes()[24:28])[0]


FAKE_DEMUCS = '''
import os, struct, sys
from pathlib import Path
args = sys.argv[1:]
out, source = Path(args[args.index("-o") + 1]), Path(args[-1])
if os.environ.get("FAKE_FAIL"):
    print("model not found", file=sys.stderr); sys.exit(7)
rate = int(os.environ.get("FAKE_RATE", "44100"))
target = out / "htdemucs" / source.stem
target.mkdir(parents=True)
data = b"\\x02\\x00" * rate
for name in ("vocals.wav", "no_vocals.wav"):
    (target / name).write_bytes(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(data)) + data)
'''


def run_wrapper(tmp_path: Path, bed: Path, out: Path, **env) -> subprocess.CompletedProcess:
    fake = tmp_path / "fake_demucs.py"
    fake.write_text(FAKE_DEMUCS, encoding="utf-8")
    return subprocess.run([sys.executable, "-I", str(WRAPPER), str(bed), str(out), "--demucs-cmd",
                           json.dumps([sys.executable, "-I", str(fake)])],
                          capture_output=True, text=True, env={**os.environ, **env}, check=False)


def test_wrapper_leaves_exactly_one_vocals_wav_and_no_scratch_inside_out_dir(tmp_path: Path) -> None:
    bed, out = tmp_path / "bed.wav", tmp_path / "gate" / "out"
    riff(bed, 44100)
    done = run_wrapper(tmp_path, bed, out, FAKE_RATE="44100")
    assert done.returncode == 0, done.stderr
    assert [p.name for p in out.rglob("*")] == ["vocals.wav"]
    assert not [p for p in out.parent.iterdir() if p.name.startswith("demucs-")]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg to resample")
def test_wrapper_resamples_the_stem_to_the_input_rate(tmp_path: Path) -> None:
    bed, out = tmp_path / "bed.wav", tmp_path / "out"
    riff(bed, 48000)
    done = run_wrapper(tmp_path, bed, out, FAKE_RATE="44100")
    assert done.returncode == 0, done.stderr
    assert rate_of(out / "vocals.wav") == 48000


def test_wrapper_exit_codes_for_a_failed_separator_and_a_missing_input(tmp_path: Path) -> None:
    bed = tmp_path / "bed.wav"
    riff(bed, 44100)
    failed = run_wrapper(tmp_path, bed, tmp_path / "o1", FAKE_FAIL="1")
    assert failed.returncode == 3 and "demucs exited 7" in failed.stderr and not (tmp_path / "o1" / "vocals.wav").exists()
    missing = run_wrapper(tmp_path, tmp_path / "nope.wav", tmp_path / "o2")
    assert missing.returncode == 2 and "input not found" in missing.stderr


def test_the_engine_vocal_gate_accepts_the_wrappers_output(tmp_path: Path) -> None:
    bed, out = tmp_path / "bed.wav", tmp_path / "gate"
    riff(bed, 44100, seconds=1.5)
    fake = tmp_path / "fake_demucs.py"
    fake.write_text(FAKE_DEMUCS, encoding="utf-8")
    command = (sys.executable, "-I", str(WRAPPER), "{input}", "{out_dir}", "--demucs-cmd",
               json.dumps([sys.executable, "-I", str(fake)]))
    gate = vocalgate.VocalGate(command, "vocals.wav", -35.0, 120.0, "test")
    result = vocalgate.run(gate, bed, out)
    assert result["status"] in ("PASS", "FAIL") and result["vocals"]["path"] == "vocals.wav", result
