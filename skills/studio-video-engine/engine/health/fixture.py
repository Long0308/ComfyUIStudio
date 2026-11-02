"""The dry form of the preflight: a ``jjv/health-fixture/v1`` document stands in for docker and ComfyUI.

``fixture_runner`` answers ``docker version`` / ``docker inspect`` and ``FixtureClient`` answers the three
GETs from the document, so the dry preflight runs the SAME collection and evaluation code as the live
one with no subprocess and no HTTP.  ``healthy_fixture`` is the reference shape of a ready machine.

Document shape::

    {"schema": "jjv/health-fixture/v1",
     "docker": {"version": "28.x" | null,                      # null = engine unreachable
                "containers": {"<name>": {"running": true, "started_at": "...Z", "restart_count": 0,
                                          "restart_policy": "unless-stopped", "args": ["main.py", ...]}}},
     "comfy": {"up": true,                                      # false = every GET fails
               "system_stats": {...}, "queue": {...}, "object_info": {"<class>": {...} | null}}}
"""

from __future__ import annotations

import json
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

from ..comfy.client import ComfyError
from ..core.errors import Uncertain
from ..core.io import read_json
from .docker_facts import INSPECT_FORMAT, Runner

FIXTURE_SCHEMA = "jjv/health-fixture/v1"
DEFAULT_ARGS = ("main.py", "--disable-partner-nodes")
DEFAULT_NODE_INFO = {"python_module": "nodes", "category": "fixture"}


def healthy_fixture(container: str, classes: Iterable[str] = (), *, vram_free_mib: int = 12288,
                    vram_total_mib: int = 16384, args: Iterable[str] = DEFAULT_ARGS,
                    restart_policy: str = "unless-stopped") -> dict[str, Any]:
    """A fixture in which every check passes for ``container`` and ``classes``."""
    argv = list(args)
    return {
        "schema": FIXTURE_SCHEMA,
        "docker": {"version": "fixture", "containers": {container: {
            "running": True, "started_at": "2026-01-01T00:00:00.000000000Z", "restart_count": 0,
            "restart_policy": restart_policy, "args": argv}}},
        "comfy": {"up": True,
                  "system_stats": {"system": {"comfyui_version": "fixture", "python_version": "fixture", "argv": argv},
                                   "devices": [{"name": "fixture-gpu", "vram_free": vram_free_mib << 20,
                                                "vram_total": vram_total_mib << 20}]},
                  "queue": {"queue_running": [], "queue_pending": []},
                  "object_info": {name: dict(DEFAULT_NODE_INFO) for name in classes}},
    }


def load_fixture(path: Path) -> dict[str, Any]:
    doc = read_json(path)
    if not isinstance(doc, dict) or doc.get("schema") != FIXTURE_SCHEMA:
        raise Uncertain(f"{path} is not a {FIXTURE_SCHEMA} document")
    for key in ("docker", "comfy"):
        if not isinstance(doc.get(key), dict):
            raise Uncertain(f"{path}: fixture block {key!r} missing or not an object")
    return doc


def _done(command: list[str], code: int, stdout: str = "", stderr: str = "") -> "subprocess.CompletedProcess[str]":
    return subprocess.CompletedProcess(command, code, stdout, stderr)


def fixture_runner(doc: dict[str, Any]) -> Runner:
    """A docker runner that answers from the fixture's ``docker`` block (runs nothing)."""
    docker = doc["docker"]

    def run(command: list[str]) -> "subprocess.CompletedProcess[str]":
        if command[:2] == ["docker", "version"]:
            version = docker.get("version")
            if version is None:
                return _done(command, 1, "", "error during connect: the docker daemon is not reachable (fixture)")
            return _done(command, 0, str(version) + "\n", "")
        if command[:2] == ["docker", "inspect"] and command[2:4] == ["--format", INSPECT_FORMAT] and len(command) == 5:
            name = command[4]
            row = (docker.get("containers") or {}).get(name)
            if row is None:
                return _done(command, 1, "", f"Error: No such object: {name}")
            line = "|".join(["/" + name, "true" if row.get("running") else "false", str(row.get("started_at", "")),
                             str(row.get("restart_count", 0)), str(row.get("restart_policy", "")),
                             json.dumps(list(row.get("args") or []))])
            return _done(command, 0, line + "\n", "")
        return _done(command, 2, "", f"fixture runner: unsupported command {command!r}")

    return run


class FixtureClient:
    """Answers ``/system_stats``, ``/queue`` and ``/object_info/<class>`` from the fixture's ``comfy`` block."""

    def __init__(self, doc: dict[str, Any]) -> None:
        self.comfy = doc["comfy"]
        self.requests: list[str] = []

    def get(self, path: str) -> Any:
        self.requests.append("GET " + path)
        if not self.comfy.get("up", True):
            raise ComfyError(f"GET {path} failed: ConnectionRefusedError (fixture: ComfyUI down)")
        if path == "/system_stats":
            return self.comfy.get("system_stats")
        if path == "/queue":
            return self.comfy.get("queue")
        if path.startswith("/object_info/"):
            name = urllib.parse.unquote(path[len("/object_info/"):])
            entry = (self.comfy.get("object_info") or {}).get(name)
            return {name: entry} if isinstance(entry, dict) else {}
        raise ComfyError(f"GET {path} answered HTTP 404 (fixture)", http_status=404)

    def post(self, path: str, payload: object) -> Any:
        self.requests.append("POST " + path)
        raise AssertionError("the health preflight never POSTs")
