"""``jjv video render`` / ``jjv video upscale`` (spec §3, CR-VENG): verb mỏng cho ĐÚNG MỘT shot.

Cả hai chạy trên :class:`engine.video.run.Scheduler` của ``run`` — cùng cổng (``--gpu-approved`` -> H3 qualification ->
h3-inputs -> khoá EXECUTOR máy; backend 1080p phải được domain qualify), cùng run receipt ``runs/run-NNN.json``.  Không
có đường đi riêng nào tới GPU: một shot đã qua bước này chỉ được đọc lại bằng chứng với ``--resume``, không bao giờ
POST lại hay upscale lại trong cùng revision.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import sha256_file
from ..layout.context import Context
from . import longtake as longtake_mod
from . import prompt as prompt_mod
from . import render as render_mod
from . import state as state_mod
from .run import Scheduler, gpu_approval_from


class ShotVerbs(Scheduler):
    """Scheduler của ``run`` cộng hai bước đơn lẻ; dùng đúng ``_render`` / ``_upscale`` / ``_finish`` của nó."""

    def _shot_state(self, shot: str, revision: int | None) -> dict[str, Any]:
        known = [row["shot"] for row in self.plan["shots"]]
        if shot not in known:
            raise Refused(f"shot {shot!r} is not in this plan ({known}); nothing was sent")
        state = state_mod.read_state(self.out, shot)
        if revision is not None and int(state["revision"]) != int(revision):
            raise Refused(f"{shot}: --revision {revision} is not the current revision {state['revision']}; nothing was sent")
        return state

    @staticmethod
    def _already_past(state: dict[str, Any], expected: str, verb: str, resume: bool) -> bool:
        """False khi shot đứng đúng ở ``expected``; True khi đã QUA bước này và ``--resume`` (chỉ đọc lại bằng chứng);
        Refused khi chưa tới bước này, hoặc đã qua mà không ``--resume`` (một shot không bao giờ làm lại một bước)."""
        current, states = state["state"], state_mod.STATES
        if states.index(current) < states.index(expected):
            raise Refused(f"{state['shot']} is {current}: it must be {expected} before `jjv video {verb}`; nothing was sent")
        if current == expected:
            return False
        if not resume:
            raise Refused(f"{state['shot']} is already {current} (receipts {sorted(state['receipts'])}); pass --resume to "
                          "re-read that evidence; a shot is never rendered or upscaled twice in one revision")
        return True

    def _gate_and_finish(self, shot: str, gate: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
        if gate is not None:
            self.gate = gate
            state_mod.set_gate(self.out, state_mod.read_state(self.out, shot), gate)
        return self._finish(shot=shot, **extra)

    def render_shot(self, shot: str, revision: int, route_name: str, *, resume: bool = False) -> dict[str, Any]:
        """03 cho một shot ``prompted``; ``--route`` phải là H3 route của domain (routes ``h3_route``)."""
        state = self._shot_state(shot, revision)
        plan_receipt = state_mod.verify_ref(self.out, state["receipts"]["plan"], "plan")
        self._take_decision(plan_receipt, route_name)
        done = self._already_past(state, "prompted", "render", resume)
        receipts = self._refs_ok(state)
        text, prompt_receipt = prompt_mod.read_prompt(self.out, shot, int(state["revision"]))
        self.prompts[shot] = {"shot": shot, "lane": 1, "revision": state["revision"], "stage": self.stages[1], "text": text,
                              "prompt_sha256": prompt_receipt["prompt"]["sha256"], "written": False, "reused": True,
                              "state": state["state"]}
        extra = {"verb": "render", "revision": int(state["revision"]), "route": route_name, "resumed": done}
        if done:
            self._record(shot, "render", "already", receipt=state["receipts"]["render"])
            return self._gate_and_finish(shot, None, **extra)
        return self._gate_and_finish(shot, self._render(state, receipts["plan"]), **extra)

    def upscale_shot(self, shot: str, source: Path, target: str, *, revision: int | None = None,
                     resume: bool = False) -> dict[str, Any]:
        """04 cho một shot ``rendered``; ``--source`` phải băm đúng native take của render receipt và ``--target`` phải là
        ``upscale.target`` của routes (không upscale file lạ, không geometry lạ)."""
        state = self._shot_state(shot, revision)
        done = self._already_past(state, "rendered", "upscale", resume)
        receipts = self._refs_ok(state)
        native = receipts["render"]["native"]
        source_path = Path(source)
        if not source_path.is_file() or sha256_file(source_path) != native["sha256"]:
            raise Refused(f"--source {source} is not this shot's native take (render receipt sha256 "
                          f"{native['sha256'][:12]}, path {native['path']}); the engine never upscales an arbitrary file")
        expected_target = self.route["upscale"]["target"]
        if target != expected_target:
            raise Refused(f"--target {target!r} is not the routes upscale.target {expected_target!r} of domain "
                          f"{self.ctx.domain_id!r}; a geometry outside the qualified recipe is refused")
        extra = {"verb": "upscale", "revision": int(state["revision"]), "backend": self.backend, "resumed": done}
        if done:
            self._record(shot, "upscale", "already", receipt=state["receipts"].get("upscale"))
            return self._gate_and_finish(shot, None, **extra)
        return self._gate_and_finish(shot, self._upscale(state, receipts["render"]), **extra)


def render_shot(ctx: Context, out: Path, shot: str, revision: int, route_name: str, *, gpu_token: str | None = None,
                comfy: render_mod.ComfyHandles | None = None, routes_path: Path | None = None, resume: bool = False,
                wait_timeout: float = 3600.0) -> dict[str, Any]:
    """``jjv video render``."""
    verbs = ShotVerbs(ctx, out, routes_path=routes_path, gpu_approval=gpu_approval_from(gpu_token), comfy=comfy,
                      wait_timeout=wait_timeout)
    return verbs.render_shot(shot, revision, route_name, resume=resume)


def upscale_shot(ctx: Context, out: Path, shot: str, source: Path, target: str, backend: str, *,
                 revision: int | None = None, gpu_token: str | None = None, comfy: render_mod.ComfyHandles | None = None,
                 routes_path: Path | None = None, resume: bool = False) -> dict[str, Any]:
    """``jjv video upscale``."""
    verbs = ShotVerbs(ctx, out, routes_path=routes_path, gpu_approval=gpu_approval_from(gpu_token), comfy=comfy,
                      backend=backend)
    return verbs.upscale_shot(shot, source, target, revision=revision, resume=resume)


__all__ = ["ShotVerbs", "render_shot", "upscale_shot"]
