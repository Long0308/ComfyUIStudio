"""``jjv images submit --provider comfyui-local``: Krea2 edit from the layout guide on local ComfyUI.

Order (every refusal comes before anything is sent): domain policy -> qualification (``--pilot``) -> input hashes ->
composed prompt -> cast sheet -> graph + LoRA gate + static node policy -> saved API graph -> [dry run stops here]
-> live ComfyUI checks (object_info/no partner nodes, LoRA listed, free VRAM) -> stage inputs -> guarded dispatch
(lock + idle queue + intent) -> bounded wait -> bound history -> receipt + GUI + review GUI.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..comfy import guards
from ..comfy.client import ComfyClient
from ..comfy.dispatch import dispatch
from ..comfy.history import select_bound_entry
from ..comfy.outputs import collect_outputs
from ..comfy.settings import ComfySettings
from ..comfy.staging import stage_input
from ..comfy.wait import wait_for_history
from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file, write_json_once
from ..health.preflight import require_ready
from ..layout.context import Context, domain_policy, load_recipe, require_provider
from .codex_queue import _refuse_blocked, provenance_problem
from . import gui, imgutil, krea2, receipts
from .common import compose_prompt, next_take, register, shot_inputs, write_prompt

RECIPE_NAME, RECIPE_SCHEMA = "krea2-edit-local-v001", "jjv/images-local-recipe/v1"


def derived_seed(ctx: Context, shot: str, plan_sha: str, take: str) -> int:
    return int(hashlib.sha256(f"{ctx.episode_id}|{shot}|{plan_sha}|{take}".encode()).hexdigest()[:8], 16)


def _vram_free_mib(client: ComfyClient) -> int | None:
    devices = (client.get("/system_stats") or {}).get("devices") or []
    free = [d.get("vram_free") for d in devices if isinstance(d.get("vram_free"), int)]
    return min(free) // (1 << 20) if free else None


def _object_info(client: ComfyClient):
    def get(name: str) -> dict:
        return (client.get(f"/object_info/{name}") or {}).get(name) or {}
    return get


def prepare(ctx: Context, out: Path, shot: str, prompt_file: Path, *, task: str | None, seed: int | None,
            take: str | None, recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything that needs no ComfyUI: composed prompt, cast sheet, graph, gates, saved API graph."""
    require_provider(ctx, "comfyui-local")
    loaded, recipe_sha = (recipe, None) if recipe else load_recipe(RECIPE_NAME, RECIPE_SCHEMA)
    task = task or loaded["default_task"]
    inputs = shot_inputs(out, shot)
    take = take or next_take(Path(out) / shot / "local")
    folder = Path(out) / shot / "local" / take
    if folder.exists():
        raise Refused(f"take folder {folder} exists; a take is never reused (pass a new --take)")
    text, prompt_src = compose_prompt(prompt_file, inputs["placement_text"])
    folder.mkdir(parents=True)
    prompt = {**write_prompt(folder, text), "source": prompt_src}
    refs = inputs["refs"]
    sheet = None
    if len(refs) >= 2:
        sheet = imgutil.cast_sheet([Path(r["path"]) for r in refs], folder / "cast-sheet.png")
        sheet["sha256"] = sha256_file(Path(sheet["path"]))
    ref_b = Path(sheet["path"]) if sheet else (Path(refs[0]["path"]) if refs else None)
    ref_b_sha = sheet["sha256"] if sheet else (refs[0]["sha256"] if refs else None)
    guide_png = receipts.png_info(Path(inputs["guide"]["path"]))
    width, height = krea2.fit_size(guide_png["width"], guide_png["height"], loaded["max_pixels"], loaded["multiple_of"])
    seed = seed if seed is not None else derived_seed(ctx, shot, inputs["plan_sha256"], take)
    guide_name = f"jjv-{inputs['guide']['sha256'][:12]}-guide.png"
    sheet_name = f"jjv-{ref_b_sha[:12]}-refs.png" if ref_b else None
    graph = krea2.build_graph(loaded, task=task, guide_name=guide_name, sheet_name=sheet_name, prompt=text, seed=seed,
                              width=width, height=height, prefix=f"{loaded['output_prefix']}/{ctx.episode_id}/{shot}/{take}")
    gate = krea2.lora_gate(graph, loaded, task)
    guards.check_graph(None, graph, guards.ClassPolicy.from_domain(ctx.domain))
    graph_sha = write_json_once(folder / "graph.api.json", graph, mode="ascii")
    return {"folder": folder, "take": take, "task": task, "seed": seed, "graph": graph, "graph_sha256": graph_sha,
            "gate": gate, "prompt": prompt, "inputs": inputs, "recipe": loaded, "recipe_sha256": recipe_sha,
            "size": [width, height], "cast_sheet": sheet, "stage": {guide_name: inputs["guide"],
            **({sheet_name: {"path": str(ref_b), "sha256": ref_b_sha}} if sheet_name else {})}}


def queue_gate(ctx: Context, item: dict[str, Any] | None, dry_run: bool) -> None:
    """G4 (IMGRT-1): a REAL local submit for a provenance_required domain needs a cleared queue row (same gate as codex-exec).
    Runs before --pilot and before any HTTP. --dry-run and other domains are unchanged."""
    required = bool(domain_policy(ctx).get("provenance_required"))
    if dry_run or not required:
        return
    why = provenance_problem(item, required)
    if why:
        raise Refused(f"comfyui-local: {why}; nothing was sent")
    _refuse_blocked(item, required, ctx=ctx)


def submit(ctx: Context, out: Path, shot: str, prompt_file: Path, settings: ComfySettings, client: ComfyClient | None, *,
           task: str | None = None, seed: int | None = None, take: str | None = None, pilot: bool = False,
           dry_run: bool = False, recipe: dict[str, Any] | None = None,
           queue_item: dict[str, Any] | None = None) -> dict[str, Any]:
    queue_gate(ctx, queue_item, dry_run)
    loaded = recipe or load_recipe(RECIPE_NAME, RECIPE_SCHEMA)[0]
    if not dry_run and loaded["qualification"]["status"] != "qualified" and not pilot:
        raise Refused(f"recipe {loaded['id']} is {loaded['qualification']['status']}: {loaded['qualification']['reason']}. "
                      "A real local submit needs --pilot (a user-authorised GPU pilot); --dry-run prepares the graph only")
    if not dry_run and client is None:
        raise Refused("a real submit needs a ComfyUI client")
    prep = prepare(ctx, out, shot, prompt_file, task=task, seed=seed, take=take, recipe=loaded)
    folder, graph = prep["folder"], prep["graph"]
    summary = {"shot": shot, "take": prep["take"], "task": prep["task"], "seed": prep["seed"], "size": prep["size"],
               "graph_sha256": prep["graph_sha256"], "graph": (folder / "graph.api.json").as_posix(),
               "prompt_sha256": prep["prompt"]["sha256"], "lora": prep["gate"]["lora_name"]}
    info = _object_info(client) if client is not None else None
    if dry_run:
        gui_rows = gui.write_guis(folder, graph, info, None, title=f"{shot} {prep['take']}",
                                  graph_sha256=prep["graph_sha256"], produced=None, domain=ctx.domain_id, shot=shot)
        return {**summary, "dry_run": True, "submitted": False, "gui": gui_rows}
    require_ready(client, settings, graph=graph, min_free_vram_mib=loaded["min_free_vram_mib"])  # T-E39 health gate
    _live_preflight(ctx, client, graph, prep, loaded)
    for name, ref in prep["stage"].items():
        stage_input(Path(ref["path"]), settings.input_dir, name, ref["sha256"])
    identity = {"stage": "images", "shot": shot, "take": prep["take"], "episode_id": ctx.episode_id}
    result = dispatch(client, settings, graph=graph, receipt_dir=folder / "comfy", identity=identity)
    entry = _wait(client, settings, result, graph, loaded)
    produced = _produced(entry, settings, graph)
    body = {"route": "comfyui-local", "provider": "comfyui-local", "requested_model": loaded["models"]["unet"],
            "resolved_model": loaded["models"]["unet"], "runtime_id": result.prompt_id, "prompt_id": result.prompt_id,
            "client_id": result.client_id, "seed": prep["seed"], "task": prep["task"],
            "models": {**loaded["models"], "lora": prep["gate"]["lora_name"], "files_sha256": "not measured"},
            "prompt": prep["prompt"], "prompt_sha256": prep["prompt"]["sha256"], "recipe": loaded["id"],
            "recipe_qualification": loaded["qualification"]["status"], "size": prep["size"],
            "cast_sheet": prep["cast_sheet"], "graph": {"api": "graph.api.json", "api_sha256": prep["graph_sha256"],
            "dir": folder.as_posix()}, "comfy_output": produced}
    receipt = register(ctx, out, shot, Path(produced["path"]), prep["inputs"], body)
    guis = gui.write_guis(folder, graph, info, settings.input_dir, title=f"{shot} {prep['take']}",
                          graph_sha256=prep["graph_sha256"], domain=ctx.domain_id, shot=shot,
                          expected_hashes={name: ref["sha256"] for name, ref in prep["stage"].items()},
                          produced={"path": produced["path"], "sha256": produced["sha256"], "prompt_id": result.prompt_id})
    return {**summary, "dry_run": False, "submitted": True, "prompt_id": result.prompt_id,
            "candidate_sha256": receipt["output"]["sha256"], "receipt": receipt["receipt_path"], "gui": guis,
            "workflow": receipt.get("review_workflow")}


def _live_preflight(ctx: Context, client: ComfyClient, graph: dict, prep: dict, recipe: dict) -> None:
    guards.check_graph(client, graph, guards.ClassPolicy.from_domain(ctx.domain))
    listing = client.get("/object_info/LoraLoaderModelOnly")
    if not krea2.lora_listed(listing, prep["gate"]["lora_name"]):
        raise Refused(f"E_LORA_GATE: ComfyUI does not list {prep['gate']['lora_name']} for LoraLoaderModelOnly "
                      "(file missing or not under models/loras); nothing was sent")
    free = _vram_free_mib(client)
    if free is None or free < recipe["min_free_vram_mib"]:
        raise Refused(f"free VRAM {free} MiB < {recipe['min_free_vram_mib']} MiB (or unreadable); another GPU job "
                      "holds the card. Nothing was sent")


def _wait(client: ComfyClient, settings: ComfySettings, result: Any, graph: dict, recipe: dict) -> dict[str, Any]:
    wait_for_history(client, result.prompt_id, timeout_seconds=recipe["history_timeout_seconds"],
                     poll_seconds=recipe["poll_seconds"])
    value = client.get("/history/" + result.prompt_id)
    return select_bound_entry(value, prompt_id=result.prompt_id, client_id=result.client_id, graph=graph)


def _produced(entry: dict[str, Any], settings: ComfySettings, graph: dict) -> dict[str, Any]:
    save_id = next(k for k, v in graph.items() if v["class_type"] == "SaveImage")
    outputs = [o for o in collect_outputs(entry, settings.output_dir) if o["node_id"] == save_id and o["exists"]]
    if len(outputs) != 1:
        raise Uncertain(f"expected exactly one SaveImage output, found {len(outputs)}: {outputs}")
    return {**outputs[0], "prompt_id": entry["prompt"][1]}

