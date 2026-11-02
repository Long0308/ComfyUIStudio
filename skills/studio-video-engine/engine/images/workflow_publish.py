"""Publish provider image results as editable ComfyUI review workflows.

Provider routes (``codex-exec``, ``openrouter``, ``codex-adopt`` and the local route)
do not run inside ComfyUI, but every accepted PNG still needs a workflow the user can
open and inspect.  This module writes a small display-only GUI (``Note`` plus
``LoadImage``), stages the exact PNG into the configured ComfyUI input folder, and
adds the workflow to the episode manifest.

The manifest entry follows the shape used by the episode workflow-index tooling:
path, sha256, kind, status, source evidence and the actual result pin.  Workflow
files are write-once and always receive a new ``vNNN`` suffix.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

from ..comfy.gui_inputs import flat_input_name
from ..comfy.settings import settings_from_machine
from ..comfy.staging import input_state, stage_input
from ..core.errors import Refused
from ..core.io import pretty_json, read_json, sha256_bytes, sha256_file, write_atomic, write_once
from ..layout.context import Context
from .gui import attach_image_result
from .workflow_note import (  # noqa: F401  (WORKFLOW_SCHEMA re-exported)
    WORKFLOW_SCHEMA, _UUID, _account_label, _base_gui, _codex_session, _note_node, _note_text, _prompt_text, _redact,
    _reference_hashes, _relative, _slug)
from .workflow_manifest import (  # noqa: F401  (re-exported for existing callers and tests)
    OWN_MANIFEST_SCHEMAS,
    _DERIVED_TOP_KEYS,
    _append_only_manifest_text,
    _entries_span,
    _manifest_update_bytes,
    _set_top_value,
    _splice_entries,
    _top_indent,
)

WORKFLOW_DIR = "03_STORYBOARD_IMAGES"
MANIFEST_RELATIVE = Path("workflows") / "WORKFLOW-MANIFEST.json"
MANIFEST_ENTRY_SCHEMA = "jjv/workflow-entry/v1"

# Set only by the CLI (``--allow-foreign-manifest``) for the duration of one verb.
_ALLOW_FOREIGN: ContextVar[bool] = ContextVar("allow_foreign_manifest", default=False)


@contextmanager
def allow_foreign_manifest(enabled: bool) -> Iterator[None]:
    """Let publication append to a manifest whose schema this module did not write."""
    token = _ALLOW_FOREIGN.set(bool(enabled))
    try:
        yield
    finally:
        _ALLOW_FOREIGN.reset(token)


def _manifest_path(episode_root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    workflows = Path(episode_root) / "workflows"
    exact = workflows / MANIFEST_RELATIVE.name
    if exact.is_file():
        return exact
    candidates = sorted(workflows.glob("WORKFLOW-MANIFEST*.json")) if workflows.is_dir() else []
    return candidates[0] if len(candidates) == 1 else exact


def _new_manifest(ctx: Context, episode_root: Path) -> dict[str, Any]:
    return {
        "schema": "jjv/workflow-manifest/v1",
        "episode_id": ctx.episode_id,
        "generated_by": "engine/images/workflow_publish.py",
        "roots": {"episode": str(episode_root.resolve())},
        "kinds": {
            "review": "Editable ComfyUI GUI with a result-pinning LoadImage node",
            "gui": "Editable ComfyUI GUI",
            "api": "ComfyUI API graph",
            "note": "Workflow note",
        },
        "entries": [],
    }


def _load_manifest(ctx: Context, episode_root: Path, explicit: Path | None,
                   *, allow_foreign: bool) -> tuple[Path, dict[str, Any]]:
    path = _manifest_path(episode_root, explicit)
    if not path.is_file():
        return path, _new_manifest(ctx, episode_root)
    manifest = read_json(path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("entries"), list):
        raise Refused(f"{path} is not a workflow manifest with an entries list")
    schema = manifest.get("schema")
    if schema not in OWN_MANIFEST_SCHEMAS and not allow_foreign:
        raise Refused(
            f"{path} has schema {schema!r}, which this publisher did not write; refusing to append to it. "
            "Re-run with --allow-foreign-manifest to append (existing entries stay byte-identical)."
        )
    return path, manifest


def _existing_publication(manifest: dict[str, Any], key: str, episode_root: Path) -> dict[str, Any] | None:
    for entry in reversed(manifest["entries"]):
        if entry.get("publication_key") != key:
            continue
        path = Path(episode_root) / entry.get("path", "")
        if path.is_file() and sha256_file(path) == entry.get("sha256"):
            return {
                "workflow": path.resolve().as_posix(),
                "workflow_sha256": entry["sha256"],
                "manifest": None,
                "manifest_entry": entry,
                "input_file": entry.get("comfyui_input"),
                "reused": True,
            }
    return None


def _next_workflow(folder: Path, stem: str) -> Path:
    """Next free ``vNNN`` path for ``stem``. Pure: creates nothing, not even the folder."""
    for number in range(1, 10000):
        candidate = folder / f"{stem}-v{number:03d}.workflow.json"
        if not candidate.exists():
            return candidate
    raise Refused(f"no free workflow version below {folder} for {stem}")


def _publish(ctx: Context, **kw: Any) -> dict[str, Any]:
    """One publish at a time per episode (N25): parallel codex lanes on one shot raced on the next review-vNNN name and
    on the manifest read-modify-write (a lost entry). The lock is an OS-level lock (released if the process dies) kept outside the episode tree."""
    from .lease import side_lock_path
    from .pool import locked

    root = Path(kw["episode_root"]) if kw.get("episode_root") is not None else Path(ctx.root)
    with locked(side_lock_path(root, "publish"), timeout_seconds=120.0, what="images review-publish lock"):
        return _publish_locked(ctx, **kw)


def _publish_locked(ctx: Context, *, shot: str, receipt: dict[str, Any], stage: str, route: str,
                    output_sha256: str, source_path: Path, source_receipt: dict[str, Any] | None,
                    episode_root: Path | None, comfy_input_dir: Path | None,
                    manifest_path: Path | None) -> dict[str, Any]:
    root = Path(episode_root) if episode_root is not None else Path(ctx.root)
    input_dir = Path(comfy_input_dir) if comfy_input_dir is not None else settings_from_machine(ctx.machine).input_dir
    manifest_file, manifest = _load_manifest(ctx, root, manifest_path, allow_foreign=_ALLOW_FOREIGN.get())
    provenance = source_receipt or receipt
    key = f"flat-v1:{ctx.domain_id}:{stage}:{shot}:{route}:{output_sha256}"
    if source_receipt is not None:
        key += ":" + str((source_receipt.get("output") or {}).get("sha256"))
    existing = _existing_publication(manifest, key, root)
    if existing is not None:
        stage_input(source_path, input_dir, existing["input_file"], output_sha256)
        existing["manifest"] = manifest_file.resolve().as_posix()
        return existing

    input_name = flat_input_name(ctx.domain_id, shot, output_sha256, source_path.name)
    input_state(input_dir, input_name, output_sha256)  # refuses a different file under this name; writes nothing
    note = _note_text(receipt, stage=stage, input_name=input_name, output_sha256=output_sha256,
                      route=route, source_receipt=source_receipt)
    metadata = {
        "stage": stage,
        "shot": shot,
        "route": route,
        "account_label": _account_label(provenance),
        "codex_session_id": _codex_session(provenance),
        "prompt_sha256": provenance.get("prompt_sha256"),
        "result_sha256": output_sha256,
        "input_file": input_name,
        "reference_hashes": _reference_hashes(provenance),
        "publication_key": key,
    }
    base = _base_gui(title=f"{shot} {route} review", note=note, metadata=metadata)
    gui = attach_image_result(
        base,
        input_name=input_name,
        status="candidate",
        prompt_id=_codex_session(provenance) or provenance.get("prompt_id") or "adopted",
        image_sha256=output_sha256,
    )
    gui["extra"]["jjv"] = {"schema": WORKFLOW_SCHEMA, **metadata}

    workflow_dir = root / WORKFLOW_DIR
    stem = f"{_slug(shot)}-{_slug(route)}-{'native-' if source_receipt is not None else ''}review"
    workflow = _next_workflow(workflow_dir, stem)
    payload = pretty_json(gui, mode="ascii")
    digest = sha256_bytes(payload)
    entry = {
        "schema": MANIFEST_ENTRY_SCHEMA,
        "stage": "03_storyboard_images",
        "path": _relative(workflow, root),
        "root": "episode",
        "sha256": digest,
        "bytes": len(payload),
        "kind": "review",
        "status": "candidate",
        "status_basis": f"auto-published after images {stage}; provider bytes are hash-bound",
        "execution_state": "rendered" if provenance.get("prompt_id") else "adopted",
        "source_prompt_id": provenance.get("prompt_id"),
        "source_receipt": _relative(Path(provenance["receipt_path"]), root) if provenance.get("receipt_path") else None,
        "editable_gui": _relative(workflow, root),
        "shows": f"LoadImage -> input/{input_name}",
        "result_sha256": output_sha256,
        "result_pins": [{"node_type": "LoadImage", "input_file": input_name, "input_exists": True}],
        "comfyui_input": input_name,
        "account_label": _account_label(provenance),
        "codex_session_id": _codex_session(provenance),
        "prompt_sha256": provenance.get("prompt_sha256"),
        "reference_hashes": _reference_hashes(provenance),
        "publication_key": key,
    }
    # All refusal checks are decided above this line; nothing has been written yet.
    manifest_bytes = _manifest_update_bytes(ctx, manifest_file, manifest, entry, root)
    stage_input(source_path, input_dir, input_name, output_sha256)
    if write_once(workflow, payload) != digest:
        raise Refused(f"workflow write did not produce the planned bytes: {workflow}")
    if manifest_bytes is not None:
        write_atomic(manifest_file, manifest_bytes)
    return {
        "workflow": workflow.resolve().as_posix(),
        "workflow_sha256": digest,
        "manifest": manifest_file.resolve().as_posix(),
        "manifest_entry": entry,
        "input_file": input_name,
        "reused": False,
    }


def publish_candidate(ctx: Context, shot: str, receipt: dict[str, Any], *,
                      episode_root: Path | None = None, comfy_input_dir: Path | None = None,
                      manifest_path: Path | None = None) -> dict[str, Any]:
    """Publish a registered provider candidate through a review-only LoadImage workflow."""
    output = receipt.get("output") or {}
    output_sha = output.get("sha256")
    if not isinstance(output_sha, str) or len(output_sha) != 64 or not output.get("path"):
        raise Refused("candidate receipt has no hash-bound output")
    source = Path(output["path"])
    if not source.is_file() or sha256_file(source) != output_sha:
        raise Refused(f"candidate image no longer matches its receipt: {source}")
    return _publish(
        ctx,
        shot=shot,
        receipt=receipt,
        stage="candidate",
        route=str(receipt.get("route") or receipt.get("provider") or "provider"),
        output_sha256=output_sha,
        source_path=source,
        source_receipt=None,
        episode_root=episode_root,
        comfy_input_dir=comfy_input_dir,
        manifest_path=manifest_path,
    )


def publish_native(ctx: Context, shot: str, receipt: dict[str, Any], source_receipt: dict[str, Any], *,
                   episode_root: Path | None = None, comfy_input_dir: Path | None = None,
                   manifest_path: Path | None = None) -> dict[str, Any]:
    """Publish the 864x480 H3 anchor while retaining the source candidate's provenance."""
    native = receipt.get("native") or {}
    output_sha = native.get("sha256")
    if not isinstance(output_sha, str) or len(output_sha) != 64 or not native.get("path"):
        raise Refused("native receipt has no hash-bound output")
    source = Path(native["path"])
    if not source.is_file() or sha256_file(source) != output_sha:
        raise Refused(f"native image no longer matches its receipt: {source}")
    return _publish(
        ctx,
        shot=shot,
        receipt=receipt,
        stage="native",
        route=str(source_receipt.get("route") or source_receipt.get("provider") or "provider"),
        output_sha256=output_sha,
        source_path=source,
        source_receipt=source_receipt,
        episode_root=episode_root,
        comfy_input_dir=comfy_input_dir,
        manifest_path=manifest_path,
    )
