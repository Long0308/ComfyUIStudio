"""Run context (episode, folders, flags) and the placeholder resolver of the run recipe.

Placeholders are the only way a recipe reaches a path: ``{episode}``, ``{episode_file}``, ``{episode_root}``,
``{engine_dir}``, ``{episode_id}``, ``{domain}``, ``{skill_root}``, ``{stages_root}``, ``{stage_dir}``,
``{stage:<id>}``, ``{file:<episode.files key>}``, ``{run_dir}``, ``{runs_root}``, ``{scratch}``, ``{shot}``,
``{approved_sha}``.  An unresolvable one raises :class:`Unresolved` naming the key, so the orchestrator can
report the stage as blocked instead of running a verb with a hole in its argv.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config.loader import SKILL_ROOT, find_episode_file
from ..core.errors import Uncertain
from ..core.io import read_json

_PLACEHOLDER = re.compile(r"\{([a-z_]+)(?::([A-Za-z0-9_.-]+))?\}")


class Unresolved(Exception):
    """A placeholder has no value (missing episode.files key, no shot, no approval ...)."""

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(f"{{{key}}}: {reason}")
        self.key = key
        self.reason = reason


def new_run_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{os.getpid()}"


@dataclass(frozen=True)
class RunContext:
    ref: str
    episode_file: Path
    episode_root: Path
    engine_dir: Path
    episode: dict[str, Any]
    stages_root: Path
    runs_root: Path
    run_id: str
    run_dir: Path
    scratch: Path
    approve_gpu: bool
    dry_run: bool
    skill_root: Path = SKILL_ROOT
    proof_required: bool = False        # recipe `human_proof: required`: a typed name never opens a gate
    gpu_proof: Path | None = None       # --gpu-proof FILE: the signed scope that --approve-gpu alone lacks

    @property
    def episode_id(self) -> str:
        return str(self.episode["episode_id"])

    @property
    def domain_id(self) -> str:
        return str(self.episode["domain"])

    @property
    def ledger_dir(self) -> Path:
        return self.runs_root / "ledger"

    @property
    def approvals_dir(self) -> Path:
        return self.runs_root / "approvals"

    def stage_dir(self, stage_id: str) -> Path:
        return self.stages_root / stage_id

    def episode_file_of(self, key: str) -> Path:
        files = self.episode.get("files") or {}
        value = files.get(key)
        if not isinstance(value, str) or not value:
            raise Unresolved(f"file:{key}", f"episode.files.{key} is not declared in {self.episode_file.name}")
        return (self.engine_dir / value).resolve()


def load_run_context(ref: str, *, runs_root: str | Path | None = None, run_dir: str | Path | None = None,
                     stages_root: str | Path | None = None, scratch: str | Path | None = None,
                     approve_gpu: bool = False, dry_run: bool = False, run_id: str | None = None,
                     gpu_proof: str | Path | None = None) -> RunContext:
    """Resolve the episode (path, root or slug) and the run folders; nothing is created here."""
    episode_file = find_episode_file(ref)
    episode = read_json(episode_file)
    if not isinstance(episode, dict) or not isinstance(episode.get("domain"), str) or "episode_id" not in episode:
        raise Uncertain(f"{episode_file}: not an episode document (needs episode_id and domain)")
    engine_dir = episode_file.parent
    episode_root = engine_dir.parent
    rid = run_id or new_run_id()
    root = Path(runs_root) if runs_root else episode_root / "engine" / "runs"
    folder = Path(run_dir) if run_dir else root / rid
    if run_dir and not runs_root:
        root = folder.parent
    scratch_dir = Path(scratch) if scratch else Path(tempfile.gettempdir()) / "jjv-run" / str(episode["episode_id"])
    return RunContext(ref=ref, episode_file=episode_file, episode_root=episode_root, engine_dir=engine_dir,
                      episode=episode, stages_root=Path(stages_root) if stages_root else episode_root / "engine" / "stages",
                      runs_root=root, run_id=rid, run_dir=folder, scratch=scratch_dir, approve_gpu=approve_gpu,
                      dry_run=dry_run, gpu_proof=Path(gpu_proof) if gpu_proof else None)


def _value(ctx: RunContext, key: str, arg: str | None, stage_id: str, extra: dict[str, str]) -> str:
    simple = {
        "episode": ctx.ref, "episode_file": str(ctx.episode_file), "episode_root": str(ctx.episode_root),
        "engine_dir": str(ctx.engine_dir), "episode_id": ctx.episode_id, "domain": ctx.domain_id,
        "skill_root": str(ctx.skill_root), "stages_root": str(ctx.stages_root), "stage_dir": str(ctx.stage_dir(stage_id)),
        "run_dir": str(ctx.run_dir), "runs_root": str(ctx.runs_root), "scratch": str(ctx.scratch),
    }
    if key in extra:
        return extra[key]
    if key == "file":
        if not arg:
            raise Unresolved("file", "needs a key: {file:<episode.files key>}")
        return str(ctx.episode_file_of(arg))
    if key == "stage":
        if not arg:
            raise Unresolved("stage", "needs a stage id: {stage:<id>}")
        return str(ctx.stage_dir(arg))
    if key in simple and arg is None:
        return simple[key]
    if key in ("shot", "approved_sha"):
        raise Unresolved(key, "only defined inside a per_shot step" if key == "shot" else "no current approval for this shot")
    raise Unresolved(key if arg is None else f"{key}:{arg}", "unknown placeholder")


def resolve(text: str, ctx: RunContext, stage_id: str, extra: dict[str, str] | None = None) -> str:
    """Substitute every placeholder in ``text``; raises :class:`Unresolved` for the first hole."""
    values = extra or {}
    return _PLACEHOLDER.sub(lambda m: _value(ctx, m.group(1), m.group(2), stage_id, values), text)


def resolve_all(items: tuple[str, ...], ctx: RunContext, stage_id: str, extra: dict[str, str] | None = None) -> tuple[str, ...]:
    return tuple(resolve(item, ctx, stage_id, extra) for item in items)


def shots_of(path: Path) -> list[str]:
    """Shot ids of a ``shots.json`` (``shots[].shot``); a missing or malformed file is Unresolved."""
    if not path.is_file():
        raise Unresolved("shot", f"{path} does not exist (per_shot steps need it)")
    doc = read_json(path)
    rows = doc.get("shots") if isinstance(doc, dict) else None
    ids = [row.get("shot") for row in rows or [] if isinstance(row, dict)]
    if not ids or not all(isinstance(s, str) and s for s in ids):
        raise Unresolved("shot", f"{path.name} has no shots[].shot list")
    return list(dict.fromkeys(ids))
