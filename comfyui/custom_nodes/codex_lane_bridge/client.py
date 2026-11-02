"""Stdlib client of the host bridge (`jjv bridge serve`): POST a codex image job, poll it, verify the landed PNGs.

No torch/PIL here so it can be tested outside ComfyUI.  The secret is read from a file and sent as a Bearer header;
it is never logged or put in an error message.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://host.docker.internal:8797"
SECRET_FILES = ("/run/codex-bridge/secret", str(Path(__file__).with_name("bridge.secret")))
FINAL = ("done", "partial", "failed", "interrupted")


class BridgeError(RuntimeError):
    pass


def bridge_url() -> str:
    return (os.environ.get("CODEX_BRIDGE_URL") or DEFAULT_URL).rstrip("/")


def read_secret() -> str:
    candidates = [os.environ.get("CODEX_BRIDGE_SECRET_FILE"), *SECRET_FILES]
    for name in [c for c in candidates if c]:
        path = Path(name)
        if path.is_file():
            value = path.read_text(encoding="ascii").strip()
            if value:
                return value
    raise BridgeError("bridge secret file not found (CODEX_BRIDGE_SECRET_FILE, /run/codex-bridge/secret or "
                      "bridge.secret next to this node); start `jjv bridge serve` on the host and mount its state folder")


MAX_PROMPTS = 10
DEFAULT_CONTEXT = "(default)"
MAX_EXTRA_REFS = 4


def ref_set_summary(doc: dict) -> dict:
    """What the bridge attached to the takes (context, source, name + sha256 per ref) for the node's job_info."""
    return doc.get("ref_set") or {"source": "none", "context": None, "refs": []}


def split_prompts(text: str | None) -> list[str] | None:
    """One prompt per non-blank line, order kept. None when the field is empty (prompt+count mode is used)."""
    if text is None or text == "":
        return None
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines:
        raise ValueError("Codex lane: the prompts field holds only blank lines (clear it to use prompt + count)")
    if len(lines) > MAX_PROMPTS:
        raise ValueError(f"Codex lane: {len(lines)} prompts; at most {MAX_PROMPTS} (one image each)")
    return lines


def build_body(prompt: str, count: int, episode: str, kind: str, client_id: str, prompts_text: str | None = None,
               context: str | None = None) -> dict:
    """Request body of ``POST /v1/images/codex``: ``prompts`` (when the field is non-empty) overrides prompt/count.
    ``context`` (a wardrobe context such as cong_truong / van_phong) is sent only when set; empty = the domain default."""
    prompts = split_prompts(prompts_text)
    base = {"episode": episode, "kind": kind, "client_id": client_id}
    if context and context.strip() and context.strip() != DEFAULT_CONTEXT:
        base["context"] = context.strip()
    if prompts is not None:
        return {**base, "prompts": prompts}
    if not str(prompt).strip():
        raise ValueError("Codex lane: prompt is empty")
    return {**base, "prompt_text": prompt, "n": int(count)}


def call(method: str, path: str, secret: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(bridge_url() + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Bearer " + secret)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read()).get("error")
        except ValueError:
            detail = None
        raise BridgeError(f"bridge {method} {path} -> HTTP {error.code}: {detail or error.reason}") from None
    except (urllib.error.URLError, OSError) as error:
        raise BridgeError(f"bridge {bridge_url()} not reachable ({error}); is `jjv bridge serve` running on the host?") from None


def wait_job(job_id: str, secret: str, timeout_seconds: float, poll_seconds: float = 3.0,
             on_poll=None) -> dict:
    """Poll ``GET /v1/jobs/<id>`` until a final state; ``on_poll(doc)`` may raise to abort (ComfyUI cancel)."""
    deadline = time.time() + timeout_seconds
    while True:
        doc = call("GET", f"/v1/jobs/{job_id}", secret)
        if on_poll is not None:
            on_poll(doc)
        if doc.get("state") in FINAL:
            return doc
        if time.time() > deadline:
            raise BridgeError(f"bridge job {job_id} still '{doc.get('state')}' after {timeout_seconds:g} s "
                              f"({len(doc.get('images') or [])} image(s) so far); it keeps running on the host: "
                              f"check GET /v1/jobs/{job_id}")
        time.sleep(poll_seconds)


def landed_paths(doc: dict, input_dir: Path) -> list[Path]:
    """The job's PNGs inside this ComfyUI's input folder, each re-hashed against the bridge's sha256."""
    paths = []
    for image in doc.get("images") or []:
        path = Path(input_dir) / image["input_relpath"]
        if not path.is_file():
            raise BridgeError(f"{image['input_relpath']} is not in the ComfyUI input folder {input_dir}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != image["sha256"]:
            raise BridgeError(f"{image['input_relpath']} hashes {digest[:12]}, bridge says {image['sha256'][:12]}")
        paths.append(path)
    return paths
