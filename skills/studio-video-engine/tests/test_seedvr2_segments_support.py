"""Shared fakes for the segments / coverage / tails tests (no tests live here).

Fake media files carry their own frame identities: ``media|frames|w|h|tag\\n<json list of frame ids>``.  The fake
ffmpeg understands exactly the commands the engine builds (trim cut, core trim + crop, concat, framemd5), so a
cut, a trim or a concat moves frame ids the way the real tools move pixels, and "frame md5 equal" means
"same frame ids".  Real ffmpeg is used only by the tests that say so.  No ComfyUI beyond ``FakeComfy`` (a local
fake server), no GPU, no network.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from engine.comfy.settings import ComfySettings
from engine.core.errors import Uncertain
from engine.core.io import sha256_file
from engine.media.probe import VideoInfo
from engine.seedvr2.coverage import Read
from exec_fixtures import FakeDocker, real_config

NATIVE_W, NATIVE_H = 864, 480


def write_media(path: Path, ids: list[str], width: int, height: int, tag: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"media|{len(ids)}|{width}|{height}|{tag}\n".encode() + json.dumps(ids).encode())
    return path


def read_ids(path: Path) -> list[str]:
    return json.loads(Path(path).read_bytes().split(b"\n", 1)[1])


def fake_probe(path: Path, *, count_packets: bool = False) -> VideoInfo:
    head = Path(path).read_bytes()[:200].decode("ascii", "replace").split("\n", 1)[0].split("|")
    if head[0] != "media" or len(head) < 5:
        raise Uncertain(f"fake probe: {path} is not a fake media file")
    return VideoInfo(frames=int(head[1]), width=int(head[2]), height=int(head[3]), fps=Fraction(24))


def md5_of(frame_id: str) -> str:
    return hashlib.md5(frame_id.encode()).hexdigest()


class FakeRunner:
    """ffmpeg double: cut/trim (+crop), concat and framemd5 over fake media."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.corrupt: Callable[[Path, list[str]], list[str]] | None = None  # (output path, ids) -> ids written

    def cuts(self) -> list[list[str]]:
        return [c for c in self.commands if "-vf" in c and "framemd5" not in c]

    @staticmethod
    def _slice(ids: list[str], vf: str | None) -> list[str]:
        match = re.search(r"trim=start_frame=(\d+):end_frame=(\d+)", vf or "")
        return ids[int(match.group(1)):int(match.group(2))] if match else ids

    def __call__(self, command: list) -> "subprocess.CompletedProcess[str]":
        cmd = [str(c) for c in command]
        self.commands.append(cmd)
        if "framemd5" in cmd:
            ids = self._slice(read_ids(Path(cmd[cmd.index("-i") + 1])), cmd[cmd.index("-vf") + 1] if "-vf" in cmd else None)
            lines = "".join(f"0, {i}, {i}, 1, 1, {md5_of(x)}\n" for i, x in enumerate(ids))
            return subprocess.CompletedProcess(cmd, 0, "#format: frame checksums\n" + lines, "")
        out = Path(cmd[-1])
        if "concat" in cmd:
            listed = re.findall(r"file '(.*)'", Path(cmd[cmd.index("-i") + 1]).read_text())
            ids = [x for p in listed for x in read_ids(Path(p))]
            info = fake_probe(Path(listed[0]))
            write_media(out, ids, info.width, info.height, "shot")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        source = Path(cmd[cmd.index("-i") + 1])
        vf = cmd[cmd.index("-vf") + 1]
        ids = self._slice(read_ids(source), vf)
        info = fake_probe(source)
        crop = re.search(r"crop=(\d+):(\d+):", vf)
        width, height = (int(crop.group(1)), int(crop.group(2))) if crop else (info.width, info.height)
        if self.corrupt:
            ids = self.corrupt(out, ids)
        write_media(out, ids, width, height, "cut")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def sha(path: Path) -> str:
    return sha256_file(path)


def make_world(tmp_path: Path, *, comfy_url: str = "http://127.0.0.1:1"):
    """A two-shot episode on fake media plus one native tail source; returns a namespace."""
    real = real_config()
    root = tmp_path / "episode"
    shots, specs = [], {"S01_A": 40, "S02_A": 30}
    for shot_id, frames in specs.items():
        clip = write_media(root / "clips" / f"{shot_id}.mp4", [f"{shot_id}:{i}" for i in range(frames)],
                           NATIVE_W, NATIVE_H)
        shots.append({"shot": shot_id, "logical_shot": shot_id,
                      "clip": {"path": f"clips/{shot_id}.mp4", "sha256": sha(clip), "frames": frames}})
    native = write_media(root / "native" / "S01_A-native.mp4", [f"S01_A:{i}" for i in range(47)],
                         NATIVE_W, NATIVE_H)  # editorial == native[0:40]
    comfy_root = tmp_path / "comfy"
    machine = {**real.machine, "gpu_lock_path": str(tmp_path / "gpu.lock"),
               "comfy": {"url": comfy_url, "root": str(comfy_root), "output_dir": str(comfy_root / "output"),
                         "container": "test-container"}}
    config = dataclasses.replace(real, shots=shots, machine=machine, episode_root=str(root))
    source = {"path": str(native), "sha256": sha(native), "frames": 47}
    transition = {"id": "T40", "delivery_start_frame": 50, "output_frames": 3, "delivery_fps": 30}
    reads = [Read("S01_A", 0, 40, "dialogue S01_A"), Read("S02_A", 0, 30, "dialogue S02_A"),
             Read("S01_A", 40, 43, "T40 outgoing tail", source, transition)]
    return SimpleNamespace(root=root, config=config, recipe=real.recipes["seedvr2"], reads=reads, native=native,
                           source=source, comfy_root=comfy_root, tmp=tmp_path, runner=FakeRunner())


def make_settings(world, url: str) -> ComfySettings:
    return ComfySettings(base_url=url, lock_path=world.tmp / "gpu.lock", input_dir=world.comfy_root / "input",
                         output_dir=world.comfy_root / "output", container="test-container",
                         lock_timeout_seconds=0.3, poll_seconds=0.01, http_timeout_seconds=5,
                         history_timeout_seconds=5.0, min_history_timeout_seconds=0)


def install_render(world, fake, geometry) -> None:
    """Make the fake ComfyUI 'restore' a chunk: raw frames are new ids, one per segment frame."""
    def render(payload: dict, prompt_id: str) -> dict:
        prefix = payload["prompt"]["15"]["inputs"]["filename_prefix"]
        subfolder, name = prefix.rsplit("/", 1)
        target = world.comfy_root / "output" / subfolder / f"{name}_00001_.mp4"
        segment = world.comfy_root / "input" / payload["prompt"]["1"]["inputs"]["file"]
        ids = [f"raw[{subfolder}]:{x}" for x in read_ids(segment)]
        write_media(target, ids, geometry.processing_width, geometry.processing_height, "raw")
        return {"15": {"images": [{"filename": target.name, "subfolder": subfolder, "type": "output"}],
                       "animated": [True]}}

    fake.on_post = render
    fake.auto_complete = True


def executor(world, plan, settings, **kw):
    from engine.config import loader
    from engine.seedvr2.execute import Executor
    kw.setdefault("probe", fake_probe)
    kw.setdefault("runner", world.runner)
    kw.setdefault("emit", lambda message: None)
    kw.setdefault("container_probe", FakeDocker())
    return Executor(config=world.config, recipe=world.recipe, plan=plan, settings=settings,
                    repo_root=loader.REPO_ROOT, **kw)
