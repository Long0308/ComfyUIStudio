"""Flat, hash-checked input staging for editable ComfyUI workflows."""
from __future__ import annotations

import copy
import re
from pathlib import Path

from ..core.errors import Refused
from ..core.io import sha256_file
from .staging import input_state, require_hash, stage_input

LOADERS = {"LoadImage": "image", "LoadImageMask": "image", "LoadAudio": "audio"}


def flat_input_name(domain: str, shot: str, digest: str, basename: str) -> str:
    """Deterministic ``<domain>__<shot>__<sha12>__<basename>`` (ASCII-safe).

    Domain/shot are explicit identifiers, never guessed from paths. Basename is
    taken after either slash style, unsafe characters become ``_``, and its stem
    is capped at 64 characters. Full SHA-256 is checked during staging; a sha12
    or sanitized-name collision with different bytes is refused, never replaced.
    """
    for value in (domain, shot):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise Refused(f"GUI_IDENTITY: invalid input namespace {value!r}")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise Refused("GUI_HASH: flat input name requires full SHA-256")
    leaf = re.sub(r"[^A-Za-z0-9_.-]", "_", str(basename).replace("\\", "/").rsplit("/", 1)[-1])
    if leaf in ("", ".", ".."):
        raise Refused("GUI_PATH: empty input basename")
    suffix = Path(leaf).suffix
    leaf = Path(leaf).stem[:64] + suffix
    return f"{domain}__{shot}__{digest[:12]}__{leaf}"


def stage_graph_inputs(api: dict, input_dir: Path | None, *, domain: str, shot: str,
                       expected_hashes: dict[str, str] | None = None) -> dict:
    """Copy all image/mask/audio inputs to input root; return an independent graph.

    Legacy GUI writers already have their API inputs under input_dir. Resolve
    both slash styles there, reject escapes, preflight every target, then use
    atomic no-overwrite staging (source/temp/destination SHA-256 checks).
    When preparation pins exist, callers supply expected_hashes keyed by the API
    input name: every loader must match its pin before any staging occurs.
    No HTTP, GPU work or modification of the receipt-bound API graph occurs.
    """
    graph = copy.deepcopy(api)
    pending = []
    for node in graph.values():
        key = LOADERS.get(node.get("class_type"))
        if key is None:
            continue
        if input_dir is None:
            raise Refused("GUI_INPUT: input directory required; no runnable GUI exported")
        root = Path(input_dir).resolve()
        value = node.get("inputs", {}).get(key)
        if not isinstance(value, str) or not value or ":" in value:
            raise Refused(f"GUI_INPUT: invalid {key} loader value {value!r}")
        relative = value.replace("\\", "/")
        if relative.startswith("/") or ".." in relative.split("/"):
            raise Refused(f"GUI_PATH: input escapes configured root: {value!r}")
        source = (root / relative).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise Refused(f"GUI_INPUT: missing or escaped input {value!r}")
        if expected_hashes is not None:
            if value not in expected_hashes:
                raise Refused(f"GUI_HASH: no preparation hash for {value!r}")
            digest = require_hash(source, expected_hashes[value], "GUI prepared input")
        else:
            digest = sha256_file(source)
        name = flat_input_name(domain, shot, digest, source.name)
        input_state(root, name, digest)
        pending.append((source, root, name, digest))
        node["inputs"][key] = name
    for source, root, name, digest in pending:
        stage_input(source, root, name, digest)
    return graph
