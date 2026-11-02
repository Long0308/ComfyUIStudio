from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import types
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

SERVER_PATH = Path(__file__).with_name("jenniejoy_comfy_mcp.py")
STAGED_MCP_ROOT = SERVER_PATH.parent


def _workspace_root() -> Path:
    for candidate in (SERVER_PATH.parent, *SERVER_PATH.parents):
        if (candidate / ".agents").is_dir() and (candidate / "production-local").is_dir():
            return candidate
    raise RuntimeError(f"cannot locate workspace root above {SERVER_PATH}")


WORKSPACE_ROOT = _workspace_root()
TEST_WORK_ROOT = STAGED_MCP_ROOT.parent / "test-work"


@pytest.fixture
def tmp_path() -> Any:
    """Use a normal workspace ACL instead of pytest's owner-only temp ACL."""
    TEST_WORK_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEST_WORK_ROOT / f"case-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def server_module() -> Any:
    name = f"jenniejoy_comfy_mcp_test_{uuid.uuid4().hex}"
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
def injected_server(server_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    lock_path = tmp_path / "injected-helper.lock"
    output_dir = tmp_path / "injected-output"
    monkeypatch.setattr(server_module.GUARDED, "DEFAULT_LOCK_PATH", lock_path)
    monkeypatch.setattr(server_module.GUARDED, "DEFAULT_OUTPUT_DIR", output_dir)
    return server_module


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


class FakeComfyState:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.posts = 0
        self.prompt_id = "fake-prompt-0001"


class FakeComfyHandler(BaseHTTPRequestHandler):
    server: "FakeComfyServer"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, value: object, status: int = 200) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self.server.state.requests.append(("GET", self.path))
        if self.path == "/queue":
            self._send({"queue_running": [], "queue_pending": []})
            return
        if self.path == "/history":
            self._send({})
            return
        if self.path == "/system_stats":
            self._send(
                {
                    "system": {
                        "os": "linux",
                        "argv": ["main.py", "--port", "8188"],
                        "comfyui_version": "fake",
                    },
                    "devices": [
                        {
                            "name": "fake cuda",
                            "type": "cuda",
                            "index": 0,
                            "vram_free": 8 * 1048576,
                            "vram_total": 16 * 1048576,
                            "torch_vram_free": 4 * 1048576,
                            "torch_vram_total": 8 * 1048576,
                        }
                    ],
                }
            )
            return
        if self.path == "/object_info/ClassA":
            self._send(
                {"ClassA": {"python_module": "nodes", "category": "test"}}
            )
            return
        if self.path == "/object_info/PartnerNode":
            self._send(
                {
                    "PartnerNode": {
                        "python_module": "comfy_api_nodes.nodes_example",
                        "category": "api node/video",
                        "api_node": True,
                    }
                }
            )
            return
        if self.path.startswith("/object_info/"):
            self._send({})
            return
        if self.path == "/history/" + self.server.state.prompt_id:
            self._send(
                {
                    self.server.state.prompt_id: {
                        "status": {"status_str": "success", "completed": True},
                        "outputs": {},
                    }
                }
            )
            return
        self._send({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        self.server.state.requests.append(("POST", self.path))
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.server.state.posts += 1
        self._send({"error": "POST is forbidden in MCP v2 tests"}, status=503)


class FakeComfyServer(ThreadingHTTPServer):
    def __init__(self) -> None:
        self.state = FakeComfyState()
        super().__init__(("127.0.0.1", 0), FakeComfyHandler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)


class McpClient:
    """Launch exactly as registered, without PYTHONIOENCODING."""

    def __init__(self, server_path: Path, base_url: str) -> None:
        env = os.environ.copy()
        env.pop("PYTHONIOENCODING", None)
        env.pop("JENNIEJOY_COMFY_LOCK_PATH", None)
        env["JENNIEJOY_COMFY_URL"] = base_url
        self.command = [sys.executable, "-I", server_path.name]
        self.process = subprocess.Popen(
            self.command,
            cwd=server_path.parent,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            bufsize=1,
            env=env,
        )
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stderr_lines: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.next_id = 1

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.messages.put(json.loads(line))

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self.stderr_lines.append(line)

    def send(self, value: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def receive(self, timeout: float = 15.0) -> dict[str, Any]:
        try:
            return self.messages.get(timeout=timeout)
        except queue.Empty as error:
            stderr = "".join(self.stderr_lines[-20:])
            raise AssertionError(
                f"MCP response timed out; returncode={self.process.poll()}; stderr={stderr!r}"
            ) from error

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        self.send(message)
        response = self.receive()
        assert response["id"] == request_id
        return response

    def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        response = self.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        result = response["result"]
        text = result["content"][0]["text"]
        return result, json.loads(text)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)


@pytest.fixture
def fake_comfy() -> Any:
    server = FakeComfyServer()
    server.thread.start()
    try:
        host, port = server.server_address
        yield server, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        server.thread.join(timeout=10)


@pytest.fixture
def mcp_client(fake_comfy: Any) -> Any:
    _, base_url = fake_comfy
    client = McpClient(SERVER_PATH, base_url)
    try:
        yield client
    finally:
        client.close()


def graph_file(tmp_path: Path) -> tuple[Path, str]:
    graph = {"1": {"class_type": "ClassA", "inputs": {}}}
    path = tmp_path / "graph.api.json"
    write_json(path, graph)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_registered_launch_initialize_ping_tools_and_annotations(
    mcp_client: McpClient,
) -> None:
    assert mcp_client.command[1] == "-I"
    assert mcp_client.command[2] == "jenniejoy_comfy_mcp.py"

    initialized = mcp_client.request(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1"},
        },
    )
    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    assert initialized["result"]["capabilities"] == {"tools": {}}
    assert initialized["result"]["serverInfo"]["name"] == "jenniejoy-comfy"

    assert mcp_client.request("ping")["result"] == {}
    listed = mcp_client.request("tools/list")
    tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
    assert set(tools) == {
        "comfy_status",
        "comfy_validate_graph",
        "comfy_submit_guarded",
        "comfy_job",
        "comfy_reconcile",
        "seedvr2_run_status",
        "episode_receipts",
        "bridge_pending",
        "bridge_wait",
        "bridge_answer",
    }
    for name in (
        "comfy_status",
        "comfy_validate_graph",
        "comfy_job",
        "seedvr2_run_status",
        "episode_receipts",
        "bridge_pending",
        "bridge_wait",
    ):
        assert tools[name]["annotations"]["readOnlyHint"] is True
    # comfy_reconcile never POSTs but writes local reconcile receipts (critic N1).
    reconcile_annotations = tools["comfy_reconcile"]["annotations"]
    assert reconcile_annotations["readOnlyHint"] is False
    assert reconcile_annotations["destructiveHint"] is False
    answer_annotations = tools["bridge_answer"]["annotations"]
    assert answer_annotations["readOnlyHint"] is False
    assert answer_annotations["destructiveHint"] is False
    submit_annotations = tools["comfy_submit_guarded"]["annotations"]
    assert submit_annotations["readOnlyHint"] is False
    assert submit_annotations["destructiveHint"] is True


@pytest.mark.parametrize("client_version", ["2025-03-26", "2024-11-05"])
def test_initialize_echoes_supported_client_protocol(
    mcp_client: McpClient, client_version: str
) -> None:
    response = mcp_client.request(
        "initialize",
        {"protocolVersion": client_version, "capabilities": {}, "clientInfo": {}},
    )
    assert response["result"]["protocolVersion"] == client_version


def test_initialize_falls_back_for_unsupported_protocol(
    mcp_client: McpClient,
) -> None:
    response = mcp_client.request(
        "initialize",
        {"protocolVersion": "2099-01-01", "capabilities": {}, "clientInfo": {}},
    )
    assert response["result"]["protocolVersion"] == "2025-06-18"


def test_vietnamese_tools_call_and_error_keep_stdio_alive(
    mcp_client: McpClient, tmp_path: Path
) -> None:
    receipt_dir = tmp_path / "unicode-receipt"
    write_json(
        receipt_dir / "submitted.json",
        {
            "prompt_id": "prompt-unicode",
            "label": "Bé cùng đọc nhé",
            "temperature": "Ấm và lạnh",
        },
    )
    result, report = mcp_client.call_tool(
        "comfy_job", {"receipt_dir": str(receipt_dir)}
    )
    assert result["isError"] is False
    assert report["receipts"]["submitted.json"]["label"] == "Bé cùng đọc nhé"
    assert report["receipts"]["submitted.json"]["temperature"] == "Ấm và lạnh"

    missing = tmp_path / "Bé cùng đọc nhé" / "Ấm và lạnh"
    error_result, error_report = mcp_client.call_tool(
        "episode_receipts", {"episode_dir": str(missing)}
    )
    assert error_result["isError"] is True
    assert "Bé cùng đọc nhé" in error_report["error"]
    assert mcp_client.request("ping")["result"] == {}
    assert mcp_client.process.poll() is None


def test_serve_continues_after_one_response_write_fails(server_module: Any) -> None:
    messages = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
    ]

    class FlakyTarget:
        def __init__(self) -> None:
            self.calls = 0
            self.payloads: list[str] = []

        def write(self, value: str) -> None:
            self.calls += 1
            if self.calls == 1:
                raise UnicodeEncodeError("cp1252", value, 0, 1, "simulated")
            self.payloads.append(value)

        def flush(self) -> None:
            return

    target = FlakyTarget()
    assert server_module.serve(iter(messages), target) == 0
    assert target.calls == 2
    assert len(target.payloads) == 1
    assert json.loads(target.payloads[0])["id"] == 2


@pytest.mark.parametrize(
    "base_url",
    [
        "HTTP://127.0.0.1:8188",
        "http://localhost:8188",
        "http://[::1]:8188",
    ],
)
def test_production_lock_env_override_is_ignored(
    injected_server: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    expected = tmp_path / "injected-helper.lock"
    override = tmp_path / "attacker-selected.lock"
    monkeypatch.setenv("JENNIEJOY_COMFY_URL", base_url)
    monkeypatch.setenv("JENNIEJOY_COMFY_LOCK_PATH", str(override))
    settings = injected_server._settings()
    assert Path(settings.lock_path) == expected


@pytest.mark.parametrize(
    "base_url",
    [
        "http://192.0.2.1:8188",
        "https://example.com:8188",
        "http://127.0.0.2:8188",
        "http://localhost.evil:8188",
    ],
)
def test_non_loopback_comfy_url_is_rejected(
    injected_server: Any, monkeypatch: pytest.MonkeyPatch, base_url: str
) -> None:
    monkeypatch.setenv("JENNIEJOY_COMFY_URL", base_url)
    with pytest.raises(injected_server.ToolError, match="loopback"):
        injected_server._settings()


def test_comfy_url_with_credentials_is_rejected(
    injected_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "JENNIEJOY_COMFY_URL", "http://user:pass@127.0.0.1:8188"
    )
    with pytest.raises(injected_server.ToolError, match="credentials"):
        injected_server._settings()


def test_episode_receipts_rejects_parent_traversal_before_glob(
    injected_server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = tmp_path / "episode"
    episode.mkdir()

    def forbidden_rglob(self: Path, pattern: str) -> Any:
        raise AssertionError("rglob must not run for a refused pattern")

    monkeypatch.setattr(Path, "rglob", forbidden_rglob)
    critic_pattern = "../" * 11 + "*.json"
    with pytest.raises(injected_server.ToolError, match="pattern"):
        injected_server.episode_receipts(str(episode), critic_pattern)


@pytest.mark.parametrize(
    "pattern",
    [
        r"C:\Windows\*.json",
        r"D:relative\*.json",
        "/etc/*.json",
        r"\Windows\*.json",
        "nested/../../*.json",
    ],
)
def test_episode_receipts_rejects_absolute_and_parent_patterns(
    injected_server: Any, tmp_path: Path, pattern: str
) -> None:
    episode = tmp_path / "episode"
    episode.mkdir()
    with pytest.raises(injected_server.ToolError, match="pattern"):
        injected_server.episode_receipts(str(episode), pattern)


def test_episode_receipts_never_opens_resolved_path_outside_episode(
    injected_server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = tmp_path / "episode"
    episode.mkdir()
    outside = tmp_path / "outside.json"
    write_json(outside, {"status": "MUST_NOT_BE_OPENED"})

    original_rglob = Path.rglob

    def leaking_rglob(self: Path, pattern: str) -> Any:
        if self == episode.resolve():
            return iter([outside])
        return original_rglob(self, pattern)

    monkeypatch.setattr(Path, "rglob", leaking_rglob)
    with pytest.raises(injected_server.ToolError, match="outside episode_dir"):
        injected_server.episode_receipts(str(episode), "*.json")


def test_comfy_job_reads_unknown_and_rejected_receipts(
    injected_server: Any, tmp_path: Path
) -> None:
    receipt_dir = tmp_path / "receipt"
    write_json(receipt_dir / "dispatch-intent.json", {"client_id": "client-1"})
    write_json(
        receipt_dir / "submit-unknown.json",
        {"status": "DISPATCH_STATUS_UNKNOWN", "client_id": "client-1"},
    )
    write_json(
        receipt_dir / "submit-rejected.json",
        {"status": "REJECTED_BY_COMFY", "client_id": "client-1"},
    )
    report = injected_server.comfy_job(str(receipt_dir))
    assert (
        report["receipts"]["submit-unknown.json"]["status"]
        == "DISPATCH_STATUS_UNKNOWN"
    )
    assert report["receipts"]["submit-rejected.json"]["status"] == "REJECTED_BY_COMFY"
    assert report["post_called"] is False


def _submit_args(tmp_path: Path) -> tuple[Path, str, Path]:
    graph, sha = graph_file(tmp_path)
    return graph, sha, tmp_path / "receipt"


def test_submit_exit_two_reports_post_called_unknown(
    injected_server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, sha, receipt_dir = _submit_args(tmp_path)

    def ambiguous_submit(settings: Any, args: Any) -> int:
        write_json(
            Path(args.receipt_dir) / "submit-unknown.json",
            {"status": "DISPATCH_STATUS_UNKNOWN", "client_id": "ambiguous"},
        )
        return injected_server.GUARDED.EXIT_ERROR

    monkeypatch.setattr(injected_server.GUARDED, "cmd_submit", ambiguous_submit)
    with pytest.raises(injected_server.ToolError) as caught:
        injected_server.comfy_submit_guarded(
            str(graph), str(receipt_dir), sha, "SUBMIT"
        )
    report = json.loads(str(caught.value))
    assert report["exit_code"] == 2
    assert report["post_called"] == "unknown"


def test_submit_http_rejection_reports_post_called_true(
    injected_server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, sha, receipt_dir = _submit_args(tmp_path)

    def rejected_submit(settings: Any, args: Any) -> int:
        write_json(
            Path(args.receipt_dir) / "submit-rejected.json",
            {"status": "REJECTED_BY_COMFY", "http_status": 400},
        )
        return injected_server.GUARDED.EXIT_REFUSED

    monkeypatch.setattr(injected_server.GUARDED, "cmd_submit", rejected_submit)
    with pytest.raises(injected_server.ToolError) as caught:
        injected_server.comfy_submit_guarded(
            str(graph), str(receipt_dir), sha, "SUBMIT"
        )
    report = json.loads(str(caught.value))
    assert report["exit_code"] == 1
    assert report["post_called"] is True


def test_submit_returns_immediately_without_long_post_hold(
    injected_server: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, sha, receipt_dir = _submit_args(tmp_path)
    observed: dict[str, float] = {}

    def fast_submit(settings: Any, args: Any) -> int:
        observed["hold_timeout"] = args.hold_timeout
        write_json(
            Path(args.receipt_dir) / "submitted.json",
            {"prompt_id": "prompt-fast", "client_id": "client-fast"},
        )
        return injected_server.GUARDED.EXIT_OK

    monkeypatch.setattr(injected_server.GUARDED, "cmd_submit", fast_submit)
    started = time.monotonic()
    report = injected_server.comfy_submit_guarded(
        str(graph), str(receipt_dir), sha, "SUBMIT"
    )
    elapsed = time.monotonic() - started
    assert observed["hold_timeout"] == 0.0
    assert report["post_called"] is True
    assert report["blocking_hold"] is False
    assert elapsed < 2.0


def test_comfy_reconcile_is_get_only(
    injected_server: Any,
    fake_comfy: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, base_url = fake_comfy
    state = server.state
    monkeypatch.setenv("JENNIEJOY_COMFY_URL", base_url)
    receipt_dir = tmp_path / "reconcile-receipt"
    write_json(
        receipt_dir / "dispatch-intent.json",
        {"client_id": "client-to-reconcile", "graph_sha256": "a" * 64},
    )
    report = injected_server.comfy_reconcile(str(receipt_dir))
    assert report["post_called"] is False
    assert report["result"]["client_id"] == "client-to-reconcile"
    assert state.posts == 0
    assert state.requests == [("GET", "/queue"), ("GET", "/history")]


def test_validate_graph_happy_path_and_no_post(
    injected_server: Any,
    fake_comfy: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, base_url = fake_comfy
    state = server.state
    monkeypatch.setenv("JENNIEJOY_COMFY_URL", base_url)
    graph, sha = graph_file(tmp_path)
    report = injected_server.comfy_validate_graph(str(graph), sha)
    assert report["valid"] is True
    assert report["known_classes"] == ["ClassA"]
    assert report["post_called"] is False
    assert state.posts == 0


def test_path_rejection_outside_root(injected_server: Any) -> None:
    with pytest.raises(
        injected_server.ToolError, match="outside the allowed workspace root"
    ):
        injected_server.comfy_validate_graph(r"C:\Windows\win.ini")


def test_seedvr2_status_validates_ids_and_reports_executor_lock(
    injected_server: Any, tmp_path: Path
) -> None:
    technical = tmp_path / "seedvr2-fixture"
    plan = {
        "schema": "milk-and-mom-seedvr2-production-plan/v004",
        "status": "PREPARED_NOT_RENDERED",
        "film_id": "04-milk-and-mom",
        "production_version": "seedvr2-production-v004",
        "shots": [
            {
                "shot_id": "S01_A",
                "chunks": [
                    {"index": 0, "chunk_name": "chunk-0000"},
                    {"index": 1, "chunk_name": "../../escape"},
                ],
            },
            {
                "shot_id": "../../outside",
                "chunks": [{"index": 0, "chunk_name": "chunk-0000"}],
            },
        ],
    }
    plan_path = technical / "PRODUCTION-PLAN.json"
    write_json(plan_path, plan)
    write_json(
        technical / "runs" / "S01_A" / "chunk-0000" / "job.json",
        {"status": "COMPLETED", "prompt_id": "done-1"},
    )
    write_json(
        technical / "outside" / "chunk-0000" / "job.json",
        {"status": "MUST_NOT_BE_READ"},
    )
    executor_lock = technical / "runs" / ".executor.lock"
    executor_lock.write_text("test-only\n", encoding="ascii")

    report = injected_server.seedvr2_run_status(str(plan_path))
    assert report["total_chunks"] == 1
    assert report["completed_chunks"] == 1
    assert len(report["invalid_entries"]) == 2
    assert report["executor_lock"] == {
        "path": str(executor_lock),
        "exists": True,
    }
    assert report["post_called"] is False


@pytest.mark.skipif(os.name != "nt", reason="Windows OpenProcess semantics")
def test_windows_open_process_access_denied_is_unknown(
    injected_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeFunction:
        def __init__(self, result: Any = 0) -> None:
            self.result = result
            self.argtypes = None
            self.restype = None

        def __call__(self, *args: Any) -> Any:
            return self.result

    kernel32 = types.SimpleNamespace(
        OpenProcess=FakeFunction(0),
        GetExitCodeProcess=FakeFunction(0),
        CloseHandle=FakeFunction(1),
    )
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda *args, **kwargs: kernel32, raising=False
    )
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    assert injected_server._process_alive(1234) is None


def test_handler_type_error_is_not_mislabeled_as_bad_arguments(
    injected_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explodes() -> dict[str, Any]:
        raise TypeError("handler bug, not a binding error")

    monkeypatch.setitem(
        injected_server.TOOLS,
        "fixture_type_error",
        (
            "fixture",
            {"type": "object", "properties": {}, "additionalProperties": False},
            explodes,
        ),
    )
    result = injected_server._call_tool("fixture_type_error", {})
    report = json.loads(result["content"][0]["text"])
    assert result["isError"] is True
    assert report["error"].startswith("TypeError:")
    assert "invalid tool arguments" not in report["error"]


def test_invalid_arguments_error_is_structured(mcp_client: McpClient) -> None:
    result, report = mcp_client.call_tool(
        "comfy_validate_graph", {"unexpected": "value"}
    )
    assert result["isError"] is True
    assert report["error"].startswith("invalid tool arguments:")


def test_readme_registration_and_shared_lock_docs() -> None:
    text = Path(__file__).with_name("README.md").read_text(encoding="utf-8")
    assert "Python 3.12+" in text
    assert text.count("-I") >= 3
    assert "python -I" in text
    assert "Do not set\n`PYTHONIOENCODING`" in text
    assert "JENNIEJOY_COMFY_LOCK_PATH" not in text
    assert "04-milk-and-mom/technical/.comfyui-image-submit.lock" in text
    assert "NEWTECONS submissions use the same lock" in text
    assert "seedvr2_run_status" in text
    assert "ep04 production plan" in text
    assert "submitted.json" in text
    assert "does not block the stdio loop" in text
