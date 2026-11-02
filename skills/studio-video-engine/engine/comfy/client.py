"""Minimal ComfyUI HTTP client: stdlib only, explicit timeout on every request.

Every transport problem (refused connection, timeout, HTTP error status, truncated body,
non-JSON body) becomes :class:`ComfyError`, an ``Uncertain``.  The client never retries and
never decides what an error means: whether a POST error is "nothing queued" is unknowable, so
``engine.comfy.dispatch`` treats any post-intent error as exit 2.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from typing import Any

from ..core.errors import Uncertain


class ComfyError(Uncertain):
    """A request to ComfyUI failed; carries the HTTP status/body when there was one."""

    def __init__(self, message: str, *, http_status: int | None = None, body: str = "") -> None:
        super().__init__(message, evidence={"http_status": http_status})
        self.http_status = http_status
        self.body = body


class ComfyClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("HTTP timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, payload: object | None,
                 timeout: float | None) -> Any:
        if not path.startswith("/"):
            raise ValueError(f"ComfyUI path must start with '/': {path!r}")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Accept": "application/json",
                     **({"Content-Type": "application/json"} if data is not None else {})},
        )
        label = f"{method} {path}"
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout_seconds) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", "replace")
            raise ComfyError(f"{label} answered HTTP {error.code}: {text[:300]}",
                             http_status=error.code, body=text) from error
        except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
            raise ComfyError(f"{label} failed: {error!r}") from error
        try:
            return json.loads(body) if body.strip() else {}
        except ValueError as error:
            raise ComfyError(f"{label} returned non-JSON body") from error

    def get(self, path: str, *, timeout: float | None = None) -> Any:
        return self._request("GET", path, None, timeout)

    def post(self, path: str, payload: object, *, timeout: float | None = None) -> Any:
        return self._request("POST", path, payload, timeout)
