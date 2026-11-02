"""Strict export of the local image engine's existing prepared Krea2 take.

Older local.prepare saves graph/prompt/sheet, but no preparation receipt. Prove
that graph by reconstructing it with the same engine builder and current plan;
never accept a free-form API graph or a user-supplied 'approved' boolean.
"""
from io import BytesIO
from pathlib import Path

from ..comfy.settings import settings_from_machine
from ..core.errors import Refused
from ..core.io import canonical_sha256, read_json, sha256_file
from ..h3 import pack_refs
from ..images import codex_queue, imgutil, krea2, local, receipts
from ..images.common import PLACEMENT_HEADER, shot_inputs
from ..layout.context import RECIPE_DIR, load_recipe, require_provider
from ..video import anchor_verify
from ..video.anchor_refs import resolve_recorded


def _ref(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256_file(path)}


def _verify_sheet(path, sources):
    # Replay exactly imgutil.cast_sheet in memory, including PNG encoding.
    # First-frame RGB equality would accept APNG tails or EXIF orientation
    # which ComfyUI decodes differently from imgutil.load_rgb.
    tiles = [imgutil.fit_height(imgutil.load_rgb(Path(row["path"])), 768) for row in sources]
    expected = imgutil.pil().new("RGB", (sum(tile.width for tile in tiles), 768), (255, 255, 255))
    left = 0
    for tile in tiles:
        expected.paste(tile, (left, 0))
        left += tile.width
    encoded = BytesIO()
    expected.save(encoded, format="PNG")
    if Path(path).read_bytes() != encoded.getvalue():
        raise Refused("GUI_IMAGE_SHEET: prepared cast sheet differs from the approved source composition")


def load_images(ctx, prepared_dir, shot, tier="preview", *, anchor_pack=None, prompt_batch=None):
    if tier != "preview":
        raise Refused("GUI_TIER_REFUSED: local image export supports preview only")
    if anchor_pack is None:
        raise Refused("ANCHOR_PACK_MISSING: image export needs --anchor-pack with approved source inputs")
    require_provider(ctx, "comfyui-local")
    folder = Path(prepared_dir).resolve()
    if folder.parent.name != "local" or folder.parent.parent.name != shot:
        raise Refused("GUI_IMAGE_PREPARED: expected existing IMAGES/SHOT/local/TAKE folder")
    images_out = folder.parents[2]
    inputs = shot_inputs(images_out, shot)
    if (inputs["plan"].get("episode_id"), inputs["plan"].get("domain")) != (ctx.episode_id, ctx.domain_id):
        raise Refused("GUI_IMAGE_FOREIGN: image plan belongs to another episode/domain")
    queue_proofs = {}
    confirmed_prompt = None
    item = None
    if prompt_batch is not None:
        batch = Path(prompt_batch).resolve()
        queue_proofs = {"prompt_batch": _ref(batch)}
        queue_proofs.update({f"prompt_queue_{index}": _ref(path)
                             for index, path in enumerate(sorted(batch.parent.glob("queue-*.json")))})
        allowed_roots, forbidden_roots = codex_queue.batch_roots(ctx, [])
        items = codex_queue.load_batch(batch, allowed=allowed_roots, forbidden=forbidden_roots)
        if len(items) != 1:
            raise Refused("GUI_IMAGE_PROMPT: exactly one confirmed prompt-batch item is required")
        item = items[0]
        confirmed_prompt = (f"{item['prompt_text'].strip()}\n\n{PLACEMENT_HEADER}\n"
                            f"{inputs['placement_text'].strip()}\n")
    # Same real-submit gate as the existing image engine. A dry-run preparation
    # is never sufficient evidence that its prompt was cleared for execution.
    local.queue_gate(ctx, item, False)
    if item and item.get("source") == "prompt_route":
        queue_proofs["prompt_confirmation"] = _ref(Path(item["queue_file"]).parent / "confirmations" /
                                                  f"{item['prompt_id']}-{item['prompt_text_sha256'][:12]}.json")
    pack_path = Path(anchor_pack).resolve()
    pack_before = _ref(pack_path)
    pack = anchor_verify.load_pack(ctx, pack_path)
    if pack.get("shot") != shot:
        raise Refused("ANCHOR_PACK_FOREIGN: image pack belongs to another shot")
    anchor_verify.require_valid(ctx, pack)
    recorded_shotlist = (pack.get("sources") or {}).get("shotlist") or {}
    if not recorded_shotlist.get("path"):
        raise Refused("ANCHOR_PACK_STALE: no source shotlist recorded")
    shotlist = resolve_recorded(recorded_shotlist["path"], ctx.machine)
    anchor_verify.require_fresh(ctx, pack, shotlist=shotlist, settings=settings_from_machine(ctx.machine))
    pack_refs._require_pack_approvals(ctx, pack, allow_pending_storyboard=False)
    guide = inputs["guide"]
    board = pack.get("storyboard_anchor") or {}
    if guide["sha256"] != board.get("sha256"):
        raise Refused("GUI_IMAGE_UNAPPROVED: prepared guide is not this pack's approved storyboard")
    allowed = {ref["sha256"] for role in ("face", "body", "wardrobe", "location") for ref in pack.get(f"{role}_refs") or []}
    refs = inputs["refs"]
    if any(ref["sha256"] not in allowed for ref in refs):
        raise Refused("GUI_IMAGE_UNAPPROVED: every prepared reference must belong to the current approved pack")
    recipe, _ = load_recipe(local.RECIPE_NAME, local.RECIPE_SCHEMA)
    graph_path, prompt_path = folder / "graph.api.json", folder / "prompt.txt"
    if confirmed_prompt is not None and prompt_path.read_text(encoding="utf-8") != confirmed_prompt:
        raise Refused("GUI_IMAGE_PROMPT: prepared prompt differs from the current confirmed queue prompt")
    graph = read_json(graph_path)
    task = next((key for key, value in recipe["loras"].items()
                 if (graph.get("4", {}).get("inputs") or {}).get("lora_name") == value), None)
    if task is None:
        raise Refused("GUI_IMAGE_GRAPH: prepared graph does not use the current engine edit recipe")
    krea2.lora_gate(graph, recipe, task)
    info = receipts.png_info(Path(guide["path"]))
    width, height = krea2.fit_size(info["width"], info["height"], recipe["max_pixels"], recipe["multiple_of"])
    guide_name = f"jjv-{guide['sha256'][:12]}-guide.png"
    sheet = None
    if len(refs) >= 2:
        sheet = folder / "cast-sheet.png"
        _verify_sheet(sheet, refs)
    ref_path = sheet if sheet else Path(refs[0]["path"]) if refs else None
    ref_sha = sha256_file(ref_path) if ref_path else None
    ref_name = f"jjv-{ref_sha[:12]}-refs.png" if ref_sha else None
    seed = (graph.get("13", {}).get("inputs") or {}).get("seed")
    if type(seed) is not int:
        raise Refused("GUI_IMAGE_GRAPH: missing explicit prepared seed")
    expected = krea2.build_graph(recipe, task=task, guide_name=guide_name, sheet_name=ref_name,
                                prompt=prompt_path.read_text(encoding="utf-8"), seed=seed,
                                width=width, height=height,
                                prefix=f"{recipe['output_prefix']}/{ctx.episode_id}/{shot}/{folder.name}")
    if graph != expected:
        raise Refused("GUI_IMAGE_GRAPH: graph differs from engine preparation; re-prepare rather than relabel it")
    bindings = [{**guide, "role": "guide", "ports": [("5", "image")], "input_name": guide_name}]
    if ref_path:
        bindings.append({"path": str(ref_path), "sha256": ref_sha, "role": "derived-approved-cast-sheet" if sheet else "reference",
                         "ports": [("7", "image")], "input_name": ref_name})
    proofs = {"anchor_pack": pack_before, "image_plan": _ref(images_out / receipts.PLAN_FILE),
              "prepared_graph": _ref(graph_path), "prepared_prompt": _ref(prompt_path),
              "image_recipe": _ref(RECIPE_DIR / f"{local.RECIPE_NAME}.json"), **queue_proofs}
    for index, source in enumerate(refs):
        proofs[f"approved_source_{index}"] = _ref(source["path"])
    for role in ("face", "body", "wardrobe", "location"):
        for index, source in enumerate(pack.get(f"{role}_refs") or []):
            if source.get("approval_record"):
                proofs[f"{role}_approval_{index}"] = _ref(resolve_recorded(source["approval_record"], ctx.machine))
    if sha256_file(pack_path) != pack_before["sha256"]:
        raise Refused("GUI_IMAGE_PACK_DRIFT: pack changed during image export")
    for proof in queue_proofs.values():
        if sha256_file(Path(proof["path"])) != proof["sha256"]:
            raise Refused("GUI_IMAGE_PROMPT: queue evidence changed during image export")
    return {"graph": graph, "graph_path": str(graph_path), "source_graph_sha256": canonical_sha256(graph, mode="ascii"),
            "bindings": bindings, "receipts": proofs, "shot": shot, "tier": tier,
            "run_requirements": {"gpu_requires_user_approval": True,
                                 "recipe_qualification": recipe["qualification"]["status"],
                                 "requires_pilot_approval": recipe["qualification"]["status"] != "qualified"}}
