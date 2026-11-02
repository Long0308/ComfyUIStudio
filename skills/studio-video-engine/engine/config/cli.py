"""``jjv config contract``: plan, lock and generate the per-episode delivery contract.

Modes (one JSON summary on stdout, a readable table on stderr):

* ``--plan``   allocate the sections from the script facts (``--inputs``), optionally to a target length
               (``--target-seconds T`` or ``--min-seconds A --max-seconds B``); exit 1 with every
               option and its numbers when the target breaks a floor or a maximum; writes nothing;
* ``--write``  the same allocation, then lock it: ``episode.contract`` (hashed) + the matching
               ``timeline`` into episode.json and a freshly generated DELIVERY-CONTRACT.json; both files are
               backed up (``.bak-<UTC>``) first and restored if the result does not validate;
* ``--write --from-episode``  regenerate DELIVERY-CONTRACT.json from the contract already in episode.json;
* neither      show the contract and whether the generated file is current (exit 1 when it is not).
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..core.errors import Refused
from ..core.io import pretty_json, read_json, sha256_file, write_atomic
from . import contract as contract_mod
from .budget import BudgetRefused, PIN_KINDS, Section, allocate, totals
from .loader import REPO_ROOT, SKILL_ROOT, build_config, find_episode_file
from .schema import validate

DEFAULT_CONTRACT_FILE = "DELIVERY-CONTRACT.json"


def register_config_verbs(config_verbs) -> None:
    """Add ``contract`` next to ``validate`` in the ``config`` verb group."""
    contract = config_verbs.add_parser("contract", help="plan / lock / generate the per-episode delivery contract")
    contract.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    contract.add_argument("--inputs", default=None,
                          help="script facts (jjv/contract-inputs/v1); default episode.files.contract_inputs")
    mode = contract.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="show the allocation table; write nothing")
    mode.add_argument("--write", action="store_true", help="lock the allocation into episode.json + DELIVERY-CONTRACT.json")
    contract.add_argument("--target-seconds", type=float, default=None, help="whole film file incl. end card")
    contract.add_argument("--min-seconds", type=float, default=None)
    contract.add_argument("--max-seconds", type=float, default=None)
    contract.add_argument("--pin", action="append", default=[], metavar="KIND=FRAMES",
                          help=f"fix a hold ({', '.join(PIN_KINDS)}) to a frame count")
    contract.add_argument("--revision", default=None, help="contract revision label stored with --write")
    contract.add_argument("--from-episode", action="store_true",
                          help="with --write: only regenerate DELIVERY-CONTRACT.json from episode.contract")


def wav_seconds(path: Path) -> float:
    """Duration of a RIFF/WAVE file (PCM or float) from its header; never decodes the samples."""
    with Path(path).open("rb") as stream:
        head = stream.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise Refused(f"{path}: not a RIFF/WAVE file")
        rate = align = None
        while True:
            chunk = stream.read(8)
            if len(chunk) < 8:
                raise Refused(f"{path}: no data chunk")
            tag, size = chunk[:4], struct.unpack("<I", chunk[4:])[0]
            if tag == b"fmt ":
                fmt = stream.read(size + (size & 1))
                rate, align = struct.unpack("<I", fmt[4:8])[0], struct.unpack("<H", fmt[12:14])[0]
            elif tag == b"data":
                if not rate or not align:
                    raise Refused(f"{path}: data chunk before fmt chunk")
                return size / align / rate
            else:
                stream.seek(size + (size & 1), 1)


def _seconds(entry: dict, root: Path, label: str) -> float:
    if "wav_s" in entry:
        return float(entry["wav_s"])
    if "wav" in entry:
        return wav_seconds(root / entry["wav"])
    raise Refused(f"{label}: give wav (path under the episode root) or wav_s")


def load_inputs(path: Path, episode_root: Path, shots: list[dict] | None) -> dict:
    """Normalise a contract-inputs file: every WAV becomes ``wav_s``; lines default to shots.json."""
    raw = read_json(path)
    errors = validate(raw, _INPUTS_SCHEMA, label="contract-inputs")
    if errors:
        raise Refused("; ".join(errors))
    if "lines" in raw:
        lines = [{"id": row["id"], "wav_s": _seconds(row, episode_root, f"line {row['id']}"),
                  **({"clip_frames": row["clip_frames"]} if "clip_frames" in row else {})} for row in raw["lines"]]
    elif shots:
        lines = [{"id": s["shot"], "wav_s": wav_seconds(episode_root / s["wav_binding"]["path"]),
                  "clip_frames": s["clip"]["frames"]} for s in shots]
    else:
        raise Refused("contract-inputs has no lines and the episode has no shots.json to take them from")
    end_line = raw.get("end_line")
    return {
        "intro_frames": raw.get("intro_frames", 0), "brand_intro_frames": raw.get("brand_intro_frames", 0),
        "lines": lines, "pins": dict(raw.get("pins") or {}),
        "vocab": [{"term": row["term"], "wav_s": _seconds(row, episode_root, f"vocab {row['term']}")}
                  for row in raw.get("vocab") or []],
        **({"sequence": raw["sequence"]} if raw.get("sequence") is not None else {}),
        "end_line": {"wav_s": _seconds(end_line, episode_root, "end_line")} if end_line else None,
        "end_card": raw.get("end_card", True), "extra": raw.get("extra"),
    }


_INPUTS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["schema"],
    "properties": {
        "schema": {"const": "jjv/contract-inputs/v1"}, "note": {"type": "string"},
        "intro_frames": {"type": "integer", "minimum": 0}, "brand_intro_frames": {"type": "integer", "minimum": 0},
        "lines": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False, "required": ["id"],
            "properties": {"id": {"type": "string", "minLength": 1}, "wav": {"type": "string", "minLength": 1},
                           "wav_s": {"type": "number", "exclusiveMinimum": 0},
                           "clip_frames": {"type": "integer", "minimum": 1}}}},
        "vocab": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["term"],
            "properties": {"term": {"type": "string", "minLength": 1}, "wav": {"type": "string", "minLength": 1},
                           "wav_s": {"type": "number", "exclusiveMinimum": 0}}}},
        "sequence": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "kind"],
            "properties": {"id": {"type": "string", "minLength": 1}, "kind": {"type": "string", "minLength": 1},
                           "line_id": {"type": "string", "minLength": 1},
                           "duration_s": {"type": "number", "exclusiveMinimum": 0}}}},
        "end_line": {"type": "object", "additionalProperties": False,
                     "properties": {"wav": {"type": "string", "minLength": 1}, "wav_s": {"type": "number", "exclusiveMinimum": 0}}},
        "end_card": {"type": "boolean"},
        "extra": {"type": "object"},
        "pins": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 1}},
    },
}


def parse_pins(items: list[str]) -> dict:
    pins: dict[str, int] = {}
    for item in items:
        kind, _, value = item.partition("=")
        if kind not in PIN_KINDS or not value.isdigit():
            raise Refused(f"--pin must be KIND=FRAMES with KIND in {PIN_KINDS}, got {item!r}")
        pins[kind] = int(value)
    return pins


def _read_domain(skill_root: Path, episode: dict) -> dict:
    path = skill_root / "domains" / f"{episode['domain']}.json"
    domain = read_json(path)
    errors = validate(domain, read_json(skill_root / "schemas" / "domain.schema.json"), label="domain")
    if errors:
        raise Refused("; ".join(errors))
    return domain


def plan_contract(episode_file: Path, *, skill_root: Path = SKILL_ROOT, inputs_path: Path | None = None,
                  target_seconds: float | None = None, min_seconds: float | None = None,
                  max_seconds: float | None = None, pins: dict | None = None,
                  revision: str | None = None) -> dict:
    """Allocate; return ``{episode, domain, inputs, sections, contract}`` or raise :class:`BudgetRefused`."""
    episode = read_json(episode_file)
    domain = _read_domain(skill_root, episode)
    engine_dir = Path(episode_file).parent
    names = episode.get("files") or {}
    chosen = inputs_path or (engine_dir / names["contract_inputs"] if names.get("contract_inputs") else None)
    if chosen is None:
        raise Refused("no script facts: pass --inputs or set episode.files.contract_inputs")
    shots = read_json(engine_dir / names["shots"])["shots"] if names.get("shots") and (engine_dir / names["shots"]).is_file() else None
    inputs = load_inputs(Path(chosen), engine_dir.parent, shots)
    inputs["pins"] = {**inputs["pins"], **(pins or {})}
    fps = domain["frame_rates"]["delivery_fps"]

    def frames(value: float | None) -> int | None:
        return None if value is None else round(value * fps)

    sections = allocate(domain, inputs, target_frames=frames(target_seconds), min_frames=frames(min_seconds),
                        max_frames=frames(max_seconds))
    label = revision or (episode.get("contract") or {}).get("revision") or f"{totals(sections)['total_frames']}-planned"
    contract = contract_mod.build_contract(
        sections, fps=fps, revision=label, brand_intro_frames=inputs["brand_intro_frames"],
        inputs_sha256=sha256_file(Path(chosen)),
        extra=inputs.get("extra") or (episode.get("contract") or {}).get("extra"))
    return {"episode": episode, "domain": domain, "inputs": inputs, "sections": sections, "contract": contract}


def format_table(sections: list[Section], fps: int) -> str:
    head = f"{'section':<12}{'kind':<11}{'floor':>6}{'max':>6}{'frames':>8}{'seconds':>9}  note"
    rows = [f"{s.id:<12}{s.kind:<11}{s.low:>6}{s.high:>6}{s.frames:>8}{s.frames / fps:>9.2f}  {s.note}" for s in sections]
    parts = totals(sections)
    foot = (f"main {parts['main_frames']} f + end card {parts['end_card_frames']} f = {parts['total_frames']} f "
            f"({parts['total_frames'] / fps:.2f} s)")
    return "\n".join([head, *rows, foot])


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup(path: Path, stamp: str) -> Path | None:
    if not path.is_file():
        return None
    target = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, target)
    return target


def _delivery_path(episode: dict, episode_file: Path) -> Path:
    return Path(episode_file).parent.parent / (episode.get("delivery_contract") or DEFAULT_CONTRACT_FILE)


def write_contract(episode_file: Path, planned: dict | None, *, skill_root: Path = SKILL_ROOT,
                   machine_path: Path | None = None, repo_root: Path = REPO_ROOT) -> dict:
    """Lock ``planned`` (or the contract already in episode.json) and generate DELIVERY-CONTRACT.json.

    Both files are backed up first; if the result does not validate they are restored and
    :class:`Refused` is raised with the violations.
    """
    episode_file = Path(episode_file)
    before = read_json(episode_file)
    domain = planned["domain"] if planned else _read_domain(skill_root, before)
    episode = dict(before)
    if planned:
        episode["contract"] = planned["contract"]
        episode["timeline"] = {**before["timeline"], **contract_mod.timeline_from_contract(planned["contract"])}
        episode.setdefault("delivery_contract", DEFAULT_CONTRACT_FILE)
    elif "contract" not in episode:
        raise Refused("episode.json has no contract; run --plan/--write with --inputs first")
    delivery = _delivery_path(episode, episode_file)
    stamp = _utc()
    saved = [(episode_file, _backup(episode_file, stamp)), (delivery, _backup(delivery, stamp))]
    write_atomic(delivery, pretty_json(contract_mod.render_delivery_contract(episode, domain), mode="ascii"))
    write_atomic(episode_file, pretty_json(episode, mode="utf8"))
    report = build_config(episode_file, skill_root=skill_root, machine_path=machine_path, repo_root=repo_root)
    if not report.ok:
        for path, backup in saved:
            if backup is not None:
                shutil.copy2(backup, path)
            else:
                path.unlink(missing_ok=True)
        raise Refused("the locked contract does not validate (files restored): " + "; ".join(report.violations))
    return {"episode_file": str(episode_file), "delivery_contract": str(delivery),
            "delivery_contract_sha256": sha256_file(delivery), "config_sha256": report.config.config_sha256,
            "backups": [str(b) for _, b in saved if b is not None]}


def _summary(planned: dict) -> dict:
    return {"ok": True, **totals(planned["sections"]), "contract_sha256": planned["contract"]["sha256"],
            "sections": [{"id": s.id, "kind": s.kind, "floor": s.low, "max": s.high, "frames": s.frames}
                         for s in planned["sections"]]}


def run_config_contract(args: argparse.Namespace, *, skill_root: Path = SKILL_ROOT,
                        machine_path: Path | None = None) -> int:
    episode_file = find_episode_file(args.episode)
    if not (args.plan or args.write):
        return _show(episode_file, skill_root, machine_path)
    if args.write and args.from_episode:
        print(json.dumps({"ok": True, **write_contract(episode_file, None, skill_root=skill_root,
                                                       machine_path=machine_path)}, indent=2))
        return 0
    try:
        planned = plan_contract(
            episode_file, skill_root=skill_root, inputs_path=Path(args.inputs) if args.inputs else None,
            target_seconds=args.target_seconds, min_seconds=args.min_seconds, max_seconds=args.max_seconds,
            pins=parse_pins(args.pin), revision=args.revision)
    except BudgetRefused as refusal:
        print(json.dumps({"ok": False, "refused": str(refusal), "options": refusal.options, "table": refusal.table},
                         indent=2), file=sys.stdout)
        print("REFUSED: " + str(refusal), file=sys.stderr)
        for option in refusal.options:
            print(f"  option: {option['option']} ({option.get('frames', 0):+d} f)", file=sys.stderr)
        return 1
    fps = planned["domain"]["frame_rates"]["delivery_fps"]
    print(format_table(planned["sections"], fps), file=sys.stderr)
    summary = _summary(planned)
    if args.write:
        summary.update(write_contract(episode_file, planned, skill_root=skill_root, machine_path=machine_path))
    print(json.dumps(summary, indent=2))
    return 0


def _show(episode_file: Path, skill_root: Path, machine_path: Path | None) -> int:
    report = build_config(episode_file, skill_root=skill_root, machine_path=machine_path)
    contract = (read_json(episode_file).get("contract")) or {}
    print(json.dumps({"ok": report.ok, "contract_sha256": contract.get("sha256"),
                      "main_frames": contract.get("main_frames"), "end_card_frames": contract.get("end_card_frames"),
                      "total_frames": contract.get("total_frames"), "vocab_count": contract.get("vocab_count"),
                      "violations": list(report.violations),
                      "config_sha256": report.config.config_sha256 if report.config else None}, indent=2))
    return 0 if report.ok else 1

