"""VoiceStudio HTTP client (stdlib, explicit timeouts) and the protocol the synth verbs need.

Surface known from the first batch tool: ``GET /history`` (list or ``{"history": [...]}``),
``POST /generate`` (multipart form; answers JSON ``{"id": ...}`` or WAV bytes with
``X-Audio-Id``), ``GET /audio/<id>.wav``.  Transport problems and 5xx are
:class:`VoiceStudioError` (Uncertain); a 4xx is :class:`VoiceStudioRejected` (Failed, exit 4:
after a POST exit 1 is impossible).  The client never retries and never decides what an
error means.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
import uuid
from typing import Any, Mapping, Protocol

from ..core.errors import Failed, Uncertain

WAV_CONTENT_TYPES = ("audio/wav", "audio/x-wav", "audio/wave")


class VoiceStudioError(Uncertain):
    """Request failed or its outcome is unknown; carries the HTTP status when there was one."""

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message, evidence={"http_status": http_status})
        self.http_status = http_status


class VoiceStudioRejected(Failed):
    """VoiceStudio answered a deterministic client error (4xx)."""


class VoiceStudio(Protocol):
    def history(self) -> list[dict]: ...
    def generate(self, fields: Mapping[str, str]) -> dict: ...
    def download(self, audio_id: str) -> bytes: ...


def normalize_history(value: object) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict) and isinstance(value.get("history"), list):
        return [item for item in value["history"] if isinstance(item, dict)]
    raise VoiceStudioError("GET /history returned an unexpected shape")


def multipart(fields: Mapping[str, str]) -> tuple[bytes, str]:
    boundary = "jjv" + uuid.uuid4().hex
    chunks = [(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n").encode("utf-8")
              for key, value in fields.items()]
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), boundary


class VoiceStudioClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 300.0, read_timeout_seconds: float = 60.0) -> None:
        if timeout_seconds <= 0 or read_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.read_timeout_seconds = read_timeout_seconds

    def _open(self, request: urllib.request.Request, label: str, timeout: float) -> tuple[bytes, Any]:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(), response.headers
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", "replace")[:400]
            if 400 <= error.code < 500:
                raise VoiceStudioRejected(f"{label} rejected: HTTP {error.code}: {text}") from error
            raise VoiceStudioError(f"{label} answered HTTP {error.code}; outcome unknown: {text}",
                                   http_status=error.code) from error
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as error:
            raise VoiceStudioError(f"{label} failed; outcome unknown: {error!r}") from error

    def history(self) -> list[dict]:
        body, _ = self._open(urllib.request.Request(self.base_url + "/history"), "GET /history",
                             self.read_timeout_seconds)
        try:
            return normalize_history(json.loads(body))
        except ValueError as error:
            raise VoiceStudioError("GET /history returned non-JSON") from error

    def generate(self, fields: Mapping[str, str]) -> dict:
        data, boundary = multipart(fields)
        request = urllib.request.Request(self.base_url + "/generate", data=data, method="POST",
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        body, headers = self._open(request, "POST /generate", self.timeout_seconds)
        content_type = headers.get_content_type() if headers is not None else ""
        if content_type in WAV_CONTENT_TYPES or body[:4] == b"RIFF":
            return {"id": headers.get("X-Audio-Id"), "wav_bytes": body}
        try:
            value = json.loads(body) if body.strip() else {}
        except ValueError as error:
            raise VoiceStudioError("POST /generate answered a non-JSON, non-WAV body") from error
        return value if isinstance(value, dict) else {}

    def download(self, audio_id: str) -> bytes:
        body, _ = self._open(urllib.request.Request(f"{self.base_url}/audio/{audio_id}.wav"),
                             f"GET /audio/{audio_id}.wav", self.read_timeout_seconds)
        return body
