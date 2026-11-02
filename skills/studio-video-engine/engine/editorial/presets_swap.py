"""``jjv editorial boundaries swap``: changing one boundary's preset is DATA, never code.

The declared ``boundaries.json`` is read-only.  A swap writes into a workspace folder:

* ``versions/boundaries-v001.json`` = the declared table, then max suffix + 1 for every swap (write-once, the same
  allocator as ``boundaries write``);
* ``boundaries.json`` = a copy of the latest version (the file ``jjv editorial build-config`` is pointed at);
* ``boundaries.current.json`` = the receipt: the SOURCE OF TRUTH for which version is current;
* ``swap-log.json`` = what changed in each version and which segments must be re-composited.  A crash between the
  receipt and the log is repaired from the receipt by the next run.

A swap replaces the WHOLE effect spec: frames and params are the new preset's defaults unless the token gives
them (``cut_push:frames=8:scale_from=1.06``); the old effect's params are dropped.  Naming the effect that is
already there changes nothing and writes nothing.

The new row must pass the engine's own row rules (class, continuity, picture / graphic, frames, direction,
params) and its tail handle must exist: a refused swap writes nothing.  The segment list comes from the
engine's own cut planner (:mod:`segments`) run on the picture boundaries before and after: a segment must be
re-composited when it is new or when a transition record that touches it changed.  Shot video is never touched.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..config.loader import SKILL_ROOT
from ..core.io import canonical_sha256, pretty_json, read_json, sha256_file, write_json_atomic
from . import boundaries as table
from . import boundaries_current as current
from . import boundaries_suggest as bs
from . import presets, segments, transitions
from .boundaries_preview import candidate_spec, parse_tokens

SCHEMA = "jjv/boundaries-swap-log/v1"
BOUNDARIES_SCHEMA = SKILL_ROOT / "schemas" / "boundaries.schema.json"


def find_row(document: dict, boundary: str) -> tuple[int, dict]:
    text = str(boundary).strip()
    for index, row in enumerate(document["boundaries"]):
        if text in (str(row.get("frame")), f"T{row.get('frame')}"):
            return index, row
    raise Refused(f"no boundary {boundary!r} in this table (use a frame number or an id such as T1310)")


def _resolved(row: dict, grid: dict) -> dict:
    return transitions.resolve_row({**row, "frame": row.get("frame", grid["starts"].get(row["to_shot"]))})


def records_of(document: dict, ctx: dict) -> list[dict]:
    """Transition records of the picture boundaries (window + ``renders_as`` + a tail marker), no file access."""
    out = []
    for row in document["boundaries"]:
        if row["from_shot"] in ctx["pictures"] and row["to_shot"] in ctx["pictures"]:
            resolved = _resolved(row, ctx["grid"])
            tail = {"shot": row["from_shot"]} if presets.tail_frames(presets.get(resolved["preset"]), resolved["frames"]) else None
            out.append(transitions.build_transition(resolved, tail, None))
    return out


def plan_of(records: list[dict], shots: list[dict], grid: dict, episode_id: str) -> dict:
    ends = {s["shot"]: grid["starts"][s["shot"]] + grid["lengths"][s["shot"]] for s in shots}
    return segments.plan_segments(
        fps=grid["fps"], total_frames=grid["dialogue_end"], main_frames=grid["dialogue_end"], intro_end=grid["intro_end"],
        dialogue_end=grid["dialogue_end"], shots=[{"id": s["shot"], "start": grid["starts"][s["shot"]],
                                                   "end": ends[s["shot"]]} for s in shots],
        transitions=records, cards=[], plate_start=None, join_frame=None, icons=[], episode_id=episode_id)


def _signatures(plan: dict, records: list[dict]) -> dict[tuple, dict]:
    out = {}
    for seg in plan["segments"]:
        touching = [{k: v for k, v in r.items() if k != "motivation"} for r in records   # a note changes no pixel
                    if seg["start"] < r["end_exclusive"] and r["start"] < seg["end_exclusive"]
                    or seg["start"] <= r["boundary"] < seg["end_exclusive"]]
        core = {k: seg[k] for k in ("id", "kind", "start", "end_exclusive", "shots_visible")}
        out[(seg["id"], seg["start"], seg["end_exclusive"], canonical_sha256([core, touching], mode="utf8"))] = seg
    return out


def segments_to_recomposite(old: dict, new: dict, shots: list[dict], grid: dict, episode_id: str) -> dict:
    """Segments of the NEW plan that are new or touch a changed record; the old ones that disappear."""
    plans = [plan_of(records, shots, grid, episode_id) for records in (old, new)]
    before, after = _signatures(plans[0], old), _signatures(plans[1], new)
    changed = [{"id": seg["id"], "kind": seg["kind"], "start": seg["start"], "end_exclusive": seg["end_exclusive"],
                "frames": seg["frames"]} for key, seg in after.items() if key not in before]
    gone = [seg["id"] for key, seg in before.items() if key not in after]
    return {"re_composite": changed, "replaced_old_segments": gone, "segments_total": len(plans[1]["segments"])}


def new_row(old: dict, spec: dict, token: dict, version: int, motivation: str | None, clip: str | None) -> dict:
    name = spec["preset"].name
    text = motivation or (f"swap v{version:03d}: {old['type']} -> {name} (picked from the preview); "
                          f"previous motivation: {old['motivation']}")
    row = {k: v for k, v in old.items() if k not in ("params", "type", "frames", "direction", "motivation")}
    row.update({"type": name, "frames": spec["frames"], "direction": spec["direction"], "motivation": text})
    if token["params"]:
        row["params"] = token["params"]
    if presets.tail_frames(spec["preset"], spec["frames"]) and clip and not row.get("tail_clip"):
        row["tail_clip"] = clip
    return row


def _repair_log(workspace: Path, log: dict) -> None:
    """Add the log entries the receipt says exist but the log lacks (a crash between the receipt and the log)."""
    receipt = current.read_receipt(workspace)
    logged = max((v["version"] for v in log["versions"]), default=0)
    if receipt is None or receipt.get("version", 0) <= logged:
        return
    for number, path in current._versions(workspace / "versions", "boundaries"):
        if logged < number <= receipt["version"]:
            log["versions"].append({"version": number, "file": f"versions/{path.name}", "sha256": sha256_file(path),
                                    "parent": logged or None, "change": "recovered from the receipt (interrupted swap)"})
            logged = number


def _load_state(config: Any, workspace: Path, declared_path: Path, dry_run: bool) -> tuple[dict, dict]:
    """The workspace is read through ``load_document`` (schema, presets, domain floors, receipt) after an interrupted
    publish is completed; the log is repaired from the receipt.  Dry runs repair nothing on disk."""
    live = workspace / "boundaries.json"
    if not live.is_file():
        document = read_json(declared_path)
        return document, {"schema": SCHEMA, "source": declared_path.name, "source_sha256": sha256_file(declared_path),
                          "versions": []}
    if not dry_run:
        current.recover(workspace)
    log_path = workspace / "swap-log.json"
    log = read_json(log_path) if log_path.is_file() else {
        "schema": SCHEMA, "source": declared_path.name, "source_sha256": sha256_file(declared_path), "versions": []}
    document = table.load_document(live, BOUNDARIES_SCHEMA, config.episode["episode_id"], config.domain)
    before = len(log["versions"])
    _repair_log(workspace, log)
    if not dry_run and len(log["versions"]) != before:
        write_json_atomic(log_path, log, mode="utf8", stamp=True)
    return document, log


def swap(ctx: dict, shots: list[dict], config: Any, declared_path: Path, workspace: Path, boundary: str, token_text: str,
         *, motivation: str | None = None, dry_run: bool = False) -> dict:
    """Validate and apply one swap; returns the summary (version file, hashes, segments to re-composite)."""
    document, log = _load_state(config, workspace, declared_path, dry_run)
    tokens = parse_tokens(token_text)
    if len(tokens) != 1:
        raise Refused("swap takes exactly one preset")
    index, old = find_row(document, boundary)
    a = next((s for s in shots if s["shot"] == old["from_shot"]), None)
    b = next((s for s in shots if s["shot"] == old["to_shot"]), None)
    if a is None or b is None:
        raise Refused(f"boundary {boundary}: {old['from_shot']} -> {old['to_shot']} is not between two picture shots "
                      "(graphic boundaries are not swapped here)")
    item = {"chosen": {"type": None, "frames": None, "direction": old.get("direction", 0)}, "alternatives": []}
    spec = candidate_spec(item, tokens[0])
    versions = workspace / "versions"
    base_payload = pretty_json(document, mode="utf8")
    if log["versions"]:
        version = current.next_version(versions, "boundaries")
    else:   # the declared table becomes the next free number (reused when identical), the swap the one after it
        existing = current._versions(versions, "boundaries")
        reused = bool(existing) and existing[-1][1].read_bytes() == base_payload
        version = (existing[-1][0] if reused else current.next_version(versions, "boundaries")) + 1
    feas, _outgoing, clip, _source = bs.feasibility_for(ctx["root"], a, b, old, ctx["grid"], ctx["probe"],
                                                        preset=spec["preset"].name, frames=spec["frames"])
    clip_rel = clip.relative_to(ctx["root"]).as_posix() if clip is not None and clip.is_relative_to(ctx["root"]) else None
    row = new_row(old, spec, tokens[0], version, motivation, clip_rel)
    resolved = _resolved(row, ctx["grid"])
    transitions.check_row(resolved, ctx["pictures"])   # class / continuity / kind first
    entry = feas[spec["preset"].name]
    if not entry["available"]:
        raise Refused(f"boundary {boundary}: {entry['reason']}")
    before = _resolved(old, ctx["grid"])
    if all(before[k] == resolved[k] for k in ("preset", "frames", "direction", "params")):
        return {"ok": True, "unchanged": True, "boundary": f"T{old['frame']}", "from": old["type"], "to": row["type"],
                "re_composite": [], "replaced_old_segments": [], "note": "same effect, frames, direction and params: "
                                                                         "nothing written"}
    updated = copy.deepcopy(document)
    updated["boundaries"][index] = row
    result = segments_to_recomposite(records_of(document, ctx), records_of(updated, ctx), shots, ctx["grid"],
                                     config.episode["episode_id"])
    summary = {"ok": True, "dry_run": dry_run, "boundary": f"T{old['frame']}", "from": old["type"], "to": row["type"],
               "frames": row["frames"], "direction": row["direction"], "version": version,
               "tail_clip": row.get("tail_clip"), **result}
    if dry_run:
        return summary
    if not log["versions"]:   # the declared table becomes a version so every later version has a parent
        base, _, base_path, base_sha = current.write_version(versions, "boundaries", base_payload)
        log["versions"].append({"version": base, "file": f"versions/{base_path.name}", "sha256": base_sha,
                                "change": "declared table (unchanged copy)"})
    parent = log["versions"][-1]["version"]
    number, _, path, digest = current.write_version(versions, "boundaries", pretty_json(updated, mode="utf8"))
    name = f"versions/{path.name}"
    log["versions"].append({"version": number, "file": name, "sha256": digest, "parent": parent,
                            "change": {"boundary": summary["boundary"], "from": old["type"], "to": row["type"],
                                       "frames": row["frames"], "direction": row["direction"]},
                            "re_composite": [s["id"] for s in result["re_composite"]]})
    current.publish(workspace, updated, version=number, version_path=name, writer="presets-swap")
    write_json_atomic(workspace / "swap-log.json", log, mode="utf8", stamp=True)
    return {**summary, "version": number, "file": name, "sha256": digest, "current": "boundaries.json"}
