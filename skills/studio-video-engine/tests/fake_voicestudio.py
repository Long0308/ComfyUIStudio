"""A fake VoiceStudio on 127.0.0.1 (ephemeral port) for the voice-stage tests.

Surface: ``GET /history`` (list), ``POST /generate`` (multipart form -> JSON ``{"id"}`` or WAV
bytes), ``GET /audio/<id>.wav``.  Modes: ``normal``, ``wav`` (answer the WAV body with
``X-Audio-Id``), ``drop`` (close the socket after the request), ``status:<code>``,
``truncated`` (declared length longer than the body), ``no_id`` (JSON without id), ``duplicate``
(generate twice in history, then drop the answer: the ambiguous reconcile case).  The real
VoiceStudio (port 8080) is never contacted: the fake binds to port 0.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from wav_fixtures import tone_wav_bytes

_FIELD = re.compile(rb'name="([^"]+)"\r\n\r\n(.*?)\r\n--', re.S)


class FakeVoiceStudio:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.audio: dict[str, bytes] = {}
        self.requests: list[tuple[str, str]] = []
        self.posts: list[dict] = []
        self.post_mode = "normal"
        self.history_mode = "normal"  # "status:<code>" | "drop"
        self.counter = 0
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def posts_made(self) -> int:
        return sum(1 for method, _ in self.requests if method == "POST")

    def add_take(self, fields: dict, audio_id: str | None = None, seconds: float = 0.5) -> str:
        """Server-side completion of a request (as if the lost POST had succeeded)."""
        with self.lock:
            self.counter += 1
            audio_id = audio_id or f"{self.counter:08x}"
            self.audio[audio_id] = tone_wav_bytes(seconds=seconds, rate=24_000, channels=1)
            self.history.append({"id": audio_id, "text": fields.get("text"), "profile_id": fields.get("profile_id"),
                                 "language": fields.get("language"), "engine": fields.get("engine"),
                                 "duration_seconds": seconds, "created_unix": time.time()})
        return audio_id

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                return

            def _send(self, code: int, body: bytes, content_type: str = "application/json",
                      extra: dict | None = None) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def _drop(self) -> None:
                self.close_connection = True
                self.wfile.close()

            def do_GET(self) -> None:  # noqa: N802
                fake.requests.append(("GET", self.path))
                if self.path == "/history":
                    if fake.history_mode.startswith("status:"):
                        return self._send(int(fake.history_mode.split(":")[1]), b"{}")
                    if fake.history_mode == "drop":
                        return self._drop()
                    return self._send(200, json.dumps(list(fake.history)).encode())
                match = re.fullmatch(r"/audio/([A-Za-z0-9_-]+)\.wav", self.path)
                if match and match.group(1) in fake.audio:
                    return self._send(200, fake.audio[match.group(1)], "audio/wav")
                return self._send(404, b'{"error":"not found"}')

            def do_POST(self) -> None:  # noqa: N802
                fake.requests.append(("POST", self.path))
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                fields = {k.decode(): v.decode("utf-8") for k, v in _FIELD.findall(raw)}
                fake.posts.append(fields)
                if self.path != "/generate":
                    return self._send(404, b"{}")
                mode = fake.post_mode
                if mode.startswith("status:"):
                    return self._send(int(mode.split(":")[1]), b'{"error":"mode"}')
                if mode == "no_id":
                    return self._send(200, b'{"ok":true}')
                if mode == "duplicate":
                    fake.add_take(fields)
                    fake.add_take(fields)
                    return self._drop()
                audio_id = fake.add_take(fields)
                if mode == "drop":
                    return self._drop()
                if mode == "truncated":
                    body = json.dumps({"id": audio_id}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body) + 50))
                    self.end_headers()
                    self.wfile.write(body)
                    return self._drop()
                if mode == "wav":
                    return self._send(200, fake.audio[audio_id], "audio/wav", {"X-Audio-Id": audio_id})
                return self._send(200, json.dumps({"id": audio_id}).encode())

        return Handler

    def __enter__(self) -> "FakeVoiceStudio":
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
