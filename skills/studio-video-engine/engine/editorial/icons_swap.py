"""``jjv icons set TERM --png NEW.png``: an icon swap as data, plus the list of what must be re-composited.

The swap writes registry version N+1 (version N stays in ``versions/``) and touches nothing else: no shot
clip, no H3, no SeedVR2.  The report names the icon events, outro cards and (when a segment table is
available) the segments whose COMPOSITE must be re-rendered; every other segment keeps its bytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from . import icons as reg
from . import segments as seg
from .icons_check import MaskFn, MeasureFn, validate_registry


def resolve_icon_id(registry: dict, key: str) -> str:
    """An icon id, a spoken term/alias or an outro card term -> the icon id it names."""
    if key in registry["icons"]:
        return key
    if reg.slug(key) in registry["icons"]:
        return reg.slug(key)
    found = reg.term_lookup(registry).get(reg.norm(key))
    if found is not None:
        return registry["terms"][found]["icon"]
    if key in registry["cards"]:
        return registry["cards"][key]["icon"]
    raise Refused(f"no icon, spoken word or card named {key!r} in the registry (icons: {sorted(registry['icons'])})")


def set_icon(registry: dict, key: str, new_png: Path, *, root: Path, recipe: dict, recipe_sha: str, ffmpeg: str,
             status: str = "candidate", attribute: str | None = None, measure_fn: MeasureFn = reg.measure,
             mask_fn: MaskFn = reg.silhouette) -> tuple[dict, dict]:
    """(new registry, change record).  Any gate error on the result is Refused and nothing is returned."""
    icon_id = resolve_icon_id(registry, key)
    old = registry["icons"][icon_id]
    new_png = Path(new_png)
    if not new_png.is_file():
        raise Refused(f"{new_png} does not exist")
    digest = sha256_file(new_png)
    if digest == old["sha256"]:
        raise Refused(f"{new_png.name} is the image icon {icon_id!r} already uses (sha256 {digest[:12]}): nothing to change")
    if status not in recipe["statuses"]:
        raise Refused(f"status must be one of {recipe['statuses']}")
    facts = measure_fn(new_png, recipe, ffmpeg)
    entry = {**old, "file": new_png.name, "png": reg.episode_relative(new_png, root), "sha256": digest,
             "bytes": new_png.stat().st_size, "size": facts["size"], "palette": facts["palette"],
             "attribute": attribute if attribute is not None else old.get("attribute"),
             "status": status, "approved": status == "approved", "source_status": "REPLACED_BY_SET"}
    version = registry["version"] + 1
    change = {"version": version, "action": "set", "icon": icon_id, "old": {"png": old["png"], "sha256": old["sha256"]},
              "new": {"png": entry["png"], "sha256": digest}}
    candidate = reg.sealed({
        **{k: v for k, v in registry.items() if k not in ("sha256", "history")},
        "version": version, "previous": {"version": registry["version"], "sha256": registry["sha256"]},
        "recipe": {"id": recipe["id"], "sha256": recipe_sha},
        "icons": {**registry["icons"], icon_id: entry}, "history": [*registry["history"], change]})
    report = validate_registry(candidate, root=root, recipe=recipe, ffmpeg=ffmpeg, measure_fn=measure_fn, mask_fn=mask_fn)
    if not report["ok"]:
        listing = "; ".join(f"{e['code']}: {e['message']}" for e in report["errors"])
        raise Refused(f"the swap would break the registry, nothing written: {listing}")
    words = sorted(w for w, row in registry["terms"].items() if row["icon"] == icon_id)
    cards = sorted(c for c, row in registry["cards"].items() if row["icon"] == icon_id)
    return candidate, {**change, "words": words, "cards": cards, "validation": report["summary"],
                       "warnings": report["warnings"]}


def segments_from_review_config(config: dict) -> dict:
    """The segment table a review config implies (what ``build-config`` would write), for configs built
    without ``segments.json``.  Same function as the engine's own cut list (``segments.plan_segments``)."""
    dialogue = config["dialogue"]
    main = config["main_frames"]
    end = config.get("end_hold_frames", 0)
    ending = (config.get("motion") or {}).get("ending") or {}
    records = config["motion"]["transitions"]
    plate = (ending.get("end_plate") or {}).get("start")
    cards = [{"term": c["term"], "start": c["start_frame"], "frames": c["duration_frames"]} for c in config["outro_cards"]]
    return seg.plan_segments(
        fps=config["fps"], total_frames=main + end, main_frames=main, intro_end=dialogue[0]["start_frame"],
        dialogue_end=dialogue[-1]["end_frame_exclusive"],
        shots=[{"id": d["id"], "start": d["start_frame"], "end": d["end_frame_exclusive"]} for d in dialogue],
        transitions=records, cards=cards, plate_start=plate, join_frame=seg.join_frame_of(records, ending),
        icons=(config["motion"].get("icons") or []), episode_id=config.get("episode_id"))


def affected(old: dict, change_cards: list[str], *, events: list[dict], config: dict | None,
             segments: dict | None) -> dict:
    """What the swap of icon ``old`` (its registry entry BEFORE the swap) re-composites."""
    hits = [e for e in events if e.get("icon_sha256") == old["sha256"] or e.get("icon") == old["file"]
            or Path(str(e.get("icon_path", ""))).name == old["file"]]
    spans = [{"event": e["id"], "shot": e.get("shot"), "start": e["frame"], "end_exclusive": e["frame"] + e["total_frames"]}
             for e in hits]
    card_spans = []
    for card in (config or {}).get("outro_cards", []):
        icon = card.get("icon") or {}
        if card["term"] in change_cards or icon.get("sha256") == old["sha256"]:
            card_spans.append({"card": card["term"], "start": card["start_frame"],
                               "end_exclusive": card["start_frame"] + card["duration_frames"]})
    windows = [(s["start"], s["end_exclusive"]) for s in (*spans, *card_spans)]
    rows: list[Any] | None = None
    if segments is not None:
        rows = [s["id"] for s in segments["segments"] if any(seg._overlap(s["start"], s["end_exclusive"], a, b)  # noqa: SLF001
                                                              for a, b in windows)]
    frames = sum(b - a for a, b in windows)
    return {"icon_events": spans, "cards": card_spans, "segments": rows,
            "segments_total": None if segments is None else len(segments["segments"]),
            "composite_frames_hint": frames, "shot_sources_changed": False}


def read_optional(path: str | None) -> dict | None:
    return read_json(Path(path)) if path else None
