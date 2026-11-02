"""Validate H3 domain qualification and preserve a qualified output namespace."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_bytes
from ..core.paths import require_inside
from ..layout.context import Context

_SHA256 = re.compile(r"[0-9a-f]{64}")
_PATH_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def domain_qualification(ctx: Context, routes_path: Path, repo_root: Path) -> dict | None:
    """Return a receipt binding for a guarded route, or None for a legacy allowed domain."""
    routes = read_json(routes_path)
    required = routes.get("qualification_required", {})
    if not isinstance(required, dict):
        raise Refused(f"{routes_path}: qualification_required must be an object")
    if ctx.domain_id not in required:
        if ctx.domain_id not in routes["allowed_domains"]:
            raise Refused(f"H3 is not qualified for domain {ctx.domain_id!r} (allowed: {routes['allowed_domains']})")
        return None

    # A domain in the legacy allow-list must still satisfy its explicit receipt policy.
    policy = required[ctx.domain_id]
    entry = policy.get("receipt") if isinstance(policy, dict) else None
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"].strip():
        raise Refused(f"H3 is not qualified for domain {ctx.domain_id!r}: qualification receipt path "
                      f"missing from {routes_path}")
    path = require_inside(repo_root / entry["path"], repo_root, "H3 qualification receipt")
    label = f"H3 is not qualified for domain {ctx.domain_id!r}: qualification receipt"
    if not path.is_file():
        raise Refused(f"{label} is missing: {path}")
    pin = entry.get("sha256")
    if not isinstance(pin, str) or not _SHA256.fullmatch(pin):
        raise Refused(f"{label} sha256 pin is missing or invalid for {path}")
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise Refused(f"{label} is unreadable: {path}: {error}") from error
    actual = sha256_bytes(payload)
    if actual != pin:
        raise Refused(f"{label} hash mismatch: expected {pin}, found {actual} ({path})")
    try:
        body = json.loads(payload.decode("utf-8-sig"), parse_constant=_reject_constant)
    except (UnicodeError, ValueError) as error:
        raise Refused(f"{label} is invalid: {path}: {error}") from error
    pilot = body.get("pilot") if isinstance(body, dict) else None
    if not isinstance(pilot, dict):
        raise Refused(f"{label} has no pilot evidence: {path}")
    overrides = pilot.get("allowed_override_ports")
    valid_overrides = (
        isinstance(overrides, list)
        and all(isinstance(item, str) and len(item.split(".")) == 2 and all(item.split("."))
                for item in overrides)
        and len(overrides) == len(set(overrides))
    )
    valid = (
        body.get("schema") == "jjv/h3-qualification/v1"
        and body.get("stage") == "h3"
        and body.get("domain") == ctx.domain_id
        and body.get("status") == "PASS"
        and pilot.get("executor") == "comfyui-local"
        and pilot.get("user_authorized") is True
        and isinstance(pilot.get("prompt_id"), str) and bool(pilot["prompt_id"].strip())
        and isinstance(pilot.get("graph_sha256"), str) and bool(_SHA256.fullmatch(pilot["graph_sha256"]))
        and isinstance(pilot.get("template_sha256"), str) and bool(_SHA256.fullmatch(pilot["template_sha256"]))
        and valid_overrides
    )
    if not valid:
        raise Refused(f"{label} is invalid or does not attest a passing authorised local H3 pilot: {path}")
    root = policy.get("output_prefix_root")
    if not isinstance(root, str) or not _PATH_PART.fullmatch(root):
        raise Refused(f"{label} has an invalid output prefix root in {routes_path}")
    return {"path": str(path), "sha256": pin, "template_sha256": pilot["template_sha256"],
            "allowed_override_ports": overrides, "output_prefix_root": root}


def validate_media_ports(graph: dict, anchor: dict, wav: dict, faces: list[dict]) -> None:
    """A media binding may change only the appropriate input of a template loader."""
    inputs = [(anchor, "LoadImage", "image"), (wav, "LoadAudio", "audio")]
    inputs.extend((face, "LoadImage", "image") for face in faces)
    for item, expected_class, expected_key in inputs:
        ports = item.get("ports")
        if not isinstance(ports, list) or not ports:
            raise Refused("H3 qualification requires media ports on each input")
        for port in ports:
            if not isinstance(port, (list, tuple)) or len(port) != 2:
                raise Refused(f"H3 qualification has an invalid media port {port!r}")
            node = graph.get(str(port[0]))
            if not isinstance(node, dict) or node.get("class_type") != expected_class or port[1] != expected_key:
                raise Refused(f"H3 qualification rejects media port {port!r}: expected {expected_class}.{expected_key}")


def output_prefix(graph: dict, port: Any, root: str) -> str:
    """Preserve the template's safe domain path; never move an output to another domain."""
    if not isinstance(port, (list, tuple)) or len(port) != 2:
        raise Refused(f"invalid H3 output prefix port {port!r}")
    node, key = str(port[0]), port[1]
    if key != "filename_prefix":
        raise Refused(f"H3 qualification rejects output port {port!r}: expected filename_prefix")
    item = graph.get(node)
    if not isinstance(item, dict) or key not in item.get("inputs", {}):
        raise Refused(f"unknown H3 output prefix port {port!r}")
    prefix = item["inputs"][key]
    parts = prefix.split("/") if isinstance(prefix, str) else []
    if len(parts) < 2 or parts[0] != root or not all(_PATH_PART.fullmatch(part) for part in parts):
        raise Refused(f"unsafe or foreign H3 output prefix {prefix!r}; expected {root}/...")
    return prefix
