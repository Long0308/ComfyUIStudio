"""A self-contained SeedVR2 execution rig for M4 tests.

Real: the resolved ep04 config layers (domain, recipe, episode templates), the pinned pilot
graph, ``build_plan``/``write_plan`` and the whole executor.  Fake: ComfyUI (local HTTP server),
the machine paths (all under tmp_path), ffprobe and ffmpeg.  Fake media files carry their own
properties in their first bytes (``media|frames|w|h|tag``), so copies and hard links keep them.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from engine.comfy.settings import ComfySettings
from engine.config import loader
from engine.core.errors import Uncertain
from engine.core.io import sha256_file
from engine.media.probe import VideoInfo
from engine.seedvr2.chunking import plan_chunks
from engine.seedvr2.execplan import ExecPlan, load_exec_plan, select_tasks
from engine.seedvr2.execute import Executor
from engine.seedvr2.plan import PLAN_FILE, build_plan, write_plan
from fake_comfy import FakeComfy

SHOT = "S01_A"


def media_bytes(frames: int, width: int, height: int, tag: str) -> bytes:
    return f"media|{frames}|{width}|{height}|{tag}".encode("ascii")


def fake_probe(path: Path, *, count_packets: bool = False) -> VideoInfo:
    head = Path(path).read_bytes()[:200]
    parts = head.decode("ascii", "replace").split("|")
    if parts[0] != "media" or len(parts) < 5:
        raise Uncertain(f"fake probe: {path} is not a fake media file")
    return VideoInfo(frames=int(parts[1]), width=int(parts[2]), height=int(parts[3]), fps=Fraction(24))


class FakeFfmpeg:
    """Understands exactly the two ffmpeg commands the engine builds: core trim and concat."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list) -> "subprocess.CompletedProcess[str]":
        self.commands.append([str(c) for c in command])
        out = Path(command[-1])
        if "concat" in command:
            listed = re.findall(r"file '(.*)'", Path(command[command.index("-i") + 1]).read_text())
            infos = [fake_probe(Path(p)) for p in listed]
            out.write_bytes(media_bytes(sum(i.frames for i in infos), infos[0].width, infos[0].height, "shot"))
        else:
            vf = command[command.index("-vf") + 1]
            start, end = map(int, re.search(r"start_frame=(\d+):end_frame=(\d+)", vf).groups())
            w, h = map(int, re.search(r"crop=(\d+):(\d+):", vf).groups())
            out.write_bytes(media_bytes(end - start, w, h, f"core-{start}"))
        return subprocess.CompletedProcess(command, 0, "", "")

    def trims(self) -> list[str]:
        return [c[c.index("-vf") + 1] for c in self.commands if "-vf" in c]


class FakeDocker:
    """ContainerProbe double.  Every ``restart()`` gives the container a NEW instance identity (StartedAt text).

    ``started_at`` (a float) is only the VM-clock reading; the engine proves a restart by the StartedAt
    TEXT changing between the dispatch intent and now, never by comparing it with the host clock.
    """

    BEFORE = "fake-instance-0"

    def __init__(self, started_at: float = 1.0, running: bool = True, faults: list[str] | None = None) -> None:
        self.started_at, self.running, self.faults = started_at, running, faults or []
        self.generation = 0
        self._restarted = False
        self.state_calls = 0
        self.unreadable = False

    @property
    def restarted(self) -> bool:
        return self._restarted

    @restarted.setter
    def restarted(self, value: bool) -> None:
        self._restarted = bool(value)
        if self._restarted and self.generation == 0:
            self.generation = 1

    def restart(self) -> None:
        self._restarted = True
        self.generation += 1

    def state(self, container: str):
        from engine.comfy.docker_probe import ContainerState
        self.state_calls += 1
        if self.unreadable:
            return None
        started = time.time() + 1.0 if self._restarted else self.started_at
        text = f"fake-instance-{self.generation}" if self._restarted else self.BEFORE
        return ContainerState(started_at=started, started_at_text=text, running=self.running, restart_count=1)

    def fault_lines(self, container: str, since: float) -> dict:
        return {"available": True, "since_unix": since, "matched_lines": list(self.faults),
                "line_count": len(self.faults), "patterns": ["cuda error"] if self.faults else []}


_REAL = None


def real_config() -> loader.ResolvedConfig:
    global _REAL
    if _REAL is None:
        _REAL = loader.resolve_episode("04-milk-and-mom")
    return _REAL


@dataclass
class Rig:
    root: Path
    fake: FakeComfy
    config: loader.ResolvedConfig
    recipe: dict
    plan: ExecPlan
    settings: ComfySettings
    ffmpeg: FakeFfmpeg
    raw_frames: dict[str, int] = field(default_factory=dict)  # chunk name -> frames Comfy "renders"

    def executor(self, **kw: Any) -> Executor:
        kw.setdefault("probe", fake_probe)
        kw.setdefault("runner", self.ffmpeg)
        kw.setdefault("emit", lambda message: None)
        kw.setdefault("container_probe", FakeDocker())  # never the real docker in tests
        return Executor(config=self.config, recipe=self.recipe, plan=self.plan, settings=self.settings,
                        repo_root=loader.REPO_ROOT, **kw)

    def tasks(self, only: str | None = None, max_chunks: int | None = None) -> list:
        return select_tasks(self.plan.tasks, only=only, max_chunks=max_chunks)

    def chunk_dir(self, index: int) -> Path:
        return self.plan.root / "runs" / SHOT / f"chunk-{index:04d}"

    def job(self, index: int) -> dict:
        import json
        return json.loads((self.chunk_dir(index) / "job.json").read_text("utf-8"))

    def reload_plan(self) -> ExecPlan:
        return load_exec_plan(self.plan.path, self.config, self.recipe)


def make_rig(tmp_path: Path, fake: FakeComfy, *, frames: int = 40, auto_complete: bool = True,
             history_timeout: float = 5.0) -> Rig:
    real = real_config()
    recipe = real.recipes["seedvr2"]
    episode_root = tmp_path / "episode"
    plan_dir = episode_root / "run"
    clip = episode_root / "clips" / f"{SHOT}.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(media_bytes(frames, 864, 480, "source"))
    shot = {"shot": SHOT, "logical_shot": SHOT,
            "clip": {"path": f"clips/{SHOT}.mp4", "sha256": sha256_file(clip), "frames": frames}}
    comfy_root = tmp_path / "comfy"
    machine = {**real.machine, "gpu_lock_path": str(tmp_path / "gpu.lock"),
               "comfy": {"url": fake.url, "root": str(comfy_root), "output_dir": str(comfy_root / "output"),
                         "container": "test-container"}}
    config = dataclasses.replace(real, shots=[shot], machine=machine, episode_root=str(episode_root))
    for chunk in plan_chunks(frames, recipe["geometry"]):
        segment = plan_dir / SHOT / "chunks" / f"chunk-{chunk['index']:04d}" / "source-segment.mp4"
        segment.parent.mkdir(parents=True)
        segment.write_bytes(media_bytes(chunk["segment_frames"], 864, 480, f"seg{chunk['index']}"))
    result = build_plan(config, repo_root=loader.REPO_ROOT, segments_root=plan_dir, probe=fake_probe)
    write_plan(plan_dir, result)
    settings = ComfySettings(base_url=fake.url, lock_path=tmp_path / "gpu.lock", input_dir=comfy_root / "input",
                             output_dir=comfy_root / "output", container="test-container",
                             lock_timeout_seconds=0.3, poll_seconds=0.01, http_timeout_seconds=5,
                             history_timeout_seconds=history_timeout, min_history_timeout_seconds=0)
    rig = Rig(root=tmp_path, fake=fake, config=config, recipe=recipe,
              plan=load_exec_plan(plan_dir / PLAN_FILE, config, recipe), settings=settings, ffmpeg=FakeFfmpeg())
    segment_frames = {t.name: t.chunk["segment_frames"] for t in rig.plan.tasks}
    g = rig.plan.geometry

    def render(payload: dict, prompt_id: str) -> dict:
        prefix = payload["prompt"]["15"]["inputs"]["filename_prefix"]
        subfolder, name = prefix.rsplit("/", 1)
        target = comfy_root / "output" / subfolder / f"{name}_00001_.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        count = rig.raw_frames.get(name, segment_frames[name])
        target.write_bytes(media_bytes(count, g.processing_width, g.processing_height, f"raw-{name}"))
        return {"15": {"images": [{"filename": target.name, "subfolder": subfolder, "type": "output"}],
                       "animated": [True]}}

    fake.on_post = render
    fake.auto_complete = auto_complete
    return rig
