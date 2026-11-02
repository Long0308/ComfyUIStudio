"""``jjv h3 prepare``: deterministic, offline preparation of one H3 motion graph per shot.

The input manifest (``jjv/h3-inputs/v1``) names, per shot, an editable API graph template, the hashed
anchor image, the hashed dialogue WAV, hashed face references, and the graph ports each one binds to.  The
engine does not re-implement H3 inference: the template stays the single editable truth and this module only
binds hashed media + explicit widget values into it.  Nothing is staged into ComfyUI and nothing is sent.

WAV rule (AGENTS.md, user 2026-10-27): a shot's dialogue WAV is the WAV named in its H3 preparation receipt
(``preparation.json -> wav.sha256``); trim once BEFORE H3, a post-H3 trim never replaces it.  The WAV must also
be a listen-approved voice-finalize WAV of this episode (``voice_dir``); a manifest with ``legacy_voice: true``
and no ``voice_dir`` (episodes produced before the voice stage existed) may instead bind to a prior
preparation receipt, whose ``wav.sha256`` then has to match exactly.

Anchor pack (user 31/10): a row carrying ``anchor_pack`` binds EVERY image from the shot's ``jjv/shot-anchor-pack/v1``
(``refs`` per ``ref_images.ref_image_N`` slot + the pack storyboard as the AddGuide image, staged names from ``jjv video
anchor-stage``); ``pack_refs.verify_row`` re-checks the pack (sha, creation rules, sources/shotlist freshness, staged names)
here and again in ``load_prepared``, so a stale or drifted pack is refused, never replaced by cast files.  Every staged ref
is recorded in ``preparation.json`` (``refs[] {path, sha256, slot, role, name, input_name}``, ``anchor_pack``, ``storyboard``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..comfy.guards import ClassPolicy, graph_class_types, static_refusals
from ..comfy.staging import require_hash
from ..core.errors import Refused
from ..core.io import canonical_json, canonical_sha256, read_json, sha256_file, write_json_once, write_once
from ..layout.context import REPO_ROOT, SKILL_ROOT, Context
from ..voice import receipts as voice_receipts
from ..voice.approval import check_listener, require_wav_approved
from . import pack_refs
from .qualification import domain_qualification, output_prefix, validate_media_ports

SCHEMA = "jjv/h3-preparation/v1"
INPUTS_SCHEMA = "jjv/h3-inputs/v1"
ROUTES = SKILL_ROOT / "recipes" / "h3" / "routes-v001.json"
PREPARATION_FILE = "preparation.json"
GRAPH_FILE = "graph.api.json"
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}")


def safe(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE.fullmatch(value):
        raise Refused(f"unsafe H3 identifier: {value!r}")
    return value


def domain_guard(ctx: Context) -> dict | None:
    """Domain routing and qualification are configured in the H3 route recipe."""
    return domain_qualification(ctx, ROUTES, REPO_ROOT)


def asset(root: Path, row: dict, label: str) -> dict:
    for key in ("path", "sha256"):
        if not isinstance(row.get(key), str):
            raise Refused(f"{label}: manifest row needs {key!r}")
    path = (Path(root) / row["path"]).resolve()
    require_hash(path, row["sha256"], label)
    return {**row, "path": str(path)}


def set_port(graph: dict, port: Any, value: Any) -> None:
    if not isinstance(port, (list, tuple)) or len(port) != 2:
        raise Refused(f"invalid H3 port {port!r}")
    node, key = str(port[0]), port[1]
    if node not in graph or key not in graph[node].get("inputs", {}):
        raise Refused(f"unknown H3 port {port!r}")
    graph[node]["inputs"][key] = value


def drop_ref_loaders(graph: dict, slots: list, bound: set[tuple]) -> list[str]:
    """Remove the template ref loaders the anchor pack has no image for (manifest ``dropped_refs``); returns the node ids.

    Each slot must name a LoadImage reached through its own ``ref_images.ref_image_N`` input and must NOT be bound; the
    consumer input is deleted and the loader node goes with it (a loader nobody reads would fail the unbound-loader check).
    Anything else is Refused, so a manifest cannot make prepare delete a node it was not built for."""
    loaders = pack_refs.ref_loaders(graph)
    removed = []
    for slot in sorted(slots):
        node = loaders.get(slot)
        if node is None:
            raise Refused(f"dropped ref slot {slot!r} is not a ref loader of the template")
        if (node, "image") in bound:
            raise Refused(f"dropped ref slot {slot!r} is bound to an image")
        for item in graph.values():
            inputs = item.get("inputs") or {}
            if slot in inputs and isinstance(inputs[slot], list) and str(inputs[slot][0]) == node:
                del inputs[slot]
        if any(isinstance(v, list) and v and str(v[0]) == node
               for other in graph.values() for v in (other.get("inputs") or {}).values()):
            raise Refused(f"loader {node} of {slot!r} is read by another input; not dropped")
        del graph[node]
        removed.append(node)
    return removed


def _is_h3_receipt(body: Any, ctx: Context, shot: str) -> bool:
    """A real H3 preparation receipt of THIS episode+shot: the engine schema, or the pre-engine receipt shape."""
    if not isinstance(body, dict) or not isinstance(body.get("wav"), dict) or not isinstance(body["wav"].get("sha256"), str):
        return False
    if body.get("status") != "PREPARED_NOT_SUBMITTED":
        return False
    if body.get("schema") == SCHEMA:
        return (body.get("episode_id"), body.get("shot")) == (ctx.episode_id, shot) \
            and isinstance(body.get("graph_sha256"), str)
    return (body.get("film_id"), body.get("shot_id")) == (ctx.episode_id, shot) \
        and isinstance(body.get("entry_type"), str) and isinstance(body.get("api"), dict) \
        and isinstance(body["api"].get("sha256"), str)


def _legacy_proof(ctx: Context, shot: str, prior: dict | None, wav: dict) -> dict:
    """legacy_voice only for episodes listed in data, and only against a real H3 preparation receipt."""
    if prior is None:
        raise Refused("legacy_voice needs a preparation_receipt on every shot (the receipt WAV is the proof)")
    if ctx.episode_id not in read_json(ROUTES).get("legacy_voice_episodes", []):
        raise Refused(f"legacy_voice is refused for episode {ctx.episode_id!r}: only episodes listed in "
                      "recipes/h3/routes-v001.json legacy_voice_episodes predate the voice stage; use voice_dir")
    if not _is_h3_receipt(read_json(prior["path"]), ctx, shot):
        raise Refused(f"{shot}: the legacy preparation_receipt is not an H3 preparation receipt of this "
                      "episode/shot (needs status PREPARED_NOT_SUBMITTED, wav.sha256 and graph/api sha256)")
    return {"mode": "legacy-preparation-receipt", "receipt_sha256": prior["sha256"], "wav_sha256": wav["sha256"]}


def voice_proof(ctx: Context, voice_dir: Path, wav: dict, logical: str) -> dict:
    """Approved + bound to this episode's dialogue line; a trimmed/other WAV is refused."""
    folder = Path(voice_dir)
    plan = read_json(folder / voice_receipts.PLAN_FILE)
    bindings = read_json(folder / voice_receipts.BINDINGS_FILE)
    if plan.get("episode_id") != ctx.episode_id or bindings.get("episode_id") != ctx.episode_id:
        raise Refused("voice evidence belongs to another episode")
    rows = [r for r in bindings.get("dialogue", []) if r["id"] == logical]
    if len(rows) != 1:
        raise Refused(f"{logical}: need exactly one dialogue voice binding")
    row = rows[0]
    proof = require_wav_approved(folder, plan, wav["sha256"], ctx.root)
    if proof["request_id"] != row["request_id"]:
        raise Refused("WAV belongs to another dialogue request")
    if row["audio"]["sha256"] != wav["sha256"]:  # only a split segment of THIS finalized line may differ
        entries = read_json(folder / voice_receipts.FINALIZE_FILE)["entries"]
        entry = next(e for e in entries if e["request_id"] == row["request_id"])
        segments = (entry.get("split") or {}).get("segments") or []
        if not any(s["sha256"] == wav["sha256"] for s in segments):
            raise Refused("WAV differs from the voice-bindings receipt WAV; post-H3 trims never replace it")
    check_listener(proof["approval"]["approved_by"])
    return proof


def selected(rows: list[dict], shots: list[str] | None) -> list[dict]:
    names = [safe(r["shot"]) for r in rows]
    if len(set(names)) != len(names):
        raise Refused("duplicate H3 shot identifiers")
    wanted = set(shots or names)
    if not wanted or wanted - set(names):
        raise Refused(f"unknown/empty H3 shot selection: {sorted(wanted - set(names))}")
    return [r for r in rows if r["shot"] in wanted]


def _bind_media(graph: dict, items: list[dict]) -> set[tuple]:
    bound: set[tuple] = set()
    for item in items:
        name = item.get("input_name") or f"h3-{item['sha256']}{Path(item['path']).suffix.lower()}"
        item["input_name"] = name
        if not item.get("ports"):
            raise Refused(f"asset {Path(item['path']).name} has no graph ports")
        for port in item["ports"]:
            key = (str(port[0]), port[1])
            if key in bound:
                raise Refused(f"duplicate media port {port}")
            bound.add(key)
            set_port(graph, port, name)
    return bound


def _identity_evidence(ctx: Context, faces: list, refs: list, shot: str) -> dict:
    """``identity_refs`` (tier per allow-listed ref, ``warning`` on qa_keep) for the preparation receipt; empty = no key."""
    from ..policy import identity_guard
    found = identity_guard.listed_report(getattr(ctx, "domain", None), [*faces, *refs])
    identity_guard.warn(found, where=f"h3 prepare {shot}")
    return {"identity_refs": found} if found else {}


def _media(ctx: Context, row: dict, shot: str) -> tuple[dict, list[dict], list[dict], dict | None]:
    """``(anchor, faces, refs, anchor_pack)``: a pack-bound row takes EVERY image from its anchor pack (re-verified), any
    other row binds the manifest's cast faces; only a pack may name the staged input (``input_name``)."""
    anchor = asset(ctx.root, row["anchor"], "anchor")
    faces = [asset(ctx.root, x, "face") for x in row.get("faces", [])]
    if row.get("anchor_pack"):
        pack_refs.verify_row(ctx, row)
        refs = [asset(ctx.root, x, "pack ref") for x in row.get("refs") or []]
        if faces or not refs:
            raise Refused(f"{shot}: a pack-bound shot binds every image from its anchor pack (no cast faces)")
        return anchor, [], refs, dict(row["anchor_pack"])
    if not faces:
        raise Refused(f"{shot}: explicit face references and mouth inputs are required")
    from ..policy import identity_guard
    identity_guard.check_refs(getattr(ctx, "domain", None), [{**face, "role": "face"} for face in faces],
                              where=f"h3 prepare {shot}")
    for item in (anchor, *faces):
        item.pop("input_name", None)
    return anchor, faces, [], None


def require_anchor_pack_or_approved_legacy(ctx: Context, document: dict, row: dict, faces: list[dict]) -> None:
    """A missing pack is legal only for the explicit, SHA approved cast path of h3 inputs."""
    if row.get("anchor_pack"):
        return
    shot = row["shot"]
    provenance = document.get("provenance") or {}
    legacy = provenance.get("legacy_cast_faces") or {}
    if legacy.get("enabled") is not True or shot not in (legacy.get("shots") or []):
        raise Refused(f"ANCHOR_PACK_MISSING: {shot}: no anchor pack and no explicit legacy_cast_faces approval")
    cast_ref = provenance.get("cast")
    if not isinstance(cast_ref, dict):
        raise Refused(f"ANCHOR_PACK_MISSING: {shot}: legacy cast approval evidence is missing")
    cast = read_json(asset(ctx.root, cast_ref, "legacy cast approval")["path"])
    source = (provenance.get("shots") or {}).get(shot) or {}
    if not isinstance(source, dict) or not (source.get("image_approval") or source.get("carry_from")):
        raise Refused(f"ANCHOR_PACK_MISSING: {shot}: legacy scene anchor has no approval/carry evidence")
    if source.get("image_approval"):
        asset(ctx.root, source["image_approval"], "legacy image approval")
        asset(ctx.root, source["native_receipt"], "legacy native anchor receipt")
        from . import inputs as inputs_mod
        images = Path(provenance.get("images_dir", ""))
        images = images if images.is_absolute() else ctx.root / images
        anchor_shot = Path(source["native_receipt"]["path"]).parent.parent.name
        native, sha, _ = inputs_mod.approved_anchor(ctx, images, anchor_shot, None)
        expected = asset(ctx.root, row["anchor"], "legacy anchor")
        if Path(expected["path"]) != native.resolve() or expected["sha256"] != sha:
            raise Refused(f"ANCHOR_PACK_MISSING: {shot}: legacy anchor differs from the current image approval")
    elif source.get("carry_from"):
        carry = source["carry_from"]
        prior = Path(carry["adopt"])
        require_hash(prior, carry["adopt_sha256"], "legacy carry adoption")
    by_id = {r.get("character_id"): r for r in cast.get("characters", []) if isinstance(r, dict)}
    if not faces:
        raise Refused(f"ANCHOR_PACK_MISSING: {shot}: legacy mode needs approved cast faces")
    for face in faces:
        identity = face.get("character_id")
        evidence = by_id.get(identity) or {}
        if not identity or not evidence:
            raise Refused(f"ANCHOR_PACK_MISSING: {shot}: cast has no approval row for {identity!r}")
        pack_refs._require_ref_approval(ctx, {"shot": shot}, {
            "role": "face", "name": identity, "sha256": face["sha256"],
            **{key: evidence.get(key) for key in ("prompt_id", "receipt", "approval_record", "approval")}})


def build_shot(ctx: Context, document: dict, row: dict) -> tuple[dict, dict]:
    qualification = domain_guard(ctx)
    shot = safe(row["shot"])
    template = asset(ctx.root, row["template"], "template")
    if qualification and template["sha256"] != qualification["template_sha256"]:
        raise Refused(f"H3 qualification template sha256 mismatch: {template['path']}")
    graph = read_json(template["path"])
    problems = static_refusals(graph_class_types(graph), ClassPolicy.from_domain(ctx.domain))
    if problems:
        raise Refused("; ".join(problems))
    anchor, faces, refs, pack_row = _media(ctx, row, shot)
    require_anchor_pack_or_approved_legacy(ctx, document, row, faces)
    wav = asset(ctx.root, row["wav"], "WAV")
    if not isinstance(row.get("mouth"), dict) or not row["mouth"]:
        raise Refused(f"{shot}: explicit face references and mouth inputs are required")
    prior = None
    if row.get("preparation_receipt"):
        prior = asset(ctx.root, row["preparation_receipt"], "prior preparation receipt")
        if read_json(prior["path"])["wav"]["sha256"] != wav["sha256"]:
            raise Refused("WAV differs from preparation.json -> wav.sha256; trim only before H3")
    logical = row.get("logical_shot", shot)
    if document.get("voice_dir"):
        voice_dir = str((ctx.root / document["voice_dir"]).resolve())
        proof = voice_proof(ctx, Path(voice_dir), wav, logical)
    elif document.get("legacy_voice") is True:
        voice_dir, proof = None, _legacy_proof(ctx, shot, prior, wav)
    else:
        raise Refused("manifest needs voice_dir (listen-approved WAVs) or an explicit legacy_voice: true")
    if qualification:
        validate_media_ports(graph, anchor, wav, [*faces, *refs])
    bound = _bind_media(graph, [anchor, wav, *faces, *refs])
    qualified_outputs = set()
    if qualification:
        for port in row.get("output_ports") or []:
            if not isinstance(port, (list, tuple)) or len(port) != 2:
                raise Refused(f"H3 qualification rejects output port {port!r}")
            key = (str(port[0]), port[1])
            if key in qualified_outputs:
                raise Refused(f"H3 qualification rejects duplicate output port {port!r}")
            qualified_outputs.add(key)
    dropped = drop_ref_loaders(graph, row["dropped_refs"], bound) if row.get("dropped_refs") else []
    for dotted, value in row["mouth"].items():
        if qualification and dotted not in qualification["allowed_override_ports"]:
            raise Refused(f"H3 qualification does not permit override of {dotted!r}")
        port = dotted.split(".", 1)
        if qualification and (port[0], port[-1]) in qualified_outputs:
            raise Refused(f"H3 qualification forbids mouth override of output port {dotted!r}")
        if (port[0], port[-1]) in bound:
            raise Refused("mouth inputs must not overwrite media bindings")
        set_port(graph, port, value)
    for node, item in graph.items():  # a template's stale scene/audio reference may not survive in any loader
        if item["class_type"] in ("LoadImage", "LoadAudio"):
            key = "image" if item["class_type"] == "LoadImage" else "audio"
            if (node, key) not in bound:
                raise Refused(f"unbound media loader {node}.{key}")
    sink = str(row.get("editorial_node", ""))
    if sink not in graph or not row.get("output_ports"):
        raise Refused("missing editorial output node/ports")
    content = canonical_sha256(graph, mode="ascii")
    for index, port in enumerate(row["output_ports"]):
        if (str(port[0]), port[1]) in bound:
            raise Refused("output port overwrites media")
        prefix = output_prefix(graph, port, qualification["output_prefix_root"]) if qualification else "h3"
        set_port(graph, port, f"{prefix}/{safe(ctx.episode_id)}/{shot}/{content}/{index}")
    digest = canonical_sha256(graph, mode="ascii")
    receipt = {"schema": SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id, "shot": shot,
               "logical_shot": logical, "status": "PREPARED_NOT_SUBMITTED", "anchor": anchor, "wav": wav,
               "faces": faces, "refs": refs, "anchor_pack": pack_row,
               **_identity_evidence(ctx, faces, refs, shot),
               "legacy_cast_evidence": ({"legacy_cast_faces": (document.get("provenance") or {}).get("legacy_cast_faces"),
                                        "cast": (document.get("provenance") or {}).get("cast"),
                                        # the images folder the load-time recheck reads the image approval from (D2)
                                        "images_dir": (document.get("provenance") or {}).get("images_dir"),
                                        "shots": {shot: ((document.get("provenance") or {}).get("shots") or {}).get(shot)}}
                                       if not pack_row else None),
               "storyboard": dict(row["storyboard"]) if pack_row and isinstance(row.get("storyboard"), dict) else None,
               "mouth": row["mouth"], "template": template, "prior_preparation": prior,
               "voice_dir": voice_dir, "voice_approval": proof, "graph_sha256": digest,
               "canonicalization": "ascii", "api": {"path": GRAPH_FILE, "sha256": digest},
               "editorial_node": sink, "sinks": {str(k): str(v) for k, v in (row.get("sinks") or {}).items()},
               "review_status": "pending"}
    if dropped:
        receipt["dropped_refs"] = {"slots": sorted(row["dropped_refs"]), "nodes": dropped}
    if qualification:
        receipt["qualification"] = qualification
    return graph, receipt


def prepare(ctx: Context, inputs: Path, out: Path, *, shots: list[str] | None = None) -> dict:
    """Write ``<out>/<shot>/graph.api.json`` + ``preparation.json`` (write-once; same inputs -> same bytes)."""
    domain_guard(ctx)
    document = read_json(inputs)
    if (document.get("schema"), document.get("episode_id"), document.get("domain")) != (
            INPUTS_SCHEMA, ctx.episode_id, ctx.domain_id):
        raise Refused("H3 input manifest schema/episode/domain mismatch")
    built = [build_shot(ctx, document, row) for row in selected(document["shots"], shots)]  # all refusals first
    results, warnings = [], []
    for graph, receipt in built:
        folder = Path(out) / receipt["shot"]
        write_once(folder / GRAPH_FILE, canonical_json(graph, mode="ascii"))
        sha = write_json_once(folder / PREPARATION_FILE, receipt, mode="ascii")
        results.append({"shot": receipt["shot"], "graph_sha256": receipt["graph_sha256"], "preparation_sha256": sha,
                        "folder": str(folder)})
        if not receipt.get("anchor_pack"):
            warnings.append(f"ANCHOR_PACK_MISSING: {receipt['shot']}: explicitly approved legacy cast faces were used")
    return {"episode_id": ctx.episode_id, "domain": ctx.domain_id, "shots": results, "warnings": warnings}


def load_prepared(ctx: Context, out: Path, *, shots: list[str] | None = None) -> list[tuple[Path, dict, dict]]:
    """Re-verify every prepared shot (hashes of graph and inputs, WAV rule, voice approval) and return
    ``[(folder, receipt, graph)]``.  Used by submit and adopt so a changed input is refused, not trusted."""
    qualification = domain_guard(ctx)
    out = Path(out)
    names = sorted(p.parent.name for p in out.glob(f"*/{PREPARATION_FILE}"))
    rows = [{"shot": n} for n in names]
    if not rows:
        raise Refused(f"no prepared shots under {out}; run 'jjv h3 prepare' first")
    result = []
    for row in selected(rows, shots):
        folder = out / row["shot"]
        receipt = read_json(folder / PREPARATION_FILE)
        if (receipt.get("schema"), receipt.get("episode_id"), receipt.get("domain")) != (
                SCHEMA, ctx.episode_id, ctx.domain_id):
            raise Refused(f"{folder.name}: preparation belongs to another episode/domain/schema")
        if receipt.get("qualification") != qualification:
            raise Refused(f"{folder.name}: H3 qualification changed after prepare")
        if qualification:
            template = receipt.get("template") or {}
            if template.get("sha256") != qualification["template_sha256"]:
                raise Refused(f"{folder.name}: H3 qualification template changed after prepare")
            require_hash(Path(template["path"]), template["sha256"], "qualified H3 template")
        require_hash(folder / GRAPH_FILE, receipt["graph_sha256"], "prepared graph")
        for item in [receipt["anchor"], receipt["wav"], *receipt["faces"], *(receipt.get("refs") or [])]:
            require_hash(Path(item["path"]), item["sha256"], "prepared input")
        if receipt.get("anchor_pack"):
            pack_refs.verify_row(ctx, receipt)  # pack sha, creation rules, freshness, staged names: refuse, never substitute
        else:
            require_anchor_pack_or_approved_legacy(
                ctx, {"provenance": receipt.get("legacy_cast_evidence") or {}}, receipt, receipt["faces"])
        prior = receipt.get("prior_preparation")
        if prior:
            require_hash(Path(prior["path"]), prior["sha256"], "prior preparation")
            if read_json(prior["path"])["wav"]["sha256"] != receipt["wav"]["sha256"]:
                raise Refused("receipt WAV mismatch: trim only before H3")
        if receipt.get("voice_dir"):
            proof = voice_proof(ctx, Path(receipt["voice_dir"]), receipt["wav"], receipt["logical_shot"])
        else:
            proof = _legacy_proof(ctx, receipt["shot"], prior, receipt["wav"])
        if proof != receipt["voice_approval"]:
            raise Refused("voice approval changed after prepare")
        result.append((folder, receipt, read_json(folder / GRAPH_FILE)))
    return result


__all__ = ["prepare", "load_prepared", "voice_proof", "sha256_file"]
