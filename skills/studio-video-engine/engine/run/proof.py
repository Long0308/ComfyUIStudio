"""Human proof for run gates: a decision counts only when a proof signed with an issuer key verifies.

HONEST LIMIT (SPEC-DAG-FIX section 5): this is a FILE-BASED token (HMAC-SHA256 over the canonical payload, key held
in a trust folder named by the environment variable ``JJV_TRUST_DIR``).  It is a SPEED BUMP against an agent that has
file access to that folder, NOT an unforgeable signature and NOT a security boundary: an orchestrator that can read
the key file can mint a proof.  What it does give: a typed name (``--by``), an ``--approve-gpu`` flag or a
``gpu-approved.json`` file no longer opens a gate by itself; the trust root is never taken from a CLI argument, a
recipe or the runs folder; a proof is bound to episode, domain, gate, verdict, subject hashes, scope and expiry.
A real boundary needs a user-held asymmetric key and a broker that owns dispatch (not built here).

Trust folder layout: ``issuers.json`` = ``{"issuers": {ID: {"principal": NAME, "key_hex": HEX}}, "revoked": [proof_id]}``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import Refused

SCHEMA = "jjv/run-human-proof/v1"
TRUST_ENV = "JJV_TRUST_DIR"
REQUIRED = ("schema", "proof_id", "issuer", "gate", "verdict", "episode_id", "domain", "subjects", "scope", "nonce",
            "issued_at", "expires_at", "mac")


@dataclass(frozen=True)
class Verified:
    principal: str
    proof_id: str
    scope: dict[str, Any]


def _mac(key_hex: str, payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "mac"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hmac.new(bytes.fromhex(key_hex), text, hashlib.sha256).hexdigest()


def sign(payload: dict[str, Any], key_hex: str) -> dict[str, Any]:
    """What a person's signer tool does: add the ``mac``.  The engine itself never calls this outside tests."""
    return {**payload, "schema": SCHEMA, "mac": _mac(key_hex, {**payload, "schema": SCHEMA})}


def _trust() -> dict[str, Any]:
    folder = os.environ.get(TRUST_ENV)
    if not folder:
        raise Refused(f"no trust root: set {TRUST_ENV} to the folder holding issuers.json (the root is never read from "
                      "a CLI argument, a recipe or the runs folder)")
    file = Path(folder) / "issuers.json"
    try:
        doc = json.loads(file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise Refused(f"trust root {file} is unreadable: {error}") from error
    if not isinstance(doc, dict) or not isinstance(doc.get("issuers"), dict):
        raise Refused(f"trust root {file} has no `issuers` object")
    return doc


def verify(proof: Any, *, gate: str, episode_id: str, domain: str, verdicts: tuple[str, ...] = ("accept",),
           subject: str | None = None, now: float | None = None) -> Verified:
    """Refuse unless ``proof`` is a current, issuer-signed decision for exactly this gate/episode/domain/subject."""
    if not isinstance(proof, dict) or any(k not in proof for k in REQUIRED) or proof.get("schema") != SCHEMA:
        raise Refused(f"human proof for {gate}: not a {SCHEMA} document with {', '.join(REQUIRED)}")
    trust = _trust()
    issuer = (trust["issuers"] or {}).get(proof["issuer"])
    if not isinstance(issuer, dict) or not issuer.get("key_hex") or not issuer.get("principal"):
        raise Refused(f"human proof {proof['proof_id']}: issuer {proof['issuer']!r} is not in the trust root")
    try:
        expected = _mac(issuer["key_hex"], proof)
    except ValueError as error:
        raise Refused(f"trust root key of {proof['issuer']!r} is not hex") from error
    if not hmac.compare_digest(expected, str(proof["mac"])):
        raise Refused(f"human proof {proof['proof_id']}: signature does not verify (payload or key changed)")
    if proof["proof_id"] in (trust.get("revoked") or []):
        raise Refused(f"human proof {proof['proof_id']} is revoked")
    if not isinstance(proof["expires_at"], (int, float)) or proof["expires_at"] < (now if now is not None else time.time()):
        raise Refused(f"human proof {proof['proof_id']} has expired")
    wrong = [k for k, v in (("gate", gate), ("episode_id", episode_id), ("domain", domain)) if proof[k] != v]
    if wrong:
        raise Refused(f"human proof {proof['proof_id']} is for another {', '.join(wrong)} (needed {gate}/{episode_id}/{domain})")
    if proof["verdict"] not in verdicts:
        raise Refused(f"human proof {proof['proof_id']} carries verdict {proof['verdict']!r}; this use needs {verdicts}")
    if subject is not None and subject not in (proof["subjects"] or []):
        raise Refused(f"human proof {proof['proof_id']} does not cover subject {subject[:12]}")
    return Verified(principal=str(issuer["principal"]), proof_id=str(proof["proof_id"]),
                    scope=proof["scope"] if isinstance(proof["scope"], dict) else {})


def load_file(path: str | Path) -> dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise Refused(f"proof file {path} is unreadable: {error}") from error
    if not isinstance(doc, dict):
        raise Refused(f"proof file {path} is not a JSON object")
    return doc
