"""Core logic of the JennieJoy Claude bridge (stdlib only, no ComfyUI imports).

This module is shared by three consumers, so it must stay importable on its own:

* the ComfyUI node ``JJClaudeBridge`` (inside the ``Comfyui-Studio`` container),
* the host-side ``jenniejoy_comfy_mcp.py`` (tools ``bridge_pending`` / ``bridge_answer``),
* the tests and the host simulation.

Layout under ``<shared>/claude-bridge/`` (``<shared>`` is the host-shared folder)::

    cache/<key>.json      deterministic answer + receipt   (written once, never replaced)
    inbox/<key>.json      request written by the node       (route "chat")
    outbox/<key>.json     answer written by the MCP         (route "chat")
    images/<sha>.png      optional input images, named by their pixel sha256
    heartbeat.json        refreshed ONLY by the MCP tools bridge_wait/bridge_pending/bridge_answer

``<key>`` is the 64-hex sha256 of the canonical request JSON, which doubles as the request id.
No secret is ever written to these files: the router token only lives in the process
environment and is redacted from every error message.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

REQUEST_SCHEMA = "jj-claude-bridge/request-v1"
ANSWER_SCHEMA = "jj-claude-bridge/answer-v1"
CACHE_SCHEMA = "jj-claude-bridge/cache-v1"
RECEIPT_SCHEMA = "jj-claude-bridge/receipt-v1"
KEY_SCHEMA = "jj-claude-bridge/key-v1"
HEARTBEAT_SCHEMA = "jj-claude-bridge/heartbeat-v1"

MODES = ("auto", "cache_only", "chat", "router")
BRIDGE_DIRNAME = "claude-bridge"
HEARTBEAT_MAX_AGE_S = 120.0
HEARTBEAT_MAX_FUTURE_SKEW_S = 5.0
DEFAULT_TIMEOUT_S = 600
MIN_TIMEOUT_S = 1
MAX_TIMEOUT_S = 86400
MAX_ANSWER_BYTES = 512 * 1024
MAX_ERROR_BODY_CHARS = 500
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
PLAIN_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})
READ_RETRIES = 3
READ_RETRY_DELAY_S = 0.05
REPLACE_RETRIES = 10  # Windows: a reader holding the file makes os.replace fail with WinError 5
HEARTBEAT_READ_RETRIES = 5
ENV_SHARED = "JJ_BRIDGE_SHARED"
ENV_BASE_URL = "JJ_BRIDGE_BASE_URL"
ENV_MODEL = "JJ_BRIDGE_MODEL"
ENV_TOKEN = "JJ_BRIDGE_TOKEN"
ENV_API = "JJ_BRIDGE_API"
ROUTER_APIS = ("chat", "responses")

REQUEST_ID_RE = re.compile(r"[0-9a-f]{64}\Z")


class BridgeError(RuntimeError):
    """Base class: every failure is loud, nothing falls back silently."""


class CacheMiss(BridgeError):
    """mode=cache_only and nothing is stored for this request."""


class ChatTimeout(BridgeError):
    """No answer reached the outbox in time; the request stays pending in the inbox."""


class RouterError(BridgeError):
    """The OpenAI-compatible gateway call failed or was misconfigured."""


class NoRouteAvailable(BridgeError):
    """mode=auto found neither a live chat nor a configured router."""


class RefusedRequest(BridgeError):
    """bridge_answer refused: unknown id, already answered, bad input, or path escape."""


# ------------------------------------------------------------------ small helpers
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def is_request_id(value: object) -> bool:
    return isinstance(value, str) and REQUEST_ID_RE.fullmatch(value) is not None


def redact(text: str, secret: str | None) -> str:
    if secret:
        text = text.replace(secret, "[redacted]")
    return text


@dataclass(frozen=True)
class ImageBlob:
    """One authoring image: ``sha256`` is over the pixels, ``png`` the saved file bytes."""

    sha256: str
    png: bytes


def cache_key(system: str, prompt: str, image_hashes: Sequence[str]) -> str:
    """Mode-independent key: only what can change the answer is part of it."""
    return sha256_hex(
        canonical_json(
            {
                "schema": KEY_SCHEMA,
                "system": system,
                "prompt": prompt,
                "images": list(image_hashes),
            }
        )
    )


def clamp_timeout(value: object) -> int:
    try:
        number = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S
    return max(MIN_TIMEOUT_S, min(MAX_TIMEOUT_S, number))


def validate_mode(mode: object) -> str:
    if mode not in MODES:
        raise BridgeError(f"mode must be one of {MODES}, got {mode!r}")
    return str(mode)


# ------------------------------------------------------------------ paths / files
def _is_link_or_junction(path: Path) -> bool:
    """True for symlinks AND Windows junctions/other reparse points (no privilege needed)."""
    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & reparse)


@dataclass(frozen=True)
class BridgePaths:
    """Everything is checked against ``base`` (the ``claude-bridge`` root), never a sub-folder.

    Every path handed out is lexically under ``base``, contains no symlink/junction/reparse
    component (the root included) and resolves strictly inside the resolved root.
    """

    base: Path  # <shared>/claude-bridge

    @classmethod
    def from_shared(cls, shared: str | os.PathLike[str]) -> "BridgePaths":
        return cls(Path(shared) / BRIDGE_DIRNAME)

    def check(self, path: Path) -> Path:
        base = self.base
        try:
            relative = path.relative_to(base)
        except ValueError:
            raise RefusedRequest(f"path is not under the bridge root {base}: {path}") from None
        if ".." in relative.parts:
            raise RefusedRequest(f"path escapes the bridge root: {path}")
        probe = base
        for part in ("", *relative.parts):
            probe = probe / part if part else base
            if _is_link_or_junction(probe):
                raise RefusedRequest(f"refusing link/junction/reparse point in the bridge tree: {probe}")
        try:
            root_resolved = base.resolve(strict=base.exists())
            resolved = path.resolve(strict=False)
        except OSError as error:
            raise RefusedRequest(f"bridge path cannot be resolved: {path}: {error}") from error
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise RefusedRequest(f"path escapes the bridge root {root_resolved}: {resolved}")
        return path

    def _folder(self, name: str) -> Path:
        return self.check(self.base / name)

    @property
    def cache(self) -> Path:
        return self._folder("cache")

    @property
    def inbox(self) -> Path:
        return self._folder("inbox")

    @property
    def outbox(self) -> Path:
        return self._folder("outbox")

    @property
    def images(self) -> Path:
        return self._folder("images")

    @property
    def heartbeat(self) -> Path:
        return self.check(self.base / "heartbeat.json")

    def ensure(self) -> None:
        self.check(self.base)
        for name in ("cache", "inbox", "outbox", "images"):
            folder = self._folder(name)  # re-checked before every mkdir
            folder.mkdir(parents=True, exist_ok=True)
            self.check(folder)  # and after, in case the name was swapped meanwhile

    def entry(self, folder: Path, request_id: str) -> Path:
        if not is_request_id(request_id):
            raise RefusedRequest("request_id must be 64 lowercase hex characters")
        return self.check(self.check(folder) / f"{request_id}.json")

    def image(self, sha: str) -> Path:
        if not is_request_id(sha):
            raise RefusedRequest("image sha256 must be 64 lowercase hex characters")
        return self.check(self.images / f"{sha}.png")


def default_shared_dir(
    env: Mapping[str, str], package_dir: Path | None = None
) -> Path:
    """Env override, else ``<ComfyUI root>/user`` derived from ``custom_nodes/<pack>``."""
    override = (env.get(ENV_SHARED) or "").strip()
    if override:
        return Path(override)
    if package_dir is None:
        raise BridgeError(f"{ENV_SHARED} is not set and no package folder is known")
    return package_dir.resolve().parent.parent / "user"


def _payload(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _write_synced(target: Path, payload: bytes, exclusive: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    flags |= getattr(os, "O_BINARY", 0)
    descriptor = os.open(target, flags, 0o644)
    try:
        view = memoryview(payload)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _temp_name(path: Path) -> Path:
    return path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")


def atomic_write_json(path: Path, value: object) -> None:
    """Write a temp file, fsync, then rename; readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temp_name(path)
    try:
        _write_synced(temporary, _payload(value), exclusive=True)
        _replace_with_retry(temporary, path)
    finally:
        _unlink_quietly(temporary)


def _replace_with_retry(source: Path, target: Path) -> None:
    """``os.replace`` that survives a reader briefly holding ``target`` open on Windows."""
    for attempt in range(REPLACE_RETRIES):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 == REPLACE_RETRIES:
                raise
            time.sleep(READ_RETRY_DELAY_S)


def atomic_create_json(path: Path, value: object) -> bool:
    """Create ``path`` only if absent; False when it already exists.

    Normal case: fsync'd temp file then ``os.link`` (atomic, fails if ``path`` exists). On a
    filesystem without hard links the fallback is an exclusive (O_EXCL) create of the final path,
    which is still race-free; its content becomes visible during the write, so readers retry a few
    times on unreadable JSON (see ``read_json_object``). It never overwrites.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _payload(value)
    temporary = _temp_name(path)
    try:
        _write_synced(temporary, payload, exclusive=True)
        try:
            os.link(temporary, path)
            return True
        except FileExistsError:
            return False
        except OSError:
            pass  # no hard links here
        try:
            _write_synced(path, payload, exclusive=True)
            return True
        except FileExistsError:
            return False  # somebody else owns it; never touch it
        except BaseException:
            _unlink_quietly(path)  # we created it, so a partial file must not stay behind
            raise
    finally:
        _unlink_quietly(temporary)


def read_json_object(path: Path, label: str) -> dict[str, Any]:
    value: Any = None
    for attempt in range(READ_RETRIES):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            break
        except FileNotFoundError as error:
            raise BridgeError(f"{label} does not exist: {path}") from error
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            if attempt + 1 == READ_RETRIES:
                raise BridgeError(f"{label} is not readable JSON: {path}: {error}") from error
            time.sleep(READ_RETRY_DELAY_S)  # a non-hardlink writer may still be mid-write
    if not isinstance(value, dict):
        raise BridgeError(f"{label} is not a JSON object: {path}")
    return value


# ------------------------------------------------------------------ cache
def cache_get(paths: BridgePaths, key: str) -> dict[str, Any] | None:
    path = paths.entry(paths.cache, key)
    if not path.is_file():
        return None
    entry = read_json_object(path, "cache entry")
    answer = entry.get("answer")
    receipt = entry.get("receipt")
    if (
        entry.get("schema") != CACHE_SCHEMA
        or entry.get("key") != key
        or not isinstance(answer, str)
        or not isinstance(receipt, dict)
    ):
        raise BridgeError(f"cache entry is malformed (refusing to guess): {path}")
    if receipt.get("response_sha256_of_answer") != sha256_hex(answer.encode("utf-8")):
        raise BridgeError(f"cache entry answer does not match its receipt hash: {path}")
    return entry


def cache_put(
    paths: BridgePaths, key: str, answer: str, receipt: dict[str, Any]
) -> dict[str, Any]:
    """Store once. A concurrent/earlier entry wins so replay stays deterministic."""
    entry = {
        "schema": CACHE_SCHEMA,
        "key": key,
        "answer": answer,
        "receipt": receipt,
    }
    path = paths.entry(paths.cache, key)
    if not atomic_create_json(path, entry):
        existing = cache_get(paths, key)
        if existing is not None:
            return existing
    return entry


# ------------------------------------------------------------------ images
def save_images(paths: BridgePaths, images: Sequence[ImageBlob]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for blob in images:
        target = paths.image(blob.sha256)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = _temp_name(target)
            try:
                _write_synced(temporary, blob.png, exclusive=True)
                _replace_with_retry(temporary, target)
            finally:
                _unlink_quietly(temporary)
        refs.append({"sha256": blob.sha256, "path": f"images/{blob.sha256}.png"})
    return refs


# ------------------------------------------------------------------ heartbeat
def write_heartbeat(paths: BridgePaths, tool: str, now: float | None = None) -> None:
    moment = time.time() if now is None else now
    atomic_write_json(
        paths.heartbeat,
        {
            "schema": HEARTBEAT_SCHEMA,
            "time_unix": moment,
            "time_iso": datetime.fromtimestamp(moment, timezone.utc).isoformat(),
            "pid": os.getpid(),
            "tool": tool,
        },
    )


def heartbeat_age(paths: BridgePaths, now: float | None = None) -> float | None:
    """Seconds since the last MCP call, or None when absent/unreadable/clock-skewed."""
    heartbeat = paths.heartbeat
    stamp: float | None = None
    for attempt in range(HEARTBEAT_READ_RETRIES):
        if not heartbeat.is_file():
            return None
        try:
            beat = json.loads(heartbeat.read_text(encoding="utf-8-sig"))
            stamp = float(beat["time_unix"])
            break
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            # A lost read (writer swapping the file, Windows sharing violation) must not
            # flip a live chat to "dead": retry briefly before giving up.
            if attempt + 1 < HEARTBEAT_READ_RETRIES:
                time.sleep(READ_RETRY_DELAY_S / 2)
    if stamp is None:
        return None
    age = (time.time() if now is None else now) - stamp
    if age < -HEARTBEAT_MAX_FUTURE_SKEW_S:
        return None  # a stamp from the future cannot prove a live chat
    return max(age, 0.0)


def chat_is_live(paths: BridgePaths, now: float | None = None) -> bool:
    age = heartbeat_age(paths, now)
    return age is not None and age < HEARTBEAT_MAX_AGE_S


# ------------------------------------------------------------------ route: chat
def write_request(
    paths: BridgePaths,
    key: str,
    system: str,
    prompt: str,
    image_refs: Sequence[Mapping[str, str]],
    timeout_s: int,
) -> dict[str, Any]:
    """Idempotent: an existing inbox file (same key = same request) is kept as-is."""
    path = paths.entry(paths.inbox, key)
    request = {
        "schema": REQUEST_SCHEMA,
        "request_id": key,
        "created_at": now_iso(),
        "created_unix": time.time(),
        "system": system,
        "prompt": prompt,
        "images": [dict(ref) for ref in image_refs],
        "timeout_s": timeout_s,
    }
    if not atomic_create_json(path, request):
        return read_json_object(path, "pending request")
    return request


def read_answer(paths: BridgePaths, key: str) -> dict[str, Any] | None:
    path = paths.entry(paths.outbox, key)
    if not path.is_file():
        return None
    answer = read_json_object(path, "outbox answer")
    if (
        answer.get("schema") != ANSWER_SCHEMA
        or answer.get("request_id") != key
        or not isinstance(answer.get("answer"), str)
    ):
        raise BridgeError(f"outbox answer is malformed or addressed elsewhere: {path}")
    return answer


def wait_for_answer(
    paths: BridgePaths,
    key: str,
    timeout_s: float,
    poll_s: float = 1.0,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    on_poll: Callable[[], None] | None = None,
) -> dict[str, Any]:
    deadline = clock() + timeout_s
    while True:
        answer = read_answer(paths, key)
        if answer is not None:
            return answer
        if clock() >= deadline:
            raise ChatTimeout(
                f"no answer for request {key} within {timeout_s:g}s. It is still pending in "
                f"{paths.inbox}; answer it with the MCP tool bridge_answer and re-run, "
                "or use another mode."
            )
        if on_poll is not None:
            on_poll()
        sleep(poll_s)


def list_pending(paths: BridgePaths) -> list[dict[str, Any]]:
    """Inbox requests that have no outbox answer yet, oldest first. Read-only."""
    pending: list[dict[str, Any]] = []
    inbox = paths.inbox
    if not inbox.is_dir():
        return pending
    for item in sorted(inbox.glob("*.json")):
        request_id = item.stem
        if not is_request_id(request_id):
            continue
        try:
            request_path = paths.entry(paths.inbox, request_id)
            if paths.entry(paths.outbox, request_id).exists():
                continue
            request = read_json_object(request_path, "pending request")
            created = request.get("created_unix", 0)
            if isinstance(created, bool) or not isinstance(created, (int, float)):
                raise BridgeError(f"pending request has a non-numeric created_unix: {request_path}")
        except BridgeError as error:
            pending.append({"request_id": request_id, "error": str(error), "created_unix": 0})
            continue
        pending.append(request)
    pending.sort(key=lambda r: (float(r.get("created_unix") or 0), str(r.get("request_id") or "")))
    return pending


def read_pending(paths: BridgePaths, request_id: str) -> dict[str, Any]:
    path = paths.entry(paths.inbox, request_id)
    if not path.is_file():
        raise RefusedRequest(f"unknown request_id (not in the inbox): {request_id}")
    request = read_json_object(path, "pending request")
    request["answered"] = paths.entry(paths.outbox, request_id).exists()
    return request


def post_answer(
    paths: BridgePaths,
    request_id: str,
    answer: object,
    model_reported: str | None = None,
) -> dict[str, Any]:
    """Atomically publish one answer. Refuses unknown ids and never overwrites."""
    if not is_request_id(request_id):
        raise RefusedRequest("request_id must be 64 lowercase hex characters")
    if not isinstance(answer, str) or not answer.strip():
        raise RefusedRequest("answer must be a non-empty string")
    if len(answer.encode("utf-8")) > MAX_ANSWER_BYTES:
        raise RefusedRequest(f"answer exceeds {MAX_ANSWER_BYTES} bytes")
    inbox_path = paths.entry(paths.inbox, request_id)
    if not inbox_path.is_file():
        raise RefusedRequest(f"unknown request_id (not in the inbox): {request_id}")
    outbox_path = paths.entry(paths.outbox, request_id)
    if outbox_path.exists():
        raise RefusedRequest(f"request {request_id} is already answered; refusing to overwrite")
    request_bytes = inbox_path.read_bytes()
    record = {
        "schema": ANSWER_SCHEMA,
        "request_id": request_id,
        "answer": answer,
        "model_reported": (model_reported or "unreported")[:200],
        "answered_at": now_iso(),
        "answered_unix": time.time(),
        "answer_sha256": sha256_hex(answer.encode("utf-8")),
        "request_file_sha256": sha256_hex(request_bytes),
    }
    if not atomic_create_json(outbox_path, record):
        raise RefusedRequest(f"request {request_id} is already answered; refusing to overwrite")
    return record


# ------------------------------------------------------------------ route: router
@dataclass(frozen=True)
class RouterConfig:
    base_url: str
    model: str
    token: str = field(repr=False)  # never shown in repr/logs
    api: str = "chat"

    @property
    def host(self) -> str:
        return urllib.parse.urlsplit(self.base_url).netloc

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        leaf = "chat/completions" if self.api == "chat" else "responses"
        if base.endswith("/v1"):
            return f"{base}/{leaf}"
        return f"{base}/v1/{leaf}"


def router_config(env: Mapping[str, str]) -> RouterConfig | None:
    """None when no router variable is set; BridgeError when only some are."""
    values = {name: (env.get(name) or "").strip() for name in (ENV_BASE_URL, ENV_MODEL, ENV_TOKEN)}
    if not any(values.values()):
        return None
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RouterError(f"router is half-configured; missing {', '.join(missing)}")
    api = (env.get(ENV_API) or "chat").strip().lower()
    if api not in ROUTER_APIS:
        raise RouterError(f"{ENV_API} must be one of {ROUTER_APIS}, got {api!r}")
    parsed = urllib.parse.urlsplit(values[ENV_BASE_URL])
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise RouterError(f"{ENV_BASE_URL} must be an http(s) URL with a host")
    if parsed.username is not None or parsed.password is not None:
        raise RouterError(f"{ENV_BASE_URL} must not contain credentials")
    if parsed.query or parsed.fragment:
        raise RouterError(f"{ENV_BASE_URL} must not contain a query or fragment")
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() == "http" and host not in PLAIN_HTTP_HOSTS:
        raise RouterError(
            f"{ENV_BASE_URL}: plain http is only allowed for {sorted(PLAIN_HTTP_HOSTS)}; "
            "use https for any other host (the token travels in the request)"
        )
    return RouterConfig(values[ENV_BASE_URL], values[ENV_MODEL], values[ENV_TOKEN], api)


def _data_uri(blob: ImageBlob) -> str:
    return "data:image/png;base64," + base64.b64encode(blob.png).decode("ascii")


def build_router_body(
    config: RouterConfig, system: str, prompt: str, images: Sequence[ImageBlob]
) -> dict[str, Any]:
    if config.api == "chat":
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if images:
            content: Any = [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": _data_uri(blob)}}
                for blob in images
            ]
        else:
            content = prompt
        messages.append({"role": "user", "content": content})
        return {"model": config.model, "messages": messages, "stream": False}
    parts: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}] + [
        {"type": "input_image", "image_url": _data_uri(blob)} for blob in images
    ]
    body: dict[str, Any] = {
        "model": config.model,
        "input": [{"role": "user", "content": parts}],
        "stream": False,
    }
    if system:
        body["instructions"] = system
    return body


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def parse_router_answer(api: str, payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    if api == "chat":
        choices = payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                return _text_of(message.get("content"))
        return ""
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    output = payload.get("output")
    texts: list[str] = []
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict) and item.get("type") == "message":
                texts.append(_text_of(item.get("content")))
    return "".join(texts)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would re-send the Authorization header elsewhere: treat it as an error."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        return None


def _default_open(request: urllib.request.Request, timeout: float) -> Any:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    return opener.open(request, timeout=timeout)


def _open_within(
    send: Callable[..., Any], request: urllib.request.Request, timeout_s: float
) -> bytes:
    """Run the request in a daemon thread and give up at a TOTAL deadline.

    The socket timeout only bounds each blocking read, so a gateway that trickles bytes could
    hold the node far beyond ``timeout_s``; this bounds the whole call (headers + body).
    """
    outcome: dict[str, Any] = {}

    def work() -> None:
        try:
            with send(request, timeout=timeout_s) as response:
                outcome["raw"] = response.read(MAX_RESPONSE_BYTES + 1)
        except BaseException as error:  # re-raised in the caller
            outcome["error"] = error

    worker = threading.Thread(target=work, name="jj-bridge-router", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise TimeoutError(f"no complete response within {timeout_s:g}s (total deadline)")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["raw"]


def call_router(
    config: RouterConfig,
    system: str,
    prompt: str,
    images: Sequence[ImageBlob],
    timeout_s: float,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """One OpenAI-compatible call. The token only travels in the Authorization header."""
    body = json.dumps(
        build_router_body(config, system, prompt, images), ensure_ascii=False
    ).encode("utf-8")
    request = urllib.request.Request(
        config.endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {config.token}",
        },
    )
    send = opener or _default_open
    try:
        raw = _open_within(send, request, timeout_s)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RouterError(
                f"gateway {config.host} response exceeds {MAX_RESPONSE_BYTES} bytes; refusing it"
            )
    except urllib.error.HTTPError as error:
        try:
            detail = error.read(MAX_ERROR_BODY_CHARS * 4).decode("utf-8", "replace")
        except Exception:
            detail = ""
        message = redact(detail, config.token)[:MAX_ERROR_BODY_CHARS]
        raise RouterError(
            f"gateway {config.host} answered HTTP {error.code} for {config.api}: {message}"
        ) from None
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        reason = redact(str(getattr(error, "reason", error)), config.token)
        raise RouterError(f"gateway {config.host} unreachable: {reason}") from None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RouterError(f"gateway {config.host} returned non-JSON: {error}") from None
    answer = parse_router_answer(config.api, payload)
    if not answer.strip():
        raise RouterError(f"gateway {config.host} returned no answer text")
    model = payload.get("model") if isinstance(payload, dict) else None
    return {
        "answer": answer,
        "model_reported": model if isinstance(model, str) and model else "unreported",
        "request_sha256": sha256_hex(body),
        "response_sha256": sha256_hex(raw),
    }


# ------------------------------------------------------------------ resolve
@dataclass(frozen=True)
class Resolution:
    answer: str
    receipt: dict[str, Any]
    cache_hit: bool
    key: str

    @property
    def receipt_text(self) -> str:
        return json.dumps(self.receipt, indent=2, ensure_ascii=False, sort_keys=True)


def _receipt(
    key: str,
    route: str,
    mode: str,
    answer: str,
    model_reported: str,
    requested_at: str,
    answered_at: str,
    request_sha256: str,
    response_sha256: str,
    image_hashes: Sequence[str],
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "key": key,
        "route": route,
        "mode_requested": mode,
        "model_reported": model_reported,
        "requested_at": requested_at,
        "answered_at": answered_at,
        "request_sha256": request_sha256,
        "response_sha256": response_sha256,
        "response_sha256_of_answer": sha256_hex(answer.encode("utf-8")),
        "image_sha256": list(image_hashes),
    }
    receipt.update(extra)
    return receipt


def resolve(
    paths: BridgePaths,
    *,
    system: str,
    prompt: str,
    images: Sequence[ImageBlob] = (),
    mode: str = "auto",
    timeout_s: object = DEFAULT_TIMEOUT_S,
    env: Mapping[str, str] | None = None,
    now: float | None = None,
    poll_s: float = 1.0,
    on_poll: Callable[[], None] | None = None,
    opener: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Resolution:
    """cache -> chat (live heartbeat) -> router (configured) -> loud error."""
    mode = validate_mode(mode)
    if not isinstance(system, str) or not isinstance(prompt, str):
        raise BridgeError("system and prompt must be strings")
    if not prompt.strip():
        raise BridgeError("prompt must not be empty")
    environment = os.environ if env is None else env
    timeout = clamp_timeout(timeout_s)
    hashes = [blob.sha256 for blob in images]
    key = cache_key(system, prompt, hashes)

    hit = cache_get(paths, key)
    if hit is not None:
        return Resolution(hit["answer"], hit["receipt"], True, key)
    if mode == "cache_only":
        raise CacheMiss(
            f"cache_only: no stored answer for key {key}; run once with mode chat, router or auto"
        )

    route = mode
    if mode == "auto":
        if chat_is_live(paths, now):
            route = "chat"
        elif router_config(environment) is not None:
            route = "router"
        else:
            age = heartbeat_age(paths, now)
            seen = "no heartbeat" if age is None else f"last heartbeat {age:.0f}s ago"
            raise NoRouteAvailable(
                f"auto: no cached answer, no live chat ({seen}, needs < "
                f"{HEARTBEAT_MAX_AGE_S:.0f}s) and no router configured ({ENV_BASE_URL}, "
                f"{ENV_MODEL}, {ENV_TOKEN}). Nothing was sent anywhere; no cloud fallback exists."
            )

    requested_at = now_iso()
    if route == "chat":
        paths.ensure()
        refs = save_images(paths, images)
        write_request(paths, key, system, prompt, refs, timeout)
        reply = wait_for_answer(
            paths, key, timeout, poll_s, sleep=sleep, on_poll=on_poll
        )
        answer = reply["answer"]
        receipt = _receipt(
            key, "chat", mode, answer,
            str(reply.get("model_reported") or "unreported"),
            requested_at, str(reply.get("answered_at") or now_iso()),
            key, str(reply.get("answer_sha256") or sha256_hex(answer.encode("utf-8"))),
            hashes, {"request_id": key},
        )
    else:
        config = router_config(environment)
        if config is None:
            raise RouterError(
                f"mode router needs {ENV_BASE_URL}, {ENV_MODEL} and {ENV_TOKEN} in the environment"
            )
        paths.ensure()
        save_images(paths, images)
        outcome = call_router(config, system, prompt, images, timeout, opener)
        answer = outcome["answer"]
        receipt = _receipt(
            key, "router", mode, answer, outcome["model_reported"],
            requested_at, now_iso(), outcome["request_sha256"], outcome["response_sha256"],
            hashes,
            {
                "gateway_host": config.host,
                "gateway_api": config.api,
                "requested_model": config.model,
            },
        )
    stored = cache_put(paths, key, answer, receipt)
    return Resolution(stored["answer"], stored["receipt"], False, key)
