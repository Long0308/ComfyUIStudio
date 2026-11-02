"""``jjv editorial build-config``: declarative inputs -> review config + events (write-once).

Inputs: the resolved episode (shots.json, timeline, domain), ``boundaries.json`` (cuts, icon terms,
cards, ending parameters) and a word-timing document.  Nothing is guessed: any rule violation is a
``Refused`` (exit 1) and nothing is written.  Outputs carry no timestamps, so a rebuild from the
same inputs is byte-identical and ``write_once`` stays idempotent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import rules
from ..config.loader import SKILL_ROOT, ResolvedConfig
from ..core.errors import Refused
from ..core.io import pretty_json, read_json, sha256_bytes, sha256_file, write_once
from ..qa.scope import require_scoped, shown_path
from ..media.probe import probe_video
from . import boundaries as table
from . import captions, derive, segments as segment_plan, sources
from .timeline import Timeline, build_timeline, synthetic_entries

CONFIG_SCHEMA = "jjv/review-config/v1"
EVENTS_SCHEMA = "jjv/events/v1"
CONFIG_NAME, EVENTS_NAME, SEGMENTS_NAME = "review-config.json", "events.json", "segments.json"
BOUNDARIES_SCHEMA = SKILL_ROOT / "schemas" / "boundaries.schema.json"
JSON_MODE = "utf8"


@dataclass(frozen=True)
class Built:
    config: dict
    events: dict
    warnings: list
    segments: dict | None = None   # segments.json (jjv/segments/v1), additive


def _relative(root: Path):
    def rel(path: Path) -> str:
        """Episode-relative POSIX path; an absolute path when none exists (another drive)."""
        try:
            return Path(os.path.relpath(Path(path).resolve(), root.resolve())).as_posix()
        except ValueError:
            return Path(path).resolve().as_posix()
    return rel


@dataclass(frozen=True)
class Prepared:
    """Everything validated before any audio/icon work: the declared table against the timeline."""
    ctx: sources.Context
    document: dict       # boundaries document (cards/plate filled in when the timeline is derived)
    timing: dict | None
    entries: dict
    cards: list
    timeline: Timeline
    rows: list           # resolved boundary rows (preset, frames, direction, params)
    derived: derive.Derived | None
    warnings: list
    fps: int


def prepare(config: ResolvedConfig, boundaries_path: Path, timing_path: Path | None, *,
            allow_outside: tuple = ()) -> Prepared:
    """Load + check the boundary table and build the timeline.  ``timing_path`` None reads the shot grid
    from shots.json instead of a word-timing document (the preset feasibility table needs no words)."""
    root = Path(config.episode_root)
    ctx = sources.Context(root=root, allow=tuple(allow_outside), rel=_relative(root))
    document = table.load_document(Path(boundaries_path), BOUNDARIES_SCHEMA, config.episode["episode_id"],
                                 config.domain)
    fps = config.domain["frame_rates"]["delivery_fps"]
    timing = read_json(Path(timing_path)) if timing_path is not None else None
    if timing is not None and timing.get("fps") != fps:
        raise Refused(f"word timing fps {timing.get('fps')} != domain delivery fps {fps}")
    warnings: list = []
    derived = derive.plan(ctx, document, config, rules, warnings)
    if derived is not None:
        document = derived.document
    entries = captions.entries_by_id(timing) if timing is not None else synthetic_entries(config)
    cards = document.get("cards", [])
    plate = (document.get("ending") or {}).get("end_plate")
    timeline = build_timeline(config, entries, cards, rules, plate_start=plate["start"] if plate else None,
                              totals=derived.totals if derived else None)
    rows = table.check_table(document, timeline, cards, has_plate=plate is not None, warnings=warnings)
    return Prepared(ctx, document, timing, entries, cards, timeline, rows, derived, warnings, fps)


def build_review_config(config: ResolvedConfig, boundaries_path: Path, timing_path: Path, *,
                        probe=None, allow_outside: tuple = ()) -> Built:
    """Pure with respect to outputs: reads inputs, validates every rule, returns the documents."""
    root = Path(config.episode_root)
    rel = _relative(root)
    probe = probe or _probe_frames
    prep = prepare(config, boundaries_path, timing_path, allow_outside=allow_outside)
    ctx, document, timing, entries, cards = prep.ctx, prep.document, prep.timing, prep.entries, prep.cards
    timeline, rows, fps, warnings = prep.timeline, prep.rows, prep.fps, list(prep.warnings)
    review = (config.domain.get("delivery") or {}).get("review") or {}
    if not review.get("label"):
        raise Refused(f"domain {config.domain['domain_id']!r} has no delivery.review.label")
    captions.check_vocabulary_list(timing, document["icons"])
    silent_specs = {item["shot"]: item for item in document.get("expect_silent", [])}
    dialogue, bindings = sources.dialogue(ctx, timeline, entries, fps, silent_specs)
    card_rows, card_bindings = sources.cards(ctx, cards)
    icon_root = require_scoped(root / document["icons"]["dir"], root, ctx.allow, "icons.dir")
    icons, icon_warnings = captions.icon_events(
        [entries[row["id"]] for row in dialogue], document["icons"], icon_root, fps, rel,
        offsets={row["id"]: row["segments"][0]["audio"]["offset_frames"] for row in dialogue})
    warnings.extend(icon_warnings)
    records = table.build_transitions(rows, timeline, root, rel, probe, ctx.allow)
    ending = sources.ending(ctx, document, timeline, cards)
    if prep.derived is not None:
        ending = {**ending, "derived_timeline": prep.derived.summary}
    word_timing = {"path": shown_path(timing_path, root), "sha256": sha256_file(Path(timing_path)),
                   "schema": timing.get("schema"), "words": sum(len(row["words"]) for row in dialogue)}
    review_config: dict[str, Any] = {
        "schema": CONFIG_SCHEMA, "episode_id": config.episode["episode_id"], "fps": fps,
        "width": review.get("width"), "height": review.get("height"), "label": review["label"],
        "main_frames": timeline.main_frames, "end_hold_frames": timeline.end_card_frames,
        "total_frames": timeline.main_frames + timeline.end_card_frames,
        "inputs": {"config_sha256": config.config_sha256,
                   "boundaries_sha256": sha256_file(Path(boundaries_path)),
                   "word_timing_sha256": word_timing["sha256"]},
        "dialogue": dialogue, "outro_cards": card_rows, "wav_bindings": bindings + card_bindings,
        "word_timing": word_timing,
        "motion": {"transitions": records, "icons": icons, "ending": ending},
        "qa": {"av": {"reference_seconds": timeline.main_frames / fps}}}
    events = {
        "schema": EVENTS_SCHEMA, "fps": fps, "frames_label": f"GLOBAL frames @{fps} fps on the main film",
        "word_timing": word_timing, "transitions": records, "icon_events": icons,
        "icon_terms_covered": sorted({event["icon"] for event in icons}), "ending": ending,
        "karaoke_lines": [{"shot": row["id"], "start_frame": row["start_frame"], "words": len(row["words"]),
                           "first_word_frame": row["words"][0]["startF"],
                           "last_word_frame": row["words"][-1]["startF"]} for row in dialogue]}
    cut_list = segment_plan.from_build(episode_id=config.episode["episode_id"], timeline=timeline, records=records,
                                       cards=cards, ending=ending, icons=icons)
    return Built(review_config, events, warnings, cut_list)


def feasibility_report(config: ResolvedConfig, boundaries_path: Path, timing_path: Path | None = None, *,
                       probe=None, allow_outside: tuple = (), only: str | None = None) -> dict:
    """``jjv editorial presets``: per boundary, which presets its existing tail handle allows.  Read-only:
    no audio is measured and nothing is rendered, requested or written."""
    prep = prepare(config, boundaries_path, timing_path, allow_outside=allow_outside)
    root = Path(config.episode_root)
    boundaries = table.feasibility_table(prep.rows, prep.timeline, root, _relative(root), probe or _probe_frames,
                                         prep.ctx.allow, only)
    return {"episode_id": config.episode["episode_id"], "fps": prep.fps, "native_fps": prep.timeline.native_fps,
            "rule": "tail needs ceil(0.8 x N) native frames beyond the editorial cut; no GPU work is requested",
            "warnings": prep.warnings, "boundaries": boundaries}


def _probe_frames(clip: Path) -> int:
    info = probe_video(clip, count_packets=True)
    if info.frames is None:
        raise Refused(f"cannot count frames of {clip}")
    return info.frames


def write_outputs(built: Built, out_dir: Path, *, dry_run: bool) -> dict:
    """Write the documents once (never overwrite a different file); ``dry_run`` only hashes."""
    summary: dict[str, Any] = {}
    documents = [(CONFIG_NAME, built.config), (EVENTS_NAME, built.events)]
    if built.segments is not None:
        documents.append((SEGMENTS_NAME, built.segments))
    payloads = [(name, pretty_json(document, mode=JSON_MODE)) for name, document in documents]
    for name, payload in payloads:  # refuse before writing anything if either target differs
        target = Path(out_dir) / name
        if target.exists() and (not target.is_file() or target.read_bytes() != payload):
            raise Refused(f"refusing to overwrite {target}: it differs from the rebuilt document")
    for name, payload in payloads:
        target = Path(out_dir) / name
        if not dry_run:
            write_once(target, payload)
        summary[name] = {"path": str(target), "sha256": sha256_bytes(payload), "bytes": len(payload),
                         "written": not dry_run}
    return summary
