"""``jjv edit master-config``: engine build output + episode contract + 4K receipts -> the master config the master adapter reads.

The master adapter (``remotion-kit/lib/adapter-master.cjs``) binds each picture clip and each outgoing tail of the review cut to its 4K source
through a receipt.  This module PRODUCES that input from data, for any episode, with no per-episode script:

* the review cut: ``review-config.json`` + ``events.json`` written by ``jjv editorial build-config`` (schema ``main_frames``);
* the episode contract (frames, fps, master size, native fps), already resolved by the caller into :class:`Contract`;
* the 4K sources: ``runs/<shot>/shot.json`` of the SeedVR2 plan (final shot cores), an optional seam-variant file (hf8 blends, bound by their
  seam-blend receipt) and ``MASTER-TAIL-MAP.json`` (tail cores).

Nothing is guessed: every bound file is re-hashed, a receipt that does not attest the clip is a problem, and a final-master build refuses
(``Refused`` naming each missing input).  ``preview=True`` writes the same document with the missing pictures bound to the review (editorial)
clip and the missing tails to the native tail, ``master_ready: false``, for stills and ranges.  Pure: no GPU, no render, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from ..core.paths import resolve_data_path

SCHEMA = "jjv/master-config/v1"
TAIL_MAP_SCHEMAS = ("jjv/master-tail-map/v1", "mam-r27-master-tail-map/v1")
SEAM_SCHEMAS = ("seam-blend-receipt/v001", "seam-blend-receipt/v002")
FINAL_SHOT, FINAL_SEAM, PREVIEW_SHOT = "shot-final-4k", "seam-variant-hf8", "editorial-preview"
FINAL_TAIL, PREVIEW_TAIL = "tail-core-4k", "preview_only_tail"


@dataclass(frozen=True)
class Contract:
    """What the episode contract + domain say about the master (the caller resolves them; this module only reads)."""
    width: int
    height: int
    fps: int
    native_fps: Fraction
    main_frames: int
    end_card_frames: int
    film_2k: dict | None = None

    @property
    def total_frames(self) -> int:
        return self.main_frames + self.end_card_frames

    @property
    def native_fps_text(self) -> str:
        return f"{self.native_fps.numerator}/{self.native_fps.denominator}"


def contract_from_config(config: Any) -> Contract:
    """The contract of a ResolvedConfig (episode.contract + domain delivery.master + domain frame_rates)."""
    contract = config.episode.get("contract")
    if not contract:
        raise Refused("the episode has no contract (episode.contract): run `jjv config contract` first")
    master = ((config.domain.get("delivery") or {}).get("master")) or {}
    native = (config.domain.get("frame_rates") or {}).get("native_fps")
    missing = [name for name, value in (("domain.delivery.master.width", master.get("width")), ("domain.delivery.master.height", master.get("height")),
                                        ("domain.frame_rates.native_fps", native), ("episode.contract.fps", contract.get("fps")),
                                        ("episode.contract.main_frames", contract.get("main_frames")),
                                        ("episode.contract.end_card_frames", contract.get("end_card_frames"))) if value is None]
    if missing:
        raise Refused("the master contract is incomplete: " + ", ".join(missing))
    return Contract(int(master["width"]), int(master["height"]), int(contract["fps"]), Fraction(str(native)),
                    int(contract["main_frames"]), int(contract["end_card_frames"]), (config.domain["delivery"] or {}).get("film_2k"))


def _absolute(text: str, base: Path) -> Path:
    """Absolute as recorded (a retired root is remapped to where the file lives now), else relative to ``base``."""
    path = Path(text)
    return resolve_data_path(path) if path.is_absolute() else (base / path).resolve()


def _check_file(path: Path, sha: str | None, label: str) -> str | None:
    if not path.is_file():
        return f"{label}: file missing ({path})"
    if sha is not None and sha256_file(path) != sha:
        return f"{label}: sha256 differs from the recorded {sha[:12]} ({path})"
    return None


def _segment_row(seg: dict, dialogue: dict, contract: Contract, path: str | None, sha: str | None, kind: str, restored: dict,
                 core_variant: str = "core") -> dict:
    return {"source_id": seg["shot"], "path": path, "sha256": sha, "native_frames": seg["native_frames"],
            "delivery_frames": seg["duration_frames"], "width": contract.width, "height": contract.height, "fps": contract.native_fps_text,
            "relative_start_frame": seg["start_frame"] - dialogue["start_frame"], "core_variant": core_variant, "source_kind": kind,
            "restored": restored, "available": path is not None, "preview_only": kind not in (FINAL_SHOT, FINAL_SEAM)}


def _final_restored(kind: str, path: str, sha: str, evidence: dict | None, variant: str) -> dict:
    return {"status": "COMPLETE", "finalized": True, "preview_only": False, "source_kind": kind, "core_variant": variant,
            "final_path": path, "final_sha256": sha, "variant_evidence": evidence, "variant_fallback": None}


def _bind_variant(seg: dict, variant: dict, base: Path) -> tuple[dict | None, str | None]:
    sid = seg["shot"]
    path, receipt = _absolute(variant["path"], base), _absolute(variant["receipt_path"], base)
    problem = _check_file(path, variant["sha256"], f"{sid} seam variant") or _check_file(receipt, variant["receipt_sha256"], f"{sid} seam receipt")
    if problem:
        return None, problem
    doc = read_json(receipt)
    if doc.get("schema") not in SEAM_SCHEMAS:
        return None, f"{sid}: seam receipt schema {doc.get('schema')!r} not in {list(SEAM_SCHEMAS)}"
    if (doc.get("output") or {}).get("sha256") != variant["sha256"]:
        return None, f"{sid}: seam receipt output.sha256 does not attest the variant clip"
    evidence = {"receipt_path": str(receipt), "receipt_sha256": variant["receipt_sha256"]}
    return {"path": str(path), "sha256": variant["sha256"], "kind": FINAL_SEAM, "variant": "hf8",
            "restored": _final_restored(FINAL_SEAM, str(path), variant["sha256"], evidence, "hf8")}, None


def _bind_shot_core(seg: dict, runs: Path | None) -> tuple[dict | None, str | None]:
    sid = seg["shot"]
    receipt = None if runs is None else runs / sid / "shot.json"
    if receipt is None or not receipt.is_file():
        return None, f"{sid}: no final shot receipt ({receipt or 'no --runs given'})"
    doc = read_json(receipt)
    if doc.get("status") != "COMPLETED" or doc.get("shot_id") != sid:
        return None, f"{sid}: shot receipt status {doc.get('status')!r} / shot_id {doc.get('shot_id')!r} is not a COMPLETED receipt of this shot"
    path = Path(str(doc.get("path") or ""))
    problem = _check_file(path, doc.get("sha256") or "", f"{sid} final core")
    if problem:
        return None, problem
    if int(doc.get("frame_count", -1)) < seg["native_frames"]:
        return None, f"{sid}: final core has {doc.get('frame_count')} frames, the editorial cut uses {seg['native_frames']}"
    return {"path": str(path), "sha256": doc["sha256"], "kind": FINAL_SHOT, "variant": "core",
            "restored": _final_restored(FINAL_SHOT, str(path), doc["sha256"], None, "core")}, None


def _bind_segment(seg: dict, dialogue: dict, contract: Contract, runs: Path | None, variants: dict, base: Path, root: Path,
                  preview: bool) -> tuple[dict, str | None]:
    final, problem = (_bind_variant(seg, variants[seg["shot"]], base) if seg["shot"] in variants else _bind_shot_core(seg, runs))
    if final:
        return _segment_row(seg, dialogue, contract, final["path"], final["sha256"], final["kind"], final["restored"], final["variant"]), None
    row = _segment_row(seg, dialogue, contract, None, None, PREVIEW_SHOT,
                       {"status": "INCOMPLETE", "finalized": False, "preview_only": True, "source_kind": PREVIEW_SHOT, "core_variant": "core",
                        "final_path": None, "final_sha256": None, "variant_evidence": None, "variant_fallback": None})
    if preview:  # the review clip stands in (HD picture, marked preview): stills and ranges only
        clip = _absolute(seg["clip"]["path"], root)
        if _check_file(clip, seg["clip"]["sha256"], f"{seg['shot']} review clip") is None:
            row.update(path=str(clip), sha256=seg["clip"]["sha256"], available=True)
    return row, problem


def _output_indexes(tail: dict, used: int, native: Fraction, fps: int) -> tuple[list[int], list[int]]:
    start = int(tail["start_from_frame"])
    spans = [Fraction(start + k) * native / fps for k in range(used)]
    return [s.__floor__() for s in spans], [s.__ceil__() for s in spans]


def _tail_problems(tid: str, tail: dict, row: dict, path: Path, first: int, frames: int, contract: Contract) -> list[str]:
    used = int(tail.get("tail_output_frames") or 0)
    floors, ceils = _output_indexes(tail, used, contract.native_fps, contract.fps)
    problems = [f"{tid}: output frame {k} needs native {lo}..{hi}, the tail core holds {first}..{first + frames - 1}"
                for k, (lo, hi) in enumerate(zip(floors, ceils)) if lo < first or hi > first + frames - 1]
    listed = row.get("clip_frame_for_output_k") or {}
    for name, computed in (("floor", floors), ("ceil", ceils)):
        values = listed.get(name)
        if values is not None and [first + v for v in values[:used]] != computed:
            problems.append(f"{tid}: tail map {name} list disagrees with the native indexes the transition reads")
    return problems


def _tail_transition(t: dict, tail: dict, source: dict | None, contract: Contract) -> tuple[dict | None, str | None]:
    """The master's outgoing_tail + tail_source for one transition; the master startFrom lands on native index ``editorial_frames``."""
    tid, editorial = t["id"], int(tail["editorial_frames"])
    if source is None:
        return None, f"{tid}: no 4K tail core"
    offset = (editorial - source["first_native_index"]) * Fraction(contract.fps) / contract.native_fps
    if offset.denominator != 1 or offset < 0:
        return None, f"{tid}: tail startFrom {offset} is not a whole, non-negative frame (first native index {source['first_native_index']}, editorial {editorial})"
    keep = {key: tail[key] for key in ("tail_output_frames", "editorial_frames", "native_frames")}
    return {**keep, "review_start_from_frame": int(tail["start_from_frame"]), "start_from_frame": int(offset)}, None


def _bind_tail(t: dict, map_path: Path | None, rows: dict, contract: Contract, root: Path, preview: bool) -> tuple[dict | None, str | None]:
    tail, tid = t["outgoing_tail"], t["id"]
    editorial, native_total = int(tail["editorial_frames"]), int(tail["native_frames"])
    base = {"transition_id": tid, "shot": tail["shot"], "boundary": t["boundary"], "native_editorial_frames": editorial,
            "last_native_index_used": tail.get("last_native_index_used")}
    row, problems = rows.get(tid), []
    if row is None or map_path is None:
        problems.append(f"{tid}: no row for this transition in the tail map ({map_path or 'no --tail-map given'})")
    else:
        path = _absolute(row["clip"], map_path.parent)
        first, frames = int(row["native_first"]), int(row["frames"])
        problem = _check_file(path, row["clip_sha256"], f"{tid} tail core")
        problems += [problem] if problem else _tail_problems(tid, tail, row, path, first, frames, contract)
        if not problems:  # native_total_frames = the end of THIS file, so the adapter's fileFrames equals the file's own frame count
            return {**base, "status": "COMPLETE", "kind": FINAL_TAIL, "preview_only_tail": False, "path": str(path), "sha256": row["clip_sha256"],
                    "frames": frames, "first_native_index": first, "native_total_frames": first + frames, "receipt": str(map_path)}, None
    if not preview:
        return None, "; ".join(problems)
    native = _absolute(tail["native_path"], root)
    return {**base, "status": "INCOMPLETE", "kind": PREVIEW_TAIL, "preview_only_tail": True, "path": str(native), "sha256": tail["native_sha256"],
            "frames": native_total, "first_native_index": 0, "native_total_frames": native_total, "reasons": problems}, "; ".join(problems)


def _load_map(map_path: Path | None) -> dict:
    if map_path is None or not map_path.is_file():
        return {}
    doc = read_json(map_path)
    if doc.get("schema") not in TAIL_MAP_SCHEMAS:
        raise Refused(f"tail map {map_path.name}: schema {doc.get('schema')!r} not in {list(TAIL_MAP_SCHEMAS)}")
    rows: dict[str, list] = {}
    for row in doc.get("tails", []):
        rows.setdefault(row.get("transition"), []).append(row)
    return {tid: found[0] for tid, found in rows.items() if len(found) == 1 and tid}


def _structure(review: dict, events: dict, contract: Contract) -> None:
    wrong = [f"review {key} {review.get(key)} != contract {want}" for key, want in
             (("fps", contract.fps), ("main_frames", contract.main_frames), ("end_hold_frames", contract.end_card_frames)) if review.get(key) != want]
    if review.get("main_frames") is None:
        wrong.append("review-config has no main_frames (not an engine build-config output)")
    ids = [t["id"] for t in review["motion"]["transitions"]]
    if ids != [t["id"] for t in events["transitions"]]:
        wrong.append("events.json and review-config.json list different transitions")
    if wrong:
        raise Refused("the engine build does not match the episode contract: " + "; ".join(wrong))


def build_master_config(review: dict, events: dict, contract: Contract, *, episode_root: Path, runs_dir: Path | None = None,
                        tail_map: Path | None = None, variants: dict | None = None, variants_base: Path | None = None,
                        inputs: dict | None = None, preview: bool = False) -> dict:
    """The master config document; ``Refused`` (naming every missing input) unless ``preview`` or every source is final."""
    _structure(review, events, contract)
    root, rows, missing_shots, missing_tails, problems = Path(episode_root), _load_map(tail_map), [], [], []
    dialogue = []
    for shot in review["dialogue"]:
        segments = []
        for seg in shot["segments"]:
            row, problem = _bind_segment(seg, shot, contract, runs_dir, variants or {}, variants_base or root, root, preview)
            segments.append(row)
            if problem:
                missing_shots.append(seg["shot"])
                problems.append(problem)
        dialogue.append({"id": shot["id"], "start_frame": shot["start_frame"], "duration_frames": shot["duration_frames"], "segments": segments})
    transitions = []
    for t in review["motion"]["transitions"]:
        entry: dict = {"id": t["id"], "boundary": t["boundary"]}
        if t.get("outgoing_tail"):
            source, problem = _bind_tail(t, tail_map, rows, contract, root, preview)
            moved, problem2 = _tail_transition(t, t["outgoing_tail"], source, contract)
            if problem or problem2:
                missing_tails.append(t["id"])
                problems.append(problem or problem2)
            if moved:
                entry.update(outgoing_tail=moved, tail_source=source)
        transitions.append(entry)
    if problems and not preview:
        raise Refused("master config refused (final master needs every 4K source bound by a receipt; pass --preview for stills): " + " | ".join(problems))
    ready = not problems
    return {"schema": SCHEMA, "episode_id": review["episode_id"], "status": "PREPARED_NOT_RENDERED" if ready else "PREVIEW_ONLY_NOT_MASTER",
            "build_mode": "master" if ready and not preview else "preview", "master_ready": ready,
            "missing_shots": missing_shots, "missing_tails": missing_tails, "problems": problems,
            "master_contract": {"width": contract.width, "height": contract.height, "fps": contract.fps, "main_frames": contract.main_frames,
                                "end_card_frames": contract.end_card_frames, "total_frames": contract.total_frames,
                                "native_restored_fps": contract.native_fps_text, "film_2k": contract.film_2k},
            "dialogue": dialogue, "motion": {"transitions": transitions}, "inputs": inputs or {}}
