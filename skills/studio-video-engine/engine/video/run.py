"""``jjv video run``: lịch theo shot, resume-safe, một GPU job, lane chỉ cho việc không GPU (prompt).

Vòng chạy: (02) prompt cho mọi shot còn ``planned`` (lane song song, CPU) -> đi từng shot theo thứ tự: (03)
render qua H3 -> (04) upscale -> (05) dừng ở cổng acceptance; shot kế chỉ mở khi shot hiện tại ``accepted``.
``--dry-run`` in payload graph của MỌI shot và không ghi gì.  Cổng người dùng (exit 0, ``ok: false``):
``gpu-approval``, ``needs-gpu-pilot-approval``, ``take-acceptance``, ``review-pending``, ``final-review``.  Lỗi kỹ thuật
(``blocked_technical``, exit 1) giữ nguyên receipt; ``RECONCILE`` (Uncertain, exit 2) không skip, không gửi lại.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_bytes, sha256_file, write_json_once
from ..h3 import prepare as prepare_mod
from ..layout.context import Context
from . import accept as accept_mod
from . import longtake as longtake_mod
from . import payload as payload_mod
from . import prompt as prompt_mod
from . import render as render_mod
from . import routes as routes_mod
from . import state as state_mod
from . import upscale as upscale_mod
from . import tiers

GATE_GPU = "gpu-approval"
GATE_PILOT = upscale_mod.GATE_PILOT
GATE_TAKE = "take-acceptance"
GATE_REVIEW = "review-pending"
GATE_FINAL = "final-review"
GATE_TECH = "blocked_technical"
USER_GATES = (GATE_GPU, GATE_PILOT, GATE_TAKE, GATE_REVIEW, GATE_FINAL)
# chính sách cổng take (trung tính theo domain; nằm ở routes ``take_gate`` hoặc tham số run):
# ``every`` = dừng ở take-acceptance của MỌI shot (mặc định, như cũ); ``first`` = chỉ shot đầu dừng, shot đầu đã
# ``accepted`` bởi người thì các shot sau chạy tự động tới ``upscaled_1080`` (đã sản xuất, chờ duyệt, KHÔNG accepted).
TAKE_GATES = ("every", "first")
PILOT_MARKERS = ("not qualified", "qualification receipt")


TOKEN_PREFIX = "token:"
# chữ sau ``token:`` đọc như một lời TỪ CHỐI thì không phải phê duyệt (critic CR-VENG: "false"/"none" từng được nhận)
_NOT_AN_APPROVAL = frozenset({"false", "no", "none", "null", "0", "off", "n"})


def gpu_approval_from(token: str | None) -> dict[str, Any] | None:
    """``--gpu-approved``: CHỈ ``token:<text>`` (lời phê duyệt tường minh của user) hoặc một receipt file CÓ THẬT (ghi
    sha256).  Chữ trần, hay một đường dẫn receipt gõ nhầm (không tồn tại), KHÔNG bao giờ được coi là phê duyệt: Refused."""
    if token is None:
        return None
    text = str(token).strip()
    if not text:
        raise Refused(f"--gpu-approved needs a non-empty value: {TOKEN_PREFIX}<text> from the user, or an existing "
                      "receipt file; nothing was sent")
    if text.startswith(TOKEN_PREFIX):
        value = text[len(TOKEN_PREFIX):].strip()
        if not value:
            raise Refused(f"--gpu-approved {text!r}: the text after {TOKEN_PREFIX} is empty; nothing was sent")
        if value.casefold() in _NOT_AN_APPROVAL:
            raise Refused(f"--gpu-approved {text!r} reads as a refusal, not an approval; nothing was sent")
        return {"kind": "token", "value": value}
    path = Path(text)
    if path.is_file():
        return {"kind": "receipt", "path": str(path.resolve()), "sha256": sha256_file(path)}
    if path.exists():
        raise Refused(f"--gpu-approved {text!r} exists but is not a file (a receipt is a file); nothing was sent")
    raise Refused(f"--gpu-approved {text!r} is neither an existing receipt file nor an explicit token "
                  f"({TOKEN_PREFIX}<text>): a mistyped receipt path never counts as approval; nothing was sent")


def _gate(kind: str, shot: str | None, detail: str, next_step: str) -> dict[str, Any]:
    return {"kind": kind, "shot": shot, "detail": detail, "next": next_step,
            "user_gate": kind in USER_GATES}


def _template_graph(plan: dict[str, Any]) -> dict[str, Any]:
    template = plan["template"]
    prepare_mod.require_hash(Path(template["path"]), template["sha256"], "video template graph")
    return read_json(Path(template["path"]))


def _manifest_rows(out: Path) -> dict[str, dict[str, Any]]:
    path = render_mod.manifest_path(out)
    if not path.is_file():
        return {}
    document = read_json(path)
    return {r["shot"]: r for r in document.get("shots") or [] if isinstance(r, dict) and "shot" in r}


class Scheduler:
    def __init__(self, ctx: Context, out: Path, *, routes_path: Path | None = None, lanes: int = 1,
                 dry_run: bool = False, gpu_approval: dict[str, Any] | None = None,
                 comfy: render_mod.ComfyHandles | None = None, backend: str | None = None,
                 wait_timeout: float = 3600.0, take_gate: str | None = None) -> None:
        self.ctx, self.out, self.dry_run = ctx, Path(out), dry_run
        self.routes = routes_mod.load_routes(routes_path)
        self.route = routes_mod.domain_route(ctx, self.routes)
        self.take_gate = take_gate if take_gate is not None else self.route.get("take_gate", self.routes.get("take_gate", "every"))
        if self.take_gate not in TAKE_GATES:
            raise Refused(f"take_gate must be one of {TAKE_GATES}, got {self.take_gate!r}; nothing was sent")
        if not isinstance(lanes, int) or isinstance(lanes, bool) or not 1 <= lanes <= int(self.routes["max_lanes"]):
            raise Refused(f"--lanes must be an integer in 1..{self.routes['max_lanes']} (prompt/QA lanes only; the GPU "
                          "always runs one job)")
        self.lanes = lanes
        self.plan = state_mod.read_plan(self.out)
        state_mod.require_plan_of(ctx, self.plan)
        self.tier_sources = tiers.validate(ctx, self.plan)
        self.route = tiers.effective_route(self.route, self.plan)
        if self.plan["template"]["sha256"] != self.route["template"]["sha256"]:
            raise Refused("the plan template sha256 is not the routes template of this domain; re-plan")
        self.graph = _template_graph(self.plan)
        self.gpu_approval, self.comfy, self.backend, self.wait_timeout = gpu_approval, comfy, backend, wait_timeout
        self.stages = list(self.plan["stages"])
        self.prompts: dict[str, dict[str, Any]] = {}
        self.steps: list[dict[str, Any]] = []
        self.payloads: list[dict[str, Any]] = []
        self.gate: dict[str, Any] | None = None

    # ---- 02 VIẾT PROMPT -------------------------------------------------------------------------------
    def _template_prompt(self) -> str:
        node, key = routes_mod.port_pair(self.route["ports"]["prompt"])
        return str(self.graph[node]["inputs"][key])

    def _prompt_one(self, shot: str, lane: int) -> dict[str, Any]:
        state = state_mod.read_state(self.out, shot)
        receipt = state_mod.verify_ref(self.out, state["receipts"]["plan"], "plan")
        row: dict[str, Any] = {"shot": shot, "lane": lane, "revision": state["revision"], "stage": self.stages[1]}
        if state["state"] != "planned":  # prompt đã đóng băng: đọc lại, không ghép lại (dry-run cũng vậy)
            text, existing = prompt_mod.read_prompt(self.out, shot, state["revision"])
            return {**row, "text": text, "prompt_sha256": existing["prompt"]["sha256"], "written": False,
                    "reused": True, "state": state["state"]}
        text = prompt_mod.compose(self._template_prompt(), receipt)
        if self.dry_run:
            return {**row, "text": text, "prompt_sha256": sha256_bytes(text.encode("utf-8")), "written": False,
                    "reused": False, "state": state["state"]}
        body = {"episode_id": self.ctx.episode_id, "domain": self.ctx.domain_id, "stage": self.stages[1],
                "plan_receipt": state["receipts"]["plan"], "shotlist_sha256": receipt["shotlist"]["sha256"],
                "template_sha256": receipt["template"]["sha256"], "routes_sha256": receipt["routes"]["sha256"],
                "refs": [{"role": r["role"], "sha256": r["sha256"], "bound": r["bound"]} for r in receipt["refs"]],
                "ports": {k: receipt["ports"][k] for k in ("prompt", "length", "seed")},
                "length": receipt["length"], "seed": receipt["seed"], "lane": lane}
        written = prompt_mod.write_prompt(self.out, shot, state["revision"], text, body=body)
        state_mod.advance(self.out, state, "prompted", receipt_key="prompt", receipt_path=written["path"])
        return {**row, "text": text, "prompt_sha256": written["prompt_sha256"], "written": not written["reused"],
                "reused": written["reused"], "state": "prompted"}

    def _prompts(self) -> None:
        shots = [row["shot"] for row in self.plan["shots"]]
        with ThreadPoolExecutor(max_workers=self.lanes) as pool:
            futures = [pool.submit(self._prompt_one, shot, index % self.lanes + 1) for index, shot in enumerate(shots)]
            for future in futures:  # một lane lỗi ⇒ dừng cả run (exception nổi lên), không bỏ shot
                row = future.result()
                self.prompts[row["shot"]] = row
        if not self.dry_run:
            self._h3_spec()

    def _h3_spec(self) -> None:
        """``jjv/h3-spec/v1`` của revision hiện tại: dữ liệu graph cho ``jjv h3 inputs`` (sha đến từ receipt)."""
        if self.plan["tier"] != "preview":
            return  # promotion consumes approved pixels, never a new H3 graph
        ports = self.route["ports"]
        rows, revisions = [], set()
        for shot_row in self.plan["shots"]:
            shot = shot_row["shot"]
            state = state_mod.read_state(self.out, shot)
            receipt = state_mod.verify_ref(self.out, state["receipts"]["plan"], "plan")
            revisions.add(int(state["revision"]))
            bound = [r for r in receipt["refs"] if r["bound"]]
            frozen = receipt.get("geometry")  # the plan's frozen H3 size: `render.require_manifest` refuses a manifest without it
            size = {frozen["ports"][axis]: frozen[axis] for axis in ("width", "height")} if frozen else {}
            rows.append({"shot": shot, "faces": [{"role": r["role"], "ports": [r["ports"]]} for r in bound],
                         "mouth": {ports["prompt"]: self.prompts[shot]["text"], ports["length"]: receipt["length"]["frames"],
                                   ports["seed"]: receipt["seed"], **size}})
        if len(revisions) != 1:
            return  # revision lệch giữa các shot: spec theo revision được ghi khi shot đó tới lượt render
        spec = {"schema": "jjv/h3-spec/v1", "episode_id": self.ctx.episode_id,
                "comment": "written by jjv video run from frozen prompt receipts; shas come from `jjv h3 inputs`",
                "defaults": {"template": self.plan["template"]["path"], "anchor_ports": ports["anchor"],
                             "wav_ports": ports["wav"], "editorial_node": ports["editorial_node"],
                             "output_ports": ports["output_ports"], "drop_unfilled_refs": True},
                "shots": rows}
        write_json_once(self.out / f"h3-spec-{state_mod.rev(next(iter(revisions)))}.json", spec, mode="utf8")

    # ---- 03/04/05 theo từng shot ----------------------------------------------------------------------
    def _refs_ok(self, state: dict[str, Any]) -> dict[str, Any]:
        return {key: state_mod.verify_ref(self.out, entry, key) for key, entry in state["receipts"].items()}

    def _record(self, shot: str, step: str, status: str, **extra: Any) -> None:
        self.steps.append({"shot": shot, "step": step, "status": status, **extra})

    def _take_decision(self, receipt: dict[str, Any], route_name: str | None = None) -> dict[str, Any]:
        """Recheck the frozen take choice on every render entry point, including run."""
        shot = {"id": receipt["shot"], "duration_s": receipt["duration_s"],
                "long_take": receipt.get("long_take_flag") is True}
        decision = longtake_mod.decide_take_mode(self.ctx.domain_id, self.route, shot,
                                                 receipt.get("take_mode_requested", "auto"))
        if any(receipt.get(key) not in (None, decision[field]) for key, field in
               (("take_mode", "take_mode"), ("take_route", "route"))):
            raise Refused(f"TAKE_PLAN_DRIFT: {receipt['shot']}: frozen take route differs from current route; re-plan")
        longtake_mod.guard_route(decision, route_name or decision["route"])
        return decision

    def _render(self, state: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any] | None:
        shot = state["shot"]
        text = self.prompts[shot]["text"]
        if self.plan["tier"] != "preview":
            sources = tiers.validate(self.ctx, self.plan)
            path = tiers.promote(self.ctx, self.out, state, self.plan, sources[shot])
            fresh = state_mod.advance(self.out, state, "rendered", receipt_key="render", receipt_path=path)
            self._record(shot, "render", "approved-source", receipt=fresh["receipts"]["render"])
            return None
        try:
            decision = self._take_decision(receipt)
            render_mod.require_gpu_approval(self.gpu_approval, "h3 submit")  # cổng đầu tiên, trước mọi I/O khác
            if self.comfy is None:
                raise Refused("NO_COMFY_HANDLES: no ComfyUI settings/client were given to the scheduler (machine.json "
                              "must name comfy + gpu_lock_path); nothing was sent")
            path = render_mod.render(self.ctx, self.out, state, receipt, text, self.route, take_decision=decision,
                                     gpu_approval=self.gpu_approval,
                                     comfy=self.comfy, wait_timeout=self.wait_timeout)
        except Refused as error:
            message = str(error)
            if message.startswith("GPU_APPROVAL_MISSING"):
                return _gate(GATE_GPU, shot, message, "get the user's explicit approval for THIS run, then re-run with "
                                                      "--gpu-approved <receipt or token>")
            if any(marker in message for marker in PILOT_MARKERS):
                return _gate(GATE_PILOT, shot, message, "run the user-authorised H3 pilot for this domain, pin its "
                                                        "qualification receipt in recipes/h3/routes, then re-run")
            return _gate(GATE_TECH, shot, message, "fix the named input (nothing was sent), then re-run; the engine "
                                                   "never fills anchor/WAV/prompt by itself")
        fresh = state_mod.advance(self.out, state, "rendered", receipt_key="render", receipt_path=path)
        self._record(shot, "render", "ok", receipt=fresh["receipts"]["render"])
        return None

    def _upscale(self, state: dict[str, Any], render_receipt: dict[str, Any] | None = None) -> dict[str, Any] | None:
        shot = state["shot"]
        tiers.validate(self.ctx, self.plan)
        if self.plan["tier"] == "preview":
            render = state_mod.verify_ref(self.out, state["receipts"]["render"], "render")
            path = tiers.retain_preview(self.ctx, self.out, state, render)
            fresh = state_mod.advance(self.out, state, "upscaled_1080", receipt_key="upscale", receipt_path=path)
            self._record(shot, "preview-ready", "awaiting-review", receipt=fresh["receipts"]["upscale"])
            return None
        try:
            verdict, path = upscale_mod.upscale(self.ctx, self.out, state, self.route, backend_name=self.backend,
                                                gpu_approval=self.gpu_approval, comfy=self.comfy,
                                                render_receipt=render_receipt,
                                                lock_path=self.comfy.settings.executor_lock_path if self.comfy else None)
        except Refused as error:
            message = str(error)
            kind = GATE_GPU if message.startswith("GPU_APPROVAL_MISSING") else (
                GATE_PILOT if message.startswith("UPSCALE_UNQUALIFIED") else GATE_TECH)
            return _gate(kind, shot, message, "qualify a 1080p backend for this domain (user-authorised pilot + receipt "
                                             "in routes upscale.qualified), then re-run with --upscale-backend")
        if verdict == "pending":
            pending = read_json(path)
            self._record(shot, "upscale", "pending", pending=state_mod.ref(self.out, path))
            return _gate(GATE_PILOT, shot, f"{shot}: upscale backend 'none' recorded upscale_pending ({path.name}); "
                                            f"{pending['reason']}", pending["next"])
        fresh = state_mod.advance(self.out, state, "upscaled_1080", receipt_key="upscale", receipt_path=path)
        self._record(shot, "upscale", "ok", receipt=fresh["receipts"]["upscale"])
        return None

    def _step(self, state: dict[str, Any]) -> dict[str, Any] | None:
        shot, current = state["shot"], state["state"]
        receipts = self._refs_ok(state)  # resume: mọi receipt đã ghi phải còn đúng byte
        if current == "planned":
            return _gate(GATE_TECH, shot, f"{shot} is still planned after the prompt stage", "re-run")
        if current == "prompted":
            return self._render(state, receipts["plan"])
        if current == "rendered":
            return self._upscale(state, receipts["render"])
        if current == "upscaled_1080":
            up = receipts["upscale"]
            return _gate(GATE_TAKE, shot, f"{shot}: {self.plan['tier']} {up['target']} take {up['output']['sha256'][:12]} awaits the user's pick/reject",
                         f"jjv video accept --episode {self.ctx.episode_id} --out {self.out} --shot {shot} --pick|--reject "
                         f"--sha256 {up['output']['sha256']} --by <person> --reason <what was watched>")
        return None  # accepted

    def _auto_take(self, shot: str) -> bool:
        """``first``: shot SAU shot đầu được đi tiếp khi shot đầu ĐÃ ``accepted`` (người duyệt thật; reject/chưa duyệt
        thì không mở).  Không bao giờ đặt ``accepted`` thay người."""
        if self.take_gate != "first":
            return False
        first = self.plan["shots"][0]["shot"]
        return shot != first and state_mod.read_state(self.out, first)["state"] == "accepted"

    def _review_pending(self) -> list[str]:
        return [r["shot"] for r in self.plan["shots"] if state_mod.read_state(self.out, r["shot"])["state"] == "upscaled_1080"]

    def _walk(self, completion: bool) -> None:
        for row in self.plan["shots"]:
            shot = row["shot"]
            state = state_mod.read_state(self.out, shot)
            if state["state"] == "accepted":
                self._record(shot, "accepted", "done")
                continue
            while not (state["state"] == "upscaled_1080" and self._auto_take(shot)):
                gate = self._step(state)
                if gate is not None:
                    self.gate = gate
                    state_mod.set_gate(self.out, state_mod.read_state(self.out, shot), gate)
                    return
                state = state_mod.read_state(self.out, shot)
                if state["state"] == "accepted" or not completion:
                    break
            if state["state"] == "upscaled_1080" and self._auto_take(shot):
                self._record(shot, "produced", "awaiting-review")
            elif state["state"] != "accepted":
                self.gate = _gate(GATE_TECH, shot, f"{shot} stopped at {state['state']} (single step; use --completion)",
                                  "re-run with --completion")
                return
        pending = self._review_pending()
        if pending:
            self.gate = {**_gate(GATE_REVIEW, None, f"all shots produced; {len(pending)} awaiting the user's pick/reject: "
                                                    f"{', '.join(pending)}",
                                 f"jjv video accept --episode {self.ctx.episode_id} --out {self.out} --shot <shot> "
                                 "--pick|--reject --sha256 <1080p sha> --by <person> --reason <what was watched>"),
                         "pending": pending}
        elif accept_mod.final_review_record(self.out) is None:
            self.gate = _gate(GATE_FINAL, None, "every required shot is accepted; the assembled candidate awaits final review",
                              f"jjv video accept --episode {self.ctx.episode_id} --out {self.out} --final --by <person> "
                              "--note <verdict>")

    def _dry_payloads(self) -> None:
        if self.plan["tier"] != "preview":
            self.payloads = [tiers.promotion_payload(self.plan, row["shot"], self.tier_sources[row["shot"]])
                             for row in self.plan["shots"]]
            return
        manifest = _manifest_rows(self.out)
        for row in self.plan["shots"]:
            shot = row["shot"]
            state = state_mod.read_state(self.out, shot)
            receipt = state_mod.verify_ref(self.out, state["receipts"]["plan"], "plan")
            prompt_row = self.prompts[shot]
            self.payloads.append(payload_mod.shot_payload(self.route, self.graph, receipt, prompt_row["text"],
                                                          prompt_row["prompt_sha256"], state, manifest.get(shot), self.stages))

    def _preview_gates(self) -> dict[str, Any]:
        try:
            prepare_mod.domain_guard(self.ctx)
            h3 = "qualified"
        except Refused as error:
            h3 = f"refused: {error}"
        backend = self.backend or self.route["upscale"]["default_backend"]
        return {"gpu_approval": self.gpu_approval is not None, "h3_qualification": h3,
                "h3_inputs": "present" if render_mod.manifest_path(self.out).is_file() else "missing",
                "upscale_backend": backend,
                "upscale_qualified": backend in (self.route["upscale"].get("qualified") or {}),
                "would_stop_at": GATE_GPU if self.gpu_approval is None else (GATE_PILOT if h3 != "qualified" else GATE_TECH)}

    def run(self, *, completion: bool, prompt_only: bool = False) -> dict[str, Any]:
        self._prompts()
        if self.dry_run:
            self._dry_payloads()
        elif not prompt_only:
            self._walk(completion)
        complete = not self.dry_run and not prompt_only and self.gate is None
        return self._finish(completion=completion, complete=complete)

    def _finish(self, *, completion: bool = False, complete: bool | None = None, **extra: Any) -> dict[str, Any]:
        """Run receipt chung cho ``run`` và hai verb mỏng: ``runs/run-NNN.json`` write-once (dry-run không ghi)."""
        receipt: dict[str, Any] = {
            "schema": state_mod.RUN_SCHEMA, "ok": self.gate is None,
            "complete": (self.gate is None) if complete is None else complete, "dry_run": self.dry_run,
            "episode_id": self.ctx.episode_id, "domain": self.ctx.domain_id, "out": str(self.out),
            "tier": self.plan["tier"], "resolution": self.plan["resolution"],
            "routes": {"path": self.routes["_path"], "sha256": self.routes["_sha256"]},
            "template_sha256": self.plan["template"]["sha256"], "lanes": self.lanes, "gpu_lock": "one GPU job at a time: "
            "machine EXECUTOR-RUN-LOCK for the whole render/upscale step + the ComfyUI submit lock at the POST",
            "gpu_approval": self.gpu_approval, "completion": completion, "take_gate": self.take_gate, "stages": self.stages,
            "prompts": [{k: v for k, v in row.items() if k != "text"} for row in self.prompts.values()],
            "steps": self.steps, "gate": self.gate,
            "shots": [{"shot": r["shot"], **{k: state_mod.read_state(self.out, r["shot"])[k] for k in ("state", "revision")}}
                      for r in self.plan["shots"]], **extra}
        if self.dry_run:
            receipt.update(payloads=self.payloads, gates_preview=self._preview_gates(), wrote=[])
            return receipt
        folder = self.out / render_mod.RUNS_DIR
        path = folder / f"run-{state_mod.next_number(folder):03d}.json"
        write_json_once(path, receipt, mode="utf8")
        return {**receipt, "run_receipt": str(path)}


def run(ctx: Context, out: Path, *, completion: bool, lanes: int = 1, dry_run: bool = False, gpu_token: str | None = None,
        comfy: render_mod.ComfyHandles | None = None, routes_path: Path | None = None, backend: str | None = None,
        wait_timeout: float = 3600.0, prompt_only: bool = False, take_gate: str | None = None) -> dict[str, Any]:
    scheduler = Scheduler(ctx, out, routes_path=routes_path, lanes=lanes, dry_run=dry_run,
                          gpu_approval=gpu_approval_from(gpu_token), comfy=comfy, backend=backend, wait_timeout=wait_timeout,
                          take_gate=take_gate)
    return scheduler.run(completion=completion, prompt_only=prompt_only)


__all__ = ["run", "Scheduler", "gpu_approval_from", "TOKEN_PREFIX", "GATE_GPU", "GATE_PILOT", "GATE_TAKE", "GATE_REVIEW",
           "GATE_FINAL", "GATE_TECH", "TAKE_GATES"]
