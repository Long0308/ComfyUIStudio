"""Read-only docker facts for the health preflight: ``docker version`` and ``docker inspect``.

Both commands run through an injectable runner.  The default runner delegates to the one
``engine.comfy.docker_probe`` uses (one subprocess policy for every docker call of the engine;
the test harness replaces that one, so a test can never reach the real docker CLI by accident).
Every failure becomes text in the facts, never an exception: the preflight turns it into a
named failed check with a next step.  Nothing here starts, stops or restarts anything.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

Runner = Callable[[list[str]], Any]  # returns an object with returncode / stdout / stderr

VERSION_COMMAND = ["docker", "version", "--format", "{{.Server.Version}}"]
INSPECT_FORMAT = ("{{.Name}}|{{.State.Running}}|{{.State.StartedAt}}|{{.RestartCount}}|"
                  "{{.HostConfig.RestartPolicy.Name}}|{{json .Args}}")
_FIELDS = 6


def inspect_command(container: str) -> list[str]:
    return ["docker", "inspect", "--format", INSPECT_FORMAT, container]


def _real_default_runner(command: list[str]) -> Any:
    """The real docker CLI through the probe module's runner, looked up at call time."""
    from ..comfy import docker_probe

    return docker_probe.default_runner(command)


default_runner: Runner = _real_default_runner  # module attribute on purpose: resolved at call time


@dataclass(frozen=True)
class ContainerFacts:
    name: str  # as docker prints it, without the leading slash
    running: bool
    started_at_text: str
    restart_count: int | None
    restart_policy: str
    args: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "running": self.running, "started_at": self.started_at_text,
                "restart_count": self.restart_count, "restart_policy": self.restart_policy, "args": list(self.args)}


@dataclass(frozen=True)
class DockerFacts:
    engine_version: str | None
    engine_error: str | None
    container: ContainerFacts | None
    container_error: str | None
    commands: tuple[str, ...]  # the read-only commands that were run (evidence)

    @property
    def engine_reachable(self) -> bool:
        return self.engine_error is None and self.engine_version is not None


def parse_inspect_line(text: str) -> ContainerFacts:
    """Parse one ``INSPECT_FORMAT`` line; ``ValueError`` unless it carries the six fields."""
    parts = text.strip().split("|", _FIELDS - 1)
    if len(parts) != _FIELDS:
        raise ValueError(f"docker inspect line has {len(parts)} field(s), expected {_FIELDS}: {text.strip()[:200]!r}")
    name, running, started, restarts, policy, args_json = (p.strip() for p in parts)
    try:
        args = json.loads(args_json or "null")
    except ValueError as error:
        raise ValueError(f"container Args is not JSON: {args_json[:200]!r}") from error
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError(f"container Args is not a list of strings: {args_json[:200]!r}")
    return ContainerFacts(name=name.lstrip("/"), running=running.lower() == "true", started_at_text=started,
                          restart_count=int(restarts) if restarts.isdigit() else None, restart_policy=policy,
                          args=tuple(args))


def _run(runner: Runner, command: list[str]) -> tuple[Any, str | None]:
    """Run one read-only command; ``(result, None)`` on exit 0, ``(None, text)`` otherwise."""
    try:
        done = runner(command)
    except (OSError, subprocess.SubprocessError) as error:
        return None, f"{command[0]} {command[1]} could not run: {error!r}"
    code = getattr(done, "returncode", 1)
    if code != 0:
        text = (getattr(done, "stderr", "") or "").strip() or (getattr(done, "stdout", "") or "").strip()
        return None, f"{command[0]} {command[1]} exit {code}: {text[:300] or 'no output'}"
    return done, None


def collect_docker_facts(container: str, runner: Runner | None = None) -> DockerFacts:
    """``docker version`` then ``docker inspect <container>``; read-only; never raises."""
    run = runner if runner is not None else default_runner
    commands = [" ".join(VERSION_COMMAND)]
    done, error = _run(run, VERSION_COMMAND)
    if error is not None:
        return DockerFacts(None, error, None, "not checked: docker engine unreachable", tuple(commands))
    version = (getattr(done, "stdout", "") or "").strip() or None
    if version is None:
        return DockerFacts(None, "docker version printed no server version", None,
                           "not checked: docker engine unreachable", tuple(commands))
    command = inspect_command(container)
    commands.append(" ".join(command[:3]) + " <INSPECT_FORMAT> " + container)
    done, error = _run(run, command)
    if error is not None:
        return DockerFacts(version, None, None, error, tuple(commands))
    try:
        facts = parse_inspect_line(getattr(done, "stdout", "") or "")
    except ValueError as err:
        return DockerFacts(version, None, None, str(err), tuple(commands))
    return DockerFacts(version, None, facts, None, tuple(commands))
