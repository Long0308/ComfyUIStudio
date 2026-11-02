"""Fixtures for config tests: a throw-away copy of the data layers under tmp_path.

Nothing here points at the real lock path; the machine file copy is only ever parsed.
"""

from __future__ import annotations

import copy
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from engine.config.loader import DEFAULT_MACHINE_PATH, REPO_ROOT, SKILL_ROOT

REAL_EPISODE_ENGINE = (
    REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom" / "engine"
)
# Worlds are built from this frozen copy of the v008-era episode files (84 s, no contract), not from the
# live episode folder, which moves on with every cut (3444 f contract, generated files, backups).
SNAPSHOT_EPISODE_ENGINE = Path(__file__).resolve().parent / "fixtures" / "ep04-engine"
SHA = "ab" * 32
SNAPSHOT_IGNORE = shutil.ignore_patterns("__pycache__", ".*.tmp", "*.tmp", "*.bak*", "*.pyc")


def _copy_if_present(source: str, target: str, **kwargs) -> str:
    """copytree copy function: a file that vanishes mid-copy (a concurrent writer's temp file) is skipped."""
    try:
        return shutil.copy2(source, target, **kwargs)
    except FileNotFoundError:
        return target


def copy_snapshot(source: Path, target: Path) -> None:
    """Copy a data folder ignoring temp/backup files and tolerating files deleted while copying."""
    shutil.copytree(source, target, ignore=SNAPSHOT_IGNORE, copy_function=_copy_if_present)


@dataclass(frozen=True)
class World:
    skill_root: Path
    machine_path: Path
    engine_dir: Path

    @property
    def episode_file(self) -> Path:
        return self.engine_dir / "episode.json"

    def edit(self, path: Path, change: Callable[[dict], None]) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def edit_episode(self, change: Callable[[dict], None]) -> None:
        self.edit(self.episode_file, change)

    def data(self, relative: str) -> Path:
        return self.skill_root / relative


def _write_test_machine(target: Path) -> None:
    """This machine's file minus its stage-private blocks: a world starts unconfigured, so the stage tests
    that pass --python/--model/--voicestudio-url (or expect "not configured") keep their premise."""
    data = json.loads(DEFAULT_MACHINE_PATH.read_text(encoding="utf-8"))
    for key in ("voicestudio", "timing", "audio"):
        data.pop(key, None)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _allow_parity_recipe(domain_file: Path) -> None:
    """Test worlds also allow the legacy parity mix (the real domain keeps it OFF the list on purpose)."""
    data = json.loads(domain_file.read_text(encoding="utf-8"))
    data["audio"]["allowed_recipes"].append("audio/mix-legacy-v004-parity")
    domain_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_world(tmp_path: Path, *, engine_name: str = "ep") -> World:
    skill = tmp_path / "skill"
    for folder in ("schemas", "domains", "recipes"):
        copy_snapshot(SKILL_ROOT / folder, skill / folder)
    machine = tmp_path / "machine.json"
    _write_test_machine(machine)
    _allow_parity_recipe(skill / "domains" / "jenniejoy_cartoon_3d.json")
    engine = tmp_path / "prod" / engine_name / "engine"
    copy_snapshot(SNAPSHOT_EPISODE_ENGINE, engine)
    return World(skill, machine, engine)


def _shot(name: str, speaker: str, listener: str, frames: int, entry: dict) -> dict:
    return {
        "shot": name, "logical_shot": name, "speaker": speaker, "listener": listener,
        "receipt_dir": f"technical/{name}", "entry": entry,
        "clip": {"path": f"clips/{name}.mp4", "sha256": SHA, "sha_source": "fixture", "frames": frames},
        "wav_binding": {"kind": "preparation_json_wav_sha256", "path": f"audio/{name}.wav",
                        "sha256": SHA, "receipt_source": "fixture", "offset_s": 0.0},
    }


def _track(role: str, last: int) -> dict:
    return {"role": role, "keyframes": [[0, 10, 10, 5, 5], [last, 12, 12, 5, 5]], "active_frames": None}


def make_live_action_world(tmp_path: Path) -> World:
    """A minimal valid second-domain episode (45 s, 24 fps, 864 native frames of dialogue)."""
    world = make_world(tmp_path, engine_name="live")
    entries = [{"kind": "cut", "evidence": "fixture"},
               {"kind": "carry", "from_shot": "S01_A", "frame": 10, "evidence": "fixture"},
               {"kind": "cut", "evidence": "fixture"}]
    shots = [_shot(f"S0{i + 1}_A", "host", "guest", 288, entries[i]) for i in range(3)]
    world.edit(world.engine_dir / "shots.json", lambda d: d.update(
        episode_id="live-fixture", shots=shots))
    boxes = {s["shot"]: {"host": _track("speaker", 287), "guest": _track("listener", 287)}
             for s in shots}
    world.edit(world.engine_dir / "mouth-boxes.json", lambda d: d.update(
        episode_id="live-fixture", shots=boxes))

    def episode(data: dict) -> None:
        data.update(episode_id="live-fixture", film_id="live-fixture", title="Live fixture",
                    domain="newtecons_live_action", recipes={},
                    timeline={"intro_s": 3.0, "dialogue_s": 36.0, "outro_s": 6.0}, overrides={})

    world.edit_episode(episode)
    return world


def deep(data: dict) -> dict:
    return copy.deepcopy(data)
