"""``jjv images adopt``: register an image that was made by hand in a Codex session (the engine never holds
ChatGPT tokens). The receipt records what is KNOWN: route, the model that was REQUESTED, ``resolved_model`` and
``runtime_id`` as null (the built-in tool exposes neither), the prompt sha256, the reference hashes and the
output sha256. Nothing here proves how the file was made; it proves which bytes were adopted and under what claim.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import sha256_file
from ..layout.cast import parse_pairs
from ..layout.context import Context, domain_policy, load_recipe, require_provider
from . import codex as codex_mod
from . import receipts
from .pool import accounts_from
from .common import register, shot_inputs

ADOPT_ROUTES = {"codex-builtin": "codex-adopt"}  # route name -> provider checked against the domain policy
DEFAULT_REQUESTED = "GPT Image Gen 2"
# A domain whose routes-recipe row says ``provenance_required: true`` must PROVE an adopted image came from a Codex
# account (N25, critic N12): a local ComfyUI image adopted with the hard-coded provider/model would be recorded as a
# GPT image. A domain without the flag keeps the old, trusting behaviour (images hand-run in Codex sessions, the
# operator's statement accepted since Q-2). The flag is DATA (recipes/images/routes-v002.json), not engine code.


def _needle(session: str, filename: str, sep: str) -> tuple[re.Pattern[bytes], int]:
    """Pattern for ``<session><sep><filename>`` as a WHOLE path (the byte after it is not a file-name character, so
    ``a/b.pn`` does not match ``a/b.png``), plus the longest match length. The session UUID is hex, so it is matched
    without regard to case on BOTH sides (N25d, critic N77: Windows keeps the on-disk case while the operator may type
    the UUID upper-case; a UUID that differs in any hex digit still fails). The separator and file name stay exact."""
    tail = (sep + filename).encode("utf-8")
    uuid = re.escape(session.lower().encode("utf-8"))
    return re.compile(rb"(?i:" + uuid + rb")" + re.escape(tail) + rb"[^A-Za-z0-9._-]"), len(session) + len(tail) + 1


def _mentions(path: Path, pattern: re.Pattern[bytes], keep: int) -> bool:
    """True if the rollout text (plain ``.jsonl`` or ``.jsonl.zst``) matches ``pattern`` from ``_needle``; ``keep`` bytes
    of the previous chunk are kept so a path split across two reads is still seen. Only the needle is searched for;
    nothing else is read into a result, printed or stored. Unreadable => False."""
    try:
        if path.name.endswith(".zst"):
            from compression import zstd  # Python 3.14+; absent => the rollout cannot be read => not proven
            handle = zstd.open(path, "rb")
        else:
            handle = open(path, "rb")
        with handle as fh:
            tail = b""
            while chunk := fh.read(1 << 20):
                buf = tail + chunk
                if pattern.search(buf):
                    return True
                tail = buf[-keep:]
            return bool(pattern.search(tail + b"\n"))  # end of file counts as a boundary
    except (OSError, ImportError, ValueError, RuntimeError):
        return False


SESSION_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
ROLLOUT_NAME = re.compile(r"rollout-.+-(?P<session>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.jsonl(\.zst)?")


def find_rollout(home: Path, session: str, filename: str) -> Path | None:
    """The rollout of ``session`` under ``<home>/sessions/**`` that names ``<session>/<filename>``, else None (N25c-exact).

    ``session`` must be a UUID; the rollout file name must be exactly ``rollout-<stamp>-<session>.jsonl[.zst]`` (the real
    Codex form, e.g. ``rollout-2026-10-30T18-52-19-01a18ca7-55a1-7a12-b98d-c2a4436c70b5.jsonl``; no substring or glob
    match; the session text is never put in a glob); the needle is ``<session>/<file>`` (either slash, or the ``\\\\`` a
    JSON ``savedPath`` carries), so a bare or partial file name in another session's rollout proves nothing. The UUID is
    compared case-insensitively in both the file name and the text (N25d); the file name is exact."""
    root = home / "sessions"
    if not root.is_dir() or not session or not SESSION_UUID.fullmatch(session) or not filename:
        return None
    wanted = session.lower()
    needles = [_needle(wanted, filename, sep) for sep in ("/", "\\", "\\\\")]
    for cand in sorted(root.rglob("rollout-*")):
        match = ROLLOUT_NAME.fullmatch(cand.name)
        if not (cand.is_file() and match and match.group("session").lower() == wanted):
            continue
        if any(_mentions(cand, pattern, keep) for pattern, keep in needles):
            return cand
    return None


def require_provenance(ctx: Context, requested_model: str | None, source_path: str | None, file: Path) -> dict[str, str]:
    """Refused unless ``--requested-model`` is given and ``--source-path`` is an EXISTING file that, with every link
    resolved, lies under ``<codex_home>/generated_images`` of an account in machine.json (``images.codex_accounts``) and
    has the same sha256 as ``--file`` (the file may be a copy, the BYTES must be the same). N25c: the source must be
    exactly ``<codex_home>/generated_images/<session>/<file>``, have ``st_nlink == 1`` (no hardlink from elsewhere) and a
    rollout of ``<session>`` under ``<codex_home>/sessions/**`` must name the file. Returns sha256/session/rollout."""
    if not (requested_model or "").strip():
        raise Refused(f"domain {ctx.domain_id} needs --requested-model for `images adopt` (no default is assumed)")
    if not (source_path or "").strip():
        raise Refused(f"domain {ctx.domain_id} needs --source-path for `images adopt`: the generated_images path of a codex "
                      "account in machine.json; an image from another route (ComfyUI) is not adopted as GPT")
    homes = [a.codex_home for a in accounts_from(ctx.machine, None)]
    if not homes:
        raise Refused(f"domain {ctx.domain_id}: machine.images.codex_accounts lists no codex account, so --source-path "
                      "cannot be proven")
    folder = load_recipe(codex_mod.RECIPE_NAME, codex_mod.RECIPE_SCHEMA)[0]["generated_images_dir"]
    named = Path(os.path.normpath(os.path.abspath(source_path)))
    if not any(named.is_relative_to(Path(os.path.normpath(os.path.abspath(h / folder)))) and
               named != Path(os.path.normpath(os.path.abspath(h / folder))) for h in homes):
        raise Refused(f"--source-path {source_path} is not under <codex_home>/{folder} of any machine.json codex account")
    try:
        real = Path(source_path).resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise Refused(f"--source-path {source_path} does not exist: nothing proves where the image came from "
                      f"(it must be the file under <codex_home>/{folder})") from None
    if not real.is_file():
        raise Refused(f"--source-path {source_path} is not a file")
    roots = []
    for home in homes:
        try:
            roots.append((home / folder).resolve(strict=True))
        except (FileNotFoundError, OSError):
            continue
    if not any(real.is_relative_to(root) for root in roots):
        raise Refused(f"--source-path {source_path} resolves to {real}, outside <codex_home>/{folder} of every machine.json "
                      "codex account (a link into another folder is not a Codex image)")
    if not Path(file).is_file():
        raise Refused(f"--file not found: {file}")
    owner = next((r for r in roots if real.is_relative_to(r)), None)
    parts = real.relative_to(owner).parts if owner else ()
    if len(parts) != 2:
        raise Refused(f"--source-path {source_path} must be <codex_home>/{folder}/<session>/<file>, got depth {len(parts)}")
    if real.stat().st_nlink > 1:
        raise Refused(f"--source-path {source_path} has {real.stat().st_nlink} hard links: a Codex image has exactly one "
                      "(a link made from another folder, e.g. ComfyUI output, is not proof)")
    session = parts[0]
    rollout = find_rollout(owner.parent, session, parts[1])
    if rollout is None:
        raise Refused(f"no rollout of session {session} under <codex_home>/sessions names {parts[1]}: the file is not tied "
                      "to a Codex session")
    source_sha, file_sha = sha256_file(real), sha256_file(Path(file))
    if source_sha != file_sha:
        raise Refused(f"--source-path sha256 {source_sha} != --file sha256 {file_sha}: the adopted bytes are not the Codex image")
    return {"sha256": source_sha, "session": session, "rollout": rollout.as_posix()}


def adopt(ctx: Context, out: Path, shot: str, file: Path, *, route: str, prompt_file: Path,
          requested_model: str | None, refs: list[str], refs_from_plan: bool, source_path: str | None,
          tool_evidence: str | None) -> dict[str, Any]:
    if route not in ADOPT_ROUTES:
        raise Refused(f"--route must be one of {sorted(ADOPT_ROUTES)}, got {route!r}")
    require_provider(ctx, ADOPT_ROUTES[route])
    file, prompt_file = Path(file), Path(prompt_file)
    source_sha256 = source_session = source_rollout = None
    verified_file_sha256 = None
    if domain_policy(ctx).get("provenance_required"):
        proof = require_provenance(ctx, requested_model, source_path, file)
        source_sha256, source_session, source_rollout = proof["sha256"], proof["session"], proof["rollout"]
        verified_file_sha256 = proof["sha256"]
    elif source_path and Path(source_path).is_file():
        source_sha256 = sha256_file(Path(source_path))  # trusting domain: recorded, never enforced
    inputs = shot_inputs(out, shot)
    if not prompt_file.is_file():
        raise Refused(f"--prompt-file not found: {prompt_file}")
    pairs = parse_pairs(refs, "--ref")
    listed = [receipts.file_ref(path, role) for role, path in pairs.items()]
    if refs_from_plan:
        listed = [inputs["guide"], *inputs["refs"], *listed]
    if not listed:
        raise Refused("an adopted image must name the reference images it was made from: pass --ref ROLE=PATH "
                      "(repeatable) or --refs-from-plan; the receipt records their hashes")
    body = {"route": route, "provider": ADOPT_ROUTES[route], "requested_model": requested_model or DEFAULT_REQUESTED,
            "resolved_model": None, "runtime_id": None, "prompt_id": None,
            "prompt": {"file": prompt_file.resolve().as_posix(), "sha256": sha256_file(prompt_file)},
            "prompt_sha256": sha256_file(prompt_file), "ref_hashes": listed, "source_path": source_path,
            "source_sha256": source_sha256, "source_session": source_session, "source_rollout": source_rollout,
            "tool_evidence": tool_evidence or "adopted from a hand-run Codex session; the tool exposes no model/runtime id",
            "status_note": "adopted image: provenance is the operator's statement, bytes are hash-bound"}
    return register(ctx, out, shot, file, inputs, body, expected_sha256=verified_file_sha256)
