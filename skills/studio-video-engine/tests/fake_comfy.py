"""A fake ComfyUI on 127.0.0.1 (ephemeral port, ThreadingHTTPServer) for M4 tests.

It records every request.  The real ComfyUI (port 8188) is never contacted by any test: the
fake binds to port 0 and tests pass its URL through ComfySettings.

Modes cover the failure shapes the v004 executor and the guarded helper tests exercised:
dropped POST connection, HTTP error status, truncated body (IncompleteRead), 500 on /queue,
flaky /history/<id>, slow /object_info.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

DEFAULT_INFO = {"python_module": "nodes", "category": "test"}


class FakeComfy:
    def __init__(self) -> None:
        self.queue: dict[str, list] = {"queue_running": [], "queue_pending": []}
        self.history: dict[str, Any] = {}
        self.requests: list[tuple[str, str]] = []
        self.posts: list[dict] = []
        self.object_info: dict[str, dict] = {}  # overrides of DEFAULT_INFO
        self.unknown: set[str] = set()
        self.on_post: Callable[[dict, str], dict | None] | None = None  # (payload, prompt_id) -> outputs
        self.auto_complete = False  # POST immediately writes a success history entry, queue stays idle
        self.complete_status: dict = {"status_str": "success", "completed": True}
        self.post_mode = "normal"  # "drop" | "incomplete" | "status:<code>" | "no_prompt_id"
        self.queue_mode = "normal"  # "incomplete" | "status:<code>"
        self.history_mode = "normal"  # "incomplete"
        self.history_fail_count = 0
        self.object_info_delay = 0.0
        self.get_delay = 0.0
        self.lose_next_posts = 0  # accept the POST, answer a prompt_id, then "crash": nothing is queued/rendered
        self.on_lose: Callable[[], None] | None = None  # e.g. mark the fake container as restarted
        self.counter = 0
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def posts_made(self) -> list[tuple[str, str]]:
        return [r for r in self.requests if r[0] == "POST"]

    def add_history(self, prompt_id: str, graph: dict, client_id: str, outputs: dict | None = None,
                    status: dict | None = None) -> None:
        self.history[prompt_id] = {"prompt": [1, prompt_id, graph, {"client_id": client_id}, ["15"]],
                                   "status": status or self.complete_status, "outputs": outputs or {}}

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def _send(self, code: int, body: object) -> None:
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _truncated(self) -> None:
                self.send_response(200)
                self.send_header("Content-Length", "500")
                self.end_headers()
                self.wfile.write(b'{"queue_run')
                self.wfile.flush()
                self.close_connection = True

            def do_GET(self) -> None:  # noqa: N802
                fake.requests.append(("GET", self.path))
                time.sleep(fake.get_delay)
                path = self.path
                if path == "/queue":
                    if fake.queue_mode == "incomplete":
                        return self._truncated()
                    if fake.queue_mode.startswith("status:"):
                        return self._send(int(fake.queue_mode[7:]), {"error": "down"})
                    return self._send(200, fake.queue)
                if path.startswith("/object_info/"):
                    time.sleep(fake.object_info_delay)
                    name = path.rsplit("/", 1)[1]
                    if name in fake.unknown:
                        return self._send(200, {})
                    return self._send(200, {name: fake.object_info.get(name, DEFAULT_INFO)})
                if path.startswith("/history/"):
                    if fake.history_mode == "incomplete":
                        return self._truncated()
                    if fake.history_fail_count > 0:
                        fake.history_fail_count -= 1
                        return self._send(500, {"error": "flaky"})
                    pid = path.rsplit("/", 1)[1]
                    return self._send(200, {pid: fake.history[pid]} if pid in fake.history else {})
                if path == "/history" or path.startswith("/history?"):
                    return self._send(200, fake.history)
                if path == "/system_stats":
                    return self._send(200, {"devices": [{"name": "gpu", "vram_free": 8 << 30,
                                                         "vram_total": 16 << 30}]})
                self._send(404, {})

            def do_POST(self) -> None:  # noqa: N802
                fake.requests.append(("POST", self.path))
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                with fake.lock:
                    fake.posts.append(payload)
                    fake.counter += 1
                    prompt_id = f"pid-{fake.counter:04d}"
                if fake.lose_next_posts > 0:
                    fake.lose_next_posts -= 1
                    if fake.on_lose:
                        fake.on_lose()
                    return self._send(200, {"prompt_id": prompt_id, "number": 1, "node_errors": {}})
                outputs = fake.on_post(payload, prompt_id) if fake.on_post else None
                if fake.post_mode == "drop":
                    self.close_connection = True
                    self.connection.close()
                    return
                if fake.post_mode == "incomplete":  # http.client.IncompleteRead (a pure HTTPException)
                    return self._truncated()
                if fake.post_mode.startswith("status:"):
                    return self._send(int(fake.post_mode[7:]), {"error": "bad prompt"})
                if fake.post_mode == "no_prompt_id":
                    return self._send(200, {"number": 1})
                if fake.auto_complete:
                    fake.add_history(prompt_id, payload["prompt"], payload["client_id"], outputs)
                else:
                    fake.queue["queue_running"] = [[1, prompt_id, payload["prompt"],
                                                    {"client_id": payload["client_id"]}, ["15"]]]
                self._send(200, {"prompt_id": prompt_id, "number": 1, "node_errors": {}})

        return Handler

    def __enter__(self) -> "FakeComfy":
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
