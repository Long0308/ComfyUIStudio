"""Wardrobe anchor sets for bridge image jobs (domain-neutral: every path and member comes from ``<state>/config.json``).

``config.json`` key ``wardrobe`` maps a domain id to::

    {"required": true, "registry": "<abs registry.json>", "default_context": "cong_truong",
     "path_map": {"D:/old-root": "J:/new-root"}, "stage_subdir": "wardrobe", "ui_data": "<abs folder>",
     "contexts": {"cong_truong": ["ITEM_ID", {"item": "ITEM_ID", "roles": ["role to keep"]}], ...}}

Members are the ``source_references`` (path, role, sha256) of the registry items a context names; nothing is invented.
A member whose file is missing or whose sha256 differs from the registry is a REFUSAL, never a silent run without it.
``stage`` copies (never moves) the members write-once into the ComfyUI input folder and writes the UI presets JSON.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from ..comfy.settings import settings_from_machine
from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_atomic, write_once

PRESETS_SCHEMA = "jjv/wardrobe-presets/v1"


def domain_block(wardrobe: dict[str, Any] | None, domain_id: str) -> dict[str, Any] | None:
    block = (wardrobe or {}).get(domain_id)
    if block is None:
        return None
    if not isinstance(block, dict) or not isinstance(block.get("contexts"), dict) or not block["contexts"]:
        raise Refused(f"config.json wardrobe[{domain_id!r}] needs a non-empty 'contexts' object")
    if not isinstance(block.get("registry"), str):
        raise Refused(f"config.json wardrobe[{domain_id!r}] needs 'registry' (absolute registry.json path)")
    return block


def _locate(raw: str, block: dict[str, Any], registry_dir: Path) -> Path:
    """The file a registry path names: as written, after ``path_map`` prefix remaps, then next to the registry."""
    candidates = [raw]
    for old, new in (block.get("path_map") or {}).items():
        a, b = raw.replace("\\", "/"), str(old).replace("\\", "/")
        if a.lower().startswith(b.lower()):
            candidates.append(str(new).replace("\\", "/").rstrip("/") + a[len(b):])
    parts = re.split(r"[\\/]", raw)
    candidates += [str(registry_dir / parts[-2] / parts[-1]) if len(parts) > 1 else "", str(registry_dir / parts[-1])]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise Refused(f"wardrobe reference file not found: {raw} (tried {[c for c in candidates if c]})")


def _members(block: dict[str, Any], context: str) -> list[dict[str, str]]:
    registry_path = Path(block["registry"])
    registry = read_json(registry_path)
    items = {i.get("id"): i for i in (registry.get("items") if isinstance(registry, dict) else None) or []}
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in block["contexts"][context]:
        spec = {"item": entry} if isinstance(entry, str) else dict(entry)
        item = items.get(spec.get("item"))
        if item is None:
            raise Refused(f"wardrobe context {context!r}: registry item {spec.get('item')!r} not in {registry_path.name}")
        roles = spec.get("roles")
        for source in item.get("source_references") or []:
            if roles is not None and source.get("role") not in roles:
                continue
            path = _locate(str(source["path"]), block, registry_path.parent)
            digest = sha256_file(path)
            if digest != source.get("sha256"):
                raise Refused(f"wardrobe reference {path.name} hashes {digest[:12]}, registry says "
                              f"{str(source.get('sha256'))[:12]}: refused (changed or wrong file)")
            if digest in seen:  # the same file named by several items (vest variants share their photos)
                continue
            seen.add(digest)
            rows.append({"name": path.name, "path": path.as_posix(), "role": str(source["role"]), "sha256": digest,
                         "origin": f"{context}:{item['id']}"})
    if not rows:
        raise Refused(f"wardrobe context {context!r} resolved to no reference")
    return rows


def resolve(wardrobe: dict[str, Any] | None, domain_id: str, context: str | None) -> tuple[str | None, list[dict[str, str]]]:
    """``(context name, verified refs)`` for a request.  No wardrobe config for the domain => ``(None, [])``."""
    block = domain_block(wardrobe, domain_id)
    if block is None:
        if context:
            raise Refused(f"context {context!r} asked but config.json has no wardrobe block for domain {domain_id!r}")
        return None, []
    chosen = context or block.get("default_context")
    if chosen not in block["contexts"]:
        raise Refused(f"wardrobe context must be one of {sorted(block['contexts'])} (got {chosen!r})")
    return chosen, _members(block, chosen)


def safe_name(name: str) -> str:
    stem = Path(name).stem.replace("\u0110", "D").replace("\u0111", "d")
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    return (re.sub(r"[^A-Za-z0-9]+", "_", ascii_stem).strip("_") or "ref") + (Path(name).suffix.lower() or ".png")


def stage(wardrobe: dict[str, Any], domain_id: str, machine_path: Path) -> dict[str, Any]:
    """Copy every context member into ``<ComfyUI input>/<stage_subdir>/<sha12>_<name>`` (write-once) and write the
    presets JSON ``<ui_data>/<domain>.json``.  Originals are only read."""
    block = domain_block(wardrobe, domain_id)
    if block is None:
        raise Refused(f"config.json has no wardrobe block for domain {domain_id!r}")
    if not isinstance(block.get("ui_data"), str):
        raise Refused(f"config.json wardrobe[{domain_id!r}] needs 'ui_data' (folder for the presets JSON)")
    input_dir = settings_from_machine(read_json(machine_path)).input_dir
    subdir = str(block.get("stage_subdir") or "wardrobe")
    contexts: dict[str, list[dict[str, str]]] = {}
    copied: list[str] = []
    for context in block["contexts"]:
        rows = []
        for ref in _members(block, context):
            relpath = f"{subdir}/{ref['sha256'][:12]}_{safe_name(ref['name'])}"
            target = input_dir / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            if write_once(target, Path(ref["path"]).read_bytes()) != ref["sha256"]:
                raise Refused(f"copy of {ref['name']} did not reproduce {ref['sha256']}")
            copied.append(target.as_posix())
            rows.append({"name": ref["name"], "file": relpath, "sha256": ref["sha256"], "role": ref["role"]})
        contexts[context] = rows
    doc = {"schema": PRESETS_SCHEMA, "domain": domain_id, "default_context": block.get("default_context"),
           "contexts": contexts}
    out = Path(block["ui_data"]) / f"{domain_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out, doc, mode="ascii")
    return {"presets": out.as_posix(), "input_dir": input_dir.as_posix(), "files": sorted(set(copied)), **doc}
