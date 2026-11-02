"""``jjv h3 publish-shots``: write the production shot list (``jjv/shots/v1``) from ACCEPTED H3 takes only.

Source of every shot row (nothing is hand-typed):

* ``shot``, ``logical_shot``, ``speaker``, ``listener``, ``entry.kind`` -- the shot list (ingest's skeleton,
  ``episode.files.shots`` or ``--shots``); every listed shot is REQUIRED;
* ``clip`` -- the take :func:`accept.accepted_takes` returns (picked, file-verified), cross-checked against the
  shot's ``adopt.json`` and ``comfy/job.json`` (same prompt, same prepared graph, editorial node output);
  ``frames`` is measured with ffprobe on that file;
* ``wav_binding`` -- the shot's ``preparation.json`` (re-verified by ``prepare.load_prepared``): the receipt WAV
  is the conditioning WAV; ``offset_s`` is 0.0 because prepare binds the whole WAV to the graph;
* ``receipt_dir`` -- the shot's H3 folder;
* carry ``entry.from_shot`` / ``frame`` -- the previous shot's accepted take must carry a ``carry`` sink output
  (``sinks.carry`` of its manifest row, e.g. a ``SaveImage`` of the last used frame) whose sha256 equals THIS
  shot's prepared anchor; the frame index is read from the hash-bound prepared graph (``ImageFromBatch``
  ``batch_index`` feeding the carry sink).  :func:`carry_output` is the same proof ``jjv h3 inputs --carry-from``
  uses to bind that frame as the anchor.

Named gaps refuse the whole publication (nothing is written): ``NOT_PREPARED``, ``NO_ACCEPTED_TAKE``,
``TAKE_RECEIPTS_DISAGREE``, ``NO_CARRY_OUTPUT``, ``CARRY_FRAME_INDEX_UNPROVEN``, ``CARRY_ANCHOR_UNBOUND``,
``CARRY_FRAME_OUTSIDE_CLIP``, ``SCHEMA``.  ``MOUTH_BOXES_NOT_DERIVABLE`` is reported, never papered over, but ONLY when
the episode names ``files.mouth_boxes`` (then the boxes are expected and no engine receipt carries per-frame
mouth-box tracks, so no mouth-boxes file is written).  An episode that names none expects none (M8b-e2,
decision c): ``unmet`` is then empty.

Output: ``shots-h3-vNNN.json`` + ``shots-h3-vNNN.publication.json`` (write-once, all-or-nothing as a pair, next
free version; identical content reuses the existing version).  Provenance: the pick's acceptance record pins
prompt, graph and the ``adopt.json`` sha256; current receipts that no longer say exactly that are a gap.  ``episode.files.shots`` is never rewritten.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Callable

from ..config.schema import validate
from ..core.errors import Refused
from ..core.io import pretty_json, read_json, sha256_bytes, sha256_file, write_once
from ..layout.context import SKILL_ROOT, Context, rel
from ..layout.plan import episode_shots
from ..media.probe import probe_video
from . import accept as accept_mod
from .adopt import ADOPT_FILE
from .ledger import ledger_path
from .prepare import PREPARATION_FILE, load_prepared, safe
from .submit import COMFY_DIR

SHOTS_SCHEMA = "jjv/shots/v1"
PUBLICATION_SCHEMA = "jjv/h3-shots-publication/v1"
SCHEMA_FILE = SKILL_ROOT / "schemas" / "shots.schema.json"
CARRY_ROLE = "carry"
STEM = "shots-h3"
MOUTH_GAP = {"code": "MOUTH_BOXES_NOT_DERIVABLE", "file": "mouth-boxes",
             "why": "no H3 receipt or adopted output carries per-frame speaker/listener mouth-box tracks; "
                    "a tracker sink or a measured review receipt is needed before mouth-boxes can be published"}


class Gap(Exception):
    """One named, unmet requirement of one shot."""

    def __init__(self, code: str, shot: str, why: str) -> None:
        super().__init__(f"{code}: {shot}: {why}")
        self.row = {"code": code, "shot": shot, "why": why}


def _expects_mouth_boxes(ctx: Context) -> bool:
    """True when the episode names ``files.mouth_boxes`` (the loader's own rule: unnamed means none expected)."""
    return bool((ctx.episode.get("files") or {}).get("mouth_boxes"))


def find_ffprobe(explicit: str | None = None) -> str:
    """An explicit path, ``$FFPROBE`` or PATH; no machine-specific default lives in the engine."""
    for candidate in (explicit, os.environ.get("FFPROBE"), shutil.which("ffprobe")):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise Refused("ffprobe not found (pass --ffprobe or set FFPROBE); clip frames are measured, never typed")


def probe_frames(path: Path, ffprobe: str) -> int:
    frames = probe_video(Path(path), ffprobe=ffprobe, count_packets=True).frames
    if not isinstance(frames, int) or frames < 1:
        raise Refused(f"{path}: ffprobe reported no frame count")
    return frames


def _take(ctx: Context, out: Path, shot: str, receipt: dict) -> dict:
    """The accepted take of ``shot`` with its adopt/job receipts cross-checked (``Gap`` otherwise)."""
    rows = accept_mod.accepted_takes(out, [shot], ctx=ctx)
    if len(rows) != 1:
        raise Gap("NO_ACCEPTED_TAKE", shot, "no picked, file-verified take (jjv h3 accept --pick)")
    take, folder = rows[0], Path(out) / shot
    adopted, adopt_sha = read_json(folder / ADOPT_FILE), sha256_file(folder / ADOPT_FILE)
    job_path = folder / COMFY_DIR / "job.json"
    job = read_json(job_path) if job_path.is_file() else {}
    listed = {(str(o.get("node_id")), o.get("sha256")) for o in job.get("outputs") or []}
    pin = take["acceptance"]  # what the human's pick saw; the current receipts must still say exactly that
    checks = {"acceptance prompt == adopt prompt": pin["prompt_id"] == adopted.get("prompt_id"),
              "acceptance graph == adopt graph == prepared graph":
              pin["graph_sha256"] == adopted.get("graph_sha256") == receipt["graph_sha256"],
              "adopt.json sha == acceptance pin": pin["adopt_sha256"] in (None, adopt_sha),  # None: pre-pin record
              "job COMPLETED on the prepared graph": (job.get("status"), job.get("graph_sha256"), job.get("prompt_id"))
              == ("COMPLETED", receipt["graph_sha256"], pin["prompt_id"]),
              "job lists the editorial output": (str(receipt["editorial_node"]), take["sha256"]) in listed}
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise Gap("TAKE_RECEIPTS_DISAGREE", shot, f"failed: {failed}")
    return {**take, "folder": folder, "adopted": adopted, "adopt_sha256": adopt_sha, "job_outputs": listed,
            "job_sha256": sha256_file(job_path), "adopt_pinned": pin["adopt_sha256"] is not None}


def _carry_index(graph: dict, sink: str) -> int | None:
    """``batch_index`` of the single-frame ``ImageFromBatch`` feeding the carry sink; ``None`` if not that shape."""
    source = (graph.get(sink) or {}).get("inputs", {}).get("images")
    node = graph.get(str(source[0])) if isinstance(source, list) and source else None
    inputs = (node or {}).get("inputs") or {}
    if (node or {}).get("class_type") == "ImageFromBatch" and inputs.get("length") == 1 \
            and isinstance(inputs.get("batch_index"), int):
        return inputs["batch_index"]
    return None


def _carry(take: dict, receipt: dict, graph: dict) -> dict:
    shot = receipt["shot"]
    sink = (receipt.get("sinks") or {}).get(CARRY_ROLE)
    rows = [o for o in take["adopted"].get("outputs") or [] if o.get("role") == CARRY_ROLE]
    if not sink or len(rows) != 1:
        raise Gap("NO_CARRY_OUTPUT", shot, f"the accepted take has {len(rows)} '{CARRY_ROLE}' outputs "
                  f"(manifest sinks.{CARRY_ROLE} = {sink!r}); the carry frame is a graph output, never extracted by hand")
    row = rows[0]
    if (str(sink), row["sha256"]) not in take["job_outputs"] or sha256_file(Path(row["path"])) != row["sha256"]:
        raise Gap("TAKE_RECEIPTS_DISAGREE", shot, "carry output differs between adopt.json, job.json and disk")
    index = _carry_index(graph, str(sink))
    if index is None:
        raise Gap("CARRY_FRAME_INDEX_UNPROVEN", shot, f"carry sink {sink} is not fed by a 1-frame ImageFromBatch; "
                  "the frame index cannot be read from the prepared graph")
    return {"path": row["path"], "sha256": row["sha256"], "frame": index, "sink": str(sink)}


def carry_output(ctx: Context, out: Path, shot: str) -> dict:
    """The hash-bound carry frame of ``shot``'s ACCEPTED take (for ``jjv h3 inputs --carry-from``)."""
    (folder, receipt, graph), = load_prepared(ctx, out, shots=[safe(shot)])
    try:
        found = _carry(_take(ctx, out, shot, receipt), receipt, graph)
    except Gap as gap:
        raise Refused(str(gap)) from gap
    return {**found, "adopt": rel(folder / ADOPT_FILE, ctx.root), "adopt_sha256": sha256_file(folder / ADOPT_FILE)}


def _listed(ctx: Context, shots_file: Path | None) -> list[dict]:
    rows = (read_json(shots_file).get("shots") if shots_file else episode_shots(ctx)) or []
    if not rows or not all(isinstance(r, dict) and isinstance(r.get("shot"), str) for r in rows):
        raise Refused("the shot list has no shots")
    return rows


def _row(ctx: Context, item: dict, previous: dict | None, prepared: dict, takes: dict, frames: dict) -> dict:
    shot = item["shot"]
    folder, receipt, _graph = prepared[shot]
    kind = (item.get("entry") or {}).get("kind")
    prep = rel(folder / PREPARATION_FILE, ctx.root)
    if kind == "carry":
        source = (item.get("entry") or {}).get("from_shot") or (previous or {}).get("shot")
        if source not in prepared or source not in takes:
            raise Gap("NO_ACCEPTED_TAKE", shot, f"carry source {source!r} has no accepted take")
        carry = _carry(takes[source], prepared[source][1], prepared[source][2])
        if carry["sha256"] != receipt["anchor"]["sha256"]:
            raise Gap("CARRY_ANCHOR_UNBOUND", shot, f"anchor {receipt['anchor']['sha256'][:12]} is not the carry "
                      f"output {carry['sha256'][:12]} of {source}'s accepted take")
        if not 0 <= carry["frame"] < frames[source]:
            raise Gap("CARRY_FRAME_OUTSIDE_CLIP", shot, f"carry frame {carry['frame']} outside {source} "
                      f"({frames[source]} frames)")
        entry = {"kind": "carry", "from_shot": source, "frame": carry["frame"],
                 "evidence": f"{prep}:anchor.sha256 == {rel(prepared[source][0] / ADOPT_FILE, ctx.root)}:outputs."
                             f"{CARRY_ROLE} {carry['sha256'][:12]} (graph node {carry['sink']} batch_index)"}
    else:
        entry = {"kind": kind, "evidence": f"{prep}:anchor {receipt['anchor']['sha256'][:12]} "
                                           f"({rel(receipt['anchor']['path'], ctx.root)}); shot list entry.kind cut"}
    take = takes[shot]
    return {"shot": shot, "logical_shot": receipt["logical_shot"], "speaker": item.get("speaker"),
            "listener": item.get("listener"), "receipt_dir": rel(folder, ctx.root), "entry": entry,
            "clip": {"path": rel(take["path"], ctx.root), "sha256": take["sha256"],
                     "sha_source": f"{rel(folder / ADOPT_FILE, ctx.root)}:outputs.editorial", "frames": frames[shot]},
            "wav_binding": {"kind": "preparation_json_wav_sha256", "path": rel(receipt["wav"]["path"], ctx.root),
                            "sha256": receipt["wav"]["sha256"], "receipt_source": f"{prep}:wav.sha256",
                            "offset_s": 0.0}}


def build(ctx: Context, out: Path, *, shots_file: Path | None = None, ffprobe: str | None = None,
          frames_of: Callable[[Path, str], int] | None = None) -> tuple[dict, dict]:
    """``(shots document, publication receipt)``; nothing is written.  Every gap is collected, then refused."""
    out, listed = Path(out), _listed(ctx, shots_file)
    names = [safe(r["shot"]) for r in listed]
    if len(set(names)) != len(names):
        raise Refused("duplicate shot ids in the shot list")
    have = {p.parent.name for p in out.glob(f"*/{PREPARATION_FILE}")}
    gaps = [Gap("NOT_PREPARED", n, f"no {PREPARATION_FILE} under {out}").row for n in names if n not in have]
    ready = [n for n in names if n in have]
    prepared = {f.name: (f, r, g) for f, r, g in load_prepared(ctx, out, shots=ready)} if ready else {}
    takes, frames = {}, {}
    measure = frames_of or probe_frames
    tool = None
    for name in ready:
        try:
            takes[name] = _take(ctx, out, name, prepared[name][1])
        except Gap as gap:
            gaps.append(gap.row)
            continue
        tool = tool or (ffprobe if frames_of else find_ffprobe(ffprobe))
        frames[name] = measure(Path(takes[name]["path"]), tool)
    rows = []
    for position, item in enumerate(listed):
        if item["shot"] not in takes:
            continue
        try:
            rows.append(_row(ctx, item, listed[position - 1] if position else None, prepared, takes, frames))
        except Gap as gap:
            gaps.append(gap.row)
    if gaps:
        raise Refused("shots.json not published; unmet: " + "; ".join(f"{g['code']} {g['shot']}: {g['why']}"
                                                                   for g in gaps))
    ledger = ledger_path(ctx)
    document = {"schema": SHOTS_SCHEMA, "episode_id": ctx.episode_id,
                "sources": [f"jjv h3 publish-shots --out {rel(out, ctx.root)}",
                            f"{rel(ledger, ctx.root)} sha256 {sha256_file(ledger)}"], "shots": rows}
    problems = validate(document, read_json(SCHEMA_FILE), label="shots")
    if problems:
        raise Refused("shots.json not published; unmet: SCHEMA: " + "; ".join(problems))
    receipt = {"schema": PUBLICATION_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
               "h3_out": rel(out, ctx.root), "frames_measured_with": "ffprobe -count_packets (nb_frames)",
               "takes": [{"shot": n, "prompt_id": takes[n]["prompt_id"], "editorial_sha256": takes[n]["sha256"],
                          "adopt_sha256": takes[n]["adopt_sha256"],
                          "adopt_pinned_by_acceptance": takes[n]["adopt_pinned"],
                          "job_sha256": takes[n]["job_sha256"],
                          "preparation_sha256": sha256_file(prepared[n][0] / PREPARATION_FILE)} for n in names],
               "unmet": [MOUTH_GAP] if _expects_mouth_boxes(ctx) else []}
    return document, receipt


def _sidecar(path: Path) -> Path:
    return path.with_name(path.stem + ".publication.json")


def _versioned(folder: Path, payload: bytes) -> Path:
    """The version holding these exact bytes, else the first version whose shots file AND sidecar are both free."""
    number = 1
    while True:
        path = folder / f"{STEM}-v{number:03d}.json"
        if path.exists() and path.read_bytes() == payload:
            return path
        if not path.exists() and not _sidecar(path).exists():
            return path
        number += 1


def _write_pair(path: Path, payload: bytes, sidecar: Path, receipt: bytes) -> tuple[str, str]:
    """All-or-nothing: the sidecar first, then the shots file; a failed shots write removes a sidecar it created.
    Readers key on the shots file, so no shots file ever exists without its publication receipt."""
    created = not sidecar.exists()
    receipt_sha = write_once(sidecar, receipt)
    try:
        digest = write_once(path, payload)
    except BaseException:
        if created:
            sidecar.unlink(missing_ok=True)
        raise
    return digest, receipt_sha


def publish_shots(ctx: Context, out: Path, *, dest_dir: Path | None = None, **options: Any) -> dict:
    document, receipt = build(ctx, out, **options)
    payload = pretty_json(document, mode="ascii")
    path = _versioned(Path(dest_dir) if dest_dir else ctx.episode_file.parent, payload)
    receipt["shots_file"] = {"path": rel(path, ctx.root), "sha256": sha256_bytes(payload)}
    sidecar = _sidecar(path)
    digest, receipt_sha = _write_pair(path, payload, sidecar, pretty_json(receipt, mode="ascii"))
    total = sum(s["clip"]["frames"] for s in document["shots"])
    return {"shots_file": str(path), "shots_sha256": digest, "publication": str(sidecar),
            "publication_sha256": receipt_sha, "shots": [s["shot"] for s in document["shots"]],
            "clip_frames_total": total, "unmet": receipt["unmet"],
            "next": ("close MOUTH_BOXES_NOT_DERIVABLE, then " if receipt["unmet"] else "")
            + "point episode.files.shots at this file"}


__all__ = ["publish_shots", "build", "carry_output", "probe_frames", "find_ffprobe", "MOUTH_GAP"]
