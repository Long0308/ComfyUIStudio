"""World cho test ``jjv video``: episode H3World (domain tuỳ chọn) + shotlist ``jjv/script/v1`` + routes test.

Không GPU, không mạng ngoài 127.0.0.1 (FakeComfy), không chạm khoá thật, không ghi vào thư mục production.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

# h3_fixtures nằm ở tests/h3/: chỉ có trên sys.path khi pytest collect cả tests/h3, nên thêm tường minh để các
# file test_video_*.py chạy được một mình (không phụ thuộc thứ tự collect).
_TESTS = Path(__file__).resolve().parent
for _folder in (_TESTS, _TESTS / "h3"):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

from h3_fixtures import EP, SHOT, FakeProbe, H3World, fake_with_video, ok_ps, sha_file  # noqa: E402

CARTOON, LIVE = "jenniejoy_cartoon_3d", "newtecons_live_action"
FIXTURE_PORTS = {"face": [["31", "image"]], "anchor": [["30", "image"]], "wav": [["7", "audio"]], "prompt": "19.value",
                 "length": "6.length", "seed": "11.noise_seed", "editorial_node": "63",
                 "output_ports": [["18", "filename_prefix"], ["63", "filename_prefix"]]}
STAGES = ["01 DOC SHOTLIST", "02 VIET PROMPT", "03 AI QUAY VIDEO", "04 LEN 1080P", "05 LUU & QUAY TIEP"]
CODE = {"subject": "alice speaks at the table", "style": "test style", "composition": "medium shot",
        "lighting": "soft light", "material": "cloth", "negative": "blurry"}
TOKEN_TEXT = "user-said-yes-2026-10-31"
TOKEN = f"token:{TOKEN_TEXT}"  # CR-VENG: --gpu-approved chỉ nhận token:<text> hoặc receipt file có thật


def write_routes(path: Path, templates: dict[str, Path], *, allowed: list[str] | None = None,
                 qualified: dict[str, dict] | None = None, backends: list[str] | None = None) -> Path:
    rows = {}
    for domain, template in templates.items():
        rows[domain] = {"template": {"path": str(template), "sha256": sha_file(template)}, "ports": FIXTURE_PORTS,
                        "frame_grid": {"step": 17, "offset": 5, "source": "fixture"}, "seed_base": 1000,
                        "h3_route": "h3-ref2va",
                        "upscale": {"default_backend": "none", "target": "1920x1080",
                                    "backends": backends or ["none", "seedvr2-7b", "lanczos"],
                                    "qualified": (qualified or {}).get(domain, {})}}
    document = {"schema": "jjv/video-routes/v1", "id": "video-routes-test",
                "allowed_domains": list(templates) if allowed is None else allowed,
                "shotlist_schemas": ["jjv/script/v1"], "stages": STAGES, "max_lanes": 10, "domains": rows}
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def shot_row(shot: str = SHOT, speaker: str = "alice", listener: str | None = None, duration: float = 4.0) -> dict:
    return {"id": shot, "speaker": speaker, **({"listener": listener} if listener else {}),
            "speech_text": f"Hello from {shot}", "duration_s": duration, "visual": "Alice at the table",
            "continuity": {"setting_id": "SET_A", "camera_id": "CAM_A"},
            "source": {"scene_id": "SCENE_02", "prompt_as_code": CODE}}


def shotlist_document(domain: str, refs: dict[str, Path], shots: list[dict] | None = None, episode_id: str = EP) -> dict:
    return {"schema": "jjv/script/v1", "film_id": episode_id, "domain": domain, "fps": 24,
            "character_references": {role: {"character_id": role, "bible_name": role.title(), "canonical_path": str(path),
                                            "canonical_sha256": sha_file(path)} for role, path in refs.items()},
            "shots": shots or [shot_row()]}


class VideoWorld:
    def __init__(self, tmp: Path, *, domain: str = CARTOON, comfy_url: str = "http://127.0.0.1:1",
                 shots: list[dict] | None = None) -> None:
        self.h3 = H3World(tmp, comfy_url=comfy_url, domain=domain)
        self.tmp, self.domain, self.root = Path(tmp), domain, self.h3.root
        self.out = self.tmp / "video-v001"
        graph = json.loads(self.h3.template.read_text("utf-8"))
        graph["6"]["inputs"].update(width=864, height=480)
        self.h3.template.write_text(json.dumps(graph), encoding="utf-8")
        self.routes = write_routes(self.tmp / "video-routes.json", {domain: self.h3.template})
        self.shotlist = self.tmp / "shotlist.json"
        self.shotlist.write_text(json.dumps(shotlist_document(domain, {"alice": self.h3.face, "mother": self.h3.anchor},
                                                              shots)), encoding="utf-8")

    def ctx(self):
        return self.h3.ctx()

    def base(self, verb: str, *more: str) -> list[str]:
        return [verb, "--episode", str(self.root), "--out", str(self.out), "--machine", str(self.h3.world.machine_path),
                "--routes", str(self.routes), *more]

    def plan(self, *more: str) -> tuple[int, dict]:
        return run_video(self.base("plan", "--shotlist", str(self.shotlist), *more))

    def run(self, *more: str) -> tuple[int, dict]:
        return run_video(self.base("run", *more))

    def status(self, *more: str) -> tuple[int, dict]:
        return run_video(self.base("status", *more))

    def accept(self, *more: str) -> tuple[int, dict]:
        return run_video(self.base("accept", *more))

    def state(self, shot: str = SHOT) -> dict:
        return json.loads((self.out / shot / "state.json").read_text("utf-8"))

    def prompt_text(self, shot: str = SHOT, revision: int = 1) -> str:
        return (self.out / shot / "prompt" / f"r{revision:03d}" / "prompt.txt").read_text("utf-8")

    def write_h3_inputs(self, shot: str = SHOT, revision: int = 1, **mouth_overrides) -> Path:
        """``h3-inputs.json`` như ``jjv h3 inputs`` dựng: media đã băm + prompt/length/seed đã đóng băng."""
        receipt = json.loads((self.out / shot / "plan-receipt.json").read_text("utf-8"))
        size = {receipt["geometry"]["ports"][a]: receipt["geometry"][a] for a in ("width", "height")}
        mouth = {**size, "19.value": self.prompt_text(shot, revision), "6.length": receipt["length"]["frames"],
                 "11.noise_seed": receipt["seed"], **mouth_overrides}
        document = {"schema": "jjv/h3-inputs/v1", "episode_id": EP, "domain": self.domain, "voice_dir": "voice",
                    "shots": [self.h3.row(shot=shot, mouth=mouth)]}
        path = self.out / "h3-inputs.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def handles(self, fake):
        from engine.comfy.client import ComfyClient
        from engine.video.render import ComfyHandles

        return ComfyHandles(settings=self.h3.settings(), client=ComfyClient(fake.url, timeout_seconds=5),
                            probe=FakeProbe(), ps=ok_ps)

    def run_direct(self, *, completion: bool = True, lanes: int = 1, dry_run: bool = False, gpu_token: str | None = None,
                   fake=None, backend: str | None = None) -> dict:
        from engine.video import run as run_mod

        return run_mod.run(self.ctx(), self.out, completion=completion, lanes=lanes, dry_run=dry_run, gpu_token=gpu_token,
                           comfy=self.handles(fake) if fake is not None else None, routes_path=self.routes,
                           backend=backend, wait_timeout=5)


def run_video(argv: list[str]) -> tuple[int, dict]:
    """Qua đúng dây argparse thật, trong process; trả ``(exit code, JSON stdout hoặc {})``."""
    from engine.core.errors import EngineError, exit_code_for
    from engine.video import cli

    parser = argparse.ArgumentParser()
    cli.register_cli(parser.add_subparsers(dest="stage", required=True))
    buffer = io.StringIO()
    code = 0
    with redirect_stdout(buffer):
        try:
            code = cli.run_video(parser.parse_args(["video", *argv]))
        except EngineError as error:
            code = exit_code_for(error)
            print(json.dumps({"ok": False, "error": str(error)}))
    text = buffer.getvalue().strip()
    return code, json.loads(text) if text.startswith("{") else {}


def hold_executor_lock(world: VideoWorld, holder: str = "other-executor") -> Path:
    """Giả lập một executor khác ĐANG SỐNG giữ khoá EXECUTOR máy (pid của chính test, token lạ)."""
    import os
    import socket

    lock = world.h3.settings().executor_lock_path
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"schema": "jjv/run-lock/v1", "pid": os.getpid(), "host": socket.gethostname(),
                                "process_start_time": None, "token": "f" * 32, "plan": holder}), encoding="utf-8")
    return lock


def watch_lock_at_post(fake, lock: Path) -> list[dict]:
    """Bọc ``fake.on_post``: ghi lại khoá EXECUTOR có tồn tại (và thân khoá) đúng lúc ComfyUI nhận POST."""
    seen: list[dict] = []
    inner = fake.on_post

    def on_post(payload: dict, prompt_id: str):
        body = json.loads(lock.read_text("utf-8")) if lock.is_file() else None
        seen.append({"exists": lock.is_file(), "body": body})
        return inner(payload, prompt_id) if inner else None

    fake.on_post = on_post
    return seen


__all__ = ["VideoWorld", "run_video", "write_routes", "shotlist_document", "shot_row", "hold_executor_lock",
           "watch_lock_at_post", "fake_with_video", "FakeProbe", "ok_ps", "CARTOON", "LIVE", "STAGES", "FIXTURE_PORTS",
           "TOKEN", "TOKEN_TEXT", "EP", "SHOT", "sha_file"]
