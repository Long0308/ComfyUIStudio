"""Long-take H3 preparation and guarded dispatch for a single video shot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..comfy.guards import ClassPolicy, check_graph, graph_class_types, static_refusals
from ..core.errors import Refused, Uncertain
from ..core.io import canonical_json, canonical_sha256, read_json, write_json_once, write_once
from ..core.runlock import run_pid_lock
from ..h3 import adopt as adopt_mod
from ..h3 import pack_refs, prepare as prepare_mod, submit as submit_mod
from ..h3.qualification import output_prefix, validate_media_ports
from ..layout.context import Context
from . import longtake, routes as routes_mod, state as state_mod


def _qualification(ctx: Context, block: dict[str, Any], approval: dict[str, Any], template: dict) -> dict | None:
    """An unqualified route needs a user token; a qualified one needs a pinned pilot."""
    record = block.get("qualification")
    if record is None:
        if approval.get("kind") != "token":
            raise Refused("LONG_TAKE_UNQUALIFIED: --gpu-approved token:<user approval> is required until this "
                          "route has its own qualification receipt; nothing was sent")
        return None
    if not isinstance(record, dict) or not all(isinstance(record.get(k), str) for k in ("path", "sha256")):
        raise Refused("LONG_TAKE_QUALIFICATION_INVALID: route needs a path and sha256")
    proof = prepare_mod.asset(longtake.REPO_ROOT, record, "long-take qualification")
    body = read_json(proof["path"])
    if (body.get("status"), body.get("domain"), body.get("route"), body.get("template_sha256"),
            body.get("user_authorized"), body.get("executor")) != (
            "PASS", ctx.domain_id, block["route"], template["sha256"], True, "comfyui-local"):
        raise Refused("LONG_TAKE_QUALIFICATION_INVALID: pilot receipt does not qualify this domain/route/template")
    return proof


def prepare_graph(ctx: Context, out: Path, state: dict, receipt: dict, prompt_text: str,
                  route: dict, manifest: Path, row: dict, approval: dict) -> tuple[Path, dict, dict]:
    block = longtake.long_block(ctx.domain_id, route)
    template = longtake.long_template(ctx.domain_id, route)
    qualification = _qualification(ctx, block, approval, template)
    document = read_json(manifest)
    shot = state["shot"]
    anchor, faces, refs, pack = prepare_mod._media(ctx, row, shot)
    prepare_mod.require_anchor_pack_or_approved_legacy(ctx, document, row, faces)
    wav = prepare_mod.asset(ctx.root, row["wav"], "WAV")
    if document.get("voice_dir"):
        voice_dir = str((ctx.root / document["voice_dir"]).resolve())
        voice_proof = prepare_mod.voice_proof(ctx, Path(voice_dir), wav, row.get("logical_shot", shot))
    elif document.get("legacy_voice") is True:
        prior = prepare_mod.asset(ctx.root, row["preparation_receipt"], "prior preparation receipt") if row.get("preparation_receipt") else None
        voice_dir, voice_proof = None, prepare_mod._legacy_proof(ctx, shot, prior, wav)
    else:
        raise Refused("manifest needs voice_dir or an approved legacy_voice preparation receipt")
    beats = receipt.get("take_windows")
    windows = longtake.window_count(receipt["duration_s"], block["max_windows"])
    if not isinstance(beats, list) or len(beats) != windows:
        raise Refused(f"LONG_TAKE_WINDOWS_MISSING: {shot}: re-plan with exactly {windows} frozen windows")
    parts = longtake.split_prompt(prompt_text, beats, receipt["duration_s"])
    graph = longtake.build_graph(read_json(Path(template["path"])), block, parts["windows"],
                                 width=(receipt.get("geometry") or {}).get("width"),
                                 height=(receipt.get("geometry") or {}).get("height"),
                                 length=receipt["length"]["frames"])
    policy = ClassPolicy.from_domain(ctx.domain)
    problems = static_refusals(graph_class_types(graph), policy)
    if problems:
        raise Refused("; ".join(problems))
    validate_media_ports(graph, anchor, wav, [*faces, *refs])
    bound = prepare_mod._bind_media(graph, [anchor, wav, *faces, *refs])
    unused = [slot for slot, node in pack_refs.ref_loaders(graph).items() if (node, "image") not in bound]
    prepare_mod.drop_ref_loaders(graph, unused, bound)
    for node, item in graph.items():
        if item["class_type"] in ("LoadImage", "LoadAudio"):
            key = "image" if item["class_type"] == "LoadImage" else "audio"
            if (node, key) not in bound:
                raise Refused(f"unbound long-take media loader {node}.{key}")
    prepare_mod.set_port(graph, routes_mod.port_pair(route["ports"]["seed"]), receipt["seed"])
    port = route["ports"]["output_ports"][0]
    short_qualification = prepare_mod.domain_guard(ctx)
    root = short_qualification["output_prefix_root"] if short_qualification else str(graph[str(port[0])]["inputs"][port[1]]).split("/")[0]
    prefix = output_prefix(graph, port, root)
    digest_before_prefix = canonical_sha256(graph, mode="ascii")
    prepare_mod.set_port(graph, port, f"{prefix}/{prepare_mod.safe(ctx.episode_id)}/{shot}/{digest_before_prefix}/0")
    digest = canonical_sha256(graph, mode="ascii")
    folder = Path(out) / f"h3-{state_mod.rev(state['revision'])}" / shot
    prep = {"schema": prepare_mod.SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
            "shot": shot, "logical_shot": row.get("logical_shot", shot), "status": "PREPARED_NOT_SUBMITTED",
            "route": block["route"], "take_mode": "long", "template": template, "qualification": qualification,
            "anchor": anchor, "wav": wav, "faces": faces, "refs": refs, "anchor_pack": pack,
            "voice_dir": voice_dir, "voice_approval": voice_proof, "graph_sha256": digest,
            "editorial_node": route["ports"]["editorial_node"], "sinks": {},
            "window_count": windows, "window_log": longtake.window_log(receipt["duration_s"], receipt["length"]["frames"], parts["windows"]),
            "prompt_windows": parts, "review_status": "pending"}
    write_once(folder / prepare_mod.GRAPH_FILE, canonical_json(graph, mode="ascii"))
    write_json_once(folder / prepare_mod.PREPARATION_FILE, prep, mode="ascii")
    return folder, prep, graph


def dispatch_and_adopt(ctx: Context, out: Path, folder: Path, prep: dict, graph: dict,
                       comfy: Any, wait_timeout: float) -> tuple[Path, dict]:
    """Use the H3 submit helper, which calls the shared locked/idle/intent dispatch."""
    check_graph(comfy.client, graph, ClassPolicy.from_domain(ctx.domain), cache={})
    lock_path = comfy.settings.executor_lock_path
    with run_pid_lock(lock_path, report_dir=Path(out) / "runs", scope="machine",
                      extra={"stage": "video-longtake", "shot": prep["shot"]}):
        existing = submit_mod._existing(folder)
        adopt_path = folder / adopt_mod.ADOPT_FILE
        if adopt_path.is_file() and existing is None:
            raise Uncertain(f"{folder}: adopted output exists without dispatch evidence; reconcile, never resubmit")
        if existing is None:
            submitted = submit_mod._submit_one(ctx, comfy.settings, comfy.client, folder, prep, graph,
                                                probe=comfy.probe, ps=comfy.ps, wait=True,
                                                wait_timeout=wait_timeout, done=[])
        else:
            submitted = existing
        if adopt_path.is_file():
            adopted = read_json(adopt_path)
        else:
            job = adopt_mod._job(folder, prep, comfy.client, comfy.settings, wait_timeout)
            outputs = adopt_mod._copy_outputs(folder, prep, job)
            editorial = next(r for r in outputs if r["role"] == "editorial")
            from ..comfy.staging import stage_input
            from ..core.io import sha256_file
            input_name = f"jjv-result-{editorial['sha256'][:12]}{Path(editorial['name']).suffix.lower()}"
            stage_input(Path(editorial["path"]), comfy.settings.input_dir, input_name, editorial["sha256"])
            gui, gui_error = adopt_mod._gui(comfy.client, graph, prep["shot"], prep["graph_sha256"])
            if gui is not None:
                write_json_once(folder / "graph.gui.json", gui, mode="ascii")
            review = adopt_mod._review_gui(gui, shot=prep["shot"], input_name=input_name,
                                           sha=editorial["sha256"], prompt_id=job["prompt_id"],
                                           graph_sha=prep["graph_sha256"])
            review_sha = write_json_once(folder / "graph.review.gui.json", review, mode="ascii")
            published = adopt_mod._publish(ctx, prep["shot"], review,
                                           f"h3-longtake:{prep['shot']}:{editorial['sha256']}:{prep['graph_sha256']}",
                                           {"result_sha256": editorial["sha256"], "source_prompt_id": job["prompt_id"],
                                            "comfyui_input": input_name, "graph_sha256": prep["graph_sha256"]})
            adopted = {"schema": adopt_mod.ADOPT_SCHEMA, "episode_id": ctx.episode_id, "shot": prep["shot"],
                       "prompt_id": job["prompt_id"], "client_id": job["client_id"],
                       "graph_sha256": prep["graph_sha256"], "preparation_wav_sha256": prep["wav"]["sha256"],
                       "outputs": outputs, "review_gui": {"path": "graph.review.gui.json", "sha256": review_sha},
                       "editable_gui": "graph.gui.json" if gui is not None else None,
                       "editable_gui_error": gui_error, "pinned_input": input_name,
                       "review_status": "pending", "published": published}
            write_json_once(adopt_path, adopted, mode="ascii")
    return adopt_path, {"submitted": submitted, "adopted": adopted}


__all__ = ["prepare_graph", "dispatch_and_adopt"]
