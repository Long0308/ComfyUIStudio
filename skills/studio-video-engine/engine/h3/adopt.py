"""``jjv h3 adopt``: pull a finished H3 prompt's outputs into the episode and publish its GUI workflow.

Reads ``<shot>/comfy/job.json`` (written by ``jjv comfy wait`` / ``h3 submit``; when it is missing and the shot
was submitted, a bounded wait is run), verifies it is bound to the prepared graph, copies every output file
(hash-checked, never overwriting) to ``<shot>/results/<prompt_id>/`` and writes the write-once receipt
``<shot>/adopt.json``.  The editable API graph is converted to a GUI graph when ComfyUI can describe its nodes
(best effort, error recorded); a review GUI carrying a ``LoadVideo`` node that PINS the editorial result is
always written, staged into ComfyUI ``input/`` and added to the episode workflow manifest.
Adoption is NOT acceptance: the take stays ``pending`` until ``jjv h3 accept``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..audio.gui import api_to_gui
from ..comfy.gui_inputs import stage_graph_inputs
from ..comfy import commands
from ..comfy.client import ComfyClient
from ..comfy.dispatch import SUBMITTED_FILE
from ..comfy.settings import ComfySettings
from ..comfy.staging import link_new_file, require_hash, stage_input
from ..core.errors import Refused
from ..core.io import pretty_json, read_json, sha256_file, write_atomic, write_json_once, write_once
from ..layout.context import Context
from .prepare import load_prepared
from .submit import COMFY_DIR

ADOPT_FILE = "adopt.json"
ADOPT_SCHEMA = "jjv/h3-adopt/v1"
WORKFLOW_DIR = "workflows/H3_MOTION"
MANIFEST = Path("workflows") / "WORKFLOW-MANIFEST.json"


def _job(folder: Path, receipt: dict, client: ComfyClient | None, settings: ComfySettings,
         timeout: float) -> dict:
    receipts = folder / COMFY_DIR
    path = receipts / commands.JOB_FILE
    if not path.is_file():
        if not (receipts / SUBMITTED_FILE).is_file() or client is None:
            raise Refused(f"{receipt['shot']}: no {commands.JOB_FILE} and no submitted receipt; "
                          "submit (and wait) first")
        commands.cmd_wait(client, settings, receipt_dir=receipts, timeout_seconds=timeout)
    job = read_json(path)
    if job.get("status") != "COMPLETED" or job.get("graph_sha256") != receipt["graph_sha256"]:
        raise Refused(f"{receipt['shot']}: job is {job.get('status')!r} / graph "
                      f"{str(job.get('graph_sha256'))[:12]} (prepared {receipt['graph_sha256'][:12]}); not adoptable")
    return job


def _copy_outputs(folder: Path, receipt: dict, job: dict) -> list[dict]:
    roles = {receipt["editorial_node"]: "editorial", **{v: k for k, v in receipt.get("sinks", {}).items()}}
    target = folder / "results" / job["prompt_id"]
    rows = []
    for item in job["outputs"]:
        if not item.get("exists") or not item.get("sha256"):
            raise Refused(f"{receipt['shot']}: output {item.get('filename')} is missing/unreadable: {item.get('error')}")
        source = Path(item["path"])
        require_hash(source, item["sha256"], "ComfyUI output")
        dest = link_new_file(source, target / source.name, item["sha256"], "adopted output")
        rows.append({"role": roles.get(item["node_id"], "extra"), "node_id": item["node_id"], "path": str(dest),
                     "name": source.name, "sha256": item["sha256"], "bytes": item["bytes"]})
    if not any(r["role"] == "editorial" for r in rows):
        raise Refused(f"{receipt['shot']}: the job has no output from editorial node {receipt['editorial_node']}")
    return sorted(rows, key=lambda r: (r["role"], r["name"]))


def _review_gui(base: dict | None, *, shot: str, input_name: str, sha: str, prompt_id: str, graph_sha: str) -> dict:
    nodes = list(base["nodes"]) if base else []
    node_id = (base["last_node_id"] if base else 0) + 1
    right = max((float(n["pos"][0]) for n in nodes), default=-520.0)
    nodes.append({"id": node_id, "type": "LoadVideo", "pos": [right + 520, 40], "size": [430, 320], "flags": {},
                  "order": len(nodes), "mode": 0,
                  "inputs": [{"localized_name": "file", "name": "file", "type": "COMBO", "widget": {"name": "file"},
                              "link": None}],
                  "outputs": [{"localized_name": "VIDEO", "name": "VIDEO", "type": "VIDEO", "links": []}],
                  "title": f"KET QUA PENDING | job {prompt_id[:8]} | SHA {sha[:12]}",
                  "properties": {"Node name for S&R": "LoadVideo"}, "widgets_values": [input_name],
                  "widgets_values_named": {"file": input_name}, "color": "#114f5a", "bgcolor": "#09292f"})
    digest = hashlib.sha256(f"{shot}|{graph_sha}".encode()).hexdigest()
    gui = {"id": digest[:8] + "-0000-4000-8000-" + digest[:12], "revision": 0, "last_node_id": node_id,
           "last_link_id": base["last_link_id"] if base else 0, "nodes": nodes,
           "links": base["links"] if base else [], "groups": base["groups"] if base else [],
           "config": {}, "extra": dict(base["extra"]) if base else {}, "version": 0.4}
    gui["extra"].update(review_only=True, result_sha256=sha, prompt_id=prompt_id, status="pending", shot=shot,
                        graph_sha256=graph_sha)
    return gui


def _publish(ctx: Context, shot: str, review: dict, key: str, entry: dict) -> dict:
    root = Path(ctx.root)
    manifest_path = root / MANIFEST
    manifest = read_json(manifest_path) if manifest_path.is_file() else {
        "schema": "jjv/workflow-manifest/v1", "episode_id": ctx.episode_id, "entries": []}
    if not isinstance(manifest.get("entries"), list):
        raise Refused(f"{manifest_path} is not a workflow manifest with an entries list")
    for old in manifest["entries"]:
        if old.get("publication_key") == key and (root / old["path"]).is_file():
            return {"workflow": str((root / old["path"]).resolve()), "reused": True, "manifest": str(manifest_path)}
    stem = f"{shot}-h3-{key.split(':')[-1][:12]}"
    folder = root / WORKFLOW_DIR
    number = 1
    while (folder / f"{stem}-v{number:03d}.workflow.json").exists():
        number += 1
    path = folder / f"{stem}-v{number:03d}.workflow.json"
    digest = write_once(path, pretty_json(review, mode="ascii"))
    row = {"schema": "jjv/workflow-entry/v1", "stage": "05_h3_motion", "path": path.relative_to(root).as_posix(),
           "root": "episode", "sha256": digest, "kind": "review", "status": "candidate", "publication_key": key,
           **entry}
    manifest["entries"] = [e for e in manifest["entries"] if e.get("path") != row["path"]] + [row]
    manifest["entry_count"] = len(manifest["entries"])
    write_atomic(manifest_path, pretty_json(manifest, mode="ascii"))
    return {"workflow": str(path.resolve()), "workflow_sha256": digest, "reused": False, "manifest": str(manifest_path)}


def _gui(client: ComfyClient | None, graph: dict, shot: str, graph_sha: str, *, input_dir: Path, domain: str,
         expected_hashes: dict[str, str] | None = None) -> tuple[dict | None, str | None]:
    if client is None:
        return None, "no ComfyUI client: editable GUI not generated"
    def info(name: str) -> dict:
        return (client.get(f"/object_info/{name}") or {}).get(name) or {}
    try:
        staged = stage_graph_inputs(graph, input_dir, domain=domain, shot=shot, expected_hashes=expected_hashes)
        return api_to_gui(staged, info, title=f"{shot} H3", extra={"graph_sha256": graph_sha}), None
    except Exception as error:  # noqa: BLE001 - the API graph + receipts are the evidence; GUI is best effort
        return None, repr(error)


def adopt(ctx: Context, out: Path, shots: list[str] | None, settings: ComfySettings, client: ComfyClient | None, *,
          wait_timeout: float = 3600.0) -> dict[str, Any]:
    results = []
    for folder, receipt, graph in load_prepared(ctx, out, shots=shots):
        done = folder / ADOPT_FILE
        if done.is_file():  # idempotent: an adopted shot is reported, never rewritten
            prior = read_json(done)
            edit = next(r for r in prior["outputs"] if r["role"] == "editorial")
            results.append({"shot": receipt["shot"], "prompt_id": prior["prompt_id"], "editorial_sha256": edit["sha256"],
                            "adopt_sha256": sha256_file(done), "workflow": prior["published"]["workflow"],
                            "gui_error": prior["editable_gui_error"], "review_status": "pending", "reused": True})
            continue
        job = _job(folder, receipt, client, settings, wait_timeout)
        outputs = _copy_outputs(folder, receipt, job)
        editorial = next(r for r in outputs if r["role"] == "editorial")
        input_name = f"jjv-result-{editorial['sha256'][:12]}{Path(editorial['name']).suffix.lower()}"
        stage_input(Path(editorial["path"]), settings.input_dir, input_name, editorial["sha256"])
        editable, gui_error = _gui(client, graph, receipt["shot"], receipt["graph_sha256"],
                                   input_dir=settings.input_dir, domain=ctx.domain_id,
                                   expected_hashes={item["input_name"]: item["sha256"] for item in
                                                    [receipt["anchor"], receipt["wav"], *receipt["faces"],
                                                     *(receipt.get("refs") or [])]})
        if editable is not None:
            write_json_once(folder / "graph.gui.json", editable, mode="ascii")
        review = _review_gui(editable, shot=receipt["shot"], input_name=input_name, sha=editorial["sha256"],
                             prompt_id=job["prompt_id"], graph_sha=receipt["graph_sha256"])
        review_sha = write_json_once(folder / "graph.review.gui.json", review, mode="ascii")
        published = _publish(ctx, receipt["shot"], review,
                             f"h3:{receipt['shot']}:{editorial['sha256']}:{receipt['graph_sha256']}",
                             {"result_sha256": editorial["sha256"], "source_prompt_id": job["prompt_id"],
                              "comfyui_input": input_name, "graph_sha256": receipt["graph_sha256"],
                              "result_pins": [{"node_type": "LoadVideo", "input_file": input_name,
                                               "input_exists": True}]})
        body = {"schema": ADOPT_SCHEMA, "episode_id": ctx.episode_id, "shot": receipt["shot"],
                "prompt_id": job["prompt_id"], "client_id": job["client_id"],
                "graph_sha256": receipt["graph_sha256"], "preparation_wav_sha256": receipt["wav"]["sha256"],
                "outputs": outputs, "review_gui": {"path": "graph.review.gui.json", "sha256": review_sha},
                "editable_gui": "graph.gui.json" if editable is not None else None,
                "editable_gui_error": gui_error, "pinned_input": input_name, "review_status": "pending",
                "published": published}
        sha = write_json_once(folder / ADOPT_FILE, body, mode="ascii")
        results.append({"shot": receipt["shot"], "prompt_id": job["prompt_id"], "editorial_sha256": editorial["sha256"],
                        "adopt_sha256": sha, "workflow": published["workflow"], "gui_error": gui_error,
                        "review_status": "pending"})
    return {"episode_id": ctx.episode_id, "adopted": results}


__all__ = ["adopt", "ADOPT_FILE"]
