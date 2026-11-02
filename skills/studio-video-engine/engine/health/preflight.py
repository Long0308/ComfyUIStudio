"""One preflight for every execute path: six named, read-only checks; refuse = nothing queued.

Checks, in order (a later check is SKIPPED, and counts as failed, when the one it needs failed):

1. ``docker_engine``       ``docker version`` answers.
2. ``container_identity``  ``docker inspect``: name == machine config, running, restart policy
                           ``unless-stopped``, launched with ``--disable-partner-nodes``.
3. ``comfy_http``          ``GET /system_stats`` answers; when it reports ``argv`` that argv must carry the
                           required flags too (the live process, not only the container definition).
4. ``queue_idle``          ``GET /queue``: running + pending == 0.
5. ``vram_free``           min ``vram_free`` over devices >= the recipe minimum (MiB).
6. ``required_nodes``      every class of the graph is known to ``/object_info`` and none is a partner/API node.

``require_ready`` raises ``Refused`` (exit 1) with the report as evidence.  Nothing is ever sent,
interrupted, freed, started or stopped here; every next step is addressed to the operator.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterable

from ..comfy import guards
from ..core.errors import Refused
from .comfy_facts import ComfyFacts, Getter, collect_comfy_facts
from .docker_facts import DockerFacts, Runner, collect_docker_facts
from .fixture import FixtureClient, fixture_runner

SCHEMA = "jjv/health-preflight/v1"
REQUIRED_CONTAINER_ARGS = ("--disable-partner-nodes",)  # engine rule: cloud partner nodes are off in the render container
REQUIRED_RESTART_POLICY = "unless-stopped"
CHECK_NAMES = ("docker_engine", "container_identity", "comfy_http", "queue_idle", "vram_free", "required_nodes")
OPERATOR = "operator: "


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: dict[str, Any]
    next_step: str | None = None
    skipped: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "skipped": self.skipped, "detail": self.detail,
                "next_step": self.next_step}

    def problem(self) -> str | None:
        if self.ok:
            return None
        return f"{self.name}: {self.detail.get('problem', 'failed')} -> {self.next_step or 'see detail'}"


@dataclass(frozen=True)
class Report:
    ready: bool
    mode: str  # "live" | "dry"
    base_url: str
    container: str
    min_free_vram_mib: int
    classes: tuple[str, ...]
    checks: tuple[Check, ...]

    @property
    def failed(self) -> list[str]:
        return [c.name for c in self.checks if not c.ok]

    @property
    def problems(self) -> list[str]:
        return [text for c in self.checks if (text := c.problem())]

    def to_json(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "ready": self.ready, "queued": False, "mode": self.mode, "base_url": self.base_url,
                "container": self.container, "min_free_vram_mib": self.min_free_vram_mib,
                "classes": list(self.classes), "checks": [c.to_json() for c in self.checks],
                "failed": self.failed, "problems": self.problems}


def _is_partner(entry: dict[str, Any]) -> bool:
    """Same three signals as ``engine.comfy.guards`` (a test pins the agreement)."""
    module, category = str(entry.get("python_module", "")), str(entry.get("category", ""))
    return bool(entry.get("api_node")) or "comfy_api_nodes" in module or category.lower().startswith("api node")


def _skipped(name: str, because: str) -> Check:
    return Check(name, False, {"problem": f"not checked: {because}"}, next_step="fix the earlier failed check first",
                 skipped=True)


def _docker_engine(docker: DockerFacts) -> Check:
    detail = {"commands": list(docker.commands), "version": docker.engine_version}
    if not docker.engine_reachable:
        return Check("docker_engine", False, {**detail, "problem": f"docker engine unreachable: {docker.engine_error}"},
                     next_step=OPERATOR + "start Docker Desktop / put the docker CLI on PATH yourself; the engine never starts it")
    return Check("docker_engine", True, detail)


def _container_identity(docker: DockerFacts, container: str, required_args: Iterable[str], policy: str) -> Check:
    if docker.container is None:
        return Check("container_identity", False,
                     {"container": container, "problem": f"container {container!r} unreadable: {docker.container_error}"},
                     next_step=OPERATOR + "check `docker ps -a`; the container must exist under the machine config name")
    facts = docker.container
    required = list(required_args)
    detail = {"container": container, **facts.to_json(), "required_args": required, "required_restart_policy": policy}
    problems = []
    if facts.name != container:
        problems.append(f"name {facts.name!r} != {container!r}")
    if not facts.running:
        problems.append("not running")
    if facts.restart_policy != policy:
        problems.append(f"restart policy {facts.restart_policy!r} != {policy!r}")
    missing = [a for a in required if a not in facts.args]
    if missing:
        problems.append(f"launched without {' '.join(missing)} (args: {' '.join(facts.args)})")
    if problems:
        return Check("container_identity", False, {**detail, "problem": f"container {container!r}: " + "; ".join(problems)},
                     next_step=OPERATOR + "fix the container definition (compose/run flags) and recreate it yourself; "
                                          "the engine never starts, stops or restarts a container")
    return Check("container_identity", True, detail)


def _comfy_http(comfy: ComfyFacts, base_url: str, required_args: Iterable[str]) -> Check:
    if not comfy.http_up or comfy.system_stats is None:
        return Check("comfy_http", False, {"base_url": base_url, "problem": f"ComfyUI HTTP down at {base_url}: {comfy.system_error}"},
                     next_step=OPERATOR + "read `docker logs <container>` and wait for ComfyUI to answer; the engine never restarts it")
    system = comfy.system_stats.get("system")
    system = system if isinstance(system, dict) else {}
    argv = system.get("argv") if isinstance(system.get("argv"), list) else None
    detail = {"base_url": base_url, "comfyui_version": system.get("comfyui_version"),
              "python_version": system.get("python_version"), "argv": argv}
    missing = [a for a in required_args if a not in argv] if argv is not None else []
    if missing:
        return Check("comfy_http", False, {**detail, "problem": f"the running ComfyUI process lacks {' '.join(missing)} "
                                                                 f"(argv: {' '.join(map(str, argv))})"},
                     next_step=OPERATOR + "the live process must run with the required flags; recreate the container yourself")
    return Check("comfy_http", True, detail)


def _queue_idle(comfy: ComfyFacts) -> Check:
    if comfy.queue is None:
        return Check("queue_idle", False, {"problem": f"queue unreadable: {comfy.queue_error}"},
                     next_step=OPERATOR + "re-run when GET /queue answers")
    running, pending = len(comfy.queue.get("queue_running") or []), len(comfy.queue.get("queue_pending") or [])
    detail = {"running": running, "pending": pending}
    if running or pending:
        return Check("queue_idle", False, {**detail, "problem": f"ComfyUI queue is busy (running={running}, pending={pending})"},
                     next_step=OPERATOR + "wait for the queue to drain (`jjv comfy check`); never interrupt the running prompt")
    return Check("queue_idle", True, detail)


def _vram_free(comfy: ComfyFacts, minimum: int) -> Check:
    devices = (comfy.system_stats or {}).get("devices")
    rows = [{"name": d.get("name"), "vram_free_mib": int(d["vram_free"]) >> 20,
             "vram_total_mib": int(d.get("vram_total") or 0) >> 20}
            for d in (devices if isinstance(devices, list) else [])
            if isinstance(d, dict) and isinstance(d.get("vram_free"), int) and not isinstance(d.get("vram_free"), bool)]
    detail: dict[str, Any] = {"minimum_mib": minimum, "devices": rows}
    if not rows:
        return Check("vram_free", False, {**detail, "problem": "GET /system_stats reports no device with vram_free"},
                     next_step=OPERATOR + "ComfyUI sees no GPU; check the container's GPU access yourself")
    free = min(r["vram_free_mib"] for r in rows)
    detail["free_mib"] = free
    if free < minimum:
        return Check("vram_free", False, {**detail, "problem": f"free VRAM {free} MiB < {minimum} MiB minimum"},
                     next_step=OPERATOR + "wait for the other GPU job to finish; the engine never frees memory or interrupts anything")
    return Check("vram_free", True, detail)


def _required_nodes(comfy: ComfyFacts, classes: Iterable[str]) -> Check:
    rows: dict[str, dict[str, Any]] = {}
    problems = []
    for name in classes:
        if name in comfy.object_info_errors:
            rows[name] = {"status": "unreadable", "error": comfy.object_info_errors[name]}
            problems.append(f"{name}: /object_info unreadable ({comfy.object_info_errors[name]})")
            continue
        entry = comfy.object_info.get(name)
        if entry is None:
            rows[name] = {"status": "missing"}
            problems.append(f"{name}: unknown to this ComfyUI (custom node missing or not whitelisted)")
            continue
        rows[name] = {"status": "present", "python_module": entry.get("python_module"), "pack": guards.custom_pack(entry)}
        if _is_partner(entry):
            rows[name]["status"] = "partner"
            problems.append(f"{name}: partner/API node (module={entry.get('python_module')!r}); never allowed in a graph")
    detail: dict[str, Any] = {"classes": rows}
    if problems:
        return Check("required_nodes", False, {**detail, "problem": "; ".join(problems)},
                     next_step=OPERATOR + "install/whitelist the missing pack or take the partner node out of the graph, "
                                          "then restart ComfyUI yourself")
    return Check("required_nodes", True, detail)


def evaluate(docker: DockerFacts, comfy: ComfyFacts, *, container: str, base_url: str, classes: Iterable[str],
             min_free_vram_mib: int, mode: str, required_args: Iterable[str] = REQUIRED_CONTAINER_ARGS,
             restart_policy: str = REQUIRED_RESTART_POLICY) -> Report:
    """Pure: facts in, report out (no probe here)."""
    if isinstance(min_free_vram_mib, bool) or not isinstance(min_free_vram_mib, int) or min_free_vram_mib < 0:
        raise ValueError(f"min_free_vram_mib must be a non-negative int, got {min_free_vram_mib!r}")
    names = tuple(classes)
    required = tuple(required_args)
    engine = _docker_engine(docker)
    identity = (_container_identity(docker, container, required, restart_policy) if engine.ok
                else _skipped("container_identity", "docker engine unreachable"))
    http = _comfy_http(comfy, base_url, required)
    if comfy.http_up:
        rest = [_queue_idle(comfy), _vram_free(comfy, min_free_vram_mib), _required_nodes(comfy, names)]
    else:
        rest = [_skipped(name, "ComfyUI HTTP down") for name in ("queue_idle", "vram_free", "required_nodes")]
    checks = (engine, identity, http, *rest)
    return Report(ready=all(c.ok for c in checks), mode=mode, base_url=base_url, container=container,
                  min_free_vram_mib=min_free_vram_mib, classes=names, checks=checks)


def classes_of(graph: dict[str, Any] | None) -> tuple[str, ...]:
    """Distinct class_types of an API graph (``Refused`` for a UI export / malformed graph); () without a graph."""
    return tuple(guards.graph_class_types(graph)) if graph is not None else ()


def run_preflight(client: Getter, settings: Any, *, graph: dict[str, Any] | None = None, min_free_vram_mib: int,
                  runner: Runner | None = None, mode: str = "live") -> Report:
    """Collect (read-only) and evaluate.  ``settings`` needs ``base_url`` and ``container`` (a ``ComfySettings``)."""
    classes = classes_of(graph)
    docker = collect_docker_facts(settings.container, runner)
    comfy = collect_comfy_facts(client, classes)
    return evaluate(docker, comfy, container=settings.container, base_url=settings.base_url, classes=classes,
                    min_free_vram_mib=min_free_vram_mib, mode=mode)


def dry_preflight(doc: dict[str, Any], *, container: str, base_url: str, graph: dict[str, Any] | None = None,
                  min_free_vram_mib: int = 0) -> Report:
    """The fixture form: same code path, no HTTP, no subprocess."""
    target = SimpleNamespace(container=container, base_url=base_url)
    return run_preflight(FixtureClient(doc), target, graph=graph, min_free_vram_mib=min_free_vram_mib,
                         runner=fixture_runner(doc), mode="dry")


def require_ready(client: Getter, settings: Any, *, graph: dict[str, Any] | None = None, min_free_vram_mib: int,
                  runner: Runner | None = None) -> Report:
    """The call-site gate: ``Refused`` (exit 1, nothing queued) unless every check is ok."""
    report = run_preflight(client, settings, graph=graph, min_free_vram_mib=min_free_vram_mib, runner=runner)
    if not report.ready:
        raise Refused("health preflight refused (nothing was queued): " + " | ".join(report.problems),
                      evidence={"stage": "health_preflight", "report": report.to_json()})
    return report
