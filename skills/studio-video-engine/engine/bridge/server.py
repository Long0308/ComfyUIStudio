"""Loopback HTTP server of the bridge (stdlib ``ThreadingHTTPServer``); one JSON envelope per response.

Bind loopback only (127.0.0.1, ::1, localhost; anything else is refused): Docker Desktop forwards ``host.docker.internal`` from a container to the host loopback (measured
2026-10-31: a listener on 127.0.0.1 answered a request from the ComfyUI container).  LAN and wildcard addresses are refused.
"""

from __future__ import annotations

import json
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from ..core.errors import EngineError, Refused
from . import images_job, secret as secret_mod, video_job
from .config import BridgeConfig
from .jobs import BridgeBusy, JobStore

LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
MAX_BODY = 192 * 1024 * 1024  # 8 refs of <= 20 MB as base64, with room
ROUTES = ["GET /v1/health", "POST /v1/images/codex", "POST /v1/video/shot", "GET /v1/jobs/<id>"]
JOB_PATH = re.compile(r"/v1/jobs/([A-Za-z0-9_-]+)")


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], cfg: BridgeConfig) -> None:
        self.cfg = cfg
        self.store = JobStore(cfg.jobs_dir)
        self.secret = secret_mod.load_or_create(cfg.secret_path)
        super().__init__(address, Handler)


class BridgeServer6(BridgeServer):
    address_family = socket.AF_INET6


class Handler(BaseHTTPRequestHandler):
    server_version = "jjv-bridge/1"
    server: BridgeServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return  # no access log: request lines never carry the secret, but bodies hold prompts; keep stdout for the start line

    def _send(self, code: int, doc: dict[str, Any]) -> None:
        payload = json.dumps(doc, ensure_ascii=True).encode("ascii")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self) -> bool:
        if secret_mod.authorized(self.headers, self.server.secret):
            return True
        self._send(401, {"ok": False, "error": "missing or wrong bridge secret (Authorization: Bearer <secret file content>)"})
        return False

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise Refused("request body is empty (JSON object expected)")
        if length > MAX_BODY:
            raise Refused(f"request body is {length} bytes; at most {MAX_BODY}")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise Refused(f"request body is not JSON: {error}") from error

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        path = urlparse(self.path).path
        if path == "/v1/health":
            self._send(200, {"ok": True, "service": "jjv-bridge", "routes": ROUTES, "secret_required": True,
                             "accounts": list(self.server.cfg.accounts)})
            return
        if not self._authorized():
            return
        match = JOB_PATH.fullmatch(path)
        doc = self.server.store.view(match.group(1)) if match else None
        if doc is None:
            self._send(404, {"ok": False, "error": f"no such job or route: {path}"})
        else:
            self._send(200, {"ok": True, **doc})

    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        if not self._authorized():
            return
        path = urlparse(self.path).path
        handlers = {"/v1/images/codex": images_job.start, "/v1/video/shot": video_job.start}
        if path not in handlers:
            self._send(404, {"ok": False, "error": f"no such route: {path}"})
            return
        try:
            result = handlers[path](self.server.cfg, self.server.store, self._body())
            self._send(202, {"ok": True, **result})
        except BridgeBusy as error:
            self._send(409, {"ok": False, "error": str(error)})
        except Refused as error:
            self._send(400, {"ok": False, "error": str(error)})
        except EngineError as error:
            self._send(400, {"ok": False, "error": str(error)})
        except Exception as error:  # noqa: BLE001 - JSON error, never a traceback page
            self._send(500, {"ok": False, "error": f"{type(error).__name__}: {error}"})


def check_loopback_host(host: str) -> bool:
    """True only for 127.0.0.1, ::1 or localhost (a whitelist: LAN addresses and wildcards are both refused)."""
    if host.strip().lower() not in LOOPBACK_HOSTS:
        raise Refused(f"bind address {host!r} refused: loopback only ({', '.join(LOOPBACK_HOSTS)}); containers reach it "
                      "through host.docker.internal on Docker Desktop")
    return True


def make_server(cfg: BridgeConfig, host: str, port: int) -> BridgeServer:
    check_loopback_host(host)  # before the state folder or the secret exist
    return (BridgeServer6 if host.strip() == "::1" else BridgeServer)((host, int(port)), cfg)
