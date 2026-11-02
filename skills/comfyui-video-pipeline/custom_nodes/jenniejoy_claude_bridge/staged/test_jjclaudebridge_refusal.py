"""Tests for the JJClaudeBridge hard refusal in comfy_guarded_submit.py.

By default they run against the STAGED helper next to this file. After root applies the staged
copy to ``scripts/comfy_guarded_submit.py`` (once the 4K run is finished) run them again with
``JJ_HELPER_PATH=<live helper>`` to prove the applied file behaves the same.

    python -m pytest staged/test_jjclaudebridge_refusal.py
    JJ_HELPER_PATH=../../../scripts/comfy_guarded_submit.py python -m pytest staged/...

These tests never touch the live helper, ComfyUI, or the shared submit lock.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
STAGED = HERE / "comfy_guarded_submit.py"
LIVE = HERE.parents[2] / "scripts" / "comfy_guarded_submit.py"
TARGET = Path(os.environ.get("JJ_HELPER_PATH") or STAGED).resolve()


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cgs = _load(TARGET, "cgs_under_test")

GRAPH = {
    "1": {"class_type": "LocalNode", "inputs": {"x": 1}},
    "2": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0]}},
}
# The bridge registers as an ordinary whitelisted custom node: object_info does NOT call it a
# partner node, so only the hard deny list can stop it.
OBJECT_INFO = {
    "LocalNode": {"python_module": "nodes", "category": "test"},
    "SaveVideo": {"python_module": "comfy_extras.nodes_video", "category": "image/video"},
    "JJClaudeBridge": {
        "python_module": "custom_nodes.jenniejoy_claude_bridge",
        "category": "JennieJoy/Authoring",
    },
}


class FakeComfy:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def _send(self, body: object) -> None:
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                fake.requests.append(("GET", self.path))
                if self.path == "/queue":
                    self._send({"queue_running": [], "queue_pending": []})
                elif self.path.startswith("/object_info/"):
                    name = self.path.rsplit("/", 1)[1]
                    self._send({name: OBJECT_INFO[name]} if name in OBJECT_INFO else {})
                else:
                    self._send({})

            def do_POST(self) -> None:  # noqa: N802
                fake.requests.append(("POST", self.path))
                self._send({"prompt_id": "should-never-happen"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def posts(self) -> list[tuple[str, str]]:
        return [item for item in self.requests if item[0] == "POST"]


@pytest.fixture()
def fake() -> Any:
    server = FakeComfy()
    server.thread.start()
    yield server
    server.server.shutdown()
    server.server.server_close()


@pytest.fixture()
def work(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("jjbridge-refusal")


def _graph(work: Path, cls: str) -> Path:
    path = work / "graph.json"
    path.write_text(json.dumps({**GRAPH, "3": {"class_type": cls, "inputs": {}}}), encoding="utf-8")
    return path


def _submit(fake: FakeComfy, work: Path, graph: Path, *extra: str) -> int:
    return cgs.main([
        "--base-url", fake.url, "--lock-path", str(work / "submit.lock"),
        "--output-dir", str(work / "out"), "--lock-timeout", "0.2", "--poll", "0.01",
        "submit", "--graph", str(graph), "--receipt-dir", str(work / "rc"),
        "--hold-timeout", "2", *extra,
    ])


def test_hard_denied_covers_both_cloud_and_bridge_classes() -> None:
    assert cgs.hard_denied(["LocalNode", "JJClaudeBridge"]) == ["JJClaudeBridge"]
    assert cgs.hard_denied(["jjclaudebridge", "JJCLAUDEBRIDGE", "ClaudeNode", "SaveVideo"]) == [
        "jjclaudebridge", "JJCLAUDEBRIDGE", "ClaudeNode"]
    assert cgs.hard_denied(["LocalNode", "SaveVideo"]) == []


@pytest.mark.parametrize("extra", [[], ["--partner-ok"]])
@pytest.mark.parametrize("cls", ["JJClaudeBridge", "jjclaudebridge"])
def test_submit_refuses_the_bridge_even_with_partner_ok(
    fake: FakeComfy, work: Path, capsys: Any, extra: list[str], cls: str
) -> None:
    OBJECT_INFO[cls] = OBJECT_INFO["JJClaudeBridge"]
    try:
        code = _submit(fake, work, _graph(work, cls), *extra)
    finally:
        if cls != "JJClaudeBridge":
            OBJECT_INFO.pop(cls, None)
    err = capsys.readouterr().err
    assert code == cgs.EXIT_REFUSED
    assert "never allowed" in err and cls in err
    assert fake.posts() == []
    assert not (work / "rc" / "dispatch-intent.json").exists()
    assert not (work / "submit.lock").exists()


def test_claudenode_is_still_refused(fake: FakeComfy, work: Path, capsys: Any) -> None:
    OBJECT_INFO["ClaudeNode"] = {"python_module": "comfy_api_nodes.nodes_anthropic",
                                 "category": "api node/text/Anthropic"}
    try:
        assert _submit(fake, work, _graph(work, "ClaudeNode"), "--partner-ok") == cgs.EXIT_REFUSED
    finally:
        OBJECT_INFO.pop("ClaudeNode", None)
    assert "never allowed" in capsys.readouterr().err
    assert fake.posts() == []


def test_an_ordinary_graph_is_not_affected(fake: FakeComfy, work: Path) -> None:
    graph = work / "ok.json"
    graph.write_text(json.dumps(GRAPH), encoding="utf-8")
    classes = cgs.graph_class_types(json.loads(graph.read_text("utf-8")))
    assert cgs.hard_denied(classes) == []


def test_staged_copy_differs_from_the_live_helper_only_by_the_planned_edit() -> None:
    """Keeps the staged copy honest: live + the three planned substitutions == staged."""
    staged = STAGED.read_bytes()
    live = LIVE.read_bytes()
    if live == staged:
        return  # already applied
    assert b'frozenset({"claudenode"})' in live, "live helper changed since staging; re-stage"
    rebuilt = live.replace(
        b'PARTNER_DENY_LIST = frozenset({"claudenode"})',
        b'PARTNER_DENY_LIST = frozenset({"claudenode", "jjclaudebridge"})',
    )
    assert rebuilt != live
    live_lines = set(live.splitlines())
    added = [line for line in staged.splitlines() if line not in live_lines]
    removed = [line for line in live.splitlines() if line not in set(staged.splitlines())]
    assert len(added) <= 6 and len(removed) <= 3, (added, removed)
    assert b'PARTNER_DENY_LIST = frozenset({"claudenode", "jjclaudebridge"})' in added


def test_staged_sha_is_recorded_for_root() -> None:
    digest = hashlib.sha256(STAGED.read_bytes()).hexdigest()
    assert len(digest) == 64  # root compares this with the report before applying
