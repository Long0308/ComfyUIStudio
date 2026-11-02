"""Derive the SFX cue sheet from the shot actions plus the transition / ending / vocabulary plan.

Cue classes are DATA (``recipe.cue_classes``):

* ``keyword``    a regex over the shot-action text; a negation word in the 40 characters before the match
                 drops it ("no pouring" never makes a pour cue); the placement is the shot start + ``offset_s``.
* ``icon``       one cue per icon event of the review config (``motion.icons[].frame``).
* ``card``       one cue per outro card start (``outro_cards[].start_frame``).
* ``transition`` one cue per transition of a listed type (``motion.transitions[]``, at ``start`` - ``lead_frames``).
* ``anchor``     a frame read from a dotted path of the review config (+ ``offset_frames``), e.g. the logo reveal.
* ``bed``        one looped placement over the whole film (optional classes only with ``include_optional``).

Text-derived cues carry the matched ``evidence`` so a reviewer can accept or strike each one.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.errors import Refused

NEGATION_WINDOW = 40


def _dotted(document: Any, path: str) -> Any:
    node = document
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def shot_starts(review_config: dict) -> dict[str, int]:
    rows = review_config.get("dialogue")
    if not isinstance(rows, list):
        raise Refused("review config has no dialogue[] (shot start frames are needed for text-derived cues)")
    return {str(r["id"]): int(r["start_frame"]) for r in rows if isinstance(r, dict) and "id" in r and "start_frame" in r}


def shot_lengths(review_config: dict) -> dict[str, int]:
    return {str(r["id"]): int(r["duration_frames"]) for r in review_config.get("dialogue", [])
            if isinstance(r, dict) and "id" in r and "duration_frames" in r}


def keyword_cues(name: str, cls: dict, texts: dict[str, str], starts: dict[str, int], fps: int,
                 negations: re.Pattern, skipped: list[dict], lengths: dict[str, int]) -> list[dict]:
    pattern = re.compile(r"\b(?:" + "|".join(cls.get("keywords", [])) + r")\b", re.IGNORECASE) if cls.get("keywords") else None
    found = []
    for shot in sorted(texts):
        text = texts[shot]
        matches = list(pattern.finditer(text)) if pattern else []
        if not matches:
            continue
        if shot not in starts:
            skipped.append({"class": name, "shot": shot, "reason": "shot has no start frame in the review config"})
            continue
        accepted = []
        for match in matches if cls.get("repeat") else matches[:1]:
            before = text[max(0, match.start() - NEGATION_WINDOW):match.start()]
            evidence = text[max(0, match.start() - 30):match.end() + 30].strip()
            if negations.search(before):
                skipped.append({"class": name, "shot": shot, "reason": "negated in the shot text", "evidence": evidence})
            else:
                accepted.append(evidence)
        for index, evidence in enumerate(accepted):
            offset = round((cls.get("offset_s", 0.0) + index * cls.get("repeat_gap_s", 0.7)) * fps)
            row = {"shot": shot, "frame": starts[shot] + offset, "source": "keyword", "action": evidence}
            if cls.get("span") == "shot" and shot in lengths:
                row["duration_s"] = max(0.1, (lengths[shot] - offset) / fps)
            found.append(row)
    return found


def event_cues(name: str, cls: dict, review_config: dict, total: int, skipped: list[dict]) -> list[dict]:
    event, motion = cls["event"], review_config.get("motion") or {}
    if event == "icon":
        return [{"shot": e.get("shot"), "frame": int(e["frame"]), "source": "icon", "action": f"icon {e.get('word') or e.get('term')}"}
                for e in motion.get("icons", []) if "frame" in e]
    if event == "card":
        return [{"shot": "outro", "frame": int(c["start_frame"]), "source": "card", "action": f"vocabulary card {c.get('term')}"}
                for c in review_config.get("outro_cards", []) if "start_frame" in c]
    if event == "transition":
        lead = cls.get("lead_frames", 0)
        return [{"shot": t.get("to"), "frame": max(0, int(t["start"]) - lead), "source": "transition",
                 "action": f"{t.get('type')} {t.get('id')} {t.get('from')}->{t.get('to')}"}
                for t in motion.get("transitions", []) if t.get("type") in cls.get("types", []) and "start" in t]
    if event == "anchor":
        rows = []
        for anchor in cls.get("anchors", []):
            value = _dotted(review_config, anchor["path"])
            if isinstance(value, bool) or not isinstance(value, int):
                skipped.append({"class": name, "reason": f"anchor {anchor['path']} is not an integer frame in the review config"})
                continue
            rows.append({"shot": "anchor", "frame": value + int(anchor.get("offset_frames", 0)), "source": "anchor",
                         "action": f"{anchor['path']}={value}"})
        return rows
    if event == "bed":
        return [{"shot": "timeline", "frame": 0, "source": "bed", "action": "looped ambience bed over the whole film"}]
    return []


def manual_cue(item: dict, classes: dict, index: int, total: int, fps: int) -> dict:
    """A hand-added cue (``--extra-cues``): class, frame and the reason are mandatory and stay in the receipt."""
    name, frame, reason = item.get("class"), item.get("frame"), item.get("reason")
    if name not in classes or isinstance(frame, bool) or not isinstance(frame, int) or not 0 <= frame < total or not reason:
        raise Refused(f"extra cue {index}: needs a known class, a frame inside the film and a reason, got {item!r}")
    cls = classes[name]
    return {"cue_id": f"MANUAL-{name.upper()}-{index:02d}", "clip_id": f"sfx-{name}", "class": name,
            "shot": item.get("shot", "manual"), "frame": frame, "duration_s": cls["seconds"],
            "gain_db": item.get("gain_db", cls["gain_db"]), "pan": item.get("pan", cls.get("pan", 0.0)),
            "loop": bool(cls.get("loop")), "source": "manual", "action": f"MANUAL: {reason}"}


def derive(recipe: dict, review_config: dict, texts: dict[str, str], timeline: dict, *, include_optional: bool,
           extra: list[dict] | None = None) -> dict:
    """``{clips, placements, skipped}`` (see module doc).  Pure; no file or network access."""
    classes, fps, total = recipe["cue_classes"], timeline["fps"], timeline["total_frames"]
    words = recipe.get("negation_words") or []
    negations = re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b", re.IGNORECASE) if words else re.compile(r"(?!x)x")
    starts = shot_starts(review_config) if any(c.get("event", "keyword") == "keyword" for c in classes.values()) else {}
    lengths = shot_lengths(review_config)
    skipped: list[dict] = []
    placements: list[dict] = []
    for name in sorted(classes):
        cls = classes[name]
        if cls.get("optional") and not include_optional:
            continue
        kind = cls.get("event", "keyword")
        rows = (keyword_cues(name, cls, texts, starts, fps, negations, skipped, lengths) if kind == "keyword"
                else event_cues(name, cls, review_config, total, skipped))
        for index, row in enumerate(sorted(rows, key=lambda r: r["frame"]), start=1):
            if not 0 <= row["frame"] < total:
                skipped.append({"class": name, "shot": row["shot"], "reason": f"frame {row['frame']} outside the film"})
                continue
            seconds = timeline["duration_s"] if kind == "bed" else row.get("duration_s", cls["seconds"])
            placements.append({"cue_id": f"{name.upper()}-{index:02d}", "clip_id": f"sfx-{name}", "class": name,
                               "shot": row["shot"], "frame": row["frame"], "duration_s": round(seconds, 6),
                               "gain_db": cls["gain_db"], "pan": cls.get("pan", 0.0),
                               "loop": bool(cls.get("loop")) or "duration_s" in row,
                               "source": row["source"], "action": row["action"]})
    for index, item in enumerate(extra or [], start=1):
        placements.append(manual_cue(item, classes, index, total, fps))
    covered = {p["shot"] for p in placements if p["source"] in ("keyword", "manual")} | {k["shot"] for k in skipped if k.get("shot")}
    uncovered = sorted(shot for shot in texts if shot not in covered)
    names = sorted({p["class"] for p in placements})
    order = {name: index for index, name in enumerate(sorted(classes))}
    clips = [{"clip_id": f"sfx-{name}", "class": name, "prompt": classes[name]["prompt"], "seconds": classes[name]["seconds"],
              "seed": recipe["seed_base"] + order[name], "loop": bool(classes[name].get("loop"))} for name in names]
    return {"clips": clips, "placements": sorted(placements, key=lambda p: (p["frame"], p["cue_id"])), "skipped": skipped,
            "uncovered_shots": uncovered}
