"""MCP side of the Claude bridge: bridge_pending / bridge_wait / bridge_answer + heartbeat."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

SERVER_PATH = Path(__file__).with_name("jenniejoy_comfy_mcp.py")


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Any:
    name = f"jenniejoy_comfy_mcp_bridge_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


@pytest.fixture
def core(server: Any) -> Any:
    return server._bridge_core()


@pytest.fixture
def paths(server: Any, core: Any) -> Any:
    return server._bridge_paths(core)


def _queue(core: Any, paths: Any, prompt: str = "q", images: list[dict[str, str]] | None = None) -> str:
    key = core.cache_key("sys", prompt, [ref["sha256"] for ref in images or []])
    core.write_request(paths, key, "sys", prompt, images or [], 60)
    return key


def _call(server: Any, name: str, arguments: dict[str, Any]) -> tuple[bool, Any]:
    result = server._call_tool(name, arguments)
    return result["isError"], json.loads(result["content"][0]["text"])


def test_bridge_pending_lists_and_reads(server: Any, core: Any, paths: Any) -> None:
    sha = "ab" * 32
    core.save_images(paths, [core.ImageBlob(sha, b"png-bytes")])
    key = _queue(core, paths, "x" * 500, [{"sha256": sha, "path": f"images/{sha}.png"}])
    failed, listing = _call(server, "bridge_pending", {})
    assert not failed and listing["count"] == 1 and listing["post_called"] is False
    item = listing["pending"][0]
    assert item["request_id"] == key and item["prompt_chars"] == 500
    assert len(item["prompt_preview"]) == 300 and "prompt" not in item
    assert item["images"] == [{"sha256": sha, "host_path": str(paths.image(sha)), "exists": True}]
    failed, detail = _call(server, "bridge_pending", {"request_id": key})
    assert not failed
    request = detail["request"]
    assert request["prompt"] == "x" * 500 and request["system"] == "sys"
    assert request["answered"] is False


def test_bridge_pending_hides_answered_and_refuses_unknown(server: Any, core: Any, paths: Any) -> None:
    key = _queue(core, paths)
    failed, _ = _call(server, "bridge_answer", {"request_id": key, "answer": "ok", "confirm": "ANSWER"})
    assert not failed
    failed, listing = _call(server, "bridge_pending", {})
    assert listing["count"] == 0
    failed, error = _call(server, "bridge_pending", {"request_id": "1" * 64})
    assert failed and "unknown request_id" in error["error"]
    failed, error = _call(server, "bridge_pending", {"request_id": "../../etc/passwd"})
    assert failed and "request_id" in error["error"]


def test_bridge_answer_requires_exact_confirm(server: Any, core: Any, paths: Any) -> None:
    key = _queue(core, paths)
    for confirm in ("answer", "YES", "", "ANSWER "):
        failed, error = _call(server, "bridge_answer", {"request_id": key, "answer": "a", "confirm": confirm})
        assert failed and "confirm" in error["error"]
    assert not list(paths.outbox.glob("*.json"))
    failed, error = _call(server, "bridge_answer", {"request_id": key, "answer": "a"})
    assert failed and "invalid tool arguments" in error["error"]  # confirm is required


def test_bridge_answer_writes_atomically_and_never_overwrites(server: Any, core: Any, paths: Any) -> None:
    key = _queue(core, paths)
    failed, done = _call(server, "bridge_answer", {
        "request_id": key, "answer": "Xin chào — hello", "confirm": "ANSWER",
        "model_reported": "claude-code-chat"})
    assert not failed and done["request_id"] == key
    stored = json.loads(paths.entry(paths.outbox, key).read_text("utf-8"))
    assert stored["answer"] == "Xin chào — hello" and stored["model_reported"] == "claude-code-chat"
    assert stored["answer_sha256"] == done["answer_sha256"]
    assert not list(paths.outbox.glob("*.tmp"))
    failed, error = _call(server, "bridge_answer", {"request_id": key, "answer": "again", "confirm": "ANSWER"})
    assert failed and "already answered" in error["error"]
    assert json.loads(paths.entry(paths.outbox, key).read_text("utf-8"))["answer"] == "Xin chào — hello"


@pytest.mark.parametrize("bad", ["9" * 64, "../" + "9" * 61, "..\\" + "9" * 62, "A" * 64, "x", "9" * 64 + "/.."])
def test_bridge_answer_refuses_unknown_and_traversal_ids(server: Any, paths: Any, bad: str) -> None:
    failed, error = _call(server, "bridge_answer", {"request_id": bad, "answer": "a", "confirm": "ANSWER"})
    assert failed and "answer refused" in error["error"]
    assert not paths.outbox.exists() or not list(paths.outbox.glob("*"))
    assert not list(paths.base.parent.rglob("*.json")) or all(
        paths.base in p.parents for p in paths.base.parent.rglob("*.json")
    )


def test_bridge_answer_refuses_empty_or_non_string_answers(server: Any, core: Any, paths: Any) -> None:
    key = _queue(core, paths)
    for answer in ("", "   ", 5, None):
        failed, error = _call(server, "bridge_answer", {"request_id": key, "answer": answer, "confirm": "ANSWER"})
        assert failed and "answer refused" in error["error"]


@pytest.mark.parametrize("tool", ["bridge_pending", "bridge_wait", "bridge_answer"])
def test_only_bridge_tools_refresh_the_heartbeat(server: Any, core: Any, paths: Any, tool: str) -> None:
    assert core.heartbeat_age(paths) is None
    arguments: dict[str, Any] = {
        "bridge_wait": {"timeout_s": 1},
        "bridge_pending": {},
        "bridge_answer": {"request_id": "1" * 64, "answer": "a", "confirm": "ANSWER"},
    }[tool]
    _call(server, tool, arguments)  # bridge_answer fails (unknown id) but still proves a chat is here
    beat = json.loads(paths.heartbeat.read_text("utf-8"))
    assert beat["tool"] == tool and core.chat_is_live(paths)
    assert not list(paths.base.glob("*.tmp"))


@pytest.mark.parametrize("tool,arguments", [
    ("episode_receipts", {"episode_dir": "does-not-exist"}),
    ("comfy_job", {"receipt_dir": "does-not-exist"}),
    ("seedvr2_run_status", {"plan_path": "does-not-exist.json"}),
])
def test_unrelated_tool_calls_do_not_make_the_chat_look_live(
    server: Any, core: Any, paths: Any, tool: str, arguments: dict[str, Any]
) -> None:
    _call(server, tool, arguments)
    assert core.heartbeat_age(paths) is None and not core.chat_is_live(paths)
    assert not paths.heartbeat.exists()


def test_unrelated_call_then_auto_does_not_wait_for_a_chat(server: Any, core: Any, paths: Any) -> None:
    _call(server, "episode_receipts", {"episode_dir": "does-not-exist"})
    with pytest.raises(core.NoRouteAvailable):  # no router here: loud, immediate, nothing queued
        core.resolve(paths, system="", prompt="q", mode="auto", env={}, timeout_s=600)
    assert core.list_pending(paths) == []


def test_unknown_tool_does_not_beat(server: Any, core: Any, paths: Any) -> None:
    failed, _ = _call(server, "no_such_tool", {})
    assert failed and core.heartbeat_age(paths) is None


def test_bridge_wait_returns_when_something_is_pending(server: Any, core: Any, paths: Any) -> None:
    key = _queue(core, paths)
    started = time.monotonic()
    failed, report = _call(server, "bridge_wait", {"timeout_s": 30})
    assert not failed and report["timed_out"] is False and time.monotonic() - started < 5
    assert report["pending"][0]["request_id"] == key
    assert core.chat_is_live(paths)


def test_bridge_wait_times_out_cleanly_and_clamps(server: Any, core: Any, paths: Any) -> None:
    started = time.monotonic()
    failed, report = _call(server, "bridge_wait", {"timeout_s": 0})  # clamped to 1 s
    elapsed = time.monotonic() - started
    assert not failed and report["timed_out"] is True and report["count"] == 0
    assert 0.9 <= elapsed < 6
    assert core.chat_is_live(paths)
    assert server.BRIDGE_WAIT_MAX_SECONDS == 100.0


def test_default_shared_folder_is_the_comfyui_user_dir(
    server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JJ_BRIDGE_SHARED", raising=False)
    base = server._bridge_paths(server._bridge_core()).base
    assert base == server.ROOT / "production-local" / "ComfyUI" / "user" / "claude-bridge"


def test_missing_core_breaks_only_the_bridge_tools(
    server: Any, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    monkeypatch.setattr(server, "BRIDGE_CORE_PATH", Path(os.devnull).parent / "nope" / "bridge_core.py")
    monkeypatch.setattr(server, "_BRIDGE_CORE", None)
    failed, error = _call(server, "bridge_pending", {})
    assert failed and "claude bridge core is missing" in error["error"]
    failed, error = _call(server, "episode_receipts", {"episode_dir": "does-not-exist"})
    assert failed and "bridge" not in error["error"]  # an ordinary episode_dir error


def test_stdio_roundtrip_unknown_answer_is_an_error_not_a_crash() -> None:
    env = os.environ.copy()
    process = subprocess.Popen(
        [sys.executable, "-I", SERVER_PATH.name],
        cwd=SERVER_PATH.parent,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    try:
        assert process.stdin is not None and process.stdout is not None
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "bridge_answer",
            "arguments": {"request_id": "7" * 64, "answer": "x", "confirm": "ANSWER"}}}
        process.stdin.write(json.dumps(call) + "\n")
        process.stdin.flush()
        result = json.loads(process.stdout.readline())["result"]
        assert result["isError"] is True
        assert "unknown request_id" in json.loads(result["content"][0]["text"])["error"]
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n")
        process.stdin.flush()
        assert json.loads(process.stdout.readline())["result"] == {}
    finally:
        process.terminate()
        process.wait(timeout=10)
