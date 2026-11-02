"""``jjv images submit --provider openrouter``: OpenAI image model through OpenRouter (PAID).

Refuses without ``--spend-ok``, without ``OPENROUTER_API_KEY`` in the environment (the key is never printed,
saved or echoed), when a credit/auth stop sentinel exists, or when the running spend would pass the budget.
The request JSON is saved BEFORE anything is sent (references appear as path + sha256, the full body's sha256 is
``request_sha256``); an intent file is created with O_EXCL right before the POST, so a crash leaves proof that a
request may be in flight and nothing is ever re-sent automatically. HTTP 401/402/403/429 write a stop sentinel.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from ..core.errors import Failed, Refused, Uncertain
from ..core.io import sha256_bytes, write_json_once
from ..layout.context import Context, load_recipe, require_provider
from . import receipts
from .common import compose_prompt, next_take, register, shot_inputs, write_prompt

RECIPE_NAME, RECIPE_SCHEMA = "openrouter-gpt-image-v001", "jjv/images-openrouter-recipe/v1"
KEY_VAR = "OPENROUTER_API_KEY"
STOP_FILE = "openrouter-STOP.json"
Opener = Callable[..., Any]


def check_endpoint(url: str, recipe: dict[str, Any]) -> str:
    """The key may only go to the recipe's hosts over https (or to loopback http, which tests use)."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme == "https" and host in recipe["allowed_endpoint_hosts"]:
        return url
    if parts.scheme == "http" and host in ("127.0.0.1", "localhost"):
        return url
    raise Refused(f"endpoint {url!r} is not allowed: https on {recipe['allowed_endpoint_hosts']} or loopback http only")


def build_request(recipe: dict[str, Any], prompt: str, images: list[dict[str, str]]) -> tuple[dict, dict]:
    """``(payload, redacted)``: the real body (base64 inline) and the saved copy (path + sha256 instead)."""
    refs, shown = [], []
    for ref in images:
        raw = Path(ref["path"]).read_bytes()
        mime = "image/png" if Path(ref["path"]).suffix.lower() == ".png" else "image/jpeg"
        url = "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")
        refs.append({"type": "image_url", "image_url": {"url": url}})
        shown.append({"type": "image_url", "role": ref["role"], "path": ref["path"], "sha256": ref["sha256"], "mime": mime})
    base = {"model": recipe["model"], "prompt": prompt, **recipe["request"]}
    return {**base, "input_references": refs}, {**base, "input_references": shown}


def spent_usd(out: Path) -> float:
    """Sum of ``usage.cost`` in this folder's openrouter receipts (costs the provider reported; unknown counts as 0)."""
    total = 0.0
    for path in Path(out).glob("*/candidates/*.receipt.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("provider") == "openrouter" and isinstance(row.get("usage"), dict):
            cost = row["usage"].get("cost")
            total += float(cost) if isinstance(cost, (int, float)) else 0.0
    return total


def _stop(out: Path, status: int, shot: str, take: str) -> None:
    try:
        write_json_once(Path(out) / STOP_FILE, {"schema": "jjv/openrouter-stop/v1", "http_status": status, "shot": shot,
                        "take": take, "why": "credit/auth/rate stop: top up or fix the key, record it, then remove this "
                        "file by hand"}, mode="ascii", stamp=True)
    except Refused:
        pass  # a sentinel already exists: keep the first one


def submit(ctx: Context, out: Path, shot: str, prompt_file: Path, *, spend_ok: bool, dry_run: bool,
           budget_usd: float | None = None, endpoint: str | None = None, take: str | None = None,
           env: Mapping[str, str] | None = None, opener: Opener = urllib.request.urlopen,
           recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    import os

    env = os.environ if env is None else env
    require_provider(ctx, "openrouter")
    loaded = recipe or load_recipe(RECIPE_NAME, RECIPE_SCHEMA)[0]
    url = check_endpoint(endpoint or loaded["endpoint"], loaded)
    inputs = shot_inputs(out, shot)
    text, source = compose_prompt(prompt_file, inputs["placement_text"])
    take = take or next_take(Path(out) / shot / "openrouter")
    folder = Path(out) / shot / "openrouter" / take
    if folder.exists():
        raise Refused(f"take folder {folder} exists; a take is never reused (pass a new --take)")
    budget = loaded["default_budget_usd"] if budget_usd is None else budget_usd
    spent = spent_usd(out)
    if not dry_run:
        _refusals(out, env, spend_ok, spent, budget, loaded)
    folder.mkdir(parents=True)
    images = [inputs["guide"], *inputs["refs"]]
    payload, redacted = build_request(loaded, text, images)
    body = json.dumps(payload).encode("utf-8")
    request_sha = sha256_bytes(body)
    prompt = {**write_prompt(folder, text), "source": source}
    write_json_once(folder / "request.json", {"endpoint": url, "request": redacted, "request_sha256": request_sha,
                    "request_bytes": len(body), "prompt_sha256": prompt["sha256"]}, mode="ascii")
    summary = {"shot": shot, "take": take, "requested_model": loaded["model"], "request_sha256": request_sha,
               "request": (folder / "request.json").as_posix(), "references": len(images), "spent_usd": round(spent, 4),
               "budget_usd": budget, "key_present": bool(env.get(KEY_VAR)), "estimated_cost_usd_max": loaded["estimated_cost_usd_max"]}
    if dry_run:
        return {**summary, "dry_run": True, "submitted": False}
    result = _post(out, folder, url, body, env[KEY_VAR], loaded, opener, shot, take, request_sha)
    return {**summary, "dry_run": False, "submitted": True, **_register(ctx, out, shot, folder, loaded, inputs, prompt,
                                                                       request_sha, take, result)}


def _refusals(out: Path, env: Mapping[str, str], spend_ok: bool, spent: float, budget: float, recipe: dict) -> None:
    if not spend_ok:
        raise Refused("openrouter spends real money: pass --spend-ok (nothing was sent)")
    if not env.get(KEY_VAR):
        raise Refused(f"{KEY_VAR} is not set in the environment (nothing was sent; the key is never read from a file)")
    stop = Path(out) / STOP_FILE
    if stop.exists():
        raise Refused(f"{stop} exists: an earlier call hit a credit/auth/rate stop. Top up or fix the key, record it, "
                      "remove the file by hand, then retry")
    if spent + recipe["estimated_cost_usd_max"] > budget:
        raise Refused(f"budget: spent {spent:.2f} USD + up to {recipe['estimated_cost_usd_max']} for this image "
                      f"exceeds --budget-usd {budget}")


def _post(out: Path, folder: Path, url: str, body: bytes, key: str, recipe: dict, opener: Opener, shot: str,
          take: str, request_sha: str) -> dict[str, Any]:
    write_json_once(folder / "intent.json", {"schema": "jjv/openrouter-intent/v1", "request_sha256": request_sha,
                    "endpoint": url, "shot": shot, "take": take}, mode="ascii", stamp=True)
    request = urllib.request.Request(url, body, {"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                                 "X-Title": "jjv images"}, method="POST")
    try:
        with opener(request, timeout=recipe["timeout_seconds"]) as response:
            raw, request_id = response.read(), response.headers.get("x-request-id")
    except urllib.error.HTTPError as error:
        status = error.code
        write_json_once(folder / "failure.json", {"http_status": status, "request_sha256": request_sha}, mode="ascii")
        if status in recipe["stop_http_status"]:
            _stop(out, status, shot, take)
        raise Failed(f"OpenRouter answered HTTP {status}; no image was made. "
                     f"{'A stop sentinel was written. ' if status in recipe['stop_http_status'] else ''}Not retried.",
                     evidence={"http_status": status, "folder": str(folder)}) from error
    except Exception as error:  # noqa: BLE001 - after the intent the outcome is unknown
        write_json_once(folder / "unknown.json", {"error": type(error).__name__, "request_sha256": request_sha}, mode="ascii")
        raise Uncertain(f"OpenRouter call outcome unknown ({type(error).__name__}); not retried. Check the provider "
                        "dashboard before another call", evidence={"folder": str(folder)}) from error
    try:
        data = json.loads(raw)
        item = data["data"][0]
        image = base64.b64decode(item["b64_json"], validate=True)
    except (ValueError, KeyError, IndexError, TypeError) as error:
        (folder / "response.raw").write_bytes(raw)
        raise Uncertain("OpenRouter answered but not with one base64 image; raw response kept", evidence={"folder": str(folder)}) from error
    meta = {k: v for k, v in data.items() if k != "data"}
    write_json_once(folder / "response-meta.json", {"meta": meta, "request_id": request_id,
                    "image_bytes": len(image), "image_sha256": sha256_bytes(image)}, mode="ascii")
    (folder / "output.png").write_bytes(image)
    return {"meta": meta, "request_id": request_id}


def _register(ctx: Context, out: Path, shot: str, folder: Path, recipe: dict, inputs: dict, prompt: dict, request_sha: str,
              take: str, result: dict[str, Any]) -> dict[str, Any]:
    info = receipts.png_info(folder / "output.png")
    if min(info["width"], info["height"]) < recipe["min_side_px"]:
        raise Uncertain(f"returned image is {info['width']}x{info['height']}, below the {recipe['min_side_px']} px minimum; "
                        "kept in the take folder, not registered", evidence={"folder": str(folder)})
    meta = result["meta"]
    runtime = meta.get("id") or result["request_id"]
    body = {"route": "openrouter", "provider": "openrouter", "requested_model": recipe["model"],
            "resolved_model": meta.get("model") if isinstance(meta.get("model"), str) else None,
            "runtime_id": runtime if isinstance(runtime, str) else None, "prompt_id": None,
            "prompt": prompt, "prompt_sha256": prompt["sha256"], "request": {"file": "request.json",
            "request_sha256": request_sha, "endpoint_host": "recorded in request.json"},
            "request_sha256": request_sha, "usage": meta.get("usage"), "recipe": recipe["id"],
            "provider_request_id": result["request_id"]}
    receipt = register(ctx, out, shot, folder / "output.png", inputs, body)
    cost = (meta.get("usage") or {}).get("cost") if isinstance(meta.get("usage"), dict) else None
    return {"candidate_sha256": receipt["output"]["sha256"], "receipt": receipt["receipt_path"], "cost_usd": cost,
            "resolved_model": body["resolved_model"], "workflow": receipt.get("review_workflow")}

