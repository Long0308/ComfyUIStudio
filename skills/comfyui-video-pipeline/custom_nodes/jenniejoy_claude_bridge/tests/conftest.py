"""Shared fixtures: load the pack like ComfyUI does and fake the OpenAI-compatible gateway."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from _jj_bridge_support import SECRET_TOKEN, load_pack

PACKAGE_NAME = "jj_claude_bridge_pack"


@pytest.fixture(scope="session")
def pack() -> Any:
    return load_pack()


@pytest.fixture(scope="session")
def core(pack: Any) -> Any:
    return sys.modules[f"{PACKAGE_NAME}.bridge_core"]


@pytest.fixture
def shared() -> Any:
    folder = tempfile.mkdtemp(prefix="jj-bridge-test-")
    try:
        yield Path(folder)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def paths(core: Any, shared: Path) -> Any:
    return core.BridgePaths.from_shared(shared)


class FakeGatewayState:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status = 200
        self.error_body = "boom"
        self.reply_text = "gateway answer"
        self.model = "fake-claude-gateway"
        self.counter = 0
        self.redirect_to: str | None = None
        self.trickle_s: float = 0.0  # seconds between body bytes


class _Handler(BaseHTTPRequestHandler):
    server: "FakeGateway"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        state = self.server.state
        state.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": json.loads(raw.decode("utf-8")),
                "raw": raw,
            }
        )
        if state.redirect_to:
            self.send_response(307)
            self.send_header("Location", state.redirect_to)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if state.status != 200:
            payload = json.dumps({"error": {"message": state.error_body}}).encode()
            self.send_response(state.status)
        else:
            state.counter += 1
            text = state.reply_text
            if self.path.endswith("/chat/completions"):
                body: Any = {
                    "model": state.model,
                    "choices": [{"message": {"role": "assistant", "content": text}}],
                }
            elif self.path.endswith("/responses"):
                body = {
                    "model": state.model,
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": text}],
                        }
                    ],
                }
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            payload = json.dumps(body).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if state.trickle_s:
            for index in range(len(payload)):
                try:
                    self.wfile.write(payload[index:index + 1])
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(state.trickle_s)
            return
        self.wfile.write(payload)


class FakeGateway(ThreadingHTTPServer):
    def __init__(self) -> None:
        self.state = FakeGatewayState()
        super().__init__(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server_address
        return f"http://{host}:{port}"


@pytest.fixture
def gateway() -> Any:
    server = FakeGateway()
    server.thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        server.thread.join(timeout=10)


@pytest.fixture
def router_env(gateway: FakeGateway) -> dict[str, str]:
    return {
        "JJ_BRIDGE_BASE_URL": gateway.url,
        "JJ_BRIDGE_MODEL": "claude-via-gateway",
        "JJ_BRIDGE_TOKEN": SECRET_TOKEN,
    }
