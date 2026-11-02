"""Fixtures of the M8 orchestrator tests: a tiny episode world and a recording fake runner.

No verb is ever really run: the fake runner records every argv and, for a few verbs, writes the receipt the
stage promises (so reuse can be measured).  GPU verbs are never reached unless a test says --approve-gpu, and
even then only the fake sees them.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path

from engine.config.loader import SKILL_ROOT

CARTOON = "jenniejoy_cartoon_3d"
LIVE = "newtecons_live_action"
SHOTS = ["S01_A", "S01_B"]


def write(path: Path, data: dict | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=1), encoding="utf-8")
    return path


@dataclass(frozen=True)
class RunWorld:
    root: Path                 # episode root
    runs_root: Path
    stages_root: Path

    @property
    def engine_dir(self) -> Path:
        return self.root / "engine"

    @property
    def episode_file(self) -> Path:
        return self.engine_dir / "episode.json"

    def stage(self, stage_id: str) -> Path:
        return self.stages_root / stage_id

    def base_argv(self, *more: str, dry_run: bool = False, approve_gpu: bool = False) -> list[str]:
        argv = ["run", "episode", "--episode", str(self.episode_file), "--runs-root", str(self.runs_root),
                "--stages-root", str(self.stages_root), "--scratch", str(self.root.parent / "scratch"), "--json", *more]
        if dry_run:
            argv.append("--dry-run")
        if approve_gpu:
            argv.append("--approve-gpu")
        return argv


def make_run_world(tmp_path: Path, *, domain: str = CARTOON, episode_id: str = "ep-fixture") -> RunWorld:
    root = tmp_path / "prod" / episode_id
    write(root / "engine" / "episode.json", {
        "schema": "jjv/episode/v1", "episode_id": episode_id, "film_id": episode_id, "title": "Fixture", "domain": domain,
        "files": {"shots": "shots.json", "script": "../script/script.json", "cast": "../characters/cast.json",
                  "shot_pack": "../script/shot-pack.json", "h3_spec": "../technical/h3-spec.json",
                  "master_config": "../editorial/master-config.json"}})
    write(root / "engine" / "shots.json", {"schema": "jjv/shots/v1", "episode_id": episode_id,
                                           "shots": [{"shot": s} for s in SHOTS]})
    write(root / "engine" / "boundaries.json", {"schema": "fixture", "rows": []})
    write(root / "script" / "script.json", {"schema": "jjv/script/v1", "status": "LOCKED", "lines": ["a"]})
    write(root / "script" / "shot-pack.json", {"schema": "fixture"})
    write(root / "characters" / "cast.json", {"schema": "jjv/cast/v1", "characters": []})
    return RunWorld(root=root, runs_root=tmp_path / "runs", stages_root=tmp_path / "stages")


def _flag(argv: tuple[str, ...], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None


@dataclass
class FakeRunner:
    """Records every argv; ``receipts`` maps a (stage, verb) prefix to the receipt file it fakes under --out (a name, or
    ``(name, payload)`` for a receipt whose content matters); ``stdout`` maps a prefix to the JSON the verb prints."""

    calls: list[tuple[str, ...]] = field(default_factory=list)
    receipts: dict[tuple[str, ...], str | tuple[str, dict]] = field(default_factory=dict)
    fail: dict[tuple[str, ...], int] = field(default_factory=dict)
    stdout: dict[tuple[str, ...], dict] = field(default_factory=dict)

    def __call__(self, argv: tuple[str, ...]):
        from engine.run.orchestrator import StepResult
        self.calls.append(tuple(argv))
        for prefix, code in self.fail.items():
            if tuple(argv[:len(prefix)]) == prefix:
                return StepResult(code, json.dumps({"ok": False, "error": "fake failure"}), "")
        for prefix, spec in self.receipts.items():
            if tuple(argv[:len(prefix)]) == prefix:
                name, payload = spec if isinstance(spec, tuple) else (spec, {"schema": "fixture-receipt", "argv": list(argv)})
                out = _flag(argv, "--out")
                if out:   # --out is a folder for most verbs, the file itself for the renders (review.mp4)
                    target = Path(out) if Path(out).name == name else Path(out) / name
                    write(target, payload)
        printed = next((doc for prefix, doc in self.stdout.items() if tuple(argv[:len(prefix)]) == prefix), {"ok": True})
        return StepResult(0, json.dumps(printed), "")

    def verbs(self) -> list[str]:
        return [" ".join(c[:3]) for c in self.calls]

    def touched_gpu(self) -> list[tuple[str, ...]]:
        return [c for c in self.calls if "--execute" in c or "--approve-gpu" in c or c[:2] == ("layout", "render")
                or c[:2] == ("images", "submit")]


def jjv_module():
    spec = importlib.util.spec_from_file_location("jjv_cli_m8", SKILL_ROOT / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cli(capsys, monkeypatch, runner: FakeRunner, argv: list[str]) -> tuple[int, dict]:
    """``jjv`` main with the fake runner injected in place of the subprocess runner."""
    from engine.run import cli as run_cli_mod
    monkeypatch.setattr(run_cli_mod, "default_runner", runner)
    code = jjv_module().main(argv)
    out = capsys.readouterr().out
    return code, json.loads(out)
