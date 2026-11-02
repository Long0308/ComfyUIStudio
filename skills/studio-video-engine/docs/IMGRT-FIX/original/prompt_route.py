"""``jjv images route list`` and ``jjv images prompt new|confirm`` (IMGRT-1): gõ prompt rồi chọn tuyến.

CPU only: no network, no GPU, no ChatGPT token (only whether ``auth.json`` EXISTS, via ``pool.Account``).
``prompt new`` writes a one-item batch + a queue row with ``dispatch_allowed:false``; ``prompt confirm`` flips it to
``true`` write-once.  The existing gates then consume that row: ``codex_queue._refuse_blocked`` for codex-exec and
(G4) ``local.queue_gate`` for comfyui-local on a ``provenance_required`` domain.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.errors import EXIT_OK, Refused
from ..core.io import read_json, sha256_bytes, sha256_file, write_json_atomic, write_json_once
from ..layout.context import RECIPE_DIR, Context, domain_policy, load_context
from . import codex_queue, library, library_plan, pool

QUEUE_SCHEMA_NOTE = "prompt-new row: awaiting_user_confirm until `prompt confirm`"
CONFIRM_SCHEMA = "jjv/image-prompt-confirmation/v1"
KINDS = ("FACE", "ACTION", "SHOT", "ASSET", "SET", "FIX")
MODEL_DIRS = {"unet": ("diffusion_models", "unet"), "clip": ("text_encoders", "clip"), "vae": ("vae",),
              "lora": ("loras",)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def provenance_required(ctx: Context) -> bool:
    return bool(domain_policy(ctx).get("provenance_required"))


# ---------------------------------------------------------------- route list
def _model_status(models: dict[str, Any], lora_names: list[str], models_dir: str | None) -> dict[str, Any]:
    wanted = {**{k: v for k, v in models.items() if isinstance(v, str)}, **{f"lora:{n}": n for n in lora_names}}
    if not models_dir or not Path(models_dir).is_dir():
        return {"installed": "unknown", "why": "machine.comfy.models_dir not set or not visible (mount point); use ComfyUI /object_info",
                "files": wanted}
    root, result = Path(models_dir), {}
    for key, name in wanted.items():
        subs = MODEL_DIRS["lora" if key.startswith("lora:") else key]
        result[name] = any((root / sub / name).is_file() for sub in subs)
    return {"installed": all(result.values()), "files": result}


def _comfy_routes(models_dir: str | None) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(RECIPE_DIR.glob("*.json")):
        recipe = read_json(path)
        if not isinstance(recipe, dict) or recipe.get("schema") != "jjv/images-local-recipe/v1":
            continue
        rows.append({"id": f"comfy-{recipe['id']}", "provider": "comfyui-local", "recipe": recipe["id"],
                     "model": (recipe.get("models") or {}).get("unet"), "gpu": True,
                     "qualification": (recipe.get("qualification") or {}).get("status"),
                     "needs": "--pilot while unqualified; user approval for the GPU run",
                     **_model_status(recipe.get("models") or {}, list((recipe.get("loras") or {}).values()), models_dir),
                     "selectable": True, "sha256": sha256_file(path)})
    return rows


def _codex_route(ctx: Context, state_path: Path | None) -> dict[str, Any]:
    accounts = pool.accounts_from(ctx.machine, None)
    state = pool.load_state(state_path) if state_path and Path(state_path).is_file() else {"cooling": {}, "last_good": None}
    _, cooling = pool.order(accounts, state, time.time(), configured_labels=pool.cooling_labels(ctx.machine, accounts))
    rows = [{"label": a.label, "auth_present": a.auth_present, "cooling_until": cooling.get(a.label),
             "selectable": a.auth_present and a.label not in cooling} for a in accounts]
    return {"id": "gpt-oauth-lanes", "provider": "codex-exec", "gpu": False, "n_max": codex_queue.MAX_N,
            "lanes_max": library_plan.MAX_PROCS, "accounts": rows,
            "state": str(state_path) if state_path else "not measured (no pool state path)",
            "selectable": any(r["selectable"] for r in rows)}


def route_list(ctx: Context, pool_state: str | None = None) -> dict[str, Any]:
    policy = domain_policy(ctx)
    allowed = policy["allowed_providers"]
    comfy = ctx.machine.get("comfy") or {}
    state = pool_state or (ctx.machine.get("images") or {}).get("codex_state_path")
    routes: list[dict[str, Any]] = []
    if "codex-exec" in allowed:
        routes.append(_codex_route(ctx, Path(state) if state else None))
    if "comfyui-local" in allowed:
        routes.extend(_comfy_routes(comfy.get("models_dir")))
    return {"allowed_providers": allowed, "provenance_required": bool(policy.get("provenance_required")),
            "queue_gate": "real submit needs a queue row with dispatch_allowed true (codex-exec and comfyui-local)"
            if policy.get("provenance_required") else "no queue required (domain is not provenance_required)",
            "preferred_order": policy.get("preferred_order"), "routes": routes,
            "live": "not measured (route list never contacts ComfyUI)"}


# ---------------------------------------------------------------- prompt new
def _parse_refs(ctx: Context, raw: list[str]) -> list[dict[str, str]]:
    allowed, forbidden = codex_queue.batch_roots(ctx, pool.accounts_from(ctx.machine, None))
    refs = []
    for pair in raw:
        role, sep, path = pair.partition("=")
        if not sep or not role or not path:
            raise Refused(f"--ref expects ROLE=ABSOLUTE_PATH, got {pair!r}")
        checked = codex_queue._check_ref_path(path, f"--ref {role}", allowed, forbidden)
        refs.append({"path": path, "role": role, "sha256": sha256_file(checked)})
    return refs


def _canvas_gate(kind: str, aspect: str | None, text: str) -> str | None:
    lock = library_plan.library_canvas().get(kind)
    if lock and aspect and aspect.replace(" ", "") != lock:
        raise Refused(f"kind {kind} is locked to {lock} by the routes recipe (library.canvas); --aspect {aspect} refused")
    wanted = lock or (aspect.replace(" ", "") if aspect else None)
    if wanted:
        problem = library_plan.canvas_problem(text, wanted)
        if problem:
            raise Refused(f"prompt text {problem}: state the frame ratio exactly once")
    return wanted


def prompt_new(ctx: Context, out: Path, *, text: str, prompt_id: str, kind: str, aspect: str | None,
               refs: list[str], route: str | None, rev: str | None, batch_id: str | None) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise Refused("prompt text is empty")
    if kind not in KINDS:
        raise Refused(f"--kind must be one of {KINDS}")
    library.check_prompt_id(prompt_id)
    batch_id = batch_id or prompt_id
    library.check_prompt_id(batch_id)
    if batch_id.startswith("_"):
        raise Refused("batch id may not start with '_' (reserved)")
    out = Path(out)
    batch_path = out / f"{batch_id}.json"
    queue_path = out / f"queue-{rev or ('p-' + prompt_id)}.json"
    for existing in sorted(out.glob("queue-*.json")) if out.is_dir() else []:
        rows = read_json(existing)
        if any(isinstance(r, dict) and r.get("prompt_id") == prompt_id for r in (rows if isinstance(rows, list) else [])):
            raise Refused(f"prompt_id {prompt_id!r} already has a row in {existing.name}: never reused")
    if batch_path.exists() or queue_path.exists():
        raise Refused(f"{batch_path.name} or {queue_path.name} already exists in {out}: nothing was written")
    wanted = _canvas_gate(kind, aspect, text)
    ref_rows = _parse_refs(ctx, refs)
    digest = sha256_bytes(text.encode("utf-8"))
    batch = [{"prompt_id": prompt_id, "prompt_text": text, "prompt_sha256": digest, "ref_images": ref_rows}]
    row = {"prompt_id": prompt_id, "prompt_sha256": digest, "dispatch_allowed": False,
           "status": "awaiting_user_confirm", "dispatch_block_reason": "free-form prompt: run `jjv images prompt confirm`",
           "domain": ctx.domain_id, "kind": kind, "aspect": wanted, "route": route, "batch_file": batch_path.name,
           "text_source": "free-form", "created_utc": _now()}
    write_json_once(batch_path, batch, mode="ascii")
    write_json_once(queue_path, [row], mode="ascii")
    return {"batch": batch_path.as_posix(), "queue": queue_path.as_posix(), "prompt_id": prompt_id,
            "prompt_sha256": digest, "dispatch_allowed": False, "next": f"jjv images prompt confirm --queue {queue_path.as_posix()} "
                                                                       f"--sha256 {digest} --by NAME"}


# ---------------------------------------------------------------- prompt confirm
def prompt_confirm(queue: Path, *, prompt_id: str | None, sha256: str, by: str, note: str | None) -> dict[str, Any]:
    queue = Path(queue)
    rows = read_json(queue)
    if not isinstance(rows, list) or not rows:
        raise Refused(f"{queue.name} must be a non-empty JSON array")
    if prompt_id is None:
        if len(rows) != 1:
            raise Refused("--prompt-id is needed: the queue has several rows")
        prompt_id = rows[0].get("prompt_id")
    hits = [r for r in rows if isinstance(r, dict) and r.get("prompt_id") == prompt_id]
    if len(hits) != 1:
        raise Refused(f"{queue.name}: expected exactly one row for {prompt_id!r}, found {len(hits)}")
    row = hits[0]
    if not by.strip():
        raise Refused("--by is required (who confirms)")
    given = sha256.strip().lower()
    if row.get("prompt_sha256") != given:
        raise Refused(f"--sha256 {given} != the row's prompt_sha256 {row.get('prompt_sha256')}: read the prompt again; nothing written")
    batch = read_json(queue.parent / str(row.get("batch_file")))
    texts = [i for i in batch if isinstance(i, dict) and i.get("prompt_id") == prompt_id]
    if len(texts) != 1 or sha256_bytes(str(texts[0].get("prompt_text")).encode("utf-8")) != given:
        raise Refused("the batch file's prompt_text no longer matches the confirmed sha256 (edited after prompt new): refused")
    record_path = queue.parent / "confirmations" / f"{prompt_id}-{given[:12]}.json"
    if record_path.exists():
        old = read_json(record_path)
        if old.get("by") != by or old.get("note") != note:
            raise Refused(f"{record_path.name} already exists with another by/note: confirmation is write-once")
    elif row.get("dispatch_allowed") is True:
        raise Refused(f"{prompt_id} is already dispatch_allowed:true without a confirmation record: refused (write-once)")
    else:
        write_json_once(record_path, {"schema": CONFIRM_SCHEMA, "prompt_id": prompt_id, "prompt_sha256": given,
                                      "by": by, "note": note, "confirmed_utc": _now(), "queue": queue.name}, mode="ascii")
    reused = row.get("dispatch_allowed") is True
    if not reused:
        row.update({"dispatch_allowed": True, "status": "confirmed", "dispatch_block_reason": None,
                    "confirmed_by": by, "confirmation": record_path.relative_to(queue.parent).as_posix()})
        write_json_atomic(queue, rows, mode="ascii")
    return {"prompt_id": prompt_id, "dispatch_allowed": True, "reused": reused, "confirmation": record_path.as_posix(),
            "queue": queue.as_posix()}


# ---------------------------------------------------------------- comfy queue source (G4)
def comfy_item(ctx: Context, batch: Path, out: Path) -> tuple[dict[str, Any], Path]:
    """Load a one-item --prompt-batch for comfyui-local through the same loader as codex-exec; the row's domain must be ours.
    The prompt text is written (write-once) to ``out/_batch-prompts/<id>.txt`` so the Krea2 path can read it as a file."""
    allowed, forbidden = codex_queue.batch_roots(ctx, [])
    items = codex_queue.load_batch(Path(batch), allowed=allowed, forbidden=forbidden)
    if len(items) != 1:
        raise Refused(f"comfyui-local takes exactly one prompt per submit (--prompt-batch holds {len(items)})")
    item = items[0]
    rows, _ = codex_queue._queue_rows(Path(batch))
    for _, row in rows.get(item["prompt_id"], []):
        if row.get("domain") not in (None, ctx.domain_id):
            raise Refused(f"queue row of {item['prompt_id']} is for domain {row.get('domain')!r}, episode is {ctx.domain_id!r}")
    target = Path(out) / "_batch-prompts" / f"{item['prompt_id']}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text(encoding="utf-8") != item["prompt_text"]:
        raise Refused(f"{target} exists with other text: refused")
    target.write_text(item["prompt_text"], encoding="utf-8")
    return item, target


# ---------------------------------------------------------------- CLI
def register(verbs: Any) -> None:
    route = verbs.add_parser("route", help="which image routes this episode can use (codex lanes, ComfyUI recipes); CPU only")
    rsub = route.add_subparsers(dest="route_verb", required=True)
    rlist = rsub.add_parser("list", help="allowed providers, codex accounts (cooling), ComfyUI recipes; never contacts ComfyUI")
    rlist.add_argument("--episode", required=True)
    rlist.add_argument("--machine", default=None, help=argparse.SUPPRESS)
    rlist.add_argument("--pool-state", default=None)
    rlist.add_argument("--json", action="store_true", help="accepted for symmetry: output is always JSON")
    prompt = verbs.add_parser("prompt", help="free-form prompt -> batch + queue row (dispatch_allowed:false) -> confirm")
    psub = prompt.add_subparsers(dest="prompt_verb", required=True)
    new = psub.add_parser("new", help="write a one-item batch and a queue row that is NOT cleared; sends nothing")
    new.add_argument("--episode", required=True)
    new.add_argument("--machine", default=None, help=argparse.SUPPRESS)
    new.add_argument("--out", required=True, help="folder for <batch>.json and queue-*.json")
    new.add_argument("--text", default=None)
    new.add_argument("--prompt-file", default=None)
    new.add_argument("--prompt-id", default=None, help="folder-safe id (default: PROMPT_<sha12>)")
    new.add_argument("--kind", default="SHOT", choices=KINDS)
    new.add_argument("--aspect", default=None, help="W:H; FACE/ACTION are locked by the routes recipe")
    new.add_argument("--ref", "--refs", action="append", default=[], metavar="ROLE=PATH")
    new.add_argument("--route", default=None, help="route id recorded on the row (informational)")
    new.add_argument("--rev", default=None)
    new.add_argument("--batch-id", default=None)
    conf = psub.add_parser("confirm", help="flip a prompt-new row to dispatch_allowed:true, write-once, by sha256")
    conf.add_argument("--queue", required=True)
    conf.add_argument("--prompt-id", default=None)
    conf.add_argument("--sha256", required=True)
    conf.add_argument("--by", required=True)
    conf.add_argument("--note", default=None)


def run(args: argparse.Namespace) -> int:
    if args.verb == "route":
        ctx = load_context(args.episode, args.machine)
        result = {"episode_id": ctx.episode_id, "domain": ctx.domain_id, **route_list(ctx, args.pool_state)}
    elif args.prompt_verb == "new":
        if (args.text is None) == (args.prompt_file is None):
            raise Refused("give exactly one of --text or --prompt-file")
        text = args.text if args.text is not None else Path(args.prompt_file).read_text(encoding="utf-8")
        ctx = load_context(args.episode, args.machine)
        pid = args.prompt_id or f"PROMPT_{sha256_bytes(text.strip().encode('utf-8'))[:12]}"
        result = {"domain": ctx.domain_id, **prompt_new(ctx, Path(args.out), text=text, prompt_id=pid, kind=args.kind,
                                                        aspect=args.aspect, refs=args.ref, route=args.route, rev=args.rev,
                                                        batch_id=args.batch_id)}
    else:
        result = prompt_confirm(Path(args.queue), prompt_id=args.prompt_id, sha256=args.sha256, by=args.by, note=args.note)
    print(json.dumps({"ok": True, **result}, indent=2))
    return EXIT_OK
