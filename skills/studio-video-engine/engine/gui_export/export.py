"""Materialise an adapter-validated shot without submitting or rendering it.

All hashes, loader coverage, node definitions and target collisions are checked
before writes. Domain folder names are policy data, never inferred from a shot.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Callable

from ..comfy.gui_inputs import LOADERS, flat_input_name
from ..comfy.staging import require_hash
from ..comfy.guards import ALWAYS_REFUSED, custom_pack, graph_class_types
from ..core import steplog
from ..core.errors import Refused
from ..core.io import canonical_sha256, pretty_json, read_json, sha256_bytes, sha256_file, write_once
from .convert import convert_gui

POLICY = Path(__file__).resolve().parents[2] / "recipes" / "gui-export-targets-v001.json"
SAFE = re.compile(r"[A-Za-z0-9_-]+\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")


def _inside(path: Path, root: Path) -> Path:
    path, root = path.resolve(), root.resolve()
    if path == root or not path.is_relative_to(root):
        raise Refused(f"GUI_PATH: target escapes its configured root: {path}")
    return path


def _segment(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value in (".", "..") or any(c in value for c in '/\\:'):
        raise Refused(f"GUI_PATH: invalid folder segment {value!r}")
    return value


def _bytes(ref: dict, label: str) -> tuple[Path, bytes]:
    path = Path(ref["path"]).resolve()
    sha = ref.get("sha256")
    if not isinstance(sha, str) or not SHA.fullmatch(sha) or not path.is_file():
        raise Refused(f"GUI_HASH: {label} needs an existing file and SHA-256")
    data = path.read_bytes()
    if sha256_bytes(data) != sha:
        raise Refused(f"GUI_HASH: {label} sha256 mismatch: {path}")
    return path, data


def _collision(path: Path, data: bytes) -> None:
    if path.exists() and (not path.is_file() or path.read_bytes() != data):
        raise Refused(f"GUI_COLLISION: refusing to overwrite {path}")


def check_identity_bindings(domain: Any, bindings: list, *, shot: str) -> int:
    """Guard 2 on the adapter bindings: identity-role media must be on the domain allow-list (path + sha256)."""
    from ..policy import identity_guard
    return identity_guard.check_refs(domain, bindings, where=f"export-gui {shot}")


def export_gui(ctx: Any, prepared: dict, *, kind: str, out: Path,
               object_info: Callable[[str], dict], policy: dict | None = None,
               workflows_root: Path | None = None) -> dict:
    """Export one *already validated* adapter result; adapters are the approval boundary.

    The CLI never accepts serialized adapter results from a user. ``policy`` and
    ``object_info`` injection are for tests; production uses checked-in policy
    and GET /object_info on the configured ComfyUI instance.
    """
    domain, shot, tier = ctx.domain_id, prepared.get("shot"), prepared.get("tier")
    if kind not in ("image", "video") or not SAFE.fullmatch(domain) or not isinstance(shot, str) or not SAFE.fullmatch(shot):
        raise Refused("GUI_IDENTITY: invalid kind, domain or shot")
    if tier != "preview":
        raise Refused("GUI_TIER_REFUSED: prepared image/H3 GUI export supports preview only")
    rules = read_json(POLICY) if policy is None else policy
    row = rules.get(domain)
    if not isinstance(row, dict):
        raise Refused(f"GUI_DOMAIN_REFUSED: no workflow target policy for {domain}")
    folder = _segment(row["folder"])
    # Two domains may never share a project folder, even under a bad policy.
    if any(key != domain and str(other.get("folder", "")).casefold() == folder.casefold()
           for key, other in rules.items() if isinstance(other, dict)):
        raise Refused("GUI_DOMAIN_REFUSED: domains share a workflow target")
    machine_root = Path(ctx.machine["comfy"]["root"]).resolve()
    base = machine_root / "user" / "default" / "workflows"
    if workflows_root is not None and Path(workflows_root).resolve() != base.resolve():
        raise Refused("GUI_PATH: workflows_root must be the configured ComfyUI user/default/workflows")
    target_dir = _inside(base / folder / _segment(row[f"{kind}_folder"]) / "UAT", base)
    input_root = machine_root / "input"
    _inside(input_root, machine_root)
    out = Path(out).resolve()
    # Refuse an arbitrary export log/receipt destination outside the episode.
    _inside(out, Path(ctx.root))
    source = prepared["graph"]
    graph_class_types(source)
    graph_path = Path(prepared["graph_path"]).resolve()
    if read_json(graph_path) != source:
        raise Refused("GUI_GRAPH_DRIFT: prepared graph and source file disagree")
    graph_sha = prepared["source_graph_sha256"]
    if graph_sha not in (sha256_file(graph_path), canonical_sha256(source, mode="ascii")):
        raise Refused("GUI_GRAPH_DRIFT: source graph sha256 mismatch")
    receipts = prepared.get("receipts") or {}
    if not receipts:
        raise Refused("GUI_APPROVAL: no adapter approval evidence")
    check_identity_bindings(getattr(ctx, "domain", None), prepared.get("bindings") or [], shot=shot)
    from ..policy import identity_guard as _ig
    identity_refs = _ig.listed_report(getattr(ctx, "domain", None), prepared.get("bindings") or [])
    from ..policy import model_policy
    model_policy.check_anchor_graph(getattr(ctx, "domain", None), source, where=f"export-gui {shot}")
    verified = {role: _bytes(ref, role) for role, ref in receipts.items()}
    graph = copy.deepcopy(source)
    media, writes, bound = [], {}, set()
    for binding in prepared.get("bindings") or []:
        path, data = _bytes(binding, binding.get("role", "input"))
        ext = path.suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".wav", ".flac", ".mp3", ".ogg"):
            raise Refused(f"GUI_MEDIA: unsupported media suffix {ext!r}")
        name = flat_input_name(domain, shot, binding["sha256"], path.name)
        target = _inside(input_root / name, input_root)
        if target in writes and writes[target] != data:
            raise Refused(f"GUI_COLLISION: different sources map to {name}")
        writes[target] = data
        ports = binding.get("ports")
        if not isinstance(ports, list) or not ports:
            raise Refused("GUI_BINDING: every source needs loader ports")
        for node_id, key in ports:
            node_id = str(node_id)
            node = graph.get(node_id) or {}
            if (node_id, key) in bound or LOADERS.get(node.get("class_type")) != key:
                raise Refused("GUI_BINDING: duplicate port or unsupported loader")
            if node.get("inputs", {}).get(key) != binding.get("input_name"):
                raise Refused("GUI_BINDING: loader does not match adapter-approved input")
            bound.add((node_id, key))
            node["inputs"][key] = name
            media.append({"role": binding["role"], "filename": name, "subfolder": "", "type": "input",
                          "sha256": binding["sha256"], "node_id": node_id, "input_key": key})
    required = {(str(n), LOADERS[v["class_type"]]) for n, v in graph.items() if v["class_type"] in LOADERS}
    if not required or bound != required:
        raise Refused("GUI_BINDING: every image/mask/audio loader needs exactly one approved input")
    definitions = {}
    writers = []
    domain_policy = getattr(ctx, "domain", {})
    forbidden = {str(n).lower() for n in domain_policy.get("forbidden_node_classes", [])} | ALWAYS_REFUSED
    allowed = {str(n).lower() for n in domain_policy.get("allowed_custom_nodes", [])}
    for nid, node in graph.items():
        name = node["class_type"]
        info = object_info(name)
        if not isinstance(info, dict) or not info.get("input"):
            raise Refused(f"GUI_NODE: missing /object_info definition for {name}")
        pack = custom_pack(info)
        if (name.lower() in forbidden or info.get("api_node") or "comfy_api_nodes" in str(info.get("python_module", ""))
                or str(info.get("category", "")).lower().startswith("api node") or pack and pack.lower() not in allowed):
            raise Refused(f"GUI_NODE: forbidden/partner/unapproved custom node {name}")
        if name.lower().startswith(("loadimage", "loadaudio", "loadvideo", "vhs_load")) and name not in LOADERS:
            raise Refused(f"GUI_MEDIA: unsupported filesystem loader {name}")
        inputs = node.get("inputs") or {}
        if "filename_prefix" in inputs:
            inputs["filename_prefix"] = f"{domain}/gui-uat/{shot}/{tier}/node-{nid}"
            writers.append({"node_id": nid, "filename_prefix": inputs["filename_prefix"]})
        elif name.lower().startswith("save") or inputs.get("save_output") is True:
            raise Refused(f"GUI_OUTPUT: unsupported output path contract for {name}")
        for key in ("output_path", "output_dir", "save_path", "directory", "file_path"):
            if key in inputs:
                raise Refused(f"GUI_PATH: unsupported file path widget {name}.{key}")
        definitions[name] = info
    if not writers:
        raise Refused("GUI_OUTPUT: graph has no supported persistent output node")
    receipt_shas = {role: ref["sha256"] for role, ref in receipts.items()}
    export_id = canonical_sha256({"domain": domain, "episode": ctx.episode_id, "kind": kind, "shot": shot,
                                  "tier": tier, "graph": graph, "receipts": receipt_shas, "target": str(target_dir)}, mode="ascii")
    meta = {"export_gui_version": 1, "export_id": export_id, "domain": domain, "episode_id": ctx.episode_id,
            "kind": kind, "shot": shot, "tier": tier, "receipt_shas": receipt_shas,
            **({"identity_refs": identity_refs} if identity_refs else {}),
            "source_graph_sha256": graph_sha, "inputs": media, "outputs": [], "output_targets": writers,
            "run_requirements": prepared.get("run_requirements", {"gpu_requires_user_approval": True}),
            "status": "EXPORTED_NOT_RENDERED"}
    gui = convert_gui(graph, definitions.__getitem__, title=f"{domain} {shot} {kind} {tier}", extra={"newtecons": meta})
    workflow = _inside(target_dir / f"{shot}-{tier}-{export_id[:16]}.workflow.json", base)
    workflow_data = pretty_json(gui, mode="utf8")
    writes[workflow] = workflow_data
    receipt_path = _inside(out / "gui-exports" / f"{kind}-{shot}-{export_id[:16]}.json", out)
    receipt = {"schema": "jjv/gui-export/v1", **meta, "workflow": str(workflow),
               "workflow_sha256": sha256_bytes(workflow_data), "source_graph": str(graph_path),
               "receipts": receipts, "rendered": False}
    writes[receipt_path] = pretty_json(receipt, mode="utf8")
    for path, data in writes.items():
        _collision(path, data)
    refs = [(role, path) for role, (path, _) in verified.items()] + [("prepared_graph", graph_path)]
    refs += [(b["role"], Path(b["path"])) for b in prepared["bindings"]]
    with steplog.logged_step(out, run_id=out.name, step_id=f"{kind}.export-gui.{shot}", stage=f"{kind}.export-gui",
                             inputs=refs, settings={"shot": shot, "tier": tier, "export_id": export_id},
                             model={"name": "cpu-gui-export", "sha256": None}) as step:
        # Recheck evidence immediately before publishing; copy payloads, never hardlink source media.
        for role, ref in receipts.items():
            _bytes(ref, role)
        for binding in prepared["bindings"]:
            _bytes(binding, binding["role"])
        for path, data in writes.items():
            write_once(path, data)
            require_hash(path, sha256_bytes(data), "GUI exported file")
            step.output(path, "workflow" if path == workflow else "export_receipt" if path == receipt_path else "staged_input")
    return {"status": "EXPORTED", "domain": domain, "shot": shot, "tier": tier, "rendered": False,
            "workflow": str(workflow), "workflow_sha256": sha256_bytes(workflow_data),
            "receipt": str(receipt_path), "inputs": media}
