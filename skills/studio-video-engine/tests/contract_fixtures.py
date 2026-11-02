"""Fixtures for the delivery-contract tests: a from-scratch fake episode (any length) under tmp_path.

The domain, schemas and recipes are copied (never edited) so a test can prove that a 60 s or a 150 s
film validates with NO domain edit.  WAVs are tiny real RIFF files, so the planner reads real durations.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from config_fixtures import SHA, World, make_world, _track
from engine.config import cli as contract_cli

RATE = 8000


def write_wav(path: Path, seconds: float) -> None:
    """A silent 16-bit mono RIFF/WAVE of ``seconds`` (rounded to a whole sample)."""
    frames = round(seconds * RATE)
    data = b"\x00\x00" * frames
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16)
              + b"data" + struct.pack("<I", len(data)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + data)


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_script_world(tmp_path: Path, *, lines: list[float], vocab: list[float], end_line: float = 1.6,
                      intro_frames: int = 60, pins: dict | None = None) -> tuple[World, Path]:
    """A film with one dialogue shot per entry of ``lines`` (WAV seconds) and one card per entry of ``vocab``.

    Returns the world and the contract-inputs path.  ``shots.json`` is NOT written yet: the contract
    decides the clip lengths first (see :func:`write_shots_from_plan`).
    """
    world = make_world(tmp_path, engine_name="script")
    root = world.engine_dir.parent
    inputs = {"schema": "jjv/contract-inputs/v1", "intro_frames": intro_frames,
              "lines": [{"id": f"S{i + 1:02d}_A", "wav": f"audio/line{i}.wav"} for i in range(len(lines))],
              "vocab": [{"term": f"Word{i}", "wav": f"audio/word{i}.wav"} for i in range(len(vocab))],
              "end_line": {"wav": "audio/end.wav"}, "pins": pins or {}}
    for i, seconds in enumerate(lines):
        write_wav(root / f"audio/line{i}.wav", seconds)
    for i, seconds in enumerate(vocab):
        write_wav(root / f"audio/word{i}.wav", seconds)
    write_wav(root / "audio/end.wav", end_line)
    path = world.engine_dir / "contract-inputs.json"
    _write(path, inputs)
    world.edit_episode(lambda d: (d["files"].update(contract_inputs="contract-inputs.json"),
                                  d["files"].pop("review_config", None), d["files"].pop("shot_pack", None),
                                  d.pop("delivery_contract", None), d.pop("contract", None)))
    return world, path


def plan(world: World, inputs: Path, **target) -> dict:
    return contract_cli.plan_contract(world.episode_file, skill_root=world.skill_root, inputs_path=inputs, **target)


def write_shots_from_plan(world: World, planned: dict) -> None:
    """shots.json / mouth-boxes.json whose H3 clips are exactly what the plan allotted to each line."""
    rates = planned["domain"]["frame_rates"]
    num, den = rates["mapping"]["num"], rates["mapping"]["den"]
    rows = [s for s in planned["sections"] if s.kind == "dialogue"]
    shots, boxes = [], {}
    for i, section in enumerate(rows):
        clip = section.frames * den // num
        who = ("mother", "alice") if i % 2 == 0 else ("alice", "mother")
        entry = {"kind": "cut", "evidence": "fixture"}
        shots.append({
            "shot": section.id, "logical_shot": section.id, "speaker": who[0], "listener": who[1],
            "receipt_dir": f"technical/{section.id}", "entry": entry,
            "clip": {"path": f"clips/{section.id}.mp4", "sha256": SHA, "sha_source": "fixture", "frames": clip},
            "wav_binding": {"kind": "preparation_json_wav_sha256", "path": f"audio/line{i}.wav", "sha256": SHA,
                            "receipt_source": "fixture", "offset_s": 0.0}})
        boxes[section.id] = {who[0]: _track("speaker", clip - 1), who[1]: _track("listener", clip - 1)}
    world.edit(world.engine_dir / "shots.json", lambda d: d.update(episode_id="script-fixture", shots=shots))
    world.edit(world.engine_dir / "mouth-boxes.json", lambda d: d.update(episode_id="script-fixture", shots=boxes))
    world.edit_episode(lambda d: d.update(episode_id="script-fixture", film_id="script-fixture", title="Script fixture"))


def locked_world(tmp_path: Path, *, lines: list[float], vocab: list[float], seconds: float | None,
                 intro_frames: int = 60) -> tuple[World, dict]:
    """Plan to ``seconds`` (None: the floors), write the shots the plan implies, lock the contract."""
    world, inputs = make_script_world(tmp_path, lines=lines, vocab=vocab, intro_frames=intro_frames)
    planned = plan(world, inputs, target_seconds=seconds)
    write_shots_from_plan(world, planned)
    world.edit_episode(lambda d: d.update(timeline={**d["timeline"], **_timeline_of(planned)}))
    contract_cli.write_contract(world.episode_file, planned, skill_root=world.skill_root, machine_path=world.machine_path)
    return world, planned


def _timeline_of(planned: dict) -> dict:
    from engine.config import contract as contract_rules

    return contract_rules.timeline_from_contract(planned["contract"])
