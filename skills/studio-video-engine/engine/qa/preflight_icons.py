"""Preflight icons: the FILE-level half of Q2, no video needed.

* every spoken vocabulary term (an anchor word of the dialogue, and every part of an outro card term) has an icon
  event within ``frame_tolerance`` frames of the word, whose icon file exists and hashes to the event's sha256
  (``q2_icons.coverage`` / ``check_files``);
* the opposite pairs (review recipe ``q2_icons.opposite_pairs``, e.g. warm/cold) are DIFFERENT PNGs whose mean
  colour (delta E) and hue are distinct (``q2_icons.check_pairs`` with no on-screen tiles: file level only);
* two different words may not share one image unless the event says ``shared_icon: true`` (T-E44 registry rule).

``icons_dir`` (``--icons``) is the fallback folder for an event whose declared ``icon_path`` is not on disk
(matched by file name).  No pixel of any render is read.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from .gates import FAIL, PASS, UNCERTAIN, q2_icons
from .preflight_segments import resolve
from .review_model import Model


def with_icon_dir(model: Model, icons_dir: Path | None, root: Path) -> Model:
    """Point every event whose icon file is missing at ``icons_dir/<file name>``."""
    if icons_dir is None:
        return model
    rows = []
    for event in model.icons:
        declared = resolve(event.get("icon_path"), root)
        if declared is None or not declared.is_file():
            name = Path(str(event.get("icon_path") or event.get("icon") or "")).name
            event = {**event, "icon_path": str(Path(icons_dir) / name)}
        rows.append(event)
    return dataclasses.replace(model, icons=tuple(rows))


def _shared_files(model: Model, files: dict[str, dict], opposite: set[tuple[str, str]]) -> list[str]:
    by_sha: dict[str, set[str]] = {}
    for info in files.values():
        for event_id in info["events"]:
            event = next(e for e in model.icons if e.get("id") == event_id)
            if not event.get("shared_icon"):
                by_sha.setdefault(info["sha256"], set()).add(q2_icons.stem(event.get("word")))
    out = []
    for sha, stems in sorted(by_sha.items()):
        names = sorted(stems)
        pairs = {tuple(sorted((a, b))) for a in names for b in names if a < b}
        if len(names) > 1 and not pairs <= opposite:
            out.append(f"words {names} share one icon image (sha {sha[:12]}): one icon per word "
                       "(mark an intentional shared icon with shared_icon: true)")
    return out


def run(model: Model, recipe: dict, pre: dict, root: Path, ffmpeg: str, icons_dir: Path | None = None) -> dict:
    p = recipe["q2_icons"]
    model = with_icon_dir(model, icons_dir, root)
    if not model.icons or not model.words:
        return {"gate": "ICONS", "status": UNCERTAIN, "failures": [],
                "note": "no icon events or no dialogue words in the config: nothing to check"}
    try:
        cover, anchors, orphans = q2_icons.coverage(model, p["frame_tolerance"])
        file_fail, files = q2_icons.check_files(model, root, ffmpeg, p)
    except (KeyError, TypeError) as error:
        raise Refused(f"icon event or dialogue word row is malformed ({type(error).__name__}: {error})") from error
    pair_fail, pairs = q2_icons.check_pairs(model, files, {}, p)
    for row in pairs:
        row.pop("screen", None)
    opposite = {tuple(sorted((q2_icons.stem(a), q2_icons.stem(b)))) for a, b in p["opposite_pairs"]}
    shared = _shared_files(model, files, opposite) if pre["icons"]["distinct_words_need_distinct_files"] else []
    failures = cover + file_fail + pair_fail + shared
    return {"gate": "ICONS", "status": FAIL if failures else PASS, "failures": failures, "anchors_checked": len(anchors),
            "events": len(model.icons), "orphan_events": orphans, "pairs": pairs, "shared_icon_words": shared,
            "icons": {v["name"]: {k: v[k] for k in ("sha256", "rgb", "hue", "saturation")} for v in files.values()},
            "params": {k: p[k] for k in ("frame_tolerance", "min_delta_e_file", "min_hue_distance_deg")}}
