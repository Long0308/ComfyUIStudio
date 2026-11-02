"""``POST /v1/images/codex``: validate, write the prompt through the engine's own prompt router, confirm it, run lanes.

The provenance path is exactly ``jjv images prompt new`` + ``prompt confirm`` (``images/prompt_route.py``): a one-item
batch + ``queue-p-<id>.json`` row, flipped to ``dispatch_allowed:true`` write-once with ``by=comfyui-run:<client_id>``
(the ComfyUI Run click IS the user's confirmation).  The images are made by ``codex.submit_library_batch`` (the same
code as ``images submit --provider codex-exec --library-out``), so the queue gate and receipts are the engine's.
"""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from typing import Any

from ..core.errors import EngineError, Refused
from ..core.io import sha256_bytes, sha256_file, write_once
from ..images import codex_queue, library, pool, prompt_route
from ..layout.context import Context, load_context
from . import lanes, wardrobe
from .config import BridgeConfig
from .jobs import JobStore

DEFAULT_KIND = "SHOT"
MAX_REFS = 12  # same as the library path's wardrobe set (12 refs per receipt)
MAX_PROMPT_CHARS = 8000  # per prompt of a `prompts` list (no limit existed for one prompt; a guess, see report)
MAX_REF_BYTES = 20 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ROUTE_NOTE = "codex-exec: cloud GPT image tool through Codex OAuth lanes (not local GPU inference)"


def _clean(value: Any, default: str, limit: int = 80) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]", "_", str(value or default).strip())[:limit]
    return text or default


def _ref(index: int, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise Refused(f"refs[{index}] must be an object {{role, png_base64 | path}}")
    role = _clean(raw.get("role"), "reference", 40).replace(":", "_")
    has_path, has_png = isinstance(raw.get("path"), str), isinstance(raw.get("png_base64"), str)
    if has_path == has_png:
        raise Refused(f"refs[{index}] needs exactly one of 'path' (absolute image under an allowed root) or 'png_base64'")
    if has_path:
        return {"role": role, "path": raw["path"]}
    if len(raw["png_base64"]) > MAX_REF_BYTES * 4 // 3 + 8:
        raise Refused(f"refs[{index}] is larger than {MAX_REF_BYTES} bytes")
    try:
        data = base64.b64decode(raw["png_base64"], validate=True)
    except (binascii.Error, ValueError) as error:
        raise Refused(f"refs[{index}].png_base64 is not valid base64") from error
    if not data.startswith(PNG_MAGIC):
        raise Refused(f"refs[{index}].png_base64 is not a PNG")
    return {"role": role, "png": data}


def _prompts(raw: Any, text: Any) -> list[str] | None:
    """``prompts``: 1..MAX_N non-empty strings (<= MAX_PROMPT_CHARS), order kept; None when the key is absent."""
    if raw is None:
        return None
    if text is not None:
        raise Refused("send either prompts (1..10 prompts, one image each) or prompt_text + n, not both")
    if not isinstance(raw, list) or not 1 <= len(raw) <= codex_queue.MAX_N:
        raise Refused(f"prompts must be a list of 1..{codex_queue.MAX_N} strings; {codex_queue.MAX_N_WHY}")
    for position, item in enumerate(raw, 1):
        if not isinstance(item, str) or not item.strip():
            raise Refused(f"prompts[{position}] must be a non-empty string")
        if len(item) > MAX_PROMPT_CHARS:
            raise Refused(f"prompts[{position}] is {len(item)} characters; at most {MAX_PROMPT_CHARS}")
    return list(raw)


def validate_request(body: Any) -> dict[str, Any]:
    """Every field checked before any job folder exists (Refused -> HTTP 400, nothing written)."""
    if not isinstance(body, dict):
        raise Refused("request body must be a JSON object")
    episode, text = body.get("episode"), body.get("prompt_text")
    if not isinstance(episode, str) or not episode.strip():
        raise Refused("episode is required (episode.json path, episode root or slug)")
    prompts = _prompts(body.get("prompts"), text)
    if prompts is None:
        if not isinstance(text, str) or not text.strip():
            raise Refused("prompt_text is empty")
        n = body.get("n", codex_queue.MAX_N)
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= codex_queue.MAX_N:
            raise Refused(f"n must be an integer 1..{codex_queue.MAX_N} (got {n!r}); {codex_queue.MAX_N_WHY}")
    else:
        text, n = None, len(prompts)  # one take per prompt; `n` is ignored
    kind = body.get("kind") or DEFAULT_KIND
    if kind not in prompt_route.KINDS:
        raise Refused(f"kind must be one of {prompt_route.KINDS} (got {kind!r})")
    prompt_id = body.get("prompt_id")
    if prompt_id is not None:
        library.check_prompt_id(prompt_id)
    refs = body.get("refs") or []
    if not isinstance(refs, list) or len(refs) > MAX_REFS:
        raise Refused(f"refs must be a list of at most {MAX_REFS} items")
    context = body.get("context")
    if context is not None and (not isinstance(context, str) or not context.strip()):
        raise Refused("context must be a non-empty string (a wardrobe context name)")
    extra = body.get("wardrobe_refs") or []
    if not isinstance(extra, list) or len(extra) > MAX_REFS:
        raise Refused(f"wardrobe_refs must be a list of at most {MAX_REFS} items")
    scene = body.get("scene_ref")
    return {"episode": episode.strip(), "prompt_text": text, "prompts": prompts, "n": n, "kind": kind, "prompt_id": prompt_id,
            "client_id": _clean(body.get("client_id"), "api"), "refs": [_ref(i, r) for i, r in enumerate(refs)],
            "context": context.strip() if context else None,
            "wardrobe_refs": [_ref(i, {**r, "role": "company_wardrobe"} if isinstance(r, dict) else r) for i, r in enumerate(extra)],
            "scene_ref": None if scene is None else _ref(0, {**scene, "role": "scene_location"} if isinstance(scene, dict) else scene)}


def attach_refs(cfg: BridgeConfig, ctx: Context, req: dict[str, Any]) -> dict[str, Any]:
    """The refs every take carries: explicit ``refs`` REPLACE the domain preset; otherwise the domain's wardrobe preset
    (``context`` or its default) is resolved and verified (a missing file / sha mismatch refuses the job); the user's
    ``wardrobe_refs`` and the optional ``scene_ref`` are added.  Returns the request with the final ``refs`` + ``ref_set``."""
    if req["refs"] and req["context"]:
        raise Refused("send either refs (an explicit override of the wardrobe preset) or context, not both")
    if req["refs"]:
        context, preset, source = None, [], "override"
    else:
        context, preset = wardrobe.resolve(cfg.wardrobe, ctx.domain_id, req["context"])
        source = "preset" if preset else "none"
    added = [*req["wardrobe_refs"], *([req["scene_ref"]] if req["scene_ref"] else [])]
    refs = [*req["refs"], *[{"role": p["role"], "path": p["path"]} for p in preset], *added]
    if len(refs) > MAX_REFS:
        raise Refused(f"{len(refs)} references attached; at most {MAX_REFS}")
    rows = [_describe(r, p) for r, p in zip(refs, [None] * len(req["refs"]) + preset + [None] * len(added))]
    return {**req, "refs": refs, "ref_set": {"source": source, "context": context, "refs": rows}}


def _describe(ref: dict[str, Any], preset: dict[str, str] | None) -> dict[str, str]:
    if preset is not None:
        return {"name": preset["name"], "role": ref["role"], "sha256": preset["sha256"], "origin": preset["origin"]}
    if "png" in ref:
        return {"name": f"{ref['role']}.png", "role": ref["role"], "sha256": sha256_bytes(ref["png"]), "origin": "request:png"}
    if not Path(ref["path"]).is_file():
        raise Refused(f"reference file not found: {ref['path']}")
    return {"name": Path(ref["path"]).name, "role": ref["role"], "sha256": sha256_file(Path(ref["path"])),
            "origin": "request:path"}


def allowed_accounts(cfg: BridgeConfig, ctx: Context) -> list[pool.Account]:
    """The allow-listed labels, each of which must be a machine codex account label (never all accounts)."""
    configured = {a.label: a for a in pool.accounts_from(ctx.machine, None)}
    missing = [label for label in cfg.accounts if label not in configured]
    if missing:
        raise Refused(f"bridge allow-list labels {missing} are not machine codex account labels {sorted(configured)}")
    return [configured[label] for label in cfg.accounts]


def _save_refs(folder: Path, refs: list[dict[str, Any]]) -> list[str]:
    pairs = []
    for index, ref in enumerate(refs, 1):
        if "png" in ref:
            target = folder / "refs" / f"ref_{index:02d}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            write_once(target, ref["png"])
            pairs.append(f"{ref['role']}={target.resolve().as_posix()}")
        else:
            pairs.append(f"{ref['role']}={ref['path']}")
    return pairs


def start(cfg: BridgeConfig, store: JobStore, body: Any) -> dict[str, Any]:
    req = validate_request(body)
    req = attach_refs(cfg, load_context(req["episode"], cfg.machine_path), req)
    texts = req["prompts"] or [req["prompt_text"]] * req["n"]
    items = [{"index": i, "prompt_sha256": sha256_bytes(t.strip().encode("utf-8")), "lane": None, "status": "pending",
              "output_sha256": None, "receipt": None, "refs": req["ref_set"]["refs"]} for i, t in enumerate(texts, 1)]
    job_id = store.new("cx", {"kind": "codex-images", "state": "queued", "route": ROUTE_NOTE, "n": req["n"],
                              "mode": "prompts" if req["prompts"] else "prompt+n",
                              "episode": req["episode"], "prompt_kind": req["kind"], "client_id": req["client_id"],
                              "prompt_sha256": None if req["prompts"] else items[0]["prompt_sha256"],
                              "refs": [r["role"] for r in req["refs"]], "ref_set": req["ref_set"], "items": items, "images": [], "errors": []})
    store.spawn(job_id, lambda: run_job(cfg, store, job_id, req))
    return {"job_id": job_id, "state": "queued", "n": req["n"], "route": ROUTE_NOTE}


def _fail(store: JobStore, job_id: str, error: BaseException) -> None:
    text = str(error) if isinstance(error, EngineError) else f"{type(error).__name__}: {error}"

    def mutate(doc: dict[str, Any]) -> None:
        doc.setdefault("errors", []).append({"stage": "setup", "error": text[:800]})
        doc["state"] = "partial" if doc.get("images") else "failed"

    store.update(job_id, mutate)


def run_job(cfg: BridgeConfig, store: JobStore, job_id: str, req: dict[str, Any]) -> None:
    """Synchronous body of one image job (the HTTP handler runs it on a background thread)."""
    try:
        store.update(job_id, lambda doc: doc.update(state="running"))
        ctx = load_context(req["episode"], cfg.machine_path)
        accounts = allowed_accounts(cfg, ctx)
        folder = store.folder(job_id)
        base_id = req["prompt_id"] or f"BR_{job_id.replace('-', '_')}"
        pairs = _save_refs(folder, req["refs"])
        by = f"comfyui-run:{req['client_id']}"
        many, tasks, rows = bool(req["prompts"]), [], []
        for index, text in enumerate(req["prompts"] or [req["prompt_text"]], 1):
            prompt_id = f"{base_id}_p{index:02d}" if many else base_id
            out = folder / "prompt" / f"p{index:02d}" if many else folder / "prompt"
            made = prompt_route.prompt_new(ctx, out, text=text, prompt_id=prompt_id, kind=req["kind"], aspect=None, refs=pairs,
                                           route="bridge:codex-exec", rev=None, batch_id=None)
            confirmed = prompt_route.prompt_confirm(
                Path(made["queue"]), prompt_id=prompt_id, sha256=made["prompt_sha256"], by=by,
                note=f"bridge job {job_id}: the ComfyUI Run click is the user's confirmation")
            rows.append({"prompt_id": prompt_id, "batch": made["batch"], "queue": made["queue"],
                         "confirmation": confirmed["confirmation"], "prompt_sha256": made["prompt_sha256"]})
            tasks += [{"index": i, "prompt_index": index, "prompt_id": prompt_id, "prompt_sha256": made["prompt_sha256"],
                       "batch": made["batch"]} for i in ([index] if many else range(1, req["n"] + 1))]
        provenance = {**rows[0], "domain": ctx.domain_id, "episode_id": ctx.episode_id,
                      "accounts": [a.label for a in accounts], "prompts": rows}

        def tag(doc: dict[str, Any]) -> None:
            doc["provenance"] = provenance
            for item, task in zip(doc["items"], tasks):
                item["prompt_id"] = task["prompt_id"]

        store.update(job_id, tag)
        lanes.run_lanes(cfg, store, job_id, ctx, accounts, tasks)
    except Exception as error:  # noqa: BLE001 - the job document is the contract: every failure is recorded there
        _fail(store, job_id, error)
