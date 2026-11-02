"""``jjv h3 inputs``: BUILD the ``jjv/h3-inputs/v1`` manifest that ``jjv h3 prepare --inputs`` reads.

Every sha256 in the manifest comes from an engine receipt or from hashing the file the receipt names; the
hand-written part is a small spec (``jjv/h3-spec/v1``) that holds only graph DATA: the template path, the graph
ports, the face roles in port order and the explicit widget values (``mouth``).  A spec key the builder does not
know (a hand-typed ``sha256``, ``legacy_voice`` ...) is refused.

Sources, per spec shot:

* anchor -- ``jjv images``: the CURRENT approval of the shot (stale-proof) and the ``jjv images native`` receipt
  made from that exact candidate with ``anchor_approved: true``; no approval or no native copy is refused.
  A ``carry`` shot (no ``anchor_shot``) with ``--carry-from DIR`` instead binds the ``carry`` sink output of the
  previous shot's ACCEPTED take in DIR (``publish.carry_output``: hash-bound, never extracted by hand);
* WAV -- ``jjv voice finalize``: the ``voice-bindings.json`` dialogue row of the logical shot (or one named split
  segment), then the same listen-approval proof ``h3 prepare`` runs (``E_LISTEN_APPROVAL``).  The manifest always
  binds ``voice_dir``; it never writes ``legacy_voice`` (that path is for episodes listed in the H3 routes data);
* faces -- the cast file through ``layout.cast`` (sha re-checked); each face is a role of the spec, mapped by
  the episode ``cast_roles`` / ``--map``; the shot's speaker and listener must be among them;
* anchor pack (user 31/10, ``--anchor-dir DIR`` -> ``DIR/<shot>/anchor-pack.json``): when the shot HAS a pack, EVERY image comes
  from it through ``pack_refs`` (library face/body, preset wardrobe, the pack storyboard as the AddGuide image; staged names from
  ``jjv video anchor-stage``); the cast file is never opened for that shot, ``faces`` is ``[]`` and the row carries ``refs`` +
  ``anchor_pack``.  A pack that is stale (``--shotlist`` context / sources), sha-drifted or unstaged is REFUSED, never replaced by
  the cast path.  No pack for a shot ⇒ REFUSED ``ANCHOR_PACK_MISSING``, unless ``legacy_cast_faces`` (``--legacy-cast-faces``):
  then the cast path above, every cast face must pass the library approval check of ``pack_refs`` (sha-bound), and the
  manifest provenance + summary record that the legacy path was used;
* shot list -- ``episode.files.shots`` or ``--shots`` (ingest's skeleton): unknown shots are refused.

Before anything is written, every row is run through ``prepare.build_shot`` in memory, so a manifest that
``h3 prepare`` would refuse is never produced; the summary carries the graph sha256 prepare will write.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_once
from ..images import approve as image_approve
from ..images.native import NATIVE_SCHEMA
from ..layout import cast as cast_mod
from ..core.paths import resolve_data_path
from ..layout.context import Context
from ..layout.plan import episode_shots
from ..voice import receipts as voice_receipts
from . import pack_refs
from . import prepare as prepare_mod
from . import publish as publish_mod

SPEC_SCHEMA = "jjv/h3-spec/v1"
ANCHOR_PACK_MISSING = "ANCHOR_PACK_MISSING"
BINDINGS_SCHEMA = "jjv/voice-bindings/v1"
GRAPH_KEYS = ("template", "anchor_ports", "wav_ports", "faces", "mouth", "editorial_node", "output_ports", "sinks",
              "drop_unfilled_refs")
SHOT_KEYS = ("shot", "anchor_shot", "wav_segment", *GRAPH_KEYS)
TOP_KEYS = ("schema", "episode_id", "comment", "defaults", "shots")


def _rel(path: Path, root: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _file(path: Path, sha: str, root: Path, ports: Any = None) -> dict:
    row = {"path": _rel(path, root), "sha256": sha}
    return {**row, "ports": ports} if ports is not None else row


def load_spec(ctx: Context, spec_path: Path) -> dict:
    spec = read_json(spec_path)
    if not isinstance(spec, dict) or spec.get("schema") != SPEC_SCHEMA:
        raise Refused(f"{Path(spec_path).name}: not a {SPEC_SCHEMA} document")
    if "legacy_voice" in spec:
        raise Refused("LEGACY_REFUSED: the manifest builder binds listen-approved WAVs (voice_dir) only")
    unknown = sorted(set(spec) - set(TOP_KEYS))
    if unknown:
        raise Refused(f"{Path(spec_path).name}: unknown top-level keys {unknown} (shas come from receipts)")
    if spec.get("episode_id") != ctx.episode_id:
        raise Refused(f"spec episode_id {spec.get('episode_id')!r} is not {ctx.episode_id!r}")
    defaults = spec.get("defaults") or {}
    if not isinstance(defaults, dict) or set(defaults) - set(GRAPH_KEYS):
        raise Refused(f"spec defaults may only hold {list(GRAPH_KEYS)}")
    shots = spec.get("shots")
    if not isinstance(shots, list) or not shots:
        raise Refused("spec needs a non-empty shots list")
    merged = []
    for row in shots:
        if not isinstance(row, dict) or set(row) - set(SHOT_KEYS):
            extra = sorted(set(row) - set(SHOT_KEYS)) if isinstance(row, dict) else row
            raise Refused(f"spec shot row may only hold {list(SHOT_KEYS)}; unknown {extra}")
        shot = prepare_mod.safe(row.get("shot"))
        item = {**copy.deepcopy(defaults), **copy.deepcopy(row)}
        item["mouth"] = {**(defaults.get("mouth") or {}), **(row.get("mouth") or {})}  # per-shot values win
        if not isinstance(item.get("drop_unfilled_refs", False), bool):
            raise Refused(f"{shot}: drop_unfilled_refs must be true or false")
        missing = [k for k in GRAPH_KEYS if k not in ("sinks", "faces", "drop_unfilled_refs") and not item.get(k)]  # faces: cast path only
        if missing:
            raise Refused(f"{shot}: spec has no {missing} (neither in defaults nor in the shot row)")
        merged.append(item)
    return {**spec, "shots": merged}


def approved_anchor(ctx: Context, images: Path, shot: str, kind: str | None) -> tuple[Path, str, dict]:
    """The native anchor made from the shot's CURRENT image approval: ``(path, sha256, provenance)``."""
    approval = image_approve.current_approval(images, shot)
    if approval is None:
        hint = (" (a carry shot's anchor is the previous accepted take's carry output: pass --carry-from)"
                if kind == "carry" else "")
        raise Refused(f"NO_IMAGE_APPROVAL: {shot} has no current `jjv images approve` record in {images}{hint}")
    if approval.get("episode_id") != ctx.episode_id:
        raise Refused(f"{shot}: the image approval belongs to episode {approval.get('episode_id')!r}")
    candidate = approval["candidate_sha256"]
    folder = Path(images) / shot / "native"
    rows = [(p, read_json(p)) for p in sorted(folder.glob("*.receipt.json"))] if folder.is_dir() else []
    hits = [(p, r) for p, r in rows if isinstance(r, dict) and r.get("schema") == NATIVE_SCHEMA
            and (r.get("source") or {}).get("sha256") == candidate]
    if len(hits) != 1:
        raise Refused(f"NO_NATIVE_ANCHOR: {shot}: {len(hits)} native receipts for approved candidate "
                      f"{candidate[:12]}; run `jjv images native --shot {shot} --sha {candidate[:12]}`")
    receipt_path, receipt = hits[0]
    if receipt.get("anchor_approved") is not True or receipt.get("episode_id") != ctx.episode_id:
        raise Refused(f"NO_NATIVE_ANCHOR: {shot}: {receipt_path.name} is a diagnostic (unapproved) copy")
    recorded = read_json(Path(receipt["approval"]))
    if recorded.get("candidate_sha256") != candidate:
        raise Refused(f"{shot}: native receipt names an approval of another candidate")
    path, sha = Path(receipt["native"]["path"]), receipt["native"]["sha256"]
    prepare_mod.require_hash(path, sha, f"{shot} native anchor")
    approval_file = Path(approval["path"])
    return path, sha, {"native_receipt": _file(receipt_path, sha256_file(receipt_path), ctx.root),
                       "image_approval": _file(approval_file, sha256_file(approval_file), ctx.root),
                       "candidate_sha256": candidate}


def carried_anchor(ctx: Context, carry_from: Path, listed: list[dict], row: dict) -> tuple[Path, str, dict]:
    """The carry sink output of the source shot's ACCEPTED take: ``(path, sha256, provenance)``."""
    source = (row.get("entry") or {}).get("from_shot")
    if source is None:
        names = [r.get("shot") for r in listed]
        position = names.index(row["shot"])
        source = names[position - 1] if position else None
    if source is None:
        raise Refused(f"{row['shot']}: a carry shot needs an earlier shot to carry from")
    found = publish_mod.carry_output(ctx, Path(carry_from), source)
    return Path(found["path"]), found["sha256"], {"carry_from": {"shot": source, "frame": found["frame"],
                                                                 "adopt": found["adopt"],
                                                                 "adopt_sha256": found["adopt_sha256"]}}


def approved_wav(ctx: Context, voice: Path, logical: str, segment: str | None) -> tuple[Path, str, dict]:
    """The voice-bindings WAV (or named split segment) of ``logical``, listen approval proven."""
    bindings = read_json(Path(voice) / voice_receipts.BINDINGS_FILE)
    if not isinstance(bindings, dict) or bindings.get("schema") != BINDINGS_SCHEMA \
            or bindings.get("episode_id") != ctx.episode_id:
        raise Refused(f"{voice}: voice-bindings.json is not a {BINDINGS_SCHEMA} document of {ctx.episode_id!r}")
    rows = [r for r in bindings.get("dialogue") or [] if r.get("id") == logical]
    if len(rows) != 1:
        raise Refused(f"NO_VOICE_BINDING: {logical}: {len(rows)} dialogue rows in voice-bindings.json")
    described, sha = rows[0]["audio"]["path"], rows[0]["audio"]["sha256"]
    if segment is not None:
        entries = read_json(Path(voice) / voice_receipts.FINALIZE_FILE).get("entries") or []
        entry = next((e for e in entries if e.get("request_id") == rows[0]["request_id"]), None)
        segs = [s for s in ((entry or {}).get("split") or {}).get("segments") or [] if s.get("label") == segment]
        if len(segs) != 1:
            raise Refused(f"{logical}: the finalize receipt has no split segment {segment!r}")
        described, sha = segs[0]["path"], segs[0]["sha256"]
    path = voice_receipts.resolve_described(described, episode_root=ctx.root, out=Path(voice))
    prepare_mod.require_hash(path, sha, f"{logical} WAV")
    proof = prepare_mod.voice_proof(ctx, Path(voice), {"sha256": sha}, logical)  # E_LISTEN_APPROVAL
    return path, sha, {"voice_request_id": proof["request_id"], "listen_approval": proof["approval"]["record_sha256"]}


def _faces(item: dict, cast: dict, mapping: dict, shot_row: dict) -> list[dict]:
    faces = item["faces"]
    if not isinstance(faces, list) or not all(isinstance(f, dict) and set(f) == {"role", "ports"} for f in faces):
        raise Refused(f"{item['shot']}: faces must be [{{role, ports}}] (the sha comes from the cast file)")
    roles = [f["role"] for f in faces]
    if len(set(roles)) != len(roles):
        raise Refused(f"{item['shot']}: a face role is listed twice")
    absent = [r for r in (shot_row.get("speaker"), shot_row.get("listener")) if r and r not in roles]
    if absent:
        raise Refused(f"FACE_MISSING: {item['shot']}: speaker/listener {absent} have no face reference")
    bound, unbound = cast_mod.bind(roles, cast, mapping)
    if unbound:
        raise Refused(f"NO_CAST_REFERENCE: {item['shot']}: no verified cast reference for {unbound}")
    by_role = {b["role"]: b for b in bound}
    return [{"role": f["role"], "character_id": by_role[f["role"]]["character_id"], "path": by_role[f["role"]]["path"],
             "sha256": by_role[f["role"]]["sha256"], "ports": f["ports"]} for f in faces]


def _cast_file(ctx: Context, given: Path | None) -> Path:
    if given is not None:
        return Path(given)
    name = (ctx.episode.get("files") or {}).get("cast")
    if not name:
        raise Refused("no --cast and episode.files.cast is not declared")
    return ctx.episode_file.parent / name


def _template(ctx: Context, shot: str, text: str) -> Path:
    path = resolve_data_path(Path(text) if Path(text).is_absolute() else ctx.root / text, ctx.machine)
    if not path.is_file():
        raise Refused(f"{shot}: template graph not found: {path}")
    return path


class _Cast:
    """Cast file + role map, opened only when a shot has NO anchor pack (a pack-bound shot never reads the cast file)."""

    def __init__(self, ctx: Context, given: Path | None, mapping: dict[str, str] | None) -> None:
        self.ctx, self.given, self.path, self.doc, self.rows = ctx, given, None, None, {}
        self.roles = {**(ctx.episode.get("cast_roles") or {}), **(mapping or {})}

    def load(self) -> dict:
        if self.doc is None:
            self.path = _cast_file(self.ctx, self.given)
            self.doc = cast_mod.load_cast(self.path)  # sha-checked; keeps only path/sha/roles
            raw = read_json(self.path)  # the approval evidence rows (prompt_id, receipt, approval_record, approval)
            self.rows = {r["character_id"]: r for r in raw["characters"]
                         if isinstance(r, dict) and isinstance(r.get("character_id"), str)}
        return self.doc


def _pack_file(anchor_dir: Path | None, shot: str) -> Path | None:
    path = Path(anchor_dir) / shot / pack_refs.PACK_FILE if anchor_dir else None
    return path if path is not None and path.is_file() else None


def _require_cast_face_approval(ctx: Context, shot: str, face: dict, row: dict | None) -> None:
    """A legacy cast face passes the SAME sha-bound library check as a pack face: ``pack_refs._require_ref_approval`` (reused)."""
    row = row or {}
    ref = {"role": "face", "name": face["character_id"], "sha256": face["sha256"], "prompt_id": row.get("prompt_id"),
           "receipt": row.get("receipt"), "approval_record": row.get("approval_record"), "approval": row.get("approval")}
    pack_refs._require_ref_approval(ctx, {"shot": shot}, ref)


def _cast_parts(ctx: Context, item: dict, listed: list[dict], listed_row: dict, kind: str | None, images: Path,
                carry_from: Path | None, cast: _Cast) -> tuple[dict, dict]:
    """Legacy path (``--legacy-cast-faces`` only, no anchor pack): the scene anchor from the image approval / carry; every
    cast face must carry a current library approval (sha-bound), else refused."""
    if kind == "carry" and carry_from is not None and not item.get("anchor_shot"):
        anchor, anchor_sha, anchor_prov = carried_anchor(ctx, carry_from, listed, listed_row)
    else:
        anchor, anchor_sha, anchor_prov = approved_anchor(ctx, images, item.get("anchor_shot") or item["shot"], kind)
    faces = _faces(item, cast.load(), cast.roles, listed_row)
    for face in faces:
        _require_cast_face_approval(ctx, item["shot"], face, cast.rows.get(face["character_id"]))
    parts = {"anchor": _file(anchor, anchor_sha, ctx.root, item["anchor_ports"]),
             # character_id travels with the face row: prepare re-reads it to find the cast approval (D1)
             "faces": [{**_file(Path(f["path"]), f["sha256"], ctx.root, f["ports"]), "character_id": f["character_id"]}
                       for f in faces]}
    return parts, {**anchor_prov, "face_roles": [f["role"] for f in faces]}


def _pack_parts(ctx: Context, item: dict, template: Path, pack_file: Path, shotlist: Path | None,
                allow_pending: bool) -> tuple[dict, dict]:
    """Pack path: EVERY image from the shot's anchor pack (verified, staged); the cast file is never opened."""
    bound = pack_refs.rows_from_pack(ctx, pack_file, read_json(template), anchor_ports=item["anchor_ports"], shotlist=shotlist,
                                     allow_pending_storyboard=allow_pending,
                                     drop_unfilled=bool(item.get("drop_unfilled_refs")))
    parts = {"anchor": bound["anchor"], "faces": [], "refs": bound["refs"], "anchor_pack": bound["anchor_pack"],
             "storyboard": bound["storyboard"], **({"dropped_refs": bound["dropped_refs"]} if bound["dropped_refs"] else {})}
    return parts, {"anchor_pack": bound["anchor_pack"], "ref_slots": [[r["slot"], r["role"], r["name"]] for r in bound["refs"]],
                   "overflow": bound["overflow"]}


def build(ctx: Context, spec_path: Path, *, images: Path, voice: Path, cast_file: Path | None = None,
          shots_file: Path | None = None, mapping: dict[str, str] | None = None, carry_from: Path | None = None,
          anchor_dir: Path | None = None, shotlist: Path | None = None,
          allow_pending_storyboard: bool = False, legacy_cast_faces: bool = False) -> tuple[dict, list[dict]]:
    """``(manifest, [{shot, graph_sha256, source}])``; nothing is written.  Every refusal happens before any write."""
    prepare_mod.domain_guard(ctx)
    spec = load_spec(ctx, spec_path)
    listed = (read_json(shots_file).get("shots") if shots_file else episode_shots(ctx)) or []
    by_shot = {r["shot"]: r for r in listed if isinstance(r, dict) and "shot" in r}
    cast = _Cast(ctx, cast_file, mapping)
    rows, provenance, warnings, sources, legacy_shots = [], {}, [], {}, []
    for item in spec["shots"]:
        shot = item["shot"]
        if shot not in by_shot:
            raise Refused(f"UNKNOWN_SHOT: {shot} is not in the shot list")
        listed_row = by_shot[shot]
        logical = listed_row.get("logical_shot") or shot
        kind = (listed_row.get("entry") or {}).get("kind")
        template = _template(ctx, shot, item["template"])
        pack_file = _pack_file(anchor_dir, shot)
        if pack_file is not None:
            parts, prov = _pack_parts(ctx, item, template, pack_file, shotlist, allow_pending_storyboard)
        else:
            where = str(anchor_dir) if anchor_dir else "--anchor-dir (not given)"
            if not legacy_cast_faces:
                raise Refused(f"{ANCHOR_PACK_MISSING}: {shot}: no {pack_refs.PACK_FILE} under {where}; refused — build the "
                              "anchor pack, or pass --legacy-cast-faces (faces then need a current library approval each)")
            warnings.append(f"{ANCHOR_PACK_MISSING}: {shot}: no {pack_refs.PACK_FILE} under {where}; faces come from the cast "
                            "file (LEGACY, --legacy-cast-faces) and the scene anchor from the image approval")
            legacy_shots.append(shot)
            parts, prov = _cast_parts(ctx, item, listed, listed_row, kind, images, carry_from, cast)
        wav, wav_sha, wav_prov = approved_wav(ctx, voice, logical, item.get("wav_segment"))
        row = {"shot": shot, "logical_shot": logical,
               "template": _file(template, sha256_file(template), ctx.root), "anchor": parts["anchor"],
               "wav": _file(wav, wav_sha, ctx.root, item["wav_ports"]), "faces": parts["faces"],
               **{k: parts[k] for k in ("refs", "anchor_pack", "storyboard", "dropped_refs") if k in parts},
               "mouth": item["mouth"], "editorial_node": item["editorial_node"],
               "output_ports": item["output_ports"], **({"sinks": item["sinks"]} if item.get("sinks") else {})}
        rows.append(row)
        provenance[shot] = {**prov, **wav_prov}
        sources[shot] = "anchor-pack" if pack_file is not None else "cast"
    manifest = {"schema": prepare_mod.INPUTS_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
                "voice_dir": _rel(voice, ctx.root), "shots": rows,
                "provenance": {"builder": "jjv h3 inputs",
                               "spec": _file(Path(spec_path), sha256_file(spec_path), ctx.root),
                               "cast": _file(cast.path, sha256_file(cast.path), ctx.root) if cast.path else None,
                               "images_dir": _rel(images, ctx.root),
                               "anchor_dir": _rel(Path(anchor_dir), ctx.root) if anchor_dir else None,
                               "shotlist": _file(Path(shotlist), sha256_file(shotlist), ctx.root) if shotlist else None,
                               "warnings": warnings, "shots": provenance,
                               "legacy_cast_faces": {"enabled": legacy_cast_faces, "shots": legacy_shots}}}
    if shots_file:
        manifest["provenance"]["shot_list"] = _file(Path(shots_file), sha256_file(shots_file), ctx.root)
    checks = []
    for row in rows:  # the exact prepare code path, in memory: a manifest prepare would refuse is never written
        _, receipt = prepare_mod.build_shot(ctx, copy.deepcopy(manifest), copy.deepcopy(row))
        checks.append({"shot": row["shot"], "graph_sha256": receipt["graph_sha256"], "source": sources[row["shot"]],
                       "legacy_cast_faces": row["shot"] in legacy_shots})
    return manifest, checks


def write_inputs(ctx: Context, spec_path: Path, out: Path, **sources: Any) -> dict:
    manifest, checks = build(ctx, spec_path, **sources)
    sha = write_json_once(Path(out), manifest, mode="ascii")
    legacy = manifest["provenance"]["legacy_cast_faces"]
    return {"inputs": str(Path(out)), "inputs_sha256": sha, "voice_dir": manifest["voice_dir"], "shots": checks,
            "warnings": list(manifest["provenance"]["warnings"]), "legacy_cast_faces": legacy["shots"],
            "next": f"jjv h3 prepare --episode {ctx.episode_id} --inputs {out} --out <H3 folder>"}
